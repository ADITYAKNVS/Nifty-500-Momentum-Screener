import sys
sys.path.append('.')
from backtest_momentum_v2 import run_backtest_variant, GLOBAL_DF

def run_exp(name, conf):
    res = run_backtest_variant(conf, name)
    if res:
        print(f"{name:<25} | {res['CAGR']:.2%} | {res['Max_DD']:.2%} | {res['Sharpe']:.2f}")

print("Run                       | CAGR    | Max DD  | Sharpe")
print("-" * 60)
run_exp('Baseline V2 (Top 20)', {'regime_sma': 100})
run_exp('Concentrated (Top 10)', {'regime_sma': 100, 'top_n': 10})
run_exp('Hyper-Concentrated (Top 5)', {'regime_sma': 100, 'top_n': 5})
run_exp('Faster Mom (90d) + Top 10', {'regime_sma': 100, 'top_n': 10, 'momentum_window': 90})
run_exp('Slower Mom (200d) + Top 10', {'regime_sma': 100, 'top_n': 10, 'momentum_window': 200})
run_exp('Top 5 + Fast Regime', {'regime_sma': 50, 'top_n': 5})
run_exp('Top 10 + No Regime Filter', {'regime_sma': 1, 'top_n': 10}) # effectively always bullish
