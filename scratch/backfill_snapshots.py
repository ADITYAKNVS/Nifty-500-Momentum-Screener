import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime, date

DB_PATH = "paper_trading.db"
PARQUET_FILE = "nifty500_daily.parquet"
INITIAL_CAPITAL = 1000000.0

def run_backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch all trades
    trades = pd.read_sql("SELECT * FROM trades ORDER BY timestamp", conn)
    print(f"Loaded {len(trades)} trades.")
    
    # 2. Get list of trading days from Nifty 50 (from 2026-05-10 onwards)
    print("Fetching Nifty 50 historical dates...")
    ticker = yf.Ticker("^NSEI")
    nifty_hist = ticker.history(start="2026-05-10")
    trading_days = nifty_hist.index.strftime('%Y-%m-%d').tolist()
    print(f"Trading days identified: {trading_days}")
    
    # 3. Load daily stock data from parquet
    print("Loading daily stock prices from parquet...")
    df_parquet = pd.read_parquet(PARQUET_FILE)
    df_parquet['Date_str'] = df_parquet['Date'].dt.strftime('%Y-%m-%d')
    price_lookup = df_parquet.set_index(['Ticker', 'Date_str'])['Close'].to_dict()
    
    # To handle fallbacks (if a ticker is not found in parquet on a day, we look for the latest price on/before it)
    ticker_history = {}
    for ticker_name, group in df_parquet.groupby('Ticker'):
        ticker_history[ticker_name] = group.sort_values('Date_str')[['Date_str', 'Close']].values.tolist()

    # 4. Reconstruct portfolio for each trading day
    snapshots = []
    prev_val = INITIAL_CAPITAL
    
    for d_str in trading_days:
        # Trades that happened on or before this day
        # Compare first 10 characters of trade timestamp (YYYY-MM-DD)
        trades_before = trades[trades['timestamp'].str.slice(0, 10) <= d_str]
        
        cash = INITIAL_CAPITAL
        holdings = {}
        for _, t in trades_before.iterrows():
            sym = t['symbol']
            side = t['side']
            qty = t['qty']
            price = t['price']
            cost = qty * price
            if side == 'buy':
                cash -= cost
                holdings[sym] = holdings.get(sym, 0) + qty
            elif side == 'sell':
                cash += cost
                holdings[sym] = holdings.get(sym, 0) - qty
                
        # Filter out tiny/zero holdings
        holdings = {k: v for k, v in holdings.items() if v > 1e-5}
        
        # Calculate portfolio value on this day
        holdings_value = 0.0
        for sym, qty in holdings.items():
            price = price_lookup.get((sym, d_str))
            if price is None:
                # Find the latest price on or before d_str
                hist = ticker_history.get(sym, [])
                last_price = 0.0
                for date_str, close in hist:
                    if date_str <= d_str:
                        last_price = close
                    else:
                        break
                # Cache fallback
                if last_price == 0.0:
                    row = conn.execute("SELECT price FROM price_cache WHERE symbol=?", (sym,)).fetchone()
                    if row:
                        last_price = row[0]
                    else:
                        # Trade price fallback
                        first_trade = trades[trades['symbol'] == sym].iloc[0]
                        last_price = first_trade['price']
                price = last_price
            
            holdings_value += qty * price
            
        port_val = cash + holdings_value
        daily_pnl = port_val - prev_val
        daily_pnl_pct = (daily_pnl / prev_val * 100) if prev_val else 0.0
        
        snapshots.append({
            'date': d_str,
            'portfolio_value': round(port_val, 2),
            'cash': round(cash, 2),
            'daily_pnl': round(daily_pnl, 2),
            'daily_pnl_pct': round(daily_pnl_pct, 4)
        })
        prev_val = port_val
        
    # 5. Clear and write to daily_snapshots table
    print("Clearing daily_snapshots table...")
    c.execute("DELETE FROM daily_snapshots")
    
    print("Inserting reconstructed snapshots...")
    for snap in snapshots:
        c.execute("""INSERT INTO daily_snapshots 
                     (date, portfolio_value, cash, daily_pnl, daily_pnl_pct)
                     VALUES (?, ?, ?, ?, ?)""",
                  (snap['date'], snap['portfolio_value'], snap['cash'], snap['daily_pnl'], snap['daily_pnl_pct']))
    
    conn.commit()
    conn.close()
    print("Backfill complete! Reconstructed snapshots in DB:")
    for snap in snapshots:
        print(f"  {snap['date']}: AUM={snap['portfolio_value']} (pnl={snap['daily_pnl']}, pnl_pct={snap['daily_pnl_pct']}%)")

if __name__ == "__main__":
    run_backfill()
