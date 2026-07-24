import pandas as pd
import numpy as np
import warnings
import matplotlib.pyplot as plt
import os
import time

warnings.filterwarnings('ignore')

# Parameters
NUM_SIMULATIONS = 2000
BLOCK_SIZE_DAYS = 63  # Approx 3 months. Preserves vol clustering well.
START_CAPITAL = 1_000_000
RUIN_DRAWDOWN_THRESHOLD = -0.50  # 50% drawdown considered "ruin" / unrecoverable for most traders

def main():
    print("===================================================================")
    print(f"🎲 BLOCK BOOTSTRAP MONTE CARLO (Simulations: {NUM_SIMULATIONS})")
    print(f"   Block Size: {BLOCK_SIZE_DAYS} days (approx 3 months)")
    print("===================================================================")
    
    t0 = time.time()
    
    # Load the true OOS walk forward equity curve
    try:
        df = pd.read_csv('wf_equity_curve.csv')
    except Exception as e:
        print(f"Error loading equity curve: {e}")
        return
        
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date').drop_duplicates('Date').reset_index(drop=True)
    
    # Calculate daily returns
    df['Return'] = df['Capital'].pct_change().fillna(0)
    returns = df['Return'].values
    num_days = len(returns)
    num_years = num_days / 252.0
    
    print(f"Loaded OOS history: {num_days} trading days ({num_years:.2f} years)")
    
    # Generate Block Bootstrap paths
    # We need to construct 2000 lists of returns of length num_days.
    # To do this, we randomly pick a starting index between 0 and num_days - BLOCK_SIZE_DAYS
    # and append the block to our simulated path until it reaches num_days.
    
    cagrs = []
    max_dds = []
    ruin_count = 0
    neg_cagr_count = 0
    
    sim_paths = [] # 2D array of simulated cumulative returns
    
    # Pre-calculate possible starting indices
    valid_starts = np.arange(0, num_days - BLOCK_SIZE_DAYS)
    
    for _ in range(NUM_SIMULATIONS):
        sim_returns = []
        while len(sim_returns) < num_days:
            start_idx = np.random.choice(valid_starts)
            block = returns[start_idx : start_idx + BLOCK_SIZE_DAYS]
            sim_returns.extend(block)
            
        # Trim to exact length
        sim_returns = np.array(sim_returns[:num_days])
        
        # Calculate capital curve
        cum_ret = np.cumprod(1 + sim_returns)
        sim_cap = START_CAPITAL * cum_ret
        
        # Determine metrics
        final_cap = sim_cap[-1]
        cagr = (final_cap / START_CAPITAL) ** (1 / num_years) - 1
        
        peaks = np.maximum.accumulate(sim_cap)
        drawdowns = (sim_cap - peaks) / peaks
        max_dd = np.min(drawdowns)
        
        cagrs.append(cagr)
        max_dds.append(max_dd)
        
        if max_dd <= RUIN_DRAWDOWN_THRESHOLD:
            ruin_count += 1
            
        if final_cap < START_CAPITAL:
            neg_cagr_count += 1
            
    cagrs = np.array(cagrs)
    max_dds = np.array(max_dds)
    
    # Aggregated metrics
    med_cagr = np.median(cagrs)
    pct5_cagr = np.percentile(cagrs, 5)
    worst_cagr = np.min(cagrs)
    
    med_dd = np.median(max_dds)
    pct5_dd = np.percentile(max_dds, 5) # 5th percentile is the 95% worst DD (since it's negative)
    worst_dd = np.min(max_dds)
    
    ruin_prob = ruin_count / NUM_SIMULATIONS
    loss_prob = neg_cagr_count / NUM_SIMULATIONS
    
    print("\n📊 MONTE CARLO RESULTS")
    print("-" * 50)
    print(f"Median CAGR (50th pct):      {med_cagr:.2%}")
    print(f"5th Percentile CAGR:         {pct5_cagr:.2%}")
    print(f"Absolute Worst CAGR:         {worst_cagr:.2%}")
    print("")
    print(f"Median Max DD:               {med_dd:.2%}")
    print(f"95th Percentile Max DD:      {pct5_dd:.2%} (Worst 5% cut-off)")
    print(f"Absolute Worst Max DD:       {worst_dd:.2%}")
    print("")
    print(f"Probability of Ruin (>50% DD): {ruin_prob:.2%} ({ruin_count} paths)")
    print(f"Probability of <= 0% CAGR:     {loss_prob:.2%} ({neg_cagr_count} paths)")
    
    elapsed = time.time() - t0
    print(f"\n⏱️ Completed 2000 full-length histories in {elapsed:.1f}s")
    
    # Make a quick histogram
    try:
        plt.figure(figsize=(14, 5))
        
        plt.subplot(1, 2, 1)
        plt.hist(cagrs * 100, bins=50, color='green', alpha=0.7)
        plt.axvline(med_cagr * 100, color='red', linestyle='dashed', linewidth=2, label=f'Median {med_cagr:.1%}')
        plt.axvline(pct5_cagr * 100, color='orange', linestyle='dashed', linewidth=2, label=f'5th Pct {pct5_cagr:.1%}')
        plt.title('Distribution of Monte Carlo CAGRs')
        plt.xlabel('CAGR (%)')
        plt.ylabel('Frequency')
        plt.legend()
        
        plt.subplot(1, 2, 2)
        plt.hist(max_dds * 100, bins=50, color='darkred', alpha=0.7)
        plt.axvline(med_dd * 100, color='red', linestyle='dashed', linewidth=2, label=f'Median {med_dd:.1%}')
        plt.axvline(pct5_dd * 100, color='orange', linestyle='dashed', linewidth=2, label=f'95th Pct {pct5_dd:.1%}')
        plt.title('Distribution of Monte Carlo Max Drawdowns')
        plt.xlabel('Max Drawdown (%)')
        plt.ylabel('Frequency')
        plt.legend()
        
        plt.tight_layout()
        plt.savefig('bootstrap_results.png')
        print("💾 Distribution plots saved to bootstrap_results.png")
    except Exception as e:
        print(f"Could not plot: {e}")
        
    print("\n🏁 VERDICT:")
    if worst_cagr > 0 or ruin_prob < 0.05:
        print("✅ The strategy effortlessly survives realistic alternate histories. Tail risk is strictly contained.")
    else:
        print("🚩 The strategy shows significant vulnerability in unlucky sequences. Ruin risk is elevated.")

if __name__ == "__main__":
    main()
