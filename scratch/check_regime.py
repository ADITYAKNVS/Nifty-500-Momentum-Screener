import yfinance as yf
import pandas as pd

ticker = yf.Ticker('^NSEI')
n50 = ticker.history(start='2025-09-01', end='2026-05-26')
n50.reset_index(inplace=True)
n50['Date'] = pd.to_datetime(n50['Date']).dt.tz_localize(None)

merged = n50[['Date', 'Close']].copy()
merged = merged.rename(columns={'Close': 'Market_Close'})
merged['Market_Close'] = pd.to_numeric(merged['Market_Close'], errors='coerce')
merged = merged.dropna().sort_values('Date').reset_index(drop=True)

merged['Market_SMA'] = merged['Market_Close'].rolling(100).mean()
merged['Is_Above'] = merged['Market_Close'] > merged['Market_SMA']

current_state = False
consec_above = 0
consec_below = 0

print("Date | Close | SMA100 | Is_Above | Consec_Above | Consec_Below | State")
print("-" * 75)

for i, row in merged.iterrows():
    if pd.isna(row['Market_SMA']):
        continue
    
    if row['Is_Above']:
        consec_above += 1
        consec_below = 0
    else:
        consec_below += 1
        consec_above = 0
        
    if consec_above >= 3:
        current_state = True
    elif consec_below >= 3:
        current_state = False
        
    # Print the last 15 days of records
    if i >= len(merged) - 15:
        print(f"{row['Date'].strftime('%Y-%m-%d')} | {row['Market_Close']:.2f} | {row['Market_SMA']:.2f} | {row['Is_Above']} | {consec_above} | {consec_below} | {'BULLISH' if current_state else 'BEARISH'}")
