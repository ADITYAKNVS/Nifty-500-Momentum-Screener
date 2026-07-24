"""
Daily Auto-Runner — Alpha Quant V5
Runs the full pipeline automatically at a scheduled time (default: 4:00 PM IST).
Can also be run manually with: python3 daily_run.py --now
"""
import subprocess
import sys
import os
import time
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore')

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

def run_step(name, script):
    print(f"\n{'─' * 50}")
    print(f"▶ Step: {name}")
    print(f"{'─' * 50}")
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, script)],
        cwd=SCRIPTS_DIR,
        capture_output=False
    )
    if result.returncode != 0:
        print(f"⚠️  {name} exited with code {result.returncode}")
    return result.returncode

def run_pipeline():
    print("\n" + "=" * 60)
    print("🚀 ALPHA QUANT V5 — DAILY PIPELINE")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 60)

    # Step 1: Update data
    run_step("1/5 — Update Daily Data", "update_daily.py")

    # Step 2: Portfolio check
    run_step("2/5 — Portfolio Manager (Check Exits)", "portfolio_manager.py")

    # Step 3: Momentum Scanner (V1)
    run_step("3/5 — Monthly Momentum Scanner", "scanner_momentum.py")

    # Step 4: Momentum V2 (God Mode)
    run_step("4/5 — V2 GOD MODE Scanner", "scanner_momentum_v2.py")

    # Step 5: Ridge Regression Scanner (Pure 1.1x)
    run_step("5/5 — Ridge Regression Scanner (Pure)", "scanner_ridge_pure.py")

    print("\n" + "=" * 60)
    print("✅ PIPELINE COMPLETE")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 60)
    print("\n💡 Dashboard will auto-refresh at http://localhost:8000")
    print("   (If not already running, start with: python3 run_dashboard.py)")

def wait_for_schedule(target_hour=16, target_minute=0):
    """Wait until the target time, then run. Repeats daily."""
    while True:
        now = datetime.now()
        target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

        # If target time has already passed today, schedule for tomorrow
        if now >= target:
            target += timedelta(days=1)

        # Skip weekends (Saturday=5, Sunday=6)
        while target.weekday() >= 5:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        hours_left = wait_seconds / 3600

        print(f"\n⏰ Next run scheduled: {target.strftime('%A %Y-%m-%d at %H:%M IST')}")
        print(f"   Sleeping for {hours_left:.1f} hours...")
        print("   (Press Ctrl+C to cancel)")

        try:
            time.sleep(wait_seconds)
        except KeyboardInterrupt:
            print("\n🛑 Scheduler cancelled.")
            return

        # It's go time!
        run_pipeline()

if __name__ == "__main__":
    if "--now" in sys.argv:
        # Run immediately
        run_pipeline()
    elif "--schedule" in sys.argv:
        # Run on schedule (default 4:00 PM, every weekday)
        print("🕐 Alpha Quant V5 — Auto Scheduler")
        print("=" * 60)
        print("Mode: Weekday auto-run at 4:00 PM IST")
        print("Usage:")
        print("  python3 daily_run.py --now        → Run pipeline NOW")
        print("  python3 daily_run.py --schedule   → Wait for 4 PM, then run daily")
        print("=" * 60)
        wait_for_schedule(target_hour=16, target_minute=0)
    else:
        print("🕐 Alpha Quant V5 — Daily Pipeline Runner")
        print("=" * 60)
        print("Usage:")
        print("  python3 daily_run.py --now        → Run the full pipeline NOW")
        print("  python3 daily_run.py --schedule   → Auto-run at 4:00 PM IST (weekdays)")
        print("=" * 60)
