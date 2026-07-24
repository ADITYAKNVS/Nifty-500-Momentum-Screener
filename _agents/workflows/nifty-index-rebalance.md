---
description: handling the official NSE NIFTY 500 September index rebalancing
---

# NSE Index Rebalancing Workflow

The NIFTY 500 officially undergoes index replacements every March and September. When this happens, new companies are added to the list, meaning our internal `nifty500_daily.parquet` historical database becomes completely blind to them unless re-synchronized.

**Warning Signs You Forgot To Do This:**
When you attempt to run `python3 update_daily.py` on a given September or March afternoon, the system will actively refuse to update and print a red flashing warning:
> `🛑 CAUTION: Detected 5 missing tickers strictly governed by the official NSE CSV!`

These are the precise steps to safely resynchronize your model so you don't panic:

1. Go manually download the `ind_nifty500list.csv` from the [NSE Equity Page](https://www.niftyindices.com/indices/equity/broad-based-indices/NIFTY-500).
2. Grab that freshly downloaded `.csv` file and drag it directly into the `Alpha model` folder, explicitly overwriting the old CSV file sitting there.
// turbo
3. Run the Deep Backfill Index engine. Type exactly:
   ```bash
   python3 backfill_index.py
   ```
4. The system will cleanly output logs confirming it mathematically extracted the specifically missing companies, grabbed all out-dated history to align the 100-SMA bounds, and merged them natively.
5. The crisis is over. You are now free to proceed. Type exactly:
   ```bash
   python3 update_daily.py
   ```
   *The market database will successfully print EOD success messages across the updated 500-tick space.*