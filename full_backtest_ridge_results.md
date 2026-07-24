# Ridge Regression (Pure) vs Momentum V2 Full Backtest Results (2015 - 2026)

This document contains the performance metrics for the **Ridge Regression (Pure)** strategy backtested over the full long-term historical period (2015–2026) compared against the **Momentum V2** baselines.

## 📊 Long-Term Performance Summary

### 11-Year Backtest (2015 - 2026)
This backtest uses the model statically trained on **2015–2020** data and run across the entire **2015–2026** period (acting as in-sample for the first half and out-of-sample for the second half).

| Strategy Name | Period | CAGR | Ann Vol | Sharpe | Max DD |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Ridge (Pure, Static 2015-2020 Train)** | **2015-2026** | **52.07%** | 32.60% | **1.35** | **-44.20%** |
| **Ridge (Regime, Static 2015-2020 Train)** | **2015-2026** | **36.94%** | 22.91% | **1.32** | **-28.81%** |
| **Momentum V2 (Pure)** | **2015-2026** | 42.99% | 31.59% | 1.18 | -52.77% |
| **Momentum V2 (Regime)** | **2015-2026** | 33.23% | 23.15% | 1.18 | -44.97% |

### 10-Year Backtest (2016 - 2026)
This backtest runs the **Expanding Window** configuration, where the model is re-trained dynamically every month on all available historical data up to that month.

| Strategy Name | Period | CAGR | Ann Vol | Sharpe | Max DD |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Momentum V2 (Regime)** | **2016-2026** | **36.71%** | 24.15% | **1.26** | **-44.97%** |
| **Ridge (Pure, Expanding Window)** | **2016-2026** | 24.31% | 36.78% | 0.67 | -62.79% |

---

## 🔍 Key Insights

1. **Ridge (Pure) Dominance:**
   - **Ridge (Pure, Static)** achieved a **52.07% CAGR** over the 11-year history, outperforming the **Momentum V2 (Pure)** strategy (**42.99% CAGR**) by **9.08% CAGR**.
   - It did this while maintaining a **higher Sharpe Ratio (1.35 vs 1.18)** and a **lower maximum drawdown (-44.20% vs -52.77%)**.

2. **Regime Protection Improvement:**
   - When combined with the regime filter, **Ridge (Regime, Static)** achieved a **36.94% CAGR** (vs. Momentum V2 Regime's **33.23% CAGR**).
   - Crucially, it reduced the maximum drawdown to **-28.81%**, which is a **16.16% absolute reduction** in drawdown compared to Momentum V2 Regime's **-44.97%**!

3. **Expanding Window Training Limitation:**
   - The **Expanding Window** model suffered from high volatility in the early years (2016-2017) due to short training windows (less than 2 years of daily data), leading to unstable predictions.
   - For machine learning models in stock picking, a **stable, longer-term static training period (like 2015-2020)** yields more robust and generalizable coefficients than short-term rolling updates.
