import pandas as pd
import numpy as np
from pure_alpha_production import (
    NSEAlphaGenerator, SimpleBacktester, load_production_data,
    SignalQualityFilter, FundamentalFilter, TrendFilter,
)

def run_v5_final_legacy_audit():
    """
    NSE ALPHA GENERATOR v6.0: FINAL INSTITUTIONAL LEGACY AUDIT
    ---------------------------------------------------------
    Period: 2016 - 2026 (10 Year Horizon)
    Includes: Full Cost Model, Sector Limits, Circuit Filters,
              Fundamental Filter, Trend Filter, RF Signal Filter, Volume Confirmation
    """
    print("\n" + "█"*80)
    print("█" + "  🛡️ NSE ALPHA GENERATOR v6.0: INSTITUTIONAL LEGACY AUDIT  ".center(78) + "█")
    print("█"*80 + "\n")
    
    # 1. LOAD DATA
    price_df, volume_df, bench_df, sector_map = load_production_data()
    
    # 2. SETUP HARDENED GENERATOR WITH ALL FILTERS
    fundamental_filter = FundamentalFilter(csv_path="fundamental_filter.csv")
    trend_filter       = TrendFilter()
    signal_filter      = SignalQualityFilter()

    alpha_gen = NSEAlphaGenerator(
        lookback_window     = 252,
        min_liquidity_rank  = 200, 
        zscore_threshold    = 2.0,
        max_position_size   = 0.03,
        transaction_cost    = 0.0010,
        sector_mapping      = sector_map,
        max_sector_exposure = 0.25,
        signal_filter       = signal_filter,
        fundamental_filter  = fundamental_filter,
        trend_filter        = trend_filter,
    )
    
    bt = SimpleBacktester(alpha_gen)
    
    # Run Parameters
    START = "2016-01-01" 
    END   = price_df.index[-1].strftime('%Y-%m-%d')
    FREQ  = "W-MON"
    
    print(f"📂 Initializing 10-year audit from {START} to {END}...")
    
    # --- Mode 1: Long Only (v5.0) ---
    print("\n📈 SCENARIO 1: Running LONG ONLY (Institutional Costs)...")
    long_results = bt.run_backtest(
        price_df       = price_df,
        benchmark_df   = bench_df,
        volume_df      = volume_df,
        start_date     = START,
        end_date       = END,
        rebalance_freq = FREQ,
        long_only      = True
    )
    long_stats = bt.performance_summary()
    
    # --- Mode 2: Long & Short (v5.0) ---
    print("\n📊 SCENARIO 2: Running LONG & SHORT (Beta Neutral)...")
    ls_results = bt.run_backtest(
        price_df       = price_df,
        benchmark_df   = bench_df,
        volume_df      = volume_df,
        start_date     = START,
        end_date       = END,
        rebalance_freq = FREQ,
        long_only      = False
    )
    ls_stats = bt.performance_summary()
    
    # 3. FINAL AUDIT TABLE
    print("\n" + "╔" + "═"*78 + "╗")
    print("║" + "  FINAL v5.0 AUDIT COMPARISON (2016-2026)  ".center(78) + "║")
    print("╠" + "═"*78 + "╣")
    print(f"║ {'Metric':<28} │ {'Long Only':>22} │ {'Long/Short':>22} ║")
    print("╠" + "─"*78 + "╣")
    
    metrics = [
        ("Total Net Return", "total_net_return", "%"),
        ("Annualized Sharpe", "annualised_sharpe", ""),
        ("Max Drawdown", "max_drawdown", "%"),
        ("Win Rate", "win_rate", "%"),
        ("Beta to Nifty", "beta_to_nifty", ""),
        ("Avg Positions (L/S)", None, ""),
        ("Avg Gross Exposure", "avg_gross_exposure", "%"),
        ("Total Transaction Cost", "total_transaction_cost", "%"),
        ("Annual Turnover", "annual_turnover", "%"),
    ]
    
    for label, key, fmt in metrics:
        if key:
            l_val = long_stats.get(key, 0)
            ls_val = ls_stats.get(key, 0)
            if fmt == "%":
                l_str, ls_str = f"{l_val:.2%}", f"{ls_val:.2%}"
            else:
                l_str, ls_str = f"{l_val:.3f}", f"{ls_val:.3f}"
            print(f"║ {label:<28} │ {l_str:>22} │ {ls_str:>22} ║")
        else:
            l_pos = f"{long_stats.get('avg_long_positions', 0):.1f}/0.0"
            ls_pos = f"{ls_stats.get('avg_long_positions', 0):.1f}/{ls_stats.get('avg_short_positions', 0):.1f}"
            print(f"║ {label:<28} │ {l_pos:>22} │ {ls_pos:>22} ║")

    print("╚" + "═"*78 + "╝")
    
    # Save results
    output_df = pd.DataFrame({
        'Date': long_results['date'],
        'LongOnly_NAV': (1 + long_results['net_return']).cumprod(),
        'LongShort_NAV': (1 + ls_results['net_return']).cumprod()
    })
    output_df.to_csv("final_v5_institutional_audit.csv", index=False)
    print(f"\n💾 Saved comparative results to final_v5_institutional_audit.csv")

if __name__ == "__main__":
    run_v5_final_legacy_audit()
