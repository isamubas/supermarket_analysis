"""
Build notebooks/analysis_walkthrough.ipynb.

The notebook is generated rather than hand-edited so it cannot drift from the
analysis modules: it imports the same prepare.py the report uses, and every
number it prints is computed live at execution time.

Run this, then execute the notebook to embed outputs:
    python src/build_notebook.py
    jupyter nbconvert --execute --inplace notebooks/analysis_walkthrough.ipynb
"""

from __future__ import annotations

import os

import nbformat as nbf

HERE = os.path.dirname(os.path.abspath(__file__))
NB_DIR = os.path.join(HERE, "..", "notebooks")
os.makedirs(NB_DIR, exist_ok=True)
OUT = os.path.join(NB_DIR, "analysis_walkthrough.ipynb")

cells: list = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(text.strip("\n")))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(text.strip("\n")))


# ---------------------------------------------------------------------------
md("""
# Three years of a vegetable counter, read end to end

This notebook is the working method behind `reports/analysis_report.txt` — not a
summary of it. It shows the joins, the judgement calls and the two or three places
where the obvious approach gives the wrong answer.

**The data.** A fresh produce counter — vegetables and mushrooms, nothing else —
from 1 July 2020 to 30 June 2023: 878,503 scanned lines across 251 catalogued items
in six categories, with a daily wholesale cost series and a per-item loss rate.

**The question.** What sold, what did not, when the money came in, what went wrong,
and what to do about it.

**The one idea worth carrying through.** Every margin in this business can be
computed two ways — against what the stock cost, or against what the stock cost
*including the portion that spoiled before anyone could buy it*. The gap between
those two numbers is 19% of reported profit, and nothing in a till report will
ever show it.
""")

# --- 1 ---------------------------------------------------------------------
md("""
## 1. Loading and joining

Four files, none of which can answer a margin question alone:

| File | Grain | Carries |
|---|---|---|
| `annex1` | one row per item | name, category |
| `annex2` | one row per scanned line | date, time, quantity, price, sale/return, discount flag |
| `annex3` | one row per item-day | wholesale cost |
| `annex4` | one row per item | loss rate (%) |

`prepare.py` is the only place these are joined, so every number downstream rests
on one set of decisions rather than on whatever each notebook cell felt like doing.
""")

code("""
import sys, os
sys.path.insert(0, os.path.abspath('../src'))

import numpy as np
import pandas as pd
import prepare

pd.set_option('display.width', 170)
pd.set_option('display.max_columns', 40)

df = prepare.load()
print(prepare.summarise(df))
""")

md("""
### The first judgement call: returns

461 rows carry a negative quantity. These are returns, and there are three things
you could do with them: drop them, take their absolute value, or leave them
negative and let them net off.

Leaving them negative is the only one that makes "revenue" mean *money that stayed
in the till*. It matters less here than it would in most datasets — returns are
0.05% of lines — but the habit is worth keeping, because the cost of getting it
wrong scales with a number you do not control.
""")

code("""
returns = df[df.is_return]
print(f"return lines      {len(returns):,}")
print(f"value refunded    RMB {-returns.revenue.sum():,.0f}")
print(f"share of revenue  {100 * -returns.revenue.sum() / df.revenue.sum():.3f}%")
returns[['date', 'item_name', 'qty_kg', 'unit_price', 'revenue']].head()
""")

md("""
### The second: what a kilo actually costs

`annex3` quotes a wholesale price per item per day. The naive join takes that
price as the cost of goods sold, and it is wrong in a way that flatters the
business.

If an item loses 20% of its stock to spoilage, then selling one kilo means buying
1.25 kg. The cost of a **sold** kilo is therefore `wholesale / (1 - loss_rate)`,
not `wholesale`. Applying the loss rate as a deduction from margin instead of as a
multiplier on cost understates the damage, and understates it worst on exactly the
perishable lines where it matters most.

Both figures are carried through the whole analysis: `profit_raw` (what a till
report shows) and `profit_true` (what the bank sees).
""")

code("""
demo = (df.groupby(['item_name'])
          .agg(loss_rate=('loss_rate', 'first'),
               wholesale=('wholesale_price', 'mean'),
               price=('unit_price', 'mean'),
               revenue=('revenue', 'sum'))
          .nlargest(6, 'revenue'))

demo['true_cost']   = demo.wholesale / (1 - demo.loss_rate)
demo['margin_book'] = 100 * (demo.price - demo.wholesale) / demo.price
demo['margin_true'] = 100 * (demo.price - demo.true_cost) / demo.price
demo['points_lost'] = demo.margin_book - demo.margin_true

demo[['loss_rate', 'wholesale', 'true_cost', 'price',
      'margin_book', 'margin_true', 'points_lost']].round(2)
""")

md("""
### A coverage check worth running before trusting any of it

A cost join is only as good as its coverage. If some sold item-days have no quoted
price, the missing ones get filled — and then a chunk of the margin analysis is
resting on an assumption rather than a measurement.

Here the answer is unusually clean, which is worth confirming rather than hoping for:
""")

code("""
wp = prepare.load_wholesale()
quoted = set(zip(wp.date, wp['item_code']))
sold   = set(zip(df.date, df['item_code']))

print(f"sold item-days              {len(sold):,}")
print(f"...without a same-day quote {len(sold - quoted):,}")
print(f"rows with imputed cost      {int(df.cost_imputed.sum()):,}")
""")

# --- 2 ---------------------------------------------------------------------
md("""
## 2. The problem with `annex4`

Before any of the loss-adjusted numbers can be trusted, the loss rates themselves
need looking at. Their distribution is not what a set of measurements looks like.
""")

code("""
cat = prepare.load_catalogue()
counts = cat.loss_rate_pct.round(2).value_counts().head(6)
print(counts.to_string())
print()
print(f"mean of the whole column: {cat.loss_rate_pct.mean():.4f}")
""")

md("""
85 of 251 items carry a loss rate of **exactly 9.43%**, which is precisely the mean
of the column. That is not a coincidence and it is not a measurement — it is a
placeholder written over every item nobody measured. A further 22 items sit at
exactly 0.00%, which for fresh vegetables is not credible either.

Those 85 items are about 17% of revenue.

This does not sink the analysis, but it does bound it. The *direction* of every
finding below survives — spoilage is unpriced whichever way you cut it — while any
single per-item figure for a placeholder line is an assumption wearing two decimal
places. Section 5 shows what this looks like on a chart, where it is unmistakable.
""")

code("""
placeholder = cat.loss_rate_pct.round(2) == round(cat.loss_rate_pct.mean(), 2)
ph_rev = df[df['item_code'].isin(cat.loc[placeholder, 'item_code'])].revenue.sum()

print(f"items at the placeholder value  {placeholder.sum()} of {len(cat)}")
print(f"items at exactly 0.00%          {(cat.loss_rate_pct == 0).sum()}")
print(f"their share of revenue          {100 * ph_rev / df.revenue.sum():.1f}%")
""")

# --- 3 ---------------------------------------------------------------------
md("""
## 3. Is the business growing?

This is where a revenue-only report actively misleads. The data begins and ends on
a July–June boundary, so three clean financial years are available with no
part-year stub to explain away.
""")

code("""
fy = df.assign(fy=np.where(df.month >= 7, df.year, df.year - 1))
t = fy.groupby('fy').agg(revenue=('revenue', 'sum'),
                         kg=('qty_kg', 'sum'),
                         lines=('revenue', 'size'),
                         days=('date', 'nunique'),
                         profit_true=('profit_true', 'sum'))

for c in ('revenue', 'kg', 'lines'):
    t[c + '_pd'] = t[c] / t.days
t['price_per_kg']    = t.revenue / t.kg
t['kg_per_line']     = t.kg / t.lines
t['margin_true_pct'] = 100 * t.profit_true / t.revenue
t.index = [f"FY{y}/{str(y + 1)[2:]}" for y in t.index]

t[['revenue_pd', 'kg_pd', 'lines_pd', 'price_per_kg',
   'kg_per_line', 'margin_true_pct']].round(2)
""")

code("""
first, last = t.iloc[0], t.iloc[-1]
for label, a, b in [('Revenue/day', first.revenue_pd, last.revenue_pd),
                    ('Kilos/day',   first.kg_pd,      last.kg_pd),
                    ('Lines/day',   first.lines_pd,   last.lines_pd),
                    ('Price/kg',    first.price_per_kg, last.price_per_kg),
                    ('Kg per line', first.kg_per_line,  last.kg_per_line)]:
    print(f"{label:<14}{a:9.2f} -> {b:9.2f}   {(b / a - 1) * 100:+6.1f}%")
""")

md("""
Read those five lines together, because any one alone tells a different story:

* the shop moved **19% more produce** in year three than in year one;
* across **17% fewer scanned lines**;
* so each line got **43% heavier** — fewer, bigger purchases;
* average price per kilo fell **23%**;
* and takings landed **9% down**.

This is not a demand problem — volume grew. Revenue fell because price per kilo
fell faster than volume rose, and margin *percentage* actually improved over the
same period, so the shop is not being squeezed on markup either.

What cannot be settled here is whether "fewer lines" means fewer customers or the
same customers buying vegetables elsewhere. There is no customer ID in these files,
and they cover only the produce counter. Both readings fit, and they call for
opposite responses, so it is worth resolving before acting on it.

One caution on the comparison: FY21/22 is the trough on every measure, so year one
against year three skips over a disrupted middle rather than describing a smooth
trend.
""")

# --- 4 ---------------------------------------------------------------------
md("""
## 4. When the money arrives

Two separate questions that often get merged: *which days*, and *which hours*.
""")

code("""
daily = df.groupby('date').agg(revenue=('revenue', 'sum'), lines=('revenue', 'size'))
top10 = daily.nlargest(10, 'revenue')
top10.assign(weekday=top10.index.day_name()).round(0)
""")

code("""
cny = [pd.Timestamp(d) for d in ('2021-02-12', '2022-02-01', '2023-01-22')]
near = sum(any(0 <= (c - d).days <= 7 for c in cny) for d in top10.index)

print(f"top-10 days falling in the week before Chinese New Year: {near}")
print(f"best day vs median day: {top10.revenue.iloc[0] / daily.revenue.median():.1f}x")
""")

md("""
Eight of the ten best days in three years fall in the week before Chinese New Year.
The two exceptions are 19 and 21 November 2022 — which sit immediately before a
four-day unplanned closure, so they are stockpiling ahead of a shutdown rather than
ordinary trade.

That is a genuinely useful planning fact: the largest revenue event of the year is
known to the calendar, lasts about four days, and repeats in all three years here.
""")

code("""
order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
d = df.groupby('dow_name').agg(revenue=('revenue', 'sum'),
                               lines=('revenue', 'size'),
                               days=('date', 'nunique')).reindex(order)
d['rev_per_day']   = d.revenue / d.days
d['lines_per_day'] = d.lines / d.days
d[['rev_per_day', 'lines_per_day']].round(0)
""")

code("""
days = df.date.nunique()
hr = df.groupby('hour').agg(revenue=('revenue', 'sum'),
                            profit_true=('profit_true', 'sum'),
                            lines=('revenue', 'size'))
hr['rev_per_day'] = hr.revenue / days
hr['margin_pct']  = 100 * hr.profit_true / hr.revenue
hr['pct_of_rev']  = 100 * hr.revenue / hr.revenue.sum()
hr.loc[9:21, ['rev_per_day', 'margin_pct', 'pct_of_rev']].round(2)
""")

md("""
The trading day has **two peaks, not one** — a 09:00–11:00 market run and a
16:00–18:00 after-work rush, split by a midday trough at about a third of peak.

The 21:00 hour is the one to look at twice: 2% of revenue at the thinnest margin of
the day, and the most heavily discounted hour. It is the weakest hour on all three
measures at once.
""")

# --- 5 ---------------------------------------------------------------------
md("""
## 5. Where the money actually leaks

The tempting framing is "which products lose money". On this data that framing
finds almost nothing, and the reason it finds nothing is the interesting part.
""")

code("""
# Grain is item_code -- the real key. Two different items can share a name.
it = df.groupby(['item_code', 'item_name', 'category']).agg(
        revenue=('revenue', 'sum'),
        profit_book=('profit_raw', 'sum'),
        profit_true=('profit_true', 'sum'),
        loss_rate=('loss_rate', 'first')).reset_index()

trap = it[(it.profit_book > 0) & (it.profit_true < 0)]
print(f"items that flip from profit to loss once spoilage is paid for: {len(trap)}")
print(f"their combined true loss: RMB {-trap.profit_true.sum():,.0f}")
print()
print(f"total cost of spoilage across the business: "
      f"RMB {(it.profit_book - it.profit_true).sum():,.0f}")
""")

md("""
Only two items flip sign, and between them they lose about RMB 21. As a headline
that would be trivia.

The real number is **RMB 239,699** — and it is spread across the whole book as a
7-point haircut on margin rather than concentrated in a few rotten lines. Markups
here average about 1.6x, wide enough that spoilage rarely pushes an item negative.
It just quietly takes a fifth of the profit on everything at once.

So the list worth acting on is not "which items lose money" but **"which items
destroy the most profit through waste"** — and because waste is loss rate
multiplied by volume, that list is the *best sellers*, not the worst.
""")

code("""
it['spoilage_cost'] = it.profit_book - it.profit_true
top = it.nlargest(10, 'spoilage_cost')
share = 100 * top.spoilage_cost.sum() / it.spoilage_cost.sum()

print(f"top 10 items carry {share:.1f}% of all spoilage cost\\n")
top[['item_name', 'category', 'revenue', 'loss_rate', 'spoilage_cost']].round(2)
""")

md("""
### Does pricing respond to spoilage at all?

If the business priced for waste, high-loss items would carry higher markups. The
correlation says otherwise.
""")

code("""
it['margin_book_pct'] = 100 * it.profit_book / it.revenue

big = it[it.revenue > 2000]
r = big[['loss_rate', 'margin_book_pct']].corr().iloc[0, 1]
slope = np.polyfit(100 * big.loss_rate, big.margin_book_pct, 1)[0]
print(f"correlation, loss rate vs book margin: {r:+.3f}  (n = {len(big)})")
print(f"slope: {slope:+.3f} margin points per 1 point of loss rate")

# The revenue floor is an arbitrary choice, so check the answer does not depend on it.
print()
for thr in (0, 500, 1000, 2000, 5000, 10000):
    v = it[it.revenue > thr]
    print(f"  revenue > {thr:>6,}   n = {len(v):>3}   "
          f"r = {v[['loss_rate', 'margin_book_pct']].corr().iloc[0, 1]:+.3f}")
""")

md("""
Effectively zero — and it stays effectively zero at every revenue floor, so this is
not an artefact of where the cut was made. An item that bins a quarter of its stock
carries the same markup as one that bins none.

This is the clearest structural fault in the data and the cheapest to fix: price
from `cost / (1 - loss_rate)` rather than from `cost`, then apply the target
margin. On a 25%-loss line that is about a third more markup than today — one
formula in a pricing sheet.
""")

code("""
target = 0.20
worst = it.nlargest(8, 'loss_rate')[['item_name', 'loss_rate']].copy()
worst['markup_today']    = 1 / (1 - target)
worst['markup_required'] = 1 / ((1 - target) * (1 - worst.loss_rate))
worst['uplift_pct']      = 100 * (worst.markup_required / worst.markup_today - 1)
worst.round(3)
""")

# --- 6 ---------------------------------------------------------------------
md("""
## 6. Is discounting destroying value?

The instinct is that markdowns bleed money. Worth checking rather than assuming.
""")

code("""
g = df.groupby('is_discounted').agg(lines=('revenue', 'size'),
                                    revenue=('revenue', 'sum'),
                                    kg=('qty_kg', 'sum'),
                                    profit_true=('profit_true', 'sum'))
g.index = ['Full price', 'Discounted']
g['margin_true_pct'] = 100 * g.profit_true / g.revenue
g['avg_price']       = g.revenue / g.kg
g['pct_of_lines']    = 100 * g.lines / g.lines.sum()
g.round(2)
""")

code("""
by_hour = (df.groupby('hour').is_discounted.mean() * 100).loc[9:21]
by_hour.round(1).to_frame('pct_of_lines_discounted')
""")

md("""
Two things come out of this, and the second reverses the intuition:

1. Discounting is **end-of-day clearance** — 3% of lines before noon, 27% in the
   21:00 hour. That is the right instinct, applied at the right time.
2. Discounted stock still returns **+9.7% true margin**. It is not destroying
   value; it is recovering cash from stock that would otherwise be binned at a
   100% loss.

So the markdown is not the problem. The problem is upstream: the volume of stock
that needs clearing at all. The evening clearance pile is the visible end of a
morning over-order, and that is where the fix belongs.
""")

# --- 7 ---------------------------------------------------------------------
md("""
## 7. The range

How much of the range is actually doing work?
""")

code("""
rev = df.groupby('item_code').revenue.sum().sort_values(ascending=False)
cum = 100 * rev.cumsum() / rev.sum()

for pct in (50, 80, 90, 99):
    k = int((cum >= pct).argmax()) + 1
    print(f"{pct}% of revenue from the top {k:>3} items  ({100 * k / len(rev):.1f}% of the range)")

bottom = rev.tail(len(rev) // 2)
print(f"\\nbottom half of the range: {100 * bottom.sum() / rev.sum():.1f}% of revenue")
""")

md("""
The curve shows the shape but not who is in it. Cutting the ranked list into bands
and naming them is what makes it actionable.

Note the grain: **item_code, not item_name**. Four names are shared by two different
codes — two distinct items are both called "Broccoli" — so ranking by name silently
merges them and gets the counts wrong.
""")

code("""
r = (df.groupby(['item_code', 'item_name', 'category'])
       .agg(revenue=('revenue', 'sum'),
            profit_true=('profit_true', 'sum'),
            loss_rate=('loss_rate', 'first'))
       .sort_values('revenue', ascending=False).reset_index())
r['pct'] = 100 * r.revenue / r.revenue.sum()
r['cum'] = r.pct.cumsum()
r['margin_true_pct'] = 100 * r.profit_true / r.revenue
r['loss_rate_pct'] = 100 * r.loss_rate

bands, start = [], 0
for pct, letter in [(50, 'A'), (80, 'B'), (90, 'C'), (99, 'D'), (100, 'E')]:
    stop = int((r.cum >= pct).argmax()) + 1 if pct < 100 else len(r)
    g = r.iloc[start:stop]
    bands.append({'band': letter, 'ranks': f"{start+1}-{stop}", 'items': len(g),
                  'revenue': g.revenue.sum(), 'pct_revenue': g.pct.sum(),
                  'rev_per_item': g.revenue.mean()})
    start = stop

pd.DataFrame(bands).set_index('band').round(1)
""")

code("""
# Band A -- the items that make the first half of the money.
a_stop = int((r.cum >= 50).argmax()) + 1
r.head(a_stop)[['item_name', 'category', 'revenue', 'pct', 'cum',
                'margin_true_pct', 'loss_rate_pct']].round(2)
""")

code("""
# Band B -- the next 30%.
b_stop = int((r.cum >= 80).argmax()) + 1
r.iloc[a_stop:b_stop][['item_name', 'category', 'revenue', 'pct', 'cum',
                       'margin_true_pct', 'loss_rate_pct']].round(2)
""")

md("""
A band-A item earns roughly **430x** what a band-E item earns — from the same shelf,
the same ordering decision and the same spoilage risk.

Two cautions before anyone acts on the band tables:

* **"Chinese Cabbage" appears twice in band B** as two item codes with different loss
  rates. A catalogue quirk, not a duplicate row.
* **8 of the 42 items in bands A and B carry the 9.43% placeholder loss rate**, so
  their true-margin figures are estimates. They are also among the most valuable lines
  in the business, which makes them the obvious place to start measuring for real.
""")

code("""
end = df.date.max()
life = df.groupby('item_name').agg(revenue=('revenue', 'sum'),
                                   days_sold=('date', 'nunique'),
                                   last_sale=('date', 'max'))
life['days_since_last_sale'] = (end - life.last_sale).dt.days

dead = life[life.days_since_last_sale > 180]
thin = life[life.days_sold <= 10]

print(f"no sale in the final 6 months : {len(dead):>3} items, "
      f"{100 * dead.revenue.sum() / life.revenue.sum():.1f}% of 3-year revenue")
print(f"sold on 10 days or fewer      : {len(thin):>3} items, "
      f"{100 * thin.revenue.sum() / life.revenue.sum():.1f}% of 3-year revenue")
""")

md("""
Half the revenue comes from 14 items out of 246. The bottom half of the range
contributes about 1%.

The honest reading of the dead tail is not "these products failed" — it is that
they were listed once and never reviewed. And the payoff from delisting them is
not revenue, because there is none. It is the ordering attention and shelf space
returned to the top decile, which is volume-constrained rather than
demand-constrained.

**One caveat that limits every "weak seller" verdict here:** this data cannot
distinguish *no demand* from *no stock*. An item that sold nothing on a Tuesday
may have had no customers or may have been out of stock, and nothing in these four
files separates the two.
""")

# --- 8 ---------------------------------------------------------------------
md("""
## 8. Price sensitivity, and why to distrust it

A log–log fit of daily kilos against daily average price gives an elasticity per
item. It is worth computing and worth heavily caveating.
""")

code("""
sales = df[~df.is_return]
d = sales.groupby(['item_name', 'category', 'date']).agg(
        kg=('qty_kg', 'sum'), revenue=('revenue', 'sum')).reset_index()
d['price'] = d.revenue / d.kg
d = d[(d.kg > 0) & (d.price > 0)]

rows = []
for (name, cat_), g in d.groupby(['item_name', 'category']):
    if len(g) < 90 or g.price.nunique() < 20:
        continue
    x, y = np.log(g.price.values), np.log(g.kg.values)
    beta = np.polyfit(x, y, 1)[0]
    rows.append({'item_name': name, 'category': cat_, 'elasticity': beta,
                 'r': np.corrcoef(x, y)[0, 1], 'revenue': g.revenue.sum()})

el = pd.DataFrame(rows)
print(f"fitted on {len(el)} items")
print(f"median elasticity {el.elasticity.median():.2f}, "
      f"revenue-weighted {np.average(el.elasticity, weights=el.revenue):.2f}")
el.nsmallest(8, 'elasticity').round(3)
""")

code("""
el.nlargest(8, 'elasticity').round(3)
""")

md("""
That second table is the useful one, because it is **wrong** in an instructive way.

A positive elasticity says people buy *more* as price *rises*, which no customer
does. Every one of those items is a pre-packed bagged line sold at a near-fixed
price, where the few price changes coincide with festival weeks when volume is high
for unrelated reasons. The correlations are weak and the sign is backwards.

More generally these fits are observational, not experimental. Price and volume
both move with supply — a glut lowers price and raises volume simultaneously — so
the slopes conflate a demand curve with a supply curve. They rank items usefully.
They do not predict what happens if you change a price, and should not be quoted
as if they do.
""")

# --- 9 ---------------------------------------------------------------------
md("""
## 9. What the figures show

Generated by `src/figures.py` from this same frame, so a number on a chart and the
same number in the report cannot disagree.
""")

code("""
from IPython.display import Image, display
for f in ['volume_vs_footfall_trend.png',
          'daily_revenue_three_years.png',
          'hourly_revenue_and_discounting.png',
          'category_margin_gap.png',
          'spoilage_cost_by_item.png',
          'loss_rate_vs_margin.png',
          'revenue_concentration.png']:
    display(Image(filename=f'../figures/{f}'))
""")

# --- 10 --------------------------------------------------------------------
md("""
## 10. Conclusions

**What went wrong**

1. **Footfall is draining while volume grows.** Lines per day fell 17% as kilos
   rose 19%. Revenue held up on bigger baskets and cheaper produce, which is a
   position that works right up until it does not — and no revenue-only report
   would show it.
2. **Spoilage is not priced in, anywhere.** RMB 239,699 of reported profit never
   existed. The correlation between an item's loss rate and its markup is +0.05 —
   indistinguishable from zero at any revenue threshold.
3. **Waste concentrates in the best sellers.** The top 10 items carry 44% of all
   spoilage cost, because waste is loss rate times volume.
4. **The range has a long unreviewed tail.** 60 items sold on ten days or fewer;
   110 have not sold at all in the final six months.
5. **The last trading hour does not pay for itself.** 2% of revenue at the
   thinnest margin and the heaviest discounting of the day.

**What to do**

| Action | Why it is the right size of fix |
|---|---|
| Price from `cost / (1 - loss_rate)` | One formula; recovers the single largest leak in the data |
| Attack the top 10 waste items specifically | 44% of waste cost sits in a list short enough to act on this week |
| Put lines/day on the revenue chart | The erosion is invisible on revenue alone |
| Quarterly range review, 90-day delist rule | Returns ordering attention to the lines that are volume-constrained |
| Split the delivery: heavy pre-09:00, light pre-16:00 | Fixes what feeds the evening clearance pile, rather than the markdown itself |
| Close at 21:00, move the hour to 09:00–11:00 | A roster change, not an investment |

**Where this stops.** Worth being explicit, because the limits bound every
recommendation above:

* One produce counter, not a shop — vegetables and mushrooms only, so nothing here
  describes the rest of the store.
* No basket or customer ID — nothing here counts shoppers or measures basket size.
* No stock-on-hand — spoilage is a per-item rate, not an observed daily loss, and
  85 of those rates are placeholders.
* Stockouts are invisible — *no demand* and *no stock* look identical.
* Everything below gross margin is absent. Rent, wages, power and transport are
  not in these files, so nothing here says whether the business is profitable —
  only which lines and hours contribute most to covering costs it cannot see.
""")

# ---------------------------------------------------------------------------
nb = nbf.v4.new_notebook(cells=cells)
nb.metadata = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}

with open(OUT, "w", encoding="utf-8") as fh:
    nbf.write(nb, fh)

print(f"wrote {OUT} ({len(cells)} cells)")
