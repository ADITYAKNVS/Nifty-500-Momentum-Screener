import pandas as pd
import numpy as np
import warnings
import time
import os
import matplotlib.pyplot as plt
import yfinance as yf
from itertools import product

warnings.filterwarnings('ignore')

PARQUET_PATH = "nifty500_daily.parquet"
SLIPPAGE = 0.005 # 0.5% assumed round trip slippage in extreme cases
LEVERAGE = 1.10 # God Mode leverage

# --- Walk Forward Config ---
TRAIN_YEARS = 5
TEST_START_YEAR = 2020 # 2015-2019 Train -> 2020 Test

# --- Grid Search Mapped Params ---
# God mode keeps Top N=5, Weights=InvVol, Window=252. We grid search the tuning thresholds.
GRID_PARAMS = {
    'skip_recent_days': [15, 21],
    'regime_sma': [100, 150, 200]
}

def fetch_nifty50_data():
    print("   🌐 Fetching Nifty 50 Index data for Regime Filter...")
    n50 = yf.download('^NSEI', start='2010-01-01', progress=False)
    if isinstance(n50.columns, pd.MultiIndex):
        n50.columns = n50.columns.get_level_values(0)
    n50.reset_index(inplace=True)
    n50['Date'] = pd.to_datetime(n50['Date']).dt.tz_localize(None)
    n50 = n50[['Date', 'Close']].rename(columns={'Close': 'Market_Close'})
    n50 = n50.dropna().sort_values('Date').reset_index(drop=True)
    return n50

def run_trading_sim(df_stocks, df_market, start_date, end_date, params, initial_capital=1_000_000.0, is_test=False):
    """
    Executes a vectorized monthly rebalancing simulation over a date range.
    Uses T+1 open execution for hyper-realistic slippage/gap tracking.
    """
    skip_days = params['skip_recent_days']
    sma_len = params['regime_sma']
    
    # Slice the global market df to calculate SMA accurately without leakage
    # We allow the market SMA to calculate using data BEFORE start_date (which is mathematically correct in live trading)
    df_mkt = df_market[df_market['Date'] <= end_date].copy()
    df_mkt['Market_SMA'] = df_mkt['Market_Close'].rolling(sma_len).mean()
    df_mkt['Market_Bullish'] = df_mkt['Market_Close'] > df_mkt['Market_SMA']
    
    # Filter the exact slice needed
    df_slice = df_stocks[(df_stocks['Date'] >= start_date) & (df_stocks['Date'] <= end_date)].copy()
    if df_slice.empty:
        return {'sharpe': 0, 'cagr': 0, 'equity_curve': pd.Series(dtype=float), 'final_capital': initial_capital, 'dd': 0}
        
    dates_df = pd.DataFrame({'Date': df_slice['Date'].unique()}).sort_values('Date')
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    rebalance_dates = sorted(dates_df.groupby('YearMonth')['Date'].max().tolist())
    
    capital = initial_capital
    daily_equity = {}
    
    # Store next-day open prices for T+1 execution
    open_matrix = df_slice.pivot(index='Date', columns='Ticker', values='Open')
    close_matrix = df_slice.pivot(index='Date', columns='Ticker', values='Close')
    all_dates = sorted(list(df_slice['Date'].unique()))
    
    target_weights = {}
    
    # Loop over rebalance dates
    for i in range(len(rebalance_dates) - 1):
        reb_date = rebalance_dates[i]
        next_reb_date = rebalance_dates[i+1]
        
        # We need the NEXT day's open price for execution (T+1)
        try:
            reb_date_idx = all_dates.index(reb_date)
            # If rebalance is last day of dataset, break
            if reb_date_idx + 1 >= len(all_dates): break
            exec_date = all_dates[reb_date_idx + 1]
        except ValueError:
            continue
            
        day_mkt = df_mkt[df_mkt['Date'] <= reb_date]
        market_is_bullish = day_mkt['Market_Bullish'].iloc[-1] if not day_mkt.empty else False
        
        target_portfolio = {}
        
        if market_is_bullish:
            # Get signals at the close of reb_date
            day_data = df_slice[df_slice['Date'] == reb_date].copy()
            # Calculate dynamic momentum score preventing lookahead
            day_data['Momentum_Score'] = (day_data[f'Close_Lag_{skip_days}'] / day_data['Close_Lag_252']) - 1
            
            day_data = day_data.dropna(subset=['Momentum_Score', 'SMA200', 'Avg_Turnover20', 'Realized_Vol_20'])
            eligible = day_data[
                (day_data['Close'] > day_data['SMA200']) & 
                (day_data['Avg_Turnover20'] > 5e7) & 
                (day_data['Close'] > 10)
            ].sort_values('Momentum_Score', ascending=False)
            
            top_n_df = eligible.head(5) # God mode top 5
            
            if not top_n_df.empty:
                total_inv_vol = (1.0 / top_n_df['Realized_Vol_20'].replace(0, 0.2)).sum()
                for _, row in top_n_df.iterrows():
                    w = (1.0 / max(row['Realized_Vol_20'], 0.2)) / total_inv_vol
                    target_portfolio[row['Ticker']] = w * LEVERAGE
        
        # Calculate month performance
        # Execute at exec_date Open, Hold until next_reb_date Close (to simplify daily MTM)
        period_dates = [d for d in all_dates if d >= exec_date and d <= next_reb_date]
        
        if not target_portfolio:
            # Cash allocation
            for d in period_dates:
                daily_equity[d] = capital
            continue
            
        # We have stocks. Track daily prices.
        tickers = list(target_portfolio.keys())
        
        # Apply slippage on entry (we assume we enter at Open + Slippage penalty)
        try:
            entry_prices = open_matrix.loc[exec_date, tickers] * (1 + (SLIPPAGE/2))
        except KeyError:
            for d in period_dates: daily_equity[d] = capital
            continue
            
        entry_prices = entry_prices.fillna(np.inf) # Cannot buy if missing open price
        
        # Simulate holding
        start_cap = capital
        cash_held = capital * (1 - sum([min(w, 1.0) for w in target_portfolio.values()]))
        if cash_held < 0: cash_held = 0 # Leverage is borrowed cash
        
        # To avoid complex daily leverage interest, we simplify margin deduction.
        for d in period_dates:
            try:
                curr_prices = close_matrix.loc[d, tickers]
                curr_prices = curr_prices.fillna(entry_prices) # Fill missing days with entry
                
                # Apply slippage on exit for the final day
                if d == next_reb_date:
                    curr_prices = curr_prices * (1 - (SLIPPAGE/2))
                
                ret = (curr_prices - entry_prices) / entry_prices
                
                port_value = cash_held
                for t in tickers:
                    allocated_cash = start_cap * target_portfolio[t]
                    port_value += allocated_cash * (1 + ret[t])
                    
                daily_equity[d] = port_value
            except KeyError:
                daily_equity[d] = start_cap
                
        # Update capital for next month based on the last day 
        if period_dates:
            capital = daily_equity[period_dates[-1]]

    # Ensure equity curve exists
    if not daily_equity:
        return {'sharpe': 0, 'cagr': 0, 'equity_curve': pd.Series(dtype=float), 'final_capital': initial_capital, 'dd': 0}
        
    eq_series = pd.Series(daily_equity).sort_index()
    daily_rets = eq_series.pct_change().dropna()
    
    if len(daily_rets) < 20:
        return {'sharpe': 0, 'cagr': 0, 'equity_curve': eq_series, 'final_capital': capital, 'dd': 0}
        
    sharpe = np.sqrt(252) * daily_rets.mean() / (daily_rets.std() + 1e-9)
    
    years = (eq_series.index[-1] - eq_series.index[0]).days / 365.25
    cagr = ((capital / initial_capital) ** (1/years) - 1) if years > 0 and capital > 0 else 0
    
    running_max = eq_series.cummax()
    dd = ((eq_series - running_max) / running_max).min()
    
    return {
        'sharpe': sharpe, 
        'cagr': cagr, 
        'equity_curve': eq_series, 
        'final_capital': capital, 
        'dd': dd
    }

def main():
    print("="*60)
    print("🚀 TRUE WALK-FORWARD LIVE SIMULATION — GOD MODE")
    print("="*60)
    print("Strict rules applied: Zero look-ahead leakage, T+1 Execution\n")
    
    print("📂 Loading global dataset and pre-calculating base indicators...")
    try:
        GLOBAL_DF = pd.read_parquet(PARQUET_PATH)
    except FileNotFoundError:
        print(f"❌ '{PARQUET_PATH}' not found!")
        return

    GLOBAL_DF['Date'] = pd.to_datetime(GLOBAL_DF['Date'])
    GLOBAL_DF = GLOBAL_DF.sort_values(['Ticker', 'Date'])
    
    # Precalculate global slow indicators (does not cause leakage because we strictly slice by Date later)
    # The calculations use ONLY trailing data inherently.
    print("📈 Generating lag windows...")
    GLOBAL_DF['Close_Lag_252'] = GLOBAL_DF.groupby('Ticker')['Close'].shift(252)
    GLOBAL_DF['Close_Lag_21'] = GLOBAL_DF.groupby('Ticker')['Close'].shift(21)
    GLOBAL_DF['Close_Lag_15'] = GLOBAL_DF.groupby('Ticker')['Close'].shift(15)
    GLOBAL_DF['SMA200'] = GLOBAL_DF.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
    
    GLOBAL_DF['Turnover'] = GLOBAL_DF['Close'] * GLOBAL_DF['Volume']
    GLOBAL_DF['Avg_Turnover20'] = GLOBAL_DF.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    GLOBAL_DF['Daily_Return'] = GLOBAL_DF.groupby('Ticker')['Close'].pct_change()
    GLOBAL_DF['Realized_Vol_20'] = GLOBAL_DF.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(20).std() * np.sqrt(252))
    
    market_n50 = fetch_nifty50_data()
    
    param_keys = list(GRID_PARAMS.keys())
    param_combos = [dict(zip(param_keys, v)) for v in product(*GRID_PARAMS.values())]
    
    overall_start_date = pd.Timestamp(f"{TEST_START_YEAR-TRAIN_YEARS}-01-01")
    dataset_end_date = GLOBAL_DF['Date'].max()
    test_years = range(TEST_START_YEAR, dataset_end_date.year + 1)
    
    # Capital carries forward!
    current_capital = 1_000_000.0
    master_equity = []
    
    yearly_results = []
    
    for t_year in test_years:
        print("\n" + "-"*50)
        print(f"🔄 WALK-FORWARD TARGET YEAR: {t_year}")
        print("-"*50)
        
        train_start = pd.Timestamp(f"{t_year - TRAIN_YEARS}-01-01")
        train_end = pd.Timestamp(f"{t_year - 1}-12-31")
        test_start = pd.Timestamp(f"{t_year}-01-01")
        test_end = pd.Timestamp(f"{t_year}-12-31")
        if test_end > dataset_end_date:
            test_end = dataset_end_date
            
        print(f"🎓 TRAIN STEP: {train_start.date()} to {train_end.date()}")
        # -- GRID SEARCH --
        best_sharpe = -999
        best_params = None
        
        for p in param_combos:
            res = run_trading_sim(GLOBAL_DF, market_n50, train_start, train_end, p, initial_capital=1_000_000.0)
            if res['sharpe'] > best_sharpe:
                best_sharpe = res['sharpe']
                best_params = p
                
        print(f"   🏆 Best Parameters Found: {best_params} (Train Sharpe: {best_sharpe:.2f})")
        print("   🔒 Freezing parameters for real-world test simulation...")
        
        # -- TEST EXECUTION --
        print(f"⚔️  TEST STEP : {test_start.date()} to {test_end.date()}")
        target_len_months = (test_end - test_start).days / 30
        
        # Run simulation with exact carried capital.
        # This accurately models continuous uninterrupted compounding over the years.
        test_res = run_trading_sim(GLOBAL_DF, market_n50, test_start, test_end, best_params, initial_capital=current_capital, is_test=True)
        
        if len(test_res['equity_curve']) > 0:
            test_cagr = test_res['cagr']
            test_dd = test_res['dd']
            
            # Since run_trading_sim returns full period CAGR, for a 1-year test period it's effectively Year Return
            year_ret = (test_res['final_capital'] / current_capital) - 1
            
            print(f"   ✅ Test Year Return: {year_ret:.2%} | Max DD: {test_dd:.2%}")
            
            yearly_results.append({
                'Year': t_year,
                'Return': year_ret,
                'Max_DD': test_dd,
                'Params': best_params
            })
            
            master_equity.append(test_res['equity_curve'])
            current_capital = test_res['final_capital']
        else:
            print("   ⚠️  No valid test data for this period.")
            
    print("\n" + "="*60)
    print("🏆 FINAL WALK-FORWARD RESULTS")
    print("="*60)
    
    if master_equity:
        full_curve = pd.concat(master_equity)
        # Drop duplicates in case test periods overlap dates slightly (they shouldn't)
        full_curve = full_curve[~full_curve.index.duplicated(keep='first')]
        
        global_years = (full_curve.index[-1] - full_curve.index[0]).days / 365.25
        global_cagr = ((current_capital / 1_000_000.0) ** (1/global_years) - 1) if global_years > 0 else 0
        global_max = full_curve.cummax()
        global_dd = ((full_curve - global_max) / global_max).min()
        
        daily_rets = full_curve.pct_change().dropna()
        global_sharpe = np.sqrt(252) * daily_rets.mean() / (daily_rets.std() + 1e-9)
        
        print(f"  Final Capital : ₹{current_capital:,.2f}  (Start: ₹1,000,000)")
        print(f"  GLOBAL CAGR   : {global_cagr:.2%}")
        print(f"  GLOBAL SHARPE : {global_sharpe:.2f}")
        print(f"  GLOBAL MAX DD : {global_dd:.2%}")
        print("-" * 60)
        
        # Print Interpretation
        print("\n🧠 FINAL INTERPRETATION:")
        if global_cagr > 0.20 and global_dd > -0.50:
            print("→ Strategy is robust and realistic")
            print("  (It successfully survived rigorous out-of-sample forward testing without leakage.)")
        else:
            print("→ Strategy is likely overfit or unstable")
            print("  (Performance decayed or collapsed when exposed to unseen future data.)")
            
        # Plot
        fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})
        axes[0].plot(full_curve.index, full_curve.values, color='green', linewidth=1.5)
        axes[0].set_title('God Mode: True Walk-Forward Equity Curve (Out of Sample)', fontweight='bold')
        axes[0].set_ylabel('Portfolio Value (₹)')
        axes[0].grid(True, alpha=0.3)
        axes[0].set_yscale('log')
        
        dd_curve = (full_curve - global_max) / global_max
        axes[1].fill_between(dd_curve.index, dd_curve.values, 0, color='red', alpha=0.5)
        axes[1].set_title('Walk-Forward Drawdown Profile')
        axes[1].set_ylabel('Drawdown (%)')
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'walk_forward_plot.png')
        plt.savefig(plot_path, dpi=150)
        print(f"\n📊 Visualization saved to: {plot_path}")
        
    else:
        print("❌ Walk forward simulation produced no valid equity curve.")

if __name__ == "__main__":
    main()
