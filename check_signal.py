"""Check whether a scanner signal reached target or stop-loss after entry."""

import argparse
import datetime
import json
import os
import zoneinfo

import requests
import yfinance as yf
from dotenv import load_dotenv


IST = zoneinfo.ZoneInfo("Asia/Kolkata")
SETUP_START = datetime.time(9, 15)
COIL_END = datetime.time(10, 30)
CUTOFF = datetime.time(14, 30)
TARGET_PCT = 0.01
STATE_FILE = "alerted_today.json"

load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check a 15-minute inside-bar signal after the trading day."
    )
    parser.add_argument("symbol", nargs="?", help="NSE symbol, for example EICHERMOT")
    parser.add_argument(
        "date",
        nargs="?",
        help="Signal date in YYYY-MM-DD format, for example 2026-08-26",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Check every signal recorded in alerted_today.json and send a Telegram report",
    )
    return parser.parse_args()


def parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise SystemExit("Date must use YYYY-MM-DD format")


def fetch_day(symbol, trade_date):
    start = datetime.datetime.combine(trade_date, datetime.time.min, tzinfo=IST)
    end = start + datetime.timedelta(days=1)
    df = yf.download(
        f"{symbol.upper()}.NS",
        start=start,
        end=end,
        interval="15m",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df.empty:
        return None
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    if df.index.tz is None:
        df.index = df.index.tz_localize(IST)
    else:
        df.index = df.index.tz_convert(IST)
    return df


def find_signal(df):
    candles = df[df.index.time >= SETUP_START]
    candles = candles[candles.index.time <= CUTOFF]
    if len(candles) < 6:
        return None

    candle1 = candles.iloc[0]
    coil = candles.iloc[1:5]
    if any(c["High"] > candle1["High"] or c["Low"] < candle1["Low"] for _, c in coil.iterrows()):
        return None

    for timestamp, candle in candles.iloc[5:].iterrows():
        if candle["Close"] > candle1["High"]:
            return "BUY", timestamp, candle, candle1, candles.loc[timestamp:]
        if candle["Close"] < candle1["Low"]:
            return "SELL", timestamp, candle, candle1, candles.loc[timestamp:]
    return None


def check_outcome(direction, breakout_time, breakout, candle1, df):
    entry = float(breakout["Close"])
    target = entry * (1 + TARGET_PCT) if direction == "BUY" else entry * (1 - TARGET_PCT)
    stop = float(candle1["Low"] if direction == "BUY" else candle1["High"])
    return check_outcome_levels(direction, breakout_time, entry, target, stop, df)


def check_outcome_levels(direction, breakout_time, entry, target, stop, df):
    after_entry = df[df.index > breakout_time]

    for timestamp, candle in after_entry.iterrows():
        hit_target = candle["High"] >= target if direction == "BUY" else candle["Low"] <= target
        hit_stop = candle["Low"] <= stop if direction == "BUY" else candle["High"] >= stop
        if hit_target and hit_stop:
            return "AMBIGUOUS: target and stop touched in the same candle", timestamp, entry, target, stop
        if hit_target:
            return "TARGET HIT", timestamp, entry, target, stop
        if hit_stop:
            return "STOP-LOSS HIT", timestamp, entry, target, stop

    return "OPEN AT DAY CLOSE", None, entry, target, stop


def check_symbol(symbol, trade_date):
    df = fetch_day(symbol, trade_date)
    if df is None:
        return f"{symbol.upper()} | Date {trade_date} | No 15-minute data found"

    signal = find_signal(df)
    if signal is None:
        return f"{symbol.upper()} | Date {trade_date} | No valid inside-bar breakout found"

    direction, breakout_time, breakout, candle1, _ = signal
    outcome, outcome_time, entry, target, stop = check_outcome(
        direction, breakout_time, breakout, candle1, df
    )
    result_time = "" if outcome_time is None else f" at {outcome_time.strftime('%H:%M')} IST"
    return (
        f"{symbol.upper()} | Date {trade_date} | {direction} | "
        f"Breakout {breakout_time.strftime('%H:%M')} IST | "
        f"Entry ₹{entry:.2f} | Target ₹{target:.2f} | Stop ₹{stop:.2f} | "
        f"{outcome}{result_time}"
    )


def check_stored_signal(signal, trade_date):
    symbol = signal["symbol"].upper()
    df = fetch_day(symbol, trade_date)
    if df is None:
        return f"{symbol} | Date {trade_date} | No 15-minute data found"

    breakout_time = datetime.datetime.combine(
        trade_date,
        datetime.time.fromisoformat(signal["breakout_time"]),
        tzinfo=IST,
    )
    outcome, outcome_time, entry, target, stop = check_outcome_levels(
        signal["direction"],
        breakout_time,
        float(signal["entry"]),
        float(signal["target"]),
        float(signal["stop"]),
        df,
    )
    result_time = "" if outcome_time is None else f" at {outcome_time.strftime('%H:%M')} IST"
    return (
        f"{symbol} | Date {trade_date} | {signal['direction']} | "
        f"Breakout {signal['breakout_time']} IST | "
        f"Entry ₹{entry:.2f} | Target ₹{target:.2f} | Stop ₹{stop:.2f} | "
        f"{outcome}{result_time}"
    )


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram credentials not configured; skipping report send.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    lines = text.splitlines()
    chunks = []
    current = []
    current_length = 0
    for line in lines:
        line_length = len(line) + (1 if current else 0)
        if current and current_length + line_length > 3900:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += len(line) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append("\n".join(current))

    for chunk in chunks:
        try:
            response = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "text": chunk},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[ERROR] Telegram send failed: {exc}")
            return False
    return True


def run_report(trade_date):
    if not os.path.exists(STATE_FILE):
        print(f"[WARN] {STATE_FILE} was not found; skipping report for {trade_date.isoformat()}.")
        return

    try:
        with open(STATE_FILE) as state_file:
            state = json.load(state_file)
    except (OSError, ValueError) as exc:
        print(f"[WARN] Could not read {STATE_FILE}: {exc}; skipping report.")
        return

    records = state.get("signals") or []
    symbols = state.get("alerted") or []
    if state.get("date") != trade_date.isoformat():
        records = []
        symbols = []

    lines = [
        f"15-MIN SIGNAL REPORT | {trade_date.strftime('%d-%b-%Y')} | 04:00 PM IST",
        "",
    ]
    if records:
        lines.extend(check_stored_signal(record, trade_date) for record in records)
    elif symbols:
        lines.extend(check_symbol(symbol, trade_date) for symbol in symbols)
    else:
        lines.append("No signals were generated today.")

    if send_telegram("\n".join(lines)):
        print(f"Sent Telegram report for {len(records) or len(symbols)} signal(s).")
    else:
        print("Telegram report skipped because sending failed or credentials were missing.")


def main():
    args = parse_args()
    if args.report:
        trade_date = parse_date(args.date or datetime.datetime.now(IST).date().isoformat())
        run_report(trade_date)
        return

    if not args.symbol or not args.date:
        raise SystemExit("Provide SYMBOL DATE, or use --report")
    trade_date = parse_date(args.date)

    print(check_symbol(args.symbol, trade_date))


if __name__ == "__main__":
    main()