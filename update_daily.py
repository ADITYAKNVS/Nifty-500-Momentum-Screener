import pandas as pd
import yfinance as yf
from datetime import datetime
import os
import warnings

warnings.filterwarnings('ignore')

PARQUET_PATH = "nifty500_daily.parquet"
REJECT_LOG   = "logs/data_rejected.log"

def update_dataset():
    if not os.path.exists(PARQUET_PATH):
        print(f"❌ '{PARQUET_PATH}' not found!")
        return

    print(f"📂 Loading existing dataset '{PARQUET_PATH}'...")
    df = pd.read_parquet(PARQUET_PATH)
    
    # Check max date
    last_date = df['Date'].max()
    print(f"📅 Last date in dataset: {last_date.strftime('%Y-%m-%d')}")
    
    start_date = last_date + pd.Timedelta(days=1)
    today = pd.Timestamp(datetime.today().date())
    
    if start_date > today:
        print("✅ Dataset is already up to date!")
        return

    tickers = sorted(df['Ticker'].unique())
    
    # Check for index drift
    CSV_PATH = "ind_nifty500list.csv"
    if os.path.exists(CSV_PATH):
        csv_df = pd.read_csv(CSV_PATH)
        if 'Symbol' in csv_df.columns:
            new_tickers = set(csv_df['Symbol'].dropna())
            missing = new_tickers - set(tickers)
            if missing:
                print(f"\n🛑 CAUTION: Detected {len(missing)} missing tickers strictly governed by the official NSE CSV!")
                print(f"   Missing: {missing}")
                print(f"   Please run `python backfill_index.py` right now to inject their historical baseline before pushing the daily updates.")
                return

    yf_tickers = [t + ".NS" for t in tickers]
    
    print(f"📡 Requesting data via Yahoo Finance from {start_date.strftime('%Y-%m-%d')} to Today ({today.strftime('%Y-%m-%d')})...")
    
    # Use quiet download
    data = yf.download(yf_tickers, start=start_date.strftime('%Y-%m-%d'), progress=False)
    
    if data.empty:
        print("✅ No new trading days found to append.")
        return
        
    print("🔄 Processing and appending new rows...")
    new_rows = []
    
    for t_ns in yf_tickers:
        t = t_ns.replace(".NS", "")
        if ('Close', t_ns) not in data.columns:
            continue
            
        t_df = data.xs(t_ns, level=1, axis=1).copy()
        t_df = t_df.dropna(subset=['Close'])
        
        if t_df.empty:
            continue
            
        t_df['Ticker'] = t
        t_df = t_df.reset_index()
        # Rename 'Date' to avoid case mismatch
        t_df.columns = t_df.columns.str.capitalize()
        if 'Date' not in t_df.columns and 'Datetime' in t_df.columns:
            t_df = t_df.rename(columns={'Datetime': 'Date'})
            
        # Ensure column order matches
        try:
            subset = t_df[['Ticker', 'Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
            new_rows.append(subset)
        except KeyError as e:
            pass

    if not new_rows:
        print("✅ No valid new rows extracted. Already up to date.")
        return
        
    df_new = pd.concat(new_rows, ignore_index=True)
    df_new['Date'] = pd.to_datetime(df_new['Date']).dt.tz_localize(None)
    
    # ─── Data Validation Guards ───
    before_count = len(df_new)
    os.makedirs("logs", exist_ok=True)
    
    # Get previous day's close for comparison — start with the parquet baseline
    prev_closes = df[df['Date'] == df['Date'].max()][['Ticker', 'Close']].set_index('Ticker')['Close'].to_dict()
    
    # Sort new data by date so we process day-by-day and update prev_closes
    # as we go — this way each candle compares against its ACTUAL previous day
    df_new = df_new.sort_values(['Date', 'Ticker']).reset_index(drop=True)
    
    bad_mask = pd.Series(False, index=df_new.index)
    reject_reasons = []
    
    for idx, row in df_new.iterrows():
        reason = None
        ticker = row['Ticker']
        
        # Rule 1: Close < 1 (garbage/delisted)
        if row['Close'] < 1:
            reason = f"Close < 1 (₹{row['Close']:.2f})"
        
        # Rule 2: Volume = 0 (bad data)
        elif row['Volume'] == 0:
            reason = f"Volume = 0"
        
        # Rule 3: High < Low (corrupted candle)
        elif row['High'] < row['Low']:
            reason = f"High < Low (H={row['High']:.2f}, L={row['Low']:.2f})"
        
        # Rule 4: High < Open or High < Close (impossible candle)
        elif row['High'] < row['Open'] or row['High'] < row['Close']:
            reason = f"High violation (H={row['High']:.2f}, O={row['Open']:.2f}, C={row['Close']:.2f})"
        
        # Rule 5: Low > Open or Low > Close (impossible candle)
        elif row['Low'] > row['Open'] or row['Low'] > row['Close']:
            reason = f"Low violation (L={row['Low']:.2f}, O={row['Open']:.2f}, C={row['Close']:.2f})"
        
        # Rule 6: >25% price change from previous close (likely split error)
        elif ticker in prev_closes and prev_closes[ticker] > 0:
            pct_change = abs(row['Close'] - prev_closes[ticker]) / prev_closes[ticker]
            if pct_change > 0.25:
                reason = f"|Change| = {pct_change:.0%} (prev ₹{prev_closes[ticker]:.0f} → ₹{row['Close']:.0f})"
        
        if reason:
            bad_mask.iloc[idx] = True
            reject_reasons.append(f"{row['Date'].strftime('%Y-%m-%d')} {ticker}: REJECTED — {reason}")
        else:
            # ✅ Candle passed — update prev_closes so the NEXT day for this
            # ticker compares against TODAY's close, not the old baseline
            prev_closes[ticker] = row['Close']
    
    rejected_count = bad_mask.sum()
    if rejected_count > 0:
        print(f"⚠️  Rejected {rejected_count} bad candle(s):")
        with open(REJECT_LOG, "a") as f:
            for r in reject_reasons:
                print(f"   🚫 {r}")
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}  {r}\n")
        df_new = df_new[~bad_mask].reset_index(drop=True)
    
    if df_new.empty:
        print("✅ All new rows were rejected. Nothing to append.")
        return
    old_len = len(df)
    df_combined = pd.concat([df, df_new], ignore_index=True)
    
    # Deduplicate just in case
    df_combined = df_combined.drop_duplicates(subset=['Ticker', 'Date'], keep='last')
    
    new_len = len(df_combined)
    added = new_len - old_len

    df_combined.to_parquet(PARQUET_PATH)
    
    print(f"✅ Success! Appended {added} new rows to {PARQUET_PATH}.")
    print(f"📅 New latest date: {df_combined['Date'].max().strftime('%Y-%m-%d')}")

if __name__ == "__main__":
    update_dataset()
