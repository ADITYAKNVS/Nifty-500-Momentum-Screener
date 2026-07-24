import pandas as pd
import numpy as np
import json
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge

PARQUET_PATH = "nifty500_daily.parquet"
MOMENTUM_WINDOW = 252
SKIP_DAYS = 21
REGIME_SMA = 100
MIN_TURNOVER = 1e7

def get_next_trading_day(current_date, all_dates):
    try:
        idx = all_dates.index(current_date)
        if idx + 1 < len(all_dates):
            return all_dates[idx + 1]
    except ValueError:
        pass
    return current_date

def get_ridge_parameters():
    print("Loading parquet...")
    df_all = pd.read_parquet(PARQUET_PATH)
    df_all['Date'] = pd.to_datetime(df_all['Date']).dt.tz_localize(None)
    df_all = df_all.sort_values(['Ticker', 'Date']).reset_index(drop=True)
    
    nifty500_csv = pd.read_csv("ind_nifty500list.csv")
    valid_tickers = set(nifty500_csv['Symbol'].dropna())
    df_all = df_all[df_all['Ticker'].isin(valid_tickers)].copy()
    
    df_all['Daily_Return'] = df_all.groupby('Ticker')['Close'].pct_change().fillna(0.0)
    df_all['Ret_21'] = df_all.groupby('Ticker')['Close'].pct_change(21)
    df_all['Ret_63'] = df_all.groupby('Ticker')['Close'].pct_change(63)
    df_all['Ret_126'] = df_all.groupby('Ticker')['Close'].pct_change(126)
    df_all['Ret_252'] = df_all.groupby('Ticker')['Close'].pct_change(252)

    df_all['Vol_20'] = df_all.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(20).std() * np.sqrt(252))
    df_all['Vol_60'] = df_all.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(60).std() * np.sqrt(252))
    df_all['Vol_20'] = df_all['Vol_20'].replace(0, np.nan).fillna(0.20)
    df_all['Vol_60'] = df_all['Vol_60'].replace(0, np.nan).fillna(0.20)

    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover_20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    df_all['Turnover_Ratio'] = (df_all['Turnover'] / df_all['Avg_Turnover_20'].replace(0, np.nan).fillna(1e6))

    df_all['SMA50'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(50).mean())
    df_all['SMA200'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())

    df_all['Price_to_SMA50'] = (df_all['Close'] / df_all['SMA50'].replace(0, np.nan))
    df_all['Price_to_SMA200'] = (df_all['Close'] / df_all['SMA200'].replace(0, np.nan))
    df_all['RiskAdjMom'] = (df_all['Ret_252'] / df_all['Vol_60'].replace(0, np.nan))
    
    features_cols = ['Ret_21', 'Ret_63', 'Ret_126', 'Ret_252', 'Vol_20', 'Vol_60', 'Turnover_Ratio', 'Price_to_SMA50', 'Price_to_SMA200', 'RiskAdjMom']
    
    CLOSE_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Close')
    OPEN_MATRIX = df_all.pivot(index='Date', columns='Ticker', values='Open')
    ALL_DATES = sorted(list(CLOSE_MATRIX.index))
    
    dates_df = pd.DataFrame({'Date': CLOSE_MATRIX.index}).sort_values('Date').dropna()
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    rebalance_dates = list(dates_df.groupby('YearMonth')['Date'].max())
    
    targets = []
    train_rebal_dates = [d for d in rebalance_dates if d <= pd.to_datetime('2020-12-31')]
    for k in range(len(train_rebal_dates) - 1):
        tk = train_rebal_dates[k]
        tk_next = train_rebal_dates[k+1]
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
    df_rebal = df_all[df_all['Date'].isin(train_rebal_dates[:-1])]
    df_ml = pd.merge(df_rebal, targets_df, on=['Date', 'Ticker'], how='inner')
    
    imputer = SimpleImputer(strategy='median')
    scaler = StandardScaler()
    
    X_train_raw = df_ml[features_cols].replace([np.inf, -np.inf], np.nan)
    y_train = df_ml['Target_Return']
    
    X_train = imputer.fit_transform(X_train_raw)
    X_train = scaler.fit_transform(X_train)
    
    ridge = Ridge(alpha=1.0)
    ridge.fit(X_train, y_train)
    
    result = {
        "features": features_cols,
        "coefs": list(ridge.coef_),
        "intercept": float(ridge.intercept_),
        "means": list(scaler.mean_),
        "scales": list(scaler.scale_),
        "medians": list(imputer.statistics_)
    }
    
    print("\n=== RIDGE MODEL COEFFICIENTS AND SCALING PARAMETERS ===")
    print(json.dumps(result, indent=4))
    
    with open("scratch/ridge_parameters.json", "w") as f:
        json.dump(result, f, indent=4)
    print("\nSaved to scratch/ridge_parameters.json")

if __name__ == "__main__":
    get_ridge_parameters()
