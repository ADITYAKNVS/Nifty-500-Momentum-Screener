import pandas as pd
import numpy as np
import warnings
import time
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge

# Suppress warnings
warnings.filterwarnings('ignore')

# ═══ ARCHITECTURE CONFIG ═══
PARQUET_PATH = "nifty500_daily.parquet"
TOP_N = 5
ROUND_TRIP_COST = 0.0035
INITIAL_CAPITAL = 10_000_000.0

def get_next_trading_day(current_date, all_dates):
    try:
        idx = all_dates.index(current_date)
        if idx + 1 < len(all_dates):
            return all_dates[idx + 1]
    except ValueError:
        pass
    return current_date

def fetch_regime_data(start_year, sma_length):
    df = pd.read_parquet(PARQUET_PATH)
    df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
    n50 = df.groupby('Date')['Close'].mean().to_frame().reset_index()
    n50.columns = ['Date', 'Close']

    n50['SMA'] = n50['Close'].rolling(sma_length).mean()
    n50['Is_Above'] = n50['Close'] > n50['SMA']

    current_state = False
    consec_above = 0
    consec_below = 0
    states = []
    bull_streaks = []

    for _, row in n50.iterrows():
        if pd.isna(row['SMA']):
            states.append(False)
            bull_streaks.append(0)
            continue
            
        if row['Is_Above']:
            consec_above += 1
            consec_below = 0
        else:
            consec_below += 1
            consec_above = 0
            
        if consec_above >= 3:
            current_state = True
        elif consec_below >= 3:
            current_state = False
            
        states.append(current_state)
        bull_streaks.append(consec_above if current_state else 0)

    n50['Bullish'] = states
    n50['Bull_Streak'] = bull_streaks
    return n50.set_index('Date')[['Bullish', 'Bull_Streak']]

def compute_metrics(eq_df):
    if eq_df.empty or len(eq_df) < 10:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    
    eq_df = eq_df.drop_duplicates('Date', keep='last').sort_values('Date')
    eq_df['Daily_Return'] = eq_df['Capital'].pct_change().fillna(0.0)
    
    # CAGR
    years = (eq_df['Date'].max() - eq_df['Date'].min()).days / 365.25
    cagr = ((eq_df['Capital'].iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1.0) if years > 0 else 0.0
    
    # Volatility
    ann_vol = eq_df['Daily_Return'].astype(float).std() * np.sqrt(252)
    
    # Sharpe
    rf_daily = 0.06 / 252
    excess = eq_df['Daily_Return'] - rf_daily
    sharpe = (excess.mean() / eq_df['Daily_Return'].astype(float).std()) * np.sqrt(252) if ann_vol > 0 else 0.0
    
    # Sortino
    down_std = eq_df[eq_df['Daily_Return'] < 0]['Daily_Return'].astype(float).std()
    sortino = (excess.mean() / down_std) * np.sqrt(252) if down_std > 0 else 0.0
    
    # Max DD
    eq_df['Peak'] = eq_df['Capital'].cummax()
    eq_df['Drawdown'] = (eq_df['Capital'] - eq_df['Peak']) / eq_df['Peak']
    max_dd = eq_df['Drawdown'].min()
    
    return cagr, ann_vol, sharpe, sortino, max_dd, years

def main():
    print("=" * 80)
    # Load and preprocess
    df_all = pd.read_parquet(PARQUET_PATH)
    df_all['Date'] = pd.to_datetime(df_all['Date']).dt.tz_localize(None)
    df_all = df_all.sort_values(['Ticker', 'Date']).reset_index(drop=True)
    
    official_tickers = set(pd.read_csv('ind_nifty500list.csv').Symbol.dropna().unique())
    official_tickers.add('ETERNAL')
    df_all = df_all[df_all.Ticker.isin(official_tickers)].copy()
    
    # Features
    df_all['Daily_Return'] = df_all.groupby('Ticker')['Close'].pct_change().replace([np.inf, -np.inf], 0.0).fillna(0.0)
    df_all['Ret_21'] = df_all.groupby('Ticker')['Close'].pct_change(21).replace([np.inf, -np.inf], np.nan)
    df_all['Ret_63'] = df_all.groupby('Ticker')['Close'].pct_change(63).replace([np.inf, -np.inf], np.nan)
    df_all['Ret_126'] = df_all.groupby('Ticker')['Close'].pct_change(126).replace([np.inf, -np.inf], np.nan)
    df_all['Ret_252'] = df_all.groupby('Ticker')['Close'].pct_change(252).replace([np.inf, -np.inf], np.nan)

    df_all['Vol_20'] = df_all.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(20).std() * np.sqrt(252))
    df_all['Vol_60'] = df_all.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(60).std() * np.sqrt(252))
    df_all['Vol_20'] = df_all['Vol_20'].replace(0, np.nan).fillna(0.20).replace([np.inf, -np.inf], 0.20)
    df_all['Vol_60'] = df_all['Vol_60'].replace(0, np.nan).fillna(0.20).replace([np.inf, -np.inf], 0.20)

    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover_20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    df_all['Turnover_Ratio'] = (df_all['Turnover'] / df_all['Avg_Turnover_20'].replace(0, np.nan).fillna(1e6)).replace([np.inf, -np.inf], np.nan)

    df_all['SMA50'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(50).mean())
    df_all['SMA200'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())

    df_all['Price_to_SMA50'] = (df_all['Close'] / df_all['SMA50'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    df_all['Price_to_SMA200'] = (df_all['Close'] / df_all['SMA200'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    df_all['RiskAdjMom'] = (df_all['Ret_252'] / df_all['Vol_60'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    
    features_cols = ['Ret_21', 'Ret_63', 'Ret_126', 'Ret_252', 'Vol_20', 'Vol_60', 'Turnover_Ratio', 'Price_to_SMA50', 'Price_to_SMA200', 'RiskAdjMom']
    
    # Matrices
    CLOSE_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Close')
    OPEN_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Open')
    ALL_DATES = sorted(list(CLOSE_MATRIX.index))
    
    dates_df = pd.DataFrame({'Date': CLOSE_MATRIX.index}).sort_values('Date').dropna()
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    rebalance_dates = list(dates_df.groupby('YearMonth')['Date'].max())
    
    # Target Labels
    targets = []
    for k in range(len(rebalance_dates) - 1):
        tk = rebalance_dates[k]
        tk_next = rebalance_dates[k+1]
        ek = get_next_trading_day(tk, ALL_DATES)
        ek_next = get_next_trading_day(tk_next, ALL_DATES)
        
        open_k = OPEN_MATRIX.loc[ek]
        open_knext = OPEN_MATRIX.loc[ek_next]
        ret = (open_knext / open_k.replace(0, np.nan)) - 1.0
        ret = ret.replace([np.inf, -np.inf], np.nan)
        
        ret_df = pd.DataFrame({
            'Date': tk,
            'Ticker': ret.index,
            'Target_Return': ret.values
        })
        targets.append(ret_df)
        
    targets_df = pd.concat(targets).dropna()
    
    # Merge targets
    df_rebal = df_all[df_all['Date'].isin(rebalance_dates[:-1])]
    df_ml = pd.merge(df_rebal, targets_df, on=['Date', 'Ticker'], how='inner')
    
    regime = fetch_regime_data(2015, 100)
    
    def simulate_with_model(name, backtest_start_date, train_on_data_func, use_regime=False):
        test_dates = [d for d in rebalance_dates if d >= pd.to_datetime(backtest_start_date) and d < ALL_DATES[-1]]
        
        capital = INITIAL_CAPITAL
        cash = INITIAL_CAPITAL
        positions = {}
        daily_equity_curve = []
        
        imputer = SimpleImputer(strategy='median')
        scaler = StandardScaler()
        
        for i in range(len(test_dates) - 1):
            tk = test_dates[i]
            tk_next = test_dates[i+1]
            ek = get_next_trading_day(tk, ALL_DATES)
            
            # Regime status
            reg_row = regime.loc[tk] if tk in regime.index else (regime.loc[:tk].iloc[-1] if not regime.loc[:tk].empty else pd.Series({'Bullish': False, 'Bull_Streak': 0}))
            is_bullish = reg_row['Bullish']
            bull_streak = reg_row['Bull_Streak']
            
            # Mark to market at Open
            invested_value = 0.0
            for t, pos in positions.items():
                p = OPEN_MATRIX.loc[ek, t] if t in OPEN_MATRIX.columns else pos['entry_price']
                if pd.isna(p) or p == 0: p = pos['entry_price']
                invested_value += pos['shares'] * p
            
            cash = capital - invested_value
            total_assets = cash + invested_value
            
            # Eligibility
            day_data = df_all[df_all['Date'] == tk].copy()
            day_data = day_data.dropna(subset=['SMA200', 'Avg_Turnover_20'])
            eligible_data = day_data[
                (day_data['Close'] > day_data['SMA200']) &
                (day_data['Avg_Turnover_20'] > 1e7) &
                (day_data['Close'] > 10)
            ]
            eligible_tickers = eligible_data['Ticker'].tolist()
            
            target_portfolio = []
            if use_regime and not is_bullish:
                target_portfolio = []
            else:
                if eligible_tickers:
                    if name == "Momentum V2":
                        eligible_data = eligible_data.sort_values('RiskAdjMom', ascending=False)
                        held_set = set(positions.keys())
                        buffer_eligible = eligible_data['Ticker'].head(15).tolist()
                        to_keep = [t for t in buffer_eligible if t in held_set]
                        to_add = [t for t in eligible_data['Ticker'].tolist() if t not in to_keep]
                        target_portfolio = to_keep + to_add[:max(0, TOP_N - len(to_keep))]
                    else:
                        # ML Model
                        model, imp_fitted, scl_fitted = train_on_data_func(tk, imputer, scaler)
                        if model is not None:
                            day_feats = eligible_data.set_index('Ticker').reindex(eligible_tickers)
                            X_raw = day_feats[features_cols]
                            X_raw = X_raw.replace([np.inf, -np.inf], np.nan)
                            
                            X_transformed = scl_fitted.transform(imp_fitted.transform(X_raw))
                            preds = model.predict(X_transformed)
                            pred_series = pd.Series(preds, index=eligible_tickers)
                            target_portfolio = pred_series.sort_values(ascending=False).head(TOP_N).index.tolist()
            
            target_weights = {t: 1.0/len(target_portfolio) for t in target_portfolio} if target_portfolio else {}
            
            # Leverage Sizing
            leverage = 1.10
            if use_regime:
                if not is_bullish:
                    leverage = 0.0
                elif bull_streak < 22:
                    leverage = 0.55
            
            sells = set(positions.keys()) - set(target_portfolio)
            buys = set(target_portfolio) - set(positions.keys())
            holds = set(target_portfolio).intersection(set(positions.keys()))
            
            # Sell
            for t in list(sells):
                p = OPEN_MATRIX.loc[ek, t] if t in OPEN_MATRIX.columns else positions[t]['entry_price']
                if pd.isna(p) or p == 0: p = positions[t]['entry_price']
                val = positions[t]['shares'] * p
                cost = val * (ROUND_TRIP_COST / 2)
                cash += (val - cost)
                total_assets -= cost
                del positions[t]
                
            # Rebalance
            for t in holds:
                p = OPEN_MATRIX.loc[ek, t] if t in OPEN_MATRIX.columns else positions[t]['entry_price']
                if pd.isna(p) or p == 0: p = positions[t]['entry_price']
                current_val = positions[t]['shares'] * p
                target_val = total_assets * target_weights[t] * leverage
                diff = target_val - current_val
                
                if diff > 0:
                    cost = diff * (ROUND_TRIP_COST / 2)
                    cash -= (diff + cost)
                    total_assets -= cost
                    positions[t]['shares'] += diff / p
                elif diff < 0:
                    amount_to_sell = abs(diff)
                    cost = amount_to_sell * (ROUND_TRIP_COST / 2)
                    cash += (amount_to_sell - cost)
                    total_assets -= cost
                    positions[t]['shares'] -= amount_to_sell / p
                    
            # Buy
            for t in buys:
                p = OPEN_MATRIX.loc[ek, t] if t in OPEN_MATRIX.columns else 0
                if pd.isna(p) or p == 0: continue
                target_val = total_assets * target_weights[t] * leverage
                cost = target_val * (ROUND_TRIP_COST / 2)
                cash -= (target_val + cost)
                total_assets -= cost
                positions[t] = {
                    'shares': target_val / p,
                    'entry_price': p,
                    'entry_date': ek
                }
                
            capital = total_assets
            
            # Daily mark to market
            start_idx = ALL_DATES.index(ek) + 1 if ek in ALL_DATES else 0
            end_idx = ALL_DATES.index(tk_next) + 1 if tk_next in ALL_DATES else 0
            for d_idx in range(start_idx, end_idx):
                d = ALL_DATES[d_idx]
                daily_port_val = 0.0
                for t, pos in positions.items():
                    p = CLOSE_MATRIX.loc[d, t] if t in CLOSE_MATRIX.columns else pos['entry_price']
                    if pd.isna(p) or p == 0: p = pos['entry_price']
                    daily_port_val += pos['shares'] * p
                capital = cash + daily_port_val
                daily_equity_curve.append({'Date': d, 'Capital': capital})
                
        return pd.DataFrame(daily_equity_curve)

    # --- Setup Ridge Models ---
    # Static 2015-2020 Train
    train_static_data = df_ml[df_ml['Date'] <= '2020-12-31']
    X_static_raw = train_static_data[features_cols].replace([np.inf, -np.inf], np.nan)
    y_static = train_static_data['Target_Return']
    imp_static = SimpleImputer(strategy='median')
    scl_static = StandardScaler()
    X_static_t = scl_static.fit_transform(imp_static.fit_transform(X_static_raw))
    ridge_static = Ridge(alpha=1.0)
    ridge_static.fit(X_static_t, y_static)
    
    def get_static_model(current_date, imputer, scaler):
        return ridge_static, imp_static, scl_static

    # Expanding Window Model Training
    def get_expanding_model(current_date, imputer, scaler):
        train_data = df_ml[df_ml['Date'] < current_date]
        if len(train_data) < 100:
            return None, None, None
        X_raw = train_data[features_cols].replace([np.inf, -np.inf], np.nan)
        y = train_data['Target_Return']
        imp = SimpleImputer(strategy='median')
        scl = StandardScaler()
        X_t = scl.fit_transform(imp.fit_transform(X_raw))
        model = Ridge(alpha=1.0)
        model.fit(X_t, y)
        return model, imp, scl

    first_rebal_date = rebalance_dates[0]
    start_dynamic = pd.to_datetime('2016-01-01')

    # Run Ridge simulations
    print("📊 Simulating Ridge (Pure, Static 2015-2020 Train, 2015-2026)...")
    eq_ridge_static = simulate_with_model("Ridge", first_rebal_date, get_static_model, use_regime=False)
    
    print("📊 Simulating Ridge (Pure, Expanding Window, 2016-2026)...")
    eq_ridge_exp = simulate_with_model("Ridge", start_dynamic, get_expanding_model, use_regime=False)
    
    print("📊 Simulating Ridge (Regime, Static 2015-2020 Train, 2015-2026)...")
    eq_ridge_reg_static = simulate_with_model("Ridge", first_rebal_date, get_static_model, use_regime=True)

    # Run Momentum V2 simulations for baseline comparison
    print("📊 Simulating Momentum V2 (Regime, 2015-2026)...")
    eq_mom_reg_full = simulate_with_model("Momentum V2", first_rebal_date, None, use_regime=True)
    
    print("📊 Simulating Momentum V2 (Pure, 2015-2026)...")
    eq_mom_pure_full = simulate_with_model("Momentum V2", first_rebal_date, None, use_regime=False)

    print("📊 Simulating Momentum V2 (Regime, 2016-2026)...")
    eq_mom_reg_2016 = simulate_with_model("Momentum V2", start_dynamic, None, use_regime=True)

    # Calculate metrics
    metrics = []
    
    # 2015-2026 comparisons
    for eq, name in [
        (eq_ridge_static, "Ridge (Pure, Static 2015-2020 Train)"),
        (eq_ridge_reg_static, "Ridge (Regime, Static 2015-2020 Train)"),
        (eq_mom_pure_full, "Momentum V2 (Pure)"),
        (eq_mom_reg_full, "Momentum V2 (Regime)")
    ]:
        cagr, vol, sh, so, dd, yr = compute_metrics(eq)
        metrics.append({'Strategy': name, 'Period': '2015-2026', 'CAGR': cagr, 'Vol': vol, 'Sharpe': sh, 'MaxDD': dd})
        
    # 2016-2026 comparisons
    for eq, name in [
        (eq_ridge_exp, "Ridge (Pure, Expanding Window)"),
        (eq_mom_reg_2016, "Momentum V2 (Regime)")
    ]:
        cagr, vol, sh, so, dd, yr = compute_metrics(eq)
        metrics.append({'Strategy': name, 'Period': '2016-2026', 'CAGR': cagr, 'Vol': vol, 'Sharpe': sh, 'MaxDD': dd})

    res_df = pd.DataFrame(metrics)
    
    print("\n" + "=" * 90)
    print("📈 FULL LONG-TERM BACKTEST PERFORMANCE SUMMARY (2015 - 2026)")
    print("=" * 90)
    print(f"{'Strategy Name':<42} | {'Period':<10} | {'CAGR':>8} | {'Ann Vol':>8} | {'Sharpe':>6} | {'Max DD':>8}")
    print("-" * 90)
    for idx, row in res_df.iterrows():
        print(f"{row['Strategy']:<42} | {row['Period']:<10} | {row['CAGR']:>8.2%} | {row['Vol']:>8.2%} | {row['Sharpe']:>6.2f} | {row['MaxDD']:>8.2%}")
    print("=" * 90)

if __name__ == "__main__":
    main()
