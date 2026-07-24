import numpy as np
import pandas as pd
import sys
import os

# Ensure local dir is tracked
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from backtest_momentum_v2 import run_backtest_variant

# Suppress pandas indexing warnings if any
import warnings
warnings.filterwarnings('ignore')

variants = {
    'V1 Baseline (Top 20)': {
        'regime_sma': 200, 'top_n': 20, 'momentum_window': 126
    },
    'Run B (SMA100 Regime)': {
        'regime_sma': 100, 'top_n': 20, 'momentum_window': 126
    },
    'Run H (God Mode Top 5)': {
        'regime_sma': 100, 'top_n': 5, 'momentum_window': 252, 
        'skip_recent_days': 21, 'allow_hold_rank': 15, 'min_turnover': 1e7
    },
    'Run I (God Mode 1.1x)': {
        'regime_sma': 100, 'top_n': 5, 'momentum_window': 252, 
        'skip_recent_days': 21, 'allow_hold_rank': 15, 'min_turnover': 1e7, 'leverage': 1.10
    }
}

TRADING_DAYS_PER_YEAR = 252

def compute_metrics(returns_slice):
    if len(returns_slice) < 50:
        return 0, 0, 0
    cum_returns = np.cumprod(1 + returns_slice)
    
    # Time in years based on literal business days
    years = len(returns_slice) / TRADING_DAYS_PER_YEAR
    
    # CAGR
    total_ret = cum_returns.iloc[-1]
    cagr = (total_ret ** (1 / years)) - 1
    
    # Sharpe
    mean_ret = np.mean(returns_slice)
    std_ret = np.std(returns_slice)
    sharpe = (mean_ret / std_ret) * np.sqrt(TRADING_DAYS_PER_YEAR) if std_ret > 0 else 0
    
    # Max DD
    running_max = np.maximum.accumulate(cum_returns)
    drawdowns = (cum_returns - running_max) / running_max
    max_dd = np.min(drawdowns)
    
    return cagr, sharpe, max_dd

def main():
    print("🚀 Extracting full 11-year daily equity curves for Walk-Forward Analysis...\n")
    
    results = {}
    
    for name, conf in variants.items():
        res = run_backtest_variant(conf, name)
        if not res or 'Daily_Returns' not in res:
            print(f"❌ Failed to extract daily returns for {name}")
            return
            
        ret_series = res['Daily_Returns']
        
        # Slicing
        train_ret = ret_series.loc[:'2020-12-31']
        test_ret = ret_series.loc['2021-01-01':]
        
        # Computing metrics
        tr_cagr, tr_sharpe, tr_dd = compute_metrics(train_ret)
        te_cagr, te_sharpe, te_dd = compute_metrics(test_ret)
        
        results[name] = {
            'Train': (tr_cagr, tr_sharpe, tr_dd),
            'Test': (te_cagr, te_sharpe, te_dd)
        }

    print("=======================================================================================================")
    print("📈 WALK-FORWARD ANALYSIS: TRAIN (2015-2020) vs TEST OOS (2021-2026)")
    print("=======================================================================================================")
    print(f"{'Strategy Name':<25} | {'TRAIN CAGR':>10} | {'TRAIN DD':>10} | {'TRAIN SHARPE':>12} || {'TEST CAGR':>10} | {'TEST DD':>10} | {'TEST SHARPE':>11}")
    print("-" * 103)
    
    for name, data in results.items():
        tr = data['Train']
        te = data['Test']
        print(f"{name:<25} | {tr[0]:>9.2%} | {tr[2]:>9.2%} | {tr[1]:>12.2f} || {te[0]:>9.2%} | {te[2]:>9.2%} | {te[1]:>11.2f}")
        
    print("=======================================================================================================\n")

if __name__ == "__main__":
    main()
