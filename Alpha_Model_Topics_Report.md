# Alpha Quant Model
**Complete Topics, Concepts & Technical Documentation**

*Report Generated: March 26, 2026 | Universe: NIFTY 500 | Data: 2014–2026*

---

## 📋 Table of Contents
1. **Strategy Overview** — Institutional momentum strategies and performance drivers
2. **Technical Indicators** — Momentum Scoring, ATR, SMA, Realized Volatility
3. **Market Regime Filters** — SMA-200, SMA-100, Absolute Momentum
4. **Signal Generation & Entry Logic** — Ranking-based selection, hold rank buffers
5. **Risk Management & Exit Logic** — Trailing stops, rebalance frequency, cooldowns
6. **Position Sizing & Portfolio Management** — Concentrated allocation, leverage, sector capping
7. **Cost & Slippage Modeling** — Transaction costs, liquidity realism, ADV participation
8. **Backtesting Framework** — Walk-forward analysis, T+1 execution, rollover logic
9. **Robustness Testing** — Monte Carlo (3 methods), liquidity realism, sensitivity analysis
10. **Live Execution Pipeline** — Daily scanner, portfolio manager, dashboard

---

## 1. Strategy Overview
*The Alpha Model contains two core institutional strategies, each targeting a different market edge.*

### Monthly Momentum V1 — Top 20 Rotation
**MONTHLY REBALANCE • NIFTY 500**
A classic cross-sectional momentum strategy that ranks all NIFTY 500 stocks by their 6-month (126-day) return, selects the Top 20, and equally-weights them. Rebalances at the end of each month. Goes 100% cash when the market regime turns bearish.

| Parameter | Value | Purpose |
| :--- | :--- | :--- |
| Momentum Window | 126 days (~6 months) | Lookback for return ranking |
| Top N Stocks | 20 | Portfolio concentration |
| Weighting | Equal (5% each) | Diversification across winners |
| Regime Filter | SMA 200 | Nifty 50 > 200-day SMA |
| Hold Period | ~30 days (EOM rebalance) | Monthly rotation |
| Trend Filter | Stock > its SMA 200 | Only buy stocks in uptrend |

### Momentum Alpha Pro — Concentrated Strategy
**EXTREME CONCENTRATION • 1.1× LEVERAGE**
**Allocation per Stock**: 22% (1.1x / 5). **Regime SMA**: 100. **Hold Rank Buffer**: 15.

---

## 2. Technical Indicators Used
*Institutional indicators and momentum factors powering signal generation.*

**2.1 — Average True Range (ATR)**
Measures daily volatility. Used to set adaptive stop losses and profit targets.
* **Formula:** ATR = 14-day Simple Moving Average of True Range (max of High-Low, High-PrevClose, Low-PrevClose). Used for trailing stops and risk adjustment.

**2.2 — Simple Moving Average (SMA 200 & SMA 50)**
Classic trend filters. SMA-200 determines long-term trend direction for individual stocks. SMA-50 is used for market breadth calculations.

**2.3 — 6-Month Momentum Return (V1)**
Simple percentage return over 126 trading days. Stocks are ranked by this return to identify the strongest performers for the momentum portfolio.

**2.4 — 12M-minus-1M Momentum (Alpha Pro)**
Uses close price from 21 days ago divided by close from 252 days ago. Skipping the most recent month avoids the well-documented short-term mean reversion effect.

**2.5 — Realized Volatility (20-Day Annualized)**
Used in Alpha Pro for risk-adjusted momentum scoring and inverse-volatility weighting.

---

## 3. Market Regime Filters
*Top-down filters that prevent trading during bear markets — the single biggest alpha driver.*

**3.1 — SMA-200 Regime Filter (Momentum V1)**
When the Nifty 50 index trades below its 200-day SMA, the market is declared bearish and **ALL trading is halted**. 100% cash. This simple rule has historically avoided major drawdowns (2020 COVID crash, 2022 bear market).

**3.2 — SMA-100 Fast Regime Filter (Alpha Pro)**
Uses a faster 100-day SMA for quicker regime switching. Gets into cash faster during crashes but also re-enters faster during recoveries. Backtested to provide better risk-adjusted returns.

**3.3 — Absolute Momentum Filter**
Requires the Nifty 50's own 126-day return to be positive. Combines with SMA filter for double confirmation during Alpha Pro backtesting.

**3.5 — Market Proxy Construction (Backtest)**
In backtesting (where Nifty index data may be unavailable for the full history), a synthetic market proxy is constructed by averaging the closing prices of the top 5 large-cap stocks: **RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK**. The SMA-200 regime is computed on this proxy.

---

## 4. Signal Generation & Entry Logic

### Momentum V1 & Alpha Pro — Ranking-Based Selection
*No complex signal — simply rank, filter, and select:*
1. Filter universe by: Close > SMA(200), Avg Turnover > min threshold, Close > ₹10
2. Compute momentum score (6M return for V1; 12M−1M for Alpha Pro)
3. Rank all eligible stocks by momentum score descending
4. Select Top N (20 for V1, 5 for Alpha Pro)
5. Alpha Pro only: Apply "Hold Rank Buffer" — keep existing holdings if still within top 15 rank

---

**5.1 — ATR-Based Trailing Stop (Alpha Pro):** An optional 15% trailing stop from the peak price, tested during diagnostics. 
**5.2 — Rebalance Cooldown:** After exiting a stock, a 5-day cooldown prevents re-entry into the same stock.

---

**6.1 — Equal Weighting:** V1: 5% per stock (20 stocks). Alpha Pro: 22% per stock (5 stocks × 1.1× leverage).
**6.2 — Inverse Volatility Weighting:** Tested in Alpha Pro diagnostics. Allocates more capital to lower-volatility stocks.
**6.3 — Sector Capping:** Limits each sector to maximum 4 stocks in the portfolio to prevent concentration risk.

---

## 7. Transaction Cost & Slippage Modeling

**7.1 — Transaction Cost:** Fixed 35 basis points per round trip, including taxes and brokerage.
**7.2 — Slippage (Liquidity Realism):** Variable model that scales cost (0.5% - 1.5%) based on ADV participation.
**7.3 — Variable Slippage by ADV Participation (Liquidity Realism):** An advanced slippage model that scales cost based on how much of a stock's Average Daily Volume (ADV) the trade consumes.
* ≤ 2% of ADV = 0.50% slippage
* 2% – 5% of ADV = 0.75% slippage
* 5% – 10% of ADV = 1.00% slippage
* > 10% of ADV = 1.50% slippage

---

## 8. Backtesting Framework
**8.1 — Walk-Forward Analysis:** Train on historical data up to Year Y−1, test on Year Y, then roll forward. 
**8.2 — T+1 Open Execution Simulation:** Realistic execution model using next-day open prices.
**8.4 — Performance Metrics Computed:** CAGR, Sharpe Ratio, Sortino Ratio, Max Drawdown, Win Rate, Profit Factor, Annualized Volatility.

---

## 9. Robustness & Stress Testing
*Five independent robustness tests validate that the strategy isn't a statistical artifact.*

**9.1 — Monte Carlo Simulations (3 Tests):**
1.  **Return Noise Injection (200 sims):** Adds random N(0, 0.5%) noise to each daily return. Simulates execution slippage and bid-ask spread variation.
2.  **Trade Shuffle (200 sims):** Keeps the same set of daily returns but randomly shuffles their order. Tests whether performance depends on "lucky sequencing" of trades.
3.  **Crash Injection (100 sims):** Injects a synthetic 5-day, −10%/day crash at a random point in the equity curve. Tests survivability during extreme tail events.

**9.2 — Liquidity Realism Test:** Tests strategy performance under increasingly strict liquidity filters (₹1Cr → ₹10Cr minimum daily turnover). Uses T+1 Open execution and variable slippage based on ADV participation rate.
**9.3 — 2D Sensitivity Analysis:** Grid search over key parameter pairs (e.g., VHF vs Z-Score) to verify the strategy isn't sitting on a narrow parameter peak.
**9.4 — Isolated Year-by-Year Analysis:** Runs the backtest independently for each calendar year to identify whether returns are driven by one or two outlier years or are broadly distributed.
**9.5 — Alpha Pro Diagnostic Testing (A/B Variants):** Systematically tests individual improvements over the V1 baseline (SMA100, Sector cap, Alpha Pro Top 5, 1.1x Leverage).

---

## 10. Live Execution Pipeline

**10.1 — Daily Automated Pipeline:** The `daily_run.py` script orchestrates the full daily workflow: Fetch prices → Portfolio Manager → Alpha Pro / V1 Scanners → Save Signals.
**10.2 — Frontend Dashboard:** HTML/CSS/JS dashboard displaying signals, sector distribution, alpha scores, and market regime status from JSON signal files.
**10.3 — Sector Mapping:** Comprehensive mapping of 100+ Nifty 500 tickers to 15+ sectors for sector-level analysis and capping.
**10.4 — Data Infrastructure:** All price data stored in a single Parquet file (`nifty500_daily.parquet`) containing OHLCV data for ~500 stocks from 2014 to present (~19MB compressed).

---

## 11. Technology Stack & Coding Methodologies
*The underlying software engineering and mathematical tools powering the quant model.*

**11.1 — Python & Vectorized Operations:** High-performance backtesting engine using Pandas and NumPy for vectorized computation across 1.5M+ data points.
**11.3 — Parquet Columnar Storage:** Historical data is stored in **Apache Parquet** format via PyArrow. Parquet provides massive compression (~19MB) and lightning-fast read speeds compared to standard CSVs, crucial for rapid backtesting iterations.
**11.4 — Statistical Standardization (Z-Scores):** The model normalizes variables by computing rolling 252-day means and standard deviations, then calculating the Z-Score to find statistically significant anomalies (Z > 1.0).
**11.5 — Monte Carlo Simulation Algorithms:** Uses programmatic simulated randomness (`numpy.random`). Applies Gaussian (Normal) distributions to inject noise into returns, and uses pseudo-random shuffling to isolate the strategy's edge from pure luck.

---

### Summary of All 45+ Topics Used

1. Simple Moving Averages (SMA 50/100/200) — Trend Filter
2. 6-Month Momentum (126-day return) — Momentum Factor
3. 12M−1M Momentum (Jegadeesh-Titman) — Momentum Factor
4. Realized Volatility (Annualized) — Risk Metric
5. Market Regime (SMA 200/100) — Macro Filter
6. Absolute Momentum Filter — Macro Filter
7. Trailing Stop (15% from Peak) — Risk Management
8. Equal Weight Portfolio — Portfolio Construction
9. Inverse Volatility Weighting — Portfolio Construction
10. Sector Capping — Portfolio Construction
11. Hold Rank Buffer — Turnover Reduction
12. Leverage (1.1×) — Return Amplification
13. Liquidity Filtering (ADT threshold) — Risk Control
14. Transaction Cost Modeling (35 bps) — Realistic Backtesting
15. Slippage Modeling (Fixed & Variable) — Realistic Backtesting
16. T+1 Open Execution — Realistic Backtesting
17. Monte Carlo: Noise Injection — Robustness Testing
18. Monte Carlo: Trade Shuffle — Robustness Testing
19. Monte Carlo: Crash Injection — Robustness Testing
20. Liquidity Realism Testing — Robustness Testing
21. Walk-Forward Analysis — Validation
22. CAGR / Sharpe / Sortino / Max DD / Win Rate — Performance Metrics
23. Equity Curve & Drawdown Analysis — Performance Metrics
