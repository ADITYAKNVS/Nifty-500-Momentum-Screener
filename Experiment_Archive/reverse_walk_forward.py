import numpy as np
import pandas as pd
import sys
import os
import itertools

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from backtest_momentum_v2 import run_backtest_variant
import warnings
warnings.filterwarnings('ignore')

TRADING_DAYS_PER_YEAR = 252

def compute_metrics(returns_slice):
    if len(returns_slice) < 50:
        return 0, 0, 0
    cum_returns = np.cumprod(1 + returns_slice)
    years = len(returns_slice) / TRADING_DAYS_PER_YEAR
    total_ret = cum_returns.iloc[-1]
    cagr = (total_ret ** (1 / years)) - 1
    mean_ret = np.mean(returns_slice)
    std_ret = np.std(returns_slice)
    sharpe = (mean_ret / std_ret) * np.sqrt(TRADING_DAYS_PER_YEAR) if std_ret > 0 else 0
    running_max = np.maximum.accumulate(cum_returns)
    drawdowns = (cum_returns - running_max) / running_max
    max_dd = np.min(drawdowns)
    return cagr, sharpe, max_dd

def main():
    print("=========================================================================================")
    print("🔥 TRUE REVERSE WALK-FORWARD TEST (COMBATING DATA SNOOPING LEAK)")
    print("=========================================================================================")
    print("1. Running blind grid search optimizing exclusively on TRAIN period: 2021-2026")
    print("2. Freezing the best model parameters.")
    print("3. Testing blindly on TEST period: 2015-2020\n")

    # The Grid
    param_grid = {
        'top_n': [5, 10, 20],
        'momentum_window': [90, 126, 252],
        'skip_recent_days': [0, 21],
        'allow_hold_rank': [None, 15],
        'regime_sma': [100, 200]
    }
    
    keys = list(param_grid.keys())
    combinations = list(itertools.product(*param_grid.values()))
    
    print(f"⚙️ Evaluating {len(combinations)} configurations...\n")
    
    best_cagr = -1
    best_sharpe = -1
    best_train_config = None
    best_train_full_metrics = None
    best_test_full_metrics = None
    
    for idx, combo in enumerate(combinations):
        conf = dict(zip(keys, combo))
        name = f"Grid_{idx}"
        
        # We must add min_turnover to all tests so penny stocks don't ruin it, 
        # but this is a structural constant, not an overfit tuning param.
        conf['min_turnover'] = 1e7
        
        # Add a tiny leverage just to mirror realistic institutional conditions, or keep it 1.0
        conf['leverage'] = 1.0 
        
        res = run_backtest_variant(conf, name)
        if not res or 'Daily_Returns' not in res:
            continue
            
        ret_series = res['Daily_Returns']
        
        # 🚨 STRICT REVERSE SPLIT
        train_ret = ret_series.loc['2021-01-01':]   # Train on 2021-2026
        test_ret = ret_series.loc[:'2020-12-31']    # Test blindly on 2015-2020
        
        tr_cagr, tr_sharpe, tr_dd = compute_metrics(train_ret)
        te_cagr, te_sharpe, te_dd = compute_metrics(test_ret)
        
        # Target: Optimize for Sharpe on the 2021-2026 Training set
        if tr_sharpe > best_sharpe:
            best_sharpe = tr_sharpe
            best_cagr = tr_cagr
            best_train_config = conf
            best_train_full_metrics = (tr_cagr, tr_sharpe, tr_dd)
            # Record what WOULD happen on the unseen 2015-2020 test data
            best_test_full_metrics = (te_cagr, te_sharpe, te_dd)

    print("=========================================================================================")
    print("🏆 BEST MODEL (OPTIMIZED ONLY ON 2021-2026)")
    print("=========================================================================================")
    print(f"Parameters chosen by the algorithm dynamically:")
    for k, v in best_train_config.items():
        print(f"  - {k}: {v}")
    
    tr_c, tr_s, tr_d = best_train_full_metrics
    te_c, te_s, te_d = best_test_full_metrics
    
    print(f"\n📊 PERFORMANCE SUMMARY")
    print(f"{'Period':<20} | {'CAGR':>10} | {'SHARPE':>10} | {'MAX DD':>10}")
    print("-" * 58)
    print(f"{'TRAIN (2021-2026)':<20} | {tr_c:>9.2%} | {tr_s:>10.2f} | {tr_d:>9.2%}")
    print(f"{'(BLIND) TEST 15-20':<20} | {te_c:>9.2%} | {te_s:>10.2f} | {te_d:>9.2%}")
    print("=========================================================================================\n")

if __name__ == "__main__":
    main()
