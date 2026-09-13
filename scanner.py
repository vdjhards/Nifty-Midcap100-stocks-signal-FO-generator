"""
15-Minute Inside-Bar Setup Scanner — Nifty Midcap 100
------------------------------------------------
Pattern:
  - Candle 1 (9:15-9:30 IST) sets the reference range (high/low).
  - Candles 2-5 (9:30-10:30 IST) must stay fully inside Candle 1's range.
    - From 10:30 IST onward until 14:30 IST, checked every run, whichever side (high/low)
    the price closes beyond triggers a signal (BUY on high break, SELL on low break).
  - Target = 1% from entry. SL = Candle 1's opposite extreme.
  - A rule-based confidence score (0-100) is computed per signal.

Data source: yfinance (15m interval, NSE tickers suffixed with .NS)
Output: Telegram message via Bot API (colors as emoji, date+time included)

NOTE: This script is designed to be run repeatedly (e.g. every 15 min from
10:30 to 14:30 IST) via GitHub Actions cron. It tracks which stocks have
ALREADY been alerted today (via a simple local state file) so the same
stock isn't alerted twice in one day.
"""

import os
import json
import csv
import io
import argparse
import datetime
import zoneinfo
import requests
import yfinance as yf
from dotenv import load_dotenv

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

STATE_FILE = "alerted_today.json"
UNIVERSE_FILE = "nifty_midcap100_symbols.json"
NIFTY_MIDCAP100_CSV_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap100list.csv"
NSE_NIFTY_MIDCAP100_CSV_URL = "https://archives.nseindia.com/content/indices/ind_niftymidcap100list.csv"

# Setup window boundaries (IST, naive HH:MM for comparison)
SETUP_START = datetime.time(9, 15)
COIL_END = datetime.time(10, 30)   # after candle 5 closes
CUTOFF = datetime.time(14, 30)     # stop looking for fresh breakouts after this

TARGET_PCT = 0.01  # 1%


def fetch_nifty_midcap100_symbols():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv",
        "Referer": "https://www.niftyindices.com/",
    }
    last_error = None
    for url in (NIFTY_MIDCAP100_CSV_URL, NSE_NIFTY_MIDCAP100_CSV_URL):
        for _ in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=20)
                response.raise_for_status()
                if response.content.lstrip().startswith(b"<"):
                    raise ValueError("official site returned HTML instead of the constituent CSV")
                break
            except (requests.RequestException, ValueError) as e:
                last_error = e
        else:
            continue
        break
    else:
        raise RuntimeError(f"Nifty Midcap 100 CSV unavailable from official sources: {last_error}")

    rows = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
    symbols = [row["Symbol"].strip() for row in rows if row.get("Symbol")]
    if len(symbols) != 100 or len(set(symbols)) != 100:
        raise ValueError(f"Expected 100 unique Nifty Midcap 100 symbols, received {len(symbols)}")
    return symbols


def save_nifty_midcap100_symbols(symbols):
    with open(UNIVERSE_FILE, "w") as f:
        json.dump(symbols, f)


def load_nifty_midcap100_symbols(force_refresh=False):
    if force_refresh:
        symbols = fetch_nifty_midcap100_symbols()
        save_nifty_midcap100_symbols(symbols)
        print(f"Saved latest Nifty Midcap 100 universe ({len(symbols)} symbols).")
        return symbols

    if os.path.exists(UNIVERSE_FILE):
        with open(UNIVERSE_FILE) as f:
            symbols = json.load(f)
        if len(symbols) == 100 and len(set(symbols)) == 100:
            return symbols

    symbols = fetch_nifty_midcap100_symbols()
    save_nifty_midcap100_symbols(symbols)
    return symbols

def load_state():
    today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            data.setdefault("signals", [])
            return data
    return {"date": today, "alerted": [], "signals": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def fetch_intraday(symbol):
    """Fetch today's 15m candles for a stock. Returns a DataFrame or None."""
    ticker = f"{symbol}.NS"
    try:
        df = yf.Ticker(ticker).history(period="1d", interval="15m")
        if df.empty:
            return None
        df.index = df.index.tz_convert(IST)
        return df
    except Exception as e:
        print(f"[WARN] Failed to fetch {symbol}: {e}")
        return None


def get_setup_candles(df):
    """
    Extract Candle 1 and Candles 2-5 (the coil) from today's data.
    Returns (candle1, coil_candles_list, breakout_candles_df) or None if not enough data yet.
    """
    today_candles = df[df.index.time >= SETUP_START]
    if len(today_candles) < 5:
        return None  # not enough candles yet today

    candle1 = today_candles.iloc[0]
    coil = today_candles.iloc[1:5]
    breakout_candidates = today_candles.iloc[5:]  # candles from 10:30 onward
    return candle1, coil, breakout_candidates


def is_contained(coil, candle1):
    """Check that every coil candle's high/low stayed inside candle1's range."""
    for _, c in coil.iterrows():
        if c["High"] > candle1["High"] or c["Low"] < candle1["Low"]:
            return False
    return True


def check_breakout(candle1, breakout_candidates, cutoff_time):
    """
    Look through breakout candidate candles (10:30 onward) for the FIRST
    candle whose CLOSE breaks beyond candle1's high or low.
    Returns (direction, breakout_candle) or (None, None).
    """
    for ts, c in breakout_candidates.iterrows():
        if ts.time() > cutoff_time:
            break
        if c["Close"] > candle1["High"]:
            return "BUY", c
        if c["Close"] < candle1["Low"]:
            return "SELL", c
    return None, None


def compute_confidence(candle1, coil, breakout_candle, direction, df):
    """
    Rule-based 0-100 confidence score. Returns (score, checklist_lines).
    Factors:
      - Coil tightness: coil's own high-low range vs candle1's range (smaller = better)
      - Candle1 size vs stock's recent average 15m range
      - Breakout close strength (already guaranteed close-beyond by check_breakout)
      - Breakout volume vs average coil volume
      - Risk:Reward ratio
    """
    lines = []
    score = 0

    candle1_range = candle1["High"] - candle1["Low"]

    # 1. Coil tightness (0-25 pts)
    coil_high = coil["High"].max()
    coil_low = coil["Low"].min()
    coil_range = coil_high - coil_low
    tightness_ratio = coil_range / candle1_range if candle1_range > 0 else 1
    if tightness_ratio <= 0.5:
        score += 25
        lines.append(f"✅ Coil used only {tightness_ratio*100:.0f}% of Candle 1's range — tight consolidation")
    elif tightness_ratio <= 0.75:
        score += 12
        lines.append(f"⚠️ Coil used {tightness_ratio*100:.0f}% of Candle 1's range — moderate")
    else:
        lines.append(f"❌ Coil used {tightness_ratio*100:.0f}% of Candle 1's range — loose, weak consolidation")

    # 2. Candle 1 size vs recent average 15m range (0-20 pts)
    recent = df.tail(30)  # roughly last few days of 15m candles available
    avg_range = (recent["High"] - recent["Low"]).mean()
    if avg_range > 0 and candle1_range >= avg_range:
        score += 20
        lines.append("✅ Candle 1 range is at/above this stock's recent 15m average — a real move")
    else:
        lines.append("⚠️ Candle 1 range is below this stock's recent 15m average — smaller base")

    # 3. Breakout close strength (0-20 pts) — already close-beyond by construction
    score += 20
    lines.append("✅ Breakout candle CLOSED beyond the high/low, not just a wick")

    # 4. Breakout volume vs coil average (0-20 pts)
    coil_avg_vol = coil["Volume"].mean()
    if coil_avg_vol > 0 and breakout_candle["Volume"] >= 1.3 * coil_avg_vol:
        score += 20
        lines.append(f"✅ Breakout volume is {breakout_candle['Volume']/coil_avg_vol:.1f}x the coil average — strong conviction")
    else:
        lines.append("⚠️ Breakout volume not meaningfully higher than the coil average")

    # 5. Risk:Reward (0-15 pts)
    entry = breakout_candle["Close"]
    if direction == "BUY":
        sl_distance_pct = (entry - candle1["Low"]) / entry
    else:
        sl_distance_pct = (candle1["High"] - entry) / entry
    if sl_distance_pct <= TARGET_PCT:
        score += 15
        lines.append(f"✅ Risk:Reward favorable — SL distance {sl_distance_pct*100:.2f}% vs {TARGET_PCT*100:.0f}% target")
    else:
        lines.append(f"❌ Risk:Reward unfavorable — SL distance {sl_distance_pct*100:.2f}% vs {TARGET_PCT*100:.0f}% target")

    return score, lines, sl_distance_pct


def format_candle_line(label, ts, c):
    return f"{label} ({ts.strftime('%H:%M')})  O:{c['Open']:.2f} H:{c['High']:.2f} L:{c['Low']:.2f} C:{c['Close']:.2f}"


def build_analysis_guide(direction, entry, target, sl, score):
    risk = abs(entry - sl)
    reward = abs(target - entry)
    risk_reward = reward / risk if risk else 0
    breakout_side = "above" if direction == "BUY" else "below"
    return [
        "",
        "── How to Read and Analyze ──",
        f"1. Meaning: price closed {breakout_side} Candle 1's range, confirming a {direction} breakout.",
        f"2. Score: {score}/100 — 75+ is stronger, 50-74 needs caution, below 50 is weak.",
        f"3. Entry: ₹{entry:.2f} — avoid chasing if price has moved far {breakout_side} this level.",
        f"4. Risk first: ₹{abs(entry - sl):.2f} per share to the fixed stop at ₹{sl:.2f}; never widen it.",
        f"5. Reward: ₹{abs(target - entry):.2f} per share to the target at ₹{target:.2f}.",
        f"6. R/R: {risk_reward:.2f} — prefer 2.0 or higher when the chart allows it.",
        "7. Check the chart: nearby resistance/support, volume, spread, and overall market/sector trend.",
        "8. Position size: choose quantity from your maximum acceptable loss, not from the target.",
        "This is a rule-based setup, not a guarantee. Confirm the live chart before entering.",
    ]


def build_message(symbol, direction, candle1, coil, breakout_candle, score, checklist, sl_distance_pct):
    now = datetime.datetime.now(IST)
    date_str = now.strftime("%d-%b-%Y")
    time_str = now.strftime("%I:%M %p IST")

    color = "🟢" if direction == "BUY" else "🔴"
    entry = breakout_candle["Close"]
    if direction == "BUY":
        target = entry * (1 + TARGET_PCT)
        sl = candle1["Low"]
    else:
        target = entry * (1 - TARGET_PCT)
        sl = candle1["High"]

    verdict = "✅ STRONG SETUP" if score >= 75 else ("⚠️ CONSIDER WITH CAUTION" if score >= 50 else "❌ WEAK — LIKELY SKIP")

    msg = [
        f"{color} 15-MIN SETUP SIGNAL",
        "",
        f"📊 {symbol}",
        f"Direction: {color} {direction}",
        f"Date: {date_str}   Time: {time_str}",
        "",
        "── Candles ──",
        format_candle_line("C1", candle1.name, candle1),
    ]
    for i, (ts, c) in enumerate(coil.iterrows(), start=2):
        msg.append(format_candle_line(f"C{i}", ts, c))
    msg.append(format_candle_line("Breakout", breakout_candle.name, breakout_candle))
    msg.append("")
    msg.append("── Trade Levels ──")
    msg.append(f"Entry: ₹{entry:.2f}")
    msg.append(f"Target (1%): ₹{target:.2f}")
    msg.append(f"SL (Candle 1 {'Low' if direction == 'BUY' else 'High'}): ₹{sl:.2f}")
    msg.append(f"SL distance: {sl_distance_pct*100:.2f}%  vs  Target: {TARGET_PCT*100:.0f}%")
    msg.append("")
    msg.append(f"── Confidence Score: {score}/100 ──")
    msg.extend(checklist)
    msg.append("")
    msg.append(f"Verdict: {verdict}")
    msg.extend(build_analysis_guide(direction, entry, target, sl, score))

    return "\n".join(msg)


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram credentials not set — printing instead:\n")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"[ERROR] Telegram send failed: {e}")
        return False
    if resp.status_code != 200:
        print(f"[ERROR] Telegram send failed: {resp.text}")
        return False
    return True


def run():
    now_time = datetime.datetime.now(IST).time()
    if now_time < COIL_END:
        print("Before 10:30 IST — coil not yet complete. Exiting.")
        return

    nifty_midcap100_symbols = load_nifty_midcap100_symbols()
    state = load_state()
    signals = []

    for symbol in nifty_midcap100_symbols:
        if symbol in state["alerted"]:
            continue  # already alerted today

        df = fetch_intraday(symbol)
        if df is None:
            continue

        setup = get_setup_candles(df)
        if setup is None:
            continue
        candle1, coil, breakout_candidates = setup

        if not is_contained(coil, candle1):
            continue  # pattern didn't form

        direction, breakout_candle = check_breakout(candle1, breakout_candidates, CUTOFF)
        if direction is None:
            continue  # no breakout yet — will be re-checked next run

        score, checklist, sl_distance_pct = compute_confidence(
            candle1, coil, breakout_candle, direction, df
        )
        msg = build_message(symbol, direction, candle1, coil, breakout_candle, score, checklist, sl_distance_pct)
        entry = float(breakout_candle["Close"])
        target = entry * (1 + TARGET_PCT) if direction == "BUY" else entry * (1 - TARGET_PCT)
        stop = float(candle1["Low"] if direction == "BUY" else candle1["High"])
        signal_record = {
            "symbol": symbol,
            "date": state["date"],
            "direction": direction,
            "breakout_time": breakout_candle.name.strftime("%H:%M"),
            "entry": entry,
            "target": target,
            "stop": stop,
            "score": score,
        }
        signals.append((score, symbol, msg, signal_record))

    # Rank by confidence, highest first, and send
    signals.sort(key=lambda x: x[0], reverse=True)
    for score, symbol, msg, signal_record in signals:
        if send_telegram(msg):
            state["alerted"].append(symbol)
            state["signals"].append(signal_record)

    if not signals:
        print(f"No new signals this run ({datetime.datetime.now(IST).strftime('%H:%M')}).")

    save_state(state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-universe",
        action="store_true",
        help="Fetch and save the latest Nifty Midcap 100 constituents, then exit",
    )
    args = parser.parse_args()
    if args.refresh_universe:
        load_nifty_midcap100_symbols(force_refresh=True)
    else:
        run()
