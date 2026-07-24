"""
Portfolio Manager — Alpha Quant V5 PRO
Tracks open positions, checks stop loss / target / trend death / max hold,
and frees portfolio slots automatically.
"""
import json
import os
import pandas as pd
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore')

POSITIONS_FILE = "positions.json"
PARQUET_PATH   = "nifty500_daily.parquet"
TRADE_LOG      = "logs/trades.log"
MAX_POSITIONS  = 10
MAX_HOLD_DAYS  = 60

# ─── Logging ───
def log_trade(message):
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp}  {message}\n"
    with open(TRADE_LOG, "a") as f:
        f.write(line)
    print(f"   📝 {message}")

# ─── Positions I/O ───
def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        return []
    with open(POSITIONS_FILE, "r") as f:
        return json.load(f)

def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=4, default=str)

# ─── Core Logic ───
def check_exits(positions, latest_prices, today_str):
    """Check each open position for stop loss, target hit, or max hold expiry."""
    still_open = []
    closed = []

    for pos in positions:
        ticker = pos["ticker"]
        entry_price = pos["entry_price"]
        stop = pos["stop_loss"]
        target = pos["target"]
        entry_date = pd.to_datetime(pos["entry_date"])
        days_held = (pd.to_datetime(today_str) - entry_date).days

        # Get latest price
        current_price = latest_prices.get(ticker, None)
        if current_price is None:
            # No price data — keep position open
            still_open.append(pos)
            continue

        pnl_pct = round(((current_price - entry_price) / entry_price) * 100, 2)

        # Check STOP LOSS
        if current_price <= stop:
            log_trade(f"EXIT {ticker} @₹{current_price:.0f} | STOP LOSS HIT | Entry ₹{entry_price:.0f} | P&L: {pnl_pct:+.2f}% | Held {days_held}d")
            closed.append({**pos, "exit_price": current_price, "exit_reason": "STOP_LOSS", "exit_date": today_str, "pnl_pct": pnl_pct})
            continue

        # Check TARGET
        if current_price >= target:
            log_trade(f"EXIT {ticker} @₹{current_price:.0f} | TARGET HIT ✅ | Entry ₹{entry_price:.0f} | P&L: {pnl_pct:+.2f}% | Held {days_held}d")
            closed.append({**pos, "exit_price": current_price, "exit_reason": "TARGET_HIT", "exit_date": today_str, "pnl_pct": pnl_pct})
            continue

        # Check MAX HOLD
        if days_held >= MAX_HOLD_DAYS:
            log_trade(f"EXIT {ticker} @₹{current_price:.0f} | MAX HOLD ({MAX_HOLD_DAYS}d) | Entry ₹{entry_price:.0f} | P&L: {pnl_pct:+.2f}% | Held {days_held}d")
            closed.append({**pos, "exit_price": current_price, "exit_reason": "MAX_HOLD", "exit_date": today_str, "pnl_pct": pnl_pct})
            continue

        # Still alive
        still_open.append(pos)

    return still_open, closed

def get_latest_prices(tickers):
    """Read latest closing prices from the parquet file."""
    if not os.path.exists(PARQUET_PATH):
        print(f"❌ {PARQUET_PATH} not found!")
        return {}
    
    df = pd.read_parquet(PARQUET_PATH)
    df['Date'] = pd.to_datetime(df['Date'])
    max_date = df['Date'].max()
    
    latest = df[df['Date'] == max_date]
    prices = {}
    for _, row in latest.iterrows():
        if row['Ticker'] in tickers:
            prices[row['Ticker']] = row['Close']
    
    return prices, max_date.strftime('%Y-%m-%d')

def add_position(ticker, entry_price, stop_loss, target, atr, entry_date=None):
    """Add a new position to the portfolio."""
    positions = load_positions()
    
    # Check if already holding this ticker
    held_tickers = [p["ticker"] for p in positions]
    if ticker in held_tickers:
        print(f"⚠️  Already holding {ticker}. Skipping.")
        return False
    
    # Check slot availability
    if len(positions) >= MAX_POSITIONS:
        print(f"⚠️  Portfolio full ({MAX_POSITIONS}/{MAX_POSITIONS} slots). Cannot add {ticker}.")
        return False
    
    if entry_date is None:
        entry_date = datetime.now().strftime("%Y-%m-%d")
    
    new_pos = {
        "ticker": ticker,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "atr": round(atr, 2),
        "entry_date": entry_date
    }
    
    positions.append(new_pos)
    save_positions(positions)
    log_trade(f"BUY {ticker} @₹{entry_price:.0f} | Stop ₹{stop_loss:.0f} | Target ₹{target:.0f} | Slot {len(positions)}/{MAX_POSITIONS}")
    return True

def get_open_slots():
    """Return number of available portfolio slots."""
    positions = load_positions()
    return MAX_POSITIONS - len(positions)

def get_held_tickers():
    """Return set of tickers currently in the portfolio."""
    positions = load_positions()
    return set(p["ticker"] for p in positions)

# ─── Main Runner ───
def run_manager():
    print("💼 Alpha Quant V5 — Portfolio Manager")
    print("=" * 65)
    
    positions = load_positions()
    
    if not positions:
        print(f"\n📭 No open positions. Portfolio is empty ({MAX_POSITIONS} slots free).")
        print("   Run scanner_v5.py to find new signals.")
        return
    
    print(f"\n📊 Open Positions: {len(positions)}/{MAX_POSITIONS}")
    print(f"   Free Slots: {MAX_POSITIONS - len(positions)}")
    print("-" * 65)
    
    # Get latest prices
    tickers = [p["ticker"] for p in positions]
    result = get_latest_prices(tickers)
    
    if not result:
        print("❌ Could not load price data.")
        return
    
    latest_prices, today_str = result
    
    # Display current status
    print(f"\n{'Ticker':<12} {'Entry':>8} {'Current':>10} {'Stop':>8} {'Target':>8} {'P&L':>8} {'Days':>6}")
    print("-" * 65)
    
    for pos in positions:
        ticker = pos["ticker"]
        entry = pos["entry_price"]
        stop = pos["stop_loss"]
        target = pos["target"]
        current = latest_prices.get(ticker, 0)
        entry_date = pd.to_datetime(pos["entry_date"])
        days_held = (pd.to_datetime(today_str) - entry_date).days
        pnl = ((current - entry) / entry * 100) if current > 0 else 0
        
        status = "🟢" if pnl > 0 else "🔴"
        print(f"   {status} {ticker:<10} ₹{entry:>7.0f} ₹{current:>9.0f} ₹{stop:>7.0f} ₹{target:>7.0f} {pnl:>+7.2f}% {days_held:>5}d")
    
    # Check exits
    print("\n" + "=" * 65)
    print("🔍 Checking exit conditions...")
    print("-" * 65)
    
    still_open, closed = check_exits(positions, latest_prices, today_str)
    
    if closed:
        print(f"\n🔔 Closed {len(closed)} position(s):")
        for c in closed:
            emoji = "✅" if c["pnl_pct"] > 0 else "❌"
            print(f"   {emoji} {c['ticker']} → {c['exit_reason']} ({c['pnl_pct']:+.2f}%)")
    else:
        print("   ✅ No exits triggered. All positions still active.")
    
    # Save updated positions
    save_positions(still_open)
    
    print(f"\n📊 Updated: {len(still_open)} open | {MAX_POSITIONS - len(still_open)} slots free")
    print("=" * 65)

if __name__ == "__main__":
    run_manager()
