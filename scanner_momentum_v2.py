"""
Live Scanner — Alpha Momentum V2 (God Mode 1.1x)
PRODUCTION MASTER SCRIPT (Stateful, Cap-Controlled, Friction-Optimized)
"""
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
import warnings
import json
import os
import sector_map
import sys
from datetime import datetime

warnings.filterwarnings('ignore')

# ═══ ARCHITECTURE LOCKS ═══
ACTIVE_REGIME = "A"         # "A" for Conventional 100% Cash, "B" for Dynamic Exposure
PARQUET_PATH = "nifty500_daily.parquet"
MOMENTUM_WINDOW = 252       # The undisputed king of net momentum
SKIP_DAYS = 21              # The 1-month mean-reversion firewall
TOP_N = 5                   # Concentrated risk envelope
REGIME_SMA = 100            # Decisively balanced macro cutoff
HOLD_RANK_BUFFER = 15       # Protects 6.5% CAGR in turnover drag
MIN_TURNOVER = 1e7          # Base liquidity cutoff

# ═══ INSTITUTIONAL SAFETY BOUNDS ═══
MAX_POSITION_CAP = 0.30      # Max 30% of total portfolio capital per stock
MAX_VOLUME_PCT = 0.05        # Strict execution cap: 5% of daily traded volume
LEVERAGE = 1.10              # Total gross deployment

# ═══ CIRCUIT BREAKER & KILL SWITCH ═══
BREAKER_ENABLED = True
BREAKER_THRESHOLD = -0.08    # Trip if monthly return < -8%
KILL_SWITCH_DD = -0.20       # Complete system halt if portfolio peaks fall >-20%
BREAKER_STATE_FILE = "v2_breaker_state.json"
SIGNAL_OUTPUT_FILE = "momentum_v2_signals.json"

def load_breaker_state():
    """Load breaker state."""
    db = {
        "tripped": False, "tripped_date": None, "last_month_return": 0.0,
        "month_start_capital": None, "month_start_date": None,
        "high_water_mark": None, "current_capital": 1000000, 
        "kill_switch_active": False, "kill_switch_date": None
    }
    if os.path.exists(BREAKER_STATE_FILE):
        try:
            with open(BREAKER_STATE_FILE, 'r') as f:
                loaded = json.load(f)
                db.update(loaded)
        except Exception:
            pass
    return db

def save_breaker_state(state):
    with open(BREAKER_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4, default=str)

def get_current_holdings():
    """Reads yesterday's signals to establish state-aware execution."""
    if not os.path.exists(SIGNAL_OUTPUT_FILE):
        return []
    try:
        with open(SIGNAL_OUTPUT_FILE, 'r') as f:
            data = json.load(f)
            return [s['ticker'] for s in data.get('signals', [])]
    except Exception:
        return []

def allocate_weights_recursively(mom_scores):
    """
    Distributes weights based on momentum.
    If any weight > MAX_POSITION_CAP (30%), clip it and distribute the overflow properly.
    """
    n = len(mom_scores)
    if n == 0: return []
    
    total_mom = sum(mom_scores)
    if total_mom <= 0:
        return [1.0/n] * n
        
    weights = np.array([v / total_mom for v in mom_scores])
    capped = np.zeros(n, dtype=bool)
    
    # Loop clipping until stable
    for _ in range(n):
        violation = weights > MAX_POSITION_CAP
        # Only clip un-capped components that newly exceeded the cap
        to_clip = violation & ~capped
        
        if not to_clip.any():
            break
            
        capped[to_clip] = True
        overflow = np.sum(weights[to_clip] - MAX_POSITION_CAP)
        weights[to_clip] = MAX_POSITION_CAP
        
        # Distribute overflow proportionally to non-capped assets
        if not capped.all():
            remain_sum = np.sum(weights[~capped])
            if remain_sum > 0:
                weights[~capped] += overflow * (weights[~capped] / remain_sum)
            else:
                weights[~capped] += overflow / sum(~capped)
                
    return weights.tolist()

def check_system_health(current_date_str):
    """Evaluates Kill Switch and Circuit Breaker logic based on real PnL."""
    state = load_breaker_state()
    if not BREAKER_ENABLED:
        return "OK", state
        
    cur_cap = state.get("current_capital", 1000000)
    
    # Update High Water Mark
    hwm = state.get("high_water_mark")
    if hwm is None or cur_cap > hwm:
        state["high_water_mark"] = cur_cap
        
    # 1. Evaluate KILL SWITCH
    hwm = state["high_water_mark"]
    dd = (cur_cap - hwm) / hwm if hwm > 0 else 0
    if dd <= KILL_SWITCH_DD and not state.get("kill_switch_active"):
        state["kill_switch_active"] = True
        state["kill_switch_date"] = current_date_str
        save_breaker_state(state)
        return "KILL_SWITCH", state
        
    if state.get("kill_switch_active"):
        return "KILL_SWITCH", state

    # 2. Evaluate Circuit Breaker
    if state.get("tripped"):
        try:
            days_since = (pd.to_datetime(current_date_str) - pd.to_datetime(state["tripped_date"])).days
        except Exception:
            days_since = 0
            
        if days_since < 25:
            return "BREAKER_ACTIVE", state
        else:
            state["tripped"] = False
            state["tripped_date"] = None
            
    m_start = state.get("month_start_date")
    m_cap = state.get("month_start_capital")
    
    if m_start and m_cap:
        try:
            days_elapsed = (pd.to_datetime(current_date_str) - pd.to_datetime(m_start)).days
        except Exception:
            days_elapsed = 0
            
        if days_elapsed >= 20:
            month_ret = (cur_cap - m_cap) / m_cap
            state["last_month_return"] = month_ret
            if month_ret < BREAKER_THRESHOLD:
                state["tripped"] = True
                state["tripped_date"] = current_date_str
                save_breaker_state(state)
                return "BREAKER_TRIPPED", state
                
            state["month_start_date"] = current_date_str
            state["month_start_capital"] = cur_cap
    else:
        state["month_start_date"] = current_date_str
        state["month_start_capital"] = cur_cap
        
    save_breaker_state(state)
    return "OK", state

def build_market_regime(df_all):
    import urllib.request
    import json
    
    print("🌐 Fetching latest Nifty 50 Index data for Regime Filter...")
    n50 = pd.DataFrame()
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?period1=1388534400&period2=9999999999&interval=1d"
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode())
            result = res['chart']['result'][0]
            timestamps = result['timestamp']
            quote = result['indicators']['quote'][0]
            closes = quote['close']
            n50 = pd.DataFrame({
                'Date': pd.to_datetime(timestamps, unit='s'),
                'Close': closes
            })
    except Exception as e:
        print(f"⚠️ Direct Nifty 50 fetch failed: {e}. Trying yfinance backup...")
        try:
            import yfinance as yf
            n50_yf = yf.download('^NSEI', start='2014-01-01', progress=False)
            if not n50_yf.empty:
                if isinstance(n50_yf.columns, pd.MultiIndex):
                    n50_yf.columns = n50_yf.columns.get_level_values(0)
                n50_yf.reset_index(inplace=True)
                n50_yf['Date'] = pd.to_datetime(n50_yf['Date']).dt.tz_localize(None)
                n50 = n50_yf[['Date', 'Close']].copy()
        except Exception as ye:
            print(f"⚠️ yfinance backup failed: {ye}")
            
    if n50.empty:
        print("🚨 CRITICAL: Could not fetch Nifty 50 index data! Generating synthetic index...")
        # Fallback: create synthetic Nifty 50 from Nifty 500 mean close scaled
        dates_sorted = sorted(df_all['Date'].unique())
        synthetic_n50 = []
        for d in dates_sorted:
            day_data = df_all[df_all['Date'] == d]
            mean_val = day_data['Close'].mean()
            synthetic_n50.append({
                'Date': d,
                'Close': float(mean_val * 10.45)
            })
        n50 = pd.DataFrame(synthetic_n50)
        
    n50['Date'] = pd.to_datetime(n50['Date']).dt.tz_localize(None)
    
    merged = n50[['Date', 'Close']].copy()
    merged = merged.rename(columns={'Close': 'Market_Close'})
    merged['Market_Close'] = pd.to_numeric(merged['Market_Close'], errors='coerce')
    merged = merged.dropna().sort_values('Date').reset_index(drop=True)
    
    merged['Market_SMA'] = merged['Market_Close'].rolling(REGIME_SMA).mean()
    merged['Is_Above'] = merged['Market_Close'] > merged['Market_SMA']
    
    current_state = False
    consec_above = 0
    consec_below = 0
    
    for _, row in merged.iterrows():
        if pd.isna(row['Market_SMA']): continue
        
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
            
    max_date = df_all['Date'].max()
    return current_state, consec_above, consec_below, merged.iloc[-1]['Market_Close'], merged.iloc[-1]['Market_SMA'], max_date

def emit_empty_signal(filename, status_type, date_str, current_capital):
    with open(filename, 'w') as f:
        json.dump({
            "nifty_level": 0,
            "regime": status_type,
            "scanned_date": date_str,
            "portfolio_value": current_capital,
            "signals": [],
            "sector_stats": {}
        }, f, indent=4)
    print(f"💾 {status_type} state saved to {filename}")

def run_momentum_v2_scanner():
    print("🚀 NIFTY 500 Momentum V2 (God Mode 1.1x) — PRODUCTION MASTER")
    print("=" * 70)
    
    try:
        df_all = pd.read_parquet(PARQUET_PATH)
    except FileNotFoundError:
        print(f"❌ {PARQUET_PATH} not found!")
        return

    # Filter to ONLY current Nifty 500 from official CSV
    nifty500_csv = pd.read_csv("ind_nifty500list.csv")
    valid_tickers = set(nifty500_csv['Symbol'].dropna())
    df_all = df_all[df_all['Ticker'].isin(valid_tickers)]

    df_all['Date'] = pd.to_datetime(df_all['Date'])
    market_is_bullish, consec_above, consec_below, last_close, last_sma, max_date = build_market_regime(df_all)
    max_date_str = max_date.strftime('%Y-%m-%d')
    
    print(f"📅 Scanning Date  : {max_date_str}")
    print(f"⚙️ ACTIVE REGIME  : [{'MODE A (100% Cash)' if ACTIVE_REGIME=='A' else 'MODE B (Dynamic Leverage)'}]")
    print(f"📈 Nifty50 Close  : {last_close:.2f} (SMA{REGIME_SMA}: {last_sma:.2f})")
    print(f"   ▶ Consecutive Days Above: {consec_above} | Below: {consec_below}")
    print(f"   ▶ Final Regime Status : {'BULLISH 🟢' if market_is_bullish else 'BEARISH 🔴 (100% Cash if Mode A)'}")

    # 🚨 HEALTH CHECKS 
    health_status, breaker_state = check_system_health(max_date_str)
    cur_capital = breaker_state.get("current_capital", 1000000)
    hwm = breaker_state.get("high_water_mark", cur_capital)
    
    print(f"💵 System Capital : ₹{cur_capital:,.0f} (HWM: ₹{hwm:,.0f}) | DD: {((cur_capital/hwm)-1 if hwm>0 else 0):.2%}")
    
    if health_status == "KILL_SWITCH":
        print(f"\n☠️  KILL SWITCH ACTIVE! Maximum Drawdown Cap ({KILL_SWITCH_DD:.0%}) Exceeded.")
        print("   System halted. Emitting 100% Cash Signal to Execution API.")
        emit_empty_signal(SIGNAL_OUTPUT_FILE, "Kill_Switch_Halted", max_date_str, cur_capital)
        return
        
    if health_status in ["BREAKER_TRIPPED", "BREAKER_ACTIVE"]:
        print("\n🛑  CIRCUIT BREAKER ACTIVE! Emitting 100% Cash Signal.")
        emit_empty_signal(SIGNAL_OUTPUT_FILE, "Breaker_Active", max_date_str, cur_capital)
        return
        
    bear_market_mode = not market_is_bullish
    mode_a_flush = False
    
    if bear_market_mode:
        if ACTIVE_REGIME == "A":
            print("\n📉 Market is BEARISH (Nifty < 100 SMA for 3+ days). Entering CONVENTIONAL 100% CASH MODE.")
            print("   -> Explicitly firing SELL signals for all active holdings.")
            print("   -> Target stocks: 0. Total capital deployment: 0.0x")
            
            # Explicit full exit
            for held_ticker in get_current_holdings():
                print(f"   🔴 FLUSHING EXPOSURE: Generating explicit SELL execution for {held_ticker}")
            
            mode_a_flush = True
        else:
            print("\n📉 Market is BEARISH. Entering DYNAMIC EXPOSURE MODE (Bear-Breakout protocol).")
            print("   -> Target stocks kept at full TOP 5.")
            print("   -> Total position leverage constrained to 0.5x.")
            print("   -> Strict standalone 200-SMA upward filter enforced.")
    else:
        print(f"\n📈 Market is BULLISH (Nifty > 100 SMA).")
        
    print(f"\n⏳ Pre-computing structural velocity across Nifty 500...")
    
    df_all = df_all.sort_values(['Ticker', 'Date'])
    df_all['Prev_Close'] = df_all.groupby('Ticker')['Close'].shift(MOMENTUM_WINDOW)
    df_all['Recent_Close'] = df_all.groupby('Ticker')['Close'].shift(SKIP_DAYS)
    
    df_all['Momentum_Score'] = (df_all['Recent_Close'] / df_all['Prev_Close']) - 1
    df_all['SMA200'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    df_all['Avg_Volume5'] = df_all.groupby('Ticker')['Volume'].transform(lambda x: x.rolling(5).mean())
    
    df_all['DailyRet'] = df_all.groupby('Ticker')['Close'].pct_change()
    df_all['Vol60'] = df_all.groupby('Ticker')['DailyRet'].transform(lambda x: x.rolling(60).std() * np.sqrt(252)).fillna(0.3)
    
    latest_data = df_all[df_all['Date'] == max_date].copy()
    latest_data = latest_data.dropna(subset=['Momentum_Score', 'SMA200', 'Avg_Turnover20'])
    
    # Quality Adjust: Mom / Vol
    latest_data['RiskAdjMom'] = latest_data['Momentum_Score'] / (latest_data['Vol60'] + 1e-6)
    latest_data.loc[~np.isfinite(latest_data['RiskAdjMom']), 'RiskAdjMom'] = latest_data['Momentum_Score']
    
    # Fundamental constraint: Ensure individual stock is healthy
    eligible = latest_data[
        (latest_data['Close'] > latest_data['SMA200']) & 
        (latest_data['Avg_Turnover20'] > MIN_TURNOVER) & 
        (latest_data['Close'] > 10)
    ]
    
    if bear_market_mode:
        # In bear mode, we require very high momentum relative strength > 20% absolute
        eligible = eligible[eligible['Momentum_Score'] > 0.20]
    
    if eligible.empty:
        print("\n❌ Zero stocks passed the trend & liquidity filters!")
        emit_empty_signal(SIGNAL_OUTPUT_FILE, "No_Candidates", max_date_str, cur_capital)
        return
        
    eligible = eligible.sort_values('RiskAdjMom', ascending=False)
    
    # ═══ HOLD RANK (CHURN BUFFER) LOGIC ═══
    current_held = set(get_current_holdings())
    buffer_eligible = eligible.head(HOLD_RANK_BUFFER)
    
    retained_tickers = [t for t in buffer_eligible['Ticker'] if t in current_held]
    new_tickers = [t for t in eligible['Ticker'] if t not in retained_tickers]
    
    active_top_n = TOP_N  # Force top 5 even in bear breakout mode
    target_tickers = retained_tickers + new_tickers[:max(0, active_top_n - len(retained_tickers))]
    
    target_df = eligible[eligible['Ticker'].isin(target_tickers)]
    target_df['Ticker_Cat'] = pd.Categorical(target_df['Ticker'], categories=target_tickers, ordered=True)
    target_df = target_df.sort_values('Ticker_Cat')
    
    # ═══ POSITION SIZING & CAPPING ═══
    raw_mom = [max(m, 0.0) for m in target_df['Momentum_Score'].fillna(0)]
    capped_weights = allocate_weights_recursively(raw_mom)
    
    # Evaluate Phase-In Rule
    active_leverage = LEVERAGE
    if not bear_market_mode:
        if consec_above < 22: # Approx 1 month
            active_leverage = LEVERAGE * 0.5
            print(f"   ▶ Re-entry Phase 1/2: Bullish streak ({consec_above}d) < 22 days. Capping total leverage to {active_leverage}x.")
        else:
            print(f"   ▶ Re-entry Phase 2/2: Bullish streak ({consec_above}d) >= 22 days. Full leverage applied ({active_leverage}x).")
    else:
        # We only reach here if ACTIVE_REGIME == "B"
        active_leverage = (LEVERAGE / 2.0)
        
    target_allocations = [w * active_leverage for w in capped_weights]
    
    print("\n" + "=" * 70)
    print("🟢 MASTER GOD MODE ALGORITHM (LIVE DEPLOYMENT ENGINE)")
    print("=" * 70)
    
    frontend_signals = []
    
    for i, (_, row) in enumerate(target_df.reset_index(drop=True).iterrows()):
        ticker = row['Ticker']
        sector = sector_map.get_sector(ticker)
        price = row['Close']
        vol5 = row.get('Avg_Volume5', 0)
        
        alloc_pct = target_allocations[i] * 100
        kept_status = "HOLD (Buffer)" if ticker in retained_tickers else "NEW ENTRY"
        
        # Max Execution Volume Cap
        max_alloc_amount = cur_capital * (alloc_pct / 100)
        max_shares = int(max_alloc_amount / price) if price > 0 else 0
        liquidity_limit_shares = int(vol5 * MAX_VOLUME_PCT)
        
        safe_shares = min(max_shares, liquidity_limit_shares)
        
        sig_str = "BUY" if ticker not in retained_tickers else "HOLD"
        
        if mode_a_flush:
            alloc_pct = 0.0
            safe_shares = 0
            sig_str = "TRACK"
            kept_status = "CASH SECURED"
        
        print(f"[{i+1}] {ticker:<12} | Alloc: {alloc_pct:4.1f}% | Limit: {safe_shares:>5} shrs | {kept_status}")
        
        frontend_signals.append({
            "ticker": ticker,
            "sector": sector,
            "signal": sig_str,
            "price": float(price),
            "hold_period": "God Mode Churn Buffer",
            "allocation_pct": round(alloc_pct, 1),
            "max_volume_shrs": liquidity_limit_shares,
            "target_shrs": safe_shares,
            "tech_status": kept_status
        })

    # Export remaining 10 buffer stocks for telemetry
    for _, row in buffer_eligible.iterrows():
        ticker = row['Ticker']
        if not any(f['ticker'] == ticker for f in frontend_signals):
            frontend_signals.append({
                "ticker": ticker,
                "sector": sector_map.get_sector(ticker),
                "signal": "TRACK",
                "price": float(row['Close']),
                "hold_period": "God Mode Churn Buffer",
                "allocation_pct": 0.0,
                "max_volume_shrs": int(row.get('Avg_Volume5', 0) * MAX_VOLUME_PCT),
                "target_shrs": 0,
                "tech_status": "OBSERVATION ONLY"
            })
        
    print("=" * 70)
    
    output_data = {
        "nifty_level": float(last_close),
        "regime": "Mode_A_100_Cash" if mode_a_flush else ("Bear_Breakout_Mode" if bear_market_mode else "God_Mode_Active"),
        "scanned_date": max_date_str,
        "portfolio_value": cur_capital,
        "signals": frontend_signals,
        "sector_stats": {s: {"avg_score": 99, "signal": "Bullish"} for s in set([f['sector'] for f in frontend_signals])},
        "system_status": {
            "breaker_tripped": breaker_state.get("tripped", False),
            "kill_switch_active": breaker_state.get("kill_switch_active", False)
        }
    }
    
    try:
        with open(SIGNAL_OUTPUT_FILE, 'w') as f:
            json.dump(output_data, f, indent=4)
        print(f"💾 Successfully flushed to {SIGNAL_OUTPUT_FILE}")
    except Exception as e:
        print(f"❌ Error writing JSON: {e}")

if __name__ == "__main__":
    run_momentum_v2_scanner()
