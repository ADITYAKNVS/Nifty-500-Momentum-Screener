# Alpha Quant V5 — Systematic Breakout Strategy
### A Quantitative Trading System for the Indian Equity Market

---

## Executive Summary

Alpha Quant V5 is a **rule-based systematic trading system** that scans 499 Nifty 500 stocks daily to identify high-probability breakout setups. The system combines three institutional-grade indicators — **VHF (Vertical Horizontal Filter)**, **KAMA (Kaufman Adaptive Moving Average)**, and **Linear Regression Z-Score** — with a market regime filter and strict risk management to generate swing trade signals with a 30-45 day holding period.

### Key Backtest Results (2014–2025, 499 Stocks)

| Metric | Value |
|--------|-------|
| **Total Trades** | 188 |
| **Win Rate** | 43.6% |
| **Avg Winner** | +7.07% |
| **Avg Loser** | -5.04% |
| **Profit Factor** | 1.39 |
| **CAGR** | +2.06% |
| **Max Drawdown** | -9.27% |
| **Risk-Reward Ratio** | 1 : 1.67 |

---

## The Core Idea

> **Buy stocks that are consolidating in an uptrend and breaking out with momentum — but only when the overall market is bullish.**

This is inspired by **Mark Minervini's VCP (Volatility Contraction Pattern)** and **William O'Neil's CANSLIM** methodology, translated into quantitative, rule-based signals.

---

## Strategy Logic

### Entry Conditions (ALL must be true)
1. **Market Regime Filter** — A synthetic Nifty proxy (average of RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK) must be above its 200-day SMA → market is bullish
2. **20-Day High Breakout** — Stock closes above its previous 20-day high
3. **Volatility Contraction** — Bollinger Band Width is below its 50-period median → stock is consolidating
4. **VHF > 0.35** — Strong directional trend confirmed
5. **Close > KAMA** — Adaptive moving average is supportive
6. **Close > 200 SMA** — Long-term uptrend intact
7. **Z-Score > 1.2** — Momentum is statistically significant (above 1.2 standard deviations)
8. **Volume > 20-day Average** — Breakout is supported by volume
9. **Price > ₹100** — Filters out penny stocks

### Exit Conditions (first one triggered)
1. **Stop Loss** — Entry Price − 1.5 × ATR(14)
2. **Target Hit** — Entry Price + 2.5 × ATR(14)
3. **Trend Death** — Close falls below KAMA − 0.5 × ATR
4. **Max Hold** — 30 trading days (timeout)

### Portfolio Rules
- Maximum **10 concurrent positions**
- **10% capital allocation** per trade
- **5-day cooldown** after exiting a stock before re-entry

---

## What Makes This System Different

### 1. Market Regime Filter
Most retail strategies ignore the macro environment. This system **halts all buying when the market is bearish**, protecting capital during downturns. The regime is determined by a synthetic index of India's 5 largest companies vs. their 200-day SMA.

### 2. Three-Indicator Quant Trio
| Indicator | What It Measures | Why It Matters |
|-----------|-----------------|----------------|
| **VHF** | Trend strength (directional vs. random) | Filters out choppy, range-bound stocks |
| **KAMA** | Adaptive trend direction | Adjusts sensitivity to volatility — tight in trends, loose in noise |
| **Z-Score** | Momentum magnitude (standard deviations) | Ensures breakout is statistically significant, not random |

### 3. Volatility Contraction Detection
Using Bollinger Band Width relative to its 50-period median, the system identifies stocks that have been **consolidating** (low volatility) before a breakout. This is the quantitative equivalent of Minervini's VCP pattern.

---

## Robustness Validation

A **243-combination parameter sensitivity grid** was run across:
- VHF threshold: [0.25, 0.30, 0.35]
- Z-Score threshold: [0.8, 1.0, 1.2]
- ATR stop multiplier: [1.2, 1.5, 1.8]
- ATR target multiplier: [2.0, 2.5, 3.0]
- Max hold days: [30, 45, 60]

### Results:
| Metric | Value |
|--------|-------|
| **Profitable configurations** | **232 / 243 (95%)** |
| **Median CAGR across all configs** | +1.89% |
| **Best CAGR** | +3.54% |
| **Worst CAGR** | -1.93% |

> **95% of nearby parameter values remain profitable.** This confirms the strategy edge is real and not the result of curve-fitting or overfitting to a single parameter set.

### Key Findings:
- ATR Stop = 1.5 is the clear sweet spot (1.2 too tight, 1.8 too wide)
- ATR Target = 3.0 maximizes CAGR; 2.5 minimizes drawdown
- Max Hold beyond 45 days has negligible impact (most trades exit before day 45)
- VHF < 0.25 + Z < 0.8 is the "danger zone" — too loose, too many bad entries

---

## System Architecture

```
Alpha Quant V5/
├── backtest_v5.py         ← Backtest engine (research)
├── scanner_v5.py          ← Live signal scanner (daily)
├── portfolio_manager.py   ← Position tracking & exit management
├── update_daily.py        ← Daily data pipeline (Yahoo Finance → Parquet)
├── daily_run.py           ← One-command pipeline runner
├── run_dashboard.py       ← Local web server
├── sector_map.py          ← Ticker → sector mapping
├── index.html / app.js / style.css  ← Dashboard UI
├── nifty500_daily.parquet ← 499-stock historical database (24 MB)
├── positions.json         ← Open trade tracker
├── signals.json           ← Scanner output for dashboard
└── logs/                  ← Trade & scanner audit trail
```

### Data Pipeline
1. **[update_daily.py](file:///Users/knvsaditya/Documents/Alpha%20model/update_daily.py)** — Fetches latest daily OHLCV data for 499 stocks, validates candles (rejects >25% price jumps, zero volume, sub-₹1 closes), appends to Parquet database
2. **[portfolio_manager.py](file:///Users/knvsaditya/Documents/Alpha%20model/portfolio_manager.py)** — Checks all open positions against stop loss, target, and max hold; auto-closes expired trades
3. **[scanner_v5.py](file:///Users/knvsaditya/Documents/Alpha%20model/scanner_v5.py)** — Runs V5 logic on latest data; skips held tickers; caps signals to available portfolio slots
4. **Dashboard** — Auto-refreshes every 30 seconds; displays signals, regime status, and risk metrics

### Daily Workflow
```bash
python3 daily_run.py --now     # Runs all 3 scripts in sequence
python3 run_dashboard.py       # Serves dashboard at localhost:8000
```

---

## Technical Skills Demonstrated

| Skill | Application |
|-------|-------------|
| **Quantitative Finance** | VHF, KAMA, Z-Score, ATR-based risk management, market regime filtering |
| **Python (pandas, numpy)** | Vectorized indicator computation, Parquet I/O, portfolio simulation |
| **Backtesting** | Walk-forward simulation with slippage, position sizing, and portfolio constraints |
| **Statistical Validation** | 243-point parameter sensitivity grid to verify robustness |
| **Data Engineering** | ETL pipeline: API → validation → Parquet storage → signal generation |
| **Web Development** | Real-time dashboard with HTML/CSS/JS, auto-refresh polling |
| **System Design** | Modular architecture: separate data, engine, portfolio, and presentation layers |
| **Risk Management** | ATR-based stops/targets, 10-slot portfolio cap, market regime halt |

---

## Limitations & Future Work

1. **Data Source** — Currently uses Yahoo Finance (rate-limited, occasional bad data). Migration to Fyers API planned for institutional-grade accuracy.
2. **Paper Trading Phase** — System needs 2-3 months of real-time paper trading to validate live performance against backtest metrics.
3. **No Auto-Execution** — Currently generates signals only; manual order placement required. Broker API integration (Fyers/Zerodha) planned for Phase 2.
4. **Transaction Costs** — Backtest includes 10bps slippage but does not model brokerage, STT, or GST.

---

*Built with Python · pandas · numpy · Parquet · HTML/CSS/JS*
*499 stocks · 1.1M+ daily candles · 10+ years of history*
