import numpy as np
import pandas as pd
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from backtest_momentum_v2 import GLOBAL_DF, CLOSE_MATRIX, build_market_regime
import warnings
warnings.filterwarnings('ignore')

def evaluate_vectorized(config, df_all, target_dates):
    min_turnover = config.get('min_turnover', 1e7)
    leverage = config.get('leverage', 1.0)
    top_n = config['top_n']
    
    ROUND_TRIP_COST = 0.0035
    ONE_WAY_COST = ROUND_TRIP_COST / 2
    
    prev_weights = {}
    eq_curve = []
    
    for idx, reb_date in enumerate(target_dates):
        day_data = df_all[df_all['Date'] == reb_date].copy()
        market_is_bullish = day_data['Market_Bullish'].iloc[0] if not day_data.empty else False
        
        target_portfolio = []
        if market_is_bullish:
            day_data = day_data.dropna(subset=['Momentum_Score', 'SMA_Trend', 'Avg_Turnover20'])
            if 'Vol60' in day_data.columns:
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
            
            # Using HOLD BUFFER if allow_hold_rank is configured
            allow_hold_rank = config.get('allow_hold_rank', None)
            if allow_hold_rank is not None:
                held_tickers = set(prev_weights.keys())
                buffer_eligible = eligible['Ticker'].head(allow_hold_rank).tolist()
                to_keep = [t for t in buffer_eligible if t in held_tickers]
                to_add = [t for t in eligible['Ticker'].tolist() if t not in to_keep]
                target_portfolio = to_keep + to_add[:max(0, top_n - len(to_keep))]
            else:
                target_portfolio = eligible['Ticker'].head(top_n).tolist()
            
        # 1. Determine new weights (Equal Weighting for simplicity)
        target_weights = {}
        if len(target_portfolio) > 0:
            w = 1.0 / len(target_portfolio)
            for t in target_portfolio:
                target_weights[t] = w
                
        # 2. Calculate Turnover % (Sum of absolute weight changes)
        all_tickers = set(prev_weights.keys()).union(set(target_weights.keys()))
        turnover = 0.0
        for t in all_tickers:
            old_w = prev_weights.get(t, 0.0)
            new_w = target_weights.get(t, 0.0)
            turnover += abs(new_w - old_w)
            
        # 3. Calculate friction penalty for this rebalance
        friction_penalty = turnover * ONE_WAY_COST * leverage
                
        # 4. Generate vectorized returns for the holding period
        if idx < len(target_dates)-1:
            next_date = target_dates[idx+1]
            sub_idx = (CLOSE_MATRIX.index > reb_date) & (CLOSE_MATRIX.index <= next_date)
            period_dates = CLOSE_MATRIX.index[sub_idx]
            
            if len(target_portfolio) > 0:
                # Get mean daily returns of the held assets
                daily_rets = CLOSE_MATRIX.loc[period_dates, target_portfolio].pct_change().fillna(0).mean(axis=1) * leverage
            else:
                # Sitting in cash
                daily_rets = pd.Series(0.0, index=period_dates)
                
            # 5. Apply the friction penalty to the FIRST day of the holding period
            if len(daily_rets) > 0:
                daily_rets.iloc[0] -= friction_penalty
                
            eq_curve.append(daily_rets)

        # Update weights for next iteration
        prev_weights = target_weights.copy()

    if not eq_curve:
        return 0, 0, 0
    
    full_ret = pd.concat(eq_curve)
    std = full_ret.std()
    shp = (full_ret.mean() / std) * np.sqrt(252) if std > 0 else 0
    cum_ret = np.cumprod(1 + full_ret.values)
    
    years = len(full_ret) / 252.0
    cagr = cum_ret[-1] ** (1 / years) - 1
    
    peaks = np.maximum.accumulate(cum_ret)
    dd = np.min((cum_ret - peaks) / peaks)
    
    return cagr, shp, dd


def run_simulation(config, target_dates):
    df_c = GLOBAL_DF.copy()
    df_c['Prev_Close'] = df_c.groupby('Ticker')['Close'].shift(config['momentum_window'])
    if config['skip_recent_days'] > 0:
        df_c['Rec_Close'] = df_c.groupby('Ticker')['Close'].shift(config['skip_recent_days'])
        df_c['Momentum_Score'] = (df_c['Rec_Close'] / df_c['Prev_Close']) - 1
    else:
        df_c['Momentum_Score'] = (df_c['Close'] / df_c['Prev_Close']) - 1
        
    df_c['SMA_Trend'] = df_c.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
    df_c['Turnover'] = df_c['Close'] * df_c['Volume']
    df_c['Avg_Turnover20'] = df_c.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    df_c['DailyRet'] = df_c.groupby('Ticker')['Close'].pct_change().fillna(0)
    df_c['Vol60'] = df_c.groupby('Ticker')['DailyRet'].transform(lambda x: x.rolling(60).std() * np.sqrt(252)).fillna(0.3)
    
    mdf = build_market_regime(df_c, sma_length=config['regime_sma'])
    df_c = df_c.merge(mdf, on='Date', how='left')
    df_c['Market_Bullish'] = df_c['Market_Bullish'].fillna(False)

    return evaluate_vectorized(config, df_c, target_dates)

def main():
    print("===================================================================")
    print("🛠️  REALISTIC ROBUSTNESS SWEEP (Top N, Mom Window, Skip Days, SMA)")
    print("     (Includes exact 0.35% round-trip trading friction)")
    print("===================================================================")
    
    dates_db = pd.DataFrame({'Date': list(CLOSE_MATRIX.index)}).sort_values('Date').dropna()
    dates_db = dates_db[(dates_db['Date'] >= '2015-01-01') & (dates_db['Date'] <= '2026-12-31')]
    dates_db['YearMonth'] = dates_db['Date'].dt.to_period('M')
    target_dates = list(dates_db.groupby('YearMonth')['Date'].max())
    
    baseline_cfg = {
        'top_n': 5, 
        'allow_hold_rank': 15,
        'momentum_window': 252, 
        'skip_recent_days': 21, 
        'regime_sma': 100, 
        'min_turnover': 1e7, 'leverage': 1.00 # Set 1x for cleaner isolated math
    }
    
    params_to_test = {
        'top_n': [3, 5, 7],
        'allow_hold_rank': [None, 10, 15, 20],  # test churn buffer
        'momentum_window': [126, 189, 252, 315],
        'skip_recent_days': [0, 21, 31],
        'regime_sma': [50, 100, 150]
    }
    
    c, s, d = run_simulation(baseline_cfg, target_dates)
    print(f"BASELINE METRICS => CAGR: {c:.2%}, Sharpe: {s:.2f}, Max DD: {d:.2%}\n")
    
    for param_name, values in params_to_test.items():
        print(f"--- Sweeping {param_name} ---")
        for val in values:
            if val == baseline_cfg.get(param_name):
                print(f" {param_name:<18} = {str(val):>6} | CAGR: {c:>7.2%} | Shp: {s:>4.2f} | Max DD: {d:>7.2%} (Baseline)")
                continue
            
            test_cfg = baseline_cfg.copy()
            test_cfg[param_name] = val
            
            tc, ts, td = run_simulation(test_cfg, target_dates)
            delta_cagr = tc - c
            print(f" {param_name:<18} = {str(val):>6} | CAGR: {tc:>7.2%} | Shp: {ts:>4.2f} | Max DD: {td:>7.2%} | Delta: {delta_cagr:>+5.2%}")
        print("")

if __name__ == '__main__':
    main()
