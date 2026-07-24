import pandas as pd
import numpy as np
from backtest_momentum_v2 import run_backtest_variant
import warnings
warnings.filterwarnings('ignore')

def main():
    print("🚀 RUNNING 2D SENSITIVITY GRID (9 RUNS) 🚀")
    print("Base: God Mode 1.1x (Skip 21, Hold 15, SMA 100, Turnover > 1Cr)\n")

    BASE_CONFIG = {
        'top_n': 5,
        'momentum_window': 252,
        'skip_recent_days': 21,
        'allow_hold_rank': 15,
        'regime_sma': 100,
        'min_turnover': 1e7,
        'leverage': 1.10
    }

    top_ns = [3, 5, 7]
    mom_wins = [189, 252, 315]

    results = []
    total = len(top_ns) * len(mom_wins)
    count = 1

    for n in top_ns:
        for mw in mom_wins:
            print(f"[{count}/{total}] Running Top {n} | Window {mw} Days...")
            cfg = BASE_CONFIG.copy()
            cfg['top_n'] = n
            cfg['momentum_window'] = mw
            
            # run_backtest_variant returns metrics dict for logging
            # Wait, our modified run_backtest_variant in v2 returns: 
            # (daily_returns_pd_series, total_trades) actually?
            # Let me just run it and calculate metrics here if it doesn't return the dict.
            # In backtest_momentum_v2.py, run_backtest_variant signature ends with:
            # return full_ret
            # So it returns a pandas series of daily returns!
            
            full_ret = run_backtest_variant(cfg, f"Top{n}_Win{mw}")
            
            results.append({
                'Top_N': n,
                'Mom_Window': mw,
                'CAGR_Pct': full_ret['CAGR'] * 100,
                'Sharpe': full_ret['Sharpe'],
                'Max_DD_Pct': full_ret['Max_DD'] * 100
            })
            count += 1

    df = pd.DataFrame(results)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.expand_frame_repr', False)

    print("\n=======================================================")
    print("🔥 2D SENSITIVITY GRID: CAGR (%) 🔥")
    print("=======================================================")
    pivot_cagr = df.pivot(index='Top_N', columns='Mom_Window', values='CAGR_Pct')
    pivot_cagr = pivot_cagr.round(2).applymap(lambda x: f"{x:.2f}%")
    pivot_cagr.columns.name = "Momentum Window (Days)"
    print(pivot_cagr)

    print("\n=======================================================")
    print("🎯 2D SENSITIVITY GRID: SHARPE RATIO 🎯")
    print("=======================================================")
    pivot_sharpe = df.pivot(index='Top_N', columns='Mom_Window', values='Sharpe')
    pivot_sharpe = pivot_sharpe.round(2)
    pivot_sharpe.columns.name = "Momentum Window (Days)"
    print(pivot_sharpe)

    print("\n=======================================================")
    print("📉 2D SENSITIVITY GRID: MAX DRAWDOWN (%) 📉")
    print("=======================================================")
    pivot_dd = df.pivot(index='Top_N', columns='Mom_Window', values='Max_DD_Pct')
    pivot_dd = pivot_dd.round(2).applymap(lambda x: f"{x:.2f}%")
    pivot_dd.columns.name = "Momentum Window (Days)"
    print(pivot_dd)

if __name__ == "__main__":
    main()
