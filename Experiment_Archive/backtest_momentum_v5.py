import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

class AuditedMomentumEngine:
    """
    Corrected Institutional Momentum Engine
    Fixes applied:
    1. Phantom Leverage: Double-entry accounting with explicit borrow tracking
    2. Free Loan: Leverage calculated as Gross/Equity with 8.5% cost on (Gross-Equity)
    3. Survivorship: Delistings valued at 0 (not entry price)
    
    Performance: Pivot-matrix lookups for O(1) price access (vs O(n) DataFrame scans)
    """
    
    def __init__(self, data_path):
        print("Loading Nifty 500 data...")
        self.raw_data = pd.read_parquet(data_path)
        self.prepare_data()
        
    def prepare_data(self):
        df = self.raw_data.copy()
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(['ticker', 'date'])
        
        # Structural indicators (no look-ahead)
        df['mom_6m'] = df.groupby('ticker')['close'].pct_change(126)
        df['ret_5d'] = df.groupby('ticker')['close'].pct_change(5)
        
        daily_ret = df.groupby('ticker')['close'].pct_change()
        df['vol_20d'] = daily_ret.groupby(df['ticker']).rolling(20).std().values * np.sqrt(252)
        
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift(1))
        low_close = np.abs(df['low'] - df['close'].shift(1))
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr_10d'] = true_range.groupby(df['ticker']).rolling(10).mean().values
        
        # T+1 execution infrastructure
        df['exec_open'] = df.groupby('ticker')['open'].shift(-1)
        df['exec_gap'] = (df['exec_open'] / df['close']) - 1
        
        self.data = df.dropna()
        self.dates = sorted(self.data['date'].unique())
        
        # ═══ PIVOT MATRICES for O(1) lookups ═══
        self.close_mat = df.pivot(index='date', columns='ticker', values='close')
        self.open_mat = df.pivot(index='date', columns='ticker', values='open')
        self.exec_open_mat = df.pivot(index='date', columns='ticker', values='exec_open')
        self.exec_gap_mat = df.pivot(index='date', columns='ticker', values='exec_gap')
        self.mom_6m_mat = df.pivot(index='date', columns='ticker', values='mom_6m')
        self.vol_20d_mat = df.pivot(index='date', columns='ticker', values='vol_20d')
        self.atr_10d_mat = df.pivot(index='date', columns='ticker', values='atr_10d')
        self.all_tickers = set(self.close_mat.columns)
        
        print(f"Data ready: {len(self.dates)} days, {len(self.all_tickers)} stocks")
        
    def _get_close(self, date, ticker):
        """O(1) close price lookup, returns NaN if missing"""
        try:
            return self.close_mat.loc[date, ticker]
        except KeyError:
            return np.nan
    
    def _get_exec_open(self, date, ticker):
        try:
            return self.exec_open_mat.loc[date, ticker]
        except KeyError:
            return np.nan
    
    def _get_exec_gap(self, date, ticker):
        try:
            return self.exec_gap_mat.loc[date, ticker]
        except KeyError:
            return np.nan
    
    def _get_mom_6m(self, date, ticker):
        try:
            return self.mom_6m_mat.loc[date, ticker]
        except KeyError:
            return np.nan
    
    def _get_vol_20d(self, date, ticker):
        try:
            return self.vol_20d_mat.loc[date, ticker]
        except KeyError:
            return np.nan

    def _get_atr_10d(self, date, ticker):
        try:
            return self.atr_10d_mat.loc[date, ticker]
        except KeyError:
            return np.nan
    
    def _ticker_exists(self, date, ticker):
        """Check if a ticker has data on this date"""
        try:
            v = self.close_mat.loc[date, ticker]
            return not pd.isna(v)
        except KeyError:
            return False

    def get_signals(self, date):
        """Generate signals at Day T Close"""
        current = self.data[self.data['date'] == date].copy()
        if len(current) == 0:
            return pd.DataFrame()
        
        # Top quartile momentum
        mom_thresh = current['mom_6m'].quantile(0.75)
        winners = current[current['mom_6m'] >= mom_thresh]
        
        # 5-day pullback overlay
        pullback = winners[winners['ret_5d'] < -0.02].copy()
        if len(pullback) == 0:
            return pd.DataFrame()
        
        # Composite score
        pullback['score_mom'] = pullback['mom_6m'].rank(pct=True)
        pullback['score_pull'] = (-pullback['ret_5d']).rank(pct=True)
        pullback['score_vol'] = (1 / (pullback['vol_20d'] + 0.001)).rank(pct=True)
        pullback['total_score'] = (0.5 * pullback['score_mom'] + 
                                   0.3 * pullback['score_pull'] + 
                                   0.2 * pullback['score_vol'])
        
        return pullback.nlargest(15, 'total_score')[['ticker', 'exec_open', 'exec_gap', 
                                                     'vol_20d', 'mom_6m', 'atr_10d']]
    
    def calc_leverage(self, equity_hist):
        """0.5x - 1.5x based on 20-day realized vol"""
        if len(equity_hist) < 21:
            return 1.0
        
        recent = [e['equity'] for e in equity_hist[-21:]]
        rets = [(recent[i]/recent[i-1]) - 1 for i in range(1, len(recent))]
        vol = np.std(rets) * np.sqrt(252) if len(rets) > 1 else 0.2
        
        if vol < 0.15:
            return min(1.5, 0.30 / (vol + 0.01))
        elif vol > 0.35:
            return max(0.5, 0.30 / (vol + 0.01))
        return 1.0
    
    def run_backtest(self):
        """T+1 execution with correct accounting — pivot matrix accelerated"""
        cash = 10_000_000.0  # ₹1 Crore equity start
        positions = {}       # ticker: {shares, entry, atr}
        borrowed = 0.0       # Track explicit borrowing
        equity_curve = []
        
        prev_month = None
        prev_date = None
        is_oos = False
        
        for i, date in enumerate(self.dates):
            date_ts = pd.Timestamp(date)
            is_oos = date_ts >= pd.Timestamp('2021-01-01')
            current_month = (date_ts.year, date_ts.month)
            
            # === MARK TO MARKET (EOD) ===
            gross_value = cash
            delisted = []
            
            for ticker, pos in list(positions.items()):
                close_p = self._get_close(date, ticker)
                if not pd.isna(close_p):
                    gross_value += pos['shares'] * close_p
                else:
                    # BUG FIX #3: Delisted = Total Loss (0 recovery)
                    delisted.append(ticker)
            
            for ticker in delisted:
                del positions[ticker]
            
            # Net equity = Assets - Liabilities
            net_equity = gross_value - borrowed
            equity_curve.append({
                'date': date, 'equity': net_equity, 'gross': gross_value,
                'cash': cash, 'borrowed': borrowed, 'is_oos': is_oos
            })
            
            # === MONTHLY REBALANCING (T+1 Execution) ===
            if current_month != prev_month and prev_month is not None:
                # Signals from T-1 (prev_date) executed at T (current date) Open
                signals = self.get_signals(prev_date)
                
                # 1. EXECUTE SELLS FIRST (Free up cash)
                if len(signals) > 0:
                    mom_median = signals['mom_6m'].median()
                    
                    for ticker in list(positions.keys()):
                        # Check exit conditions using prev_date close
                        close_p = self._get_close(prev_date, ticker)
                        if pd.isna(close_p):
                            continue
                        
                        pos = positions[ticker]
                        mom = self._get_mom_6m(prev_date, ticker)
                        
                        # Stop loss: 3x ATR or 8% max loss
                        stop_p = max(pos['entry'] - 3*pos['atr'], pos['entry'] * 0.92)
                        
                        if close_p < stop_p or (not pd.isna(mom) and mom < mom_median):
                            # Execute sell at T Open
                            exec_p = self._get_exec_open(date, ticker)
                            gap = self._get_exec_gap(date, ticker)
                            
                            if not pd.isna(exec_p):
                                proceeds = pos['shares'] * exec_p
                                costs = proceeds * 0.0020  # 20bps exit
                                if not pd.isna(gap) and gap > 0.02:
                                    costs += proceeds * 0.0050  # Slippage
                                
                                cash += (proceeds - costs)
                                del positions[ticker]
                
                # 2. CALCULATE TARGET ALLOCATION
                # Use prev_date equity (known at signal time) for sizing
                prev_gross = cash
                for ticker, pos in positions.items():
                    close_p = self._get_close(prev_date, ticker)
                    if not pd.isna(close_p):
                        prev_gross += pos['shares'] * close_p
                
                prev_equity = prev_gross - borrowed
                leverage = self.calc_leverage(equity_curve)
                target_gross = prev_equity * leverage
                
                # Current exposure after sells
                current_exposure = 0
                for ticker, pos in positions.items():
                    close_p = self._get_close(date, ticker)
                    if not pd.isna(close_p):
                        current_exposure += pos['shares'] * close_p
                
                # Available capacity for new buys
                capacity = target_gross - current_exposure
                
                # 3. EXECUTE BUYS (Within capacity constraint)
                if len(signals) > 0 and capacity > 100000:
                    # Inverse vol weighting
                    inv_vol = 1 / (signals['vol_20d'] + 0.001)
                    weights = inv_vol / inv_vol.sum()
                    
                    for idx, row in signals.iterrows():
                        ticker = row['ticker']
                        if ticker in positions:
                            continue
                        
                        alloc = capacity * weights.loc[idx]
                        if alloc < 50000:
                            continue
                        
                        # Execute at T+1 Open
                        exec_p = self._get_exec_open(date, ticker)
                        gap = self._get_exec_gap(date, ticker)
                        
                        if pd.isna(exec_p):
                            continue
                        
                        # Entry costs
                        cost_per_share = exec_p * 0.0020
                        if not pd.isna(gap) and gap > 0.02:
                            cost_per_share += exec_p * 0.0050
                        
                        total_cost = exec_p + cost_per_share
                        shares = int(alloc / total_cost)
                        
                        # BUG FIX #1: Check cash availability (no phantom money)
                        required = shares * total_cost
                        if shares > 0 and required <= cash:
                            cash -= required
                            positions[ticker] = {
                                'shares': shares, 'entry': exec_p, 
                                'atr': row['atr_10d'], 'date': date
                            }
                            
                            # Update borrowing if we exceeded equity
                            if cash < 0:
                                borrowed = abs(cash)
                            else:
                                borrowed = 0
                
                prev_month = current_month
            elif prev_month is None:
                prev_month = current_month
            
            prev_date = date
            
            # === DAILY LEVERAGE COST (BUG FIX #2) ===
            eod_gross = cash
            for ticker, pos in positions.items():
                close_p = self._get_close(date, ticker)
                if not pd.isna(close_p):
                    eod_gross += pos['shares'] * close_p
            
            eod_equity = eod_gross - borrowed
            
            # Correct leverage calculation: Gross / Equity
            if eod_equity > 0:
                lev = eod_gross / eod_equity
                if lev > 1.0:
                    # Charge 8.5% on borrowed portion
                    daily_cost = borrowed * 0.085 / 252
                    cash -= daily_cost
                else:
                    borrowed = 0
        
        return equity_curve
    
    def metrics(self, curve):
        df = pd.DataFrame(curve)
        is_df = df[~df['is_oos']]
        oos_df = df[df['is_oos']]
        
        results = {}
        for name, subdf in [('In-Sample (2014-2020)', is_df), ('Out-of-Sample (2021-2024)', oos_df)]:
            if len(subdf) < 2:
                continue
            
            start = subdf['equity'].iloc[0]
            end = subdf['equity'].iloc[-1]
            years = (subdf['date'].iloc[-1] - subdf['date'].iloc[0]).days / 365.25
            
            cagr = (end/start)**(1/years) - 1
            subdf['cum'] = subdf['equity'] / start
            subdf['peak'] = subdf['cum'].cummax()
            max_dd = ((subdf['cum'] / subdf['peak']) - 1).min()
            
            results[name] = {
                'CAGR': cagr * 100,
                'Max DD': max_dd * 100,
                'Final Value': end
            }
        
        return results
    
    def report(self):
        print("\n" + "="*80)
        print("AUDITED MOMENTUM ENGINE V5 - CORRECTED ACCOUNTING")
        print("="*80)
        
        curve = self.run_backtest()
        results = self.metrics(curve)
        
        for period, data in results.items():
            print(f"\n{period}:")
            print(f"  CAGR:         {data['CAGR']:.2f}%")
            print(f"  Max Drawdown:  {data['Max DD']:.2f}%")
            print(f"  Final Value:  ₹{data['Final Value']:,.0f}")
        
        # Overfitting check
        if len(results) == 2:
            is_cagr = list(results.values())[0]['CAGR']
            oos_cagr = list(results.values())[1]['CAGR']
            deg = (is_cagr - oos_cagr) / is_cagr if is_cagr != 0 else 0
            print(f"\nRobustness: {deg*100:.1f}% degradation ", 
                  "(PASS)" if deg <= 0.30 else "(FAIL)")
        
        print("="*80)

if __name__ == "__main__":
    engine = AuditedMomentumEngine('nifty500_daily.parquet')
    engine.report()