"""
fetch_fundamentals.py — Quarterly Fundamental Data Puller
==========================================================

Pulls fundamental data for ALL stocks in nifty500_daily.parquet
using yfinance and outputs fundamental_filter.csv

RUN THIS QUARTERLY:
  python3 fetch_fundamentals.py

What it pulls automatically (yfinance):
  ROE, ROCE, Debt/Equity, ICR, Market Cap,
  Revenue Growth, Net Profit, EBITDA

What you fill manually (quarterly):
  PromoterHolding, PromoterPledge,
  PledgeIncreasing3Qtrs, PromoterSelling,
  AuditorFlag

Source for manual data:
  https://www.nseindia.com/companies-listing/
  corporate-filings-shareholding-pattern
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
import os
import time
from datetime import datetime
from typing import Optional

warnings.filterwarnings('ignore')

# =============================================================================
# CONFIG
# =============================================================================

PARQUET_PATH      = "nifty500_daily.parquet"
SECTOR_MAP_CSV    = "sector_map.csv"
OUTPUT_CSV        = "fundamental_filter.csv"

# yfinance rate limiting — sleep between batches
BATCH_SIZE        = 10     # stocks per batch
BATCH_SLEEP_SEC   = 2      # seconds between batches
RETRY_SLEEP_SEC   = 10     # seconds before retry on failure
MAX_RETRIES       = 4      # max retries per stock

# Finance sectors from sector_map.csv — NOT hardcoded by ticker.
# Determined dynamically at runtime from the CSV.
FINANCE_SECTOR_NAMES = {"Financial Services"}


# =============================================================================
# HELPERS
# =============================================================================

def _load_finance_tickers() -> set:
    """
    Load finance tickers from sector_map.csv dynamically.
    This way when NIFTY 500 rebalances, new finance stocks
    are automatically detected — no hardcoding needed.
    """
    if not os.path.exists(SECTOR_MAP_CSV):
        warnings.warn(f"sector_map.csv not found — finance detection disabled.")
        return set()

    df = pd.read_csv(SECTOR_MAP_CSV)
    finance = set(
        df[df["Sector"].isin(FINANCE_SECTOR_NAMES)]["Symbol"].tolist()
    )
    return finance


def _safe_float(val, default=None):
    """Safely convert to float."""
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return float(val)
    except Exception:
        return default


def _compute_roce(ticker_obj) -> Optional[float]:
    """
    Compute ROCE = EBIT / Capital Employed
    Capital Employed = Total Assets - Current Liabilities
    """
    try:
        fin = ticker_obj.financials
        bal = ticker_obj.balance_sheet

        if fin is None or bal is None or fin.empty or bal.empty:
            return None

        ebit = None
        for key in ["Operating Income", "EBIT", "Ebit"]:
            if key in fin.index:
                ebit = float(fin.loc[key].iloc[0])
                break

        if ebit is None:
            return None

        total_assets = None
        curr_liab    = None

        for key in ["Total Assets", "TotalAssets"]:
            if key in bal.index:
                total_assets = float(bal.loc[key].iloc[0])
                break

        for key in ["Current Liabilities", "CurrentLiabilities",
                     "Total Current Liabilities"]:
            if key in bal.index:
                curr_liab = float(bal.loc[key].iloc[0])
                break

        if total_assets is None or curr_liab is None:
            return None

        cap_employed = total_assets - curr_liab
        if cap_employed <= 0:
            return None

        return round((ebit / cap_employed) * 100, 2)

    except Exception:
        return None


def _compute_icr(ticker_obj) -> Optional[float]:
    """Compute ICR = EBIT / Interest Expense."""
    try:
        fin = ticker_obj.financials
        if fin is None or fin.empty:
            return None

        ebit     = None
        interest = None

        for key in ["Operating Income", "EBIT", "Ebit"]:
            if key in fin.index:
                ebit = float(fin.loc[key].iloc[0])
                break

        for key in ["Interest Expense", "InterestExpense",
                     "Total Interest Expense"]:
            if key in fin.index:
                interest = abs(float(fin.loc[key].iloc[0]))
                break

        if ebit is None or interest is None or interest == 0:
            return None

        return round(ebit / interest, 2)

    except Exception:
        return None


def _check_revenue_decline_2yr(ticker_obj) -> bool:
    """Returns True if revenue declined in BOTH of the last 2 years."""
    try:
        fin = ticker_obj.financials
        if fin is None or fin.empty:
            return False

        rev_row = None
        for key in ["Total Revenue", "Revenue", "TotalRevenue"]:
            if key in fin.index:
                rev_row = fin.loc[key]
                break

        if rev_row is None or len(rev_row) < 3:
            return False

        rev = [float(rev_row.iloc[i]) for i in range(min(3, len(rev_row)))]
        return rev[0] < rev[1] and rev[1] < rev[2]

    except Exception:
        return False


def _check_net_profit_negative(ticker_obj) -> bool:
    """Returns True if net profit was negative in ANY of last 2 years."""
    try:
        fin = ticker_obj.financials
        if fin is None or fin.empty:
            return False

        np_row = None
        for key in ["Net Income", "NetIncome", "Net Income Common Stockholders"]:
            if key in fin.index:
                np_row = fin.loc[key]
                break

        if np_row is None or len(np_row) < 1:
            return False

        for i in range(min(2, len(np_row))):
            if float(np_row.iloc[i]) < 0:
                return True

        return False

    except Exception:
        return False


def _check_ebitda_negative(info: dict, ticker_obj) -> bool:
    """Returns True if EBITDA is negative."""
    try:
        ebitda = _safe_float(info.get("ebitda"))
        if ebitda is not None:
            return ebitda < 0

        fin = ticker_obj.financials
        if fin is not None and not fin.empty:
            for key in ["EBITDA", "Ebitda"]:
                if key in fin.index:
                    return float(fin.loc[key].iloc[0]) < 0

        return False
    except Exception:
        return False


# =============================================================================
# MAIN PULLER
# =============================================================================

def fetch_stock_fundamentals(ticker_nse: str, finance_tickers: set) -> dict:
    """
    Fetch all yfinance-available fundamentals for one NSE stock.
    ticker_nse: NSE ticker without .NS suffix (e.g. "INFY")
    Returns dict with all fundamental fields.
    """
    yf_ticker = f"{ticker_nse}.NS"

    row = {
        "Ticker"               : ticker_nse,
        "Sector"               : "Unknown",
        "IsFinanceSector"      : ticker_nse in finance_tickers,
        "NetProfitNegative"    : False,
        "EBITDA_Negative"      : False,
        "ROE"                  : 15.0,
        "ROCE"                 : 15.0,
        "DebtEquity"           : 0.5,
        "ICR"                  : 3.0,
        "GrossNPA_Pct"         : 0.0,
        "CAR_Pct"              : 15.0,
        "RevenueDecline2Yr"    : False,
        "PromoterHolding"      : 50.0,
        "PromoterPledge"       : 0.0,
        "PledgeIncreasing3Qtrs": False,
        "MarketCap_Cr"         : 10000,
        "AuditorFlag"          : False,
        "PromoterSelling"      : False,
        "LastUpdated"          : datetime.now().strftime("%Y-%m-%d"),
        "DataSource"           : "placeholder",
        "FetchError"           : "",
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            t    = yf.Ticker(yf_ticker)
            info = t.info or {}

            if len(info) < 5:
                row["FetchError"] = "empty_info"
                return row

            # --- Sector ---
            row["Sector"] = info.get("sector", "Unknown") or "Unknown"

            # --- Market Cap (convert to Crores: ₹ / 1e7) ---
            mcap = _safe_float(info.get("marketCap"))
            if mcap is not None:
                row["MarketCap_Cr"] = round(mcap / 1e7, 0)

            # --- ROE (yfinance returns decimal, e.g. 0.18 = 18%) ---
            roe = _safe_float(info.get("returnOnEquity"))
            if roe is not None:
                row["ROE"] = round(roe * 100, 2)

            # --- ROCE (manual computation from financials) ---
            roce = _compute_roce(t)
            if roce is not None:
                row["ROCE"] = roce

            # --- Debt to Equity ---
            # yfinance returns D/E as percentage (e.g. 35.6 means 0.356x ratio)
            de = _safe_float(info.get("debtToEquity"))
            if de is not None:
                row["DebtEquity"] = round(de / 100, 2)

            # --- ICR (manual computation from financials) ---
            icr = _compute_icr(t)
            if icr is not None:
                row["ICR"] = icr

            # --- Revenue decline 2yr ---
            row["RevenueDecline2Yr"] = _check_revenue_decline_2yr(t)

            # --- Net profit negative ---
            row["NetProfitNegative"] = _check_net_profit_negative(t)

            # --- EBITDA negative ---
            row["EBITDA_Negative"] = _check_ebitda_negative(info, t)

            row["DataSource"] = "yfinance"
            row["FetchError"] = ""
            return row

        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SLEEP_SEC)
                continue
            else:
                row["FetchError"] = str(e)[:100]
                return row

    return row


def run_full_fetch():
    """Main runner — fetches fundamentals for all stocks in parquet."""
    print("=" * 65)
    print("📊 FUNDAMENTAL DATA PULLER — NSE Nifty 500")
    print(f"📅 Run Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # ── 1. Load tickers from parquet ──
    if not os.path.exists(PARQUET_PATH):
        print(f"❌ ERROR: {PARQUET_PATH} not found!")
        return

    print(f"\n📁 Loading tickers from {PARQUET_PATH}...")
    df_p    = pd.read_parquet(PARQUET_PATH)
    tickers = sorted(df_p["Ticker"].dropna().unique().tolist())
    print(f"   Found {len(tickers)} unique tickers")

    # ── 2. Load finance tickers from sector_map.csv ──
    finance_tickers = _load_finance_tickers()
    print(f"   Finance sector tickers: {len(finance_tickers)} "
          f"(from {SECTOR_MAP_CSV})")

    # ── 3. Load existing CSV (preserve manual columns) ──
    existing_df = None
    manual_cols = [
        "PromoterHolding", "PromoterPledge",
        "PledgeIncreasing3Qtrs", "PromoterSelling",
        "AuditorFlag", "GrossNPA_Pct", "CAR_Pct",
    ]

    if os.path.exists(OUTPUT_CSV):
        print(f"\n📂 Existing {OUTPUT_CSV} found — preserving manual columns...")
        existing_df = pd.read_csv(OUTPUT_CSV).set_index("Ticker")
        backup = f"fundamental_filter_backup_{datetime.now().strftime('%Y%m%d')}.csv"
        existing_df.reset_index().to_csv(backup, index=False)
        print(f"   💾 Backup saved: {backup}")

    # ── 4. Fetch in PARALLEL ──
    from concurrent.futures import ThreadPoolExecutor, as_completed

    MAX_WORKERS = 2   # 2 threads — aggressive rate limiting avoidance
    total       = len(tickers)
    print(f"\n🚀 Fetching fundamentals for {total} stocks...")
    print(f"   Threads: {MAX_WORKERS} concurrent | Est: ~15-20 minutes\n")

    results_dict = {}
    errors       = []
    done_count   = 0

    def _fetch_one(ticker):
        time.sleep(2.0)  # generous delay between tickets to avoid rate limits
        return ticker, fetch_stock_fundamentals(ticker, finance_tickers)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}

        for future in as_completed(futures):
            ticker, row = future.result()
            results_dict[ticker] = row

            done_count += 1
            if row["FetchError"]:
                errors.append(ticker)

            if done_count % 50 == 0 or done_count == total:
                pct = done_count / total * 100
                print(f"   [{done_count:>3}/{total}] {pct:5.1f}% done | "
                      f"Errors: {len(errors)}")

    # ── 4b. RETRY failed stocks sequentially (slower but reliable) ──
    if errors:
        print(f"\n🔄 Retrying {len(errors)} failed stocks (sequential)...")
        retry_fixed = 0
        for ticker in list(errors):
            time.sleep(2)  # generous delay for retries
            row = fetch_stock_fundamentals(ticker, finance_tickers)
            if not row["FetchError"]:
                results_dict[ticker] = row
                errors.remove(ticker)
                retry_fixed += 1
        print(f"   Fixed {retry_fixed} on retry | Still failing: {len(errors)}")

    # Maintain sorted order
    results = [results_dict[t] for t in tickers if t in results_dict]

    # Preserve manual columns from existing CSV
    if existing_df is not None:
        for row in results:
            ticker = row["Ticker"]
            if ticker in existing_df.index:
                for col in manual_cols:
                    if col in existing_df.columns:
                        existing_val = existing_df.loc[ticker, col]
                        if pd.notna(existing_val):
                            row[col] = existing_val

    # ── 5. Build final DataFrame ──
    final_df = pd.DataFrame(results)

    col_order = [
        "Ticker", "Sector", "IsFinanceSector",
        "NetProfitNegative", "EBITDA_Negative",
        "ROE", "ROCE", "DebtEquity", "ICR",
        "GrossNPA_Pct", "CAR_Pct", "RevenueDecline2Yr",
        "PromoterHolding", "PromoterPledge", "PledgeIncreasing3Qtrs",
        "MarketCap_Cr", "AuditorFlag", "PromoterSelling",
        "LastUpdated", "DataSource", "FetchError",
    ]
    final_df = final_df[[c for c in col_order if c in final_df.columns]]
    final_df.to_csv(OUTPUT_CSV, index=False)

    # ── 6. Summary ──
    print("\n" + "=" * 65)
    print("✅ FETCH COMPLETE")
    print("=" * 65)
    print(f"   Total stocks        : {len(final_df)}")
    print(f"   Successfully fetched: {len(final_df) - len(errors)}")
    print(f"   Failed/errors       : {len(errors)}")

    if errors:
        err_str = ", ".join(sorted(errors)[:20])
        extra   = f" ... and {len(errors)-20} more" if len(errors) > 20 else ""
        print(f"\n   ❌ Failed: [{err_str}{extra}]")

    print(f"\n📋 FUNDAMENTAL SUMMARY:")
    print(f"   ROE < 8%           : "
          f"{(pd.to_numeric(final_df['ROE'], errors='coerce') < 8).sum()}")
    print(f"   ROCE < 10%         : "
          f"{(pd.to_numeric(final_df['ROCE'], errors='coerce') < 10).sum()}")
    print(f"   D/E > 1.5          : "
          f"{(pd.to_numeric(final_df['DebtEquity'], errors='coerce') > 1.5).sum()}")
    print(f"   Revenue decline 2yr: {final_df['RevenueDecline2Yr'].sum()}")
    print(f"   -ve Net Profit     : {final_df['NetProfitNegative'].sum()}")
    print(f"   -ve EBITDA         : {final_df['EBITDA_Negative'].sum()}")
    print(f"   MarketCap < 500 Cr : "
          f"{(pd.to_numeric(final_df['MarketCap_Cr'], errors='coerce') < 500).sum()}")

    print(f"\n💾 Saved to: {OUTPUT_CSV}")
    print(f"\n⚠️  MANUAL columns (update these yourself):")
    print(f"   PromoterHolding, PromoterPledge, PledgeIncreasing3Qtrs")
    print(f"   PromoterSelling, AuditorFlag, GrossNPA_Pct, CAR_Pct")
    print("=" * 65)

    return final_df


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    run_full_fetch()
