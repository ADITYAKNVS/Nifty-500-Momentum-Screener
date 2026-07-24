"""
Alpha Intelligence — Multi-User Server Engine
──────────────────────────────────────────────
FastAPI backend with per-user portfolio isolation via Firebase Auth tokens.
Each user's portfolio is stored in Firestore (client-side) AND mirrored
locally for fast backend operations.

Usage:
    python3 server.py
"""

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
import pandas as pd
from datetime import datetime
import yfinance as yf

app = FastAPI(title="Alpha Intelligence — Multi-User Terminal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3002", "http://127.0.0.1:3002", "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PARQUET_FILE = "nifty500_daily.parquet"
USERS_DIR = "user_data"

# Ensure user data directory exists
os.makedirs(USERS_DIR, exist_ok=True)


# ── Per-User File Helpers ──

def get_user_dir(user_id: str) -> str:
    """Get or create a user's data directory."""
    user_dir = os.path.join(USERS_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def get_positions_db(user_id: str):
    pos_file = os.path.join(get_user_dir(user_id), "positions.json")
    if not os.path.exists(pos_file):
        return {"cash": 1000000.0, "positions": []}
    with open(pos_file, 'r') as f:
        return json.load(f)

def save_positions_db(user_id: str, data):
    pos_file = os.path.join(get_user_dir(user_id), "positions.json")
    with open(pos_file, 'w') as f:
        json.dump(data, f, indent=4)

def get_trades_db(user_id: str):
    trades_file = os.path.join(get_user_dir(user_id), "trades.json")
    if not os.path.exists(trades_file):
        return []
    with open(trades_file, 'r') as f:
        return json.load(f)

def save_trades_db(user_id: str, data):
    trades_file = os.path.join(get_user_dir(user_id), "trades.json")
    with open(trades_file, 'w') as f:
        json.dump(data, f, indent=4)


# ── Price Engine ──

def get_ltp(ticker: str) -> float:
    # 1. Offline Parquet lookup
    try:
        if os.path.exists(PARQUET_FILE):
            df = pd.read_parquet(PARQUET_FILE)
            dft = df[df['Ticker'] == ticker].sort_values('Date')
            if not dft.empty:
                return float(dft.iloc[-1]['Close'])
    except Exception as e:
        print(f"Parquet lookup failed: {e}")
    
    # 2. Yahoo Finance live
    try:
        t = yf.Ticker(f"{ticker}.NS")
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist.iloc[-1]['Close'])
        return float(t.fast_info['lastPrice'])
    except:
        return 100.0


# ── Auth: Extract user ID from request header ──

def get_user_id(request: Request) -> str:
    """
    Extract user ID from X-User-ID header.
    In production, you'd verify the Firebase ID token here.
    For local dev, we fallback to an admin directory.
    """
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        return "alpha_admin_local"
    return user_id


# ── API Routes ──

class TradeRequest(BaseModel):
    ticker: str
    action: str
    qty: int
    price: str


@app.get("/api/portfolio")
def get_portfolio(request: Request):
    user_id = get_user_id(request)
    db = get_positions_db(user_id)
    
    live_positions = []
    total_position_val = 0.0
    
    for pos in db["positions"]:
        ltp = get_ltp(pos["ticker"])
        pnl = (ltp - pos["avg_price"]) * pos["qty"]
        
        live_positions.append({
            "ticker": pos["ticker"],
            "qty": pos["qty"],
            "avg_price": pos["avg_price"],
            "ltp": ltp,
            "pnl": pnl,
            "strategy": pos.get("strategy", "Momentum V2")
        })
        total_position_val += (ltp * pos["qty"])
    
    return {
        "cash": db["cash"],
        "portfolio_value": db["cash"] + total_position_val,
        "positions": live_positions
    }


@app.get("/api/history")
def get_history(request: Request):
    user_id = get_user_id(request)
    return get_trades_db(user_id)


@app.get("/api/quote")
def get_quote(ticker: str):
    ltp = get_ltp(ticker.upper())
    return {"ticker": ticker.upper(), "ltp": ltp}

@app.get("/api/tickers")
def get_tickers():
    if not os.path.exists("ind_nifty500list.csv"):
        return ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
    df = pd.read_csv("ind_nifty500list.csv")
    return df['Symbol'].tolist()

@app.get("/api/signals")
def get_signals(strategy: str = "momentum_v2"):
    try:
        filename = "ridge_pure_signals.json" if strategy == "ridge_pure" else "momentum_v2_signals.json"
        if os.path.exists(filename):
            with open(filename, "r") as f:
                data = json.load(f)
            
            # Fetch live Nifty 50 spot price from yfinance
            try:
                n50 = yf.Ticker("^NSEI")
                live_nifty = float(n50.fast_info.get('lastPrice') or n50.info.get('regularMarketPrice') or 0)
                if live_nifty > 0:
                    data["nifty_level"] = live_nifty
            except Exception as e:
                print(f"[API] Warning: Failed to fetch live Nifty 50 spot: {e}")
                
            return data
    except Exception:
        pass
    return {"signals": [], "nifty_level": 0, "regime": "Unknown"}


@app.get("/api/chart/{ticker}")
def get_chart(ticker: str):
    try:
        suffix = "" if ticker.startswith("^") else ".NS"
        t = yf.Ticker(f"{ticker.upper()}{suffix}")
        # Fetch 5-day intraday to ensure we have data if today is a holiday/weekend
        hist = t.history(period="5d", interval="5m")
        if hist.empty:
            hist = t.history(period="1mo", interval="1d")
            
        data = []
        for index, row in hist.iterrows():
            data.append({
                "time": int(index.timestamp()),
                "open": float(row['Open']),
                "high": float(row['High']),
                "low": float(row['Low']),
                "close": float(row['Close']),
                "volume": float(row.get('Volume', 0))
            })
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/execute")
def execute_trade(req: TradeRequest, request: Request):
    user_id = get_user_id(request)
    
    if req.qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
    
    ticker = req.ticker.upper()
    exec_price = float(req.price) if req.price.lower() != "mkt" else get_ltp(ticker)
    
    db = get_positions_db(user_id)
    trades = get_trades_db(user_id)
    
    total_cost = exec_price * req.qty
    
    if req.action == "BUY":
        if db["cash"] < total_cost:
            raise HTTPException(status_code=400, detail="Insufficient Unallocated Cash")
        
        db["cash"] -= total_cost
        
        pos_exists = False
        for pos in db["positions"]:
            if pos["ticker"] == ticker:
                old_qty = pos["qty"]
                old_avg = pos["avg_price"]
                new_qty = old_qty + req.qty
                pos["avg_price"] = ((old_avg * old_qty) + total_cost) / new_qty
                pos["qty"] = new_qty
                pos_exists = True
                break
        
        if not pos_exists:
            db["positions"].append({
                "ticker": ticker,
                "strategy": "Momentum V2",
                "qty": req.qty,
                "avg_price": exec_price
            })
    
    elif req.action == "SELL":
        pos_index = -1
        for i, pos in enumerate(db["positions"]):
            if pos["ticker"] == ticker:
                pos_index = i
                break
        
        if pos_index == -1:
            raise HTTPException(status_code=400, detail=f"No active position matching {ticker} to sell.")
        
        if db["positions"][pos_index]["qty"] < req.qty:
            raise HTTPException(status_code=400, detail="Cannot sell more quantity than owned.")
        
        db["cash"] += total_cost
        db["positions"][pos_index]["qty"] -= req.qty
        
        if db["positions"][pos_index]["qty"] == 0:
            db["positions"].pop(pos_index)
    
    # Record History
    log_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ticker": ticker,
        "action": req.action,
        "qty": req.qty,
        "price": exec_price,
        "status": "FILLED"
    }
    trades.insert(0, log_entry)
    
    save_positions_db(user_id, db)
    save_trades_db(user_id, trades)
    
    return {"message": "Trade executed successfully", "log": log_entry}


# ── Root redirect to login ──
@app.get("/")
def root_redirect():
    return {"status": "ok", "message": "Alpha Intelligence API is running."}

if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading
    import time
    
    def open_browser():
        time.sleep(1.5)
        # Point to the Next.js frontend
        webbrowser.open("http://localhost:3000")
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("🚀 Alpha Intelligence — API Engine Starting...")
    print("📡 Local Frontend: http://localhost:3000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
