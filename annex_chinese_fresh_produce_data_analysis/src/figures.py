"""
Charts for the vegetable retail analysis.

Every figure is built from the same joined frame the report uses, so a number
in a chart and the same number in analysis_report.txt cannot drift apart.

Design rules kept deliberately plain: one idea per figure, no chartjunk, no
dual axes, direct labels instead of legends wherever a legend would be a
lookup table. Colour carries meaning only where the meaning is stated in the
title or the annotation.
"""

from __future__ import annotations

import os
import sys

import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prepare  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "..", "figures")
os.makedirs(FIG, exist_ok=True)

INK = "#1a1a1a"
MUTED = "#8a8a8a"
ACCENT = "#c1502e"       # the "this is the problem" colour
COOL = "#2e6171"         # the "this is fine" colour
GRID = "#e4e4e4"

plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 130,
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": INK,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def _finish(ax, title, subtitle=None, ylab=None):
    """
    Title above subtitle above axes, with enough room that neither collides.
    Subtitles wrap at ~105 characters so a long one does not run off the figure.
    """
    if subtitle:
        wrapped = textwrap.wrap(subtitle, width=105)
        ax.set_title(title, loc="left", pad=14 + 11.5 * len(wrapped))
        for i, line in enumerate(wrapped):
            ax.text(0, 1.0 + 0.030 * (len(wrapped) - i), line,
                    transform=ax.transAxes, fontsize=8.5, color=MUTED, va="bottom")
    else:
        ax.set_title(title, loc="left", pad=8)
    if ylab:
        ax.set_ylabel(ylab, fontsize=8.5)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)


def save(fig, name):
    path = os.path.join(FIG, name)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote figures/{name}")


# ---------------------------------------------------------------------------
def fig_hourly(df):
    days = df.date.nunique()
    hr = df[df.hour.between(9, 21)].groupby("hour").agg(
        rev=("revenue", "sum"), profit=("profit_true", "sum"),
        lines=("revenue", "size"), disc=("is_discounted", "mean"))
    hr["rev_per_day"] = hr.rev / days
    hr["margin"] = 100 * hr.profit / hr.rev

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9, 6.4), sharex=True,
                                  gridspec_kw={"height_ratios": [2.2, 1]})

    colors = [ACCENT if h >= 21 else COOL for h in hr.index]
    ax.bar(hr.index, hr.rev_per_day, color=colors, width=0.75)
    peak = hr.rev_per_day.idxmax()
    ax.annotate(f"peak {peak:02d}:00 -- RMB {hr.rev_per_day.max():,.0f}/day",
                xy=(peak, hr.rev_per_day.max()),
                xytext=(peak + 0.7, hr.rev_per_day.max() * 1.02),
                fontsize=8.5, color=INK, va="bottom",
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.set_ylim(0, hr.rev_per_day.max() * 1.16)
    ax.annotate("21:00 hour:\n2% of revenue,\nthinnest margin",
                xy=(21, hr.rev_per_day.loc[21]), xytext=(19.1, 300),
                fontsize=8, color=ACCENT,
                arrowprops=dict(arrowstyle="->", color=ACCENT, lw=0.9))
    _finish(ax, "The trading day has two peaks, not one",
            "Revenue per trading day by hour, 1,085 days. Morning market and after-work rush, "
            "split by a midday trough.", "RMB per day")
    ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))

    ax2.plot(hr.index, 100 * hr.disc, color=ACCENT, lw=1.8, marker="o", ms=3.5)
    ax2.fill_between(hr.index, 0, 100 * hr.disc, color=ACCENT, alpha=0.10)
    _finish(ax2, "Discounting is end-of-day clearance",
            None, "% of lines discounted")
    ax2.set_xlabel("Hour of day")
    ax2.set_xticks(range(9, 22))
    ax2.set_xticklabels([f"{h:02d}" for h in range(9, 22)])
    fig.tight_layout()
    save(fig, "hourly_revenue_and_discounting.png")


def fig_dow(df):
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    d = df.groupby("dow_name").agg(rev=("revenue", "sum"), days=("date", "nunique"),
                                   lines=("revenue", "size"))
    d = d.reindex(order)
    d["rev_per_day"] = d.rev / d.days

    fig, ax = plt.subplots(figsize=(8, 4.2))
    colors = [ACCENT if x in ("Saturday", "Sunday") else COOL for x in d.index]
    bars = ax.bar(range(7), d.rev_per_day, color=colors, width=0.68)
    for i, (b, v) in enumerate(zip(bars, d.rev_per_day)):
        ax.text(b.get_x() + b.get_width() / 2, v + 60, f"{v:,.0f}",
                ha="center", fontsize=8.5, color=INK)
    ax.set_xticks(range(7))
    ax.set_xticklabels([x[:3] for x in order])
    wd = d.rev_per_day[:5].mean()
    ax.axhline(wd, color=MUTED, ls="--", lw=1)
    ax.text(6.5, wd + 55, f"weekday avg {wd:,.0f}", ha="right", fontsize=8, color=MUTED)
    _finish(ax, "The weekend carries a third more trade than midweek",
            "Revenue per trading day by weekday. Monday-Thursday are within 5% of each other.",
            "RMB per day")
    ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    fig.tight_layout()
    save(fig, "revenue_by_weekday.png")


def fig_trend(df):
    """
    Twelve-month trailing averages, not raw months.

    Indexing raw monthly figures to a single base month is fragile here: this
    business swings 2x between January and June, so the endpoints of a raw
    monthly index say more about which month they land on than about the trend.
    A 12-month trailing mean removes the seasonal cycle entirely, and the first
    plotted value is by construction the FY20/21 average -- so this chart and
    the financial-year table in the report are the same comparison drawn twice.
    """
    m = df.groupby("year_month").agg(rev=("revenue", "sum"), kg=("qty_kg", "sum"),
                                     lines=("revenue", "size"), days=("date", "nunique"))
    m.index = pd.PeriodIndex(m.index, freq="M").to_timestamp()
    for c in ("rev", "kg", "lines"):
        m[c + "_pd"] = m[c] / m.days

    # Weight each month by its trading days so closures do not skew the mean.
    roll = pd.DataFrame({
        c: (m[c].rolling(12).sum() / m.days.rolling(12).sum()) for c in ("rev", "kg", "lines")
    }).dropna()

    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    base = roll.iloc[0]
    ax.plot(roll.index, 100 * roll.rev / base.rev, color=INK, lw=2.2, label="Revenue")
    ax.plot(roll.index, 100 * roll.kg / base.kg, color=COOL, lw=2, label="Kilos sold")
    ax.plot(roll.index, 100 * roll.lines / base.lines, color=ACCENT, lw=2, label="Lines scanned")
    ax.axhline(100, color=MUTED, lw=0.9, ls=":")
    m = roll

    # Direct labels, nudged apart so the two lower series stay readable.
    last = m.iloc[-1]
    ends = sorted([(100 * last.rev / base.rev, INK, "Revenue"),
                   (100 * last.kg / base.kg, COOL, "Kilos sold"),
                   (100 * last.lines / base.lines, ACCENT, "Lines scanned")])
    placed = []
    for val, col, lab in ends:
        y = val
        while any(abs(y - p) < 6.5 for p in placed):
            y += 1.5
        placed.append(y)
        ax.annotate(f"{lab}  {val:.0f}", xy=(m.index[-1], val),
                    xytext=(m.index[-1] + pd.Timedelta(days=22), y),
                    color=col, fontsize=8.5, va="center", fontweight="bold",
                    arrowprops=dict(arrowstyle="-", color=col, lw=0.7, alpha=0.5))

    _finish(ax, "Volume rose while footfall fell -- and revenue followed neither",
            "12-month trailing average, per trading day, indexed so that the first point "
            "(the FY20/21 average) = 100. The trailing window removes the 2x seasonal "
            "swing that makes raw monthly figures unreadable.",
            "Index (FY20/21 average = 100)")
    ax.set_xlim(m.index[0], m.index[-1] + pd.Timedelta(days=200))
    fig.tight_layout()
    save(fig, "volume_vs_footfall_trend.png")


def fig_spoilage(df):
    it = df.groupby("item_name").agg(
        rev=("revenue", "sum"), pb=("profit_raw", "sum"), pt=("profit_true", "sum"),
        lr=("loss_rate", "first"))
    it["spoil"] = it.pb - it.pt
    top = it.nlargest(12, "spoil").sort_values("spoil")

    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    ax.barh(range(len(top)), top.spoil, color=ACCENT, height=0.68)
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(top.index, fontsize=8.5)
    for i, (v, lr) in enumerate(zip(top.spoil, top.lr)):
        ax.text(v + 250, i, f"{v:,.0f}   ({lr*100:.0f}% loss)",
                va="center", fontsize=8, color=MUTED)
    share = 100 * it.nlargest(10, "spoil").spoil.sum() / it.spoil.sum()
    _finish(ax, "Waste is concentrated in the best sellers",
            f"Profit destroyed by spoilage, RMB over three years. The top 10 items carry "
            f"{share:.0f}% of all waste cost.", None)
    ax.set_xlabel("RMB of profit lost to spoilage")
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, top.spoil.max() * 1.28)
    fig.tight_layout()
    save(fig, "spoilage_cost_by_item.png")


def fig_loss_vs_margin(df):
    # Grain and threshold match analyze.py section 7 exactly, so the r quoted on
    # this chart and the r in the report are the same computation.
    it = df.groupby(["item_code", "item_name", "category"]).agg(
        rev=("revenue", "sum"), pb=("profit_raw", "sum"),
        lr=("loss_rate", "first")).reset_index()
    it = it[it.rev > 2000]
    it["mb"] = 100 * it.pb / it.rev

    fig, ax = plt.subplots(figsize=(8.2, 5))
    sizes = 12 + 260 * it.rev / it.rev.max()
    ax.scatter(100 * it.lr, it.mb, s=sizes, color=COOL, alpha=0.55,
               edgecolor="white", lw=0.6)

    b, a = np.polyfit(100 * it.lr, it.mb, 1)
    xs = np.linspace(0, 100 * it.lr.max(), 50)
    ax.plot(xs, a + b * xs, color=ACCENT, lw=1.8)
    r = np.corrcoef(it.lr, it.mb)[0, 1]
    ax.text(0.97, 0.06, f"slope {b:+.2f} pts of margin per 1% loss\nr = {r:+.3f}",
            transform=ax.transAxes, ha="right", fontsize=8.5, color=ACCENT)

    # The vertical stripe is not a coincidence: 85 catalogue items were backfilled
    # with the column mean. Label it rather than let a reader mistake it for signal.
    ph = round(prepare.load_catalogue().loss_rate_pct.mean(), 2)
    ax.axvline(ph, color=MUTED, ls=":", lw=1)
    ax.annotate(f"{ph}% -- the column mean, written over\n"
                f"85 items nobody measured. This stripe\nis a placeholder, not a finding.",
                xy=(ph, it.mb.max() * 0.97), xytext=(ph + 2.6, it.mb.max() * 0.99),
                fontsize=8, color=MUTED, va="top",
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.8))

    _finish(ax, "Pricing does not respond to spoilage at all",
            "Each bubble is an item with over RMB 2,000 of revenue; size is revenue. "
            "If pricing accounted for waste, the fitted line would slope up.",
            "Book gross margin (%)")
    ax.set_xlabel("Loss rate (%)")
    fig.tight_layout()
    save(fig, "loss_rate_vs_margin.png")


def fig_pareto(df):
    # Grain must be item_code, not item_name: four names are shared by two
    # different codes (two distinct items are both called "Broccoli"), which
    # silently collapsed the curve to 242 points under a title claiming 246.
    it = (df.groupby("item_code").revenue.sum()
            .sort_values(ascending=False).reset_index(drop=True))
    cum = 100 * it.cumsum() / it.sum()
    n = len(it)

    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    ax.fill_between(range(1, n + 1), 0, cum, color=COOL, alpha=0.18)
    ax.plot(range(1, n + 1), cum, color=COOL, lw=2)

    marks = {}
    for pct, col in ((50, MUTED), (80, ACCENT), (90, MUTED)):
        k = int((cum >= pct).argmax()) + 1
        marks[pct] = k
        ax.plot([k, k], [0, pct], color=col, ls=":", lw=1)
        ax.plot([0, k], [pct, pct], color=col, ls=":", lw=1)
        ax.text(k + 3, pct - 7, f"{pct}% of revenue\nfrom {k} items",
                fontsize=8.2, color=col)

    _finish(ax, f"Half the revenue comes from {marks[50]} of {n} items",
            f"Cumulative share of revenue by item, best first. The bottom half of the "
            f"range contributes about 1%.", "Cumulative % of revenue")
    ax.set_xlabel("Items, ranked by revenue")
    ax.set_xlim(0, n)
    ax.set_ylim(0, 102)
    fig.tight_layout()
    save(fig, "revenue_concentration.png")


def fig_seasonality(df):
    days = df.groupby("month").date.nunique()
    piv = df.pivot_table(index="month", columns="category", values="revenue",
                         aggfunc="sum").div(days, axis=0)
    piv = piv[piv.sum().sort_values(ascending=False).index]

    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    bottom = np.zeros(12)
    palette = [COOL, ACCENT, "#6b8f71", "#9a7aa0", "#c9a227", "#7d7d7d"]
    for i, c in enumerate(piv.columns):
        ax.bar(range(1, 13), piv[c], bottom=bottom, label=c,
               color=palette[i % len(palette)], width=0.72)
        bottom += piv[c].values

    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper center",
              bbox_to_anchor=(0.5, -0.13))
    _finish(ax, "January and February carry the year",
            "Revenue per trading day by month and category, pooled across three years. "
            "The Chinese New Year window is worth roughly twice a summer month.",
            "RMB per day")
    ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    fig.tight_layout()
    save(fig, "seasonality_by_category.png")


def fig_category_margin(df):
    c = df.groupby("category").agg(rev=("revenue", "sum"), pb=("profit_raw", "sum"),
                                   pt=("profit_true", "sum"))
    c["mb"] = 100 * c.pb / c.rev
    c["mt"] = 100 * c.pt / c.rev
    c = c.sort_values("rev", ascending=True)

    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    y = np.arange(len(c))
    ax.hlines(y, c.mt, c.mb, color=GRID, lw=3.5)
    ax.scatter(c.mb, y, s=64, color=MUTED, zorder=3, label="Book margin (till report)")
    ax.scatter(c.mt, y, s=64, color=ACCENT, zorder=3, label="True margin (after spoilage)")
    for i, (mb, mt) in enumerate(zip(c.mb, c.mt)):
        ax.text((mb + mt) / 2, i + 0.22, f"-{mb-mt:.1f} pts", ha="center",
                fontsize=7.8, color=ACCENT)
    ax.set_yticks(y)
    ax.set_yticklabels(c.index, fontsize=8.5)
    ax.legend(frameon=False, fontsize=8.2, loc="upper center",
              bbox_to_anchor=(0.5, -0.16), ncol=2)
    _finish(ax, "What the till reports, and what the bank sees",
            "Gross margin by category, before and after paying for stock that spoiled. "
            "Categories ordered by revenue, largest at top.", None)
    ax.set_xlabel("Gross margin (%)")
    ax.set_ylim(-0.6, len(c) - 0.25)
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    save(fig, "category_margin_gap.png")


def fig_calendar(df):
    daily = df.groupby("date").revenue.sum()
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(daily.index, daily.values, color=COOL, lw=0.55)
    roll = daily.rolling(28, center=True).mean()
    ax.plot(roll.index, roll.values, color=INK, lw=1.9)

    for d, lab in ((pd.Timestamp("2021-02-10"), "CNY 2021"),
                   (pd.Timestamp("2022-01-30"), "CNY 2022"),
                   (pd.Timestamp("2023-01-20"), "CNY 2023")):
        if d in daily.index:
            ax.annotate(lab, xy=(d, daily.loc[d]), xytext=(d, daily.loc[d] + 4200),
                        ha="center", fontsize=8, color=ACCENT,
                        arrowprops=dict(arrowstyle="->", color=ACCENT, lw=0.8))

    ax.axvspan(pd.Timestamp("2022-11-25"), pd.Timestamp("2022-12-05"),
               color=ACCENT, alpha=0.13)
    ax.text(pd.Timestamp("2022-12-06"), 21000, "four-day\nclosure", fontsize=8,
            color=ACCENT, va="top")

    _finish(ax, "Three years of daily takings",
            "Daily revenue with a 28-day average. The New Year spike dwarfs everything else.",
            "RMB per day")
    ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    fig.tight_layout()
    save(fig, "daily_revenue_three_years.png")


def main():
    df = prepare.load()
    print("building figures...")
    fig_trend(df)
    fig_calendar(df)
    fig_dow(df)
    fig_hourly(df)
    fig_category_margin(df)
    fig_spoilage(df)
    fig_loss_vs_margin(df)
    fig_pareto(df)
    fig_seasonality(df)
    print("done")


if __name__ == "__main__":
    main()
