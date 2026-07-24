import sys
import os
from datetime import datetime
from fno_data_engine import fetch_bhavcopy, process_bhavcopy

date_legacy = datetime(2024, 8, 14)
date_udiff = datetime(2024, 9, 10)

print(f"Testing Boundary 1: {date_legacy.strftime('%Y-%m-%d')} (Legacy)")
raw_leg = fetch_bhavcopy(date_legacy)
if raw_leg is not None:
    fut_leg, opt_leg = process_bhavcopy(raw_leg)
    print("Futures Columns:", list(fut_leg.columns) if fut_leg is not None else "None")
    print("Options Columns:", list(opt_leg.columns) if opt_leg is not None else "None")

print(f"\nTesting Boundary 2: {date_udiff.strftime('%Y-%m-%d')} (UDiFF)")
raw_udiff = fetch_bhavcopy(date_udiff)
if raw_udiff is not None:
    fut_udiff, opt_udiff = process_bhavcopy(raw_udiff)
    print("Futures Columns:", list(fut_udiff.columns) if fut_udiff is not None else "None")
    print("Options Columns:", list(opt_udiff.columns) if opt_udiff is not None else "None")
