"""
NSE Pure Alpha Generator — v5.0 (Fundamental + Trend Filters)
=============================================================

NEW IN v5.0 — FUNDAMENTAL + TREND FILTERS:

  Layer 0A — Fundamental Filter (FundamentalFilter class):
    CSV-based quarterly blacklist.  Stocks failing ANY of 15 fundamental
    health checks are removed from the universe BEFORE signal generation.
    Rules cover: profitability (ROE/ROCE), leverage, promoter quality,
    audit flags, and sector-specific rules (NPA/CAR for financials,
    DebtEquity/ICR for non-financials).  Updated quarterly.

  Layer 0B — Trend Filter (TrendFilter class):
    Dynamic price-based gate.  Blocks stocks in confirmed downtrends:
    below 200/50 SMA, 12M return < -20%, or caught in sector-wide
    collapse.  Fully dynamic — recovers automatically.  Protects
    existing open positions (never forces exit).

NEW IN v4.0 — HOLDING DURATION & EXIT MANAGEMENT:

  PositionTracker class remembers every open position and evaluates
  exit conditions on each rebalance before generating new entries.

  Exit rules by signal type
  -------------------------
  MEAN REVERSION (long or short futures):
    - PRIMARY : Exit when z-score crosses back through 0 (thesis complete).
    - TIME STOP: Force exit after MAX_MR_DAYS (default 15 trading days).
    - LOSS STOP: Hard stop at STOP_LOSS_MR (default -3 %) vs entry price.

  PAIRS TRADING (long one leg, short futures the other):
    - PRIMARY : Exit both legs when spread z-score < EXIT_PAIRS_Z (default 0.5).
    - TIME STOP: Force exit after MAX_PAIRS_DAYS (default 30 trading days).
    - LOSS STOP: Hard stop at STOP_LOSS_PAIRS (default -4 %) on the spread P&L.

  RESIDUAL MOMENTUM (long winners, short futures of losers):
    - MINIMUM HOLD: Do NOT exit before MIN_MOM_DAYS (default 21 trading days).
    - PRIMARY : Exit when 12-1 month rank drops out of top/bottom decile.
    - LOSS STOP: Hard stop at STOP_LOSS_MOM (default -5 %).

  All thresholds are module-level constants — tune them at the top of this file.

INHERITED FROM v3.0:
  - F&O universe restriction (shorts via futures only).
  - Rupee-volume liquidity filter.
  - FIX-1 through FIX-6 (see v3.0 changelog).
"""

import warnings
import os
import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass, field
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.tsa.stattools import coint
from typing import Dict, List, Optional, Tuple
from sklearn.ensemble import RandomForestClassifier


# =============================================================================
# EXIT / HOLDING THRESHOLDS  ← tune these without touching the class logic
# =============================================================================

# Mean reversion
MAX_MR_DAYS      = 15      # force-exit after N trading days with no reversion
STOP_LOSS_MR     = -0.03   # -3 % hard stop on position P&L

# Pairs trading
MAX_PAIRS_DAYS   = 30      # force-exit after N trading days
EXIT_PAIRS_Z     = 0.50    # exit when |spread z| falls below this (partial reversion)
STOP_LOSS_PAIRS  = -0.04   # -4 % hard stop on spread P&L

# Residual momentum
MIN_MOM_DAYS     = 21      # do NOT touch momentum positions before this
STOP_LOSS_MOM    = -0.05   # -5 % hard stop


# =============================================================================
# F&O ELIGIBLE UNIVERSE
# =============================================================================

FNO_ELIGIBLE = {
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN", "BANKBARODA",
    "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "HDFCLIFE", "SBILIFE", "ICICIGI",
    "PNB", "FEDERALBNK", "IDFCFIRSTB", "BANDHANBNK", "CANBK", "INDUSINDBK",
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS",
    "COFORGE", "PERSISTENT", "LTTS",
    "RELIANCE", "ONGC", "NTPC", "POWERGRID", "ADANIGREEN", "TATAPOWER",
    "BPCL", "IOC", "GAIL", "PETRONET", "ADANIPORTS",
    "MARUTI", "TATAMOTORS", "M&M", "HEROMOTOCO", "BAJAJ-AUTO", "EICHERMOT",
    "ASHOKLEY", "TVSMOTOR", "BOSCHLTD", "MOTHERSON",
    "SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "DIVISLAB", "BIOCON",
    "AUROPHARMA", "ALKEM", "TORNTPHARM", "APLLTD",
    "HINDUNILVR", "ITC", "DABUR", "NESTLEIND", "GODREJCP", "BRITANNIA",
    "MARICO", "COLPAL", "TATACONSUM", "VBL",
    "TATASTEEL", "HINDALCO", "JSWSTEEL", "COALINDIA", "NMDC", "VEDL",
    "SAIL", "NATIONALUM",
    "ULTRACEMCO", "AMBUJACEM", "ACC", "SHREECEM", "RAMCOCEM",
    "BHARTIARTL", "IDEA", "ZEEL",
    "LT", "GODREJPROP", "DLF", "OBEROIREALTY", "PRESTIGE",
    "ASIANPAINT", "BERGER", "TITAN", "JUBLFOOD", "INDIAMART",
    "PIDILITIND", "SIEMENS", "ABB", "HAVELLS", "VOLTAS",
}

FNO_LOT_SIZES: Dict[str, int] = {
    "RELIANCE": 250, "HDFCBANK": 550, "ICICIBANK": 1375, "INFY": 400,
    "TCS": 150, "KOTAKBANK": 400, "AXISBANK": 1200, "SBIN": 1500,
    "BAJFINANCE": 125, "TATAMOTORS": 1425, "SUNPHARMA": 700, "MARUTI": 100,
    "NTPC": 3750, "ONGC": 1925, "WIPRO": 1600, "HCLTECH": 700,
    "LTIM": 150, "HINDALCO": 2150, "TATASTEEL": 5500, "JSWSTEEL": 675,
    "HINDUNILVR": 300, "ITC": 3200, "BHARTIARTL": 950, "ULTRACEMCO": 100,
    "TECHM": 600, "DRREDDY": 125, "CIPLA": 650,
}
DEFAULT_LOT_SIZE = 500


# =============================================================================
# HELPERS
# =============================================================================

def _safe_mad(series: pd.Series) -> float:
    median = series.median()
    mad    = (series - median).abs().median()
    return float(mad) if mad != 0 else float(series.std())


def _annualisation_factor(freq: str) -> int:
    _map = {
        "D": 252, "B": 252,
        "W": 52, "W-MON": 52, "W-FRI": 52,
        "M": 12, "MS": 12, "BM": 12, "BMS": 12,
        "Q": 4,  "QS": 4,
    }
    return _map.get(freq, 52)


# =============================================================================
# POSITION TRACKER
# =============================================================================

@dataclass
class OpenPosition:
    """Single open position record."""
    ticker      : str
    signal_type : str               # 'mean_reversion' | 'pairs_long' | 'pairs_short'
                                    # | 'residual_momentum'
    direction   : int               # +1 = long cash/futures, -1 = short futures
    entry_date  : pd.Timestamp
    entry_price : float             # adjusted close at entry
    entry_z     : float             # z-score at entry (signed)
    size        : float             # fraction of NAV
    pair_partner: Optional[str] = None   # for pairs positions only
    days_held   : int = 0


class PositionTracker:
    """
    Stateful book of open positions.

    On each rebalance date the backtester / live runner calls:
      1. tracker.update_days(current_prices)  — age all positions by 1 period
      2. tracker.evaluate_exits(...)           — apply exit rules, returns tickers to close
      3. tracker.open_new(signals, ...)        — add new entries that don't overlap existing
      4. tracker.current_book()               — get active positions as a Series

    Design note
    -----------
    The tracker stores positions in a plain dict so it can be pickled / serialised
    between live-trading sessions without any database dependency.
    """

    def __init__(self):
        self._book: Dict[str, OpenPosition] = {} 

    # ------------------------------------------------------------------
    # BOOK MANAGEMENT
    # ------------------------------------------------------------------

    def open_position(self, pos: OpenPosition) -> None:
        """Add a new position.  Overwrites if ticker already exists (re-entry)."""
        self._book[pos.ticker] = pos

    def close_position(self, ticker: str) -> Optional[OpenPosition]:
        """Remove and return a position, or None if not found."""
        return self._book.pop(ticker, None)

    def is_open(self, ticker: str) -> bool:
        return ticker in self._book

    def current_book(self) -> Dict[str, OpenPosition]:
        return dict(self._book)

    def active_tickers(self) -> List[str]:
        return list(self._book.keys())

    # ------------------------------------------------------------------
    # AGEING
    # ------------------------------------------------------------------

    def increment_days(self) -> None:
        """Call once per trading day (or once per rebalance period)."""
        for pos in self._book.values():
            pos.days_held += 1

    # ------------------------------------------------------------------
    # EXIT EVALUATION  ← core logic
    # ------------------------------------------------------------------

    def evaluate_exits(
        self,
        current_prices   : pd.Series,          # ticker → today's close
        current_z_scores : pd.Series,          # ticker → today's z-score (signed)
        spread_z_scores  : Optional[Dict[str, float]] = None,  # pair_key → spread z
    ) -> List[Tuple[str, str]]:
        """
        Check every open position against its exit rules.

        Returns
        -------
        List of (ticker, reason) tuples for positions that should be closed.
        Caller is responsible for calling self.close_position() after acting.

        Exit reasons
        ------------
        'z_reversal'   : z-score crossed zero — mean reversion complete.
        'time_stop'    : held too long without the thesis playing out.
        'loss_stop'    : hard stop-loss triggered.
        'mom_exit'     : momentum rank degraded out of signal decile.
        'spread_close' : pairs spread reverted to within EXIT_PAIRS_Z.
        'min_hold'     : momentum position not yet old enough to exit (blocked).
        """
        exits = []

        for ticker, pos in self._book.items():
            if ticker not in current_prices.index:
                exits.append((ticker, "delisted_or_missing"))
                continue

            current_price = current_prices[ticker]
            pnl           = (current_price / pos.entry_price - 1) * pos.direction

            # ── MEAN REVERSION exits ────────────────────────────────────────
            if pos.signal_type == "mean_reversion":

                current_z = current_z_scores.get(ticker, np.nan)

                # Primary: z crossed zero → reversion complete
                if not np.isnan(current_z):
                    if pos.entry_z * current_z < 0:   # sign flip
                        exits.append((ticker, "z_reversal"))
                        continue

                # Time stop
                if pos.days_held >= MAX_MR_DAYS:
                    exits.append((ticker, "time_stop"))
                    continue

                # Loss stop
                if pnl <= STOP_LOSS_MR:
                    exits.append((ticker, "loss_stop"))
                    continue

            # ── PAIRS exits ─────────────────────────────────────────────────
            elif pos.signal_type in ("pairs_long", "pairs_short"):

                # Spread z check (if caller provided it)
                if spread_z_scores and pos.pair_partner:
                    pair_key = tuple(sorted([ticker, pos.pair_partner]))
                    sz = spread_z_scores.get(pair_key, None)
                    if sz is not None and abs(sz) < EXIT_PAIRS_Z:
                        exits.append((ticker, "spread_close"))
                        continue

                # Time stop
                if pos.days_held >= MAX_PAIRS_DAYS:
                    exits.append((ticker, "time_stop"))
                    continue

                # Loss stop
                if pnl <= STOP_LOSS_PAIRS:
                    exits.append((ticker, "loss_stop"))
                    continue

            # ── RESIDUAL MOMENTUM exits ──────────────────────────────────────
            elif pos.signal_type == "residual_momentum":

                # Minimum hold — do NOT exit early (avoids churn)
                if pos.days_held < MIN_MOM_DAYS:
                    continue   # blocked — not an exit, just skip

                current_z = current_z_scores.get(ticker, np.nan)

                # Exit when momentum rank degrades (z crosses zero)
                if not np.isnan(current_z):
                    if pos.entry_z * current_z < 0:
                        exits.append((ticker, "mom_exit"))
                        continue

                # Loss stop (wider for momentum — normal to have drawdowns)
                if pnl <= STOP_LOSS_MOM:
                    exits.append((ticker, "loss_stop"))
                    continue

        return exits

    # ------------------------------------------------------------------
    # OPEN NEW POSITIONS FROM SIGNAL OUTPUT
    # ------------------------------------------------------------------

    def open_new_from_signals(
        self,
        signals       : pd.DataFrame,   # output of NSEAlphaGenerator.generate_signals()
        current_prices: pd.Series,       # ticker → today's close
        date          : pd.Timestamp,
    ) -> List[str]:
        """
        Add new positions from the latest signal DataFrame,
        skipping tickers that already have an open position.

        Returns list of tickers that were newly opened.
        """
        opened = []

        for ticker in signals.index:
            pos_size = signals.loc[ticker, "hedged_position"]
            sig_type = signals.loc[ticker, "signal_type"]
            z_score  = signals.loc[ticker, "z_score"]

            if abs(pos_size) < 0.001:
                continue   # no signal

            if self.is_open(ticker):
                continue   # already have a position — let exit logic handle it

            if ticker not in current_prices.index:
                continue

            direction = 1 if pos_size > 0 else -1

            # Resolve pair partner for pairs signals
            partner = None
            if "pairs" in str(sig_type):
                partner = signals.loc[ticker, "hedge_ratio"]   # stored separately

            self.open_position(OpenPosition(
                ticker       = ticker,
                signal_type  = sig_type if sig_type != "" else "mean_reversion",
                direction    = direction,
                entry_date   = date,
                entry_price  = float(current_prices[ticker]),
                entry_z      = float(z_score) * direction,   # signed by direction
                size         = float(abs(pos_size)),
                pair_partner = partner,
                days_held    = 0,
            ))
            opened.append(ticker)

        return opened

    # ------------------------------------------------------------------
    # DIAGNOSTICS
    # ------------------------------------------------------------------

    def summary(self) -> pd.DataFrame:
        """Return current book as a readable DataFrame."""
        if not self._book:
            return pd.DataFrame(columns=[
                "ticker", "signal_type", "direction", "entry_date",
                "days_held", "size", "entry_z",
            ])
        rows = []
        for ticker, pos in self._book.items():
            rows.append({
                "ticker"      : ticker,
                "signal_type" : pos.signal_type,
                "direction"   : "LONG" if pos.direction == 1 else "SHORT FUT",
                "entry_date"  : pos.entry_date.date(),
                "days_held"   : pos.days_held,
                "size"        : round(pos.size, 4),
                "entry_z"     : round(pos.entry_z, 2),
                "pair_partner": pos.pair_partner or "",
            })
        return pd.DataFrame(rows).sort_values("signal_type")


# =============================================================================
# FUNDAMENTAL FILTER (v5.0) — CSV-based quarterly blacklist
# =============================================================================

class FundamentalFilter:
    """
    Layer 0A — Fundamental Health Gate.

    Blacklists stocks that fail ANY of 15 fundamental quality checks.
    Data loaded from a CSV updated quarterly (Jan, Apr, Jul, Oct).

    Rules 1-11 : All stocks
    Rules 12-13: Non-finance only (DebtEquity, ICR)
    Rules 14-15: Finance only  (GrossNPA, CAR)

    Finance sector is determined from the IsFinanceSector column in the CSV,
    NOT hardcoded — so it adapts automatically when the NIFTY 500 changes.
    """

    def __init__(self, csv_path: str = "fundamental_filter.csv"):
        self._csv_path = csv_path
        self._data: Optional[pd.DataFrame] = None
        self._blacklist: set = set()

        if os.path.exists(csv_path):
            self._data = pd.read_csv(csv_path)
            self._blacklist = self._build_blacklist()
            bl_list = sorted(self._blacklist)
            bl_str  = ", ".join(bl_list[:10])
            extra   = f" ... and {len(bl_list) - 10} others" if len(bl_list) > 10 else ""
            print(f"  [FUND FILTER] Loaded {len(self._data)} stocks | "
                  f"{len(self._blacklist)} blacklisted: [{bl_str}{extra}]")
        else:
            warnings.warn(
                f"[FUND FILTER] '{csv_path}' not found — filter disabled.",
                UserWarning, stacklevel=2,
            )

    def _build_blacklist(self) -> set:
        """Apply all 15 fundamental rules. Return set of blacklisted tickers."""
        if self._data is None or self._data.empty:
            return set()

        blacklisted = set()
        df = self._data

        for _, row in df.iterrows():
            ticker = str(row.get("Ticker", ""))
            if not ticker:
                continue

            is_finance = bool(row.get("IsFinanceSector", False))

            # --- Rules 1-11: ALL STOCKS ---
            if row.get("NetProfitNegative", False) is True:
                blacklisted.add(ticker); continue
            if row.get("EBITDA_Negative", False) is True:
                blacklisted.add(ticker); continue
            if float(row.get("ROE", 999)) < 8.0:
                blacklisted.add(ticker); continue
            if float(row.get("ROCE", 999)) < 10.0:
                blacklisted.add(ticker); continue
            if row.get("RevenueDecline2Yr", False) is True:
                blacklisted.add(ticker); continue
            if float(row.get("PromoterHolding", 100)) < 25.0:
                blacklisted.add(ticker); continue
            if float(row.get("PromoterPledge", 0)) > 20.0:
                blacklisted.add(ticker); continue
            if row.get("PledgeIncreasing3Qtrs", False) is True:
                blacklisted.add(ticker); continue
            if float(row.get("MarketCap_Cr", 99999)) < 500:
                blacklisted.add(ticker); continue
            if row.get("AuditorFlag", False) is True:
                blacklisted.add(ticker); continue
            if row.get("PromoterSelling", False) is True:
                blacklisted.add(ticker); continue

            # --- Rules 12-13: NON-FINANCE ONLY ---
            if not is_finance:
                if float(row.get("DebtEquity", 0)) > 1.5:
                    blacklisted.add(ticker); continue
                if float(row.get("ICR", 999)) < 1.5:
                    blacklisted.add(ticker); continue

            # --- Rules 14-15: FINANCE ONLY ---
            if is_finance:
                if float(row.get("GrossNPA_Pct", 0)) > 5.0:
                    blacklisted.add(ticker); continue
                if float(row.get("CAR_Pct", 999)) < 12.0:
                    blacklisted.add(ticker); continue

        return blacklisted

    def is_blacklisted(self, ticker: str) -> bool:
        return ticker in self._blacklist

    def get_blacklisted_tickers(self) -> List[str]:
        return sorted(list(self._blacklist))

    def reload(self) -> None:
        """Reload CSV from disk and rebuild blacklist. Call quarterly."""
        if os.path.exists(self._csv_path):
            self._data = pd.read_csv(self._csv_path)
            self._blacklist = self._build_blacklist()
            bl_list = sorted(self._blacklist)
            bl_str  = ", ".join(bl_list[:10])
            extra   = f" ... and {len(bl_list) - 10} others" if len(bl_list) > 10 else ""
            print(f"  [FUND FILTER] Reloaded | "
                  f"{len(self._blacklist)} blacklisted: [{bl_str}{extra}]")
        else:
            warnings.warn(
                f"[FUND FILTER] '{self._csv_path}' not found on reload.",
                UserWarning, stacklevel=2,
            )

    @staticmethod
    def _is_quarter_start(date: pd.Timestamp) -> bool:
        """True in the first week of Jan/Apr/Jul/Oct — triggers auto-reload."""
        return date.month in (1, 4, 7, 10) and date.day <= 7


# =============================================================================
# TREND FILTER (v5.0) — Dynamic price-based blocking
# =============================================================================

class TrendFilter:
    """
    Layer 0B — Dynamic Trend Gate.

    Blocks stocks in confirmed downtrends from receiving NEW signals.
    Fully dynamic: stock recovers → automatically eligible again.

    Block conditions (ANY ONE triggers block):
      1. Price < 200 SMA
      2. Price < 50 SMA
      3. 12-month return < -20 % (252 trading days)
      4. Sector avg 12M return < -15 % AND stock 12M return < -10 %
      5. Fewer than 200 trading days of history
    """

    @staticmethod
    def _truncate_list(items: list, limit: int = 10) -> str:
        s = ", ".join(items[:limit])
        if len(items) > limit:
            s += f" ... and {len(items) - limit} others"
        return s

    def get_blocked_tickers(
        self,
        prices: pd.DataFrame,
        sector_map: Dict,
        date: pd.Timestamp,
        full_universe_prices: pd.DataFrame,
    ) -> set:
        """
        Compute trend-blocked tickers.

        Parameters
        ----------
        prices : post-fundamental-filter prices (for SMA / return checks)
        sector_map : ticker → sector name
        date : current signal date
        full_universe_prices : FULL F&O prices before fundamental filter
            (for accurate sector average calculation)
        """
        blocked = set()

        # --- Sector averages from FULL universe (prevents bias) ---
        sector_12m_avg: Dict[str, float] = {}
        if len(full_universe_prices) >= 252:
            full_current  = full_universe_prices.iloc[-1]
            full_past     = full_universe_prices.iloc[-252]
            full_12m_ret  = (full_current / full_past - 1).dropna()

            sector_returns: Dict[str, list] = {}
            for stock in full_12m_ret.index:
                sec = sector_map.get(stock, "Other")
                sector_returns.setdefault(sec, []).append(full_12m_ret[stock])

            for sec, rets in sector_returns.items():
                sector_12m_avg[sec] = float(np.mean(rets))

        # --- Per-stock checks ---
        for stock in prices.columns:
            price_series = prices[stock].dropna()
            n = len(price_series)

            # Rule 5: insufficient history
            if n < 200:
                blocked.add(stock)
                continue

            current_price = price_series.iloc[-1]

            # Rule 1: price < 200 SMA
            sma200 = price_series.rolling(200).mean().iloc[-1]
            if not np.isnan(sma200) and current_price < sma200:
                blocked.add(stock)
                continue

            # Rule 2: price < 50 SMA
            sma50 = price_series.rolling(50).mean().iloc[-1]
            if not np.isnan(sma50) and current_price < sma50:
                blocked.add(stock)
                continue

            # Rule 3: 12-month return < -20%
            if n >= 252:
                ret_12m = current_price / price_series.iloc[-252] - 1
                if ret_12m < -0.20:
                    blocked.add(stock)
                    continue

                # Rule 4: sector collapse + stock weakness
                sec = sector_map.get(stock, "Other")
                sec_avg = sector_12m_avg.get(sec, 0.0)
                if sec_avg < -0.15 and ret_12m < -0.10:
                    blocked.add(stock)
                    continue

        bl_sorted = sorted(blocked)
        print(f"  [TREND FILTER] {len(blocked)} stocks blocked: "
              f"[{self._truncate_list(bl_sorted)}]")

        return blocked


# =============================================================================
# SIGNAL QUALITY FILTER (v6.0) — RF + Volume Confirmation
# =============================================================================

class SignalQualityFilter:
    """
    Layer 1 Signal Quality Gate.

    Random Forest Filter:
        Predicts P(reversion) for mean reversion signals using a walk-forward
        trained classifier on 8 technical features.  Blocks entries where
        confidence < RF_CONFIDENCE_THRESH (default 55 %).

    Volume Confirmation (mean reversion only):
        Blocks entries where current volume < VOL_RATIO_THRESH × 20-day avg.

    Walk-forward:
        Train on 504-day rolling window, retrain every 52 rebalances.
        class_weight='balanced' handles reversion class imbalance.
    """

    RF_MIN_SAMPLES        = 100
    RF_CONFIDENCE_THRESH  = 0.55
    VOL_RATIO_THRESH      = 1.30
    TRAIN_WINDOW_DAYS     = 504
    RETRAIN_EVERY_PERIODS = 52
    LABEL_HORIZON_DAYS    = 15

    FEATURE_NAMES = [
        "abs_z", "z_velocity", "resid_vol", "beta",
        "r_squared", "rsi_resid", "vol_ratio", "spread_5d",
    ]

    def __init__(self):
        self._model: Optional[RandomForestClassifier] = None
        self._is_trained: bool = False
        self._periods_since_train: int = 999  # force first train

    # ----- helpers ----------------------------------------------------------

    @staticmethod
    def _rsi_series(series: pd.Series, window: int = 14) -> pd.Series:
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(window).mean()
        loss  = (-delta.clip(upper=0)).rolling(window).mean()
        rs    = gain / (loss + 1e-10)
        return 100.0 - 100.0 / (1.0 + rs)

    # ----- training data construction ---------------------------------------

    def _build_training_data(
        self,
        residuals: pd.DataFrame,
        betas: Dict,
        volume_df: Optional[pd.DataFrame],
        z_entry: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Scan residuals at 5-day intervals.  For each stock with |z| > z_entry,
        build 8 features and label (did residual revert within 15 days?).
        """
        n       = len(residuals)
        max_t   = n - self.LABEL_HORIZON_DAYS - 1
        start_t = max(25, n - self.TRAIN_WINDOW_DAYS)
        if max_t <= start_t:
            return np.empty((0, 8)), np.empty(0)

        # Pre-compute RSI for all stocks
        rsi_cache = {s: self._rsi_series(residuals[s]).values for s in residuals.columns}

        # Align volume
        vol_al = None
        if volume_df is not None:
            cc = residuals.columns.intersection(volume_df.columns)
            vol_al = volume_df.reindex(index=residuals.index, columns=cc)

        X_rows: list = []
        y_rows: list = []

        for t in range(start_t, max_t, 5):
            form   = residuals.iloc[max(0, t - 4): t + 1].sum()
            median = form.median()
            mad    = _safe_mad(form)
            if mad == 0:
                continue
            z_all = (form - median) / (1.4826 * mad)

            # previous z for velocity
            if t >= 10:
                pf   = residuals.iloc[max(0, t - 9): t - 4].sum()
                pm   = pf.median()
                pmad = _safe_mad(pf)
                pz   = (pf - pm) / (1.4826 * pmad) if pmad != 0 else z_all * 0
            else:
                pz = z_all * 0

            for stock in residuals.columns:
                z = float(z_all.get(stock, 0))
                if abs(z) < z_entry or stock not in betas:
                    continue

                z_vel = z - float(pz.get(stock, 0))
                rv    = betas[stock]["resid_vol"]
                b     = betas[stock]["beta"]
                rsq   = betas[stock]["r_squared"]

                rsi_v = 50.0
                if stock in rsi_cache and t < len(rsi_cache[stock]):
                    _r = float(rsi_cache[stock][t])
                    if not np.isnan(_r):
                        rsi_v = _r

                vr = 1.0
                if vol_al is not None and stock in vol_al.columns and t >= 20:
                    av = vol_al[stock].iloc[t - 19: t + 1].mean()
                    cv = vol_al[stock].iloc[t]
                    if av > 0 and not np.isnan(cv) and not np.isnan(av):
                        vr = cv / av

                s5d = float(form.get(stock, 0))
                X_rows.append([abs(z), z_vel, rv, b, rsq, rsi_v, vr, s5d])

                # Label: reversion = future residual opposite sign to z
                future = residuals[stock].iloc[t + 1: t + 1 + self.LABEL_HORIZON_DAYS].sum()
                reverted = 1 if (z > 0 and future < 0) or (z < 0 and future > 0) else 0
                y_rows.append(reverted)

        if not X_rows:
            return np.empty((0, 8)), np.empty(0)
        return np.array(X_rows), np.array(y_rows)

    # ----- model training ---------------------------------------------------

    def train(self, residuals, betas, volume_df, z_entry) -> bool:
        X, y = self._build_training_data(residuals, betas, volume_df, z_entry)
        if len(X) < self.RF_MIN_SAMPLES:
            print(f"  [RF] Skip: {len(X)} samples < {self.RF_MIN_SAMPLES}")
            return False

        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        self._model = RandomForestClassifier(
            n_estimators=200, max_depth=5, min_samples_leaf=10,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
        self._model.fit(X, y)
        self._is_trained = True
        self._periods_since_train = 0

        acc  = self._model.score(X, y)
        dist = {0: int((y == 0).sum()), 1: int((y == 1).sum())}
        imp  = dict(zip(self.FEATURE_NAMES, self._model.feature_importances_))
        top  = sorted(imp.items(), key=lambda x: -x[1])[:3]
        print(f"  [RF] Trained: {len(X)} samples | acc={acc:.1%} | {dist}")
        print(f"  [RF] Top: {', '.join(f'{k}={v:.2f}' for k, v in top)}")
        return True

    # ----- prediction features for current date -----------------------------

    def _features_for_stock(self, stock, cs_z, residuals, betas, volume_df):
        """Build 1×8 feature vector for one stock at the latest date."""
        if stock not in betas or stock not in residuals.columns:
            return None
        resid = residuals[stock]
        n = len(resid)
        if n < 20:
            return None

        # z_velocity
        if n >= 10:
            all_cur  = residuals.iloc[-5:].sum()
            all_prev = residuals.iloc[-10:-5].sum()
            mc, madc = all_cur.median(), _safe_mad(all_cur)
            mp, madp = all_prev.median(), _safe_mad(all_prev)
            zc = (resid.iloc[-5:].sum() - mc) / (1.4826 * madc) if madc else cs_z
            zp = (resid.iloc[-10:-5].sum() - mp) / (1.4826 * madp) if madp else 0
            z_vel = zc - zp
        else:
            z_vel = 0.0

        rsi_s  = self._rsi_series(resid)
        rsi_v  = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50.0

        vr = 1.0
        if volume_df is not None and stock in volume_df.columns:
            vd = volume_df[stock].reindex(residuals.index)
            if n >= 20:
                av = vd.iloc[-20:].mean()
                cv = vd.iloc[-1]
                if av > 0 and not np.isnan(cv) and not np.isnan(av):
                    vr = cv / av

        s5d = float(resid.iloc[-5:].sum())
        row = np.array([[
            abs(cs_z), z_vel,
            betas[stock]["resid_vol"], betas[stock]["beta"],
            betas[stock]["r_squared"], rsi_v, vr, s5d,
        ]])
        return np.nan_to_num(row, nan=0.0, posinf=0.0, neginf=0.0)

    # ----- master filter entry point ----------------------------------------

    def filter_signals(self, raw_signals, residuals, betas, volume_df, z_entry):
        """
        Apply RF + Volume filters to raw_signals (in-place).
        Called from NSEAlphaGenerator.generate_signals() after combining.
        """
        self._periods_since_train += 1
        if not self._is_trained or self._periods_since_train >= self.RETRAIN_EVERY_PERIODS:
            self.train(residuals, betas, volume_df, z_entry)

        raw_signals["rf_confidence"] = 1.0
        raw_signals["vol_ratio_live"] = 1.0

        rf_blocked  = 0
        vol_blocked = 0

        for stock in raw_signals.index:
            sig_type = raw_signals.loc[stock, "signal_type"]
            pos      = raw_signals.loc[stock, "hedged_position"]
            if abs(pos) < 0.001 or sig_type != "mean_reversion":
                continue

            # ── Volume filter ──────────────────────────────────────────
            if volume_df is not None and stock in volume_df.columns:
                vd = volume_df[stock].reindex(residuals.index)
                if len(vd) >= 20:
                    av = vd.iloc[-20:].mean()
                    cv = vd.iloc[-1]
                    if av > 0 and not np.isnan(cv) and not np.isnan(av):
                        vr = cv / av
                        raw_signals.loc[stock, "vol_ratio_live"] = round(vr, 2)
                        if vr < self.VOL_RATIO_THRESH:
                            raw_signals.loc[stock, "hedged_position"] = 0.0
                            vol_blocked += 1
                            continue

            # ── RF filter ──────────────────────────────────────────────
            if self._is_trained:
                cs_z = (
                    raw_signals.loc[stock, "cs_z"]
                    if "cs_z" in raw_signals.columns
                    else raw_signals.loc[stock, "z_score"]
                )
                feat = self._features_for_stock(stock, cs_z, residuals, betas, volume_df)
                if feat is not None:
                    proba = self._model.predict_proba(feat)[0]
                    conf  = proba[1] if len(proba) > 1 else proba[0]
                    raw_signals.loc[stock, "rf_confidence"] = round(conf, 3)
                    if conf < self.RF_CONFIDENCE_THRESH:
                        raw_signals.loc[stock, "hedged_position"] = 0.0
                        rf_blocked += 1

        n_mr = ((raw_signals["signal_type"] == "mean_reversion") &
                (raw_signals["hedged_position"].abs() > 0.001)).sum()
        print(f"  [FILTER] MR signals passed: {n_mr} | "
              f"RF blocked: {rf_blocked} | Vol blocked: {vol_blocked}")
        return raw_signals


# =============================================================================
# CORE ALPHA GENERATOR
# =============================================================================

class NSEAlphaGenerator:
    """
    Production-Grade Pure Alpha Generator — NSE F&O Edition.

    Negative `hedged_position` → SHORT THE FUTURES CONTRACT (not cash stock).

    New in v4.0: generate_signals() now accepts an optional `tracker` argument.
    When provided, the tracker's open positions are carried forward (with exit
    rules applied) and new entries are added on top.
    """

    ROLL_COST_MONTHLY = 0.003
    ROLL_COST_DAILY   = ROLL_COST_MONTHLY / 21

    def __init__(
        self,
        lookback_window    : int   = 252,
        min_liquidity_rank : int   = 200,
        zscore_threshold   : float = 2.0,
        max_position_size  : float = 0.03,
        transaction_cost   : float = 0.0010,
        sector_mapping     : Optional[Dict] = None,
        max_sector_exposure: float = 0.25,
        signal_filter      : Optional[SignalQualityFilter] = None,
        fundamental_filter : Optional[FundamentalFilter] = None,
        trend_filter       : Optional[TrendFilter] = None,
    ):
        self.lookback       = lookback_window
        self.liq_rank       = min_liquidity_rank
        self.z_entry        = zscore_threshold
        self.max_pos        = max_position_size
        self.tcost          = transaction_cost
        self.sector_map     = sector_mapping or {}
        self.max_sector_exp = max_sector_exposure
        self._signal_filter       = signal_filter
        self._fundamental_filter  = fundamental_filter
        self._trend_filter        = trend_filter

        self._fitted_params : Dict = {}
        self._hedge_ratios  : Dict = {}
        self._last_signals  : Optional[pd.DataFrame] = None

        # Spread z-scores from last cointegration run (shared with tracker)
        self._last_spread_zs: Dict[Tuple, float] = {}

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def generate_signals(
        self,
        price_df     : pd.DataFrame,
        benchmark_df : pd.DataFrame,
        volume_df    : Optional[pd.DataFrame] = None,
        date         : Optional[pd.Timestamp]  = None,
        tracker      : Optional[PositionTracker] = None,
        long_only    : bool = False,
    ) -> pd.DataFrame:
        """
        Generate alpha signals, optionally integrated with a PositionTracker.

        When `tracker` is supplied:
          1. Existing open positions are aged by 1 period.
          2. Exit rules are evaluated — positions that should close are zeroed.
          3. New entries are added for signals without an existing position.
          4. Output DataFrame reflects the combined (carry + new) portfolio.

        Without `tracker`: behaves identically to v3.0 (stateless).

        Output columns
        --------------
        hedged_position : >0 long cash/futures  |  <0 SHORT FUTURES
        signal_type     : source module
        z_score         : master z (max of components)
        liquidity_score : rupee-volume percentile
        beta_exposure   : portfolio beta after neutralisation
        is_fno          : always True (universe is F&O-only)
        effective_tcost : one-way cost incl. roll for shorts
        exit_reason     : populated when a position was closed this period
        days_held       : age of position (from tracker); 0 for new entries
        """

        if date is None:
            date = price_df.index[-1]

        # ------------------------------------------------------------------
        # 1. DATA PREP
        # ------------------------------------------------------------------
        tail          = int(self.lookback * 1.5)
        prices        = price_df.loc[:date].iloc[-tail:].copy()
        benchmarks    = benchmark_df.loc[:date].iloc[-tail:].copy()

        if len(prices) < self.lookback:
            raise ValueError(
                f"Insufficient history to {date}: "
                f"{len(prices)} rows < {self.lookback} required."
            )

        # ------------------------------------------------------------------
        # 1A. FUNDAMENTAL FILTER (v5.0)
        # ------------------------------------------------------------------
        # Start with FULL NIFTY 500 universe for LONG signals.
        # Shorts restricted to FNO_ELIGIBLE later (need futures to short).
        universe_cols = list(prices.columns)

        if self._fundamental_filter is not None:
            # Auto-reload at quarter start (Jan/Apr/Jul/Oct first week)
            if FundamentalFilter._is_quarter_start(date):
                self._fundamental_filter.reload()

            fundamentally_blocked = set(self._fundamental_filter.get_blacklisted_tickers())
            pre_count     = len(universe_cols)
            universe_cols = [c for c in universe_cols if c not in fundamentally_blocked]
            removed       = pre_count - len(universe_cols)
            if removed > 0:
                rm_list = sorted(fundamentally_blocked & set(prices.columns))
                rm_str  = ", ".join(rm_list[:10])
                extra   = f" ... and {len(rm_list) - 10} others" if len(rm_list) > 10 else ""
                print(f"  [FUND FILTER] {removed} stocks removed from universe: [{rm_str}{extra}]")
            print(f"  [UNIVERSE] {len(universe_cols)} stocks after fundamental filter")

        # Save full FNO prices BEFORE liquidity filter (for trend filter sector avg)
        fno_full_prices = prices[[c for c in prices.columns if c in FNO_ELIGIBLE]]

        # ------------------------------------------------------------------
        # 2. LIQUIDITY FILTER
        # ------------------------------------------------------------------
        if volume_df is not None:
            vol_slice        = volume_df.loc[:date].iloc[-tail:]
            shared_cols      = prices.columns.intersection(vol_slice.columns)
            shared_idx       = prices.index.intersection(vol_slice.index)
            rupee_volume     = (
                prices.loc[shared_idx, shared_cols]
                * vol_slice.loc[shared_idx, shared_cols]
            )
            liquidity_metric = rupee_volume.rolling(20).mean().iloc[-1]
        else:
            warnings.warn(
                "volume_df not supplied — using volatility proxy for liquidity.",
                UserWarning, stacklevel=2,
            )
            ret              = prices.pct_change()
            liquidity_metric = (prices * ret.std()).rolling(20).mean().iloc[-1]

        # Apply liquidity filter on full universe (not just FNO)
        liquidity_metric = liquidity_metric.reindex(universe_cols).dropna()
        liquid_stocks    = liquidity_metric.nlargest(self.liq_rank).index.tolist()
        prices_filtered  = prices[liquid_stocks].dropna(axis=1, how="any")

        n_fno_in_universe = len([c for c in prices_filtered.columns if c in FNO_ELIGIBLE])
        n_non_fno         = len(prices_filtered.columns) - n_fno_in_universe
        print(
            f"[INFO] Universe: {len(price_df.columns)} total → "
            f"{len(universe_cols)} eligible → "
            f"{len(prices_filtered.columns)} liquid "
            f"({n_fno_in_universe} F&O + {n_non_fno} cash-only)."
        )

        # ------------------------------------------------------------------
        # 3. BETA ESTIMATION & ORTHOGONALISATION
        # ------------------------------------------------------------------
        log_returns   = np.log(prices_filtered / prices_filtered.shift(1)).dropna()
        bench_returns = np.log(benchmarks / benchmarks.shift(1)).dropna()
        common_dates  = log_returns.index.intersection(bench_returns.index)
        log_ret       = log_returns.loc[common_dates]
        bench_ret     = bench_returns.loc[common_dates]

        nifty_ret = (
            bench_ret["NIFTY_50"]
            if "NIFTY_50" in bench_ret.columns
            else bench_ret.iloc[:, 0]
        )

        betas    : Dict = {}
        residuals = pd.DataFrame(
            index=log_ret.index, columns=log_ret.columns, dtype=float
        )

        for stock in log_ret.columns:
            y     = log_ret[stock].iloc[-self.lookback:]
            X     = add_constant(nifty_ret.iloc[-self.lookback:])
            model = OLS(y, X, missing="drop").fit()
            betas[stock] = {
                "beta"     : model.params[1],
                "alpha"    : model.params[0],
                "resid_vol": model.resid.std(),
                "r_squared": model.rsquared,
            }
            fitted           = model.params[0] + model.params[1] * nifty_ret.iloc[-self.lookback:]
            residuals[stock] = y - fitted

        # ------------------------------------------------------------------
        # 1c. SECTOR NEUTRALIZATION (v5.0)
        # ------------------------------------------------------------------
        if self.sector_map:
            residuals = self._sector_neutralize(residuals)

        # ------------------------------------------------------------------
        # 4. SIGNAL MODULES
        # ------------------------------------------------------------------
        cs_signals    = self._cross_sectional_mean_reversion(residuals)
        pairs_signals = self._cointegration_pairs(residuals, prices_filtered)
        mom_signals   = self._residual_momentum(residuals)

        # ------------------------------------------------------------------
        # 5. COMBINE
        # ------------------------------------------------------------------
        combined      = self._combine_signals(cs_signals, pairs_signals, mom_signals)
        raw_signals   = self._apply_beta_constraint(combined, betas, liquidity_metric)

        raw_signals["is_fno"]         = raw_signals.index.isin(FNO_ELIGIBLE)
        raw_signals["effective_tcost"] = raw_signals.apply(
            lambda r: self.tcost + self.ROLL_COST_DAILY if r["hedged_position"] < 0 else self.tcost,
            axis=1,
        )
        raw_signals["exit_reason"]    = ""
        raw_signals["days_held"]      = 0

        # ------------------------------------------------------------------
        # 5a. F&O SHORT ENFORCEMENT
        # ------------------------------------------------------------------
        # Shorts require futures → only FNO stocks can be shorted.
        # Long positions allowed from any stock in NIFTY 500.
        non_fno_shorts = (
            (raw_signals["hedged_position"] < -0.001) &
            (~raw_signals.index.isin(FNO_ELIGIBLE))
        )
        n_blocked_shorts = non_fno_shorts.sum()
        if n_blocked_shorts > 0:
            raw_signals.loc[non_fno_shorts, "hedged_position"] = 0.0
            print(f"  [F&O] {n_blocked_shorts} non-FNO shorts blocked (no futures available).")

        # If long_only, zero out all short signals BEFORE tracker processing
        if long_only:
            raw_signals.loc[raw_signals["hedged_position"] < 0, "hedged_position"] = 0.0

        # Apply Sector Limits (v5.0)
        raw_signals = self._apply_sector_limits(raw_signals)

        # Apply Circuit Filters (v5.0)
        raw_signals = self._check_circuit_filters(raw_signals, price_df, date)

        # ------------------------------------------------------------------
        # 7A. TREND FILTER (v5.0) — dynamic downtrend blocking
        # ------------------------------------------------------------------
        if self._trend_filter is not None:
            trend_blocked = self._trend_filter.get_blocked_tickers(
                prices              = prices_filtered,
                sector_map          = self.sector_map,
                date                = date,
                full_universe_prices = fno_full_prices,
            )

            # Pairs protection: if one leg blocked, block the partner too
            for pair_key in list(self._last_spread_zs.keys()):
                leg1, leg2 = pair_key
                if leg1 in trend_blocked or leg2 in trend_blocked:
                    trend_blocked.add(leg1)
                    trend_blocked.add(leg2)

            # Also include fundamentally blocked for priority labeling
            fund_blocked = set()
            if self._fundamental_filter is not None:
                fund_blocked = set(self._fundamental_filter.get_blacklisted_tickers())

            trend_zeroed = 0
            for stock in trend_blocked:
                if stock not in raw_signals.index:
                    continue
                if abs(raw_signals.loc[stock, "hedged_position"]) < 0.001:
                    continue

                # CRITICAL: Do NOT force-exit existing open positions.
                # Let PositionTracker's exit rules (time stop, loss stop,
                # z reversal) handle them naturally. Only block NEW entries.
                if tracker is not None and tracker.is_open(stock):
                    continue

                raw_signals.loc[stock, "hedged_position"] = 0.0
                # Fundamental takes priority in labeling
                if stock in fund_blocked:
                    raw_signals.loc[stock, "signal_type"] = "fundamental_blocked"
                else:
                    raw_signals.loc[stock, "signal_type"] = "trend_blocked"
                trend_zeroed += 1

            if trend_zeroed > 0:
                zeroed_list = sorted([s for s in trend_blocked if s in raw_signals.index])
                z_str = ", ".join(zeroed_list[:10])
                z_ext = f" ... and {len(zeroed_list) - 10} others" if len(zeroed_list) > 10 else ""
                print(f"  [TREND FILTER] {trend_zeroed} stocks zeroed: [{z_str}{z_ext}]")

            n_active = (raw_signals["hedged_position"].abs() > 0.001).sum()
            print(f"  [UNIVERSE FINAL] {n_active} stocks with active signals after all filters")

        # ------------------------------------------------------------------
        # 5b. SIGNAL QUALITY FILTER (v6.0) — RF + Volume Confirmation
        # ------------------------------------------------------------------
        if self._signal_filter is not None:
            vol_for_filter = volume_df.reindex(residuals.index) if volume_df is not None else None
            raw_signals = self._signal_filter.filter_signals(
                raw_signals = raw_signals,
                residuals   = residuals,
                betas       = betas,
                volume_df   = vol_for_filter,
                z_entry     = self.z_entry,
            )

        # ------------------------------------------------------------------
        # 6. POSITION TRACKER INTEGRATION (new in v4.0)
        # ------------------------------------------------------------------
        if tracker is not None:
            current_prices_series = prices_filtered.iloc[-1]

            # 6a. Build current per-ticker z-scores for exit evaluation
            current_z = pd.Series(
                {t: raw_signals.loc[t, "z_score"] * (
                    1 if raw_signals.loc[t, "hedged_position"] >= 0 else -1
                ) for t in raw_signals.index},
                dtype=float,
            )

            # 6b. Age existing positions
            tracker.increment_days()

            # 6c. Evaluate exits
            exits = tracker.evaluate_exits(
                current_prices   = current_prices_series,
                current_z_scores = current_z,
                spread_z_scores  = {
                    k: v for k, v in self._last_spread_zs.items()
                },
            )

            for ticker, reason in exits:
                tracker.close_position(ticker)
                if ticker in raw_signals.index:
                    raw_signals.loc[ticker, "hedged_position"] = 0.0
                    raw_signals.loc[ticker, "exit_reason"]     = reason
                print(f"  [EXIT] {ticker:15s} reason={reason}")

            # 6d. Carry forward remaining open positions
            #     (override raw signal with existing size so we don't churn)
            for ticker, pos in tracker.current_book().items():
                if ticker in raw_signals.index:
                    carry_size = pos.size * pos.direction
                    raw_signals.loc[ticker, "hedged_position"] = carry_size
                    raw_signals.loc[ticker, "signal_type"]     = pos.signal_type
                    raw_signals.loc[ticker, "days_held"]       = pos.days_held

            # 6e. Open new positions (skips tickers already in book)
            newly_opened = tracker.open_new_from_signals(
                signals        = raw_signals,
                current_prices = current_prices_series,
                date           = date,
            )
            if newly_opened:
                print(f"  [ENTRY] {len(newly_opened)} new positions: {newly_opened}")

        self._last_signals = raw_signals
        return raw_signals

    # -------------------------------------------------------------------------
    # SIGNAL MODULES (unchanged from v3.0)
    # -------------------------------------------------------------------------

    def _sector_neutralize(self, residual_returns: pd.DataFrame) -> pd.DataFrame:
        out      = residual_returns.copy()
        sectors: Dict[str, list] = {}
        for stock in residual_returns.columns:
            sectors.setdefault(self.sector_map.get(stock, "Unknown"), []).append(stock)
        for sector, members in sectors.items():
            valid = [m for m in members if m in residual_returns.columns]
            if len(valid) < 3:
                continue
            sec_ret = residual_returns[valid].mean(axis=1)
            for stock in valid:
                out[stock] = residual_returns[stock] - sec_ret
        return out

    def _cross_sectional_mean_reversion(
        self, resid_returns: pd.DataFrame
    ) -> pd.DataFrame:
        sigs = pd.DataFrame(index=resid_returns.columns)
        sigs["signal_type"] = "mean_reversion"

        formation = resid_returns.iloc[-5:].sum()
        median    = formation.median()
        mad       = _safe_mad(formation)

        sigs["z_score"]   = (formation - median) / (1.4826 * mad)
        sigs["raw_alpha"] = np.where(
            sigs["z_score"] >  self.z_entry, -1,   # Short overextended winners
            np.where(sigs["z_score"] < -self.z_entry,  1, 0), # Long oversold losers
        )

        vol = (resid_returns.std() * np.sqrt(252)).replace(0, np.nan)
        vol_scaling = (1.0 / vol).fillna((1.0 / vol).median())
        sigs["alpha_signal"] = (
            sigs["raw_alpha"] * vol_scaling / vol_scaling.sum() * len(vol_scaling)
        )
        return sigs

    def _cointegration_pairs(
        self, resid_returns: pd.DataFrame, prices: pd.DataFrame
    ) -> pd.DataFrame:
        sigs = pd.DataFrame(index=resid_returns.columns)
        sigs["alpha_signal"] = 0.0
        sigs["z_score"]      = 0.0
        sigs["signal_type"]  = ""
        sigs["hedge_ratio"]  = 0.0

        candidate_pairs = [
            ("HDFCBANK",   "ICICIBANK"),
            ("AXISBANK",   "KOTAKBANK"),
            ("SBIN",       "BANKBARODA"),
            ("RELIANCE",   "ONGC"),
            ("INFY",       "TCS"),
            ("WIPRO",      "HCLTECH"),
            ("TATAMOTORS", "M&M"),
            ("MARUTI",     "HEROMOTOCO"),
            ("SUNPHARMA",  "DRREDDY"),
            ("TATASTEEL",  "JSWSTEEL"),
            ("BAJFINANCE", "CHOLAFIN"),
            ("NTPC",       "POWERGRID"),
        ]

        valid_pairs = []
        self._last_spread_zs = {}   # reset for this run

        for leg1, leg2 in candidate_pairs:
            if leg1 not in prices.columns or leg2 not in prices.columns:
                continue
            if leg1 not in FNO_ELIGIBLE or leg2 not in FNO_ELIGIBLE:
                continue

            p1 = prices[leg1].dropna().iloc[-self.lookback:]
            p2 = prices[leg2].dropna().iloc[-self.lookback:]
            common_idx = p1.index.intersection(p2.index)
            if len(common_idx) < 200:
                continue
            p1, p2 = p1.loc[common_idx], p2.loc[common_idx]

            try:
                _, pvalue, _ = coint(p1, p2)
                if pvalue >= 0.05:
                    continue

                hedge_model = OLS(p1, add_constant(p2)).fit()
                hedge_ratio = hedge_model.params[1]
                spread      = p1 - hedge_ratio * p2
                spread_mean = spread.mean()
                spread_std  = spread.std()

                if spread_std == 0:
                    continue

                z = (spread.iloc[-1] - spread_mean) / spread_std

                # Store spread z for tracker exit evaluation
                pair_key = tuple(sorted([leg1, leg2]))
                self._last_spread_zs[pair_key] = z

                if abs(z) <= self.z_entry:
                    continue

                valid_pairs.append((leg1, leg2, z, hedge_ratio))
                direction = -np.sign(z)

                sigs.loc[leg1, "alpha_signal"] = direction * min(abs(z) / 3, 1.0)
                sigs.loc[leg1, "z_score"]      = z
                sigs.loc[leg1, "signal_type"]  = f'pairs_{"long" if z < 0 else "short"}'
                sigs.loc[leg1, "hedge_ratio"]  = hedge_ratio

                sigs.loc[leg2, "alpha_signal"] = -direction * min(abs(z) / 3, 1.0) * hedge_ratio
                sigs.loc[leg2, "z_score"]      = -z
                sigs.loc[leg2, "signal_type"]  = f'pairs_{"short" if z < 0 else "long"}'
                sigs.loc[leg2, "hedge_ratio"]  = (1.0 / hedge_ratio) if hedge_ratio != 0 else 0.0

            except Exception:
                continue

        print(f"[INFO] Valid cointegrated pairs: {len(valid_pairs)}")
        return sigs

    def _residual_momentum(self, resid_returns: pd.DataFrame) -> pd.DataFrame:
        sigs            = pd.DataFrame(index=resid_returns.columns)
        formation_start = -252
        formation_end   = -21

        if len(resid_returns) < abs(formation_start):
            warnings.warn(
                f"[_residual_momentum] Only {len(resid_returns)} rows — "
                f"need {abs(formation_start)}. Momentum signal zeroed.",
                UserWarning, stacklevel=2,
            )
            sigs["alpha_signal"] = 0.0
            sigs["signal_type"]  = "residual_momentum"
            sigs["z_score"]      = 0.0
            return sigs

        cum_ret = resid_returns.iloc[formation_start:formation_end].sum(axis=0)
        ranks   = cum_ret.rank(pct=True)
        sigs["alpha_signal"] = np.where(
            ranks > 0.9,  1,
            np.where(ranks < 0.1, -1, 0),
        )
        sigs["signal_type"] = "residual_momentum"
        sigs["z_score"]     = (ranks - 0.5) * 4
        return sigs

    def _combine_signals(
        self,
        cs_signals    : pd.DataFrame,
        pairs_signals : pd.DataFrame,
        mom_signals   : pd.DataFrame,
    ) -> pd.DataFrame:
        combined = pd.DataFrame(index=cs_signals.index)

        def _normalize(s: pd.Series) -> pd.Series:
            total = s.abs().sum()
            return (s - s.mean()) if total > 0 else s

        cs_norm    = _normalize(cs_signals["alpha_signal"].fillna(0))
        pairs_norm = _normalize(pairs_signals["alpha_signal"].fillna(0))
        mom_norm   = _normalize(mom_signals["alpha_signal"].fillna(0))

        combined["alpha_signal"] = (
            0.40 * cs_norm + 0.35 * pairs_norm + 0.25 * mom_norm
        )
        combined["cs_z"]    = cs_signals["z_score"].fillna(0)
        combined["pairs_z"] = pairs_signals["z_score"].fillna(0)
        combined["mom_z"]   = mom_signals["z_score"].fillna(0)
        combined["z_score"] = combined[["cs_z", "pairs_z", "mom_z"]].abs().max(axis=1)

        def _dominant_type(row) -> str:
            if abs(row["pairs_z"]) > self.z_entry:
                return pairs_signals.loc[row.name, "signal_type"]
            if abs(row["mom_z"]) > 1.5:
                return "residual_momentum"
            return "mean_reversion"

        combined["signal_type"] = combined.apply(_dominant_type, axis=1)

        gross = combined["alpha_signal"].abs().sum()
        combined["hedged_position"] = (
            combined["alpha_signal"] / gross * 2.0 if gross > 0 else 0.0
        )
        combined["hedged_position"] = combined["hedged_position"].clip(
            -self.max_pos, self.max_pos
        )
        return combined

    def _apply_beta_constraint(
        self,
        signals         : pd.DataFrame,
        betas           : Dict,
        liquidity_metric: pd.Series,
    ) -> pd.DataFrame:
        port_beta = sum(
            signals.loc[s, "hedged_position"] * betas[s]["beta"]
            for s in signals.index if s in betas
        )
        signals["beta_exposure"] = port_beta

        if abs(port_beta) > 0.05:
            print(f"[WARNING] Portfolio beta {port_beta:.4f} > 0.05 — rescaling.")
            scale = 0.04 / abs(port_beta)
            signals["hedged_position"] *= scale
            signals["beta_exposure"]   *= scale

        signals["liquidity_score"] = liquidity_metric.rank(pct=True)
        min_edge   = self.tcost * 4
        edge_proxy = signals["z_score"].abs().fillna(0) * 0.02
        signals["hedged_position"] *= (edge_proxy > min_edge).astype(float)
        return signals

    def _sector_neutralize(self, resid_ret: pd.DataFrame) -> pd.DataFrame:
        """Remove sector-level returns from residuals to extract stock-specific alpha."""
        neutralized = resid_ret.copy()
        sectors = {}
        
        for stock in resid_ret.columns:
            sec = self.sector_map.get(stock, 'Other')
            sectors.setdefault(sec, []).append(stock)
        
        for sec, stocks in sectors.items():
            if len(stocks) >= 3:
                sec_ret = resid_ret[stocks].mean(axis=1)
                for s in stocks:
                    neutralized[s] = resid_ret[s] - sec_ret
        
        return neutralized

    def _apply_sector_limits(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Limit sector exposure to ±25% of gross exposure."""
        sector_exp = {}
        for stock in signals.index:
            sec = self.sector_map.get(stock, 'Other')
            sector_exp[sec] = sector_exp.get(sec, 0) + signals.loc[stock, 'hedged_position']
        
        # Simple scaling if any sector exceeds limit
        for sec, exp in sector_exp.items():
            if abs(exp) > self.max_sector_exp:
                scale = self.max_sector_exp / abs(exp)
                for stock in signals.index:
                    if self.sector_map.get(stock, 'Other') == sec:
                        signals.loc[stock, 'hedged_position'] *= scale
        
        return signals

    def _check_circuit_filters(self, signals: pd.DataFrame, price_df: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
        """Flag stocks near circuit limits (NSE-specific) and reduce position exposure."""
        for stock in signals.index:
            if stock not in price_df.columns:
                continue
            
            recent_prices = price_df[stock].loc[:date].iloc[-5:]
            if len(recent_prices) < 2: continue
            
            daily_changes = recent_prices.pct_change().dropna()
            
            # If stock hit ±9% (near 10% limit) recently, reduce position (illiquid at limit)
            if abs(daily_changes).max() > 0.09:
                signals.loc[stock, 'hedged_position'] *= 0.5
                signals.loc[stock, 'signal_type'] += '_circuit_warning'
        
        return signals

    # -------------------------------------------------------------------------
    # DIAGNOSTICS
    # -------------------------------------------------------------------------

    def get_portfolio_metrics(self) -> Dict:
        if self._last_signals is None:
            return {"error": "No signals yet."}
        sigs = self._last_signals
        pos  = sigs["hedged_position"]
        return {
            "num_long"            : int((pos >  0.001).sum()),
            "num_short_futures"   : int((pos < -0.001).sum()),
            "gross_exposure"      : round(float(pos.abs().sum()), 4),
            "net_exposure"        : round(float(pos.sum()), 4),
            "portfolio_beta"      : round(float(
                sigs["beta_exposure"].iloc[0]
                if "beta_exposure" in sigs.columns else 0), 4),
            "signal_distribution" : sigs["signal_type"].value_counts().to_dict(),
            "exits_this_period"   : sigs[sigs["exit_reason"] != ""]["exit_reason"]
                                    .value_counts().to_dict(),
        }

    def get_lot_size_check(self, nav_inr: float) -> pd.DataFrame:
        if self._last_signals is None:
            raise RuntimeError("Call generate_signals() first.")
        sigs = self._last_signals
        rows = []
        for stock in sigs[sigs["hedged_position"].abs() > 0.001].index:
            pos_frac = sigs.loc[stock, "hedged_position"]
            rows.append({
                "ticker"           : stock,
                "position_fraction": round(pos_frac, 4),
                "notional_inr"     : round(abs(pos_frac) * nav_inr, 0),
                "lot_size"         : FNO_LOT_SIZES.get(stock, DEFAULT_LOT_SIZE),
                "direction"        : "LONG" if pos_frac > 0 else "SHORT FUTURES",
                "signal_type"      : sigs.loc[stock, "signal_type"],
                "days_held"        : int(sigs.loc[stock, "days_held"]),
            })
        return pd.DataFrame(rows).sort_values("position_fraction")


# =============================================================================
# PRODUCTION DATA LOADING
# =============================================================================

def load_production_data():
    print("📁 Loading Production Data...")
    df_s       = pd.read_csv("sector_map.csv")
    sector_map = dict(zip(df_s["Symbol"], df_s["Sector"]))

    df_p         = pd.read_parquet("nifty500_daily.parquet")
    df_p["Date"] = pd.to_datetime(df_p["Date"]).dt.tz_localize(None)
    price_df  = df_p.pivot(index="Date", columns="Ticker", values="Close").ffill()
    volume_df = df_p.pivot(index="Date", columns="Ticker", values="Volume").ffill()

    print("📊 Fetching Benchmark Data...")
    raw = yf.download(
        ["^NSEI", "^NSEBANK"],
        start=price_df.index.min(),
        end=price_df.index.max() + pd.Timedelta(days=1),
        progress=False,
    )["Close"]
    raw      = raw.rename(columns={"^NSEI": "NIFTY_50", "^NSEBANK": "BANK_NIFTY"})
    bench_df = raw.reindex(price_df.index).ffill()

    print(f"✅ {len(price_df)} days, {len(price_df.columns)} tickers.")
    return price_df, volume_df, bench_df, sector_map


# =============================================================================
# PRODUCTION RUNNER
# =============================================================================

def run_production_alpha():
    price_df, volume_df, bench_df, sector_map = load_production_data()

    fundamental_filter = FundamentalFilter(csv_path="fundamental_filter.csv")
    trend_filter       = TrendFilter()
    signal_filter      = SignalQualityFilter()

    alpha_gen = NSEAlphaGenerator(
        lookback_window    = 252,
        min_liquidity_rank = 150,
        zscore_threshold   = 2.0,
        max_position_size  = 0.03,
        transaction_cost   = 0.0010,
        sector_mapping     = sector_map,
        signal_filter      = signal_filter,
        fundamental_filter = fundamental_filter,
        trend_filter       = trend_filter,
    )

    # Create a fresh tracker for this run
    # In live trading: persist/load this object between daily runs
    tracker = PositionTracker()

    print("=" * 70)
    print("NSE PURE ALPHA GENERATOR v4.0 — F&O + EXIT LOGIC")
    print("=" * 70)

    latest_date = price_df.index[-1]
    print(f"Signal date: {latest_date.date()}")

    signals = alpha_gen.generate_signals(
        price_df     = price_df,
        benchmark_df = bench_df,
        volume_df    = volume_df,
        date         = latest_date,
        tracker      = tracker,
    )

    active = signals[signals["hedged_position"].abs() > 0.001].copy()

    # ──────────────────────────────────────────────────────────────
    # PORTFOLIO MANAGEMENT INSTRUCTIONS
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  📝 PORTFOLIO MANAGEMENT INSTRUCTIONS")
    print(f"{'='*70}")
    print("  1. CHECK EXITS FIRST: Look at the 'exits_this_period' section below.")
    print("     If a stock is listed there, SELL it today.")
    print("  2. HOLD EXISTING POSITIONS: Do NOT sell any other open positions.")
    print(f"     - Mean Reversion: Hold until z-score hits 0 (Max {MAX_MR_DAYS} days).")
    print(f"     - Momentum: MUST hold for minimum {MIN_MOM_DAYS} days.")
    print("  3. DEPLOY IDLE CASH: Only use the 'Top Recommendations' lists below")
    print("     if you have idle cash to deploy today.")

    # ──────────────────────────────────────────────────────────────
    # TOP RECOMMENDATIONS
    # ──────────────────────────────────────────────────────────────
    longs  = active[active["hedged_position"] > 0].copy()
    shorts = active[active["hedged_position"] < 0].copy()

    # Rank by absolute z-score (strongest conviction first)
    longs  = longs.sort_values("z_score", ascending=False)
    shorts = shorts.sort_values("z_score", ascending=True)

    TOP_LONG  = 10
    TOP_SHORT = 5

    print(f"\n{'='*70}")
    print(f"  🟢 TOP {TOP_LONG} LONG RECOMMENDATIONS (BUY)")
    print(f"{'='*70}")
    if len(longs) == 0:
        print("  No long signals today.")
    else:
        top_longs = longs.head(TOP_LONG)
        for i, (ticker, row) in enumerate(top_longs.iterrows(), 1):
            fno_tag = "F&O" if ticker in FNO_ELIGIBLE else "CASH"
            sig     = row["signal_type"]
            z       = row["z_score"]
            pos     = row["hedged_position"]
            print(f"  {i:>2}. {ticker:<15s}  z={z:+.2f}  size={pos:.3f}  "
                  f"{sig:<30s}  [{fno_tag}]")
        if len(longs) > TOP_LONG:
            print(f"\n  ... and {len(longs) - TOP_LONG} more long signals")
        print(f"\n  Total longs: {len(longs)}")

    print(f"\n{'='*70}")
    print(f"  🔴 TOP {TOP_SHORT} SHORT RECOMMENDATIONS (SELL FUTURES)")
    print(f"{'='*70}")
    if len(shorts) == 0:
        print("  No short signals today.")
    else:
        top_shorts = shorts.head(TOP_SHORT)
        for i, (ticker, row) in enumerate(top_shorts.iterrows(), 1):
            fno_tag = "F&O ✅" if ticker in FNO_ELIGIBLE else "NO FNO ❌"
            sig     = row["signal_type"]
            z       = row["z_score"]
            pos     = row["hedged_position"]
            print(f"  {i:>2}. {ticker:<15s}  z={z:+.2f}  size={pos:+.3f}  "
                  f"{sig:<30s}  [{fno_tag}]")
        if len(shorts) > TOP_SHORT:
            print(f"\n  ... and {len(shorts) - TOP_SHORT} more short signals")
        print(f"\n  Total shorts: {len(shorts)}")

    # ──────────────────────────────────────────────────────────────
    # FILTER FUNNEL
    # ──────────────────────────────────────────────────────────────
    sig_dist = signals["signal_type"].value_counts().to_dict()
    print(f"\n{'='*70}")
    print(f"  📊 FILTER FUNNEL")
    print(f"{'='*70}")
    print(f"  Total NIFTY 500         : {len(price_df.columns)}")
    print(f"  After fundamental filter: {len(price_df.columns) - sig_dist.get('fundamental_blocked', 0)}")
    print(f"  Trend blocked           : {sig_dist.get('trend_blocked', 0)}")
    print(f"  Active positions        : {len(active)}")
    print(f"    ├── Longs             : {len(longs)}")
    print(f"    └── Shorts (futures)  : {len(shorts)}")

    print(f"\n{'='*70}")
    print(f"  📋 POSITION BOOK")
    print(f"{'='*70}")
    print(tracker.summary())

    print(f"\n📊 PORTFOLIO METRICS:")
    for k, v in alpha_gen.get_portfolio_metrics().items():
        print(f"  {k}: {v}")

    return signals, alpha_gen, tracker


# =============================================================================
# HARDENED BACKTESTER  (now tracker-aware)
# =============================================================================

class SimpleBacktester:
    """
    Walk-forward backtester with PositionTracker integrated.
    The tracker persists across rebalance dates so exit logic fires correctly.
    """

    def __init__(self, alpha_generator: NSEAlphaGenerator):
        self.gen     = alpha_generator
        self.results : Optional[pd.DataFrame] = None

    def run_backtest(
        self,
        price_df      : pd.DataFrame,
        benchmark_df  : pd.DataFrame,
        volume_df     : pd.DataFrame,
        start_date    : str,
        end_date      : str,
        rebalance_freq: str = "W-MON",
        long_only     : bool = False,
    ) -> pd.DataFrame:

        rebal_dates    = pd.date_range(
            start=start_date, end=end_date, freq=rebalance_freq
        )
        portfolio_rets = []
        tracker        = PositionTracker()   # persistent across rebalances

        print(f"🚀 Backtest: {start_date} → {end_date}  freq={rebalance_freq}")

        for target_date in rebal_dates:
            available = price_df.index[price_df.index <= target_date]
            if len(available) == 0:
                continue
            actual_date = available[-1]

            try:
                signals = self.gen.generate_signals(
                    price_df     = price_df.loc[:actual_date],
                    benchmark_df = benchmark_df.loc[:actual_date],
                    volume_df    = volume_df.loc[:actual_date],
                    date         = actual_date,
                    tracker      = tracker,
                    long_only    = long_only,
                )

                next_idx = price_df.index.get_loc(actual_date) + 1
                if next_idx >= len(price_df):
                    continue

                fwd_ret   = price_df.pct_change().iloc[next_idx]
                bench_fwd = benchmark_df["NIFTY_50"].pct_change().iloc[next_idx]

                # --- INSTITUTIONAL COST CALCULATION (v5.0) ---
                pos             = signals["hedged_position"]
                prev_pos        = self._last_pos if hasattr(self, '_last_pos') else pd.Series(0, index=pos.index)
                turnover_series = (pos - prev_pos).abs()
                total_turnover  = turnover_series.sum()
                
                # 1. Brokerage(0.03%), STT(0.1% sells), Regulatory(~0.02%), Impact(5bps)
                total_tcost = (total_turnover * 0.0003) + \
                              ((prev_pos - pos).clip(lower=0).sum() * 0.001) + \
                              (total_turnover * 0.0002) + \
                              (total_turnover * 0.0005)
                # ---------------------------------------------

                roll_adj = pos.apply(
                    lambda p: -NSEAlphaGenerator.ROLL_COST_DAILY if p < 0 else 0.0
                )
                port_ret = (pos * fwd_ret + roll_adj).sum()
                beta_exp = float(
                    signals["beta_exposure"].iloc[0]
                    if "beta_exposure" in signals.columns else 0.0
                )

                portfolio_rets.append({
                    "date"             : actual_date,
                    "portfolio_return" : port_ret,
                    "net_return"       : port_ret - total_tcost,
                    "benchmark_return" : bench_fwd,
                    "alpha"            : (port_ret - total_tcost) - bench_fwd * beta_exp,
                    "transaction_cost" : total_tcost,
                    "turnover"         : total_turnover,
                    "num_long"         : int((pos >  0.001).sum()),
                    "num_short"        : int((pos < -0.001).sum()),
                    "gross_exposure"   : float(pos.abs().sum()),
                })
                self._last_pos = pos

            except Exception as e:
                print(f"[SKIP] {actual_date}: {e}")
                continue

        self.results     = pd.DataFrame(portfolio_rets)
        self._rebal_freq = rebalance_freq
        return self.results

    def performance_summary(self) -> Dict:
        if self.results is None or self.results.empty:
            return {"error": "No results — call run_backtest() first."}

        rets       = self.results["alpha"].dropna()
        bench_rets = self.results["benchmark_return"].dropna()
        ann_factor = _annualisation_factor(getattr(self, "_rebal_freq", "W-MON"))

        cumulative  = (1 + rets).cumprod()
        rolling_max = cumulative.cummax()
        max_dd      = float(((cumulative - rolling_max) / rolling_max).min())

        sharpe = (
            float(rets.mean() / rets.std() * np.sqrt(ann_factor))
            if rets.std() != 0 else 0.0
        )

        return {
            "num_periods"           : len(rets),
            "total_alpha_return"    : round(float(rets.sum()), 4),
            "total_net_return"      : round(float(self.results["net_return"].sum()), 4),
            "annualised_sharpe"     : round(sharpe, 3),
            "max_drawdown"          : round(max_dd, 4),
            "win_rate"              : round(float((rets > 0).mean()), 3),
            "avg_transaction_cost"  : round(float(self.results["transaction_cost"].mean()), 5),
            "total_transaction_cost": round(float(self.results["transaction_cost"].sum()), 5),
            "annual_turnover"       : round(float(self.results["turnover"].sum() / (len(rets)/ann_factor)), 3),
            "beta_to_nifty"         : round(
                float(
                    np.cov(rets, bench_rets.loc[rets.index])[0, 1]
                    / np.var(bench_rets.loc[rets.index])
                ) if len(rets) > 1 else 0.0, 4
            ),
            "avg_long_positions"    : round(float(self.results["num_long"].mean()), 1),
            "avg_short_positions"   : round(float(self.results["num_short"].mean()), 1),
            "avg_gross_exposure"    : round(float(self.results["gross_exposure"].mean()), 3),
        }


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    signals, generator, tracker = run_production_alpha()

    # Optional backtest:
    # price_df, volume_df, bench_df, _ = load_production_data()
    # bt = SimpleBacktester(generator)
    # results = bt.run_backtest(
    #     price_df, bench_df, volume_df,
    #     start_date="2022-06-01", end_date="2024-01-01",
    #     rebalance_freq="W-MON",
    # )
    # print(bt.performance_summary())