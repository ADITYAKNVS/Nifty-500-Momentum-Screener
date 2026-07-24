"""
Beta vs Alpha Diagnostic — Long/Short Pure Alpha Model
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
import warnings

warnings.filterwarnings("ignore")

EQUITY_CURVE = "master_equity_curve_pure_alpha.csv"

def fetch_nifty50_index(start_year=2014):
    import yfinance as yf
    n50 = yf.download("^NSEI", start=f"{start_year}-01-01", progress=False)
    if isinstance(n50.columns, pd.MultiIndex):
        n50.columns = n50.columns.get_level_values(0)
    n50.reset_index(inplace=True)
    n50["Date"] = pd.to_datetime(n50["Date"]).dt.tz_localize(None)
    n50 = n50[["Date", "Close"]].rename(columns={"Close": "Nifty_Close"})
    n50["Nifty_Close"] = pd.to_numeric(n50["Nifty_Close"], errors="coerce")
    return n50.dropna().sort_values("Date").set_index("Date")

def run_diagnostic():
    print("=" * 72)
    print("🔬 BETA vs ALPHA DIAGNOSTIC — Pure Alpha Long/Short Production")
    print("=" * 72)

    eq = pd.read_csv(EQUITY_CURVE)
    eq["Date"] = pd.to_datetime(eq["Date"]).dt.tz_localize(None)
    eq = eq.sort_values("Date").set_index("Date")
    
    nifty = fetch_nifty50_index()
    
    # Merge and calculate returns
    merged = eq.join(nifty, how="inner").dropna()
    
    # Calculate returns based on the rows which are ~weekly
    merged["R_strat"] = merged["LongOnly_NAV"].pct_change()
    merged["R_market"] = merged["Nifty_Close"].pct_change()
    merged = merged.dropna()
    
    # Revert to the original daily risk-free calibration 
    rf_daily = (1 + 0.06) ** (1/252) - 1
    merged["XR_strat"] = merged["R_strat"] - rf_daily
    merged["XR_market"] = merged["R_market"] - rf_daily
    
    slope, intercept, r_value, p_value, std_err = stats.linregress(
        merged["XR_market"], merged["XR_strat"]
    )
    
    beta = slope
    # Determine precise annualization factor
    years = (merged.index[-1] - merged.index[0]).days / 365.25
    ann_factor = len(merged) / years
    alpha_ann = intercept * ann_factor
    
    r_squared = r_value ** 2
    corr = r_value
    
    # Up / Down Capture
    up_days = merged[merged["R_market"] > 0]
    dn_days = merged[merged["R_market"] < 0]
    up_capture = up_days["R_strat"].mean() / up_days["R_market"].mean() if len(up_days) else 0
    dn_capture = dn_days["R_strat"].mean() / dn_days["R_market"].mean() if len(dn_days) else 0

    # Information Ratio & Tracking Error
    active_ret = merged["R_strat"] - merged["R_market"]
    tracking_error = active_ret.std() * np.sqrt(ann_factor)
    info_ratio = (active_ret.mean() * ann_factor) / tracking_error if tracking_error > 0 else 0

    # Residual (Idiosyncratic) Volatility
    residuals = merged["XR_strat"] - (beta * merged["XR_market"] + intercept)
    idio_vol = residuals.std() * np.sqrt(ann_factor)
    total_vol = merged["R_strat"].std() * np.sqrt(ann_factor)
    systematic_vol = beta * merged["R_market"].std() * np.sqrt(ann_factor)

    print(f"  Beta (β)               : {beta:.4f}")
    print(f"  Jensen's Alpha (α ann) : {alpha_ann:+.2%}")
    print(f"  R²                     : {r_squared:.4f}")
    print(f"  Correlation (period)   : {corr:+.4f}")
    print("─" * 72)
    print(f"\n  📊 Up Capture Ratio    : {up_capture:.2%}")
    print(f"  📉 Down Capture Ratio  : {dn_capture:.2%}")
    print(f"  📐 Tracking Error (ann): {tracking_error:.2%}")
    print(f"  📈 Information Ratio   : {info_ratio:.2f}")
    print(f"\n  🔒 Total Volatility    : {total_vol:.2%}")
    print(f"  🌊 Systematic Vol (β)  : {systematic_vol:.2%}")
    print(f"  🧬 Idiosyncratic Vol   : {idio_vol:.2%}")
    
    if r_squared < 0.15:
        print("\n  🏆  PURE ALPHA CONFIRMED")
    else:
        print("\n  ⚠️  HAS SYSTEMATIC BETA EXPOSURE")

if __name__ == "__main__":
    run_diagnostic()

