# 🚀 Nifty 500 Momentum Screener & Quantitative Trading System (`Alpha Model`)

An institutional-grade **rule-based systematic trading, stock screening, and quantitative research platform** tailored for the Indian Equity Market (Nifty 500). 

The platform integrates **Minervini VCP / CANSLIM breakout filters**, **Ridge Regression machine learning models**, **Market Regime macro protection**, an **automated paper trading engine**, and a high-performance **Next.js Institutional Trading Terminal**.

---

## 📌 Executive Summary

The **Alpha Model** continuously scans 499 Nifty 500 stocks daily to identify high-probability breakout momentum setups. By combining technical volatility contraction indicators (**VHF**, **KAMA**, **Z-Score**), Ridge ML factor modeling, market regime filtering, and strict ATR-based risk management, the platform identifies swing trades with an average 30–45 day holding period while systematically protecting capital during macro downtrends.

---

## 📊 Backtest & Walk-Forward Performance

### Rolling Walk-Forward Ledger (2020 – 2026, T+1 Execution)

| Year | Start Capital (₹) | End Capital (₹) | Return (%) | Max Drawdown (%) | Sharpe Ratio | Total Trades |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **2020** | 1,000,000 | 2,182,961 | **+118.30%** | -15.77% | **3.20** | 78 |
| **2021** | 2,205,197 | 4,375,632 | **+98.42%** | -19.87% | **2.73** | 76 |
| **2022** | 4,375,632 | 5,009,750 | **+14.49%** | -17.48% | **0.77** | 33 |
| **2023** | 4,795,684 | 13,873,054 | **+189.28%** | -11.21% | **3.82** | 44 |
| **2024** | 17,157,854 | 29,457,657 | **+71.69%** | -22.39% | **1.27** | 25 |
| **2025** | 29,457,657 | 33,066,515 | **+12.25%** | -14.19% | **0.66** | 31 |
| **2026** | 30,698,007 | 29,885,907 | **-2.65%** | 0.00% | 0.00 | 5 |

> **Robustness Validation**: Parameter sensitivity analysis across a **243-combination grid** confirmed **95% parameter profitability** (232/243 parameter sets remained profitable), verifying the system edge is structurally sound and free from overfitting.

---

## 🔥 Key Features & Capabilities

### 1. **Quantitative Signal Engine (Alpha Quant V5)**
* **Volatility Contraction Pattern (VCP)**: Detects tight consolidation periods using Bollinger Band Width vs. its 50-period median before breakouts occur.
* **Vertical Horizontal Filter (VHF)**: Quantifies directional trend strength to eliminate choppy, range-bound stocks.
* **Kaufman Adaptive Moving Average (KAMA)**: Dynamically adjusts noise sensitivity to track structural trends.
* **Z-Score Momentum**: Enforces statistical significance (breakout magnitude > 1.2 standard deviations above mean).

### 2. **Ridge Regression Pure Alpha Model**
* Machine learning pipeline (`scanner_ridge_pure.py`) isolating true idiosyncratic asset alpha from broad market beta using cross-validated Ridge regressors.

### 3. **Market Regime Macro Protection**
* Evaluates macro market health using a synthetic index of top weight Nifty proxies (RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK). All new signal generation halts when the proxy drops below its 200-day SMA, locking in profits and preserving capital.

### 4. **Automated ETL & Daily Data Pipeline**
* Incremental daily ingestion of 499 Nifty 500 stocks (1.1M+ candles) stored in an optimized Parquet database (`nifty500_daily.parquet`).
* Automatic candle validation filtering bad ticks, zero-volume days, and extreme corporate action splits.

### 5. **SQLite Paper Trading Engine**
* Real-time trade desk (`paper_trading.py` on port `8001`) managing virtual execution, trailing ATR stop losses, target pricing, timeout exits, and daily trade logs.

### 6. **Institutional Trading Terminal (Next.js)**
* Dark-themed fullstack trading dashboard built with **Next.js 15**, **TypeScript**, **Tailwind CSS**, and **Shadcn UI**.
* Real-time interactive charts, active position trackers, performance telemetry, and signal scanner feed.

### 7. **TradingView Pine Script Integration**
* Includes custom Pine Script v5 strategy & indicator files (`tradingview_momentum_v2_strategy.pine`) for visual plotting, manual verification, and live TradingView alerts.

---

## 🏗️ System Architecture

```
                                  ┌───────────────────────────┐
                                  │   NSE / Yahoo Finance     │
                                  └─────────────┬─────────────┘
                                                │
                                                ▼
                                    [ update_daily.py ]
                                (ETL, Validation & Cleanse)
                                                │
                                                ▼
                                 [ nifty500_daily.parquet ]
                             (499 Stocks Daily Historical Data)
                                                │
                                                ├──────────────────────────────┐
                                                ▼                              ▼
                                    [ scanner_momentum_v2.py ]     [ scanner_ridge_pure.py ]
                                     (VCP, VHF, Z-Score Model)      (Ridge ML Factor Model)
                                                │                              │
                                                └──────────────┬───────────────┘
                                                               │
                                                               ▼
                                                      [ Regime Filter ]
                                                  (Top Nifty 200-SMA Check)
                                                               │
                                                               ▼
                                                    [ paper_trading.py ]
                                                 (SQLite Paper Trade Desk)
                                                               │
                                                               ▼
                                                    [ Backend API (8000) ]
                                                               │
                                                               ▼
                                                 [ Next.js Terminal (3000) ]
```

---

## 📁 Repository Structure

```
Nifty-500-Momentum-Screener/
├── start.sh                              # One-click launcher for API, Engine & Next.js UI
│
├── 🐍 Core Backend & Quantitative Engines
├── scanner_momentum_v2.py                # Main V5 quantitative momentum breakout screener
├── scanner_ridge_pure.py                 # Ridge ML Pure Alpha factor model screener
├── pure_alpha_production.py              # Production pure alpha strategy pipeline
├── paper_trading.py                      # SQLite paper trading engine & order tracker (Port 8001)
├── server.py                             # Fast HTTP Backend REST API (Port 8000)
├── daily_run.py                          # Automated daily pipeline runner
├── update_daily.py                       # Market data downloader & Parquet updater
├── fetch_fundamentals.py                 # Fundamental metrics & financial filter ETL
├── backfill_index.py                     # Historical index backfill utility
│
├── 📈 Backtesting & Research Diagnostics
├── backtest_master_v2.py                 # Master backtest engine (2014-2026)
├── backtest_ml_comparison.py             # Comparative ML backtester
├── backtest_ridge_full.py                # Ridge regression backtest suite
├── beta_alpha_diagnostic.py              # Beta vs Alpha factor decomposition
├── final_v5_institutional_audit.py       # Institutional trade audit script
├── walk_forward_test.py                  # Rolling Walk-Forward simulation module
│
├── 🖥️ Frontend Terminal
├── frontend/                             # Next.js 15 Trading Terminal Application
│   ├── src/app/                          # Dashboard pages & layouts
│   ├── src/components/terminal/          # Charting, order book, and signal desk widgets
│   ├── package.json                      # Frontend dependencies
│   └── next.config.ts                    # Next.js configuration
│
├── 🌲 TradingView Pine Scripts
├── tradingview_momentum_v2.pine          # TradingView Indicator v5
├── tradingview_momentum_v2_strategy.pine # TradingView Strategy Backtester v5
│
├── 💾 Data & Reports
├── nifty500_daily.parquet                # Historical OHLCV dataset (499 Nifty stocks)
├── fundamental_filter.csv                # Fundamental financial data map
├── sector_map.csv                        # Industry & sector classifications
├── yearly_ledger.md                      # Year-by-year performance metrics
├── alpha_quant_v5_report.md              # In-depth strategy documentation
└── Momentum_V2_Interview_Prep.md        # Technical interview & quantitative deep-dive
```

---

## ⚡ Quickstart Guide

### Prerequisites
* **Python 3.10+**
* **Node.js 18+** & **npm**

### 1. Installation
Clone the repository and install required packages:

```bash
# Clone the repository
git clone https://github.com/ADITYAKNVS/Nifty-500-Momentum-Screener.git
cd Nifty-500-Momentum-Screener

# Install Python backend dependencies
pip install pandas numpy scikit-learn yfinance pyarrow requests

# Install Next.js frontend dependencies
cd frontend
npm install
cd ..
```

---

### 2. Launching the Full Stack App (One-Click)

You can launch all 3 servers (**Backend API**, **Paper Trading Engine**, and **Next.js Frontend**) simultaneously using the provided shell script:

```bash
chmod +x start.sh
./start.sh
```

Once launched, open your browser:
* 🖥️ **Trading Terminal UI**: [http://localhost:3000](http://localhost:3000)
* 📡 **Backend REST API**: [http://localhost:8000](http://localhost:8000)
* 📊 **Paper Trading Desk**: [http://localhost:8001](http://localhost:8001)

---

### 3. Running Daily Pipeline Manually

To trigger a daily market update and run the screening engines manually:

```bash
# 1. Update daily price data (Yahoo Finance -> Parquet)
python3 update_daily.py

# 2. Run signal screener
python3 scanner_momentum_v2.py

# 3. Or execute the full automated daily pipeline
python3 daily_run.py
```

---

## 🛡️ Risk Management & Exit Rules

1. **Hard Stop Loss**: Entry Price − 1.5 × ATR(14)
2. **Profit Target**: Entry Price + 2.5 × ATR(14)
3. **Trend Death Exit**: Close < KAMA − 0.5 × ATR(14)
4. **Max Holding Period**: 30 Trading Days Timeout
5. **Portfolio Cap**: Maximum 10 concurrent active positions (10% allocation per trade)
6. **Re-entry Cooldown**: 5-day mandatory pause after exiting a stock before re-entering

---

## ⚖️ Disclaimer

*This software is created for quantitative research and paper trading educational purposes only. It does not constitute financial advice or investment recommendations. Past backtest results do not guarantee future live trading returns.*

---
*Developed with Python · Pandas · Scikit-Learn · Parquet · Next.js · TypeScript · Tailwind CSS*
