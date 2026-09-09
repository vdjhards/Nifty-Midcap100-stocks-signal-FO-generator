import datetime
import subprocess
import sys
import time
import zoneinfo


IST = zoneinfo.ZoneInfo("Asia/Kolkata")
SCAN_MINUTES = (1, 16, 31, 46)
SESSION_START = datetime.time(10, 20)
SESSION_END = datetime.time(14, 40)


def run_scanner(*args):
    result = subprocess.run([sys.executable, "scanner.py", *args], check=False)
    if result.returncode:
        print(f"Scanner exited with status {result.returncode}; continuing.")


def next_scan_time(now):
    candidates = []
    for hour in (now.hour, now.hour + 1):
        for minute in SCAN_MINUTES:
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                candidates.append(candidate)
    return min(candidates)


def main():
    started = datetime.datetime.now(IST).replace(tzinfo=None)
    end = started.replace(hour=SESSION_END.hour, minute=SESSION_END.minute, second=0, microsecond=0)
    print(f"Watcher started at {started:%H:%M:%S} IST.")

    run_scanner("--refresh-universe")

    while True:
        now = datetime.datetime.now(IST).replace(tzinfo=None)
        if now >= end:
            break
        if now.time() < SESSION_START:
            target = now.replace(hour=SESSION_START.hour, minute=SESSION_START.minute, second=0, microsecond=0)
        else:
            target = next_scan_time(now)
        wait_seconds = (target - now).total_seconds()
        if wait_seconds > 0:
            print(f"Sleeping until {target:%H:%M} IST.")
            time.sleep(wait_seconds)
        if datetime.datetime.now(IST).replace(tzinfo=None) < end:
            run_scanner()

    print("Trading session watcher finished.")


if __name__ == "__main__":
    main()