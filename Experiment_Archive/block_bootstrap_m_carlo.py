import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os
import warnings
from backtest_momentum import run_momentum_backtest

warnings.filterwarnings('ignore')

MONTHS_PER_YEAR = 12

def generate_block_bootstrap(returns, N_length, min_block=3, max_block=6):
    """
    Generates a synthetic return series of length N_length by randomly 
    sampling contiguous blocks (with replacement) from the original returns.
    """
    synthetic_returns = []
    max_idx = len(returns) - 1
    
    while len(synthetic_returns) < N_length:
        block_len = np.random.randint(min_block, max_block + 1)
        # Ensure we don't start a block too close to the end
        if max_idx - block_len + 1 <= 0:
            start_idx = 0
            block_len = len(returns)
        else:
            start_idx = np.random.randint(0, max_idx - block_len + 1)
        
        block = returns[start_idx : start_idx + block_len]
        synthetic_returns.extend(block)
        
    return np.array(synthetic_returns[:N_length])

def run_block_bootstrap_test(trade_returns, n_sims=1000):
    """
    Runs a Block Bootstrap Monte Carlo test on sequential returns.
    """
    print(f"\n⚙️ Running {n_sims} Block Bootstrap Simulations (Monthly Returns)...")
    
    trade_returns = np.array(trade_returns)
    n_trades = len(trade_returns)
    
    if n_trades == 0:
        print("❌ Error: No returns provided.")
        return
        
    print(f"📊 Input: {n_trades} historical periods.")
    print("🧩 Block Size: 3 to 6 months (Preserving Market Regimes)")
    
    sim_cagrs = []
    sim_max_dds = []
    sim_sharpes = []
    
    curves_to_plot = min(30, n_sims)
    equity_curves = []
    
    for i in range(n_sims):
        # Build synthetic path via Block Bootstrapping
        synth_ret = generate_block_bootstrap(trade_returns, n_trades, min_block=3, max_block=6)
        
        # Build equity curve
        equity = np.cumprod(1 + synth_ret)
        
        # Metrics
        years = n_trades / MONTHS_PER_YEAR
        cagr = (equity[-1] ** (1 / years)) - 1 if (equity[-1] > 0 and years > 0) else -1
        
        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max) / running_max
        max_dd = drawdown.min()
        
        # Monthly sharpe annualized
        sharpe = np.sqrt(MONTHS_PER_YEAR) * np.mean(synth_ret) / (np.std(synth_ret) + 1e-9)
        
        sim_cagrs.append(cagr)
        sim_max_dds.append(max_dd)
        sim_sharpes.append(sharpe)
        
        if i < curves_to_plot:
            full_curve = np.insert(equity, 0, 1.0)
            equity_curves.append(full_curve)
            
    sim_cagrs = np.array(sim_cagrs)
    sim_max_dds = np.array(sim_max_dds)
    sim_sharpes = np.array(sim_sharpes)
    
    # 5. OUTPUT SUMMARY
    median_cagr = np.median(sim_cagrs)
    p5_cagr     = np.percentile(sim_cagrs, 5)
    worst_cagr  = np.min(sim_cagrs)
    
    median_dd   = np.median(sim_max_dds)
    worst_dd    = np.min(sim_max_dds)
    
    pct_lost_money = np.mean(sim_cagrs < 0) * 100
    
    print("\n" + "=" * 55)
    print("🎯 BLOCK BOOTSTRAP MONTE CARLO RESULTS")
    print("=" * 55)
    print(f"  Median CAGR         : {median_cagr:>10.2%}")
    print(f"  5th Percentile CAGR : {p5_cagr:>10.2%}")
    print(f"  Worst CAGR          : {worst_cagr:>10.2%}")
    print("-" * 55)
    print(f"  Median Max DD       : {median_dd:>10.2%}")
    print(f"  Worst Max DD        : {worst_dd:>10.2%}")
    print("-" * 55)
    print(f"  Sims losing money   : {pct_lost_money:>9.1f}%")
    print("=" * 55)
    
    # 7. INTERPRETATION LOGIC
    print("\n🧠 INTERPRETATION:")
    if median_cagr > 0.15 and worst_cagr > 0 and (worst_dd > -0.60):
        print("→ Strategy is robust across alternate realistic histories")
        print("  (It survived extreme regime shuffling while keeping sequence structures intact.)")
    else:
        print("→ Strategy is fragile to regime variation")
        print("  (It is highly dependent on the singular, specific chronological history it experienced.)")
        
    print("=" * 55)
    
    # 6. VISUALIZATION
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    
    for curve in equity_curves:
        axes[0].plot(curve, alpha=0.3, linewidth=1.5)
    
    axes[0].set_title(f"Random 30 Equity Curves (from {n_sims} Block Resamples)", fontweight='bold')
    axes[0].set_xlabel("Months Simulated")
    axes[0].set_ylabel("Equity Multiplier")
    axes[0].grid(True, alpha=0.3)
    
    n_bins = 5 if np.isclose(np.max(sim_cagrs), np.min(sim_cagrs)) else max(15, int(len(sim_cagrs)/15))
    axes[1].hist(sim_cagrs * 100, bins=n_bins, color='#e67e22', edgecolor='white', alpha=0.8)
    axes[1].axvline(median_cagr * 100, color='red', linestyle='dashed', linewidth=2, label=f"Median: {median_cagr:.1%}")
    axes[1].axvline(p5_cagr * 100, color='black', linestyle='dotted', linewidth=2, label=f"5th Pctl: {p5_cagr:.1%}")
    
    axes[1].set_title("Distribution of Final CAGRs", fontweight='bold')
    axes[1].set_xlabel("CAGR (%)")
    axes[1].set_ylabel("Frequency")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'block_bootstrap_plot.png')
    plt.savefig(plot_path, dpi=150)
    print(f"\n📊 Visualization saved to: {plot_path}")

def main():
    print("📥 Extracting true Monthly Returns from Momentum V1 backtest...")
    # Get the monthly basket returns 
    # Momentum V1 generates robust monthly returns via run_momentum_backtest()
    # If the user has live output hidden, it will still return the series perfectly.
    monthly_returns = run_momentum_backtest()
    
    if monthly_returns is None or len(monthly_returns) == 0:
         print("❌ Failed to load returns. Aborting.")
         return
         
    run_block_bootstrap_test(monthly_returns.values, n_sims=1000)

if __name__ == "__main__":
    main()
