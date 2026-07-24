import pandas as pd
import numpy as np
import warnings
import time
import os

warnings.filterwarnings('ignore')

PARQUET_PATH = "nifty500_daily.parquet"
MOM_WINDOW = 252 
TOP_N = 5
HOLD_BUFFER = 15
SKIP_DAYS = 21
REGIME_SMA = 100
ROUND_TRIP_COST = 0.0035 
INITIAL_CAPITAL = 10_000_000.0

def fetch_regime_data(start_year, sma_length):
    import yfinance as yf
    print(f"📊 Fetching Benchmark Data (Nifty 50)...")
    n50 = yf.download('^NSEI', start=f'{start_year-1}-01-01', progress=False)
    if isinstance(n50.columns, pd.MultiIndex): n50.columns = n50.columns.get_level_values(0)
    n50.reset_index(inplace=True)
    n50['Date'] = pd.to_datetime(n50['Date']).dt.tz_localize(None)
    n50['SMA'] = n50['Close'].rolling(sma_length).mean()
    n50['Is_Above'] = n50['Close'] > n50['SMA']
    
    current_state = False
    consec_above = 0
    consec_below = 0
    states = []
    bull_streaks = []
    
    for _, row in n50.iterrows():
        if pd.isna(row['SMA']):
            states.append(False)
            bull_streaks.append(0)
            continue
            
        if row['Is_Above']:
            consec_above += 1
            consec_below = 0
        else:
            consec_below += 1
            consec_above = 0
            
        if consec_above >= 3:
            current_state = True
        elif consec_below >= 3:
            current_state = False
            
        states.append(current_state)
        bull_streaks.append(consec_above if current_state else 0)
        
    n50['Bullish'] = states
    n50['Bull_Streak'] = bull_streaks
    return n50.set_index('Date')[['Bullish', 'Bull_Streak']]

def allocate_weights_recursively(mom_scores):
    import numpy as np
    n = len(mom_scores)
    if n == 0: return []
    total_mom = sum(mom_scores)
    if total_mom <= 0:
        return [1.0/n] * n
    weights = np.array([v / total_mom for v in mom_scores])
    capped = np.zeros(n, dtype=bool)
    for _ in range(n):
        violation = weights > 0.30
        to_clip = violation & ~capped
        if not to_clip.any(): break
        capped[to_clip] = True
        overflow = np.sum(weights[to_clip] - 0.30)
        weights[to_clip] = 0.30
        if not capped.all():
            remain_sum = np.sum(weights[~capped])
            if remain_sum > 0:
                weights[~capped] += overflow * (weights[~capped] / remain_sum)
            else:
                weights[~capped] += overflow / sum(~capped)
    return weights.tolist()

def run_master_backtest():
    print("=" * 70)
    print("🚀 INSTITUTIONAL ALPHA: MASTER MOMENTUM V2 (2015-2026)")
    print("=" * 70)
    
    # 1. LOAD & FILTER UNIVERSE
    print(f"📁 Loading master dataset...")
    df = pd.read_parquet(PARQUET_PATH)
    official_tickers = set(pd.read_csv('ind_nifty500list.csv').Symbol.dropna().unique())
    # Ensure ETERNAL is included even if renamed
    official_tickers.add('ETERNAL')
    
    df = df[df.Ticker.isin(official_tickers)]
    df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
    df = df.sort_values(['Ticker', 'Date'])
    
    # Check coverage
    date_min = df['Date'].min()
    date_max = df['Date'].max()
    print(f"   📅 Data Coverage: {date_min.date()} to {date_max.date()}")
    
    # 2. VECTORIZED SIGNAL ENGINE (Matrix Pivot)
    print(f"⚡ Computing Pivot Matrices...")
    CLOSE_P = df.pivot(index='Date', columns='Ticker', values='Close')
    VOL_P = df.pivot(index='Date', columns='Ticker', values='Volume')
    
    # Momentum (252/21)
    MOM = (CLOSE_P.shift(SKIP_DAYS) / CLOSE_P.shift(MOM_WINDOW)) - 1
    SMA200 = CLOSE_P.rolling(200).mean()
    TURNOVER = (CLOSE_P * VOL_P).rolling(20).mean()
    
    DAILY_RET = CLOSE_P.pct_change()
    VOL60 = DAILY_RET.rolling(60).std() * np.sqrt(252)
    # Fill NAs/zeros with 0.3 (30% vol floor)
    VOL60 = VOL60.where(VOL60 > 1e-6, 0.3)
    RISK_ADJ_MOM = MOM / VOL60
    
    # 3. REGIME FILTER
    regime = fetch_regime_data(2015, REGIME_SMA)
    
    # 4. ROBUST DATA SHIELD (Annual CV check to handle data drifts/rebrands)
    # We blacklist tickers annually to handle new IPOs/Frozen stocks dynamically
    blacklist_map = {}
    for year in range(2015, 2027):
        y_data = CLOSE_P[CLOSE_P.index.year == year]
        if not y_data.empty:
            cv = y_data.std() / y_data.mean()
            blacklist_map[year] = cv[cv < 0.01].index.tolist()

    # 5. SIMULATION
    print(f"🚀 Rebalancing Monthly...")
    cash = INITIAL_CAPITAL
    positions = {} # {Ticker: Shares}
    equity_curve = []
    
    all_dates = sorted(list(CLOSE_P.index))
    target_dates = [d for d in all_dates if d.year >= 2015]
    reb_dates = pd.Series(target_dates).groupby(pd.Series(target_dates).dt.to_period('M')).max().tolist()
    
    for d in target_dates:
        # Mark to Market (Handle missing prices gracefully)
        port_val = 0
        for t, sh in positions.items():
            price = CLOSE_P.loc[d, t]
            if np.isnan(price):
                # Fallback to the last available known price row
                price = CLOSE_P.loc[:d, t].ffill().iloc[-1]
            port_val += sh * price
            
        nav = cash + port_val
        equity_curve.append({'Date': d, 'Capital': nav})
        
        if d in reb_dates:
            reg_row = regime.loc[d] if d in regime.index else (regime.loc[:d].iloc[-1] if not regime.loc[:d].empty else pd.Series({'Bullish': False, 'Bull_Streak': 0}))
            is_bullish = reg_row['Bullish']
            bull_streak = reg_row['Bull_Streak']
            bear_market_mode = not is_bullish
            target_tickers = []
            
            ACTIVE_REGIME = "A" # Lock to Run A Configuration
            
            scores = RISK_ADJ_MOM.loc[d].copy()
            raw_scores = MOM.loc[d].copy()
            year_blacklist = blacklist_map.get(d.year, [])
            
            # Eligibility: No Blacklist, Above SMA200, Turnover > 5Cr
            mask = (
                (~scores.index.isin(year_blacklist)) & 
                (CLOSE_P.loc[d] > SMA200.loc[d]) & 
                (TURNOVER.loc[d] > 5e7)
            )
            
            if ACTIVE_REGIME == "A":
                # In regime A, we DO NOT trade in bear markets.
                if bear_market_mode:
                    target_tickers = []
                else:
                    eligible = scores[mask].dropna().sort_values(ascending=False).head(HOLD_BUFFER)
                    if len(eligible) < 5:
                        target_tickers = list(positions.keys())
                    else:
                        held = list(positions.keys())
                        top5 = eligible.head(TOP_N).index.tolist()
                        top15 = eligible.index.tolist()
                        
                        to_keep = [t for t in held if t in top15]
                        to_buy = [t for t in top5 if t not in to_keep]
                        target_tickers = (to_keep + to_buy)[:TOP_N]
            
            # Rebalance
            for t, sh in list(positions.items()):
                if t not in target_tickers:
                    p = CLOSE_P.loc[d, t]
                    if np.isnan(p): p = CLOSE_P.loc[:d, t].ffill().iloc[-1]
                    cash += (sh * p) * (1 - ROUND_TRIP_COST/2)
                    del positions[t]
            
            # Update NAV after exits
            nav_now = cash + sum([positions[tx] * (CLOSE_P.loc[d, tx] if not np.isnan(CLOSE_P.loc[d, tx]) else CLOSE_P.loc[:d, tx].ffill().iloc[-1]) for tx in positions])
            if target_tickers:
                if ACTIVE_REGIME == "A":
                    # Scaling phase-in: If bull streak < 22 days (roughly 1 month), scale at 0.5x, else 1.1x
                    scale_factor = 0.5 if bull_streak < 22 else 1.10
                else:
                    scale_factor = 1.10 if not bear_market_mode else 0.5
                    
                # Dynamic Sizing using Vol-Adjusted weights
                raw_target_moms = [max(raw_scores.get(t, 0.0), 0.0) for t in target_tickers]
                alloc_weights = allocate_weights_recursively(raw_target_moms)
                
                for i, t in enumerate(target_tickers):
                    target_per = nav_now * scale_factor * alloc_weights[i]
                    p = CLOSE_P.loc[d, t]
                    if np.isnan(p): p = CLOSE_P.loc[:d, t].ffill().iloc[-1]
                    
                    if t in positions:
                        cur_val = positions[t] * p
                        diff = target_per - cur_val
                        if abs(diff) > (nav_now * 0.02):
                            cost = abs(diff) * (ROUND_TRIP_COST/2)
                            positions[t] += diff / p
                            cash -= (diff + cost)
                    else:
                        cost = target_per * (ROUND_TRIP_COST/2)
                        positions[t] = target_per / p
                        cash -= (target_per + cost)

    # 6. PERFORMANCE ANALYTICS
    eq_df = pd.DataFrame(equity_curve)
    eq_df['Year'] = eq_df['Date'].dt.year
    
    annual_stats = []
    for yr, group in eq_df.groupby('Year'):
        start_val = group['Capital'].iloc[0]
        end_val = group['Capital'].iloc[-1]
        ret = (end_val / start_val) - 1
        dd = ((group['Capital'] - group['Capital'].cummax()) / group['Capital'].cummax()).min()
        annual_stats.append({'Year': yr, 'Return': ret, 'MaxDD': dd})
    
    stats_df = pd.DataFrame(annual_stats)
    
    total_ret = (eq_df['Capital'].iloc[-1] / INITIAL_CAPITAL) - 1
    total_dd = ((eq_df['Capital'] - eq_df['Capital'].cummax()) / eq_df['Capital'].cummax()).min()
    
    print("\n" + "=" * 70)
    print(f"{'Year':<6} | {'Annual Return':>15} | {'Max Drawdown':>12}")
    print("-" * 70)
    for _, r in stats_df.iterrows():
        print(f"{int(r['Year']):<6} | {r['Return']:>15.2%} | {r['MaxDD']:>12.2%}")
    print("-" * 70)
    print(f"{'TOTAL':<6} | {total_ret:>15.2%} | {total_dd:>12.2%}")
    print("=" * 70)
    
    eq_df.to_csv("master_equity_curve.csv", index=False)
    print(f"\n💾 Saved Full Equity Curve: master_equity_curve.csv")

if __name__ == "__main__":
    run_master_backtest()