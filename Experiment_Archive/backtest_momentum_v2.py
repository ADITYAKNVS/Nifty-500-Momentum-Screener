import pandas as pd
import numpy as np
import warnings
import time

warnings.filterwarnings('ignore')

PARQUET_PATH = "nifty500_daily.parquet"
MOMENTUM_WINDOW = 126 
TOP_N = 20
ROUND_TRIP_COST = 0.0035 

NSE_SECTORS = {
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT", "TECHM": "IT", "LTIM": "IT", "COFORGE": "IT", "PERSISTENT": "IT", "MPHASIS": "IT", "LTTS": "IT", "KPITTECH": "IT",
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking", "KOTAKBANK": "Banking", "AXISBANK": "Banking", "INDUSINDBK": "Banking", "BANKBARODA": "Banking", "PNB": "Banking", "CANBK": "Banking", "UNIONBANK": "Banking", "IDFCFIRSTB": "Banking", "FEDERALBNK": "Banking",
    "BAJFINANCE": "Financials", "BAJAJFINSV": "Financials", "CHOLAFIN": "Financials", "SHRIRAMFIN": "Financials", "MUTHOOTFIN": "Financials", "PFC": "Financials", "RECLTD": "Financials", "HDFCAMC": "Financials", "NAM-INDIA": "Financials", "HDFCLIFE": "Financials", "SBILIFE": "Financials", "ICICIGI": "Financials", "ICICIPRULI": "Financials", "IREDA": "Financials", "IRFC": "Financials",
    "RELIANCE": "Energy", "ONGC": "Energy", "NTPC": "Energy", "POWERGRID": "Energy", "COALINDIA": "Energy", "IOC": "Energy", "BPCL": "Energy", "GAIL": "Energy", "TATAPOWER": "Energy", "ADANIPOWER": "Energy", "ADANIGREEN": "Energy", "JSWENERGY": "Energy", "NHPC": "Energy",
    "MARUTI": "Auto", "M&M": "Auto", "TATAMOTORS": "Auto", "BAJAJ-AUTO": "Auto", "HEROMOTOCO": "Auto", "EICHERMOT": "Auto", "TVSMOTOR": "Auto", "ASHOKLEY": "Auto", "BOSCHLTD": "Auto", "MRF": "Auto", "BALKRISIND": "Auto", "MOTHERSON": "Auto",
    "TATASTEEL": "Metals", "HINDALCO": "Metals", "JSWSTEEL": "Metals", "VEDL": "Metals", "NMDC": "Metals", "SAIL": "Metals", "JINDALSTEL": "Metals",
    "SUNPHARMA": "Pharma", "CIPLA": "Pharma", "DRREDDY": "Pharma", "DIVISLAB": "Pharma", "LUPIN": "Pharma", "AUROPHARMA": "Pharma", "APOLLOHOSP": "Pharma", "MAXHEALTH": "Pharma", "TORNTPI": "Pharma", "ZYDUSLIFE": "Pharma", "MANKIND": "Pharma",
    "ITC": "FMCG", "HUL": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG", "TATACONSUM": "FMCG", "DABUR": "FMCG", "GODREJCP": "FMCG", "MARICO": "FMCG", "COLPAL": "FMCG", "AVENUE": "Retail", "TRENT": "Retail", "TITAN": "Retail",
    "LT": "Infrastructure", "L&T": "Infrastructure", "SIEMENS": "CapGoods", "ABB": "CapGoods", "BHEL": "CapGoods", "HAL": "Defense", "BEL": "Defense", "MAZDOCK": "Defense", "CUMMINSIND": "CapGoods", "CGPOWER": "CapGoods", "POLYCAB": "CapGoods",
    "DLF": "RealEstate", "LODHA": "RealEstate", "GODREJPROP": "RealEstate", "PRESTIGE": "RealEstate", "BHARTIARTL": "Telecom", "INDIGO": "Aviation", "SRF": "Chemicals", "PIDILITIND": "Chemicals", "TATACHEM": "Chemicals", "DEEPAKNTR": "Chemicals",
    "ADANIENT": "Diversified", "ADANIPORTS": "Infrastructure", "AMBUJACEM": "Cement", "ULTRACEMCO": "Cement", "GRASIM": "Cement", "SHREECEM": "Cement"
}

def get_sector(ticker):
    return NSE_SECTORS.get(ticker, "General")

def build_market_regime(df_all, sma_length):
    import yfinance as yf
    if not hasattr(build_market_regime, "n50_cache"):
        print("   🌐 Fetching Nifty 50 Index data...")
        n50 = yf.download('^NSEI', start='2014-01-01', progress=False)
        if isinstance(n50.columns, pd.MultiIndex): n50.columns = n50.columns.get_level_values(0)
        n50.reset_index(inplace=True)
        n50['Date'] = pd.to_datetime(n50['Date']).dt.tz_localize(None)
        build_market_regime.n50_cache = n50
    else:
        n50 = build_market_regime.n50_cache.copy()
        
    merged = n50[['Date', 'Open', 'High', 'Low', 'Close']].copy()
    merged = merged.rename(columns={'Close': 'Market_Close'})
    for col in ['Market_Close', 'Open', 'High', 'Low']:
        merged[col] = pd.to_numeric(merged[col], errors='coerce')
    merged = merged.dropna(subset=['Market_Close']).sort_values('Date').reset_index(drop=True)
    valid_mask = (merged['High'] >= merged['Open']) & (merged['High'] >= merged['Market_Close']) & \
                 (merged['Low'] <= merged['Open']) & (merged['Low'] <= merged['Market_Close'])
    if not valid_mask.all():
        merged = merged[valid_mask].copy()

    merged['Market_SMA'] = merged['Market_Close'].rolling(sma_length).mean()
    merged['Market_Bullish'] = merged['Market_Close'] > merged['Market_SMA']
    merged['Market_Ret_126'] = merged['Market_Close'].pct_change(126)
    merged['Market_Abs_Bullish'] = merged['Market_Ret_126'] > 0
    
    return merged[['Date', 'Market_Close', 'Market_Bullish', 'Market_Abs_Bullish']]


print("📂 Loading master daily parquet data...")
try:
    GLOBAL_DF = pd.read_parquet(PARQUET_PATH)
    GLOBAL_DF['Date'] = pd.to_datetime(GLOBAL_DF['Date'])
    GLOBAL_DF = GLOBAL_DF.sort_values(['Ticker', 'Date'])
    GLOBAL_DF['Daily_Return'] = GLOBAL_DF.groupby('Ticker')['Close'].pct_change()
    
    CLOSE_MATRIX = GLOBAL_DF.pivot(index='Date', columns='Ticker', values='Close')
    OPEN_MATRIX = GLOBAL_DF.pivot(index='Date', columns='Ticker', values='Open') # ADDED
    LOW_MATRIX = GLOBAL_DF.pivot(index='Date', columns='Ticker', values='Low')
    HIGH_MATRIX = GLOBAL_DF.pivot(index='Date', columns='Ticker', values='High')
    ALL_DATES = sorted(list(CLOSE_MATRIX.index))
except Exception as e:
    print(f"❌ Failed to load data: {e}")
    exit()

def get_next_trading_day(current_date):
    """Find the actual next trading day for T+1 execution."""
    try:
        idx = ALL_DATES.index(current_date)
        if idx + 1 < len(ALL_DATES):
            return ALL_DATES[idx + 1]
    except ValueError:
        pass
    return current_date # Fallback

def run_backtest_variant(config, run_name):
    rebalance_freq = config.get('rebalance_freq', 'monthly')
    regime_sma = config.get('regime_sma', 200)
    sector_cap = config.get('sector_cap', None)
    trailing_stop_pct = config.get('trailing_stop', None)
    weighting = config.get('weighting', 'equal')
    use_absolute_momentum = config.get('absolute_momentum', False)
    top_n = config.get('top_n', TOP_N)
    momentum_window = config.get('momentum_window', MOMENTUM_WINDOW)
    skip_recent_days = config.get('skip_recent_days', 0)
    momentum_score_type = config.get('momentum_score_type', 'simple')
    min_price = config.get('min_price', 10)
    min_turnover = config.get('min_turnover', 5e7)
    stock_trend_sma = config.get('stock_trend_sma', 200)
    leverage = config.get('leverage', 1.0)
    
    df_all = GLOBAL_DF.copy()
    
    df_all['Prev_Close_Window'] = df_all.groupby('Ticker')['Close'].shift(momentum_window)
    if skip_recent_days > 0:
        df_all['Recent_Close'] = df_all.groupby('Ticker')['Close'].shift(skip_recent_days)
        df_all['Momentum_Score'] = (df_all['Recent_Close'] / df_all['Prev_Close_Window']) - 1
    else:
        df_all['Momentum_Score'] = (df_all['Close'] / df_all['Prev_Close_Window']) - 1
        
    df_all['SMA200'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
    df_all['SMA_Trend'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(stock_trend_sma).mean())
    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    df_all['Realized_Vol_20'] = df_all.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(20).std() * np.sqrt(252))
    
    market_df = build_market_regime(df_all, sma_length=regime_sma)
    df_all = df_all.merge(market_df, on='Date', how='left')
    df_all['Market_Bullish'] = df_all['Market_Bullish'].fillna(False)
    df_all['Market_Abs_Bullish'] = df_all['Market_Abs_Bullish'].fillna(False)
    
    dates_df = pd.DataFrame({'Date': CLOSE_MATRIX.index}).sort_values('Date').dropna()
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    dates_df['YearWeek'] = dates_df['Date'].dt.to_period('W')
    
    reb_group = 'YearWeek' if rebalance_freq == 'weekly' else 'YearMonth'
    rebalance_dates = list(dates_df.groupby(reb_group)['Date'].max())
    
    capital = 10_000_000.0
    current_portfolio = []
    daily_equity_curve = []
    total_trades = 0
    total_hold_days = 0 
    positions = {}
    
    print(f"⚙️ Running simulation: {run_name} ...")

    for i in range(len(rebalance_dates) - 1):
        signal_date = rebalance_dates[i]
        next_reb_date = rebalance_dates[i+1]
        
        # THE FIX: Execute at T+1 Open
        exec_date = get_next_trading_day(signal_date)
        
        day_data = df_all[df_all['Date'] == signal_date].copy()
        market_is_bullish = day_data['Market_Bullish'].iloc[0] if not day_data.empty else False
        
        if use_absolute_momentum:
            market_is_bullish = market_is_bullish and (day_data['Market_Abs_Bullish'].iloc[0] if not day_data.empty else False)
            
        target_portfolio = []
        target_weights = {}
        
        if market_is_bullish:
            if momentum_score_type == 'risk_adjusted':
                vol = day_data['Realized_Vol_20'].replace(0, np.nan).fillna(0.20)
                day_data['Momentum_Score'] = day_data['Momentum_Score'] / vol

            day_data = day_data.dropna(subset=['Momentum_Score', 'SMA_Trend', 'Avg_Turnover20'])
            eligible = day_data[
                (day_data['Close'] > day_data['SMA_Trend']) & 
                (day_data['Avg_Turnover20'] > min_turnover) & 
                (day_data['Close'] > min_price)
            ].sort_values('Momentum_Score', ascending=False)
            
            if sector_cap is not None and not eligible.empty:
                sector_counts = {}
                for idx, row in eligible.iterrows():
                    sec = get_sector(row['Ticker'])
                    if sec not in sector_counts: sector_counts[sec] = 0
                    if sector_counts[sec] < sector_cap or sec == "General":
                        target_portfolio.append(row['Ticker'])
                        sector_counts[sec] += 1
                        if len(target_portfolio) == top_n: break
            else:
                allow_hold_rank = config.get('allow_hold_rank', None)
                if allow_hold_rank is not None:
                    held_tickers = set(positions.keys())
                    buffer_eligible = eligible['Ticker'].head(allow_hold_rank).tolist()
                    to_keep = [t for t in buffer_eligible if t in held_tickers]
                    to_add = [t for t in eligible['Ticker'].tolist() if t not in to_keep]
                    target_portfolio = to_keep + to_add[:max(0, top_n - len(to_keep))]
                else:
                    target_portfolio = eligible['Ticker'].head(top_n).tolist()
                
            if target_portfolio:
                if weighting == 'inverse_vol':
                    port_data = eligible[eligible['Ticker'].isin(target_portfolio)]
                    port_data['Inv_Vol'] = 1.0 / (port_data['Realized_Vol_20'].replace(0, np.nan).fillna(0.20))
                    total_inv_vol = port_data['Inv_Vol'].sum()
                    for idx, row in port_data.iterrows():
                        target_weights[row['Ticker']] = row['Inv_Vol'] / total_inv_vol
                else:
                    for t in target_portfolio:
                        target_weights[t] = 1.0 / len(target_portfolio)

        # Mark to market at T+1 Open to know current cash
        invested_value = 0.0
        for t, pos in positions.items():
            # Use Open price on execution day to value current holdings
            p = OPEN_MATRIX.loc[exec_date, t] if t in OPEN_MATRIX.columns else pos['entry_price']
            if pd.isna(p): p = pos['entry_price']
            invested_value += pos['shares'] * p
            
        cash = capital - invested_value 
        total_assets = cash + invested_value
        
        sells = set(positions.keys()) - set(target_portfolio)
        buys = set(target_portfolio) - set(positions.keys())
        holds = set(target_portfolio).intersection(set(positions.keys()))
        
        # SELL at T+1 Open
        for t in list(sells):
            p = OPEN_MATRIX.loc[exec_date, t] if t in OPEN_MATRIX.columns else positions[t]['entry_price']
            if pd.isna(p): p = positions[t]['entry_price']
            
            val = positions[t]['shares'] * p
            cost = val * (ROUND_TRIP_COST / 2)
            
            # FIX: Calculate hold days BEFORE deleting
            total_hold_days += (exec_date - positions[t]['entry_date']).days
            
            cash += (val - cost)
            total_assets -= cost
            del positions[t]
            total_trades += 1
            
        # REBALANCE HOLDS at T+1 Open
        for t in holds:
            p = OPEN_MATRIX.loc[exec_date, t] if t in OPEN_MATRIX.columns else positions[t]['entry_price']
            if pd.isna(p): p = positions[t]['entry_price']
            
            current_val = positions[t]['shares'] * p
            target_val = total_assets * target_weights[t] * leverage
            diff = target_val - current_val
            
            if diff > 0: 
                cost = diff * (ROUND_TRIP_COST / 2)
                cash -= (diff + cost)
                total_assets -= cost
                positions[t]['shares'] += diff / p
            elif diff < 0: 
                amount_to_sell = abs(diff)
                cost = amount_to_sell * (ROUND_TRIP_COST / 2)
                cash += (amount_to_sell - cost)
                total_assets -= cost
                positions[t]['shares'] -= amount_to_sell / p
                
            positions[t]['peak_price'] = max(positions[t]['peak_price'], p)
                
        # BUY at T+1 Open
        for t in buys:
            p = OPEN_MATRIX.loc[exec_date, t] if t in OPEN_MATRIX.columns else 0
            if pd.isna(p) or p == 0: continue
            
            target_val = total_assets * target_weights[t] * leverage
            cost = target_val * (ROUND_TRIP_COST / 2)
            cash -= (target_val + cost)
            total_assets -= cost
            
            positions[t] = {
                'shares': target_val / p,
                'entry_price': p,
                'peak_price': p,
                'entry_date': exec_date # Track from actual execution date
            }
            total_trades += 1

        capital = total_assets 
        
        # Intra-period day-by-day simulation
        start_idx = ALL_DATES.index(exec_date) + 1 if exec_date in ALL_DATES else 0
        end_idx = ALL_DATES.index(next_reb_date) + 1 if next_reb_date in ALL_DATES else 0
        
        for d_idx in range(start_idx, end_idx):
            d = ALL_DATES[d_idx]
            daily_port_val = 0.0
            
            for t in list(positions.keys()):
                try:
                    p = CLOSE_MATRIX.loc[d, t]
                    low_p = LOW_MATRIX.loc[d, t]
                    high_p = HIGH_MATRIX.loc[d, t]
                except KeyError:
                    p = positions[t]['entry_price']
                    low_p = p
                    high_p = p
                    
                if pd.isna(p) or p == 0: p = positions[t]['entry_price']
                
                pos = positions[t]
                
                stop_hit = False
                if trailing_stop_pct is not None:
                    stop_price = pos['peak_price'] * (1 - trailing_stop_pct)
                    if low_p <= stop_price:
                        # FIX: Real stop orders fill BELOW the trigger price
                        exit_price = stop_price * (1 - 0.002) 
                        exit_val = pos['shares'] * exit_price
                        cost = exit_val * (ROUND_TRIP_COST / 2)
                        
                        cash += (exit_val - cost) 
                        # FIX: Removed "capital -= cost" to prevent double deduction
                        
                        total_hold_days += (d - pos['entry_date']).days
                        del positions[t]
                        stop_hit = True
                        total_trades += 1
                    else:
                        pos['peak_price'] = max(pos['peak_price'], high_p)
                
                if not stop_hit:
                    daily_port_val += pos['shares'] * p
                    
            capital = cash + daily_port_val
            daily_equity_curve.append({'Date': d, 'Capital': capital})
            
    # Metrics calculation (unchanged)
    eq_df = pd.DataFrame(daily_equity_curve)
    if eq_df.empty: return None
    
    eq_df = eq_df.drop_duplicates('Date', keep='last')
    eq_df['Daily_Return'] = eq_df['Capital'].pct_change().fillna(0)
    
    years = (eq_df['Date'].max() - eq_df['Date'].min()).days / 365.25
    cagr = ((eq_df['Capital'].iloc[-1] / 10_000_000) ** (1/years) - 1) if years > 0 else 0
    
    eq_df['Peak'] = eq_df['Capital'].cummax()
    eq_df['Drawdown'] = (eq_df['Capital'] - eq_df['Peak']) / eq_df['Peak']
    max_dd = eq_df['Drawdown'].min()
    
    daily_ret = eq_df['Daily_Return']
    rf_daily = 0.06 / 252
    excess = daily_ret - rf_daily
    
    ann_vol = daily_ret.std() * np.sqrt(252)
    sharpe = (excess.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else 0
    
    down_std = daily_ret[daily_ret < 0].std()
    sortino = (excess.mean() / down_std) * np.sqrt(252) if down_std > 0 else 0
    
    trades_per_year = total_trades / years if years > 0 else 0
    avg_hold = total_hold_days / total_trades if total_trades > 0 else 30
    
    return {
        'Run': run_name, 'CAGR': cagr, 'Vol': ann_vol, 'Sharpe': sharpe,
        'Sortino': sortino, 'Max_DD': max_dd, 'Trades_Yr': trades_per_year,
        'Avg_Hold_Days': avg_hold,
        'Daily_Returns': eq_df.set_index('Date')['Daily_Return'],
        'Equity_Curve': eq_df.set_index('Date')['Capital']
    }

def main():
    print("=" * 65)
    print("🚀 NIFTY 500 Momentum - V2 REALISTIC T+1 Engine")
    print("=" * 65)
    
    results = []
    r_v1 = run_backtest_variant({}, "V1 Baseline (T+1 Fixed)")
    if r_v1: results.append(r_v1)
    
    configs = [
        ({"rebalance_freq": "weekly"}, "A - Weekly Rebalance"),
        ({"regime_sma": 100}, "B - Faster Regime (SMA100)"),
        ({"sector_cap": 4}, "C - Sector Cap (Max 4)"),
        ({"trailing_stop": 0.15}, "D - Trailing Stop (15%)"),
        ({"weighting": "inverse_vol"}, "E - Inverse Vol Weighting"),
        ({"absolute_momentum": True}, "F - Absolute Momentum Filter"),
        ({
            'regime_sma': 100, 'top_n': 5, 'momentum_window': 252,
            'skip_recent_days': 21, 'allow_hold_rank': 15, 'min_turnover': 1e7
        }, "H - God Mode (Unlevered)"),
        ({
            'regime_sma': 100, 'top_n': 5, 'momentum_window': 252,
            'skip_recent_days': 21, 'allow_hold_rank': 15, 'min_turnover': 1e7,
            'leverage': 1.10
        }, "I - God Mode + 1.1x Leverage")
    ]
    
    for conf, name in configs:
        res = run_backtest_variant(conf, name)
        if res: results.append(res)
        
    res_df = pd.DataFrame(results)
    baseline_sharpe = res_df[res_df['Run'] == 'V1 Baseline (T+1 Fixed)']['Sharpe'].iloc[0]
    baseline_dd = res_df[res_df['Run'] == 'V1 Baseline (T+1 Fixed)']['Max_DD'].iloc[0]
    
    combined_config = {}
    for idx, row in res_df.iterrows():
        if "Baseline" in row['Run']: continue
        if row['Sharpe'] > baseline_sharpe and row['Max_DD'] > baseline_dd:
            char = row['Run'][0]
            if char == 'A': combined_config['rebalance_freq'] = 'weekly'
            elif char == 'B': combined_config['regime_sma'] = 100
            elif char == 'C': combined_config['sector_cap'] = 4
            elif char == 'D': combined_config['trailing_stop'] = 0.15
            elif char == 'E': combined_config['weighting'] = 'inverse_vol'
            elif char == 'F': combined_config['absolute_momentum'] = True
                
    if combined_config:
        res_g = run_backtest_variant(combined_config, "G - Combined Winners")
        if res_g: results.append(res_g)
        
    final_df = pd.DataFrame(results)
    
    print("\n" + "=" * 105)
    print("📈 REALISTIC T+1 MOMENTUM V2 RESULTS")
    print("=" * 105)
    header = f"{'Run Variant':<32} | {'CAGR':>7} | {'Ann Vol':>7} | {'Sharpe':>6} | {'Sortino':>7} | {'Max DD':>7} | {'Trades/Yr':>9} | {'Hold Days':>9}"
    print(header)
    print("-" * 105)
    
    for idx, row in final_df.iterrows():
        name = row['Run']
        cagr = f"{row['CAGR']:.2%}"
        vol = f"{row['Vol']:.2%}"
        sharpe = f"{row['Sharpe']:.2f}"
        sortino = f"{row['Sortino']:.2f}"
        dd = f"{row['Max_DD']:.2%}"
        trd = f"{row['Trades_Yr']:.1f}"
        hld = f"{row['Avg_Hold_Days']:.1f}"
        print(f"{name:<32} | {cagr:>7} | {vol:>7} | {sharpe:>6} | {sortino:>7} | {dd:>7} | {trd:>9} | {hld:>9}")
        
    print("=" * 105)

if __name__ == "__main__":
    main()
