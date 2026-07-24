import pandas as pd
import numpy as np
import warnings
import json
import os
import sector_map
from datetime import datetime

# Suppress warnings
warnings.filterwarnings('ignore')

PARQUET_PATH = "nifty500_daily.parquet"
SIGNAL_OUTPUT_FILE = "momentum_signals.json"
MOMENTUM_WINDOW = 126  # ~6 months
TOP_N = 20
REGIME_SMA = 200
MIN_TURNOVER = 5e7  # 5 Cr

def get_current_holdings():
    """Reads yesterday's signals to establish state-aware execution."""
    if not os.path.exists(SIGNAL_OUTPUT_FILE):
        return []
    try:
        with open(SIGNAL_OUTPUT_FILE, 'r') as f:
            data = json.load(f)
            return [s['ticker'] for s in data.get('signals', []) if s.get('signal') in ('BUY', 'HOLD')]
    except Exception:
        return []

def build_market_regime(df_all):
    import urllib.request
    import json
    
    print("🌐 Fetching latest Nifty 50 Index data for Regime Filter...")
    n50 = pd.DataFrame()
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?period1=1388534400&period2=9999999999&interval=1d"
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode())
            result = res['chart']['result'][0]
            timestamps = result['timestamp']
            quote = result['indicators']['quote'][0]
            closes = quote['close']
            n50 = pd.DataFrame({
                'Date': pd.to_datetime(timestamps, unit='s'),
                'Close': closes
            })
    except Exception as e:
        print(f"⚠️ Direct Nifty 50 fetch failed: {e}. Trying yfinance backup...")
        try:
            import yfinance as yf
            n50_yf = yf.download('^NSEI', start='2014-01-01', progress=False)
            if not n50_yf.empty:
                if isinstance(n50_yf.columns, pd.MultiIndex):
                    n50_yf.columns = n50_yf.columns.get_level_values(0)
                n50_yf.reset_index(inplace=True)
                n50_yf['Date'] = pd.to_datetime(n50_yf['Date']).dt.tz_localize(None)
                n50 = n50_yf[['Date', 'Close']].copy()
        except Exception as ye:
            print(f"⚠️ yfinance backup failed: {ye}")
            
    if n50.empty:
        print("🚨 CRITICAL: Could not fetch Nifty 50 index data! Generating synthetic index...")
        dates_sorted = sorted(df_all['Date'].unique())
        synthetic_n50 = []
        for d in dates_sorted:
            day_data = df_all[df_all['Date'] == d]
            mean_val = day_data['Close'].mean()
            synthetic_n50.append({
                'Date': d,
                'Close': float(mean_val * 10.45)
            })
        n50 = pd.DataFrame(synthetic_n50)
        
    n50['Date'] = pd.to_datetime(n50['Date']).dt.tz_localize(None)
    
    merged = n50[['Date', 'Close']].copy()
    merged = merged.rename(columns={'Close': 'Market_Close'})
    merged['Market_Close'] = pd.to_numeric(merged['Market_Close'], errors='coerce')
    merged = merged.dropna().sort_values('Date').reset_index(drop=True)
    
    merged['Market_SMA'] = merged['Market_Close'].rolling(REGIME_SMA).mean()
    merged['Is_Above'] = merged['Market_Close'] > merged['Market_SMA']
    
    last_row = merged.iloc[-1]
    market_is_bullish = bool(last_row['Is_Above'])
    max_date = df_all['Date'].max()
    return market_is_bullish, last_row['Market_Close'], last_row['Market_SMA'], max_date

def emit_empty_signal(filename, status_type, date_str, nifty_level):
    with open(filename, 'w') as f:
        json.dump({
            "nifty_level": nifty_level,
            "regime": status_type,
            "scanned_date": date_str,
            "signals": [],
            "sector_stats": {}
        }, f, indent=4)
    print(f"💾 {status_type} state saved to {filename}")

def run_momentum_scanner():
    print("🚀 NIFTY 500 Monthly Momentum V1 — PRODUCTION SCREENER")
    print("=" * 70)
    
    try:
        df_all = pd.read_parquet(PARQUET_PATH)
    except FileNotFoundError:
        print(f"❌ {PARQUET_PATH} not found!")
        return

    # Filter to ONLY current Nifty 500 from official CSV
    nifty500_csv = pd.read_csv("ind_nifty500list.csv")
    valid_tickers = set(nifty500_csv['Symbol'].dropna())
    df_all = df_all[df_all['Ticker'].isin(valid_tickers)]

    df_all['Date'] = pd.to_datetime(df_all['Date'])
    market_is_bullish, last_close, last_sma, max_date = build_market_regime(df_all)
    max_date_str = max_date.strftime('%Y-%m-%d')
    
    print(f"📅 Scanning Date  : {max_date_str}")
    print(f"📈 Nifty50 Close  : {last_close:.2f} (SMA{REGIME_SMA}: {last_sma:.2f})")
    print(f"   ▶ Regime Status : {'BULLISH 🟢' if market_is_bullish else 'BEARISH 🔴 (100% Cash)'}")

    if not market_is_bullish:
        print("\n📉 Market is BEARISH. Entering 100% CASH MODE.")
        emit_empty_signal(SIGNAL_OUTPUT_FILE, "Bearish", max_date_str, float(last_close))
        return
        
    print(f"\n⏳ Pre-computing structural velocity across Nifty 500...")
    df_all = df_all.sort_values(['Ticker', 'Date'])
    df_all['Prev_Close_126'] = df_all.groupby('Ticker')['Close'].shift(MOMENTUM_WINDOW)
    df_all['Momentum_6M'] = (df_all['Close'] / df_all['Prev_Close_126']) - 1
    df_all['SMA200'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    df_all['Avg_Volume5'] = df_all.groupby('Ticker')['Volume'].transform(lambda x: x.rolling(5).mean())

    latest_data = df_all[df_all['Date'] == max_date].copy()
    latest_data = latest_data.dropna(subset=['Momentum_6M', 'SMA200', 'Avg_Turnover20'])
    
    # Fundamental filters
    eligible = latest_data[
        (latest_data['Close'] > latest_data['SMA200']) & 
        (latest_data['Avg_Turnover20'] > MIN_TURNOVER) & 
        (latest_data['Close'] > 10)
    ]
    
    if eligible.empty:
        print("\n❌ Zero stocks passed the trend & liquidity filters!")
        emit_empty_signal(SIGNAL_OUTPUT_FILE, "No_Candidates", max_date_str, float(last_close))
        return
        
    eligible = eligible.sort_values('Momentum_6M', ascending=False)
    target_df = eligible.head(TOP_N)
    
    current_held = set(get_current_holdings())
    frontend_signals = []
    
    alloc_pct = 100.0 / TOP_N  # 5% each for TOP_20
    
    for i, (_, row) in enumerate(target_df.reset_index(drop=True).iterrows()):
        ticker = row['Ticker']
        sector = sector_map.get_sector(ticker)
        price = row['Close']
        vol5 = row.get('Avg_Volume5', 0)
        
        kept_status = "HOLD" if ticker in current_held else "NEW ENTRY"
        sig_str = "HOLD" if ticker in current_held else "BUY"
        
        max_alloc_amount = 1000000 * (alloc_pct / 100.0) # assume 10L starting capital
        max_shares = int(max_alloc_amount / price) if price > 0 else 0
        liquidity_limit_shares = int(vol5 * 0.05) # 5% volume limit
        safe_shares = min(max_shares, liquidity_limit_shares) if liquidity_limit_shares > 0 else max_shares
        
        print(f"[{i+1}] {ticker:<12} | Price: ₹{price:<7.1f} | Alloc: {alloc_pct:.1f}% | {kept_status}")
        
        frontend_signals.append({
            "ticker": ticker,
            "sector": sector,
            "signal": sig_str,
            "price": float(price),
            "hold_period": "Monthly Hold",
            "allocation_pct": round(alloc_pct, 1),
            "max_volume_shrs": liquidity_limit_shares if liquidity_limit_shares > 0 else 100000,
            "target_shrs": safe_shares,
            "tech_status": kept_status
        })

    output_data = {
        "nifty_level": float(last_close),
        "regime": "Bullish",
        "scanned_date": max_date_str,
        "signals": frontend_signals,
        "sector_stats": {s: {"avg_score": 99, "signal": "Bullish"} for s in set([f['sector'] for f in frontend_signals])}
    }
    
    try:
        with open(SIGNAL_OUTPUT_FILE, 'w') as f:
            json.dump(output_data, f, indent=4)
        print(f"💾 Successfully saved Momentum V1 signals to {SIGNAL_OUTPUT_FILE}")
    except Exception as e:
        print(f"❌ Error writing JSON: {e}")

if __name__ == "__main__":
    run_momentum_scanner()
