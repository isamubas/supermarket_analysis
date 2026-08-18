# Annex Chinese Fresh Produce — three years of a vegetable counter

A full sales, margin and waste analysis of an item-level retail ledger:
**878,503 scanned lines, 251 catalogued items, 1,085 trading days**, from
1 July 2020 to 30 June 2023.

Unlike the simulated [`mutundwe_kampala`](../mutundwe_kampala) dataset in this
repository, **this is a real transaction ledger** — with the gaps, placeholders and
awkward edges that real data has. Several of the more interesting findings below are
about those edges rather than about vegetables.

> ### Scope: this is one fresh produce counter
>
> It is all vegetables and mushrooms. **No meat, dairy, rice, oil, drinks or
> packaged goods** anywhere in the 251-item catalogue.
>
> | Category | % of revenue | What it is |
> |---|---|---|
> | Flower/Leaf Vegetables | 32.0% | leaf greens, herbs |
> | Capsicum | 22.4% | peppers and chillies |
> | Edible Mushroom | 18.4% | mushrooms |
> | Cabbage | 11.2% | cabbage, broccoli |
> | Aquatic Tuberous Vegetables | 10.4% | lotus root, water chestnut |
> | Solanum | 5.7% | aubergine |
>
> Two findings below are bounded by this:
>
> - **"Traffic" means lines scanned at this counter**, not shoppers in the store.
>   A fall could be fewer customers, or the same customers buying vegetables
>   elsewhere.
> - **The 21:00 finding is about staffing this counter**, not about closing a shop.

---

## The finding, in one line

> The business reports a **36.9% gross margin**. Once the stock that spoiled before
> anyone could buy it is paid for, the real figure is **29.8%** — and **RMB 239,699**
> of three-year "profit" turns out never to have existed.

Nothing in a till report will ever show that gap, because a till only sees the kilos
that scanned. It never sees the ones that went in the bin.

---

## Contents

| Path | What it is |
|---|---|
| [`notebooks/analysis_walkthrough.ipynb`](notebooks/analysis_walkthrough.ipynb) | **Start here.** The full method, with outputs and charts rendered inline |
| [`reports/analysis_report.txt`](reports/analysis_report.txt) | The complete 12-section findings report |
| [`reports/findings.json`](reports/findings.json) | Every figure in the report, machine-readable |
| [`src/prepare.py`](src/prepare.py) | Loads and joins the four annexes — the only place joins happen |
| [`src/analyze.py`](src/analyze.py) | The analysis pass; writes the report and the JSON |
| [`src/figures.py`](src/figures.py) | The nine charts |
| [`src/build_notebook.py`](src/build_notebook.py) | Generates the notebook, so it cannot drift from the modules |
| `data/` | The four raw annexes, unmodified |

### Running it

```bash
pip install -r ../requirements.txt
```

```bash
python src/prepare.py && python src/analyze.py && python src/figures.py
```

To regenerate the notebook and re-execute it end to end:

```bash
python src/build_notebook.py && python -m nbconvert --execute --inplace notebooks/analysis_walkthrough.ipynb
```

---

## The data

Four files that each answer part of the question and none of which answer it alone:

| File | Grain | Carries |
|---|---|---|
| `annex1.csv` | one row per item | item name, category (6 categories, 251 items) |
| `annex2.csv` | one row per scanned line | date, time, quantity (kg), unit price, sale/return, discount flag |
| `annex3.csv` | one row per item-day | wholesale cost that day |
| `annex4.csv` | one row per item | loss rate (%) |

**Coverage is unusually good.** All 46,599 sold item-days have a same-day wholesale
quote, so no cost is estimated anywhere in this analysis. That is worth checking
before trusting a margin number, and it is rarer than it sounds.

### The one thing that has to be got right

If an item loses 20% of its stock to spoilage, selling one kilo means *buying* 1.25 kg.
So the true cost of a sold kilo is:

```
true_cost = wholesale_price / (1 - loss_rate)
```

Treating the loss rate as a deduction from margin instead of a multiplier on cost
understates the damage — and understates it worst on exactly the perishable lines
where it matters most. Every margin in this analysis is therefore reported twice:
**book** (what the till shows) and **true** (what the bank sees).

---

## What went wrong

### 1. Footfall is draining away while volume grows

Comparing the first financial year to the third, per trading day:

| | FY20/21 | FY22/23 | Change |
|---|---|---|---|
| Revenue | RMB 3,542 | RMB 3,224 | **−9.0%** |
| Kilos sold | 451 | 536 | **+18.9%** |
| Lines scanned | 957 | 796 | **−16.8%** |
| Price per kg | RMB 7.85 | RMB 6.01 | **−23.4%** |
| Kg per line | 0.47 | 0.67 | **+42.8%** |

![Volume versus footfall](figures/volume_vs_footfall_trend.png)

The shop moved **19% more produce across 17% fewer transactions**. Each purchase got
43% heavier while price per kilo fell 23%, and takings landed 9% down.

This is not a demand problem — volume grew, and margin percentage actually *improved*
(28.3% → 32.5%). But a revenue-only report would show a business roughly holding
steady, while the transaction count eroded underneath it.

> **What this data cannot say:** whether "fewer lines" means fewer customers or the
> same customers consolidating trips. There is no basket or customer ID in these
> files. Both readings fit, and they call for opposite responses.

### 2. Spoilage is not priced in — anywhere

![Loss rate versus margin](figures/loss_rate_vs_margin.png)

The correlation between an item's loss rate and its markup is **+0.047**. It stays
near zero at every revenue threshold tested, and turns *negative* at one of them.

An item that bins a quarter of its stock carries the same markup as one that bins none.

**The fix is one formula:** price from `cost / (1 - loss_rate)` rather than from
`cost`, then apply the target margin. On a 25%-loss line that is about a third more
markup than today.

### 3. Waste concentrates in the best sellers, not the worst

![Spoilage cost by item](figures/spoilage_cost_by_item.png)

Only **2 items** actually flip from profit to loss once spoilage is paid for, and
between them they lose about RMB 21. Framing this as "which products lose money"
finds almost nothing.

The real damage is **RMB 239,699**, spread across the whole book as a 7-point margin
haircut. Markups here average 1.6x — wide enough that spoilage rarely pushes a line
negative. It just quietly takes a fifth of the profit on everything at once.

Because waste is loss rate *times volume*, it lands hardest on the biggest sellers.
**The top 10 items carry 44% of all spoilage cost** — a list short enough to act on
this week.

### 4. Half the range does no work

![Revenue concentration](figures/revenue_concentration.png)

Cut the ranked list into bands, and the shape of the business is obvious:

| Band | Ranks | Items | Revenue | Share | Avg per item |
|---|---|---|---|---|---|
| **A** | 1–14 | 14 | RMB 1,698,933 | **50.4%** | RMB 121,352 |
| **B** | 15–42 | 28 | RMB 1,011,768 | 30.0% | RMB 36,135 |
| **C** | 43–64 | 22 | RMB 326,030 | 9.7% | RMB 14,820 |
| **D** | 65–130 | 66 | RMB 300,263 | 8.9% | RMB 4,549 |
| **E** | 131–246 | 116 | RMB 32,772 | 1.0% | RMB 283 |

**A band-A item earns 430× what a band-E item earns** — from the same shelf, the same
ordering decision, and the same risk of spoiling.

### Band A — the 14 items that make the first half of the money

| # | Item | Category | Revenue | Share | True margin | Loss rate |
|---|---|---|---|---|---|---|
| 1 | Broccoli | Cabbage | 269,874 | 8.01% | 26.6% | 9.26% |
| 2 | Net Lotus Root (1) | Aquatic Tuberous | 211,652 | 6.28% | 25.3% | 5.54% |
| 3 | Xixia Mushroom (1) | Edible Mushroom | 211,198 | 6.27% | 23.2% | 13.82% |
| 4 | Wuhu Green Pepper (1) | Capsicum | 205,114 | 6.09% | 25.7% | 5.70% |
| 5 | Yunnan Shengcai | Flower/Leaf | 129,757 | 3.85% | 27.5% | 15.25% |
| 6 | Eggplant (2) | Solanum | 117,729 | 3.49% | 29.8% | 6.07% |
| 7 | Paopaojiao (Jingpin) | Capsicum | 95,569 | 2.84% | 21.6% | 7.08% |
| 8 | Luosi Pepper | Capsicum | 82,009 | 2.43% | 26.9% | 10.18% |
| 9 | Yunnan Lettuces | Flower/Leaf | 70,665 | 2.10% | 30.6% | 12.81% |
| 10 | Honghu Lotus Root Powder | Aquatic Tuberous | 64,340 | 1.91% | **20.99%** | 11.81% |
| 11 | Yunnan Lettuce (Bag) | Flower/Leaf | 63,995 | 1.90% | 33.7% | 9.43%* |
| 12 | Xixia Black Mushroom (1) | Edible Mushroom | 60,116 | 1.78% | 27.0% | 10.80% |
| 13 | Needle Mushroom (Box) | Edible Mushroom | 58,641 | 1.74% | 35.4% | 0.45% |
| 14 | Qinggengsanhua | Cabbage | 58,273 | 1.73% | 24.3% | 17.06% |

<sub>* the 9.43% placeholder, not a measured rate</sub>

**All six categories appear here**, so there is no single category to protect — the
concentration is at *item* level, which is where ordering decisions get made anyway.

Margins run 21.0% to 35.4%. The weakest is **Honghu Lotus Root Powder at 21.0% on
RMB 64,340** — the single most valuable pricing conversation in the business.

The pairing worth noticing: **Xixia Mushroom is the 3rd biggest seller and loses
13.8%**, and **Qinggengsanhua is 14th and loses 17.1%**. Those two are why the waste
list and the bestseller list are nearly the same list.

**Bands B, C and D are listed item by item in
[the report](reports/analysis_report.txt)**; band E and the raw records are in
[`findings.json`](reports/findings.json).

### What bands C and D turn out to hide

Two things only became visible once the items were named rather than counted.

**Band C holds the worst margins in the business.** Its spread is 10.1% to 49.5%
— the widest of any band — and the bottom of it is where loss-adjusted pricing
matters most:

| Item | Revenue | True margin | Loss rate |
|---|---|---|---|
| Honghu Lotus Root | 21,463 | **10.1%** | 24.1% |
| Sichuan Red Cedar | 10,548 | 14.6% | 10.5% |
| High Melon (1) | 16,258 | 16.0% | 29.3% |
| Foreign Garland Chrysanthemum | 11,700 | 16.2% | 26.2% |

Three of those four are high-spoilage lines losing 24–29% of stock — they are small
*because* a quarter never reaches a customer, not because they sell badly. Sichuan
Red Cedar is the odd one out: 10.5% loss doesn't explain a 14.6% margin, so it is
bought or priced badly, and this data can't say which. Worth asking the buyer.

**Band D is mostly the same products entered twice.** 51 of its 66 rows carry a
(Bag), (Box), (Bunch) or numbered suffix. Across the whole range:

> **246 item codes represent only 167 distinct products.** 79 codes are a
> repackaging of something already stocked — 7 separate codes for *Haixian
> Mushroom*, 7 for *Needle Mushroom*, 5 for *Apricot Bao Mushroom*.

Each duplicate is its own ordering decision, shelf facing, price and spoilage risk
for a product the shop already sells. **Consolidating variants should come before
delisting anything** — it removes the same overhead without removing a single thing
a customer can buy, and it is a far easier conversation.

**Two cautions on that table.** "Chinese Cabbage" appears twice in band B as two
different item codes with different loss rates — a catalogue quirk that ranking by
*name* would silently merge. And **8 of the 42 items in bands A and B carry the 9.43%
placeholder loss rate**, so their true-margin figures are estimates. Those are the
most valuable lines in the business, which makes them the obvious place to start
measuring waste for real.

### The tail

- The **bottom half of the range** contributes **1.2%** of revenue
- **60 items** sold on ten days or fewer in three years
- **110 items** have not sold at all in the final six months

These are not failing products so much as decisions made once and never reviewed.
The payoff from delisting them is not revenue — there is none. It is the ordering
attention and shelf space returned to the top decile, which is volume-constrained
rather than demand-constrained.

### 5. The last trading hour does not pay for itself

![Hourly revenue and discounting](figures/hourly_revenue_and_discounting.png)

The trading day has **two peaks, not one**: a 09:00–11:00 market run and a 16:00–18:00
after-work rush, split by a midday trough at about a third of peak.

The 21:00 hour is **2.0% of revenue at 24.9% margin** — against ~30% through the rest
of the day — and it is the most heavily discounted hour. Weakest on all three measures
at once.

---

## When the money arrives

**By weekday.** The weekend carries a third more trade than midweek — and the gap is
driven by *traffic*, not by bigger baskets: margin is near-identical across all seven
days.

![Revenue by weekday](figures/revenue_by_weekday.png)

| | Revenue/day | Lines/day |
|---|---|---|
| Saturday (best) | RMB 3,956 | 1,032 |
| Sunday | RMB 3,825 | 998 |
| Thursday (worst) | RMB 2,667 | 699 |

Monday to Thursday sit within 5% of each other. A midweek promotion is competing
with itself rather than filling a genuine trough; the ordering step-up belongs on
Friday and Saturday.

**By month.** January and February carry the year at roughly **2.1x** a June day.

![Seasonality by category](figures/seasonality_by_category.png)

The categories do not move together, which matters for ordering. Aquatic Tuberous
Vegetables swing **4.9x** between peak and trough month; Cabbage only **2.1x**.

## Category performance

![Category margin gap](figures/category_margin_gap.png)

Every category loses between 4.3 and 8.7 margin points to spoilage. Flower/Leaf
Vegetables — the largest category at 32% of revenue — loses the most, at **8.7 points**,
because it combines high volume with the highest volume-weighted loss rate (12.5%).

| Category | Revenue share | Book margin | True margin | Lost to waste |
|---|---|---|---|---|
| Flower/Leaf Vegetables | 32.0% | 39.9% | 31.2% | −8.7 pts |
| Capsicum | 22.4% | 37.1% | 31.6% | −5.5 pts |
| Edible Mushroom | 18.4% | 36.4% | 29.8% | −6.7 pts |
| Cabbage | 11.2% | 34.8% | 27.2% | −7.7 pts |
| Aquatic Tuberous Vegetables | 10.4% | 30.8% | 23.3% | −7.5 pts |
| Solanum | 5.7% | 36.3% | 32.0% | −4.3 pts |

---

## What was working better than expected

Not everything here is a problem, and two findings run against the obvious intuition.

**Discounting is not destroying value.** Marked-down stock still returns **+9.7% true
margin**. It is a functioning clearance mechanism recovering cash from stock that would
otherwise be binned at a 100% loss. Discounting runs at 3% of lines before noon and
27% in the 21:00 hour — it is end-of-day clearance, applied at the right time.

The markdown is not the problem. The *volume of stock that needs clearing* is, and
that is a morning ordering decision.

**The year's biggest sales event is completely predictable.** Eight of the ten best
days in three years fall in the week before Chinese New Year, and the best single day
took **10.4x the median day**.

![Three years of daily takings](figures/daily_revenue_three_years.png)

There is no forecasting difficulty here — the date is known years ahead and the shape
repeats in all three years.

---

## What to do

| Action | Why it is the right size of fix |
|---|---|
| Price from `cost / (1 − loss_rate)` | One formula; recovers the single largest leak in the data |
| Attack the top 10 waste items specifically | 44% of waste cost sits in a list short enough to act on this week |
| Put lines/day on the revenue chart | The erosion is invisible on revenue alone |
| Consolidate duplicate SKUs before delisting | 246 codes are only 167 products; merging costs the customer nothing |
| Quarterly range review, 90-day delist rule | Returns ordering attention to the volume-constrained lines |
| Split deliveries: heavy pre-09:00, light pre-16:00 | Fixes what *feeds* the evening clearance pile |
| Close at 21:00; move the hour to 09:00–11:00 | A roster change, not an investment |

---

## A data quality problem worth its own section

**85 of the 251 items in `annex4` carry a loss rate of exactly 9.43%** — which is
precisely the mean of that column (9.4267). That is not a measurement. It is a
placeholder written over every item nobody measured. A further **22 items sit at
exactly 0.00%**, which for fresh vegetables is not credible either.

Those 85 items are **16.7% of revenue**. On the loss-rate scatter plot in
["Spoilage is not priced in"](#2-spoilage-is-not-priced-in--anywhere) they form an
unmistakable vertical stripe — the chart labels it directly.

This bounds the analysis without sinking it. The *direction* of every finding survives
— spoilage is unpriced whichever way you cut it, and the aggregate RMB 239,699 is
dominated by high-revenue items that mostly have real measured rates. But **any single
per-item figure for a placeholder line is an assumption wearing two decimal places**,
and should not be taken to the decimal.

---

## Where this analysis stops

Stated plainly, because the limits bound every recommendation above.

- **No basket or customer ID.** Nothing here counts shoppers or measures basket size.
  "Traffic" always means lines scanned.
- **No stock-on-hand.** Spoilage is a per-item rate, not an observed daily loss, so
  this says what waste costs on average — not which delivery went bad.
- **Stockouts are invisible.** An item that sold nothing on a Tuesday may have had no
  demand or no stock. Nothing in these files separates the two, and every "weak seller"
  verdict carries that caveat.
- **The elasticity fits are observational, not experimental.** Price and volume both
  move with supply — a glut lowers price and raises volume at once — so the slopes
  conflate a demand curve with a supply curve. They rank items usefully; they do not
  predict the result of a price change. The notebook shows a block of *positive*
  fitted elasticities that demonstrate the method breaking on fixed-price bagged lines.
- **Everything below gross margin is absent.** No rent, wages, power or transport.
  Gross margin is not profit. This cannot say whether the business makes money — only
  which lines and hours contribute most to covering costs it cannot see.

---

## The words used above, in plain English

**Gross margin** — what is left of the selling price after paying for the goods
themselves, before rent, wages or power. Not profit.

**Book margin** — gross margin measured against what the stock cost to buy. What a
till report shows.

**True margin** — the same figure after also paying for the stock that spoiled. What
the bank sees.

**Loss rate** — the share of stock that spoils or is thrown away before it can be sold.

**SKU** — one distinct sellable item.

**Markup** — selling price divided by cost. A 1.6x markup on a RMB 5 kilo means RMB 8.

**Elasticity** — how much volume moves when price moves. −1.5 means a 10% price rise
costs about 15% of volume.

**Line** — one scanned item on one receipt. Not a customer and not a basket.
