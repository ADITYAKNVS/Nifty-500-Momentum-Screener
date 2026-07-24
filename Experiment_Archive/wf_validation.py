import numpy as np
import pandas as pd
import sys
import os
import matplotlib.pyplot as plt

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from backtest_momentum_v2 import GLOBAL_DF, CLOSE_MATRIX, LOW_MATRIX, HIGH_MATRIX, ALL_DATES, build_market_regime, get_sector
import warnings
warnings.filterwarnings('ignore')

ROUND_TRIP_COST = 0.0035
BREAKER_THRESHOLD = -0.08

# Build OPEN_MATRIX
try:
    OPEN_MATRIX = GLOBAL_DF.pivot(index='Date', columns='Ticker', values='Open')
except Exception as e:
    print(f"Error building OPEN_MATRIX: {e}")
    # Fallback to close if Open is somehow missing
    OPEN_MATRIX = CLOSE_MATRIX.copy()

def get_exec_price(target_date, ticker):
    try:
        if target_date in OPEN_MATRIX.index and ticker in OPEN_MATRIX.columns:
            p = OPEN_MATRIX.loc[target_date, ticker]
            if pd.notna(p) and p > 0: return float(p)
            
        if target_date in CLOSE_MATRIX.index and ticker in CLOSE_MATRIX.columns:
            p = CLOSE_MATRIX.loc[target_date, ticker]
            if pd.notna(p) and p > 0: return float(p)
            
        return 0.0
    except KeyError:
        return 0.0

def run_year_simulator(year, config, initial_capital, initial_positions, df_all, market_regime, target_dates):
    """
    Runs a rigorous T+1 execution simulation for exactly one year.
    Returns ending_capital, ending_positions, and the daily equity curve.
    """
    min_turnover = config['min_turnover']
    leverage = config['leverage']
    top_n = config['top_n']
    allow_hold_rank = config['allow_hold_rank']
    
    cash = initial_capital
    
    # Calculate initial total assets based on Dec 31 prior year closing prices
    # Since we are starting the year, we mark to market the carried over positions.
    start_of_year_date = ALL_DATES[ALL_DATES.index(target_dates[0]) - 1] if target_dates[0] in ALL_DATES and ALL_DATES.index(target_dates[0]) > 0 else target_dates[0]
    
    invested_val = 0
    for t, pos in initial_positions.items():
        p = CLOSE_MATRIX.loc[start_of_year_date, t] if start_of_year_date in CLOSE_MATRIX.index and t in CLOSE_MATRIX.columns else pos['entry_price']
        if pd.isna(p) or p == 0: p = pos['entry_price']
        invested_val += pos['shares'] * p
        
    cash = initial_capital - invested_val
    total_assets = initial_capital
    positions = initial_positions.copy()
    
    daily_equity_curve = []
    trades = 0
    skip_next_month = False
    
    # Execute the year's month-end loops
    for i, reb_date in enumerate(target_dates):
        # reb_date is technically the last day of the month where we EVALUATE signals
        # The trades are executed blindly on the OPEN of target_dates[i] + 1 business day
        
        # Determine the execution date (T+1)
        exec_idx = ALL_DATES.index(reb_date) + 1 if reb_date in ALL_DATES else 0
        if exec_idx >= len(ALL_DATES):
            break # Year is over, no next day to trade
        exec_date = ALL_DATES[exec_idx]
        
        # --- CIRCUIT BREAKER: skip this month if tripped ---
        if skip_next_month:
            # Sell everything and sit in cash
            for t in list(positions.keys()):
                p = get_exec_price(exec_date, t)
                if p == 0: p = positions[t]['entry_price']
                gross_val = positions[t]['shares'] * p
                cost = gross_val * (ROUND_TRIP_COST / 2)
                cash += (gross_val - cost)
                total_assets -= cost
                del positions[t]
                trades += 1
            skip_next_month = False
            
            # Track flat equity through the month
            next_reb_date = target_dates[i+1] if i+1 < len(target_dates) else None
            end_idx = ALL_DATES.index(next_reb_date) if next_reb_date and next_reb_date in ALL_DATES else min(exec_idx + 21, len(ALL_DATES))
            for d_idx in range(exec_idx, end_idx):
                d = ALL_DATES[d_idx]
                if d.year > year: break
                daily_equity_curve.append({'Date': d, 'Capital': cash})
            total_assets = cash
            continue
            
        # --- SIGNAL EVALUATION (Day T Close) ---
        
        day_data = df_all[df_all['Date'] == reb_date].copy()
        market_is_bullish = day_data['Market_Bullish'].iloc[0] if not day_data.empty else False
        
        target_portfolio = []
        target_weights = {}

        if market_is_bullish:
            day_data = day_data.dropna(subset=['Momentum_Score', 'SMA_Trend', 'Avg_Turnover20'])
            # Risk-adjusted momentum: rank by Mom/Vol (quality-filtered momentum)
            if 'Vol60' in day_data.columns:
                day_data = day_data.copy()
                day_data['RiskAdjMom'] = day_data['Momentum_Score'] / (day_data['Vol60'] + 1e-6)
                day_data.loc[~np.isfinite(day_data['RiskAdjMom']), 'RiskAdjMom'] = day_data['Momentum_Score']
                sort_col = 'RiskAdjMom'
            else:
                sort_col = 'Momentum_Score'
            eligible = day_data[
                (day_data['Close'] > day_data['SMA_Trend']) & 
                (day_data['Avg_Turnover20'] > min_turnover) & 
                (day_data['Close'] > 10)
            ].sort_values(sort_col, ascending=False)
            
            if not eligible.empty:
                if allow_hold_rank is not None:
                    held_tickers = set(positions.keys())
                    buffer_eligible = eligible['Ticker'].head(allow_hold_rank).tolist()
                    to_keep = [t for t in buffer_eligible if t in held_tickers]
                    to_add = [t for t in eligible['Ticker'].tolist() if t not in to_keep]
                    target_portfolio = to_keep + to_add[:max(0, top_n - len(to_keep))]
                else:
                    target_portfolio = eligible['Ticker'].head(top_n).tolist()
            
            if target_portfolio:
                # Momentum-weighted: higher momentum score → more weight
                mom_vals = []
                for t in target_portfolio:
                    t_row = eligible.loc[eligible['Ticker'] == t, 'Momentum_Score']
                    val = float(t_row.iloc[0]) if len(t_row) > 0 and pd.notna(t_row.iloc[0]) else 0.0
                    # Guard against inf (from division by zero in momentum calc)
                    if not np.isfinite(val) or val <= 0:
                        val = 0.0
                    mom_vals.append(val)
                total_mom = sum(mom_vals)
                if total_mom > 0:
                    target_weights = {t: v / total_mom for t, v in zip(target_portfolio, mom_vals)}
                else:
                    # Fallback: equal weight (early data or all negative/inf scores)
                    w = 1.0 / len(target_portfolio)
                    target_weights = {t: w for t in target_portfolio}

        # --- T+1 EXECUTION (Day T+1 Open) ---
        # First, mark-to-market using current T+1 opens to establish "Total Assets" right before we trade
        exec_invested = 0
        for t, pos in list(positions.items()):
            p = get_exec_price(exec_date, t)
            if p == 0: p = pos['entry_price']
            exec_invested += pos['shares'] * p
            
        total_assets = cash + exec_invested
        month_start_capital = total_assets  # Snapshot for circuit breaker
        
        # 1. Sell OUTs
        sells = [t for t in positions if t not in target_portfolio]
        for t in sells:
            p = get_exec_price(exec_date, t)
            if p == 0: p = positions[t]['entry_price']
            
            gross_val = positions[t]['shares'] * p
            cost = gross_val * (ROUND_TRIP_COST / 2)
            cash += (gross_val - cost)
            total_assets -= cost
            del positions[t]
            trades += 1
            
        # 2. Adjust HOLDs and BUY NEWs
        holds = [t for t in positions if t in target_portfolio]
        buys = [t for t in target_portfolio if t not in positions]
        
        for t in holds:
            p = get_exec_price(exec_date, t)
            if p == 0: p = positions[t]['entry_price']
            
            current_val = positions[t]['shares'] * p
            target_val = total_assets * target_weights[t] * leverage
            diff = target_val - current_val
            
            if diff > 0:
                cost = diff * (ROUND_TRIP_COST / 2)
                cash -= (diff + cost)
                total_assets -= cost
                positions[t]['shares'] += diff / p
            elif diff < 0:
                amount_sell = abs(diff)
                cost = amount_sell * (ROUND_TRIP_COST / 2)
                cash += (amount_sell - cost)
                total_assets -= cost
                positions[t]['shares'] -= amount_sell / p
                
        for t in buys:
            p = get_exec_price(exec_date, t)
            if p == 0: continue
            
            target_val = total_assets * target_weights[t] * leverage
            cost = target_val * (ROUND_TRIP_COST / 2)
            cash -= (target_val + cost)
            total_assets -= cost
            
            positions[t] = {
                'shares': target_val / p,
                'entry_price': p
            }
            trades += 1
            
        # --- TRACK DAILY EQUITY THROUGH THE REST OF THE MONTH ---
        next_reb_date = target_dates[i+1] if i+1 < len(target_dates) else None
        end_idx = ALL_DATES.index(next_reb_date) if next_reb_date in ALL_DATES else (ALL_DATES.index(reb_date) + 21 if ALL_DATES.index(reb_date) + 21 < len(ALL_DATES) else len(ALL_DATES))
        
        # Note: we execute on exec_idx, so from exec_idx to end_idx we track the equity curve
        for d_idx in range(exec_idx, end_idx):
            d = ALL_DATES[d_idx]
            if d.year > year: break # Stop tracking if it spills out of the current year entirely
            
            daily_port_val = 0.0
            for t in positions.keys():
                p = CLOSE_MATRIX.loc[d, t] if d in CLOSE_MATRIX.index and t in CLOSE_MATRIX.columns else 0
                if pd.isna(p) or p == 0: p = positions[t]['entry_price']
                daily_port_val += positions[t]['shares'] * p
                
            daily_equity_curve.append({
                'Date': d,
                'Capital': cash + daily_port_val
            })
            
        # --- CIRCUIT BREAKER CHECK: did this month lose > 8%? ---
        if daily_equity_curve and month_start_capital > 0:
            month_end_capital = daily_equity_curve[-1]['Capital']
            month_return = (month_end_capital - month_start_capital) / month_start_capital
            if month_return < BREAKER_THRESHOLD:
                skip_next_month = True
            
    return cash, positions, pd.DataFrame(daily_equity_curve), trades

# Fast-pass vectorized training evaluator (Uses Close prices natively, ignoring T+1 slippage strictly for relative model ranking)
def evaluate_train_sharpe(config, df_all, market_regime, start_date, end_date):
    # This simulates the strategy heavily vectorized
    min_turnover = config['min_turnover']
    leverage = config['leverage']
    top_n = config['top_n']
    allow_hold_rank = config['allow_hold_rank']
    
    dates_df = pd.DataFrame({'Date': list(CLOSE_MATRIX.index)}).sort_values('Date').dropna()
    dates_df = dates_df[(dates_df['Date'] >= start_date) & (dates_df['Date'] <= end_date)]
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    target_dates = list(dates_df.groupby('YearMonth')['Date'].max())
    
    cash = 1000000.
    total_assets = 1000000.
    positions = {}
    eq_curve = []
    
    for idx, reb_date in enumerate(target_dates):
        day_data = df_all[df_all['Date'] == reb_date].copy()
        market_is_bullish = day_data['Market_Bullish'].iloc[0] if not day_data.empty else False
        
        target_portfolio = []
        if market_is_bullish:
            day_data = day_data.dropna(subset=['Momentum_Score', 'SMA_Trend', 'Avg_Turnover20'])
            eligible = day_data[
                (day_data['Close'] > day_data['SMA_Trend']) & 
                (day_data['Avg_Turnover20'] > min_turnover) & 
                (day_data['Close'] > 10)
            ].sort_values('Momentum_Score', ascending=False)
            
            if not eligible.empty:
                if allow_hold_rank is not None:
                    held_tickers = set(positions.keys())
                    buffer = eligible['Ticker'].head(allow_hold_rank).tolist()
                    to_keep = [t for t in buffer if t in held_tickers]
                    to_add = [t for t in eligible['Ticker'].tolist() if t not in to_keep]
                    target_portfolio = to_keep + to_add[:max(0, top_n - len(to_keep))]
                else:
                    target_portfolio = eligible['Ticker'].head(top_n).tolist()
                    
        # Simplistic vector tracking for speed
        for t in list(positions.keys()):
            if t not in target_portfolio:
                del positions[t]
        for t in target_portfolio:
            if t not in positions:
                positions[t] = 1.0 / len(target_portfolio)
                
        # Track next 21 days simply using equal weight indices
        if idx < len(target_dates)-1:
            next_date = target_dates[idx+1]
            sub_idx = (CLOSE_MATRIX.index > reb_date) & (CLOSE_MATRIX.index <= next_date)
            if len(target_portfolio) > 0:
                ret = CLOSE_MATRIX.loc[sub_idx, target_portfolio].pct_change().fillna(0).mean(axis=1) * leverage
                eq_curve.append(ret)
            else:
                eq_curve.append(pd.Series(0.0, index=CLOSE_MATRIX.index[sub_idx]))

    if not eq_curve:
        return 0.0
    
    full_ret = pd.concat(eq_curve)
    std = full_ret.std()
    return (full_ret.mean() / std) * np.sqrt(252) if std > 0 else 0

def main():
    print("=========================================================================================")
    print("🌍 LIVE YEAR-BY-YEAR SIMULATION ENGINE (ROLLING WALK-FORWARD WITH T+1 EXECUTION)")
    print("=========================================================================================")
    print("1. START = 10,00,000 INR")
    print("2. For each year, grid search on prior historical data to pick optimal parameters")
    print("3. Execute blindly in the test year strictly at T+1 Open prices + slippage")
    print("4. Rollover physical shares and cash directly into January of the next year")
    print("=========================================================================================\n")

    param_grid = [
        {'top_n': 5, 'momentum_window': 252, 'skip_recent_days': 21, 'allow_hold_rank': 15, 'regime_sma': 100, 'min_turnover': 1e7, 'leverage': 1.10},
        {'top_n': 10, 'momentum_window': 126, 'skip_recent_days': 21, 'allow_hold_rank': 20, 'regime_sma': 100, 'min_turnover': 1e7, 'leverage': 1.10},
        {'top_n': 5, 'momentum_window': 126, 'skip_recent_days': 0, 'allow_hold_rank': 15, 'regime_sma': 200, 'min_turnover': 1e7, 'leverage': 1.10},
    ]

    # Pre-build data and signals for all configs (to save time) 
    # The actual SMA and Momentum signals rely on GLOBAL_DF
    # We will pick Config 0 as default since computing 3 copies of GLOBAL_DF is perfectly fine here.
    df_all_configs = []
    market_regimes = []
    for c in param_grid:
        df_c = GLOBAL_DF.copy()
        df_c['Prev_Close'] = df_c.groupby('Ticker')['Close'].shift(c['momentum_window'])
        if c['skip_recent_days'] > 0:
            df_c['Rec_Close'] = df_c.groupby('Ticker')['Close'].shift(c['skip_recent_days'])
            df_c['Momentum_Score'] = (df_c['Rec_Close'] / df_c['Prev_Close']) - 1
        else:
            df_c['Momentum_Score'] = (df_c['Close'] / df_c['Prev_Close']) - 1
            
        df_c['SMA_Trend'] = df_c.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
        df_c['Turnover'] = df_c['Close'] * df_c['Volume']
        df_c['Avg_Turnover20'] = df_c.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
        
        # 60-day realized volatility for risk-adjusted momentum ranking
        df_c['DailyRet'] = df_c.groupby('Ticker')['Close'].pct_change()
        df_c['Vol60'] = df_c.groupby('Ticker')['DailyRet'].transform(lambda x: x.rolling(60).std() * np.sqrt(252))
        
        mdf = build_market_regime(df_c, sma_length=c['regime_sma'])
        df_c = df_c.merge(mdf, on='Date', how='left')
        df_c['Market_Bullish'] = df_c['Market_Bullish'].fillna(False)
        
        df_all_configs.append(df_c)
        market_regimes.append(mdf)

    start_capital = 1_000_000
    current_cash = start_capital
    current_positions = {}
    
    master_equity_curve = []
    yearly_ledgers = []
    
    dates_db = pd.DataFrame({'Date': list(CLOSE_MATRIX.index)}).sort_values('Date').dropna()
    dates_db['YearMonth'] = dates_db['Date'].dt.to_period('M')
    
    print(f"{'Year':<5} | {'Optimized Param ID':<20} | {'Starting Capital':>16} | {'Ending Capital':>16} | {'Run CAGR':>10}")
    print("-" * 78)

    for year in range(2020, 2027):
        target_dates = list(dates_db[dates_db['Date'].dt.year == year].groupby('YearMonth')['Date'].max())
        if not target_dates: continue
        
        best_cfg_idx = 0
        # Rolling 5-year windows => train from [Year - 5] to [Year - 1]
        train_start = f"{year-5}-01-01"
        train_end = f"{year-1}-12-31"
        
        best_sharpe = -1
        for cfg_idx in range(len(param_grid)):
            shp = evaluate_train_sharpe(param_grid[cfg_idx], df_all_configs[cfg_idx], market_regimes[cfg_idx], pd.to_datetime(train_start), pd.to_datetime(train_end))
            if shp > best_sharpe:
                best_sharpe = shp
                best_cfg_idx = cfg_idx

        # Run Live Simulation for Year Y using T+1 engine
        my_config = param_grid[best_cfg_idx]
        df_live = df_all_configs[best_cfg_idx]
        mreg = market_regimes[best_cfg_idx]
        
        # Calculate Starting Capital exactly
        start_eval_cap = current_cash
        for t, pos in current_positions.items():
            start_eval_cap += pos['shares'] * CLOSE_MATRIX.loc[target_dates[0]-pd.Timedelta(days=1), t] if (target_dates[0]-pd.Timedelta(days=1)) in CLOSE_MATRIX.index else pos['entry_price']
            
        final_cash, final_pos, eq_curve, yr_trades = run_year_simulator(year, my_config, start_eval_cap, current_positions.copy(), df_live, mreg, target_dates)
        
        # If no dates traded (e.g. data missing entirely), just carry over
        if eq_curve.empty:
            continue
            
        end_eval_cap = eq_curve['Capital'].iloc[-1]
        cagr = (end_eval_cap / start_eval_cap) - 1
        
        print(f"{year:<5} | {f'Config_{best_cfg_idx}':<20} | {start_eval_cap:>16,.2f} | {end_eval_cap:>16,.2f} | {cagr:>9.2%}")
        
        master_equity_curve.append(eq_curve)
        current_cash = final_cash
        current_positions = final_pos
        
        # DD and Sharpe Calculation for Year
        eq_curve['Return'] = eq_curve['Capital'].pct_change().fillna(0)
        shp = (eq_curve['Return'].mean() / eq_curve['Return'].std()) * np.sqrt(252) if eq_curve['Return'].std() > 0 else 0
        peak = eq_curve['Capital'].cummax()
        dd = ((eq_curve['Capital'] - peak) / peak).min()
        
        yearly_ledgers.append({
            'Year': year,
            'Start_Cap': start_eval_cap,
            'End_Cap': end_eval_cap,
            'Return': cagr,
            'Max_DD': dd,
            'Sharpe': shp,
            'Trades': yr_trades
        })

    print("-" * 78)
    
    # --- FINAL METRICS ---
    full_eq = pd.concat(master_equity_curve).drop_duplicates('Date', keep='last')
    total_years = (full_eq['Date'].max() - full_eq['Date'].min()).days / 365.25
    final_capital = full_eq['Capital'].iloc[-1]
    tot_cagr = (final_capital / start_capital) ** (1 / total_years) - 1
    
    res_df = pd.DataFrame(yearly_ledgers)
    worst_yr = res_df['Return'].min()
    best_yr = res_df['Return'].max()
    prof_years = (res_df['Return'] > 0).mean()
    
    full_peak = full_eq['Capital'].cummax()
    max_total_dd = ((full_eq['Capital'] - full_peak) / full_peak).min()

    print("\n=========================================================================================")
    print("🏆 FINAL LIVE RUN METRICS (2015-2026)")
    print("=========================================================================================")
    print(f"Total Master CAGR:      {tot_cagr:.2%}")
    print(f"Total Max Drawdown:     {max_total_dd:.2%}")
    print(f"Final Capital (10L):    {final_capital:,.2f} INR")
    print(f"Best Year Return:       {best_yr:.2%}")
    print(f"Worst Year Return:      {worst_yr:.2%}")
    print(f"Profitable Years:       {prof_years:.0%}")
    print("=========================================================================================\n")

    # Export equity curve for Monte Carlo
    full_eq.to_csv('wf_equity_curve.csv', index=False)
    print("💾 Saved full equity curve to wf_equity_curve.csv")

    # Outputs
    plt.figure(figsize=(14, 10))
    
    plt.subplot(2, 1, 1)
    plt.plot(full_eq['Date'], full_eq['Capital'], color='blue', linewidth=2)
    plt.yscale('log')
    plt.title('T+1 Live Simulation Equity Curve (Log Scale)')
    plt.ylabel('Capital (INR)')
    plt.grid(True, alpha=0.3)
    
    plt.subplot(2, 1, 2)
    colors = ['green' if x > 0 else 'red' for x in res_df['Return']]
    plt.bar(res_df['Year'].astype(str), res_df['Return'] * 100, color=colors)
    plt.title('Year-by-Year Returns (%)')
    plt.ylabel('Return (%)')
    plt.grid(True, alpha=0.3, axis='y')
    
    for i, v in enumerate(res_df['Return']):
        plt.text(i, (v * 100) + (2 if v > 0 else -5), f"{v*100:.1f}%", ha='center', fontsize=9)

    plt.tight_layout()
    plot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'live_simulation_plot.png')
    plt.savefig(plot_path)
    print(f"📊 Plot saved successfully to: {plot_path}")
    
    # Save ledger text file
    with open('yearly_ledger.md', 'w') as f:
        f.write("### Rolling Walk-Forward Yearly Ledger (T+1 Exec)\n\n")
        f.write("| Year | Start Capital | End Capital | Return | Max DD | Sharpe | Trades |\n")
        f.write("|:---|---:|---:|---:|---:|---:|---:|\n")
        for idx, row in res_df.iterrows():
            f.write(f"| **{row['Year']}** | {row['Start_Cap']:,.0f} | {row['End_Cap']:,.0f} | {row['Return']:.2%} | {row['Max_DD']:.2%} | {row['Sharpe']:.2f} | {row['Trades']} |\n")

if __name__ == "__main__":
    main()
