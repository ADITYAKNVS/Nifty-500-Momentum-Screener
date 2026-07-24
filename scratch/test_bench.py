import sqlite3
import pandas as pd
import yfinance as yf
import numpy as np
import requests
from datetime import datetime

DB_PATH = "paper_trading.db"
INITIAL_CAPITAL = 10_00_000.0

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def test_benchmark():
    try:
        conn = get_db()
        snaps = pd.read_sql("SELECT date, portfolio_value FROM daily_snapshots ORDER BY date", conn)
        conn.close()

        print(f"Snapshots found: {len(snaps)}")
        if len(snaps) < 2:
            print("Error: Insufficient data")
            return

        first_date = snaps['date'].iloc[0]
        print(f"First date: {first_date}")
        
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})
        
        ticker = yf.Ticker("^NSEI", session=session)
        nifty_hist = ticker.history(start=first_date)
        print(f"Nifty rows fetched: {len(nifty_hist)}")
        
        if nifty_hist.empty:
            print("Error: Nifty data empty")
            return
            
        nifty_data = nifty_hist[['Close']].reset_index()
        nifty_data.columns = ['date', 'nifty_close']
        nifty_data['date'] = nifty_data['date'].dt.strftime('%Y-%m-%d')
        
        df = pd.merge(snaps, nifty_data, on='date', how='inner')
        print(f"Merged rows: {len(df)}")
        
        if len(df) < 2:
            print("Error: Insufficient overlapping dates")
            return
            
        initial_nifty = df['nifty_close'].iloc[0]
        df['nifty_value'] = INITIAL_CAPITAL * (df['nifty_close'] / initial_nifty)
        
        print("Success! Metrics can be calculated.")
        print(df.head())
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")

if __name__ == "__main__":
    test_benchmark()
