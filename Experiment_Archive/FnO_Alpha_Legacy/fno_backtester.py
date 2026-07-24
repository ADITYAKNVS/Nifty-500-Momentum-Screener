#!/usr/bin/env python3
import pandas as pd
import numpy as np
from datetime import timedelta
import sys

# Constants matching Phase 2/3 thresholds
OI_SPIKE_THRESHOLD = 0.05
PRICE_CHANGE_MIN = 0.005
PORTFOLIO_CAPITAL = 1_000_000
MAX_RISK_PER_TRADE = 0.02
MASTER_PARQUET = "fno_master.parquet"
OPTIONS_PARQUET = "fno_options_master.parquet"

def round_to_strike(price):
    if price > 25000: step = 100
    elif price > 10000: step = 100
    elif price > 1000: step = 50
    elif price > 500: step = 10
    else: step = 5
    return round(price / step) * step

def load_data():
    try:
        fut_df = pd.read_parquet(MASTER_PARQUET)
        opt_df = pd.read_parquet(OPTIONS_PARQUET)
        
        # Ensure datetimes across mixed formatting bounds
        fut_df['Date'] = pd.to_datetime(fut_df['Date'], format='mixed', errors='coerce')
        opt_df['Date'] = pd.to_datetime(opt_df['Date'], format='mixed', errors='coerce')
        opt_df['EXPIRY_DT'] = pd.to_datetime(opt_df['EXPIRY_DT'], format='mixed', errors='coerce')
        return fut_df, opt_df
    except Exception as e:
        print(f"❌ Cache error (Run Data Engine first): {e}")
        sys.exit(1)

def run_backtest():
    print("=" * 60)
    print("🔮 F&O ALPHA BACKTESTER (Multi-Year Spread Simulator)")
    print("=" * 60)
    
    fut_df, opt_df = load_data()
    
    # --- REGIME FILTER (ALPHA QUANT PORT) ---
    nifty_context = fut_df[fut_df['SYMBOL'] == 'NIFTY'][['Date', 'CLOSE']].rename(columns={'CLOSE': 'NIFTY_Close'})
    nifty_context = nifty_context.sort_values('Date').drop_duplicates('Date')
    nifty_context['NIFTY_SMA100'] = nifty_context['NIFTY_Close'].rolling(100, min_periods=1).mean()
    fut_df = fut_df.merge(nifty_context, on='Date', how='left')
    fut_df['NIFTY_Regime_Bullish'] = fut_df['NIFTY_Close'] > fut_df['NIFTY_SMA100']
    
    # 1. GENERATE OI SIGNALS
    fut_df = fut_df.sort_values(['SYMBOL', 'Date']).reset_index(drop=True)
    fut_df['OI_5D_Baseline'] = fut_df.groupby('SYMBOL')['OPEN_INT'].transform(lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    fut_df['Prev_Close'] = fut_df.groupby('SYMBOL')['CLOSE'].transform(lambda x: x.shift(1))
    
    fut_df['OI_Spike_Pct'] = (fut_df['OPEN_INT'] - fut_df['OI_5D_Baseline']) / fut_df['OI_5D_Baseline']
    fut_df['Price_Change_Pct'] = (fut_df['CLOSE'] - fut_df['Prev_Close']) / fut_df['Prev_Close']
    
    # Red Flag 4 Fix: Dynamically lower threshold for heavily liquified indices or they never trigger unconditionally
    fut_df['Dyn_OI_Threshold'] = np.where(fut_df['SYMBOL'].isin(['NIFTY', 'BANKNIFTY']), 0.00, OI_SPIKE_THRESHOLD)
    fut_df['Dyn_Px_Threshold'] = np.where(fut_df['SYMBOL'].isin(['NIFTY', 'BANKNIFTY']), 0.001, PRICE_CHANGE_MIN)
    
    conditions = [
        (fut_df['OI_Spike_Pct'] > fut_df['Dyn_OI_Threshold']) & (fut_df['Price_Change_Pct'] >= fut_df['Dyn_Px_Threshold']),
        (fut_df['OI_Spike_Pct'] > fut_df['Dyn_OI_Threshold']) & (fut_df['Price_Change_Pct'] <= -fut_df['Dyn_Px_Threshold']),
        (fut_df['OI_Spike_Pct'] < -fut_df['Dyn_OI_Threshold']) & (fut_df['Price_Change_Pct'] >= fut_df['Dyn_Px_Threshold']),
        (fut_df['OI_Spike_Pct'] < -fut_df['Dyn_OI_Threshold']) & (fut_df['Price_Change_Pct'] <= -fut_df['Dyn_Px_Threshold'])
    ]
    choices = ['Long Buildup', 'Short Buildup', 'Short Covering', 'Long Unwinding']
    fut_df['Signal_State'] = np.select(conditions, choices, default='Neutral')
    
    fut_df['Lag1'] = fut_df.groupby('SYMBOL')['Signal_State'].shift(1)
    fut_df['Lag2'] = fut_df.groupby('SYMBOL')['Signal_State'].shift(2)
    fut_df['Consecutive_3_Days'] = (fut_df['Signal_State'] != 'Neutral') & (fut_df['Signal_State'] == fut_df['Lag1']) & (fut_df['Signal_State'] == fut_df['Lag2'])
    
    # Isolate confirmed setups: 
    #   1. Routine 3-Day stock anomalies 
    #   2. Unconditional daily scanning for Index (NIFTY/BANKNIFTY) upon ANY Long/Short buildup
    entry_signals = fut_df[
        (fut_df['Consecutive_3_Days'] == True) | 
        ((fut_df['SYMBOL'].isin(['NIFTY', 'BANKNIFTY'])) & (fut_df['Signal_State'] != 'Neutral'))
    ].copy()
    entry_signals = entry_signals[entry_signals['Signal_State'].isin(['Long Buildup', 'Short Buildup'])]
    
    # ── APPLY REGIME FILTER ──
    # Actively suppress standard stock trading in Sideways/Choppy Regimes (NIFTY < SMA100)
    # Index execution stays mathematically alive unconditionally.
    regime_mask = (entry_signals['SYMBOL'].isin(['NIFTY', 'BANKNIFTY'])) | (entry_signals['NIFTY_Regime_Bullish'] == True)
    entry_signals = entry_signals[regime_mask]
    
    print(f"🔎 Detected {len(entry_signals)} historical institutional anomalies (Filtered by SMA100). Initiating Walk-Forward Execution...")
    
    # Structural Indexing Optimization
    opt_df.set_index(['Date', 'SYMBOL', 'OPTION_TYPE'], inplace=True)
    opt_df.sort_index(inplace=True)
    
    trade_log = []
    
    for idx, row in entry_signals.iterrows():
        entry_date = row['Date']
        ticker = row['SYMBOL']
        signal = row['Signal_State']
        spot_price = row['CLOSE']
        
        atm_strike = round_to_strike(spot_price)
        
        if signal == "Long Buildup":
            if ticker == 'NIFTY': otm_strike = atm_strike + 150
            elif ticker == 'BANKNIFTY': otm_strike = atm_strike + 300
            else: otm_strike = round_to_strike(spot_price * 1.03)
            leg_type = "CE"
            action_type = "Bull Call Spread"
        else:
            if ticker == 'NIFTY': otm_strike = atm_strike - 150
            elif ticker == 'BANKNIFTY': otm_strike = atm_strike - 300
            else: otm_strike = round_to_strike(spot_price * 0.97)
            leg_type = "PE"
            action_type = "Bear Put Spread"
            
        try:
            daily_chain = opt_df.loc[(entry_date, ticker, leg_type)]
            if isinstance(daily_chain, pd.Series):
                daily_chain = daily_chain.to_frame().T
        except KeyError:
            continue
            
        if daily_chain.empty: continue
            
        # ── 1. Target Expiry: Monthly (Last Thursday) ──
        expiries = pd.to_datetime(daily_chain['EXPIRY_DT'].unique())
        # Rule out heavily theta-decayed 0-DTE or 1-DTE weeklies by demanding at least 5 days breathing room
        valid_expiries = expiries[expiries >= entry_date + pd.Timedelta(days=5)]
        if len(valid_expiries) == 0: continue
            
        # Identify the LAST expiry available within the earliest target month
        monthly_expiries = pd.Series(valid_expiries).groupby(pd.Series(valid_expiries).dt.to_period('M')).max()
        target_expiry = monthly_expiries.iloc[0]
        
        target_chain = daily_chain[daily_chain['EXPIRY_DT'] == target_expiry]
        
        # ── EXTRACT ENTRY PREMIUMS ──
        atm_leg = target_chain[target_chain['STRIKE'] == atm_strike]
        otm_leg = target_chain[target_chain['STRIKE'] == otm_strike]
        
        if atm_leg.empty or otm_leg.empty:
            continue
            
        atm_prem = float(atm_leg['CLOSE'].values[0])
        otm_prem = float(otm_leg['CLOSE'].values[0])
        lot_size = int(atm_leg['LOT_SIZE'].values[0])
        
        if lot_size == 0: lot_size = 50
        
        net_debit = atm_prem - otm_prem
        if net_debit <= 0: continue
            
        # Compute exact Sizing (Max Risk limit)
        max_rupee_loss = PORTFOLIO_CAPITAL * MAX_RISK_PER_TRADE
        optimal_lots = max(1, int(max_rupee_loss / (net_debit * lot_size)))
        
        actual_risk_rs = optimal_lots * lot_size * net_debit
        spread_width = abs(atm_strike - otm_strike)
        
        # Absolute execution firewalls defined by User
        if net_debit >= spread_width:
            continue
        if actual_risk_rs > max_rupee_loss * 1.1:
            continue
            
        max_profit_rs = (spread_width - net_debit) * lot_size * optimal_lots
        
        target_profit_rs = max_profit_rs * 0.50 # 50% Take-Profit Threshold
        
        # ── 2. Walk Forward EXIT LOGIC ──
        underlying_future = fut_df[(fut_df['SYMBOL'] == ticker) & (fut_df['Date'] > entry_date) & (fut_df['Date'] <= target_expiry)].copy()
        if underlying_future.empty: continue
        
        future_dates = underlying_future['Date'].unique()
        exit_date = target_expiry
        exit_pnl = 0
        exit_premium = 0
        exit_reason = "Expiry"
        
        # Sweep future dates to test early Exit Module
        for sim_date in future_dates:
            try:
                sim_chain = opt_df.loc[(sim_date, ticker, leg_type)]
                if isinstance(sim_chain, pd.Series): sim_chain = sim_chain.to_frame().T
                
                sim_atm = sim_chain[(sim_chain['STRIKE'] == atm_strike) & (sim_chain['EXPIRY_DT'] == target_expiry)]
                sim_otm = sim_chain[(sim_chain['STRIKE'] == otm_strike) & (sim_chain['EXPIRY_DT'] == target_expiry)]
                
                if not sim_atm.empty and not sim_otm.empty:
                    sim_atm_prem = float(sim_atm['CLOSE'].values[0])
                    sim_otm_prem = float(sim_otm['CLOSE'].values[0])
                    current_debit = sim_atm_prem - sim_otm_prem
                    
                    current_pnl = (current_debit - net_debit) * lot_size * optimal_lots
                    
                    # 50% TAKE PROFIT EXIT RULE
                    if current_pnl >= target_profit_rs:
                        exit_date = sim_date
                        exit_pnl = current_pnl
                        exit_premium = current_debit
                        exit_reason = "50% Profit Exit"
                        break
            except KeyError:
                continue
                
        # Fallback Expiry Settle Rule (No take-profit tripped)
        if exit_reason == "Expiry":
            exit_spot = underlying_future.iloc[-1]['CLOSE']
            exit_date = underlying_future.iloc[-1]['Date']
            
            if signal == "Long Buildup":
                if exit_spot >= otm_strike:
                    exit_pnl = max_profit_rs
                    exit_premium = spread_width
                elif exit_spot <= atm_strike:
                    exit_pnl = -actual_risk_rs
                    exit_premium = 0
                else:
                    intrinsic = (exit_spot - atm_strike)
                    exit_pnl = (intrinsic - net_debit) * lot_size * optimal_lots
                    exit_premium = intrinsic
            else:
                if exit_spot <= otm_strike:
                    exit_pnl = max_profit_rs
                    exit_premium = spread_width
                elif exit_spot >= atm_strike:
                    exit_pnl = -actual_risk_rs
                    exit_premium = 0
                else:
                    intrinsic = (atm_strike - exit_spot)
                    exit_pnl = (intrinsic - net_debit) * lot_size * optimal_lots
                    exit_premium = intrinsic
        
        trade_log.append({
            'Entry_Date': entry_date.strftime('%Y-%m-%d'),
            'Ticker': ticker,
            'Action': action_type,
            'Strike': f"{atm_strike}/{otm_strike} {leg_type}",
            'Expiry': target_expiry.strftime('%Y-%m-%d'),
            'Lots': optimal_lots,
            'Entry_Premium': round(net_debit, 2),
            'Exit_Date': exit_date.strftime('%Y-%m-%d'),
            'Exit_Premium': round(exit_premium, 2),
            'PnL': round(exit_pnl, 2),
            'Note': exit_reason
        })

    if not trade_log:
        print("📉 Zero active trades evaluated. Wait for Data Engine.")
        return
        
    trades_df = pd.DataFrame(trade_log)
    
    trades_df.to_csv("fno_trade_journal.csv", index=False)
    
    # Compute Global Math to address Red Flag 3
    total_trades = len(trades_df)
    win_rate = (len(trades_df[trades_df['PnL'] > 0]) / total_trades) * 100 if total_trades > 0 else 0
    total_pnl = trades_df['PnL'].sum()
    avg_pnl = trades_df['PnL'].mean()
    
    # Drawdown Physics and Monthly Tracking 
    trades_df['Entry_Date_ts'] = pd.to_datetime(trades_df['Entry_Date'])
    sort_df = trades_df.sort_values('Entry_Date_ts').copy()
    sort_df['Cumulative_PnL'] = sort_df['PnL'].cumsum()
    sort_df['Rolling_Max'] = sort_df['Cumulative_PnL'].cummax()
    sort_df['Drawdown'] = sort_df['Cumulative_PnL'] - sort_df['Rolling_Max']
    max_drawdown = sort_df['Drawdown'].min()
    
    print("\n" + "="*110)
    print(f"📊 FULL 3-YEAR BACKTEST PERFORMANCE (2023-07 to 2026-04)")
    print("="*110)
    print(f"Total Institutional Trades: {total_trades}")
    print(f"Global Net PnL (Rs):      ₹{total_pnl:,.0f}")
    print(f"Maximum Drawdown:         ₹{max_drawdown:,.0f}")
    print(f"Absolute Win Rate:        {win_rate:.1f}%")
    print(f"Average Return per Trade: ₹{avg_pnl:,.0f}")
    
    # Also print monthly breakdown
    sort_df['Month'] = sort_df['Entry_Date_ts'].dt.to_period('M')
    monthly = sort_df.groupby('Month')['PnL'].sum()
    print("\n🗓️ MONTHLY P&L BREAKDOWN:")
    print(monthly.to_string())
    
    # ── 3. PRINT INSTITUTIONAL TRADE JOURNAL ──
    print("\n" + "="*125)
    print("📈 INSTITUTIONAL F&O TRADE JOURNAL")
    print("="*125)
    print("💾 Full historical dataset exported to: fno_trade_journal.csv")
    print("\n📅 LATEST 10 ALGORITHMIC EXECUTIONS:")
    
    # Output robust line-by-line format natively exactly as requested
    header = f"{'Entry Date':<12} | {'Ticker':<10} | {'Action':<18} | {'Strike':<12} | {'Expiry':<10} | {'Entry Prem':<10} | {'Exit Date':<12} | {'Exit Prem':<10} | {'PnL':<10} | {'Reason':<15}"
    print(header)
    print("-" * len(header))
    
    for idx, row in trades_df.sort_values('Entry_Date', ascending=False).head(10).iterrows():
        print(f"{row['Entry_Date']:<12} | {row['Ticker']:<10} | {row['Action']:<18} | {row['Strike']:<12} | {row['Expiry']:<10} | ₹{row['Entry_Premium']:<9} | {row['Exit_Date']:<12} | ₹{row['Exit_Premium']:<9} | ₹{row['PnL']:<9.2f} | {row['Note']:<15}")

if __name__ == "__main__":
    run_backtest()
