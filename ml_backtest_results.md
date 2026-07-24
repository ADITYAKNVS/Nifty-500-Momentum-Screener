# ML Stock Picking vs Momentum V2 Performance Comparison

**Test Period:** 2021-01-01 to 2026-05-26 (Out-Of-Sample)
**Train Period:** 2015-01-01 to 2020-12-31 (For ML Models)

| Strategy Name | CAGR | Ann Vol | Sharpe | Sortino | Max DD | Trades/Yr | Hold Days |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Momentum V2 (Regime) | 47.88% | 24.80% | 1.55 | 1.84 | -24.89% | 20.2 | 54.5 |
| Ridge (Pure) | 66.68% | 32.32% | 1.67 | 2.54 | -36.20% | 57.5 | 30.8 |
| Ridge (Regime) | 51.39% | 24.39% | 1.69 | 2.10 | -22.18% | 38.9 | 28.3 |
| Random Forest (Pure) | 20.40% | 38.22% | 0.50 | 0.69 | -45.31% | 84.2 | 21.2 |
| Random Forest (Regime) | 18.24% | 28.20% | 0.49 | 0.51 | -27.65% | 57.3 | 19.3 |
| XGBoost (Pure) | 23.35% | 38.16% | 0.60 | 0.85 | -51.26% | 92.2 | 19.5 |
| XGBoost (Regime) | 15.71% | 28.67% | 0.45 | 0.48 | -32.63% | 58.8 | 18.8 |
| LightGBM (Pure) | 23.35% | 38.16% | 0.60 | 0.85 | -51.26% | 92.2 | 19.5 |
| LightGBM (Regime) | 15.71% | 28.67% | 0.45 | 0.48 | -32.63% | 58.8 | 18.8 |
| LSTM (Pure) | 27.93% | 33.48% | 0.74 | 1.04 | -36.84% | 115.5 | 15.6 |
| LSTM (Regime) | 32.13% | 25.64% | 1.01 | 1.06 | -21.91% | 70.3 | 15.7 |
