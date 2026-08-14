"""
Generate a realistic POS + inventory dataset for a 3-branch Kampala supermarket
chain, covering Uganda's FY2025/26 (1 Jul 2025 - 30 Jun 2026).

The point of this dataset is to look and behave like a real Ugandan supermarket
back-office export: the seasonality is local (payday on the 28th, school term
openings, Ramadan/Eid, the January 2026 general election, the two rainy
seasons, load shedding), the tax treatment follows Uganda's VAT rules, and the
data carries the same defects a real export carries -- voided tickets left in
the file, returns as negative lines, near-zero-margin airtime booked at full
value, and stockouts that are invisible unless you join to inventory.

Everything is driven off a fixed seed so the analysis is reproducible.

Outputs (data/):
    branches.csv            3 rows
    suppliers.csv           35 rows
    products.csv            ~380 SKUs
    calendar.csv            365 days with local demand drivers
    price_history.csv       monthly cost/price per SKU
    promotions.csv          promo calendar
    customers.csv           loyalty base
    staff.csv               cashiers
    staff_shifts.csv        rostered cashier-hours by branch/day/hour
    transactions.csv        ~300k ticket headers
    transaction_lines.csv   ~1.3M line items
    inventory_daily.csv     branch x SKU x day stock position + stockout flag
    lost_sales.csv          ground-truth demand lost to stockouts
    shrinkage.csv           waste / expiry / unexplained loss events
    purchase_orders.csv     PO header + fill performance
"""

from __future__ import annotations

import os
import numpy as np
import pandas as pd

from catalog import CATALOG, BRANCHES, SUPPLIERS, CHAIN_NAME, KVI_KEYWORDS

SEED = 20260811
rng = np.random.default_rng(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
os.makedirs(DATA, exist_ok=True)

START = pd.Timestamp("2025-07-01")
END = pd.Timestamp("2026-06-30")
DATES = pd.date_range(START, END, freq="D")
NDAYS = len(DATES)

TARGET_ANNUAL_REVENUE_UGX = 9.4e9   # ~UGX 780m/month across 3 branches
VAT_RATE = 0.18


# --------------------------------------------------------------------------
# 1. Master data
# --------------------------------------------------------------------------

branches = pd.DataFrame(
    BRANCHES,
    columns=["branch_code", "branch_name", "area", "size_index",
             "affluence_index", "opened_date", "tills"],
)
NB = len(branches)

suppliers = pd.DataFrame(
    SUPPLIERS,
    columns=["supplier_name", "primary_category", "lead_time_days",
             "fill_rate", "credit_days", "lead_time_sd"],
)
suppliers.insert(0, "supplier_id",
                 ["SUP%03d" % (i + 1) for i in range(len(suppliers))])

rows = []
for cat, items in CATALOG.items():
    for (name, sub, unit, cost, price, base, vat_ex, shelf, sup) in items:
        rows.append(dict(
            product_name=name, category=cat, subcategory=sub, unit_size=unit,
            unit_cost_ugx=cost, unit_price_ugx=price, base_units_day=base,
            vat_exempt=vat_ex, shelf_life_days=shelf, supplier_name=sup,
        ))
products = pd.DataFrame(rows)
products.insert(0, "sku", ["SKU%04d" % (i + 1) for i in range(len(products))])
products = products.merge(suppliers[["supplier_id", "supplier_name"]],
                          on="supplier_name", how="left")
products["is_kvi"] = products["product_name"].isin(KVI_KEYWORDS)
products["is_perishable"] = products["shelf_life_days"].between(1, 30)

# Category mix correction. The per-SKU baselines in catalog.py were set line by
# line; these factors pull the resulting category shares into line with what a
# Kampala supermarket of this size actually reports -- fresh and bakery carry
# more of the basket, and packaged oil rather less, than the raw SKU
# baselines implied.
CATEGORY_MIX_ADJ = {
    "Cooking Oil & Fats": 0.65,
    "Fresh Produce": 1.35,
    "Bakery": 1.25,
    "Dairy & Eggs": 1.20,
    "Butchery & Fish": 1.15,
}
products["base_units_day"] *= products["category"].map(CATEGORY_MIX_ADJ).fillna(1.0)

# Case packs. Distributors sell in cases, not units, and that single constraint
# is what creates dead stock: one case of a slow line is six months of cover.
# Fresh produce and butchery are bought loose daily, so their case size is 1.
def _case_size(r):
    if r["category"] in ("Fresh Produce", "Butchery & Fish"):
        return 1
    if r["category"] == "Airtime & Mobile Money":
        return 10
    p = r["unit_price_ugx"]
    if p < 2000:
        return 24
    if p < 6000:
        return 12
    if p < 20000:
        return 6
    if p < 45000:
        return 4
    return 2

products["case_size"] = products.apply(_case_size, axis=1)

NS = len(products)

cat_index = {c: i for i, c in enumerate(sorted(products["category"].unique()))}
CATS = sorted(cat_index)
products["cat_idx"] = products["category"].map(cat_index)


# --------------------------------------------------------------------------
# 2. Calendar -- the local demand drivers
# --------------------------------------------------------------------------

cal = pd.DataFrame({"date": DATES})
cal["dow"] = cal["date"].dt.dayofweek           # 0 = Monday
cal["day_of_month"] = cal["date"].dt.day
cal["month"] = cal["date"].dt.month
cal["year"] = cal["date"].dt.year
cal["month_name"] = cal["date"].dt.strftime("%b %Y")
cal["days_in_month"] = cal["date"].dt.days_in_month
cal["week"] = cal["date"].dt.isocalendar().week.astype(int)

HOLIDAYS = {
    "2025-10-09": "Independence Day",
    "2025-12-25": "Christmas Day",
    "2025-12-26": "Boxing Day",
    "2026-01-01": "New Year's Day",
    "2026-01-15": "General Election Day",
    "2026-01-26": "NRM Liberation Day",
    "2026-02-16": "Janani Luwum Day",
    "2026-03-08": "International Women's Day",
    "2026-03-20": "Eid al-Fitr (observed)",
    "2026-04-03": "Good Friday",
    "2026-04-06": "Easter Monday",
    "2026-05-01": "Labour Day",
    "2026-05-27": "Eid al-Adha (observed)",
    "2026-06-03": "Martyrs' Day",
    "2026-06-09": "National Heroes' Day",
}
cal["holiday"] = cal["date"].dt.strftime("%Y-%m-%d").map(HOLIDAYS).fillna("")
cal["is_holiday"] = cal["holiday"] != ""

# Ugandan school terms: three terms, and the openings are a real retail event.
TERM_OPENINGS = ["2025-09-08", "2026-02-02", "2026-05-25"]
term_open = pd.to_datetime(TERM_OPENINGS)
days_to_term = np.array([
    min(abs((d - t).days) for t in term_open) for d in DATES
])
# Signed: buying happens in the ~10 days BEFORE opening, not after.
days_before_term = np.array([
    min([(t - d).days for t in term_open if 0 <= (t - d).days <= 14] or [99])
    for d in DATES
])
cal["days_to_term_opening"] = np.where(days_before_term < 99, days_before_term, -1)
cal["is_school_shopping"] = cal["days_to_term_opening"].between(0, 12)

# Salaries land around the 28th; the payday window runs to about the 3rd.
dom = cal["day_of_month"].values
dim = cal["days_in_month"].values
_from_payday = np.where(dom >= 25, dom - 28, dom + (dim - 28))
payday_curve = np.exp(-0.5 * (_from_payday / 3.1) ** 2)
cal["payday_intensity"] = np.round(payday_curve, 4)
cal["is_payday_window"] = (dom >= 25) | (dom <= 3)

# Ramadan 2026 (approx 18 Feb - 19 Mar).
cal["is_ramadan"] = cal["date"].between("2026-02-18", "2026-03-19")

# The January 2026 general election: households stock up beforehand, then the
# city goes quiet for about a week.
cal["election_phase"] = ""
cal.loc[cal["date"].between("2026-01-07", "2026-01-14"), "election_phase"] = "pre-election stock-up"
cal.loc[cal["date"].between("2026-01-15", "2026-01-21"), "election_phase"] = "election lull"

# Two rainy seasons; rain suppresses walk-in footfall.
rain_prob = np.where(cal["month"].isin([3, 4, 5]), 0.55,
             np.where(cal["month"].isin([9, 10, 11]), 0.48,
             np.where(cal["month"].isin([12, 1, 2]), 0.14, 0.26)))
cal["is_rainy_day"] = rng.random(NDAYS) < rain_prob

# Load shedding / grid outages: hits cold chain, so it drives frozen+dairy waste.
cal["power_outage_hours"] = np.round(
    np.where(rng.random(NDAYS) < 0.22, rng.gamma(2.0, 1.6, NDAYS), 0.0), 1)

# ---- composite footfall multiplier -------------------------------------
dow_mult = np.array([0.86, 0.83, 0.89, 0.96, 1.19, 1.46, 0.93])
month_mult = {7: 0.97, 8: 0.99, 9: 1.03, 10: 1.02, 11: 1.01, 12: 1.34,
              1: 0.87, 2: 0.98, 3: 1.00, 4: 1.04, 5: 1.01, 6: 1.02}

foot = dow_mult[cal["dow"].values] * cal["month"].map(month_mult).values
foot = foot * (1 + 0.46 * cal["payday_intensity"].values)
foot = foot * np.where(cal["is_rainy_day"], 0.86, 1.0)
foot = foot * np.where(cal["is_holiday"], 0.72, 1.0)      # most shoppers stay home
foot = foot * np.where(cal["election_phase"] == "pre-election stock-up", 1.28, 1.0)
foot = foot * np.where(cal["election_phase"] == "election lull", 0.58, 1.0)
# Christmas / New Year run-up
xmas = cal["date"].between("2025-12-18", "2025-12-24")
foot = foot * np.where(xmas, 1.55, 1.0)
nye = cal["date"].between("2025-12-29", "2025-12-31")
foot = foot * np.where(nye, 1.30, 1.0)
# Day before the big holidays
eve = cal["date"].isin(pd.to_datetime(
    ["2026-03-19", "2026-04-02", "2026-05-26", "2026-06-02", "2026-06-08"]))
foot = foot * np.where(eve, 1.35, 1.0)
foot = foot * rng.normal(1.0, 0.055, NDAYS).clip(0.75, 1.3)

cal["footfall_index"] = np.round(foot, 4)


# ---- category-level seasonality ---------------------------------------
cat_mult = np.ones((NDAYS, len(CATS)))

def cmul(cat, mask, factor):
    cat_mult[np.asarray(mask), cat_index[cat]] *= factor

# School shopping
school_wave = np.where(cal["is_school_shopping"], 1.0, 0.0)
cmul("Stationery & School", school_wave > 0, 7.5)
cmul("Bags & Sundries", school_wave > 0, 1.5)
cmul("Personal Care", school_wave > 0, 1.35)
cmul("Household Cleaning", school_wave > 0, 1.4)
cmul("Sugar & Sweeteners", school_wave > 0, 1.3)
# Off-season stationery is genuinely dead
cmul("Stationery & School", ~cal["is_school_shopping"].values, 0.55)

# December: booze, meat, soft drinks, snacks
dec = (cal["month"] == 12).values
for c, f in [("Beverages - Alcohol", 1.85), ("Beverages - Soft", 1.55),
             ("Butchery & Fish", 1.48), ("Snacks & Confectionery", 1.42),
             ("Frozen Foods", 1.35), ("Bags & Sundries", 1.3)]:
    cmul(c, dec, f)

# January squeeze: school fees crowd out discretionary spend
jan = (cal["month"] == 1).values
for c, f in [("Beverages - Alcohol", 0.68), ("Home & Kitchen", 0.62),
             ("Snacks & Confectionery", 0.80), ("Frozen Foods", 0.82)]:
    cmul(c, jan, f)
cmul("Staples & Grains", jan, 1.10)   # people fall back on basics

# Ramadan: dates/staples up in the evening, alcohol down
ram = cal["is_ramadan"].values
cmul("Beverages - Alcohol", ram, 0.80)
cmul("Staples & Grains", ram, 1.14)
cmul("Fresh Produce", ram, 1.10)
cmul("Beverages - Soft", ram, 1.12)

# Weekend / Friday drinking and meat
fri_sat = cal["dow"].isin([4, 5]).values
cmul("Beverages - Alcohol", fri_sat, 1.55)
cmul("Butchery & Fish", fri_sat, 1.30)
cmul("Frozen Foods", fri_sat, 1.18)

# Election stock-up is concentrated in shelf-stable staples
pre_el = (cal["election_phase"] == "pre-election stock-up").values
for c, f in [("Staples & Grains", 1.75), ("Cooking Oil & Fats", 1.55),
             ("Sugar & Sweeteners", 1.60), ("Canned & Packaged", 1.45),
             ("Home & Kitchen", 1.25)]:
    cmul(c, pre_el, f)

# Rain: fresh produce trips get deferred harder than packaged goods
rainy = cal["is_rainy_day"].values
cmul("Fresh Produce", rainy, 0.88)
cmul("Butchery & Fish", rainy, 0.90)

# Month-end payday skews to bulk staples rather than top-ups
payday_hi = (cal["payday_intensity"] > 0.55).values
for c, f in [("Staples & Grains", 1.32), ("Cooking Oil & Fats", 1.30),
             ("Sugar & Sweeteners", 1.28), ("Household Cleaning", 1.26),
             ("Personal Care", 1.20), ("Baby Care", 1.22)]:
    cmul(c, payday_hi, f)
# ...and airtime is bought constantly but spikes on payday
cmul("Airtime & Mobile Money", payday_hi, 1.35)


# --------------------------------------------------------------------------
# 3. Price history -- inflation plus two real commodity shocks
# --------------------------------------------------------------------------

months = pd.period_range(START, END, freq="M")
NM = len(months)
month_idx = {p: i for i, p in enumerate(months)}
cal["m_idx"] = cal["date"].dt.to_period("M").map(month_idx).astype(int)

cost_f = np.ones((NM, NS))
price_f = np.ones((NM, NS))

base_infl = np.cumprod(np.r_[1.0, np.full(NM - 1, 1.0032)])   # ~3.9%/yr
cost_f *= base_infl[:, None]
price_f *= base_infl[:, None]

is_sugar = (products["category"] == "Sugar & Sweeteners").values
is_oil = (products["category"] == "Cooking Oil & Fats").values
is_produce = (products["category"] == "Fresh Produce").values

# Sugar: cane shortage pushes mill prices up from Nov; the shelf price only
# catches up in Feb. That lag is a real margin hole, and it is the kind of
# thing an owner never sees without this analysis.
sugar_cost = np.ones(NM)
sugar_price = np.ones(NM)
for i, p in enumerate(months):
    key = (p.year, p.month)
    sugar_cost[i] = {(2025, 11): 1.09, (2025, 12): 1.18, (2026, 1): 1.24,
                     (2026, 2): 1.22, (2026, 3): 1.15, (2026, 4): 1.08,
                     (2026, 5): 1.05, (2026, 6): 1.04}.get(key, 1.0)
    sugar_price[i] = {(2025, 11): 1.01, (2025, 12): 1.04, (2026, 1): 1.09,
                      (2026, 2): 1.21, (2026, 3): 1.20, (2026, 4): 1.14,
                      (2026, 5): 1.09, (2026, 6): 1.07}.get(key, 1.0)
cost_f[:, is_sugar] *= sugar_cost[:, None]
price_f[:, is_sugar] *= sugar_price[:, None]

# Cooking oil steps up in January and mostly holds
oil_cost = np.ones(NM)
for i, p in enumerate(months):
    if (p.year, p.month) >= (2026, 1):
        oil_cost[i] = 1.085
cost_f[:, is_oil] *= oil_cost[:, None]
price_f[:, is_oil] *= np.clip(oil_cost * 0.985, 1.0, None)[:, None]

# Fresh produce swings with the seasons: dry season is expensive, harvest cheap
prod_f = np.ones(NM)
for i, p in enumerate(months):
    prod_f[i] = {12: 1.18, 1: 1.30, 2: 1.26, 3: 1.05,
                 6: 0.92, 7: 0.90, 8: 0.94}.get(p.month, 1.0)
cost_f[:, is_produce] *= prod_f[:, None]
price_f[:, is_produce] *= (1 + (prod_f - 1) * 0.88)[:, None]

unit_cost = np.round(products["unit_cost_ugx"].values[None, :] * cost_f, 0)
unit_price = np.round(
    products["unit_price_ugx"].values[None, :] * price_f / 50, 0) * 50  # UGX-50 pricing

price_hist = pd.DataFrame({
    "month": np.repeat([str(p) for p in months], NS),
    "sku": np.tile(products["sku"].values, NM),
    "unit_cost_ugx": unit_cost.ravel(),
    "unit_price_ugx": unit_price.ravel(),
})
price_hist["gross_margin_pct"] = np.where(
    price_hist["unit_price_ugx"] > 0,
    (price_hist["unit_price_ugx"] - price_hist["unit_cost_ugx"])
    / price_hist["unit_price_ugx"] * 100, 0).round(2)


# --------------------------------------------------------------------------
# 4. Promotions
# --------------------------------------------------------------------------

# supplier_funded is the share of the discount the supplier rebates back. This
# is the single thing that decides whether a supermarket promotion makes money,
# and it is almost never tracked in the POS.
promo_specs = [
    # (name, sku_name, start, end, discount_pct, branches, supplier_funded)
    ("Back to School Sugar Deal", "Kakira Sugar 2kg",        "2025-09-01", "2025-09-12", 0.07, "ALL", 0.00),
    ("Independence Beer Offer",   "Nile Special Lager 500ml","2025-10-05", "2025-10-12", 0.09, "ALL", 1.00),
    ("Festive Oil Promo",         "Mukwano Cooking Oil 5L",  "2025-12-05", "2025-12-24", 0.06, "ALL", 0.85),
    ("Festive Rice Promo",        "Super Rice Pishori 5kg",  "2025-12-05", "2025-12-24", 0.08, "ALL", 0.00),
    ("New Year Soap Bundle",      "Mukwano Bar Soap 800g",   "2026-01-02", "2026-01-20", 0.12, "ALL", 0.00),
    ("New Year Detergent Deal",   "Nomi Washing Powder 1kg", "2026-01-02", "2026-01-20", 0.14, "ALL", 0.20),
    ("Term 1 Books Offer",        "Picfare Exercise Book 96pg","2026-01-24","2026-02-08", 0.15, "ALL", 0.70),
    ("Ramadan Staples Offer",     "Super Rice Pishori 1kg",  "2026-02-18", "2026-03-19", 0.08, "ALL", 0.55),
    ("Easter Chicken Promo",      "Chicken Whole Broiler 1.5kg","2026-03-28","2026-04-06", 0.10, "ALL", 0.40),
    ("Sugar Price Fight",         "Kakira Sugar 1kg",        "2026-04-10", "2026-05-10", 0.05, "ALL", 0.00),
    ("Ntinda Fresh Milk Deal",    "Fresh Dairy Milk UHT 1L", "2026-02-01", "2026-02-28", 0.10, "NTI", 1.00),
    ("Kabalagala Bread Offer",    "Ntake Bread White 600g",  "2026-05-01", "2026-05-31", 0.08, "KAB", 0.50),
]
sku_by_name = dict(zip(products["product_name"], products["sku"]))
promo_rows = []
for i, (nm, pname, s, e, d, br, fund) in enumerate(promo_specs):
    promo_rows.append(dict(
        promo_id="PRM%02d" % (i + 1), promo_name=nm, sku=sku_by_name[pname],
        product_name=pname, start_date=s, end_date=e,
        discount_pct=d, branch_scope=br, supplier_funded_pct=fund))
promotions = pd.DataFrame(promo_rows)

promo_disc = np.zeros((NDAYS, NB, NS))
promo_fund = np.zeros((NDAYS, NB, NS))
sku_pos = {s: i for i, s in enumerate(products["sku"])}
br_pos = {b: i for i, b in enumerate(branches["branch_code"])}
for _, r in promotions.iterrows():
    dmask = (DATES >= pd.Timestamp(r["start_date"])) & (DATES <= pd.Timestamp(r["end_date"]))
    bidx = list(range(NB)) if r["branch_scope"] == "ALL" else [br_pos[r["branch_scope"]]]
    for b in bidx:
        ix = np.ix_(np.where(dmask)[0], [b], [sku_pos[r["sku"]]])
        promo_disc[ix] = r["discount_pct"]
        promo_fund[ix] = r["supplier_funded_pct"]


# --------------------------------------------------------------------------
# 5. Potential demand (what customers WOULD buy if everything were in stock)
# --------------------------------------------------------------------------

# Branch demand share: size x affluence, plus a category skew per branch.
# base_units_day is a CHAIN-WIDE figure, so these shares must sum to 1.
branch_scale = (branches["size_index"].values * 0.82
                + branches["affluence_index"].values * 0.18)
branch_scale = branch_scale / branch_scale.sum()

# Ntinda skews premium/packaged; Kabalagala skews value/staples/alcohol.
branch_cat_skew = np.ones((NB, len(CATS)))
skews = {
    "NTI": {"Baby Care": 1.45, "Frozen Foods": 1.40, "Personal Care": 1.30,
            "Canned & Packaged": 1.28, "Home & Kitchen": 1.25,
            "Beverages - Soft": 1.10, "Staples & Grains": 0.86,
            "Airtime & Mobile Money": 0.80, "Fresh Produce": 0.92},
    "KAB": {"Staples & Grains": 1.30, "Airtime & Mobile Money": 1.55,
            "Beverages - Alcohol": 1.42, "Sugar & Sweeteners": 1.22,
            "Fresh Produce": 1.18, "Baby Care": 0.62, "Frozen Foods": 0.70,
            "Home & Kitchen": 0.65, "Canned & Packaged": 0.78},
    "NAK": {"Bakery": 1.15, "Dairy & Eggs": 1.10, "Butchery & Fish": 1.12,
            "Stationery & School": 1.10},
}
for bcode, sk in skews.items():
    for c, f in sk.items():
        branch_cat_skew[br_pos[bcode], cat_index[c]] = f

base = products["base_units_day"].values                     # (NS,)
cat_of_sku = products["cat_idx"].values

# (NDAYS, NB, NS)
demand = (base[None, None, :]
          * cal["footfall_index"].values[:, None, None]
          * branch_scale[None, :, None]
          * cat_mult[:, None, cat_of_sku]
          * branch_cat_skew[None, :, cat_of_sku])

# Price elasticity: promos lift volume, and the sugar/oil price shocks suppress it.
elasticity = np.where(products["is_kvi"].values, -2.1, -1.1)
elasticity = np.where(products["category"].values == "Beverages - Alcohol", -0.7, elasticity)
elasticity = np.where(products["category"].values == "Airtime & Mobile Money", -0.2, elasticity)

price_rel = unit_price / unit_price[0][None, :]
price_effect = np.power(np.clip(price_rel, 0.5, 2.0), elasticity[None, :])
demand *= price_effect[cal["m_idx"].values][:, None, :]

promo_lift = np.power(np.clip(1 - promo_disc, 0.5, 1.0), elasticity[None, None, :])
demand *= promo_lift

demand *= rng.gamma(9.0, 1 / 9.0, size=demand.shape)          # daily noise
demand = np.clip(demand, 0, None)

# Calibrate to the target turnover. This is done on POTENTIAL demand, so the
# realised till roll lands a few percent lower once stockouts bite -- which is
# the whole point of the exercise.
_price_daily = unit_price[cal["m_idx"].values]                # (NDAYS, NS)
_potential_rev = (demand * _price_daily[:, None, :]).sum()
demand *= (TARGET_ANNUAL_REVENUE_UGX * 1.07) / _potential_rev
products["base_units_day"] = (
    products["base_units_day"] * (TARGET_ANNUAL_REVENUE_UGX * 1.07) / _potential_rev
).round(3)

potential_units = rng.poisson(demand).astype(np.int32)


# --------------------------------------------------------------------------
# 6. Inventory simulation -> what was actually available to sell
# --------------------------------------------------------------------------

sup_by_sku = products["supplier_name"].map(
    dict(zip(suppliers["supplier_name"], suppliers.index))).values
lead_time = suppliers["lead_time_days"].values[sup_by_sku].astype(float)
lead_sd = suppliers["lead_time_sd"].values[sup_by_sku]
fill_rate = suppliers["fill_rate"].values[sup_by_sku]

mu_day = demand.mean(axis=0)                                  # (NB, NS) annual average
shelf_life = products["shelf_life_days"].values.astype(float)
is_perish = products["is_perishable"].values

# Replenishment policy. Note deliberately: the reorder point is built off the
# ANNUAL average, with no month-end or seasonal uplift. That is exactly how most
# Ugandan supermarkets run their reorder cards, and it is why they run dry at
# month-end on the very lines that bring people through the door.
# Fresh is ordered daily; ambient lines are ordered weekly, which is how the
# distributor delivery rounds actually work in Kampala.
review_cycle = np.where(is_perish, 1.0, 7.0)
# Carrying safety stock on a 3-day-shelf-life item just buys spoilage, so the
# fresh counters run deliberately tighter than the ambient aisles.
safety_z = np.where(is_perish, 0.55, 1.4)
sigma_day = demand.std(axis=0)

rop = (mu_day * (lead_time[None, :] + 1)
       + safety_z[None, :] * sigma_day * np.sqrt(lead_time[None, :] + 1))
order_up_to = rop + mu_day * review_cycle[None, :] * 2.6
# Perishables are ordered close to expected demand plus a buffer; the buffer is
# what turns into waste.
order_up_to = np.where(is_perish[None, :], mu_day * (1.0 + np.clip(shelf_life, 1, 8))[None, :] * 0.55,
                       order_up_to)
order_up_to = np.maximum(order_up_to, rop + 1)

# Shelf presentation minimum: a supermarket keeps its facings full, so even a
# line selling one unit a week holds a visible block of stock. Combined with
# case-pack ordering below, this is where dead stock comes from.
case = products["case_size"].values.astype(float)
min_display = np.where(is_perish[None, :], 0.0,
                       np.maximum(case[None, :], np.ceil(mu_day * 22)))
order_up_to = np.maximum(order_up_to, min_display)
rop = np.maximum(rop, np.where(is_perish[None, :], 0.0, case[None, :] * 0.4))

on_hand = np.round(order_up_to * 0.8).astype(float)
pipeline = np.zeros((NDAYS + 40, NB, NS))                     # arrivals by day

served = np.zeros((NDAYS, NB, NS), dtype=np.int32)
lost = np.zeros((NDAYS, NB, NS), dtype=np.int32)
closing = np.zeros((NDAYS, NB, NS), dtype=np.float32)
receipts_log = np.zeros((NDAYS, NB, NS), dtype=np.float32)
waste_log = np.zeros((NDAYS, NB, NS), dtype=np.float32)
theft_log = np.zeros((NDAYS, NB, NS), dtype=np.float32)

# Shrink profiles. Kabalagala has a genuine control problem on small,
# high-value, easily-pocketed lines -- and it shows up as unexplained loss.
high_value_small = (
    (products["unit_price_ugx"].values >= 4000)
    & products["category"].isin(
        ["Personal Care", "Baby Care", "Beverages - Alcohol",
         "Snacks & Confectionery", "Tea & Coffee"]).values
)
theft_rate = np.zeros((NB, NS))
theft_rate[:, :] = 0.00055
theft_rate[:, high_value_small] = 0.0015
theft_rate[br_pos["KAB"], :] = 0.0011
theft_rate[br_pos["KAB"], high_value_small] = 0.0080     # the planted problem

# Cold-chain quality by branch (Kabalagala's chillers are the oldest).
coldchain = np.ones(NB)
coldchain[br_pos["NAK"]] = 1.00
coldchain[br_pos["NTI"]] = 0.88
coldchain[br_pos["KAB"]] = 1.60

is_coldchain = products["category"].isin(
    ["Frozen Foods", "Dairy & Eggs", "Butchery & Fish"]).values

po_records = []
po_counter = 0
outage = cal["power_outage_hours"].values

for t in range(NDAYS):
    on_hand += pipeline[t]
    receipts_log[t] = pipeline[t]

    want = potential_units[t]
    sell = np.minimum(want, np.floor(on_hand)).astype(np.int32)
    served[t] = sell
    lost[t] = want - sell
    on_hand -= sell

    # --- shrinkage ------------------------------------------------------
    # Perishable spoilage rises with how long stock has been sitting relative
    # to shelf life, and with power outages for anything refrigerated.
    sl = np.where(shelf_life > 0, shelf_life, 9999)
    spoil = np.where(is_perish[None, :], on_hand / np.maximum(sl[None, :], 1.0) * 0.20, 0.0)
    spoil = spoil * coldchain[:, None]
    if outage[t] > 0:
        spoil = spoil + np.where(is_coldchain[None, :],
                                 on_hand * 0.012 * outage[t] * coldchain[:, None], 0.0)
    spoil = np.minimum(spoil, on_hand)
    waste_log[t] = spoil
    on_hand -= spoil

    theft = np.minimum(on_hand * theft_rate, on_hand)
    theft_log[t] = theft
    on_hand -= theft

    closing[t] = on_hand

    # --- reorder --------------------------------------------------------
    inbound = pipeline[t + 1:t + 1 + 20].sum(axis=0)
    position = on_hand + inbound
    need = position < rop
    if need.any():
        # You cannot order 7 units of something that comes in cases of 12.
        raw = np.clip(order_up_to - position, 0, None)
        qty = np.where(is_perish[None, :], np.ceil(raw),
                       np.ceil(raw / case[None, :]) * case[None, :]) * need
        lt = np.maximum(1, np.round(
            lead_time[None, :] + rng.normal(0, lead_sd[None, :], size=(NB, NS)))).astype(int)
        # Suppliers short-ship around their nominal fill rate.
        got = np.floor(qty * np.clip(
            rng.normal(fill_rate[None, :], 0.07, size=(NB, NS)), 0.35, 1.0))
        for b in range(NB):
            idx = np.where(need[b])[0]
            if idx.size == 0:
                continue
            arr = np.clip(t + lt[b, idx], 0, NDAYS + 39)
            np.add.at(pipeline[:, b, :], (arr, idx), got[b, idx])
            po_counter += 1
            po_records.append((
                t, b, idx, qty[b, idx].copy(), got[b, idx].copy(), lt[b, idx].copy()))

stockout = (closing <= 0.5) & (potential_units > 0)


# --------------------------------------------------------------------------
# 7. Purchase orders (aggregated to PO header per branch/supplier/day)
# --------------------------------------------------------------------------

po_rows = []
sup_names = products["supplier_name"].values
sup_ids = products["supplier_id"].values
cost_by_day = unit_cost[cal["m_idx"].values]                  # (NDAYS, NS)
for (t, b, idx, qty, got, lt) in po_records:
    df = pd.DataFrame({"sku_i": idx, "qty": qty, "got": got, "lt": lt})
    df["supplier_id"] = sup_ids[idx]
    df["supplier_name"] = sup_names[idx]
    df["cost"] = cost_by_day[t][idx]
    g = df.groupby(["supplier_id", "supplier_name"], as_index=False).agg(
        lines=("sku_i", "size"), qty_ordered=("qty", "sum"),
        qty_received=("got", "sum"), avg_lead_days=("lt", "mean"),
        order_value_ugx=("cost", lambda s: 0))
    val = df.assign(v=df["qty"] * df["cost"], rv=df["got"] * df["cost"]).groupby(
        "supplier_id", as_index=False).agg(order_value_ugx=("v", "sum"),
                                           received_value_ugx=("rv", "sum"))
    g = g.drop(columns=["order_value_ugx"]).merge(val, on="supplier_id")
    g["order_date"] = DATES[t]
    g["branch_code"] = branches["branch_code"].iloc[b]
    po_rows.append(g)

purchase_orders = pd.concat(po_rows, ignore_index=True)
purchase_orders.insert(0, "po_id",
                       ["PO%06d" % (i + 1) for i in range(len(purchase_orders))])
purchase_orders["expected_date"] = purchase_orders["order_date"] + pd.to_timedelta(
    purchase_orders["avg_lead_days"].round(), unit="D")
purchase_orders["fill_rate_pct"] = (
    purchase_orders["qty_received"] / purchase_orders["qty_ordered"].replace(0, np.nan) * 100
).round(2)
purchase_orders["avg_lead_days"] = purchase_orders["avg_lead_days"].round(2)
purchase_orders = purchase_orders[[
    "po_id", "order_date", "expected_date", "branch_code", "supplier_id",
    "supplier_name", "lines", "qty_ordered", "qty_received", "fill_rate_pct",
    "avg_lead_days", "order_value_ugx", "received_value_ugx"]]


# --------------------------------------------------------------------------
# 8. Customers, staff, shifts
# --------------------------------------------------------------------------

NCUST = 14200
first = ["Nakato","Babirye","Kato","Wasswa","Achieng","Okello","Namutebi","Ssemwanga",
         "Aisha","Ibrahim","Grace","Moses","Sarah","David","Joan","Ronald","Prossy",
         "Emmanuel","Betty","Julius","Sylvia","Patrick","Harriet","Fred","Immaculate",
         "Denis","Rebecca","Andrew","Justine","Samuel","Zainab","Hassan","Peace",
         "Brian","Sandra","Geoffrey","Milly","Charles","Esther","Robert"]
last = ["Nakawesi","Ssentongo","Mugisha","Nabirye","Odongo","Kabuye","Nansubuga",
        "Tumwine","Lubega","Kyeyune","Atim","Mukasa","Nabukenya","Ochieng","Ssali",
        "Namara","Wanyama","Byaruhanga","Nakigudde","Opio","Kirabo","Muwanga",
        "Asiimwe","Nalubega","Ekiring","Sebugwawo","Nakiwala","Turyahikayo"]

cust = pd.DataFrame({
    "customer_id": ["CUS%05d" % (i + 1) for i in range(NCUST)],
    "customer_name": [f"{rng.choice(first)} {rng.choice(last)}" for _ in range(NCUST)],
})
cust["home_branch"] = rng.choice(branches["branch_code"], NCUST, p=[0.34, 0.42, 0.24])
cust["signup_date"] = (pd.Timestamp("2022-01-01")
                       + pd.to_timedelta(rng.integers(0, 1600, NCUST), unit="D"))
cust["tier"] = rng.choice(["Bronze", "Silver", "Gold"], NCUST, p=[0.70, 0.24, 0.06])
# Spend propensity is heavy-tailed: a small group carries the loyalty programme.
cust["propensity"] = rng.lognormal(0.0, 0.95, NCUST)
cust["propensity"] *= np.where(cust["tier"] == "Gold", 3.4,
                        np.where(cust["tier"] == "Silver", 1.7, 1.0))

staff_rows = []
for _, b in branches.iterrows():
    n = int(b["tills"] * 1.7)
    for i in range(n):
        staff_rows.append(dict(
            staff_id=f"CB-{b['branch_code']}-{i+1:02d}",
            staff_name=f"{rng.choice(first)} {rng.choice(last)}",
            branch_code=b["branch_code"], role="Cashier",
            hired_date=(pd.Timestamp("2021-01-01")
                        + pd.Timedelta(days=int(rng.integers(0, 1700)))).date(),
        ))
staff = pd.DataFrame(staff_rows)

# The till we want the analysis to find.
SUSPECT_TILL = "CB-KAB-04"

OPEN_HOUR, CLOSE_HOUR = 7, 21
hours = np.arange(OPEN_HOUR, CLOSE_HOUR + 1)

def hour_profile(dow, is_holiday):
    if dow == 5:        # Saturday: broad all-day peak
        w = np.array([0.5,1.4,2.6,3.4,3.8,3.9,3.6,3.4,3.5,3.7,3.4,2.6,1.7,0.9,0.4])
    elif dow == 6:      # Sunday: late start, early close
        w = np.array([0.2,0.5,1.1,2.0,2.8,3.1,3.0,2.8,2.6,2.3,1.8,1.1,0.5,0.2,0.1])
    else:               # Weekday: commuter morning, lunch, and a big evening peak
        w = np.array([1.1,1.8,1.5,1.3,1.5,2.2,2.4,1.9,1.7,2.1,3.4,4.3,4.1,2.6,1.0])
    if is_holiday:
        w = w * np.array([0.3,0.6,1.0,1.4,1.7,1.8,1.7,1.5,1.4,1.3,1.1,0.8,0.5,0.3,0.1])
    return w / w.sum()

hour_probs = np.zeros((NDAYS, len(hours)))
for t in range(NDAYS):
    hour_probs[t] = hour_profile(cal["dow"].iloc[t], cal["is_holiday"].iloc[t])


# --------------------------------------------------------------------------
# 9. Basket construction -- shopping missions create the affinities
# --------------------------------------------------------------------------

MISSIONS = ["Top-up", "Breakfast run", "Weekly shop", "Fresh & meat",
            "Party / event", "School prep", "Baby run", "Household restock"]
MPRIOR = np.array([0.30, 0.12, 0.16, 0.14, 0.07, 0.03, 0.05, 0.13])
MSIZE = np.array([2.3, 3.0, 12.5, 4.6, 10.0, 7.5, 3.6, 5.2])   # mean units/ticket

MW = {
    "Top-up":           {"Airtime & Mobile Money": 8, "Beverages - Soft": 5, "Bakery": 4,
                         "Snacks & Confectionery": 5, "Bags & Sundries": 4,
                         "Dairy & Eggs": 3, "Canned & Packaged": 2},
    "Breakfast run":    {"Bakery": 9, "Dairy & Eggs": 8, "Tea & Coffee": 7,
                         "Sugar & Sweeteners": 5, "Cooking Oil & Fats": 3,
                         "Snacks & Confectionery": 2},
    "Weekly shop":      {"Staples & Grains": 8, "Cooking Oil & Fats": 6,
                         "Sugar & Sweeteners": 6, "Household Cleaning": 6,
                         "Personal Care": 5, "Canned & Packaged": 5,
                         "Fresh Produce": 5, "Dairy & Eggs": 4, "Bakery": 3,
                         "Beverages - Soft": 3, "Bags & Sundries": 3,
                         "Butchery & Fish": 3, "Tea & Coffee": 3},
    "Fresh & meat":     {"Fresh Produce": 10, "Butchery & Fish": 9, "Frozen Foods": 4,
                         "Dairy & Eggs": 3, "Canned & Packaged": 2, "Bags & Sundries": 2},
    "Party / event":    {"Beverages - Alcohol": 10, "Beverages - Soft": 8,
                         "Snacks & Confectionery": 6, "Butchery & Fish": 5,
                         "Frozen Foods": 4, "Bags & Sundries": 4, "Home & Kitchen": 2},
    "School prep":      {"Stationery & School": 12, "Household Cleaning": 4,
                         "Personal Care": 4, "Staples & Grains": 3,
                         "Sugar & Sweeteners": 3, "Snacks & Confectionery": 2,
                         "Home & Kitchen": 2},
    "Baby run":         {"Baby Care": 12, "Dairy & Eggs": 4, "Personal Care": 3,
                         "Household Cleaning": 2, "Bags & Sundries": 2},
    "Household restock":{"Household Cleaning": 10, "Personal Care": 7,
                         "Home & Kitchen": 5, "Bags & Sundries": 4,
                         "Canned & Packaged": 2},
}
Wmat = np.full((len(MISSIONS), len(CATS)), 0.35)
for m, d in MW.items():
    for c, w in d.items():
        Wmat[MISSIONS.index(m), cat_index[c]] = float(w)

# Payment mix drifts toward mobile money over the year -- a real and expensive trend.
PAYMENTS = ["Cash", "MTN MoMo", "Airtel Money", "Card (Visa/Mastercard)", "Staff/Account Credit"]

tx_chunks, ln_chunks = [], []
tx_counter = 0
price_by_day = unit_price[cal["m_idx"].values]
cost_by_day_arr = cost_by_day
vat_exempt_arr = products["vat_exempt"].values
staff_by_branch = {b: staff.loc[staff["branch_code"] == b, "staff_id"].values
                   for b in branches["branch_code"]}

cust_idx_by_branch = {b: np.where(cust["home_branch"].values == b)[0]
                      for b in branches["branch_code"]}
cust_p_by_branch = {}
for b, ix in cust_idx_by_branch.items():
    p = cust["propensity"].values[ix]
    cust_p_by_branch[b] = p / p.sum()

for t in range(NDAYS):
    date = DATES[t]
    dow = cal["dow"].iloc[t]
    m_idx = cal["m_idx"].iloc[t]

    # Mission mix shifts with the day and the season.
    prior = MPRIOR.copy()
    if dow in (4, 5):
        prior[MISSIONS.index("Party / event")] *= 2.4
        prior[MISSIONS.index("Weekly shop")] *= 1.5
        prior[MISSIONS.index("Fresh & meat")] *= 1.4
    if dow == 6:
        prior[MISSIONS.index("Fresh & meat")] *= 1.3
    if cal["payday_intensity"].iloc[t] > 0.55:
        prior[MISSIONS.index("Weekly shop")] *= 2.1
        prior[MISSIONS.index("Household restock")] *= 1.5
        prior[MISSIONS.index("Top-up")] *= 0.7
    if cal["is_school_shopping"].iloc[t]:
        prior[MISSIONS.index("School prep")] *= 9.0
    if cal["month"].iloc[t] == 12:
        prior[MISSIONS.index("Party / event")] *= 1.8
    prior = prior / prior.sum()

    for b in range(NB):
        s = served[t, b]
        total_units = int(s.sum())
        if total_units == 0:
            continue

        pool = np.repeat(np.arange(NS), s)
        pool_cat = cat_of_sku[pool]

        # Assign every unit to a mission via P(mission | category).
        joint = prior[:, None] * Wmat[:, pool_cat]
        joint /= joint.sum(axis=0, keepdims=True)
        u = rng.random(pool.size)
        mission_of_unit = (joint.cumsum(axis=0) < u).sum(axis=0)

        for mi in range(len(MISSIONS)):
            sel = np.where(mission_of_unit == mi)[0]
            if sel.size == 0:
                continue
            units = pool[rng.permutation(sel)]

            # Chunk the mission's units into tickets.
            mean_sz = MSIZE[mi]
            sizes = 1 + rng.poisson(max(mean_sz - 1, 0.2),
                                    size=int(units.size / mean_sz * 1.6) + 8)
            sizes = sizes[np.cumsum(sizes) - sizes < units.size]
            if sizes.size == 0:
                sizes = np.array([units.size])
            cuts = np.cumsum(sizes)
            cuts[-1] = units.size
            starts = np.r_[0, cuts[:-1]]
            ntk = sizes.size

            ticket_ids = np.arange(tx_counter, tx_counter + ntk)
            tx_counter += ntk

            line_ticket = np.repeat(ticket_ids, np.diff(np.r_[starts, units.size]))
            df = pd.DataFrame({"tx_i": line_ticket, "sku_i": units})
            df = df.groupby(["tx_i", "sku_i"], as_index=False).size()
            df.rename(columns={"size": "quantity"}, inplace=True)

            # ---- line economics ----
            si = df["sku_i"].values
            base_price = price_by_day[t][si]
            disc_pct = promo_disc[t, b][si]
            unit_p = np.round(base_price * (1 - disc_pct) / 50) * 50
            df["unit_price_ugx"] = unit_p
            # Where the supplier funds the deal, the rebate lands as a lower
            # effective cost of goods for the promoted units.
            rebate = (base_price - unit_p) * promo_fund[t, b][si]
            df["unit_cost_ugx"] = np.round(cost_by_day_arr[t][si] - rebate)
            df["discount_ugx"] = np.round((base_price - unit_p) * df["quantity"])
            df["line_total_ugx"] = unit_p * df["quantity"]
            df["line_cost_ugx"] = df["unit_cost_ugx"] * df["quantity"]
            ve = vat_exempt_arr[si]
            df["vat_ugx"] = np.where(
                ve, 0.0,
                np.round(df["line_total_ugx"] * VAT_RATE / (1 + VAT_RATE)))
            df["sku"] = products["sku"].values[si]
            df["mission"] = MISSIONS[mi]

            # ---- ticket headers ----
            hh = rng.choice(hours, size=ntk, p=hour_probs[t])
            mm = rng.integers(0, 60, ntk)
            ts = (pd.Timestamp(date) + pd.to_timedelta(hh, unit="h")
                  + pd.to_timedelta(mm, unit="m"))

            cashiers = rng.choice(staff_by_branch[branches["branch_code"].iloc[b]], ntk)

            tot = df.groupby("tx_i", as_index=False).agg(
                n_lines=("sku", "size"), n_units=("quantity", "sum"),
                total_ugx=("line_total_ugx", "sum"),
                cost_ugx=("line_cost_ugx", "sum"),
                vat_ugx=("vat_ugx", "sum"),
                discount_ugx=("discount_ugx", "sum"))
            tot = tot.set_index("tx_i").reindex(ticket_ids).reset_index().rename(
                columns={"index": "tx_i"})

            # Payment method: mobile money share climbs through the year and is
            # higher at Kabalagala; cards concentrate at Ntinda and big baskets.
            mm_share = 0.30 + 0.13 * (t / NDAYS)
            bcode = branches["branch_code"].iloc[b]
            if bcode == "KAB":
                mm_share += 0.09
            if bcode == "NTI":
                mm_share -= 0.04
            big = tot["total_ugx"].values > 60000
            # Card is still a minority tender outside the high-end branches.
            card_share = np.where(big, 0.09, 0.025) + (0.05 if bcode == "NTI" else 0.0)
            p_cash = np.clip(1 - mm_share - card_share - 0.012, 0.05, 1)
            pm = np.empty(ntk, dtype=object)
            r = rng.random(ntk)
            c1 = p_cash
            c2 = c1 + mm_share * 0.62
            c3 = c2 + mm_share * 0.38
            c4 = c3 + card_share
            pm[r < c1] = "Cash"
            pm[(r >= c1) & (r < c2)] = "MTN MoMo"
            pm[(r >= c2) & (r < c3)] = "Airtel Money"
            pm[(r >= c3) & (r < c4)] = "Card (Visa/Mastercard)"
            pm[r >= c4] = "Staff/Account Credit"

            # Loyalty capture ~ 36%, higher on big baskets
            has_loy = rng.random(ntk) < np.clip(0.30 + tot["total_ugx"].values / 400000, 0, 0.72)
            cidx = rng.choice(cust_idx_by_branch[bcode], size=ntk,
                              p=cust_p_by_branch[bcode])
            cust_ids = np.where(has_loy, cust["customer_id"].values[cidx], "")

            # Voids: normal background rate, but one till is an outlier.
            void_p = np.where(cashiers == SUSPECT_TILL, 0.068, 0.011)
            # ...and that till's voids cluster in the evening, after the
            # supervisor has gone home.
            void_p = np.where((cashiers == SUSPECT_TILL) & (hh >= 18), 0.115, void_p)
            voided = rng.random(ntk) < void_p

            # EFRIS fiscalisation (URA e-invoicing). Mostly compliant, with a
            # conspicuous gap on the same till.
            efris_p = np.where(cashiers == SUSPECT_TILL, 0.79, 0.977)
            efris_p = np.where((cashiers == SUSPECT_TILL) & (hh >= 18), 0.62, efris_p)
            efris_p = np.where(pm == "Cash", efris_p - 0.012, efris_p)
            fiscalised = rng.random(ntk) < efris_p

            head = pd.DataFrame({
                "transaction_id": ["TX%08d" % i for i in ticket_ids],
                "datetime": ts,
                "date": pd.Timestamp(date).date(),
                "hour": hh,
                "branch_code": bcode,
                "till_no": rng.integers(1, int(branches["tills"].iloc[b]) + 1, ntk),
                "staff_id": cashiers,
                "customer_id": cust_ids,
                "shopping_mission": MISSIONS[mi],
                "n_lines": tot["n_lines"].values,
                "n_units": tot["n_units"].values,
                "gross_amount_ugx": tot["total_ugx"].values,
                "discount_ugx": tot["discount_ugx"].values,
                "vat_ugx": tot["vat_ugx"].values,
                "cost_of_sales_ugx": tot["cost_ugx"].values,
                "payment_method": pm,
                "is_voided": voided,
                "efris_fiscalised": fiscalised,
            })

            df["transaction_id"] = ["TX%08d" % i for i in df["tx_i"].values]
            df["branch_code"] = bcode
            df["date"] = pd.Timestamp(date).date()

            tx_chunks.append(head)
            ln_chunks.append(df[[
                "transaction_id", "date", "branch_code", "sku", "quantity",
                "unit_price_ugx", "unit_cost_ugx", "discount_ugx",
                "line_total_ugx", "line_cost_ugx", "vat_ugx"]])

transactions = pd.concat(tx_chunks, ignore_index=True)
lines = pd.concat(ln_chunks, ignore_index=True)

# A handful of genuine customer returns, booked as negative lines a few days
# after the original sale. Left in the export on purpose -- an analyst who sums
# quantity without checking the sign will be wrong.
n_ret = int(len(lines) * 0.0016)
ret_idx = rng.choice(len(lines), n_ret, replace=False)
returns = lines.iloc[ret_idx].copy().reset_index(drop=True)
returns["orig_transaction_id"] = returns["transaction_id"].values
returns["transaction_id"] = ["RT%08d" % i for i in range(n_ret)]
returns["quantity"] = -returns["quantity"]
for c in ["discount_ugx", "line_total_ugx", "line_cost_ugx", "vat_ugx"]:
    returns[c] = -returns[c]

# Pull the original ticket's context (till, cashier, customer, tender) so the
# credit note reconciles back to a real sale.
tx_lookup = transactions.set_index("transaction_id")
ctx = tx_lookup.reindex(returns["orig_transaction_id"].values)

lag = pd.to_timedelta(rng.integers(1, 6, n_ret), unit="D")
ret_dt = ctx["datetime"].values + lag
ret_dt = pd.Series(ret_dt).clip(upper=pd.Timestamp(END) + pd.Timedelta(hours=20))

ret_head = pd.DataFrame({
    "transaction_id": returns["transaction_id"].values,
    "datetime": ret_dt.values,
    "date": pd.to_datetime(ret_dt).dt.date.values,
    "hour": pd.to_datetime(ret_dt).dt.hour.values,
    "branch_code": ctx["branch_code"].values,
    "till_no": ctx["till_no"].values,
    "staff_id": ctx["staff_id"].values,
    "customer_id": ctx["customer_id"].values,
    "shopping_mission": "Return",
    "n_lines": 1,
    "n_units": returns["quantity"].values,
    "gross_amount_ugx": returns["line_total_ugx"].values,
    "discount_ugx": returns["discount_ugx"].values,
    "vat_ugx": returns["vat_ugx"].values,
    "cost_of_sales_ugx": returns["line_cost_ugx"].values,
    "payment_method": ctx["payment_method"].values,
    "is_voided": False,
    "efris_fiscalised": rng.random(n_ret) < 0.96,
})

returns["date"] = ret_head["date"].values
lines = pd.concat([lines, returns.drop(columns=["orig_transaction_id"])],
                  ignore_index=True)
transactions = pd.concat([transactions, ret_head], ignore_index=True)
transactions = transactions.sort_values("datetime").reset_index(drop=True)


# --------------------------------------------------------------------------
# 10. Long-format inventory, lost sales and shrinkage
# --------------------------------------------------------------------------

bcodes = branches["branch_code"].values
skus = products["sku"].values

def to_long(arr, name, dtype="float32"):
    d, bb, ss = np.meshgrid(np.arange(NDAYS), np.arange(NB), np.arange(NS), indexing="ij")
    return pd.DataFrame({
        "date": DATES.values[d.ravel()],
        "branch_code": bcodes[bb.ravel()],
        "sku": skus[ss.ravel()],
        name: arr.ravel().astype(dtype),
    })

inv = to_long(closing, "closing_units")
inv["units_sold"] = served.ravel()
inv["units_received"] = receipts_log.ravel()
inv["waste_units"] = waste_log.ravel().round(3)
inv["unexplained_loss_units"] = theft_log.ravel().round(3)
inv["lost_sales_units"] = lost.ravel()
inv["is_stockout"] = stockout.ravel()
inv["date"] = pd.to_datetime(inv["date"]).dt.date

# Trim the inventory file to SKU/branch/day rows that matter (any movement or
# any stock) -- a full cross-join is mostly zeros and needlessly large.
keep = ((inv["closing_units"] > 0) | (inv["units_sold"] != 0)
        | (inv["units_received"] > 0) | (inv["is_stockout"]))
inventory_daily = inv[keep].reset_index(drop=True)

ls = inv.loc[inv["lost_sales_units"] > 0,
             ["date", "branch_code", "sku", "lost_sales_units"]].copy()
ls["month"] = pd.to_datetime(ls["date"]).dt.to_period("M").astype(str)
ls = ls.merge(price_hist[["month", "sku", "unit_price_ugx", "unit_cost_ugx"]],
              on=["month", "sku"], how="left")
ls["lost_revenue_ugx"] = (ls["lost_sales_units"] * ls["unit_price_ugx"]).round(0)
ls["lost_margin_ugx"] = (ls["lost_sales_units"]
                         * (ls["unit_price_ugx"] - ls["unit_cost_ugx"])).round(0)
lost_sales = ls[["date", "branch_code", "sku", "lost_sales_units",
                 "lost_revenue_ugx", "lost_margin_ugx"]]

shrink = inv.loc[(inv["waste_units"] > 0.05) | (inv["unexplained_loss_units"] > 0.05),
                 ["date", "branch_code", "sku", "waste_units", "unexplained_loss_units"]].copy()
shrink["month"] = pd.to_datetime(shrink["date"]).dt.to_period("M").astype(str)
shrink = shrink.merge(price_hist[["month", "sku", "unit_cost_ugx", "unit_price_ugx"]],
                      on=["month", "sku"], how="left")
shrink = shrink.merge(products[["sku", "category", "is_perishable"]], on="sku", how="left")
shrink["waste_cost_ugx"] = (shrink["waste_units"] * shrink["unit_cost_ugx"]).round(0)
shrink["unexplained_cost_ugx"] = (shrink["unexplained_loss_units"] * shrink["unit_cost_ugx"]).round(0)
shrink["total_shrink_cost_ugx"] = shrink["waste_cost_ugx"] + shrink["unexplained_cost_ugx"]
shrink["loss_reason"] = np.where(
    shrink["waste_units"] > shrink["unexplained_loss_units"],
    np.where(shrink["is_perishable"], "Expiry / spoilage", "Damage"),
    "Unexplained (stock count variance)")
shrinkage = shrink[["date", "branch_code", "sku", "category", "loss_reason",
                    "waste_units", "unexplained_loss_units", "waste_cost_ugx",
                    "unexplained_cost_ugx", "total_shrink_cost_ugx"]]


# --------------------------------------------------------------------------
# 11. Staff shifts -- rostered cashier-hours, deliberately not demand-matched
# --------------------------------------------------------------------------

shift_rows = []
for t in range(NDAYS):
    dow = cal["dow"].iloc[t]
    for b in range(NB):
        tills = int(branches["tills"].iloc[b])
        for h in hours:
            # A flat-ish roster: two shifts, a modest Saturday uplift, and no
            # month-end uplift at all.
            if h < 12:
                n = max(2, int(round(tills * 0.45)))
            elif h < 17:
                n = max(2, int(round(tills * 0.55)))
            else:
                n = max(2, int(round(tills * 0.50)))
            if dow == 5:
                n = int(round(n * 1.25))
            if dow == 6:
                n = max(2, int(round(n * 0.7)))
            n = min(n, tills)
            shift_rows.append((DATES[t].date(), branches["branch_code"].iloc[b], int(h), n))
staff_shifts = pd.DataFrame(shift_rows, columns=["date", "branch_code", "hour",
                                                 "cashiers_rostered"])


# --------------------------------------------------------------------------
# 12. Write everything out
# --------------------------------------------------------------------------

def w(df, name):
    p = os.path.join(DATA, name)
    df.to_csv(p, index=False)
    print(f"  {name:<26} {len(df):>10,} rows  {os.path.getsize(p)/1e6:8.1f} MB")

print(f"\n{CHAIN_NAME} -- FY2025/26 dataset")
print(f"Period {START.date()} to {END.date()}  ({NDAYS} days, {NS} SKUs, {NB} branches)\n")

w(branches, "branches.csv")
w(suppliers, "suppliers.csv")
w(products.drop(columns=["cat_idx"]), "products.csv")
w(cal.drop(columns=["m_idx"]), "calendar.csv")
w(price_hist, "price_history.csv")
w(promotions, "promotions.csv")
w(cust.drop(columns=["propensity"]), "customers.csv")
w(staff, "staff.csv")
w(staff_shifts, "staff_shifts.csv")
w(transactions, "transactions.csv")
w(lines, "transaction_lines.csv")
w(inventory_daily, "inventory_daily.csv")
w(lost_sales, "lost_sales.csv")
w(shrinkage, "shrinkage.csv")
w(purchase_orders, "purchase_orders.csv")

net = transactions.loc[~transactions["is_voided"], "gross_amount_ugx"].sum()
print(f"\n  Net recorded sales : UGX {net:,.0f}")
print(f"  Tickets            : {len(transactions):,}")
print(f"  Line items         : {len(lines):,}")
print(f"  Lost sales (truth) : UGX {lost_sales['lost_revenue_ugx'].sum():,.0f}")
print(f"  Shrinkage at cost  : UGX {shrinkage['total_shrink_cost_ugx'].sum():,.0f}")
print("\nDone.")
