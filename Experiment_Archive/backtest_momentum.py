import pandas as pd
import numpy as np
import warnings
import time

warnings.filterwarnings('ignore')

PARQUET_PATH = "nifty500_daily.parquet"
MOMENTUM_WINDOW = 126 # ~6 months
TOP_N = 20
ROUND_TRIP_COST = 0.0035 # 35 bps total per round trip to be safe

def build_market_regime(df_all):
    # Use real Nifty 50 Index (Downloaded LIVE from yfinance)
    import yfinance as yf
    
    print("🌐 Fetching latest Nifty 50 Index data for Regime Filter...")
    n50 = yf.download('^NSEI', start='2014-01-01', progress=False)
    
    if isinstance(n50.columns, pd.MultiIndex):
        n50.columns = n50.columns.get_level_values(0)
    
    n50.reset_index(inplace=True)
    n50['Date'] = pd.to_datetime(n50['Date']).dt.tz_localize(None)
    
    # Explicit mapping to avoid column order bugs
    merged = n50[['Date', 'Open', 'High', 'Low', 'Close']].copy()
    merged = merged.rename(columns={'Close': 'Market_Close'})
    
    for col in ['Market_Close', 'Open', 'High', 'Low']:
        merged[col] = pd.to_numeric(merged[col], errors='coerce')
        
    merged = merged.dropna(subset=['Market_Close']).sort_values('Date').reset_index(drop=True)
    
    # Sanity Check
    valid_mask = (merged['High'] >= merged['Open']) & (merged['High'] >= merged['Market_Close']) & \
                 (merged['Low'] <= merged['Open']) & (merged['Low'] <= merged['Market_Close'])
    
    if not valid_mask.all():
        print(f"⚠️  Warning: Found {len(merged) - valid_mask.sum()} invalid Nifty 50 candles in backtest stream. Filtering...")
        merged = merged[valid_mask].copy()

    # Calculate 200-day moving average and Bullish regime boolean
    merged['Market_SMA200'] = merged['Market_Close'].rolling(200).mean()
    merged['Market_Bullish'] = merged['Market_Close'] > merged['Market_SMA200']
    
    return merged[['Date', 'Market_Close', 'Market_Bullish']]

def run_momentum_backtest():
    print("🚀 NIFTY 500 Monthly Momentum Engine - Backtest")
    print("=" * 65)
    
    start_time = time.time()
    print("📂 Loading data...")
    df_all = pd.read_parquet(PARQUET_PATH)
    df_all['Date'] = pd.to_datetime(df_all['Date'])
    
    print("📊 Calculating indicators...")
    df_all = df_all.sort_values(['Ticker', 'Date'])
    
    # Needs to shift within groups
    df_all['Prev_Close_126'] = df_all.groupby('Ticker')['Close'].shift(MOMENTUM_WINDOW)
    df_all['Momentum_6M'] = (df_all['Close'] / df_all['Prev_Close_126']) - 1
    df_all['SMA200'] = df_all.groupby('Ticker')['Close'].transform(lambda x: x.rolling(200).mean())
    df_all['Turnover'] = df_all['Close'] * df_all['Volume']
    df_all['Avg_Turnover20'] = df_all.groupby('Ticker')['Turnover'].transform(lambda x: x.rolling(20).mean())
    
    # Market Regime
    market_df = build_market_regime(df_all)
    df_all = df_all.merge(market_df[['Date', 'Market_Bullish']], on='Date', how='left')
    df_all['Market_Bullish'] = df_all['Market_Bullish'].fillna(False)
    
    print("🗓️ Finding rebalance dates...")
    dates_df = pd.DataFrame({'Date': df_all['Date'].unique()}).sort_values('Date')
    dates_df['YearMonth'] = dates_df['Date'].dt.to_period('M')
    rebalance_dates = list(dates_df.groupby('YearMonth')['Date'].max())
    
    print(f"   Found {len(rebalance_dates)} monthly rebalance points.")
    
    print("🧮 Preparing return matrix...")
    df_all['Daily_Return'] = df_all.groupby('Ticker')['Close'].pct_change()
    
    # We only need close prices to calculate monthly holding returns
    close_matrix = df_all.pivot(index='Date', columns='Ticker', values='Close')
    
    portfolio_history = []
    current_portfolio = [] 
    capital = 1_000_000
    
    print("⚙️ Running simulation...")
    
    for i in range(len(rebalance_dates) - 1):
        reb_date = rebalance_dates[i]
        next_reb_date = rebalance_dates[i+1]
        
        day_data = df_all[df_all['Date'] == reb_date].copy()
        market_is_bullish = day_data['Market_Bullish'].iloc[0] if not day_data.empty else False
        
        target_portfolio = []
        
        if market_is_bullish:
            day_data = day_data.dropna(subset=['Momentum_6M', 'SMA200', 'Avg_Turnover20'])
            
            # Filters
            eligible = day_data[
                (day_data['Close'] > day_data['SMA200']) & 
                (day_data['Avg_Turnover20'] > 5e7) &  # 5Cr turnover
                (day_data['Close'] > 10)
            ]
            
            if not eligible.empty:
                top_stocks = eligible.sort_values('Momentum_6M', ascending=False).head(TOP_N)
                target_portfolio = top_stocks['Ticker'].tolist()
        
        # Calculate turnover
        sells = set(current_portfolio) - set(target_portfolio)
        buys = set(target_portfolio) - set(current_portfolio)
        
        turnover_count = len(sells) + len(buys)
        position_size = capital / TOP_N if TOP_N > 0 else 0
        turnover_cost = turnover_count * position_size * (ROUND_TRIP_COST / 2)
        capital -= turnover_cost
        
        # Calculate holding period return
        if target_portfolio:
            # We buy at close of reb_date, sell at close of next_reb_date
            available_tickers = [t for t in target_portfolio if t in close_matrix.columns]
            
            if available_tickers:
                try:
                    entry_prices = close_matrix.loc[reb_date, available_tickers]
                    exit_prices = close_matrix.loc[next_reb_date, available_tickers]
                    
                    # Fill missing exit prices with entry prices (assume 0% return if delisted etc)
                    exit_prices = exit_prices.fillna(entry_prices)
                    
                    stock_returns = (exit_prices - entry_prices) / entry_prices
                    port_return = stock_returns.mean()
                except KeyError:
                    port_return = 0.0
            else:
                port_return = 0.0
        else:
            port_return = 0.0 # Cash
            
        capital = capital * (1 + port_return)
        
        portfolio_history.append({
            'Date': next_reb_date,
            'Capital': capital,
            'Market_Bullish': market_is_bullish,
            'Turnover': turnover_count,
            'Holdings': len(target_portfolio)
        })
        
        current_portfolio = target_portfolio

    res_df = pd.DataFrame(portfolio_history)
    res_df = res_df.dropna()
    res_df['Peak'] = res_df['Capital'].cummax()
    res_df['Drawdown'] = (res_df['Capital'] - res_df['Peak']) / res_df['Peak']
    
    total_years = (res_df['Date'].max() - res_df['Date'].min()).days / 365.25
    cagr = ((capital / 1_000_000) ** (1/total_years) - 1) if total_years > 0 else 0
    max_dd = res_df['Drawdown'].min()
    
    monthly_returns = res_df['Capital'].pct_change().dropna()
    win_months = (monthly_returns > 0).sum()
    loss_months = (monthly_returns < 0).sum()
    win_rate = win_months / len(monthly_returns) if len(monthly_returns) > 0 else 0
    avg_win = monthly_returns[monthly_returns > 0].mean() if win_months > 0 else 0
    avg_loss = monthly_returns[monthly_returns < 0].mean() if loss_months > 0 else 0
    
    print("\n✅ Simulation complete in {:.1f} seconds".format(time.time() - start_time))
    print("\n=================================================================")
    print("📈 MONTHLY MOMENTUM (TOP 20) — FULL BACKTEST")
    print("=================================================================")
    print(f"Period             : {res_df['Date'].min().strftime('%Y-%m-%d')} to {res_df['Date'].max().strftime('%Y-%m-%d')}")
    print(f"Ending Capital     : ₹{capital:,.2f}")
    print(f"CAGR               : {cagr:.2%}")
    print(f"Max Drawdown       : {max_dd:.2%}")
    print("")
    print(f"Win Rate (Months)  : {win_rate:.2%}")
    print(f"Average Win Month  : {avg_win:.2%}")
    print(f"Average Loss Month : {avg_loss:.2%}")
    print(f"Average Turnover   : {res_df['Turnover'].mean():.1f} stocks/month")
    print("=================================================================")
    return monthly_returns

if __name__ == "__main__":
    run_momentum_backtest()
