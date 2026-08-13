"""Generate the report figures.

Charts render on an opaque light surface so they stay readable in GitHub's
dark theme (a transparent PNG with dark ink is unreadable there).
Palette: dataviz reference slots 1-2, validated for CVD separation.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

SURFACE   = "#fcfcfb"
SERIES_1  = "#2a78d6"
SERIES_2  = "#eb6834"
INK       = "#0b0b0b"
SECONDARY = "#52514e"
MUTED     = "#898781"
GRID      = "#e1e0d9"
BASELINE  = "#c3c2b7"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans"], "font.size": 10,
    "axes.edgecolor": BASELINE, "axes.linewidth": 0.8,
    "text.color": INK, "axes.labelcolor": SECONDARY,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 9, "ytick.labelsize": 9,
})

ROOT = Path(__file__).resolve().parent.parent
FIG  = ROOT / "figures"
df = pd.read_excel(ROOT / "data" / "supermarket.xls")
df["hour"] = pd.to_datetime(df["time"].astype(str), format="mixed").dt.hour


def tidy(ax, ygrid=True):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(BASELINE)
    ax.spines["bottom"].set_color(BASELINE)
    if ygrid:
        ax.set_axisbelow(True)
        ax.grid(axis="y", color=GRID, linewidth=0.8, linestyle="-")


def ci95(x):
    """95% CI half-width for a mean."""
    return 1.96 * np.std(x, ddof=1) / np.sqrt(len(x))


def overlap_chart(group_col, title, subtitle, outfile, label_map=None):
    """Mean transaction value by segment, with 95% CIs and the grand mean."""
    g = df.groupby(group_col)["cost"]
    stats_df = pd.DataFrame({"mean": g.mean(), "ci": g.apply(ci95), "n": g.size()})
    stats_df = stats_df.sort_values("mean", ascending=False)
    labels = [label_map.get(i, i) if label_map else i for i in stats_df.index]

    fig, ax = plt.subplots(figsize=(9, 4.6))
    y = np.arange(len(stats_df))
    ax.barh(y, stats_df["mean"], height=0.42, color=SERIES_1, zorder=3)
    ax.errorbar(stats_df["mean"], y, xerr=stats_df["ci"], fmt="none",
                ecolor=INK, elinewidth=1.4, capsize=5, capthick=1.4, zorder=4)

    grand = df["cost"].mean()
    ax.axvline(grand, color=SERIES_2, linewidth=2, zorder=5)
    # sits in the top margin: the y-axis is inverted, so -0.42 is above the first bar
    ax.text(grand, -0.42, f"  overall mean  {grand:,.0f} EGP",
            color=SERIES_2, fontsize=9, va="center", fontweight="bold")

    for i, (m, c) in enumerate(zip(stats_df["mean"], stats_df["ci"])):
        ax.text(m + c + 8, i, f"{m:,.0f}", va="center", fontsize=9, color=SECONDARY)

    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Mean transaction value (EGP)  ·  bars show 95% confidence interval")
    ax.set_xlim(0, max(stats_df["mean"] + stats_df["ci"]) * 1.18)
    tidy(ax, ygrid=False)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    fig.suptitle(title, x=0.012, ha="left", fontsize=13, fontweight="bold", y=0.98)
    ax.set_title(subtitle, loc="left", fontsize=9.5, color=SECONDARY, pad=10)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(FIG / outfile, dpi=200)
    plt.close(fig)


overlap_chart(
    "city", "Branch performance: no real difference",
    "Every confidence interval crosses the overall mean. ANOVA p = 0.41 — the gaps are sampling noise.",
    "revenue_by_branch.png")

overlap_chart(
    "type", "Product lines: no real difference",
    "All six intervals overlap. ANOVA p = 0.89 — ranking these categories is ranking noise.",
    "revenue_by_product.png")

# --- The authenticity evidence -------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.2))
panels = [
    ("unit_price", 10, 100, "Unit price (EGP)", "KS p = 0.50"),
    ("quantity",    1,  10, "Quantity per sale", "chi2 p = 0.30"),
    ("rating",      4,  10, "Customer rating",   "KS p = 0.53"),
]
for ax, (col, lo, hi, xlabel, pval) in zip(axes, panels):
    bins = np.arange(0.5, 11.5, 1) if col == "quantity" else 12
    n, edges, _ = ax.hist(df[col], bins=bins, color=SERIES_1,
                          edgecolor=SURFACE, linewidth=1.6, zorder=3,
                          label="Observed")
    expected = len(df) / len(n)
    ax.axhline(expected, color=SERIES_2, linewidth=2, zorder=4,
               label="Expected if random")
    ax.set_xlabel(xlabel, fontsize=9.5)
    ax.set_ylim(0, max(n) * 1.35)
    ax.text(0.5, 0.94, pval, transform=ax.transAxes, ha="center",
            fontsize=9, color=SECONDARY, fontweight="bold")
    tidy(ax)
axes[0].set_ylabel("Number of transactions")
axes[0].legend(frameon=False, loc="upper left", fontsize=8.5, labelcolor=SECONDARY)
fig.suptitle("Every numeric field is indistinguishable from a random number generator",
             x=0.008, ha="left", fontsize=13, fontweight="bold", y=0.99)
fig.text(0.008, 0.90,
         "Real retail data is lumpy — price points cluster, most baskets are small, ratings skew high. "
         "None of that is present here.",
         ha="left", fontsize=9.5, color=SECONDARY)
fig.tight_layout(rect=[0, 0, 1, 0.87])
fig.savefig(FIG / "uniformity_evidence.png", dpi=200)
plt.close(fig)

# --- Daily revenue --------------------------------------------------------
daily = df.groupby("date")["cost"].sum()
fig, ax = plt.subplots(figsize=(12.5, 4))
ax.plot(daily.index, daily.values, color=SERIES_1, linewidth=1.6, zorder=3)
ax.axhline(daily.mean(), color=SERIES_2, linewidth=2, zorder=4,
           label=f"Mean {daily.mean():,.0f} EGP/day")
ax.set_ylabel("Daily revenue (EGP)")
ax.set_xlabel("2019")
ax.legend(frameon=False, loc="upper right", fontsize=9, labelcolor=SECONDARY)
tidy(ax)
fig.suptitle("Daily revenue: noise around a flat line", x=0.008, ha="left",
             fontsize=13, fontweight="bold", y=0.98)
ax.set_title("No trend, no weekly rhythm, no seasonality across the 89-day window.",
             loc="left", fontsize=9.5, color=SECONDARY, pad=10)
fig.tight_layout(rect=[0, 0, 1, 0.95])
fig.savefig(FIG / "daily_revenue.png", dpi=200)
plt.close(fig)

print("Figures written to", FIG)
for f in sorted(FIG.glob("*.png")):
    print(" -", f.name, f"({f.stat().st_size//1024} KB)")
