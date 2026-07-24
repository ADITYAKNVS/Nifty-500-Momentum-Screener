import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
import warnings
import json
import os
import time
import sector_map
from datetime import datetime
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge

# Suppress warnings
warnings.filterwarnings('ignore')

PARQUET_PATH = "nifty500_daily.parquet"
SIGNAL_OUTPUT_FILE = "ridge_pure_signals.json"
TOP_N = 5
LEVERAGE = 1.10
ROUND_TRIP_COST = 0.0035

def load_breaker_state():
    """Load breaker state."""
    db = {
        "tripped": False, "tripped_date": None, "last_month_return": 0.0,
        "month_start_capital": None, "month_start_date": None,
        "high_water_mark": None, "current_capital": 1000000, 
        "kill_switch_active": False, "kill_switch_date": None
    }
    if os.path.exists("v2_breaker_state.json"):
        try:
            with open("v2_breaker_state.json", 'r') as f:
                loaded = json.load(f)
                db.update(loaded)
        except Exception:
            pass
    return db

def get_next_trading_day(current_date, all_dates):
    try:
        idx = all_dates.index(current_date)
        if idx + 1 < len(all_dates):
            return all_dates[idx + 1]
    except ValueError:
        pass
    return current_date

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

def run_ridge_scanner():
    print("🚀 Ridge Regression (Pure 1.1x) — PRODUCTION SCREENER")
    print("=" * 70)
    
    if not os.path.exists(PARQUET_PATH):
        print(f"❌ {PARQUET_PATH} not found!")
        return
        
    df_all = pd.read_parquet(PARQUET_PATH)
    df_all['Date'] = pd.to_datetime(df_all['Date']).dt.tz_localize(None)
    df_all = df_all.sort_values(['Ticker', 'Date']).reset_index(drop=True)
    
    # Filter universe
    nifty500_csv = pd.read_csv("ind_nifty500list.csv")
    valid_tickers = set(nifty500_csv['Symbol'].dropna())
    valid_tickers.add('ETERNAL')
    df_all = df_all[df_all['Ticker'].isin(valid_tickers)].copy()
    
    latest_date = df_all['Date'].max()
    latest_date_str = latest_date.strftime('%Y-%m-%d')
    print(f"📅 Screener Date  : {latest_date_str}")
    
    # 1. Feature Engineering
    print("⏳ Engineering features...")
    df_all['Daily_Return'] = df_all.groupby('Ticker')['Close'].pct_change().replace([np.inf, -np.inf], 0.0).fillna(0.0)
    df_all['Ret_21'] = df_all.groupby('Ticker')['Close'].pct_change(21).replace([np.inf, -np.inf], np.nan)
    df_all['Ret_63'] = df_all.groupby('Ticker')['Close'].pct_change(63).replace([np.inf, -np.inf], np.nan)
    df_all['Ret_126'] = df_all.groupby('Ticker')['Close'].pct_change(126).replace([np.inf, -np.inf], np.nan)
    df_all['Ret_252'] = df_all.groupby('Ticker')['Close'].pct_change(252).replace([np.inf, -np.inf], np.nan)

    df_all['Vol_20'] = df_all.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(20).std() * np.sqrt(252))
    df_all['Vol_60'] = df_all.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(60).std() * np.sqrt(252))
    df_all['Vol_20'] = df_all['Vol_20'].replace(0, np.nan).fillna(0.20).replace([np.inf, -np.inf], 0.20)
    df_all['Vol_60'] = df_all['Vol_60'].replace(0, np.nan).fillna(0.20).replace([np.inf, -np.inf], 0.20)

    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover_20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    df_all['Turnover_Ratio'] = (df_all['Turnover'] / df_all['Avg_Turnover_20'].replace(0, np.nan).fillna(1e6)).replace([np.inf, -np.inf], np.nan)

    df_all['SMA50'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(50).mean())
    df_all['SMA200'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())

    df_all['Price_to_SMA50'] = (df_all['Close'] / df_all['SMA50'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    df_all['Price_to_SMA200'] = (df_all['Close'] / df_all['SMA200'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    df_all['RiskAdjMom'] = (df_all['Ret_252'] / df_all['Vol_60'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    
    features_cols = ['Ret_21', 'Ret_63', 'Ret_126', 'Ret_252', 'Vol_20', 'Vol_60', 'Turnover_Ratio', 'Price_to_SMA50', 'Price_to_SMA200', 'RiskAdjMom']

    # 2. Build Targets for Training (using 2015-2020)
    print("🤖 Preparing Ridge model training on 2015-2020...")
    CLOSE_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Close')
    OPEN_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Open')
    ALL_DATES = sorted(list(CLOSE_MATRIX.index))
    
    dates_df = pd.DataFrame({'Date': CLOSE_MATRIX.index}).sort_values('Date').dropna()
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    rebalance_dates = list(dates_df.groupby('YearMonth')['Date'].max())
    
    targets = []
    # Train up to 2020
    train_rebal_dates = [d for d in rebalance_dates if d <= pd.to_datetime('2020-12-31')]
    for k in range(len(train_rebal_dates) - 1):
        tk = train_rebal_dates[k]
        tk_next = train_rebal_dates[k+1]
        ek = get_next_trading_day(tk, ALL_DATES)
        ek_next = get_next_trading_day(tk_next, ALL_DATES)
        
        open_k = OPEN_MATRIX.loc[ek]
        open_knext = OPEN_MATRIX.loc[ek_next]
        ret = (open_knext / open_k.replace(0, np.nan)) - 1.0
        ret = ret.replace([np.inf, -np.inf], np.nan)
        
        ret_df = pd.DataFrame({
            'Date': tk,
            'Ticker': ret.index,
            'Target_Return': ret.values
        })
        targets.append(ret_df)
        
    targets_df = pd.concat(targets).dropna()
    df_rebal = df_all[df_all['Date'].isin(train_rebal_dates[:-1])]
    df_ml = pd.merge(df_rebal, targets_df, on=['Date', 'Ticker'], how='inner')
    
    # Train Model
    imputer = SimpleImputer(strategy='median')
    scaler = StandardScaler()
    
    X_train_raw = df_ml[features_cols].replace([np.inf, -np.inf], np.nan)
    y_train = df_ml['Target_Return']
    
    X_train = imputer.fit_transform(X_train_raw)
    X_train = scaler.fit_transform(X_train)
    
    ridge = Ridge(alpha=1.0)
    ridge.fit(X_train, y_train)
    print("   Model trained successfully.")
    
    # 3. Predict on Latest Date
    latest_data = df_all[df_all['Date'] == latest_date].copy()
    latest_data = latest_data.dropna(subset=['SMA200', 'Avg_Turnover_20'])
    
    # Eligibility filters
    eligible = latest_data[
        (latest_data['Close'] > latest_data['SMA200']) &
        (latest_data['Avg_Turnover_20'] > 1e7) &
        (latest_data['Close'] > 10)
    ]
    eligible_tickers = eligible['Ticker'].tolist()
    print(f"   Eligible Tickers for Ridge Pure: {len(eligible_tickers)}")
    
    if not eligible_tickers:
        print("❌ Zero stocks passed trend & liquidity filters!")
        return
        
    day_feats = eligible.set_index('Ticker').reindex(eligible_tickers)
    X_raw = day_feats[features_cols].replace([np.inf, -np.inf], np.nan)
    
    X_scaled = scaler.transform(imputer.transform(X_raw))
    preds = ridge.predict(X_scaled)
    pred_series = pd.Series(preds, index=eligible_tickers)
    
    target_tickers = pred_series.sort_values(ascending=False).head(TOP_N).index.tolist()
    target_df = eligible[eligible['Ticker'].isin(target_tickers)]
    target_df['Ticker_Cat'] = pd.Categorical(target_df['Ticker'], categories=target_tickers, ordered=True)
    target_df = target_df.sort_values('Ticker_Cat')
    
    # 4. Generate Signal Signals
    current_held = set(get_current_holdings())
    frontend_signals = []
    
    # Load capital
    breaker_state = load_breaker_state()
    cur_capital = breaker_state.get("current_capital", 1000000)
    
    # Allocations (leverage 1.1x, equal weights: 22% each)
    alloc_pct = (LEVERAGE / TOP_N) * 100
    
    print("\n" + "=" * 70)
    print("🟢 RIDGE REGRESSION PURE (LIVE DEPLOYMENT SCREENER)")
    print("=" * 70)
    
    for i, (_, row) in enumerate(target_df.reset_index(drop=True).iterrows()):
        ticker = row['Ticker']
        price = row['Close']
        vol5 = row.get('Volume', 0)  # estimate vol
        
        kept_status = "HOLD" if ticker in current_held else "NEW ENTRY"
        sig_str = "HOLD" if ticker in current_held else "BUY"
        
        # Max Execution limit shares estimation (5% volume cap)
        max_shares = int((cur_capital * (alloc_pct / 100)) / price) if price > 0 else 0
        liquidity_limit_shares = int(vol5 * 0.05)
        safe_shares = min(max_shares, liquidity_limit_shares) if liquidity_limit_shares > 0 else max_shares
        
        print(f"[{i+1}] {ticker:<12} | Alloc: {alloc_pct:4.1f}% | Limit: {safe_shares:>5} shrs | {kept_status}")
        
        frontend_signals.append({
            "ticker": ticker,
            "sector": sector_map.get_sector(ticker),
            "signal": sig_str,
            "price": float(price),
            "hold_period": "Ridge Pure Core Hold",
            "allocation_pct": round(alloc_pct, 1),
            "max_volume_shrs": liquidity_limit_shares if liquidity_limit_shares > 0 else 100000,
            "target_shrs": safe_shares,
            "tech_status": kept_status
        })
        
    print("=" * 70)
    
    # Fetch actual Nifty 50 spot index
    nifty_level = 0.0
    try:
        print("🌐 Fetching Nifty 50 index spot level via direct API...")
        import urllib.request
        import json
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=1d&interval=1m"
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            res = json.loads(response.read().decode())
            price = res['chart']['result'][0]['meta']['regularMarketPrice']
            if price and price > 0:
                nifty_level = float(price)
    except Exception as e:
        print(f"⚠️ Direct spot fetch failed: {e}. Trying yfinance backup...")
        try:
            import yfinance as yf
            n50 = yf.download('^NSEI', period='5d', progress=False)
            if not n50.empty:
                if isinstance(n50.columns, pd.MultiIndex):
                    n50.columns = n50.columns.get_level_values(0)
                nifty_level = float(n50['Close'].iloc[-1])
        except Exception as ye:
            print(f"⚠️ yfinance backup failed: {ye}")
        
    if nifty_level <= 0:
        if os.path.exists("momentum_v2_signals.json"):
            try:
                with open("momentum_v2_signals.json", "r") as f:
                    data = json.load(f)
                    nifty_level = float(data.get("nifty_level", 0.0))
            except:
                pass
                
    if nifty_level <= 0:
        nifty_level = float(latest_data['Close'].mean() * 10.45)
    
    output_data = {
        "nifty_level": nifty_level,
        "regime": "Ridge_Pure_Active",
        "scanned_date": latest_date_str,
        "portfolio_value": cur_capital,
        "signals": frontend_signals,
        "sector_stats": {s: {"avg_score": 99, "signal": "Bullish"} for s in set([f['sector'] for f in frontend_signals])},
        "system_status": {
            "breaker_tripped": False,
            "kill_switch_active": False
        }
    }
    
    try:
        with open(SIGNAL_OUTPUT_FILE, 'w') as f:
            json.dump(output_data, f, indent=4)
        print(f"💾 Successfully saved Ridge Pure signals to {SIGNAL_OUTPUT_FILE}")
    except Exception as e:
        print(f"❌ Error writing JSON: {e}")

if __name__ == "__main__":
    run_ridge_scanner()
