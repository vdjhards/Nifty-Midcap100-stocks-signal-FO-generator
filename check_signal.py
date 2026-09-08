"""Check whether a scanner signal reached target or stop-loss after entry."""

import argparse
import datetime
import zoneinfo

import yfinance as yf


IST = zoneinfo.ZoneInfo("Asia/Kolkata")
SETUP_START = datetime.time(9, 15)
COIL_END = datetime.time(10, 30)
CUTOFF = datetime.time(14, 30)
TARGET_PCT = 0.01


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check a 15-minute inside-bar signal after the trading day."
    )
    parser.add_argument("symbol", help="NSE symbol, for example EICHERMOT")
    parser.add_argument(
        "date",
        help="Signal date in YYYY-MM-DD format, for example 2026-08-26",
    )
    return parser.parse_args()


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


def main():
    args = parse_args()
    try:
        trade_date = datetime.date.fromisoformat(args.date)
    except ValueError:
        raise SystemExit("Date must use YYYY-MM-DD format")

    df = fetch_day(args.symbol, trade_date)
    if df is None:
        raise SystemExit(f"No 15-minute data found for {args.symbol.upper()} on {args.date}")

    signal = find_signal(df)
    if signal is None:
        raise SystemExit("No valid inside-bar breakout found for that symbol and date")

    direction, breakout_time, breakout, candle1, _ = signal
    outcome, outcome_time, entry, target, stop = check_outcome(
        direction, breakout_time, breakout, candle1, df
    )

    print(f"{args.symbol.upper()} | {trade_date} | {direction}")
    print(f"Breakout: {breakout_time.strftime('%H:%M')} IST")
    print(f"Entry: ₹{entry:.2f} | Target: ₹{target:.2f} | Stop-loss: ₹{stop:.2f}")
    if outcome_time is None:
        print(f"Result: {outcome}")
    else:
        print(f"Result: {outcome} at {outcome_time.strftime('%H:%M')} IST")


if __name__ == "__main__":
    main()