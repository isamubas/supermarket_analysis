"""Generate the Mutundwe report figures.

Conventions match src/04_figures.py in the parent project: charts render on an
opaque light surface so they stay readable in GitHub's dark theme, and the
palette is the same CVD-validated pair.

Every figure carries a fictional-data stamp, because images get shared and
screenshotted separately from the README that explains them.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path

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
DATA = ROOT / "data"
FIG.mkdir(exist_ok=True)

STAMP = ("SIMULATED DATA  ·  Mutundwe Family Supermarket is a fictional chain.  "
         "Figures illustrate analytical method and describe no real business.")


def tidy(ax, ygrid=True, xgrid=False):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(BASELINE)
    ax.spines["bottom"].set_color(BASELINE)
    ax.set_axisbelow(True)
    if ygrid:
        ax.grid(axis="y", color=GRID, linewidth=0.8, linestyle="-")
    if xgrid:
        ax.grid(axis="x", color=GRID, linewidth=0.8, linestyle="-")


def finish(fig, outfile, title, subtitle, rect_top=0.88):
    fig.suptitle(title, x=0.008, ha="left", fontsize=13, fontweight="bold", y=0.985)
    fig.text(0.008, rect_top + 0.035, subtitle, ha="left", fontsize=9.5, color=SECONDARY)
    fig.text(0.008, 0.012, STAMP, ha="left", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=[0, 0.045, 1, rect_top])
    fig.savefig(FIG / outfile, dpi=200)
    plt.close(fig)
    print(" -", outfile)


# --------------------------------------------------------------------------
# Load, and strip the defects the raw export carries
# --------------------------------------------------------------------------
tx = pd.read_csv(DATA / "transactions.csv", parse_dates=["datetime"])
ln = pd.read_csv(DATA / "transaction_lines.csv", parse_dates=["date"])
pr = pd.read_csv(DATA / "products.csv")
inv = pd.read_csv(DATA / "inventory_daily.csv", parse_dates=["date"])
shr = pd.read_csv(DATA / "shrinkage.csv")
shifts = pd.read_csv(DATA / "staff_shifts.csv", parse_dates=["date"])

void_ids = set(tx.loc[tx["is_voided"], "transaction_id"])
ln = ln[~ln["transaction_id"].isin(void_ids)].merge(
    pr[["sku", "category"]], on="sku", how="left")
ln["margin"] = ln["line_total_ugx"] - ln["line_cost_ugx"]
ln["month"] = ln["date"].dt.to_period("M").astype(str)
sales_tx = tx[(~tx["is_voided"]) & (tx["shopping_mission"] != "Return")]

print("Figures written to", FIG)

# --------------------------------------------------------------------------
# 1. Revenue share vs margin share by category
# --------------------------------------------------------------------------
cat = ln.groupby("category").agg(sales=("line_total_ugx", "sum"),
                                 margin=("margin", "sum"))
cat["s_share"] = cat["sales"] / cat["sales"].sum() * 100
cat["m_share"] = cat["margin"] / cat["margin"].sum() * 100
cat["gm"] = cat["margin"] / cat["sales"] * 100
cat = cat.sort_values("sales", ascending=False).head(11)

fig, ax = plt.subplots(figsize=(10, 5.6))
y = np.arange(len(cat))
h = 0.36
ax.barh(y - h/2, cat["s_share"], height=h, color=SERIES_1, zorder=3, label="Share of sales")
ax.barh(y + h/2, cat["m_share"], height=h, color=SERIES_2, zorder=3, label="Share of gross margin")
for i, (s, m, g) in enumerate(zip(cat["s_share"], cat["m_share"], cat["gm"])):
    ax.text(max(s, m) + 0.25, i, f"GM {g:.1f}%", va="center", fontsize=8.5, color=SECONDARY)
ax.set_yticks(y, [c.replace(" - ", " – ") for c in cat.index])
ax.invert_yaxis()
ax.set_xlabel("Percent of chain total")
ax.set_xlim(0, max(cat[["s_share", "m_share"]].max()) * 1.28)
ax.legend(frameon=False, loc="lower right", fontsize=9, labelcolor=SECONDARY)
tidy(ax, ygrid=False, xgrid=True)
finish(fig, "category_revenue_vs_margin.png",
       "Revenue is not profit: where the two diverge",
       "Where the orange bar falls short of the blue one, the category consumes shelf space and working "
       "capital out of proportion to what it returns.")

# --------------------------------------------------------------------------
# 2. Monthly sales and margin — two panels, never a dual axis
# --------------------------------------------------------------------------
m = ln.groupby("month").agg(sales=("line_total_ugx", "sum"), margin=("margin", "sum"))
m["gm"] = m["margin"] / m["sales"] * 100
labels = [pd.Period(x).strftime("%b") for x in m.index]

fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1.15]})
bars = a1.bar(labels, m["sales"] / 1e6, color=SERIES_1, zorder=3, width=0.62)
peak = int(np.argmax(m["sales"].values))
bars[peak].set_color(SERIES_2)
a1.text(peak, m["sales"].iloc[peak] / 1e6 + 28, f"{m['sales'].iloc[peak]/1e6:,.0f}",
        ha="center", fontsize=9.5, fontweight="bold", color=SERIES_2)
a1.set_ylabel("Sales (UGX millions)")
tidy(a1)

a2.plot(labels, m["gm"], color=SERIES_2, linewidth=2, marker="o",
        markersize=5, zorder=3)
# Headroom so the annotated low/high labels sit inside the axes rather than
# colliding with the shared tick labels below.
a2.set_ylim(m["gm"].min() - 0.42, m["gm"].max() + 0.30)
lo, hi = int(np.argmin(m["gm"].values)), int(np.argmax(m["gm"].values))
for idx, va in ((lo, "top"), (hi, "bottom")):
    a2.annotate(f"{m['gm'].iloc[idx]:.1f}%", (idx, m["gm"].iloc[idx]),
                textcoords="offset points", xytext=(0, -16 if va == "top" else 10),
                ha="center", fontsize=9, fontweight="bold", color=INK)
a2.set_ylabel("Gross margin (%)")
a2.set_xlabel("FY2025/26  ·  July 2025 to June 2026")
tidy(a2)
finish(fig, "monthly_sales_and_margin.png",
       "The biggest selling month is the least profitable",
       "December takes 13% of the year's sales at the year's weakest margin. Plotted on two panels rather "
       "than two y-axes, so the scales cannot flatter each other.")

# --------------------------------------------------------------------------
# 3. The sugar trap
# --------------------------------------------------------------------------
sug = ln[ln["category"] == "Sugar & Sweeteners"].groupby("month").agg(
    sales=("line_total_ugx", "sum"), margin=("margin", "sum"))
sug["gm"] = sug["margin"] / sug["sales"] * 100
slab = [pd.Period(x).strftime("%b") for x in sug.index]

fig, ax = plt.subplots(figsize=(10, 4.4))
colors = [SERIES_2 if v < 0 else SERIES_1 for v in sug["gm"]]
ax.bar(slab, sug["gm"], color=colors, zorder=3, width=0.6)
ax.axhline(0, color=INK, linewidth=1.2, zorder=4)
for i, v in enumerate(sug["gm"]):
    if v < 0:
        ax.text(i, v - 0.55, f"{v:.1f}%", ha="center", va="top",
                fontsize=9, fontweight="bold", color=SERIES_2)
ax.set_ylabel("Sugar gross margin (%)")
ax.set_xlabel("FY2025/26")
tidy(ax)
finish(fig, "sugar_margin_trap.png",
       "Sugar was sold below cost for three months",
       "Mill prices rose in November; the shelf price only caught up in February. Margin is measured against "
       "the cost in force in the month of sale.")

# --------------------------------------------------------------------------
# 4. Shrinkage by branch — as a share of each branch's own sales
# --------------------------------------------------------------------------
bs = ln.groupby("branch_code")["line_total_ugx"].sum()
sb = shr.groupby("branch_code").agg(waste=("waste_cost_ugx", "sum"),
                                    unexp=("unexplained_cost_ugx", "sum"))
sb["waste_pct"] = sb["waste"] / bs * 100
sb["unexp_pct"] = sb["unexp"] / bs * 100
names = {"NAK": "Nakawa", "NTI": "Ntinda", "KAB": "Kabalagala"}
sb = sb.sort_values("unexp_pct")

fig, ax = plt.subplots(figsize=(10, 4.2))
y = np.arange(len(sb))
ax.barh(y, sb["waste_pct"], height=0.5, color=SERIES_1, zorder=3,
        label="Spoilage / expiry / damage")
ax.barh(y, sb["unexp_pct"], height=0.5, left=sb["waste_pct"], color=SERIES_2,
        zorder=3, label="Unexplained stock variance")
for i, (w, u) in enumerate(zip(sb["waste_pct"], sb["unexp_pct"])):
    ax.text(w + u + 0.06, i, f"unexplained {u:.2f}%", va="center",
            fontsize=9, color=SECONDARY,
            fontweight="bold" if u > 1 else "normal")
ax.set_yticks(y, [names[i] for i in sb.index])
ax.set_xlabel("Percent of that branch's own sales")
ax.set_xlim(0, (sb["waste_pct"] + sb["unexp_pct"]).max() * 1.32)
ax.legend(frameon=False, loc="lower right", fontsize=9, labelcolor=SECONDARY)
tidy(ax, ygrid=False, xgrid=True)
finish(fig, "shrinkage_by_branch.png",
       "One branch loses seven times more stock than its neighbours",
       "Measured against each branch's own turnover, so size is taken out of the comparison. Kabalagala is "
       "the smallest of the three.")

# --------------------------------------------------------------------------
# 5. Stockouts cluster on payday
# --------------------------------------------------------------------------
inv["dom"] = inv["date"].dt.day
so = inv.groupby("dom")["is_stockout"].mean() * 100
payday = (so.index >= 25) | (so.index <= 3)

fig, ax = plt.subplots(figsize=(11, 4.2))
ax.bar(so.index, so.values, color=np.where(payday, SERIES_2, SERIES_1),
       zorder=3, width=0.72)
ax.axhline(so.mean(), color=INK, linewidth=1.4, linestyle="--", zorder=4)
ax.text(15.5, so.mean() * 1.06, f"year average {so.mean():.2f}%",
        fontsize=9, color=SECONDARY, ha="center")
ax.set_ylabel("SKU-days out of stock (%)")
ax.set_xlabel("Day of month  ·  orange = the payday window, 25th to 3rd")
ax.set_xticks(range(1, 32, 2))
tidy(ax)
finish(fig, "stockouts_by_day_of_month.png",
       "The shelves run dry exactly when customers have money",
       "Salaries land around the 28th. Reorder points are built off an annual average that knows nothing "
       "about the pay cycle, so availability collapses in the eight days that carry 38% of turnover.")

# --------------------------------------------------------------------------
# 6. Cashier load by hour
# --------------------------------------------------------------------------
hr = sales_tx.groupby(["branch_code", "date", "hour"], as_index=False).agg(
    baskets=("transaction_id", "size"))
hr["date"] = pd.to_datetime(hr["date"])
hr = hr.merge(shifts, on=["branch_code", "date", "hour"], how="left")
hr["per_cashier"] = hr["baskets"] / hr["cashiers_rostered"]
hp = hr.groupby("hour")["per_cashier"].mean()

fig, ax = plt.subplots(figsize=(11, 4.2))
peak_mask = hp.index.isin([17, 18, 19])
ax.bar(hp.index, hp.values, color=np.where(peak_mask, SERIES_2, SERIES_1),
       zorder=3, width=0.68)
ax.axhline(hp.mean(), color=INK, linewidth=1.4, linestyle="--", zorder=4)
ax.text(8.5, hp.mean() * 1.07, f"average {hp.mean():.1f}", fontsize=9, color=SECONDARY)
for h in (17, 18, 19):
    ax.text(h, hp[h] + 0.12, f"{hp[h]:.1f}", ha="center", fontsize=9,
            fontweight="bold", color=SERIES_2)
ax.set_ylabel("Baskets per rostered cashier-hour")
ax.set_xlabel("Hour of day")
ax.set_xticks(list(hp.index))
tidy(ax)
finish(fig, "cashier_load_by_hour.png",
       "The roster is flat and the trading day is not",
       "The 18:00 cashier handles nearly four times the load of the 07:00 one for the same pay. Plotted as a "
       "single derived measure rather than baskets and headcount on two scales.")

print("\nDone.")
for f in sorted(FIG.glob("*.png")):
    print(f"   {f.name:<38} {f.stat().st_size//1024} KB")
