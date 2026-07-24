import pandas as pd
import numpy as np
import warnings
import time
import os
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor

# Suppress warnings
warnings.filterwarnings('ignore')

# ═══ DEPENDENCY CHECK & FALLBACKS ═══
XGB_AVAILABLE = False
LGB_AVAILABLE = False

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
    print("✅ XGBoost is available.")
except ImportError:
    from sklearn.ensemble import HistGradientBoostingRegressor
    print("⚠️ XGBoost is not available. Will use HistGradientBoostingRegressor as fallback.")

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
    print("✅ LightGBM is available.")
except ImportError:
    from sklearn.ensemble import HistGradientBoostingRegressor
    print("⚠️ LightGBM is not available. Will use HistGradientBoostingRegressor as fallback.")

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader

# ═══ ARCHITECTURE CONFIG ═══
PARQUET_PATH = "nifty500_daily.parquet"
TOP_N = 5
ROUND_TRIP_COST = 0.0035
INITIAL_CAPITAL = 10_000_000.0
TRAIN_END_DATE = '2020-12-31'
TEST_START_DATE = '2021-01-01'

# LSTM PyTorch Model
class PyTorchLSTM(nn.Module):
    def __init__(self, input_dim=1, hidden_dim=32, num_layers=1):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_dim, 1)
        
    def forward(self, x):
        out, (hn, cn) = self.lstm(x)
        # out: (batch, seq_len, hidden_dim)
        # We take the final time step output
        return self.fc(out[:, -1, :]).squeeze(-1)

# ═══ UTILITIES ═══
def get_next_trading_day(current_date, all_dates):
    try:
        idx = all_dates.index(current_date)
        if idx + 1 < len(all_dates):
            return all_dates[idx + 1]
    except ValueError:
        pass
    return current_date

def fetch_regime_data(start_year, sma_length):
    import yfinance as yf
    print("🌐 Fetching Nifty 50 Index for regime calculation...")
    try:
        n50 = yf.download('^NSEI', start=f'{start_year-1}-01-01', progress=False)
        if isinstance(n50.columns, pd.MultiIndex):
            n50.columns = n50.columns.get_level_values(0)
        n50.reset_index(inplace=True)
        n50['Date'] = pd.to_datetime(n50['Date']).dt.tz_localize(None)
        if n50.empty:
            raise ValueError("Empty response")
    except Exception as e:
        print(f"⚠️ yfinance download failed: {e}. Falling back to synthetic Nifty 500 index from parquet...")
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

# ═══ MAIN PIPELINE ═══
def main():
    print("=" * 80)
    print("📈 ML STOCK PICKING VS MOMENTUM V2 COMPARISON ENGINE")
    print("=" * 80)

    # 1. LOAD DATA
    print("📁 Loading master parquet data...")
    df_all = pd.read_parquet(PARQUET_PATH)
    df_all['Date'] = pd.to_datetime(df_all['Date']).dt.tz_localize(None)
    df_all = df_all.sort_values(['Ticker', 'Date']).reset_index(drop=True)
    
    # Universe Filter
    official_tickers = set(pd.read_csv('ind_nifty500list.csv').Symbol.dropna().unique())
    official_tickers.add('ETERNAL')
    df_all = df_all[df_all.Ticker.isin(official_tickers)].copy()
    
    print(f"   Data Shape: {df_all.shape} | Unique Tickers: {df_all['Ticker'].nunique()}")
    print(f"   Data Range: {df_all['Date'].min().date()} to {df_all['Date'].max().date()}")

    # 2. FEATURE ENGINEERING
    print("⏳ Engineering features...")
    t_start = time.time()
    
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
    df_all['Turnover_Ratio'] = df_all['Turnover'] / df_all['Avg_Turnover_20'].replace(0, np.nan).fillna(1e6)
    df_all['Turnover_Ratio'] = df_all['Turnover_Ratio'].replace([np.inf, -np.inf], np.nan)

    df_all['SMA50'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(50).mean())
    df_all['SMA200'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())

    df_all['Price_to_SMA50'] = (df_all['Close'] / df_all['SMA50'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    df_all['Price_to_SMA200'] = (df_all['Close'] / df_all['SMA200'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    df_all['RiskAdjMom'] = (df_all['Ret_252'] / df_all['Vol_60'].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    
    features_cols = ['Ret_21', 'Ret_63', 'Ret_126', 'Ret_252', 'Vol_20', 'Vol_60', 'Turnover_Ratio', 'Price_to_SMA50', 'Price_to_SMA200', 'RiskAdjMom']
    
    print(f"   Features engineered in {time.time() - t_start:.2f} seconds.")

    # 3. PIVOT MATRICES FOR BACKTESTING
    print("⚡ Building pivot matrices for daily portfolio tracking...")
    CLOSE_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Close')
    OPEN_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Open')
    LOW_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Low')
    HIGH_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='High')
    RETURN_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Daily_Return').fillna(0.0)
    ALL_DATES = sorted(list(CLOSE_MATRIX.index))
    
    # 4. REBALANCING DATES
    dates_df = pd.DataFrame({'Date': CLOSE_MATRIX.index}).sort_values('Date').dropna()
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    rebalance_dates = list(dates_df.groupby('YearMonth')['Date'].max())
    
    # 5. TARGET LABELS GENERATION
    print("🎯 Building target return labels...")
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
    
    # Merge targets back into daily dataset filtered to rebalance dates
    df_rebal = df_all[df_all['Date'].isin(rebalance_dates[:-1])]
    df_ml = pd.merge(df_rebal, targets_df, on=['Date', 'Ticker'], how='inner')
    
    # 6. SPLIT DATA FOR TABULAR MODELS
    train_mask = df_ml['Date'] <= TRAIN_END_DATE
    test_mask = df_ml['Date'] >= TEST_START_DATE
    
    print(f"   Train samples (2015-2020): {train_mask.sum()}")
    print(f"   Test samples (2021-2026): {test_mask.sum()}")
    
    imputer = SimpleImputer(strategy='median')
    scaler = StandardScaler()
    
    X_train_raw = df_ml[train_mask][features_cols]
    y_train = df_ml[train_mask]['Target_Return']
    X_test_raw = df_ml[test_mask][features_cols]
    y_test = df_ml[test_mask]['Target_Return']
    
    X_train = imputer.fit_transform(X_train_raw)
    X_train = scaler.fit_transform(X_train)
    X_test = imputer.transform(X_test_raw)
    X_test = scaler.transform(X_test)
    
    # 7. GENERATE SEQUENCES FOR LSTM MODEL
    print("🌀 Vectorizing daily return sequences for PyTorch LSTM...")
    lstm_features = []
    lstm_targets = []
    lstm_dates = []
    lstm_tickers = []
    
    for k in range(len(rebalance_dates) - 1):
        tk = rebalance_dates[k]
        idx = ALL_DATES.index(tk)
        if idx < 21:
            continue
            
        slice_df = RETURN_MATRIX.iloc[idx-20 : idx+1]  # shape (21, N_tickers)
        target_row = targets_df[targets_df['Date'] == tk].set_index('Ticker')['Target_Return']
        common_tickers = list(set(slice_df.columns).intersection(target_row.dropna().index))
        
        seqs = slice_df[common_tickers].values.T  # shape (N_common, 21)
        targs = target_row.loc[common_tickers].values
        
        lstm_features.append(seqs)
        lstm_targets.append(targs)
        lstm_dates.extend([tk] * len(common_tickers))
        lstm_tickers.extend(common_tickers)
        
    X_lstm = np.vstack(lstm_features)
    y_lstm = np.concatenate(lstm_targets)
    X_lstm = np.expand_dims(X_lstm, axis=-1)  # shape (N, 21, 1)
    
    lstm_dates_series = pd.to_datetime(lstm_dates)
    lstm_train_mask = lstm_dates_series <= TRAIN_END_DATE
    lstm_test_mask = lstm_dates_series >= TEST_START_DATE
    
    X_lstm_train = np.nan_to_num(X_lstm[lstm_train_mask], nan=0.0)
    y_lstm_train = y_lstm[lstm_train_mask]
    
    print(f"   LSTM Train samples: {X_lstm_train.shape[0]} | Shape: {X_lstm_train.shape}")

    # 8. TRAIN MODELS
    print("🤖 Training models on 2015-2020 Train set...")
    
    # Ridge
    ridge = Ridge(alpha=1.0)
    ridge.fit(X_train, y_train)
    print("   Ridge Baseline trained.")
    
    # Random Forest
    rf = RandomForestRegressor(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)
    print("   Random Forest Regressor trained.")
    
    # XGBoost
    if XGB_AVAILABLE:
        xgb_model = xgb.XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42, n_jobs=-1)
    else:
        xgb_model = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, random_state=42)
    xgb_model.fit(X_train, y_train)
    print("   XGBoost Regressor trained.")
    
    # LightGBM
    if LGB_AVAILABLE:
        lgb_model = lgb.LGBMRegressor(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42, n_jobs=-1, verbose=-1)
    else:
        lgb_model = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, random_state=42)
    lgb_model.fit(X_train, y_train)
    print("   LightGBM Regressor trained.")
    
    # PyTorch LSTM
    device = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    print(f"   PyTorch Device: {device}")
    
    X_tr_t = torch.tensor(X_lstm_train, dtype=torch.float32)
    y_tr_t = torch.tensor(y_lstm_train, dtype=torch.float32)
    
    train_dataset = TensorDataset(X_tr_t, y_tr_t)
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
    
    lstm = PyTorchLSTM(input_dim=1, hidden_dim=32, num_layers=1).to(device)
    optimizer = optim.Adam(lstm.parameters(), lr=0.005)
    criterion = nn.MSELoss()
    
    lstm.train()
    epochs = 8
    for epoch in range(epochs):
        epoch_loss = 0.0
        for batch_X, batch_y in train_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            pred = lstm(batch_X)
            loss = criterion(pred, batch_y)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item() * len(batch_y)
        print(f"      LSTM Epoch {epoch+1}/{epochs} - Loss: {epoch_loss/len(X_lstm_train):.6f}")
    
    # 9. BACKTEST ENGINE
    regime = fetch_regime_data(2015, 100)
    
    def simulate_backtest(name, model, use_regime=True):
        print(f"🚀 Simulating {name} ({'Regime-Controlled' if use_regime else 'Pure ML'}) ...")
        
        # Test period dates
        test_dates = [d for d in rebalance_dates if d >= pd.to_datetime(TEST_START_DATE) and d < ALL_DATES[-1]]
        
        capital = INITIAL_CAPITAL
        cash = INITIAL_CAPITAL
        positions = {}  # {Ticker: {'shares': float, 'entry_price': float, 'entry_date': Date}}
        daily_equity_curve = []
        total_trades = 0
        total_hold_days = 0
        
        # Churn buffer for Momentum V2 baseline
        held_tickers = []
        
        for i in range(len(test_dates) - 1):
            tk = test_dates[i]
            tk_next = test_dates[i+1]
            ek = get_next_trading_day(tk, ALL_DATES)
            
            # Regime Status
            reg_row = regime.loc[tk] if tk in regime.index else (regime.loc[:tk].iloc[-1] if not regime.loc[:tk].empty else pd.Series({'Bullish': False, 'Bull_Streak': 0}))
            is_bullish = reg_row['Bullish']
            bull_streak = reg_row['Bull_Streak']
            
            # Mark to Market at execution day Open to establish cash value
            invested_value = 0.0
            for t, pos in positions.items():
                p = OPEN_MATRIX.loc[ek, t] if t in OPEN_MATRIX.columns else pos['entry_price']
                if pd.isna(p) or p == 0: p = pos['entry_price']
                invested_value += pos['shares'] * p
            
            cash = capital - invested_value
            total_assets = cash + invested_value
            
            # 1. Eligibility Selection
            day_data = df_all[df_all['Date'] == tk].copy()
            day_data = day_data.dropna(subset=['SMA200', 'Avg_Turnover_20'])
            
            # Apply base filters (same as Run I)
            eligible_data = day_data[
                (day_data['Close'] > day_data['SMA200']) &
                (day_data['Avg_Turnover_20'] > 1e7) &
                (day_data['Close'] > 10)
            ]
            eligible_tickers = eligible_data['Ticker'].tolist()
            
            # 2. Strategy Signal Generations
            target_portfolio = []
            
            # Regime Control: if bear market and use_regime, stay in cash (no buys/holds)
            if use_regime and not is_bullish:
                target_portfolio = []
            else:
                if eligible_tickers:
                    if name == "Momentum V2":
                        # Baseline Momentum V2 logic (MOM score sorting & churn buffer of 15)
                        eligible_data = eligible_data.sort_values('RiskAdjMom', ascending=False)
                        
                        held_set = set(positions.keys())
                        buffer_eligible = eligible_data['Ticker'].head(15).tolist()
                        to_keep = [t for t in buffer_eligible if t in held_set]
                        to_add = [t for t in eligible_data['Ticker'].tolist() if t not in to_keep]
                        target_portfolio = to_keep + to_add[:max(0, TOP_N - len(to_keep))]
                    else:
                        # ML Model logic
                        if name == "LSTM":
                            # Sequence predict
                            idx = ALL_DATES.index(tk)
                            slice_df = RETURN_MATRIX.iloc[idx-20 : idx+1][eligible_tickers].fillna(0.0)
                            seqs = slice_df.values.T
                            seqs = np.expand_dims(seqs, axis=-1)
                            
                            model.eval()
                            with torch.no_grad():
                                tensor_X = torch.tensor(seqs, dtype=torch.float32).to(device)
                                preds = model(tensor_X).cpu().numpy()
                            pred_series = pd.Series(preds, index=eligible_tickers)
                        else:
                            # Tabular models
                            day_feats = eligible_data.set_index('Ticker').reindex(eligible_tickers)
                            X_raw = day_feats[features_cols]
                            X_scaled = scaler.transform(imputer.transform(X_raw))
                            preds = model.predict(X_scaled)
                            pred_series = pd.Series(preds, index=eligible_tickers)
                        
                        # Rank by highest predicted return
                        target_portfolio = pred_series.sort_values(ascending=False).head(TOP_N).index.tolist()
            
            # 3. Position Sizing Weights
            target_weights = {}
            if target_portfolio:
                for t in target_portfolio:
                    target_weights[t] = 1.0 / len(target_portfolio)
            
            # Leverage Scaling Factor
            leverage = 1.10
            if use_regime:
                if not is_bullish:
                    leverage = 0.0
                elif bull_streak < 22:
                    leverage = 0.55  # 0.5x leverage
            
            sells = set(positions.keys()) - set(target_portfolio)
            buys = set(target_portfolio) - set(positions.keys())
            holds = set(target_portfolio).intersection(set(positions.keys()))
            
            # Sell Exits at Open
            for t in list(sells):
                p = OPEN_MATRIX.loc[ek, t] if t in OPEN_MATRIX.columns else positions[t]['entry_price']
                if pd.isna(p) or p == 0: p = positions[t]['entry_price']
                
                val = positions[t]['shares'] * p
                cost = val * (ROUND_TRIP_COST / 2)
                
                total_hold_days += (ek - positions[t]['entry_date']).days
                cash += (val - cost)
                total_assets -= cost
                del positions[t]
                total_trades += 1
                
            # Rebalance Holds at Open
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
            
            # New Buys at Open
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
                total_trades += 1
                
            capital = total_assets
            
            # Intra-period daily tracking
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
        
        eq_df = pd.DataFrame(daily_equity_curve)
        cagr, ann_vol, sharpe, sortino, max_dd, years = compute_metrics(eq_df)
        trades_yr = total_trades / years if years > 0 else 0
        avg_hold = total_hold_days / total_trades if total_trades > 0 else 0.0
        
        return {
            'Strategy': name,
            'Regime_Control': use_regime,
            'CAGR': cagr,
            'Vol': ann_vol,
            'Sharpe': sharpe,
            'Sortino': sortino,
            'MaxDD': max_dd,
            'Trades_Yr': trades_yr,
            'Avg_Hold_Days': avg_hold,
            'Equity_Curve': eq_df.set_index('Date')['Capital']
        }

    # 10. RUN SIMULATIONS
    simulations = []
    
    # A. Baseline Momentum V2
    simulations.append(simulate_backtest("Momentum V2", None, use_regime=True))
    
    # B. Ridge Regression
    simulations.append(simulate_backtest("Ridge", ridge, use_regime=False))
    simulations.append(simulate_backtest("Ridge", ridge, use_regime=True))
    
    # C. Random Forest
    simulations.append(simulate_backtest("Random Forest", rf, use_regime=False))
    simulations.append(simulate_backtest("Random Forest", rf, use_regime=True))
    
    # D. XGBoost
    simulations.append(simulate_backtest("XGBoost", xgb_model, use_regime=False))
    simulations.append(simulate_backtest("XGBoost", xgb_model, use_regime=True))
    
    # E. LightGBM
    simulations.append(simulate_backtest("LightGBM", lgb_model, use_regime=False))
    simulations.append(simulate_backtest("LightGBM", lgb_model, use_regime=True))
    
    # F. PyTorch LSTM
    simulations.append(simulate_backtest("LSTM", lstm, use_regime=False))
    simulations.append(simulate_backtest("LSTM", lstm, use_regime=True))

    # 11. COMPILE RESULTS
    results_list = []
    for s in simulations:
        results_list.append({
            'Strategy': f"{s['Strategy']} (Regime)" if s['Regime_Control'] else f"{s['Strategy']} (Pure)",
            'CAGR': s['CAGR'],
            'Ann Vol': s['Vol'],
            'Sharpe': s['Sharpe'],
            'Sortino': s['Sortino'],
            'Max DD': s['MaxDD'],
            'Trades/Yr': s['Trades_Yr'],
            'Avg Hold (Days)': s['Avg_Hold_Days']
        })
        
    res_df = pd.DataFrame(results_list)
    
    print("\n" + "=" * 105)
    print("📈 OUT-OF-SAMPLE PERFORMANCE COMPARISON (2021 - 2026)")
    print("=" * 105)
    header = f"{'Strategy Name':<28} | {'CAGR':>7} | {'Ann Vol':>7} | {'Sharpe':>6} | {'Sortino':>7} | {'Max DD':>7} | {'Trades/Yr':>9} | {'Hold Days':>9}"
    print(header)
    print("-" * 105)
    for idx, row in res_df.iterrows():
        name = row['Strategy']
        cagr = f"{row['CAGR']:.2%}"
        vol = f"{row['Ann Vol']:.2%}"
        sharpe = f"{row['Sharpe']:.2f}"
        sortino = f"{row['Sortino']:.2f}"
        dd = f"{row['Max DD']:.2%}"
        trd = f"{row['Trades/Yr']:.1f}"
        hld = f"{row['Avg Hold (Days)']:.1f}"
        print(f"{name:<28} | {cagr:>7} | {vol:>7} | {sharpe:>6} | {sortino:>7} | {dd:>7} | {trd:>9} | {hld:>9}")
    print("=" * 105)
    
    # Save table to Markdown format
    with open("ml_backtest_results.md", "w") as f:
        f.write("# ML Stock Picking vs Momentum V2 Performance Comparison\n\n")
        f.write(f"**Test Period:** {TEST_START_DATE} to {df_all['Date'].max().strftime('%Y-%m-%d')} (Out-Of-Sample)\n")
        f.write(f"**Train Period:** 2015-01-01 to {TRAIN_END_DATE} (For ML Models)\n\n")
        f.write("| Strategy Name | CAGR | Ann Vol | Sharpe | Sortino | Max DD | Trades/Yr | Hold Days |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for idx, row in res_df.iterrows():
            name = row['Strategy']
            cagr = f"{row['CAGR']:.2%}"
            vol = f"{row['Ann Vol']:.2%}"
            sharpe = f"{row['Sharpe']:.2f}"
            sortino = f"{row['Sortino']:.2f}"
            dd = f"{row['Max DD']:.2%}"
            trd = f"{row['Trades/Yr']:.1f}"
            hld = f"{row['Avg Hold (Days)']:.1f}"
            f.write(f"| {name} | {cagr} | {vol} | {sharpe} | {sortino} | {dd} | {trd} | {hld} |\n")
            
    print("\n💾 Saved comparison report: ml_backtest_results.md")

    # 12. PLOT EQUITY CURVES
    plt.figure(figsize=(14, 8))
    for s in simulations:
        lbl = f"{s['Strategy']} (Regime)" if s['Regime_Control'] else f"{s['Strategy']} (Pure)"
        # Normalize to start at 1.0 (or 10M INR)
        norm_curve = s['Equity_Curve'] / INITIAL_CAPITAL
        plt.plot(norm_curve.index, norm_curve.values, label=lbl, alpha=0.8)
        
    plt.title("Equity Curve Comparison: ML Stock Selection vs Momentum V2 (2021-2026)", fontsize=14, fontweight='bold')
    plt.xlabel("Date", fontsize=12)
    plt.ylabel("Normalized Portfolio Value (Base 1.0)", fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(loc='upper left', frameon=True, shadow=True)
    plt.tight_layout()
    
    plt.savefig("ml_backtest_comparison.png", dpi=150)
    print("💾 Saved comparison chart: ml_backtest_comparison.png")
    
if __name__ == "__main__":
    main()
