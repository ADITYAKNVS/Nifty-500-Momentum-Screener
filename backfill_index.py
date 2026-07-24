import pandas as pd
import yfinance as yf
import os
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

PARQUET_PATH = "nifty500_daily.parquet"
CSV_PATH = "ind_nifty500list.csv"

# Historical Ticker Bridge (Yahoo data sometimes renames but loses history)
TICKER_MAP = {
    "ETERNAL": "ZOMATO.NS",
    "ADANIENSOL": "ADANITRANS.NS",
    "JIOFIN": "JIOFIN.NS"
}

def backfill():
    if not os.path.exists(PARQUET_PATH) or not os.path.exists(CSV_PATH):
        print("❌ Files missing.")
        return

    print("📊 Loading current master database...")
    df = pd.read_parquet(PARQUET_PATH)
    start_date = df['Date'].min()
    
    csv_df = pd.read_csv(CSV_PATH)
    symbols = set(csv_df['Symbol'].dropna())
    current = set(df['Ticker'].unique())
    
    # We want to force-repair ETERNAL and the 43 other potential "poison" tickers
    # To be safe, we repair EVERYTHING that was added in the recent sync
    old_tickers = set(open('/tmp/current_tickers.txt').read().splitlines())
    to_repair = (symbols - old_tickers) | {"ETERNAL"}
    
    print(f"🚀 Repairing {len(to_repair)} symbols with ADJUSTED history and Ticker Stitching...")
    
    new_data = []
    for s in to_repair:
        yf_s_primary = s + ".NS"
        yf_s_legacy = TICKER_MAP.get(s, None)
        
        print(f"📡 Processing {s}...")
        
        # 1. Fetch Legacy Data if applicable
        legacy_df = pd.DataFrame()
        if yf_s_legacy:
            print(f"   📜 Pulling Legacy History ({yf_s_legacy})...")
            legacy_df = yf.download(yf_s_legacy, start=start_date.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
            if not legacy_df.empty and isinstance(legacy_df.columns, pd.MultiIndex):
                legacy_df.columns = legacy_df.columns.get_level_values(0)

        # 2. Fetch Current Data
        print(f"   📡 Pulling Current History ({yf_s_primary})...")
        current_df = yf.download(yf_s_primary, start=start_date.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
        if not current_df.empty and isinstance(current_df.columns, pd.MultiIndex):
            current_df.columns = current_df.columns.get_level_values(0)

        # 3. Stitch Logic
        # We prefer 'current_df' but check for 'flat' data (corruption)
        # If current_df is flat in 2025, we use legacy_df
        is_corrupted = False
        d_25 = current_df[current_df.index.year == 2025]
        if not d_25.empty and d_25['Close'].std() < 0.1: # Flat line check
            is_corrupted = True
            print(f"   ⚠️ Detected flat data in {s}.NS (Yahoo migration bug). Using Legacy instead.")

        if is_corrupted and not legacy_df.empty:
            final_t_df = legacy_df.copy()
        elif not current_df.empty:
            # If we have both and they don't overlap perfectly, merge
            if not legacy_df.empty:
                # Merge: Take legacy for old dates, current for new
                final_t_df = pd.concat([legacy_df[legacy_df.index < current_df.index.min()], current_df])
            else:
                final_t_df = current_df.copy()
        else:
            final_t_df = legacy_df.copy()

        if final_t_df.empty:
            print(f"   ❌ No data found for {s}")
            continue

        final_t_df = final_t_df.dropna(subset=['Close'])
        final_t_df['Ticker'] = s
        final_t_df = final_t_df.reset_index()
        final_t_df.columns = final_t_df.columns.str.capitalize()
        
        if 'Volume' in final_t_df.columns:
            new_data.append(final_t_df[['Ticker', 'Date', 'Open', 'High', 'Low', 'Close', 'Volume']])
            print(f"   ✔️ Successfully stitched/adjusted {len(final_t_df)} bars for {s}")

    if not new_data:
        print("❌ No new data points synthesized.")
        return
        
    df_new = pd.concat(new_data, ignore_index=True)
    df_new['Date'] = pd.to_datetime(df_new['Date']).dt.tz_localize(None)
    
    # Overwrite the dirty symbols
    df = df[~df['Ticker'].isin([s for s in to_repair])]
    df_combined = pd.concat([df, df_new], ignore_index=True)
    df_combined = df_combined.sort_values(['Ticker', 'Date']).drop_duplicates(['Ticker', 'Date'], keep='last')
    
    df_combined.to_parquet(PARQUET_PATH)
    print(f"✅ Database repair complete. {len(df_combined['Ticker'].unique())} symbols synced.")

if __name__ == "__main__":
    backfill()
