import numpy as np
import pandas as pd
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from backtest_momentum_v2 import GLOBAL_DF, CLOSE_MATRIX, build_market_regime
import warnings
warnings.filterwarnings('ignore')

def analyze_year(year):
    print(f"\n================================================================================")
    print(f"📊 BEHAVIORAL ANALYSIS: {year}")
    print(f"================================================================================")

    config = {
        'top_n': 5,
        'momentum_window': 252,
        'skip_recent_days': 21,
        'allow_hold_rank': 15,
        'regime_sma': 100,
        'min_turnover': 1e7,
        'leverage': 1.10
    }

    df_all = GLOBAL_DF.copy()
    
    # Pre-calculate Momentum
    df_all['Prev_Close'] = df_all.groupby('Ticker')['Close'].shift(config['momentum_window'])
    df_all['Rec_Close'] = df_all.groupby('Ticker')['Close'].shift(config['skip_recent_days'])
    df_all['Momentum_Score'] = (df_all['Rec_Close'] / df_all['Prev_Close']) - 1
    
    df_all['SMA_Trend'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    
    market_df = build_market_regime(df_all, sma_length=config['regime_sma'])
    df_all = df_all.merge(market_df, on='Date', how='left')
    df_all['Market_Bullish'] = df_all['Market_Bullish'].fillna(False)

    dates_df = pd.DataFrame({'Date': list(CLOSE_MATRIX.index)}).sort_values('Date').dropna()
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    all_target_dates = list(dates_df.groupby('YearMonth')['Date'].max())
    
    target_dates = [d for d in all_target_dates if d.year == year]
    if not target_dates: return
    
    # We calculate the start context from the end of the previous year
    prior_date = all_target_dates[all_target_dates.index(target_dates[0]) - 1] if target_dates[0] in all_target_dates and all_target_dates.index(target_dates[0]) >= 1 else None

    # We will simulate exactly 1 year starting with 1M INR
    cash = 1000000.0
    positions = {}
    ROUND_TRIP_COST = 0.0035
    
    trades = 0
    cash_allocation = []
    
    daily_equity = []
    
    for i, reb_date in enumerate(target_dates):
        day_data = df_all[df_all['Date'] == reb_date].copy()
        market_is_bullish = day_data['Market_Bullish'].iloc[0] if not day_data.empty else False
        
        target_portfolio = []
        target_weights = {}

        if market_is_bullish:
            day_data = day_data.dropna(subset=['Momentum_Score', 'SMA_Trend', 'Avg_Turnover20'])
            eligible = day_data[
                (day_data['Close'] > day_data['SMA_Trend']) & 
                (day_data['Avg_Turnover20'] > config['min_turnover']) & 
                (day_data['Close'] > 10)
            ].sort_values('Momentum_Score', ascending=False)
            
            if not eligible.empty:
                held_tickers = set(positions.keys())
                buffer_eligible = eligible['Ticker'].head(config['allow_hold_rank']).tolist()
                to_keep = [t for t in buffer_eligible if t in held_tickers]
                to_add = [t for t in eligible['Ticker'].tolist() if t not in to_keep]
                target_portfolio = to_keep + to_add[:max(0, config['top_n'] - len(to_keep))]
                
            if target_portfolio:
                w = 1.0 / len(target_portfolio)
                target_weights = {t: w for t in target_portfolio}

        # Value portfolio
        invested = 0
        for t, pos in positions.items():
            p = CLOSE_MATRIX.loc[reb_date, t] if t in CLOSE_MATRIX.columns else 0
            if pd.isna(p) or p == 0: p = pos['entry_price']
            invested += pos['shares'] * p
            
        total_assets = cash + invested
        target_total_invested = total_assets * config['leverage'] if len(target_portfolio) > 0 else 0
        cash_allocation.append((cash / total_assets) * 100)
        
        # 1. Sells
        sells = [t for t in positions if t not in target_portfolio]
        for t in sells:
            p = CLOSE_MATRIX.loc[reb_date, t] if t in CLOSE_MATRIX.columns else 0
            if pd.isna(p) or p == 0: p = positions[t]['entry_price']
            gross_val = positions[t]['shares'] * p
            cost = gross_val * (ROUND_TRIP_COST / 2)
            cash += (gross_val - cost)
            total_assets -= cost
            del positions[t]
            trades += 1
            
        # 2. Adjust & Buy
        holds = [t for t in positions if t in target_portfolio]
        buys = [t for t in target_portfolio if t not in positions]
        
        for t in holds:
            p = CLOSE_MATRIX.loc[reb_date, t] if t in CLOSE_MATRIX.columns else 0
            if pd.isna(p) or p == 0: p = positions[t]['entry_price']
            current_val = positions[t]['shares'] * p
            target_val = total_assets * target_weights[t] * config['leverage']
            diff = target_val - current_val
            if diff > 0:
                cost = diff * (ROUND_TRIP_COST / 2)
                cash -= (diff + cost)
                total_assets -= cost
                positions[t]['shares'] += diff / p
            elif diff < 0:
                amt = abs(diff)
                cost = amt * (ROUND_TRIP_COST / 2)
                cash += (amt - cost)
                total_assets -= cost
                positions[t]['shares'] -= amt / p
                
        for t in buys:
            p = CLOSE_MATRIX.loc[reb_date, t] if t in CLOSE_MATRIX.columns else 0
            if pd.isna(p) or p == 0: continue
            target_val = total_assets * target_weights[t] * config['leverage']
            cost = target_val * (ROUND_TRIP_COST / 2)
            cash -= (target_val + cost)
            total_assets -= cost
            positions[t] = {'shares': target_val / p, 'entry_price': p}
            trades += 1
            
        # Track daily equity
        next_date = target_dates[i+1] if i+1 < len(target_dates) else None
        end_idx = list(CLOSE_MATRIX.index).index(next_date) if next_date in CLOSE_MATRIX.index else len(CLOSE_MATRIX.index)
        start_idx = list(CLOSE_MATRIX.index).index(reb_date)
        
        for d_idx in range(start_idx, end_idx):
            d = list(CLOSE_MATRIX.index)[d_idx]
            if d.year > year+1: break # small spillover buffer
            day_val = 0
            for t in positions:
                p = CLOSE_MATRIX.loc[d, t] if t in CLOSE_MATRIX.columns else 0
                if pd.isna(p) or p == 0: p = positions[t]['entry_price']
                day_val += positions[t]['shares'] * p
            daily_equity.append(cash + day_val)
            
    eq_series = pd.Series(daily_equity)
    if eq_series.empty: return
    
    ret = (eq_series.iloc[-1] / 1000000.0) - 1
    peak = eq_series.cummax()
    dd = ((eq_series - peak) / peak).min()
    
    avg_cash = np.mean(cash_allocation)
    months_in_cash = sum(1 for c in cash_allocation if c > 90)
    
    print(f"📈 Return: {ret:.2%}")
    print(f"📉 Max Drawdown: {dd:.2%}")
    print(f"🔄 Total Trades: {trades}")
    print(f"💵 Avg Cash Position: {avg_cash:.1f}%")
    print(f"🛑 Months 100% in Cash: {months_in_cash} out of {len(target_dates)}")
    print(f"🧠 Behavioral Notes:")
    
    if year == 2016:
        print("  - Demonetization shock hit in Nov 2016. Sideways chop early year.")
        if months_in_cash > 0: print(f"  - The Nifty100 SMA regime filter successfully pushed the portfolio to cash for {months_in_cash} months, dodging the worst of the volatility.")
        else: print("  - Kept taking shots during the choppy period leading to high turnover.")
    elif year == 2018:
        print("  - Midcap Bear Market & NBFC crisis. This is notoriously hard for Momentum.")
        if ret < 0: print("  - Strategy suffered a drawdown. The 100-day SMA was slow to trigger a total cash exit while midcaps bled out incrementally.")
        if trades > 40: print("  - High churn (whipsaw). The model kept trying to buy relative strength bounces that quickly failed in the bear market.")
    elif year == 2020:
        print("  - COVID-19 Crash & V-shaped Recovery.")
        if months_in_cash >= 2: print("  - The regime filter correctly identified the catastrophic breakdown and hunkered down in CASH during the bloodbath.")
        if ret > 40: print("  - Once the market trended back up, it aggressively re-leveraged into high momentum winners, catching the massive post-COVID rally.")
    elif year == 2022:
        print("  - War, inflation, and rate hikes sideways chop.")
        if dd > -15 and ret > 0: print("  - Impressively defensive. Momentum usually gets violently whipsawed here, but the model managed small positive returns with contained drawdowns.")

if __name__ == "__main__":
    for y in [2016, 2018, 2020, 2022]:
        analyze_year(y)
