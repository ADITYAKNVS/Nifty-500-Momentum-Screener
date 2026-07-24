import pandas as pd
import numpy as np
import json
from datetime import datetime
import warnings

# Suppress pandas chained assignment warnings for clean terminal output
warnings.filterwarnings('ignore')

MASTER_PARQUET = "fno_master.parquet"
OUTPUT_JSON = "fno_oi_signals.json"

OI_SPIKE_THRESHOLD = 0.05  # 5% spike relative to baseline
PRICE_CHANGE_MIN = 0.005   # 0.5% minimum price move

def map_sector(ticker, inst):
    """Accurately tag index futures instead of generic 'INDEX'"""
    if inst == 'FUTIDX':
        if 'BANKNIFTY' in ticker: return 'BANKNIFTY'
        if 'FINNIFTY' in ticker: return 'FINNIFTY'
        if 'MIDCPNIFTY' in ticker: return 'MIDCPNIFTY'
        if 'NIFTY' in ticker: return 'NIFTY'
        return 'INDEX'
    return 'STOCK'

def run_scanner():
    print("=" * 60)
    print("🧠 SMART MONEY OI SCANNER (Phase 2 w/ 3D Confirmation)")
    print("=" * 60)
    
    try:
        df = pd.read_parquet(MASTER_PARQUET)
    except Exception as e:
        print(f"❌ Failed to load {MASTER_PARQUET}: {e}")
        return
        
    df = df.sort_values(['SYMBOL', 'Date']).reset_index(drop=True)
    latest_date = df['Date'].max()
    print(f"Scanning Anomaly Data for: {latest_date.strftime('%Y-%m-%d')}")
    
    # --- REGIME FILTER (NIFTY SMA100) ---
    nifty_context = df[df['SYMBOL'] == 'NIFTY'][['Date', 'CLOSE']].rename(columns={'CLOSE': 'NIFTY_Close'})
    nifty_context = nifty_context.sort_values('Date').drop_duplicates('Date')
    nifty_context['NIFTY_SMA100'] = nifty_context['NIFTY_Close'].rolling(100, min_periods=1).mean()
    df = df.merge(nifty_context, on='Date', how='left')
    df['NIFTY_Regime_Bullish'] = df['NIFTY_Close'] > df['NIFTY_SMA100']
    
    # Calculate 5-Day Baseline Open Interest (shift to avoid forward leak)
    df['OI_5D_Baseline'] = df.groupby('SYMBOL')['OPEN_INT'].transform(lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    df['Prev_Close'] = df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.shift(1))
    
    # Calculate Percent Spikes
    df['OI_Spike_Pct'] = (df['OPEN_INT'] - df['OI_5D_Baseline']) / df['OI_5D_Baseline']
    df['Price_Change_Pct'] = (df['CLOSE'] - df['Prev_Close']) / df['Prev_Close']
    
    # Vectorized 4-State Machine Calculation for all history
    conditions = [
        (df['OI_Spike_Pct'] > OI_SPIKE_THRESHOLD) & (df['Price_Change_Pct'] >= PRICE_CHANGE_MIN),
        (df['OI_Spike_Pct'] > OI_SPIKE_THRESHOLD) & (df['Price_Change_Pct'] <= -PRICE_CHANGE_MIN),
        (df['OI_Spike_Pct'] < -OI_SPIKE_THRESHOLD) & (df['Price_Change_Pct'] >= PRICE_CHANGE_MIN),
        (df['OI_Spike_Pct'] < -OI_SPIKE_THRESHOLD) & (df['Price_Change_Pct'] <= -PRICE_CHANGE_MIN)
    ]
    choices = ['Long Buildup', 'Short Buildup', 'Short Covering', 'Long Unwinding']
    df['Signal_State'] = np.select(conditions, choices, default='Neutral')
    
    # 3-Day Institutional Confirmation Filter 
    # Validates that Smart Money has been aggressively holding/building the SAME behavior for 3 consecutive days
    df['Lag1'] = df.groupby('SYMBOL')['Signal_State'].shift(1)
    df['Lag2'] = df.groupby('SYMBOL')['Signal_State'].shift(2)
    df['Consecutive_3_Days'] = (df['Signal_State'] != 'Neutral') & (df['Signal_State'] == df['Lag1']) & (df['Signal_State'] == df['Lag2'])
    
    # Apply the stringent filter isolating only today's data
    latest_df = df[df['Date'] == latest_date].copy()
    confirmed_setups = latest_df[latest_df['Consecutive_3_Days'] == True]
    
    # --- APPLY REGIME FILTER ---
    # Suppress all stock signals when Nifty is in a sideways/choppy regime (below SMA100)
    # Only allow index signals (FUTIDX) in non-bullish regimes
    regime_mask = (confirmed_setups['INSTRUMENT'] == 'FUTIDX') | (confirmed_setups['NIFTY_Regime_Bullish'] == True)
    confirmed_setups = confirmed_setups[regime_mask]
    
    signals = []
    
    for _, row in confirmed_setups.iterrows():
        ticker = row['SYMBOL']
        oi_change = row['OI_Spike_Pct']
        px_change = row['Price_Change_Pct']
        oi_raw = row['OPEN_INT']
        price = row['CLOSE']
        instrument = row['INSTRUMENT']
        state = row['Signal_State']
        
        # Enhanced Multi-Factor Alpha Score blending Velocity + Conviction
        score_val = (abs(oi_change) * 0.6 + abs(px_change) * 0.4) * 500
        alpha_score = min(99, int(score_val))
        
        # Pure Schema representation (No fake frontend hold_period properties)
        signals.append({
            "ticker": ticker,
            "signal": state,
            "sector": map_sector(ticker, instrument),
            "price": round(price, 2),
            "price_change_pct": round(px_change * 100, 2),
            "oi_raw": int(oi_raw),
            "oi_spike_pct": round(oi_change * 100, 2),
            "alpha_score": alpha_score,
            "instrument": instrument
        })

    # Sort strictly by Alpha Score now that it represents multi-factor conviction
    signals = sorted(signals, key=lambda x: x['alpha_score'], reverse=True)
    
    output_payload = {
        "nifty_level": 0,
        "regime": "3D Trend Reversals",
        "scanned_date": latest_date.strftime('%Y-%m-%d'),
        "portfolio_value": 0,
        "signals": signals[:15], 
        "sector_stats": {
            "INDEX": {"avg_score": 90, "signal": "Macro"},
            "STOCK": {"avg_score": 50, "signal": "Volatile"}
        }
    }
    
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output_payload, f, indent=4)
        
    print(f"✅ Filtered & Detected {len(signals)} confirmed 3-Day Institutional Anomalies.")
    print(f"💾 Payload schema natively updated for {OUTPUT_JSON}")
    
    print("\n🔥 TOP EXPLOSIVE MOVES (3D Filtered):")
    for sig in signals[:5]:
        print(f"   [{sig['ticker']}] {sig['signal']} | Alpha: {sig['alpha_score']} | OI: {sig['oi_spike_pct']}% | Px: {sig['price_change_pct']}%")

if __name__ == "__main__":
    run_scanner()
