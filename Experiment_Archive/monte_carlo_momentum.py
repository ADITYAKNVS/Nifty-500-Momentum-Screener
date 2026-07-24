import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys
import os
import warnings

warnings.filterwarnings('ignore')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from backtest_momentum_v2 import run_backtest_variant

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
TRADING_DAYS_PER_YEAR = 252

GOD_MODE_CONFIG = {
    'regime_sma': 100, 'top_n': 5, 'momentum_window': 252,
    'skip_recent_days': 21, 'allow_hold_rank': 15, 'min_turnover': 1e7,
    'leverage': 1.10
}

# Pass criteria
PASS_MEDIAN_CAGR = 0.25       # Median CAGR > 25%
PASS_WORST_DD    = -0.50      # Worst-case DD > -50%
PASS_WORST_CAGR  = 0.00      # No collapse (worst CAGR > 0%)


# ══════════════════════════════════════════════════════════════
# TEST 1 — RETURN NOISE INJECTION (most important)
# ══════════════════════════════════════════════════════════════
def monte_carlo_noise(returns, n_sim=200):
    """
    Add small N(0, 0.005) noise to each daily return.
    Simulates execution slippage, fill timing, spread variation.
    """
    results = []
    ret_vals = returns.values if hasattr(returns, 'values') else returns

    for _ in range(n_sim):
        noisy = ret_vals + np.random.normal(0, 0.005, len(ret_vals))
        eq = np.cumprod(1 + noisy)

        years = len(eq) / TRADING_DAYS_PER_YEAR
        cagr = (eq[-1] ** (1 / years)) - 1 if eq[-1] > 0 else -1
        dd = (eq / np.maximum.accumulate(eq) - 1).min()

        results.append((cagr, dd))

    return pd.DataFrame(results, columns=['CAGR', 'Max_DD'])


# ══════════════════════════════════════════════════════════════
# TEST 2 — TRADE SHUFFLE (very powerful)
# ══════════════════════════════════════════════════════════════
def monte_carlo_shuffle(trade_returns, n_sim=200):
    """
    Same trades, different order.
    Tests dependency on lucky sequencing.
    """
    results = []
    ret_vals = trade_returns.values if hasattr(trade_returns, 'values') else trade_returns

    for _ in range(n_sim):
        shuffled = np.random.permutation(ret_vals)
        eq = np.cumprod(1 + shuffled)

        years = len(eq) / TRADING_DAYS_PER_YEAR
        cagr = (eq[-1] ** (1 / years)) - 1 if eq[-1] > 0 else -1
        dd = (eq / np.maximum.accumulate(eq) - 1).min()

        results.append((cagr, dd))

    return pd.DataFrame(results, columns=['CAGR', 'Max_DD'])


# ══════════════════════════════════════════════════════════════
# TEST 3 — CRASH INJECTION (real stress)
# ══════════════════════════════════════════════════════════════
def monte_carlo_crash(returns, n_sim=100):
    """
    Inject a random 5-day -10%/day crash at a random point.
    Tests recovery and worst-case survivability.
    """
    results = []
    ret_vals = returns.values.copy() if hasattr(returns, 'values') else returns.copy()

    for _ in range(n_sim):
        ret = ret_vals.copy()

        # Inject crash at random position (leave room for 5 days)
        crash_day = np.random.randint(0, max(1, len(ret) - 5))
        end_day = min(crash_day + 5, len(ret))
        ret[crash_day:end_day] -= 0.10  # -10% for 5 days

        eq = np.cumprod(1 + ret)

        years = len(eq) / TRADING_DAYS_PER_YEAR
        cagr = (eq[-1] ** (1 / years)) - 1 if eq[-1] > 0 else -1
        dd = (eq / np.maximum.accumulate(eq) - 1).min()

        results.append((cagr, dd))

    return pd.DataFrame(results, columns=['CAGR', 'Max_DD'])


# ══════════════════════════════════════════════════════════════
# REPORTING
# ══════════════════════════════════════════════════════════════
def print_test_summary(name, df):
    """Print a clean summary table for one test."""
    cagrs = df['CAGR']
    dds = df['Max_DD']

    med_cagr  = cagrs.median()
    p5_cagr   = cagrs.quantile(0.05)
    p95_cagr  = cagrs.quantile(0.95)
    worst_cagr = cagrs.min()

    med_dd    = dds.median()
    worst_dd  = dds.min()
    pct_dd_bad = (dds < -0.50).mean() * 100

    print(f"  {'Metric':<20} | {'Value':>10}")
    print(f"  {'-'*20}-+-{'-'*10}")
    print(f"  {'Median CAGR':<20} | {med_cagr:>9.2%}")
    print(f"  {'5th pctl CAGR':<20} | {p5_cagr:>9.2%}")
    print(f"  {'95th pctl CAGR':<20} | {p95_cagr:>9.2%}")
    print(f"  {'Worst CAGR':<20} | {worst_cagr:>9.2%}")
    print(f"  {'Median Max DD':<20} | {med_dd:>9.2%}")
    print(f"  {'Worst Max DD':<20} | {worst_dd:>9.2%}")
    print(f"  {'% sims DD < -50%':<20} | {pct_dd_bad:>9.1f}%")

    # Per-test pass/fail
    passes = []
    passes.append(("Median CAGR > 25%", med_cagr > PASS_MEDIAN_CAGR))
    passes.append(("Worst DD > -50%", worst_dd > PASS_WORST_DD))
    passes.append(("No collapse (CAGR>0)", worst_cagr > PASS_WORST_CAGR))

    print()
    all_pass = True
    for label, ok in passes:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {label}")
        if not ok:
            all_pass = False

    return all_pass


def plot_distributions(results_dict, save_path):
    """Plot CAGR and DD distributions for all 3 tests."""
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    colors = {'Noise Injection': '#3498db', 'Trade Shuffle': '#2ecc71', 'Crash Injection': '#e74c3c'}

    for col_idx, (name, df) in enumerate(results_dict.items()):
        color = colors[name]

        # CAGR distribution
        ax = axes[0, col_idx]
        cagr_vals = df['CAGR'] * 100
        n_bins_cagr = min(40, max(5, int(cagr_vals.max() - cagr_vals.min()) * 10)) if cagr_vals.max() != cagr_vals.min() else 5
        ax.hist(cagr_vals, bins=n_bins_cagr, alpha=0.75, color=color, edgecolor='white', linewidth=0.5)
        ax.axvline(cagr_vals.median(), color='black', linestyle='--', linewidth=2, label=f"Median: {df['CAGR'].median():.1%}")
        ax.axvline(25, color='red', linestyle=':', linewidth=1.5, label='25% threshold')
        ax.set_title(f'{name} — CAGR Distribution', fontweight='bold')
        ax.set_xlabel('CAGR (%)')
        ax.set_ylabel('Count')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        # Max DD distribution
        ax = axes[1, col_idx]
        dd_vals = df['Max_DD'] * 100
        n_bins_dd = min(40, max(5, int(abs(dd_vals.max() - dd_vals.min())) * 10)) if dd_vals.max() != dd_vals.min() else 5
        ax.hist(dd_vals, bins=n_bins_dd, alpha=0.75, color=color, edgecolor='white', linewidth=0.5)
        ax.axvline(dd_vals.median(), color='black', linestyle='--', linewidth=2, label=f"Median: {df['Max_DD'].median():.1%}")
        ax.axvline(-50, color='red', linestyle=':', linewidth=1.5, label='-50% threshold')
        ax.set_title(f'{name} — Max DD Distribution', fontweight='bold')
        ax.set_xlabel('Max Drawdown (%)')
        ax.set_ylabel('Count')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    plt.suptitle('Monte Carlo Robustness Tests — God Mode Strategy', fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    print(f"\n📊 Distributions saved to: {save_path}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
    np.random.seed(42)

    print("=" * 70)
    print("🎯 MONTE CARLO ROBUSTNESS TESTS — GOD MODE STRATEGY")
    print("=" * 70)
    print("Testing: Will this strategy survive slightly different realities?\n")

    # 1. Extract daily returns from God Mode backtest
    print("🚀 Running God Mode backtest to extract daily returns...\n")
    res = run_backtest_variant(GOD_MODE_CONFIG, "God Mode (MC Source)")

    if not res or 'Daily_Returns' not in res:
        print("❌ Failed to extract daily returns. Aborting.")
        return

    daily_returns = res['Daily_Returns']
    baseline_cagr = res['CAGR']
    baseline_dd = res['Max_DD']

    print(f"\n📈 Baseline God Mode: CAGR={baseline_cagr:.2%}  Max DD={baseline_dd:.2%}")
    print(f"   Daily returns: {len(daily_returns)} trading days\n")

    results_dict = {}
    test_verdicts = {}

    # ─── TEST 1: Noise Injection ───
    print("=" * 70)
    print("🧪 TEST 1 — RETURN NOISE INJECTION (200 sims)")
    print("   Adding N(0, 0.5%) noise to each daily return")
    print("=" * 70)

    df_noise = monte_carlo_noise(daily_returns, n_sim=200)
    results_dict['Noise Injection'] = df_noise
    test_verdicts['Noise Injection'] = print_test_summary("Noise Injection", df_noise)

    # ─── TEST 2: Trade Shuffle ───
    print()
    print("=" * 70)
    print("🧪 TEST 2 — TRADE SHUFFLE (200 sims)")
    print("   Same trades, random order — tests lucky sequence dependency")
    print("=" * 70)

    df_shuffle = monte_carlo_shuffle(daily_returns, n_sim=200)
    results_dict['Trade Shuffle'] = df_shuffle
    test_verdicts['Trade Shuffle'] = print_test_summary("Trade Shuffle", df_shuffle)

    # ─── TEST 3: Crash Injection ───
    print()
    print("=" * 70)
    print("🧪 TEST 3 — CRASH INJECTION (100 sims)")
    print("   Injecting random 5-day, -10%/day crash")
    print("=" * 70)

    df_crash = monte_carlo_crash(daily_returns, n_sim=100)
    results_dict['Crash Injection'] = df_crash
    test_verdicts['Crash Injection'] = print_test_summary("Crash Injection", df_crash)

    # ─── FINAL VERDICT ───
    print()
    print("=" * 70)
    print("🔥 FINAL VERDICT")
    print("=" * 70)

    all_passed = True
    for test_name, passed in test_verdicts.items():
        icon = "✅" if passed else "❌"
        status = "PASS" if passed else "FAIL"
        print(f"  {icon} {test_name}: {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("  🏆 STRATEGY IS ROBUST — All Monte Carlo tests passed!")
    else:
        print("  ⚠️  STRATEGY HAS WEAKNESSES — Review failed tests above.")

    print("=" * 70)

    # Save plots
    plot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monte_carlo_robustness.png')
    plot_distributions(results_dict, plot_path)


if __name__ == "__main__":
    main()
