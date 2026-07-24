"""
Beta vs Alpha Diagnostic — Momentum V2 Strategy
═══════════════════════════════════════════════════
Determines whether the strategy return is driven by:
  • Beta (market exposure / correlation with Nifty 50)
  • Alpha (genuine skill / independent signal)

Tests:
  1. CAPM Regression: R_strategy = α + β × R_market + ε
  2. Rolling Beta (63-day & 126-day windows)
  3. Rolling Correlation
  4. Jensen's Alpha (annualized)
  5. R² — % of strategy variance explained by market
  6. Up / Down capture ratios

Outputs:
  • Console report with all statistics
  • beta_alpha_diagnostics.png  — 4-panel chart
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from scipy import stats
import warnings, os

warnings.filterwarnings("ignore")

# ─── CONFIG ───────────────────────────────────────────────────────
EQUITY_CURVE = "master_equity_curve.csv"     # Momentum V2 backtest output
RISK_FREE_ANNUAL = 0.06                       # ~6% annualised (India T-bill proxy)
ROLL_SHORT = 63                               # 3-month rolling window
ROLL_LONG  = 126                              # 6-month rolling window


def fetch_nifty50_index(start_year=2014):
    """Download Nifty 50 daily close from Yahoo Finance."""
    import yfinance as yf
    print("📡 Fetching Nifty 50 benchmark data...")
    n50 = yf.download("^NSEI", start=f"{start_year}-01-01", progress=False)
    if isinstance(n50.columns, pd.MultiIndex):
        n50.columns = n50.columns.get_level_values(0)
    n50.reset_index(inplace=True)
    n50["Date"] = pd.to_datetime(n50["Date"]).dt.tz_localize(None)
    n50 = n50[["Date", "Close"]].rename(columns={"Close": "Nifty_Close"})
    n50["Nifty_Close"] = pd.to_numeric(n50["Nifty_Close"], errors="coerce")
    return n50.dropna().sort_values("Date").set_index("Date")


def load_strategy_nav():
    """Load Momentum V2 equity curve from the backtest master."""
    print(f"📂 Loading strategy equity curve: {EQUITY_CURVE}")
    eq = pd.read_csv(EQUITY_CURVE)
    eq["Date"] = pd.to_datetime(eq["Date"]).dt.tz_localize(None)
    eq = eq[["Date", "Capital"]].rename(columns={"Capital": "Strategy_NAV"})
    return eq.sort_values("Date").set_index("Date")


def run_diagnostic():
    print("=" * 72)
    print("🔬 BETA vs ALPHA DIAGNOSTIC — Momentum V2 Strategy")
    print("=" * 72)

    # 1. Load data ────────────────────────────────────────────────
    strat = load_strategy_nav()
    nifty = fetch_nifty50_index()

    # Merge on common trading dates
    merged = strat.join(nifty, how="inner").dropna()
    print(f"   📅 Overlap Period: {merged.index[0].date()} → {merged.index[-1].date()}  "
          f"({len(merged)} trading days)")

    # Daily returns
    merged["R_strat"]  = merged["Strategy_NAV"].pct_change()
    merged["R_market"] = merged["Nifty_Close"].pct_change()
    merged = merged.dropna()

    # Risk-free daily rate
    rf_daily = (1 + RISK_FREE_ANNUAL) ** (1/252) - 1

    # Excess returns
    merged["XR_strat"]  = merged["R_strat"]  - rf_daily
    merged["XR_market"] = merged["R_market"] - rf_daily

    # ── 2. CAPM OLS Regression ──────────────────────────────────
    slope, intercept, r_value, p_value, std_err = stats.linregress(
        merged["XR_market"], merged["XR_strat"]
    )
    beta       = slope
    alpha_daily = intercept           # Jensen's daily alpha
    alpha_ann   = alpha_daily * 252   # Annualised
    r_squared   = r_value ** 2
    corr        = r_value

    # ── 3. Rolling Beta & Correlation ───────────────────────────
    def rolling_beta(xr_strat, xr_mkt, window):
        cov = xr_strat.rolling(window).cov(xr_mkt)
        var = xr_mkt.rolling(window).var()
        return cov / var

    merged["Beta_63"]   = rolling_beta(merged["XR_strat"], merged["XR_market"], ROLL_SHORT)
    merged["Beta_126"]  = rolling_beta(merged["XR_strat"], merged["XR_market"], ROLL_LONG)
    merged["Corr_63"]   = merged["XR_strat"].rolling(ROLL_SHORT).corr(merged["XR_market"])
    merged["Corr_126"]  = merged["XR_strat"].rolling(ROLL_LONG).corr(merged["XR_market"])

    # ── 4. Up / Down Capture ────────────────────────────────────
    up_days   = merged[merged["R_market"] > 0]
    dn_days   = merged[merged["R_market"] < 0]
    up_capture = up_days["R_strat"].mean() / up_days["R_market"].mean() if len(up_days) else 0
    dn_capture = dn_days["R_strat"].mean() / dn_days["R_market"].mean() if len(dn_days) else 0

    # ── 5. Monthly Return Correlation ───────────────────────────
    monthly = merged[["R_strat", "R_market"]].resample("ME").apply(
        lambda x: (1 + x).prod() - 1
    )
    monthly_corr = monthly["R_strat"].corr(monthly["R_market"])

    # ── 6. Information Ratio & Tracking Error ───────────────────
    active_ret = merged["R_strat"] - merged["R_market"]
    tracking_error = active_ret.std() * np.sqrt(252)
    info_ratio = (active_ret.mean() * 252) / tracking_error if tracking_error > 0 else 0

    # ── 7. Residual (Idiosyncratic) Volatility ──────────────────
    residuals = merged["XR_strat"] - (beta * merged["XR_market"] + alpha_daily)
    idio_vol = residuals.std() * np.sqrt(252)
    total_vol = merged["R_strat"].std() * np.sqrt(252)
    systematic_vol = beta * merged["R_market"].std() * np.sqrt(252)

    # ═══════════════════════════════════════════════
    # CONSOLE REPORT
    # ═══════════════════════════════════════════════
    print("\n" + "─" * 72)
    print("  CAPM REGRESSION:  R_strategy = α + β × R_market + ε")
    print("─" * 72)
    print(f"  Beta (β)               : {beta:.4f}")
    print(f"  Jensen's Alpha (α ann) : {alpha_ann:+.2%}")
    print(f"  R²                     : {r_squared:.4f}  ({r_squared*100:.1f}% of variance explained by market)")
    print(f"  Correlation (daily)    : {corr:+.4f}")
    print(f"  Monthly Correlation    : {monthly_corr:+.4f}")
    print(f"  p-value (β)            : {p_value:.2e}")
    print(f"  Std Error (β)          : {std_err:.4f}")
    print("─" * 72)

    print(f"\n  📊 Up Capture Ratio    : {up_capture:.2%}")
    print(f"  📉 Down Capture Ratio  : {dn_capture:.2%}")
    print(f"  📐 Tracking Error (ann): {tracking_error:.2%}")
    print(f"  📈 Information Ratio   : {info_ratio:.2f}")

    print(f"\n  🔒 Total Volatility    : {total_vol:.2%}")
    print(f"  🌊 Systematic Vol (β)  : {systematic_vol:.2%}")
    print(f"  🧬 Idiosyncratic Vol   : {idio_vol:.2%}")

    # ── VERDICT ─────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  🧪 VERDICT")
    print("=" * 72)

    if r_squared < 0.15:
        verdict = "PURE ALPHA"
        emoji = "🏆"
        desc = (f"R² = {r_squared:.2%} → Market explains less than 15% of returns.\n"
                f"  This is a genuinely independent momentum signal, NOT a levered beta play.")
    elif r_squared < 0.40:
        verdict = "ALPHA-DOMINANT"
        emoji = "✅"
        desc = (f"R² = {r_squared:.2%} → Market explains {r_squared*100:.0f}% of variance.\n"
                f"  Significant alpha exists on top of moderate market exposure.")
    elif r_squared < 0.65:
        verdict = "MIXED — Alpha + Beta"
        emoji = "⚖️"
        desc = (f"R² = {r_squared:.2%} → Strategy is ~half market, ~half alpha.\n"
                f"  Beta: {beta:.2f}. Jensen's Alpha: {alpha_ann:+.2%} annualised.")
    else:
        verdict = "BETA-DRIVEN"
        emoji = "⚠️"
        desc = (f"R² = {r_squared:.2%} → Market explains {r_squared*100:.0f}%+ of returns.\n"
                f"  This is essentially a levered market exposure with β = {beta:.2f}.")

    print(f"\n  {emoji}  {verdict}")
    print(f"  {desc}")

    if alpha_ann > 0:
        print(f"\n  ✅ Jensen's Alpha is POSITIVE ({alpha_ann:+.2%} p.a.).")
        print("     Strategy generates excess return BEYOND its market beta exposure.")
    else:
        print(f"\n  ❌ Jensen's Alpha is NEGATIVE ({alpha_ann:+.2%} p.a.).")
        print("     Strategy UNDERPERFORMS for the amount of market risk it takes.")

    print(f"\n  Rolling Beta (median 63d): {merged['Beta_63'].median():.2f}")
    print(f"  Rolling Beta (median 126d): {merged['Beta_126'].median():.2f}")
    print(f"  Rolling Corr  (median 63d): {merged['Corr_63'].median():.2f}")
    print("=" * 72)

    # ═══════════════════════════════════════════════
    # PLOTTING — 4-Panel Diagnostic Chart
    # ═══════════════════════════════════════════════
    fig, axes = plt.subplots(2, 2, figsize=(16, 12), facecolor="#0D1117")
    fig.suptitle("Beta vs Alpha Diagnostic — Momentum V2",
                 fontsize=18, fontweight="bold", color="white", y=0.98)
    fig.subplots_adjust(hspace=0.35, wspace=0.30, top=0.92, bottom=0.06)

    for ax in axes.flat:
        ax.set_facecolor("#161B22")
        ax.tick_params(colors="white", labelsize=9)
        ax.spines["bottom"].set_color("#30363D")
        ax.spines["left"].set_color("#30363D")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, alpha=0.15, color="white")

    # ── Panel 1: Scatter + CAPM Regression ──────────────────────
    ax1 = axes[0, 0]
    ax1.scatter(merged["XR_market"]*100, merged["XR_strat"]*100,
                alpha=0.15, s=8, color="#58A6FF", edgecolors="none")
    # Regression line
    x_line = np.linspace(merged["XR_market"].min(), merged["XR_market"].max(), 100)
    y_line = alpha_daily + beta * x_line
    ax1.plot(x_line*100, y_line*100, color="#F78166", linewidth=2,
             label=f"CAPM: α={alpha_ann:+.2%} β={beta:.2f} R²={r_squared:.2f}")
    ax1.axhline(0, color="#484F58", linewidth=0.5)
    ax1.axvline(0, color="#484F58", linewidth=0.5)
    ax1.set_xlabel("Market Excess Return (%)", color="white", fontsize=10)
    ax1.set_ylabel("Strategy Excess Return (%)", color="white", fontsize=10)
    ax1.set_title("CAPM Regression Scatter", color="white", fontsize=13, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=9, facecolor="#21262D", edgecolor="#30363D",
               labelcolor="white")

    # ── Panel 2: Rolling Beta ───────────────────────────────────
    ax2 = axes[0, 1]
    ax2.plot(merged.index, merged["Beta_63"], color="#7EE787", linewidth=1.0,
             alpha=0.8, label=f"Beta (63d)")
    ax2.plot(merged.index, merged["Beta_126"], color="#F78166", linewidth=1.2,
             alpha=0.9, label=f"Beta (126d)")
    ax2.axhline(1.0, color="#FF7B72", linewidth=1, linestyle="--", alpha=0.5, label="β=1 (Pure Market)")
    ax2.axhline(0.0, color="#484F58", linewidth=0.5)
    ax2.axhline(beta, color="#58A6FF", linewidth=1.5, linestyle=":", alpha=0.7,
                label=f"Full-Period β={beta:.2f}")
    ax2.set_ylabel("Beta", color="white", fontsize=10)
    ax2.set_title("Rolling Beta (Strategy vs Nifty 50)", color="white", fontsize=13, fontweight="bold")
    ax2.legend(loc="upper left", fontsize=8, facecolor="#21262D", edgecolor="#30363D",
               labelcolor="white", ncol=2)
    ax2.set_ylim(-1.5, 3.5)

    # ── Panel 3: Rolling Correlation ────────────────────────────
    ax3 = axes[1, 0]
    ax3.fill_between(merged.index, 0, merged["Corr_63"],
                     where=merged["Corr_63"] > 0, color="#7EE787", alpha=0.3)
    ax3.fill_between(merged.index, 0, merged["Corr_63"],
                     where=merged["Corr_63"] < 0, color="#FF7B72", alpha=0.3)
    ax3.plot(merged.index, merged["Corr_63"], color="#58A6FF", linewidth=1.0,
             alpha=0.8, label="63d Correlation")
    ax3.plot(merged.index, merged["Corr_126"], color="#F78166", linewidth=1.2,
             alpha=0.9, label="126d Correlation")
    ax3.axhline(0, color="#484F58", linewidth=0.5)
    ax3.axhline(monthly_corr, color="#D2A8FF", linewidth=1.5, linestyle=":",
                label=f"Monthly Corr = {monthly_corr:.2f}")
    ax3.set_ylabel("Correlation", color="white", fontsize=10)
    ax3.set_title("Rolling Correlation with Market", color="white", fontsize=13, fontweight="bold")
    ax3.legend(loc="lower left", fontsize=8, facecolor="#21262D", edgecolor="#30363D",
               labelcolor="white")
    ax3.set_ylim(-0.6, 1.0)

    # ── Panel 4: Cumulative Returns — Strategy vs Market ────────
    ax4 = axes[1, 1]
    strat_cum = (1 + merged["R_strat"]).cumprod()
    mkt_cum   = (1 + merged["R_market"]).cumprod()
    alpha_cum = strat_cum / mkt_cum   # Relative cumulative outperformance

    ax4.plot(merged.index, strat_cum, color="#7EE787", linewidth=1.5, label="Momentum V2")
    ax4.plot(merged.index, mkt_cum, color="#58A6FF", linewidth=1.5, label="Nifty 50")
    ax4.plot(merged.index, alpha_cum, color="#F78166", linewidth=1.2,
             linestyle="--", alpha=0.8, label="Relative (Strat / Market)")
    ax4.axhline(1.0, color="#484F58", linewidth=0.5)
    ax4.set_ylabel("Cumulative Growth (1 = Start)", color="white", fontsize=10)
    ax4.set_title("Cumulative Performance Attribution", color="white", fontsize=13, fontweight="bold")
    ax4.legend(loc="upper left", fontsize=8, facecolor="#21262D", edgecolor="#30363D",
               labelcolor="white")
    ax4.set_yscale("log")

    # Final annotation box
    verdict_text = f"β={beta:.2f}  |  α={alpha_ann:+.1%} p.a.  |  R²={r_squared:.2%}  |  Verdict: {verdict}"
    fig.text(0.5, 0.01, verdict_text, ha="center", fontsize=12,
             fontweight="bold", color="#7EE787" if "ALPHA" in verdict else "#FF7B72",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="#21262D", edgecolor="#30363D"))

    output_path = "beta_alpha_diagnostics.png"
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#0D1117")
    plt.close()
    print(f"\n💾 Diagnostic chart saved → {output_path}")

    # Save detailed data to CSV for further inspection
    detail_cols = ["R_strat", "R_market", "XR_strat", "XR_market",
                   "Beta_63", "Beta_126", "Corr_63", "Corr_126"]
    merged[detail_cols].to_csv("beta_alpha_detail.csv")
    print(f"💾 Detailed data saved → beta_alpha_detail.csv")


if __name__ == "__main__":
    run_diagnostic()
