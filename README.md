# 15-Minute Inside-Bar Setup Scanner — Nifty Midcap 100

An automated intraday scanner that detects a "coil and breakout" candlestick
pattern across Nifty Midcap 100 stocks and sends signals to Telegram, with a
rule-based confidence score attached to each one.

---

## 1. The Strategy — How It Works

**The idea:** a strong first candle of the day sets a range. If the next
four candles stay *inside* that range (a "coil"), it suggests the stock is
consolidating before its next move. Once price breaks out of that range
after 10:30 AM, the direction of the break is taken as the trade direction.

### Step by step

1. **Candle 1 (9:15–9:30 AM)** — the first 15-minute candle of the day.
   Its high and low become the reference "box" for everything else.

2. **Candles 2–5 (9:30–10:30 AM)** — the next four 15-minute candles.
   For the pattern to qualify, **all four must stay fully inside** Candle
   1's high/low range. If even one of them breaks out early, the stock is
   skipped for the day — the setup didn't form as intended.

3. **Breakout check (10:30 AM onward)** — starting at 10:30 and re-checked
   every 15 minutes up to a cutoff (2:30 PM), the scanner watches for a
   candle that **closes** beyond Candle 1's high or low:
   - Close **above** Candle 1's high → **BUY** signal
   - Close **below** Candle 1's low → **SELL** signal
   - A wick poking beyond the range that closes back inside does **not**
     count — only a confirmed close triggers a signal.

   The scanner ignores the currently forming 15-minute candle. Because each
   run happens shortly after a candle boundary, the latest candle is usually
   checked on the next run after its 15-minute close is available. No fresh
   breakout is accepted after 2:30 PM IST.

4. **Trade levels:**
   - **Entry** = the breakout candle's close price
   - **Target** = entry ± 1%
   - **Stop-loss** = Candle 1's opposite extreme (its low for a BUY, its
     high for a SELL)

5. **Confidence score (0–100)** — a rule-based score, not a statistical
   probability, built from five factors:

   | Factor | Points | What it checks |
   |---|---|---|
   | Coil tightness | 25 | Did candles 2–5 stay in a small portion of Candle 1's range (tight = stronger), or did they use almost the whole range (loose = weaker)? |
   | Candle 1 size | 20 | Was Candle 1 a meaningfully large move for that stock, or a small/insignificant one? |
   | Breakout close strength | 20 | Did the breakout candle actually *close* beyond the range (always true by design — the scanner only signals on a confirmed close, never a wick) |
   | Breakout volume | 20 | Was volume on the breakout candle notably higher than the average of candles 2–5? |
   | Risk:Reward | 15 | Is the stop-loss distance reasonable relative to the 1% target, or is the risk several times larger than the reward? |

   Score ≥ 75 → **STRONG SETUP**
   Score 50–74 → **CONSIDER WITH CAUTION**
   Score < 50 → **WEAK — LIKELY SKIP**

### Important honesty note

This is a rule-based heuristic, not a backtested statistical edge. The
scanner tells you a pattern occurred and scores it against sensible
technical criteria — it does not guarantee a win rate. Treat every signal
as one input into your own trade decision, not an instruction to trade.
Consider backtesting this logic against historical data before trading it
live, and always size positions with your own risk management in mind
(especially relevant here given intraday leverage).

---

## 2. What a Generated BUY Signal Looks Like

```
🟢 15-MIN SETUP SIGNAL

📊 TATAMOTORS
Direction: 🟢 BUY
Date: 25-Aug-2026   Time: 10:30 AM IST

── Candles ──
C1 (09:15)  O:945.00 H:962.00 L:940.00 C:958.00
C2 (09:30)  O:958.00 H:960.00 L:952.00 C:955.00
C3 (09:45)  O:955.00 H:958.00 L:950.00 C:953.00
C4 (10:00)  O:953.00 H:957.00 L:949.00 C:952.00
C5 (10:15)  O:952.00 H:959.00 L:948.00 C:956.00
Breakout (10:30)  O:956.00 H:965.00 L:955.00 C:963.50

── Trade Levels ──
Entry: ₹963.50
Target (1%): ₹973.14
SL (Candle 1 Low): ₹940.00
SL distance: 2.43%  vs  Target: 1%

── Confidence Score: 85/100 ──
✅ Coil used only 42% of Candle 1's range — tight consolidation
✅ Candle 1 range is at/above this stock's recent 15m average — a real move
✅ Breakout candle CLOSED beyond the high/low, not just a wick
✅ Breakout volume is 1.8x the coil average — strong conviction
❌ Risk:Reward unfavorable — SL distance 2.43% vs 1% target

Verdict: ✅ STRONG SETUP
```

**How to read this:** Candle 1 set a range of 940–962. Candles 2–5 all
stayed inside that range (a tight coil, using only 42% of it). At 10:30,
the breakout candle closed at 963.50 — above Candle 1's high of 962 — so
the direction is BUY. The scanner scored this 85/100 because four of the
five checks passed, but flagged the risk:reward as unfavorable (the stop
distance of 2.43% is wider than the 1% target), which is exactly the kind
of detail the score is designed to surface rather than hide.

---

## 3. Setup Instructions

### A. Get the script into your repo
Place `scanner.py` in your repository root (or adjust the `run` step path
in the workflow file if you put it elsewhere).

### B. Create your Telegram bot
1. Open Telegram, message **@BotFather**, send `/newbot`, and follow the
   prompts to name it. You'll receive a **Bot Token**.
2. Send any message to your new bot once (so it has a chat to talk to).
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a
   browser — the JSON response contains your **Chat ID**.

### C. Add GitHub repo secrets
Go to your repo → **Settings → Secrets and variables → Actions** → add:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### D. Add the workflow
The repository includes `inside_bar_scanner.yml` at `.github/workflows/inside_bar_scanner.yml`.
If you are adding it to another repository, place the workflow there at the same path.
The workflow starts one long-running watcher at about 10:31 AM IST,
Monday–Friday. The watcher runs the scanner at each 15-minute boundary from
10:46 AM through 2:31 PM IST. The watcher schedules runs at minutes `:01`,
`:16`, `:31`, and `:46`, starts scanning after 10:30, and stops around 2:40 PM.
The fresh-breakout cutoff is 2:30 PM, so a final confirmed candle can be
evaluated on the next watcher pass.

The watcher is used because GitHub Actions cron events are best-effort and
frequent 15-minute cron jobs can be skipped. If the 10:31 AM start event is
missed, use **Actions → 15-Min Inside-Bar Scanner → Run workflow**. A manual
run starts the same long-lived watcher and can remain active for most of the
trading session; it is not a single point-in-time scan. The scan and report
jobs have separate concurrency groups, so the 4:00 PM IST report can run
independently of the watcher.

A separate weekday report runs around 4:00 PM IST and checks the day's alerted
symbols with `check_signal.py` before sending their outcomes to Telegram. The
scanner saves each sent signal's original date, direction, breakout time, and
trade levels, so the report does not need to rediscover the signal from changed
Yahoo Finance candles. If there are no signals for the day or Telegram delivery
fails, the report logs a warning and exits cleanly instead of failing the job.

The watcher refreshes the Nifty Midcap 100 universe at startup. It downloads the
official constituent CSV, validates that it contains exactly 100 unique symbols,
and saves them to `nifty_midcap100_symbols.json` for the session. If the refresh
cannot be completed, the checked-in universe file is used when it is valid.

### Local installation and commands

The GitHub workflow uses Python 3.11 and these packages:

```powershell
python -m pip install yfinance requests python-dotenv
```

Useful commands from the repository root:

```powershell
# Run the full trading-session watcher; refreshes the universe at startup.
python watch.py

# Run one scanner pass using the cached universe.
python scanner.py

# Refresh and save the latest 100-symbol universe, then exit.
python scanner.py --refresh-universe

# Check one symbol/date after market close.
python check_signal.py EICHERMOT 2026-08-26

# Check all signals stored for today and send the report when Telegram is configured.
python check_signal.py --report
```

Without `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, `scanner.py` prints each
signal locally instead of sending it. The report command skips Telegram delivery
and logs a warning when those credentials are missing.

### E. Test it manually first
Before relying on the schedule, trigger it manually: go to the **Actions**
tab → select the workflow → **Run workflow**. Check that a Telegram message
arrives (or that the logs show "No new signals" if nothing qualified that
moment) before trusting the automated schedule.

### F. Check a signal after market close
Run the general outcome checker with only the NSE symbol and signal date:

```powershell
python check_signal.py EICHERMOT 2026-08-26
```

It reconstructs the first valid breakout, then reports whether the 1% target
or Candle 1 stop-loss was reached first. If both are touched in one 15-minute
candle, it reports the result as ambiguous because candle data cannot show
which level was reached first. Yahoo Finance generally limits intraday history,
so check older signals soon after the trading day.

The workflow also sends an automated report around 4:00 PM IST on weekdays.
It checks every symbol that generated a signal that day and sends the breakout,
entry, target, stop-loss, and outcome to Telegram.

### Alert state

`alerted_today.json` is date-scoped and prevents duplicate alerts during
repeated scanner passes. Its shape is:

```json
{
   "date": "2026-08-26",
   "alerted": ["EICHERMOT"],
   "signals": [
      {
         "symbol": "EICHERMOT",
         "date": "2026-08-26",
         "direction": "BUY",
         "breakout_time": "10:45",
         "entry": 1000.0,
         "target": 1010.0,
         "stop": 980.0,
         "score": 85
      }
   ]
}
```

The report uses the stored entry, target, stop, direction, and breakout time
instead of trying to rediscover the original signal. A new date creates fresh
state automatically.

---

## 4. Known Limitations

- **Data source is yfinance**, which can lag 15–20 minutes behind real-time
  and occasionally has gaps for less liquid stocks. Fine for testing;
  consider switching to a broker API (e.g., Angel One SmartAPI) for
  tighter live accuracy later.
- **No backtested win rate** — the pattern and scoring are rule-based, not
  statistically validated yet.
- **Duplicate-alert protection** relies on a cached state file across scanner
   passes and fallback watcher starts during the same trading day. The report
   checks the state date before using it, so older cached signals are ignored.
- **Universe refresh** uses the official Nifty Indices constituent CSV when
   the watcher starts and keeps the refreshed 100-symbol list for that session.
   If the refresh fails, the scanner can use the checked-in universe file.
- **Secrets** should be stored in GitHub Actions secrets. Never commit `.env`
   or expose a Telegram bot token; revoke any token that has been exposed.
