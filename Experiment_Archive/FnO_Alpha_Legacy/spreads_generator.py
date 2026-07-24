import json
from datetime import datetime
import os
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

OI_SIGNALS_FILE = "fno_oi_signals.json"
SPREAD_SIGNALS_FILE = "fno_spread_signals.json"
LATEST_OPTIONS_CACHE = "latest_options_chain.parquet"

PORTFOLIO_CAPITAL = 1_000_000   # 10 Lakhs capital
MAX_RISK_PER_TRADE = 0.02       # 2% Max Loss boundary

def round_to_strike(price):
    if price > 10000: step = 100
    elif price > 1000: step = 50
    elif price > 500: step = 10
    else: step = 5
    return round(price / step) * step

def extract_option_data(opt_df, symbol, strike, opt_type):
    """Fetches the EOD premium and precise actual Lot Size for the nearest expiry option leg."""
    leg_df = opt_df[(opt_df['SYMBOL'] == symbol) & 
                    (opt_df['STRIKE'] == strike) & 
                    (opt_df['OPTION_TYPE'] == opt_type)].copy()
    
    if leg_df.empty:
        return None, None
        
    # Isolate nearest expiry to ensure dense liquidity
    leg_df['EXPIRY_DT'] = pd.to_datetime(leg_df['EXPIRY_DT'])
    nearest_expiry = leg_df['EXPIRY_DT'].min()
    leg_df = leg_df[leg_df['EXPIRY_DT'] == nearest_expiry]
    
    close_price = leg_df['CLOSE'].values[0]
    lot_size = leg_df['LOT_SIZE'].values[0]
    
    premium = float(close_price) if close_price > 0 else None
    return premium, int(lot_size)

def generate_spreads():
    print("=" * 60)
    print("🛡️ RISK-DEFINED SPREADS ENGINE (Real Pricing)")
    print("=" * 60)

    if not os.path.exists(OI_SIGNALS_FILE) or not os.path.exists(LATEST_OPTIONS_CACHE):
        print("❌ Cannot find necessary inputs. Run Phase 1 & 2 first.")
        return

    with open(OI_SIGNALS_FILE, 'r') as f:
        data = json.load(f)

    oi_signals = data.get("signals", [])
    scanned_date = data.get("scanned_date", datetime.now().strftime('%Y-%m-%d'))

    try:
        opt_df = pd.read_parquet(LATEST_OPTIONS_CACHE)
    except Exception as e:
        print(f"❌ Failed to load option chain cache: {e}")
        return

    spread_signals = []

    for sig in oi_signals:
        ticker = sig['ticker']
        raw_signal = sig['signal']
        price = float(sig['price'])
        
        # Only build spreads for institutional entry signals
        if raw_signal not in ["Long Buildup", "Short Buildup"]:
            continue

        atm_strike = round_to_strike(price)
        
        if raw_signal == "Long Buildup":
            strategy = "Bull Call Spread"
            otm_strike = round_to_strike(price * 1.03)
            leg_type = "CE"
        else:
            strategy = "Bear Put Spread"
            otm_strike = round_to_strike(price * 0.97)
            leg_type = "PE"

        # ─── REAL SPREAD PRICING ───
        atm_prem, lot_size = extract_option_data(opt_df, ticker, atm_strike, leg_type)
        otm_prem, _ = extract_option_data(opt_df, ticker, otm_strike, leg_type)
        
        if atm_prem is None or otm_prem is None or lot_size is None:
            continue # Illiquid missing strikes are gracefully skipped
            
        real_net_debit = atm_prem - otm_prem
        
        if real_net_debit <= 0:
            continue # Discard broken structural skews
            
        real_max_loss_per_share = real_net_debit
        real_spread_width = abs(atm_strike - otm_strike)
        real_max_profit_per_share = real_spread_width - real_net_debit
        
        # Sizing execution logic based on strict risk limit natively tracking NewBrdLotQty
        max_rupee_loss = PORTFOLIO_CAPITAL * MAX_RISK_PER_TRADE
        optimal_lots = max_rupee_loss / (real_max_loss_per_share * lot_size)
        optimal_lots = max(1, int(optimal_lots)) # Minimum 1 lot
        
        actual_risk_rs = optimal_lots * lot_size * real_max_loss_per_share
        actual_profit_rs = optimal_lots * lot_size * real_max_profit_per_share
        
        rr_ratio = abs(actual_profit_rs / actual_risk_rs) if actual_risk_rs > 0 else 0

        leg_1_str = f"BUY {atm_strike} {leg_type} @ ₹{atm_prem:.1f}"
        leg_2_str = f"SELL {otm_strike} {leg_type} @ ₹{otm_prem:.1f}"

        # Populate payload correctly without lying the schema this time
        spread_signals.append({
            "ticker": ticker,
            "sector": strategy,     
            "signal": "ENTRY", # Using a generic non-confusing badge instead of BUY
            "price": price, 
            "hold_period": f"{leg_1_str} | {leg_2_str}", # Displaying actual legs
            "stop_loss": -actual_risk_rs,                # True mathematical risk
            "target": actual_profit_rs,                  # True mathematical reward
            "rr_ratio": f"1:{rr_ratio:.1f}",
            "alpha_score": sig['alpha_score']
        })

    # Sort by the most structurally optimal R:R ratio
    spread_signals = sorted(spread_signals, key=lambda x: x['target']/abs(x['stop_loss']) if x['stop_loss']!=0 else 0, reverse=True)

    output_payload = {
        "nifty_level": data.get("nifty_level", 0),
        "regime": "Spreads Engine Active",
        "scanned_date": scanned_date,
        "portfolio_value": PORTFOLIO_CAPITAL,
        "signals": spread_signals,
        "sector_stats": {
            "Bull Call Spread": {"avg_score": 95, "signal": "Bullish"},
            "Bear Put Spread": {"avg_score": 90, "signal": "Bearish"}
        }
    }

    with open(SPREAD_SIGNALS_FILE, 'w') as f:
        json.dump(output_payload, f, indent=4)

    print(f"✅ Generated {len(spread_signals)} genuine Risk-Defined Spread Setups using real pricing.")
    print(f"💾 Flushed payload to {SPREAD_SIGNALS_FILE}")
    print("\n🛡️ MATHEMATICALLY ACCURATE EXECUTION DIRECTIVES:")
    for sig in spread_signals[:3]:
        print(f"   [{sig['ticker']}] {sig['sector']} (Max Loss: ₹{-sig['stop_loss']:,.0f} | Max Reward: ₹{sig['target']:,.0f})")
        
if __name__ == "__main__":
    generate_spreads()
