"""
Paper Trading Backend — FastAPI + yfinance + SQLite
Run: uvicorn paper_trading:app --reload --port 8001

Supports per-strategy isolation: momentum_v2 and ridge_pure
each get their own portfolio, positions, trades, snapshots, and benchmarks.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3, json, os
import yfinance as yf
from datetime import datetime, date
import uvicorn
import threading
import time as _time
import numpy as np
import pandas as pd
import requests

app = FastAPI(title="Paper Trading API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "paper_trading.db"
INITIAL_CAPITAL = 10_00_000.0
VALID_STRATEGIES = ("momentum_v2", "ridge_pure")


# ─── Database ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(cursor, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cols = [row[1] for row in cursor.execute(f"PRAGMA table_info({table})")]
    return column in cols


def init_db():
    conn = get_db()
    c = conn.cursor()

    # ── Create tables if they don't exist ──
    c.execute("""CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY,
        cash REAL DEFAULT 1000000.0,
        initial_capital REAL DEFAULT 1000000.0,
        strategy TEXT DEFAULT 'momentum_v2'
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS positions (
        symbol TEXT,
        qty REAL,
        avg_cost REAL,
        strategy TEXT DEFAULT 'momentum_v2',
        PRIMARY KEY (symbol, strategy)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        side TEXT,
        qty REAL,
        price REAL,
        timestamp TEXT,
        pnl REAL DEFAULT 0.0,
        strategy TEXT DEFAULT 'momentum_v2'
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS daily_snapshots (
        date TEXT,
        portfolio_value REAL,
        cash REAL,
        daily_pnl REAL,
        daily_pnl_pct REAL,
        strategy TEXT DEFAULT 'momentum_v2',
        PRIMARY KEY (date, strategy)
    )""")

    # Price cache — stores last known good price per symbol so yfinance
    # failures don't destroy portfolio value
    c.execute("""CREATE TABLE IF NOT EXISTS price_cache (
        symbol TEXT PRIMARY KEY,
        price REAL,
        updated_at TEXT
    )""")

    # ── Migration: add strategy column to legacy tables if missing ──
    migrated = False

    if not _column_exists(c, "portfolio", "strategy"):
        print("🔄 Migrating portfolio table: adding 'strategy' column...")
        c.execute("ALTER TABLE portfolio ADD COLUMN strategy TEXT DEFAULT 'momentum_v2'")
        c.execute("UPDATE portfolio SET strategy = 'momentum_v2' WHERE strategy IS NULL")
        migrated = True

    if not _column_exists(c, "positions", "strategy"):
        print("🔄 Migrating positions table: adding 'strategy' column...")
        # SQLite doesn't support adding columns to change PKs, so we rebuild
        c.execute("ALTER TABLE positions RENAME TO positions_old")
        c.execute("""CREATE TABLE positions (
            symbol TEXT,
            qty REAL,
            avg_cost REAL,
            strategy TEXT DEFAULT 'momentum_v2',
            PRIMARY KEY (symbol, strategy)
        )""")
        c.execute("""INSERT INTO positions (symbol, qty, avg_cost, strategy)
                     SELECT symbol, qty, avg_cost, 'momentum_v2' FROM positions_old""")
        c.execute("DROP TABLE positions_old")
        migrated = True

    if not _column_exists(c, "trades", "strategy"):
        print("🔄 Migrating trades table: adding 'strategy' column...")
        c.execute("ALTER TABLE trades ADD COLUMN strategy TEXT DEFAULT 'momentum_v2'")
        c.execute("UPDATE trades SET strategy = 'momentum_v2' WHERE strategy IS NULL")
        migrated = True

    if not _column_exists(c, "daily_snapshots", "strategy"):
        print("🔄 Migrating daily_snapshots table: adding 'strategy' column...")
        # Rebuild to change PK from (date) to (date, strategy)
        c.execute("ALTER TABLE daily_snapshots RENAME TO daily_snapshots_old")
        c.execute("""CREATE TABLE daily_snapshots (
            date TEXT,
            portfolio_value REAL,
            cash REAL,
            daily_pnl REAL,
            daily_pnl_pct REAL,
            strategy TEXT DEFAULT 'momentum_v2',
            PRIMARY KEY (date, strategy)
        )""")
        c.execute("""INSERT INTO daily_snapshots (date, portfolio_value, cash, daily_pnl, daily_pnl_pct, strategy)
                     SELECT date, portfolio_value, cash, daily_pnl, daily_pnl_pct, 'momentum_v2'
                     FROM daily_snapshots_old""")
        c.execute("DROP TABLE daily_snapshots_old")
        migrated = True

    if migrated:
        print("✅ Migration complete — existing data tagged as 'momentum_v2'")

    # ── Seed portfolios if missing ──
    # Momentum V2
    mv2 = c.execute("SELECT COUNT(*) FROM portfolio WHERE strategy = 'momentum_v2'").fetchone()[0]
    if mv2 == 0:
        c.execute("INSERT INTO portfolio (cash, initial_capital, strategy) VALUES (?,?,?)",
                  (INITIAL_CAPITAL, INITIAL_CAPITAL, "momentum_v2"))
        print("🆕 Created momentum_v2 portfolio with ₹10L")

    # Ridge Pure
    rp = c.execute("SELECT COUNT(*) FROM portfolio WHERE strategy = 'ridge_pure'").fetchone()[0]
    if rp == 0:
        c.execute("INSERT INTO portfolio (cash, initial_capital, strategy) VALUES (?,?,?)",
                  (INITIAL_CAPITAL, INITIAL_CAPITAL, "ridge_pure"))
        print("🆕 Created ridge_pure portfolio with ₹10L")

    conn.commit()
    conn.close()


def _validate_strategy(strategy: str) -> str:
    s = strategy.strip().lower()
    if s not in VALID_STRATEGIES:
        raise HTTPException(400, f"Invalid strategy '{strategy}'. Must be one of: {VALID_STRATEGIES}")
    return s


# ─── Price Fetching ───────────────────────────────────────────────────────────

def _get_cached_price(symbol: str) -> float:
    """Return last known good price from SQLite cache, or 0 if none."""
    try:
        conn = get_db()
        row = conn.execute("SELECT price FROM price_cache WHERE symbol=?", (symbol,)).fetchone()
        conn.close()
        return float(row["price"]) if row else 0.0
    except Exception:
        return 0.0


def _set_cached_price(symbol: str, price: float) -> None:
    """Store a known-good price in the cache."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO price_cache (symbol, price, updated_at) VALUES (?,?,?)",
            (symbol, price, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def fetch_price(symbol: str) -> float:
    """Fetch latest price using yfinance. Prioritizes actual live LTP over 1m history closes."""
    try:
        yf_symbol = symbol if "." in symbol or symbol.startswith("^") else f"{symbol}.NS"
        ticker = yf.Ticker(yf_symbol)
        
        # 1. Try to get live Last Traded Price (LTP) first
        try:
            live = float(ticker.fast_info['last_price'])
            if live > 0:
                _set_cached_price(symbol, live)
                return live
        except Exception:
            pass
            
        # 2. Fallback to info dictionary
        try:
            live = float(ticker.info.get("regularMarketPrice") or ticker.info.get("currentPrice") or 0)
            if live > 0:
                _set_cached_price(symbol, live)
                return live
        except Exception:
            pass
            
        # 3. Fallback to last 1-minute history candle close
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            if price > 0:
                _set_cached_price(symbol, price)
                return price
    except Exception:
        pass

    # yfinance failed — use last known good price from cache
    cached = _get_cached_price(symbol)
    if cached > 0:
        print(f"  [PRICE] Using cached price for {symbol}: ₹{cached:.2f}")
    return cached



# ─── Portfolio Logic ──────────────────────────────────────────────────────────

def compute_portfolio(strategy: str = "momentum_v2") -> dict:
    conn = get_db()
    c = conn.cursor()

    row = c.execute("SELECT * FROM portfolio WHERE strategy=?", (strategy,)).fetchone()
    if not row:
        conn.close()
        return {
            "cash": INITIAL_CAPITAL, "holdings_value": 0.0,
            "total_value": INITIAL_CAPITAL, "initial_capital": INITIAL_CAPITAL,
            "total_pnl": 0.0, "total_pnl_pct": 0.0, "positions": [],
        }

    cash = row["cash"]
    initial = row["initial_capital"]

    positions_rows = c.execute("SELECT * FROM positions WHERE strategy=?", (strategy,)).fetchall()
    conn.close()

    positions = []
    holdings_value = 0.0

    for p in positions_rows:
        sym = p["symbol"]
        qty = p["qty"]
        avg_cost = p["avg_cost"]
        price = fetch_price(sym)
        mkt_val = qty * price
        cost_basis = qty * avg_cost
        upnl = mkt_val - cost_basis
        upnl_pct = (upnl / cost_basis * 100) if cost_basis else 0
        holdings_value += mkt_val
        positions.append({
            "symbol": sym, "qty": qty, "avg_cost": round(avg_cost, 4),
            "current_price": round(price, 4), "market_value": round(mkt_val, 2),
            "unrealized_pnl": round(upnl, 2), "unrealized_pnl_pct": round(upnl_pct, 2),
        })

    total_value = cash + holdings_value
    total_pnl = total_value - initial
    total_pnl_pct = (total_pnl / initial * 100)

    return {
        "cash": round(cash, 2),
        "holdings_value": round(holdings_value, 2),
        "total_value": round(total_value, 2),
        "initial_capital": round(initial, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "positions": positions,
    }


def take_snapshot(label: str = "auto", strategy: str = "momentum_v2"):
    """Record EOD (or on-demand) portfolio snapshot for a specific strategy."""
    # Guard: Do not take snapshots on weekends (Saturday=5, Sunday=6)
    if datetime.now().weekday() >= 5:
        print(f"[{label}] ⚠️  Skipping snapshot — weekend")
        return

    pf = compute_portfolio(strategy)
    today = date.today().isoformat()

    # Guard: if ANY position has price=0, yfinance failed — skip snapshot
    # to avoid recording garbage values that corrupt the equity curve
    for pos in pf["positions"]:
        if pos["current_price"] <= 0:
            print(f"[{label}/{strategy}] ⚠️  Skipping snapshot — price unavailable for {pos['symbol']}")
            return

    conn = get_db()
    c = conn.cursor()

    # FIX: Get previous DAY's snapshot (exclude today) so same-day
    # restarts don't reset daily_pnl to 0
    prev = c.execute(
        "SELECT portfolio_value FROM daily_snapshots WHERE date < ? AND strategy = ? ORDER BY date DESC LIMIT 1",
        (today, strategy)
    ).fetchone()
    prev_val = prev["portfolio_value"] if prev else pf["initial_capital"]

    daily_pnl = pf["total_value"] - prev_val
    daily_pnl_pct = (daily_pnl / prev_val * 100) if prev_val else 0

    c.execute("""INSERT OR REPLACE INTO daily_snapshots
                 (date, portfolio_value, cash, daily_pnl, daily_pnl_pct, strategy)
                 VALUES (?,?,?,?,?,?)""",
              (today, pf["total_value"], pf["cash"],
               round(daily_pnl, 2), round(daily_pnl_pct, 4), strategy))
    conn.commit()
    conn.close()
    print(f"[{label}/{strategy}] Snapshot {today}: ₹{pf['total_value']:.2f}  daily_pnl=₹{daily_pnl:.2f}  cumulative=₹{pf['total_pnl']:.2f}")


def compute_stats(strategy: str = "momentum_v2") -> dict:
    conn = get_db()
    c = conn.cursor()

    # Count ALL sell trades as completed round-trips (including zero-PnL ones)
    trades = c.execute(
        "SELECT pnl FROM trades WHERE side = 'sell' AND strategy = ? ORDER BY timestamp",
        (strategy,)
    ).fetchall()
    snaps = c.execute(
        "SELECT date, portfolio_value FROM daily_snapshots WHERE strategy = ? ORDER BY date",
        (strategy,)
    ).fetchall()
    conn.close()

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = (len(wins) / len(pnls) * 100) if pnls else 0
    avg_win = (sum(wins) / len(wins)) if wins else 0
    avg_loss = (sum(losses) / len(losses)) if losses else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss else 0
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    # Max drawdown from equity curve — include current live portfolio value if weekday
    max_dd = 0.0
    max_dd_pct = 0.0
    vals = [s["portfolio_value"] for s in snaps] if snaps else []
    
    live_pf = compute_portfolio(strategy)
    today_str = date.today().isoformat()
    # Append current live portfolio value so drawdown is tracked across all holding days
    if date.today().weekday() < 5:
        if not snaps or snaps[-1]["date"] != today_str:
            vals.append(live_pf["total_value"])
            
    if vals:
        peak = vals[0]
        for v in vals:
            if v > peak:
                peak = v
            dd = peak - v
            dd_pct = (dd / peak * 100) if peak else 0
            if dd > max_dd:
                max_dd, max_dd_pct = dd, dd_pct

    # Cumulative PnL from inception (initial capital to current live value)
    cumulative_pnl = live_pf["total_value"] - live_pf["initial_capital"]
    cumulative_pnl_pct = (cumulative_pnl / live_pf["initial_capital"] * 100) if live_pf["initial_capital"] else 0

    return {
        "total_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "cumulative_pnl": round(cumulative_pnl, 2),
        "cumulative_pnl_pct": round(cumulative_pnl_pct, 2),
    }


# ─── API Routes ───────────────────────────────────────────────────────────────

class TradeReq(BaseModel):
    symbol: str
    side: str   # "buy" | "sell"
    qty: float
    strategy: str = "momentum_v2"


@app.get("/api/portfolio")
def api_portfolio(strategy: str = Query("momentum_v2")):
    strategy = _validate_strategy(strategy)
    return compute_portfolio(strategy)


@app.get("/api/price/{symbol}")
def api_price(symbol: str):
    p = fetch_price(symbol.upper())
    if p == 0:
        raise HTTPException(404, f"Price unavailable for {symbol.upper()}")
    return {"symbol": symbol.upper(), "price": round(p, 4)}


@app.post("/api/trade")
def api_trade(req: TradeReq):
    strategy = _validate_strategy(req.strategy)
    symbol = req.symbol.strip().upper()
    side = req.side.lower()
    qty = req.qty

    if qty <= 0:
        raise HTTPException(400, "Quantity must be > 0")
    if side not in ("buy", "sell"):
        raise HTTPException(400, "Side must be 'buy' or 'sell'")

    price = fetch_price(symbol)
    if price <= 0:
        raise HTTPException(400, f"Could not fetch price for {symbol}")

    cost = round(price * qty, 2)
    conn = get_db()
    c = conn.cursor()
    pf = c.execute("SELECT * FROM portfolio WHERE strategy=?", (strategy,)).fetchone()
    if not pf:
        conn.close()
        raise HTTPException(400, f"No portfolio found for strategy '{strategy}'")
    cash = pf["cash"]
    pnl = 0.0

    if side == "buy":
        if cash < cost:
            conn.close()
            raise HTTPException(400, f"Insufficient cash — need ₹{cost:.2f}, have ₹{cash:.2f}")
        c.execute("UPDATE portfolio SET cash=? WHERE strategy=?", (cash - cost, strategy))
        ex = c.execute("SELECT * FROM positions WHERE symbol=? AND strategy=?", (symbol, strategy)).fetchone()
        if ex:
            new_qty = ex["qty"] + qty
            new_avg = (ex["qty"] * ex["avg_cost"] + qty * price) / new_qty
            c.execute("UPDATE positions SET qty=?,avg_cost=? WHERE symbol=? AND strategy=?",
                      (new_qty, new_avg, symbol, strategy))
        else:
            c.execute("INSERT INTO positions (symbol,qty,avg_cost,strategy) VALUES (?,?,?,?)",
                      (symbol, qty, price, strategy))

    else:  # sell
        ex = c.execute("SELECT * FROM positions WHERE symbol=? AND strategy=?", (symbol, strategy)).fetchone()
        if not ex or ex["qty"] < qty:
            conn.close()
            raise HTTPException(400, f"Insufficient shares — have {ex['qty'] if ex else 0}")
        pnl = round((price - ex["avg_cost"]) * qty, 2)
        c.execute("UPDATE portfolio SET cash=? WHERE strategy=?", (cash + cost, strategy))
        new_qty = ex["qty"] - qty
        if new_qty < 1e-6:
            c.execute("DELETE FROM positions WHERE symbol=? AND strategy=?", (symbol, strategy))
        else:
            c.execute("UPDATE positions SET qty=? WHERE symbol=? AND strategy=?", (new_qty, symbol, strategy))

    c.execute(
        "INSERT INTO trades (symbol,side,qty,price,timestamp,pnl,strategy) VALUES (?,?,?,?,?,?,?)",
        (symbol, side, qty, price, datetime.now().isoformat(), pnl, strategy)
    )
    conn.commit()
    conn.close()

    take_snapshot("trade", strategy)

    return {
        "success": True, "symbol": symbol, "side": side,
        "qty": qty, "price": price, "total": cost, "pnl": pnl,
        "strategy": strategy,
        "message": f"{'Bought' if side=='buy' else 'Sold'} {qty} {symbol} @ ₹{price:.2f} [{strategy}]"
    }


@app.get("/api/stats")
def api_stats(strategy: str = Query("momentum_v2")):
    strategy = _validate_strategy(strategy)
    return compute_stats(strategy)


@app.get("/api/history")
def api_history(strategy: str = Query("momentum_v2")):
    strategy = _validate_strategy(strategy)
    conn = get_db()
    c = conn.cursor()
    trades = c.execute(
        "SELECT * FROM trades WHERE strategy=? ORDER BY timestamp DESC LIMIT 200",
        (strategy,)
    ).fetchall()
    snaps = c.execute(
        "SELECT * FROM daily_snapshots WHERE strategy=? ORDER BY date",
        (strategy,)
    ).fetchall()
    conn.close()
    return {
        "trades": [dict(t) for t in trades],
        "snapshots": [dict(s) for s in snaps],
    }


@app.post("/api/snapshot")
def api_snapshot(strategy: str = Query("momentum_v2")):
    strategy = _validate_strategy(strategy)
    take_snapshot("manual", strategy)
    return {"success": True, "message": f"Snapshot recorded for {strategy}"}


@app.get("/api/cumulative")
def api_cumulative(strategy: str = Query("momentum_v2")):
    """Full cumulative stats from inception — never resets between days."""
    strategy = _validate_strategy(strategy)
    pf = compute_portfolio(strategy)
    stats = compute_stats(strategy)

    conn = get_db()
    c = conn.cursor()
    snaps = c.execute(
        "SELECT date, portfolio_value, daily_pnl, daily_pnl_pct FROM daily_snapshots WHERE strategy=? ORDER BY date",
        (strategy,)
    ).fetchall()
    conn.close()

    equity_curve = [{"date": s["date"], "value": s["portfolio_value"]} for s in snaps]
    # Append live value as today's data point only if today is a weekday
    today_str = date.today().isoformat()
    if date.today().weekday() < 5:
        if not snaps or snaps[-1]["date"] != today_str:
            equity_curve.append({"date": today_str, "value": pf["total_value"]})

    return {
        "initial_capital": pf["initial_capital"],
        "current_value": pf["total_value"],
        "cumulative_pnl": stats["cumulative_pnl"],
        "cumulative_pnl_pct": stats["cumulative_pnl_pct"],
        "max_drawdown": stats["max_drawdown"],
        "max_drawdown_pct": stats["max_drawdown_pct"],
        "equity_curve": equity_curve,
        "total_snapshots": len(snaps),
    }


@app.get("/api/benchmark")
def api_benchmark(strategy: str = Query("momentum_v2")):
    """
    Comprehensive performance comparison against Nifty 50 index.
    Includes Alpha, Beta, Sharpe, Max Drawdown and Monthly Returns.
    Filtered by strategy.
    """
    strategy = _validate_strategy(strategy)
    try:
        conn = get_db()
        snaps = pd.read_sql(
            "SELECT date, portfolio_value FROM daily_snapshots WHERE strategy=? ORDER BY date",
            conn, params=(strategy,)
        )
        
        # --- INJECT LIVE POINT ---
        # Calculate current live AUM to ensure benchmark matches Telemetry exactly
        try:
            pf = compute_portfolio(strategy)
            current_aum = pf["total_value"]
            today_str = date.today().strftime('%Y-%m-%d')
            
            # Only inject today's live point if it's a weekday
            if date.today().weekday() < 5:
                # If today already has a snapshot, update it; otherwise append
                if not snaps.empty and snaps['date'].iloc[-1] == today_str:
                    snaps.loc[snaps.index[-1], 'portfolio_value'] = current_aum
                else:
                    new_row = pd.DataFrame({'date': [today_str], 'portfolio_value': [current_aum]})
                    snaps = pd.concat([snaps, new_row], ignore_index=True)
        except Exception as e:
            print(f"[BENCHMARK/{strategy}] Live injection failed: {e}")
        
        conn.close()

        if len(snaps) < 2:
            return {
                "error": "Insufficient data. Need at least 2 snapshots for comparison.",
                "equity_curve": snaps.to_dict('records') if not snaps.empty else [],
                "metrics": None,
                "monthly_returns": []
            }

        first_date = snaps['date'].iloc[0]
        
        # 1. Fetch Nifty 50 with a buffer to find the "Pre-Inception" close
        nifty_data = pd.DataFrame()
        fetch_error = None
        
        try:
            ticker = yf.Ticker("^NSEI")
            # Fetch from 14 days before to find the last trading day before inception
            buffer_start = (pd.to_datetime(first_date) - pd.Timedelta(days=14)).strftime('%Y-%m-%d')
            nifty_hist = ticker.history(start=buffer_start)
            
            if not nifty_hist.empty:
                nifty_data = nifty_hist[['Close']].reset_index()
                nifty_data.columns = ['date', 'nifty_close']
                # Strip timezone to allow merging with naive portfolio dates
                nifty_data['date_dt'] = pd.to_datetime(nifty_data['date']).dt.tz_localize(None)
            else:
                fetch_error = "Yahoo Finance returned no data for Nifty 50."
        except Exception as e:
            fetch_error = f"Nifty 50 connection error: {str(e)}"

        # 2. Prepare FULL data for Metric Calculation (starting from inception)
        snaps['date_dt'] = pd.to_datetime(snaps['date'])
        
        if not nifty_data.empty:
            # Get list of trading days from Nifty 50
            trading_dates = set(nifty_data['date_dt'].dt.strftime('%Y-%m-%d').tolist())
            
            # If today is a weekday and not in Nifty data yet, add it
            today_str = date.today().strftime('%Y-%m-%d')
            if date.today().weekday() < 5:
                trading_dates.add(today_str)
                
            # Create a sorted DataFrame of these trading dates starting from first snapshot date
            df_trading = pd.DataFrame({'date_dt': pd.to_datetime(sorted(list(trading_dates)))})
            df_trading = df_trading[df_trading['date_dt'] >= snaps['date_dt'].min()].copy()
            
            # Join snaps and Nifty data onto this trading day grid
            df_metrics = pd.merge(df_trading, snaps[['date_dt', 'portfolio_value']], on='date_dt', how='left')
            df_metrics['portfolio_value'] = df_metrics['portfolio_value'].ffill().bfill()
            
            df_metrics = pd.merge(df_metrics, nifty_data[['date_dt', 'nifty_close']], on='date_dt', how='left')
            df_metrics['nifty_close'] = df_metrics['nifty_close'].ffill().bfill()
            
            # If today is a weekday and we don't have the nifty close yet, fetch live price
            if today_str in trading_dates:
                today_dt = pd.to_datetime(today_str)
                if pd.isna(df_metrics.loc[df_metrics['date_dt'] == today_dt, 'nifty_close'].values[0]):
                    try:
                        nifty_ticker = yf.Ticker("^NSEI")
                        live_nifty = float(nifty_ticker.fast_info.get('lastPrice') or nifty_ticker.info.get('regularMarketPrice') or 0)
                        if live_nifty > 0:
                            df_metrics.loc[df_metrics['date_dt'] == today_dt, 'nifty_close'] = live_nifty
                    except Exception as e:
                        print(f"[BENCHMARK/{strategy}] Live Nifty price fetch failed: {e}")
            
            # Find the Nifty Price on the last trading day BEFORE the user started
            # This is the price that represents the 10L starting value
            pre_inception_nifty = nifty_data[nifty_data['date_dt'] < pd.to_datetime(first_date)]
            if not pre_inception_nifty.empty:
                nifty_base_price = pre_inception_nifty['nifty_close'].iloc[-1]
            else:
                nifty_base_price = df_metrics['nifty_close'].iloc[0]
        else:
            # Fallback if nifty_data is empty
            full_range = pd.date_range(start=snaps['date_dt'].min(), end=pd.to_datetime(date.today()), freq='D')
            df_metrics = pd.DataFrame({'date_dt': full_range})
            df_metrics = pd.merge(df_metrics, snaps[['date_dt', 'portfolio_value']], on='date_dt', how='left')
            df_metrics['portfolio_value'] = df_metrics['portfolio_value'].ffill().bfill()
            nifty_base_price = 1.0
            df_metrics['nifty_close'] = 1.0
            
        # 3. Normalize Nifty (Nifty at 10L on its last close before you started)
        df_metrics['nifty_value'] = INITIAL_CAPITAL * (df_metrics['nifty_close'] / nifty_base_price)

        # 4. Calculate Daily Returns on FULL history
        df_metrics['port_ret'] = df_metrics['portfolio_value'].pct_change().fillna(0)
        df_metrics['nifty_ret'] = df_metrics['nifty_value'].pct_change().fillna(0)

        # 5. Calculate Metrics on FULL history
        port_total_ret = (df_metrics['portfolio_value'].iloc[-1] / INITIAL_CAPITAL - 1) * 100
        nifty_total_ret = (df_metrics['nifty_value'].iloc[-1] / INITIAL_CAPITAL - 1) * 100
        alpha = port_total_ret - nifty_total_ret

        # Beta
        try:
            if len(df_metrics) > 2:
                # Use standard OLS beta logic
                cov = np.cov(df_metrics['port_ret'], df_metrics['nifty_ret'])[0][1]
                var = np.var(df_metrics['nifty_ret'], ddof=1)
                beta = cov / var if var > 0.000001 else 1.0
            else:
                beta = 1.0
        except:
            beta = 1.0

        # Sharpe
        sharpe = 0
        if len(df_metrics) > 5:
            rfr_daily = 0.065 / 252
            excess = df_metrics['port_ret'] - rfr_daily
            sharpe = (excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0.0001 else 0
        else:
            sharpe = -999 

        # Max Drawdown (calculated on the full range, capturing the initial 10L peak)
        def get_max_dd(values):
            # Prepend INITIAL_CAPITAL to capture drawdown from day 0
            all_values = pd.concat([pd.Series([INITIAL_CAPITAL]), values])
            peak = all_values.cummax()
            dd = (all_values - peak) / peak
            return dd.min() * 100

        port_mdd = get_max_dd(df_metrics['portfolio_value'])
        nifty_mdd = get_max_dd(df_metrics['nifty_value'])

        # 6. Filter for display (May 11th onwards)
        df_display = df_metrics[df_metrics['date_dt'] >= '2026-05-11'].copy()
        df_display['date'] = df_display['date_dt'].dt.strftime('%Y-%m-%d')

        # 7. Monthly Returns (Inception to Date)
        df_metrics['dt'] = df_metrics['date_dt']
        df_monthly = df_metrics.set_index('dt').resample('ME').last()
        
        monthly_table = []
        df_monthly['port_mom'] = df_monthly['portfolio_value'].pct_change() * 100
        df_monthly['nifty_mom'] = df_monthly['nifty_value'].pct_change() * 100
        
        if not df_monthly.empty:
            first_idx = df_monthly.index[0]
            df_monthly.at[first_idx, 'port_mom'] = (df_monthly.at[first_idx, 'portfolio_value'] / INITIAL_CAPITAL - 1) * 100
            df_monthly.at[first_idx, 'nifty_mom'] = (df_monthly.at[first_idx, 'nifty_value'] / INITIAL_CAPITAL - 1) * 100

        for idx, row in df_monthly.iterrows():
            monthly_table.append({
                "month": idx.strftime('%b %Y'),
                "portfolio_return": round(float(row['port_mom']), 2),
                "nifty_return": round(float(row['nifty_mom']), 2),
                "alpha": round(float(row['port_mom'] - row['nifty_mom']), 2)
            })
        
        monthly_table.reverse()

        return {
            "equity_curve": df_display[['date', 'portfolio_value', 'nifty_value']].to_dict('records'),
            "metrics": {
                "portfolio_total_return_pct": round(port_total_ret, 2),
                "nifty_total_return_pct": round(nifty_total_ret, 2),
                "alpha": round(alpha, 2),
                "beta": round(float(beta), 2),
                "sharpe_ratio": round(float(sharpe), 2),
                "portfolio_max_drawdown_pct": round(port_mdd, 2),
                "nifty_max_drawdown_pct": round(nifty_mdd, 2)
            },
            "monthly_returns": monthly_table
        }
    except Exception as e:
        print(f"[BENCHMARK/{strategy} ERROR] {e}")
        return {"error": str(e)}


@app.post("/api/reset")
def api_reset(strategy: str = Query("momentum_v2")):
    strategy = _validate_strategy(strategy)
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE portfolio SET cash=?,initial_capital=? WHERE strategy=?",
              (INITIAL_CAPITAL, INITIAL_CAPITAL, strategy))
    c.execute("DELETE FROM positions WHERE strategy=?", (strategy,))
    c.execute("DELETE FROM trades WHERE strategy=?", (strategy,))
    c.execute("DELETE FROM daily_snapshots WHERE strategy=?", (strategy,))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Portfolio reset to ₹10,00,000 for {strategy}"}


# ─── Background Snapshot Thread ──────────────────────────────────────────────

def _snapshot_loop():
    """
    Background thread that takes a portfolio snapshot every 30 minutes
    during Indian market hours (9:15 AM — 3:45 PM, Mon—Fri).
    This ensures PnL and drawdown accumulate across days even without trades.
    Snapshots both strategies independently.
    """
    while True:
        try:
            now = datetime.now()
            # Only run Mon-Fri (weekday 0=Mon, 4=Fri)
            if now.weekday() < 5:
                market_open = now.replace(hour=9, minute=15, second=0)
                market_close = now.replace(hour=15, minute=45, second=0)
                if market_open <= now <= market_close:
                    for strat in VALID_STRATEGIES:
                        take_snapshot("auto", strat)
        except Exception as e:
            print(f"[auto-snapshot] Error: {e}")
        _time.sleep(1800)  # 30 minutes


@app.on_event("startup")
def startup_event():
    init_db()

    # Take an immediate snapshot on startup so we always have today's baseline
    for strat in VALID_STRATEGIES:
        try:
            take_snapshot("startup", strat)
        except Exception as e:
            print(f"[startup snapshot/{strat}] Warning: {e}")

    # Start background auto-snapshot thread (no external dependency needed)
    global _snap_thread_started
    if not globals().get("_snap_thread_started", False):
        snap_thread = threading.Thread(target=_snapshot_loop, daemon=True)
        snap_thread.start()
        globals()["_snap_thread_started"] = True
        print("✅ Auto-snapshot thread started (every 30 min during market hours)")


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("✅ Paper Trading Server running at http://localhost:8001")
    uvicorn.run("paper_trading:app", host="0.0.0.0", port=8001, log_level="info")

