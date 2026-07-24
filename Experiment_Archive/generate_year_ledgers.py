import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from backtest_momentum_v2 import GLOBAL_DF, CLOSE_MATRIX, build_market_regime
import warnings
warnings.filterwarnings('ignore')

def generate_ledger(year):
    print(f"🚀 Extracting Trade Ledger for God Mode 1.1x in {year}...")
    
    config = {
        'regime_sma': 100, 
        'top_n': 5,
        'momentum_window': 252,
        'skip_recent_days': 21,
        'allow_hold_rank': 15,
        'min_turnover': 1e7,
        'leverage': 1.10
    }
    
    df_all = GLOBAL_DF.copy()
    
    momentum_window = config['momentum_window']
    skip_recent_days = config['skip_recent_days']
    min_turnover = config['min_turnover']
    leverage = config['leverage']
    top_n = config['top_n']
    allow_hold_rank = config['allow_hold_rank']
    
    df_all['Prev_Close_Window'] = df_all.groupby('Ticker')['Close'].shift(momentum_window)
    if skip_recent_days > 0:
        df_all['Recent_Close'] = df_all.groupby('Ticker')['Close'].shift(skip_recent_days)
        df_all['Momentum_Score'] = (df_all['Recent_Close'] / df_all['Prev_Close_Window']) - 1
    else:
        df_all['Momentum_Score'] = (df_all['Close'] / df_all['Prev_Close_Window']) - 1
        
    df_all['SMA_Trend'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    df_all['Realized_Vol_20'] = df_all.groupby('Ticker')['Daily_Return'].transform(lambda x: x.rolling(20).std() * np.sqrt(252))
    
    # Nifty 50 Regime
    market_df = build_market_regime(df_all, sma_length=config['regime_sma'])
    df_all = df_all.merge(market_df, on='Date', how='left')
    df_all['Market_Bullish'] = df_all['Market_Bullish'].fillna(False)
    
    dates_df = pd.DataFrame({'Date': list(CLOSE_MATRIX.index)}).sort_values('Date').dropna()
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    target_dates = list(dates_df.groupby('YearMonth')['Date'].max())
    
    target_dates = [d for d in target_dates if d.year == year]
    
    if not target_dates:
        print(f"No dates found for {year}!")
        return

    initial_capital = 1_000_000
    cash = initial_capital
    total_assets = initial_capital
    positions = {}
    ROUND_TRIP_COST = 0.0035

    trade_log = []

    for i, reb_date in enumerate(target_dates):
        str_date = reb_date.strftime('%Y-%m-%d')
        
        day_data = df_all[df_all['Date'] == reb_date].copy()
        market_is_bullish = day_data['Market_Bullish'].iloc[0] if not day_data.empty else False
        target_portfolio = []
        target_weights = {}

        if market_is_bullish:
            day_data = day_data.dropna(subset=['Momentum_Score', 'SMA_Trend', 'Avg_Turnover20'])
            eligible = day_data[
                (day_data['Close'] > day_data['SMA_Trend']) & 
                (day_data['Avg_Turnover20'] > min_turnover) & 
                (day_data['Close'] > 10)
            ].sort_values('Momentum_Score', ascending=False)
            
            if not eligible.empty:
                if allow_hold_rank is not None:
                    held_tickers = set(positions.keys())
                    buffer_eligible = eligible['Ticker'].head(allow_hold_rank).tolist()
                    to_keep = [t for t in buffer_eligible if t in held_tickers]
                    to_add = [t for t in eligible['Ticker'].tolist() if t not in to_keep]
                    target_portfolio = to_keep + to_add[:max(0, top_n - len(to_keep))]
                else:
                    target_portfolio = eligible['Ticker'].head(top_n).tolist()
            
            if target_portfolio:
                w = 1.0 / len(target_portfolio)
                target_weights = {t: w for t in target_portfolio}

        holds = [t for t in positions if t in target_portfolio]
        sells = [t for t in positions if t not in target_portfolio]
        
        for t in sells:
            p = CLOSE_MATRIX.loc[reb_date, t] if t in CLOSE_MATRIX.columns else 0
            if pd.isna(p) or p == 0: p = positions[t]['entry_price']
            
            shares = positions[t]['shares']
            gross_val = shares * p
            cost = gross_val * (ROUND_TRIP_COST / 2)
            net_val = gross_val - cost
            
            cash += net_val
            total_assets = cash + sum(positions[ht]['shares'] * CLOSE_MATRIX.loc[reb_date, ht] for ht in holds if pd.notna(CLOSE_MATRIX.loc[reb_date, ht]))
            
            trade_log.append({
                'Date': str_date,
                'Action': 'SELL',
                'Ticker': t,
                'Shares': round(shares, 2),
                'Price': round(p, 2),
                'Value': round(net_val, 2),
                'Profit_Pct': round((p / positions[t]['entry_price'] - 1) * 100, 2)
            })
            del positions[t]
            
        buys = [t for t in target_portfolio if t not in holds]
        
        for t in holds:
            p = CLOSE_MATRIX.loc[reb_date, t] if t in CLOSE_MATRIX.columns else positions[t]['entry_price']
            if pd.isna(p): p = positions[t]['entry_price']
            
            current_val = positions[t]['shares'] * p
            target_val = total_assets * target_weights[t] * leverage
            diff = target_val - current_val
            
            if diff > 0: 
                cost = diff * (ROUND_TRIP_COST / 2)
                cash -= (diff + cost)
                positions[t]['shares'] += diff / p
            elif diff < 0: 
                amount_to_sell = abs(diff)
                cost = amount_to_sell * (ROUND_TRIP_COST / 2)
                cash += (amount_to_sell - cost)
                positions[t]['shares'] -= amount_to_sell / p
                
        for t in buys:
            p = CLOSE_MATRIX.loc[reb_date, t] if t in CLOSE_MATRIX.columns else 0
            if pd.isna(p) or p == 0: continue
            
            target_val = total_assets * target_weights[t] * leverage
            cost = target_val * (ROUND_TRIP_COST / 2)
            cash -= (target_val + cost)
            
            positions[t] = {
                'shares': target_val / p,
                'entry_price': p
            }
            trade_log.append({
                'Date': str_date,
                'Action': 'BUY',
                'Ticker': t,
                'Shares': round(target_val / p, 2),
                'Price': round(p, 2),
                'Value': round(target_val, 2),
                'Profit_Pct': 0.0
            })
            
        daily_curr_vals = [positions[t]['shares'] * (CLOSE_MATRIX.loc[reb_date, t] if pd.notna(CLOSE_MATRIX.loc[reb_date, t]) else positions[t]['entry_price']) for t in positions]
        total_assets = cash + sum(daily_curr_vals)
        
    end_date = target_dates[-1].strftime('%Y-%m-%d')
    for t in list(positions.keys()):
        p = CLOSE_MATRIX.loc[target_dates[-1], t] if t in CLOSE_MATRIX.columns else positions[t]['entry_price']
        if pd.isna(p) or p == 0: p = positions[t]['entry_price']
        
        trade_log.append({
            'Date': end_date,
            'Action': 'OPEN (E.O.Y)',
            'Ticker': t,
            'Shares': round(positions[t]['shares'], 2),
            'Price': round(p, 2),
            'Value': round(positions[t]['shares'] * p, 2),
            'Profit_Pct': round((p / positions[t]['entry_price'] - 1) * 100, 2)
        })

    df_log = pd.DataFrame(trade_log)
    filepath = f"god_mode_trades_{year}.csv"
    df_log.to_csv(filepath, index=False)
    print(f"✅ Executed {len(df_log)} log entries. Saved to: {filepath}\n")

if __name__ == "__main__":
    generate_ledger(2020)
    generate_ledger(2022)
    generate_ledger(2025)
