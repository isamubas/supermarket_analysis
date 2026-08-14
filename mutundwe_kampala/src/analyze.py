"""
Full analysis pass over the Mutundwe Family Supermarket FY2025/26 dataset.

Prints a readable findings report and writes outputs/findings.json for the
client-facing deck.

Analytical care taken here (and worth saying out loud in the meeting):
  * voided tickets are stripped from BOTH the header and the line table -- the
    line table carries no void flag, so a naive sum overstates sales;
  * returns are negative lines and are netted off revenue, not counted as
    baskets;
  * airtime/Yaka is reported separately from retail, because booking a
    UGX 10,000 airtime top-up as UGX 10,000 of "sales" wrecks every margin
    percentage in the business;
  * margin is measured against the cost in force in the month of sale, not
    today's cost.
"""

from __future__ import annotations

import json
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(HERE, "..", "outputs")
os.makedirs(OUT, exist_ok=True)
P = lambda f: os.path.join(DATA, f)

F = {}          # findings, dumped to JSON at the end
UGX = lambda v: f"UGX {v:,.0f}"
PCT = lambda v: f"{v:.1f}%"


def h(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------
tx = pd.read_csv(P("transactions.csv"), parse_dates=["datetime"])
ln = pd.read_csv(P("transaction_lines.csv"))
products = pd.read_csv(P("products.csv"))
branches = pd.read_csv(P("branches.csv"))
suppliers = pd.read_csv(P("suppliers.csv"))
cal = pd.read_csv(P("calendar.csv"), parse_dates=["date"])
inv = pd.read_csv(P("inventory_daily.csv"), parse_dates=["date"])
shr = pd.read_csv(P("shrinkage.csv"), parse_dates=["date"])
lost = pd.read_csv(P("lost_sales.csv"), parse_dates=["date"])
po = pd.read_csv(P("purchase_orders.csv"), parse_dates=["order_date"])
promos = pd.read_csv(P("promotions.csv"), parse_dates=["start_date", "end_date"])
custs = pd.read_csv(P("customers.csv"))
shifts = pd.read_csv(P("staff_shifts.csv"), parse_dates=["date"])

tx["date"] = pd.to_datetime(tx["date"])
ln["date"] = pd.to_datetime(ln["date"])

# ---- the cleaning step every analyst must do on this export ----
n_raw_lines, n_raw_tx = len(ln), len(tx)
void_ids = set(tx.loc[tx["is_voided"], "transaction_id"])
ln = ln[~ln["transaction_id"].isin(void_ids)].copy()
tx_clean = tx[~tx["is_voided"]].copy()

ln = ln.merge(products[["sku", "product_name", "category", "subcategory",
                        "supplier_name", "is_kvi", "vat_exempt"]], on="sku", how="left")
ln["margin_ugx"] = ln["line_total_ugx"] - ln["line_cost_ugx"]

is_return = ln["quantity"] < 0
sales_tx = tx_clean[tx_clean["shopping_mission"] != "Return"].copy()

# Airtime / Yaka is an agency service, not retail turnover.
SERVICE_CAT = "Airtime & Mobile Money"
retail = ln[ln["category"] != SERVICE_CAT]
service = ln[ln["category"] == SERVICE_CAT]

net_sales = ln["line_total_ugx"].sum()
retail_sales = retail["line_total_ugx"].sum()
service_sales = service["line_total_ugx"].sum()
gross_margin = ln["margin_ugx"].sum()
retail_margin = retail["margin_ugx"].sum()
service_margin = service["margin_ugx"].sum()


# --------------------------------------------------------------------------
h("0. DATA QUALITY -- what the raw export does not tell you")
# --------------------------------------------------------------------------
n_void = n_raw_tx - len(tx_clean)
void_value = tx.loc[tx["is_voided"], "gross_amount_ugx"].sum()
n_ret = int(is_return.sum())
efris_gap = 1 - tx_clean["efris_fiscalised"].mean()
unfiscalised_value = tx_clean.loc[~tx_clean["efris_fiscalised"], "gross_amount_ugx"].sum()

print(f"Raw tickets in export        : {n_raw_tx:,}")
print(f"  voided (must be removed)   : {n_void:,}  worth {UGX(void_value)}")
print(f"Raw line items               : {n_raw_lines:,}")
print(f"  return lines (negative qty): {n_ret:,}")
print(f"Tickets not fiscalised (EFRIS): {(~tx_clean['efris_fiscalised']).sum():,}"
      f"  ({PCT(efris_gap*100)})  worth {UGX(unfiscalised_value)}")
print("\nNOTE: transaction_lines.csv carries NO void flag. Summing it directly")
print(f"      overstates turnover by {UGX(void_value)} before you start.")

F["data_quality"] = dict(
    raw_tickets=n_raw_tx, voided_tickets=int(n_void), voided_value=float(void_value),
    raw_lines=n_raw_lines, return_lines=n_ret,
    efris_gap_pct=float(efris_gap * 100), unfiscalised_value=float(unfiscalised_value))


# --------------------------------------------------------------------------
h("1. HEADLINE -- FY2025/26 (1 Jul 2025 - 30 Jun 2026)")
# --------------------------------------------------------------------------
n_baskets = len(sales_tx)
avg_basket = sales_tx["gross_amount_ugx"].mean()
units_per_basket = sales_tx["n_units"].mean()

print(f"Net sales (all)              : {UGX(net_sales)}")
print(f"  of which retail goods      : {UGX(retail_sales)}  ({PCT(retail_sales/net_sales*100)})")
print(f"  of which airtime/Yaka      : {UGX(service_sales)}  ({PCT(service_sales/net_sales*100)})")
print(f"Gross margin (all)           : {UGX(gross_margin)}  ({PCT(gross_margin/net_sales*100)})")
print(f"Gross margin (retail only)   : {UGX(retail_margin)}  ({PCT(retail_margin/retail_sales*100)})")
print(f"Airtime margin               : {UGX(service_margin)}  ({PCT(service_margin/service_sales*100)})")
print(f"\nBaskets                      : {n_baskets:,}")
print(f"Average basket               : {UGX(avg_basket)}   ({units_per_basket:.1f} units)")
print(f"Baskets/day/branch           : {n_baskets/365/3:.0f}")

print("\n>> Airtime is 4.5% of 'sales' at a 3.5% margin. Reported on the same")
print("   line as groceries it drags the blended margin down and hides how the")
print("   grocery business is really performing.")

F["headline"] = dict(
    net_sales=float(net_sales), retail_sales=float(retail_sales),
    service_sales=float(service_sales), gross_margin=float(gross_margin),
    gross_margin_pct=float(gross_margin / net_sales * 100),
    retail_margin_pct=float(retail_margin / retail_sales * 100),
    service_margin_pct=float(service_margin / service_sales * 100),
    baskets=int(n_baskets), avg_basket=float(avg_basket),
    units_per_basket=float(units_per_basket))

# monthly trend
ln["month"] = ln["date"].dt.to_period("M").astype(str)
monthly = ln.groupby("month").agg(sales=("line_total_ugx", "sum"),
                                  margin=("margin_ugx", "sum")).reset_index()
monthly["margin_pct"] = monthly["margin"] / monthly["sales"] * 100
mb = sales_tx.assign(month=sales_tx["date"].dt.to_period("M").astype(str)) \
             .groupby("month").agg(baskets=("transaction_id", "size"),
                                   avg_basket=("gross_amount_ugx", "mean")).reset_index()
monthly = monthly.merge(mb, on="month")
print("\nMonthly:")
print(monthly.assign(sales=lambda d: (d["sales"]/1e6).round(1),
                     margin=lambda d: (d["margin"]/1e6).round(1),
                     margin_pct=lambda d: d["margin_pct"].round(1),
                     avg_basket=lambda d: d["avg_basket"].round(0))
      .rename(columns={"sales": "sales_M", "margin": "margin_M"}).to_string(index=False))
F["monthly"] = monthly.to_dict("records")


# --------------------------------------------------------------------------
h("2. REVENUE LIES -- category revenue share vs margin share")
# --------------------------------------------------------------------------
cat = ln.groupby("category").agg(sales=("line_total_ugx", "sum"),
                                 margin=("margin_ugx", "sum"),
                                 units=("quantity", "sum")).reset_index()
cat["margin_pct"] = cat["margin"] / cat["sales"] * 100
cat["sales_share"] = cat["sales"] / cat["sales"].sum() * 100
cat["margin_share"] = cat["margin"] / cat["margin"].sum() * 100
cat["gap"] = cat["margin_share"] - cat["sales_share"]
cat = cat.sort_values("sales", ascending=False)

print(cat.assign(sales_M=lambda d: (d["sales"]/1e6).round(0),
                 margin_M=lambda d: (d["margin"]/1e6).round(0),
                 margin_pct=lambda d: d["margin_pct"].round(1),
                 sales_share=lambda d: d["sales_share"].round(1),
                 margin_share=lambda d: d["margin_share"].round(1),
                 gap=lambda d: d["gap"].round(1))
      [["category", "sales_M", "sales_share", "margin_M", "margin_share",
        "margin_pct", "gap"]].to_string(index=False))

worst = cat.nsmallest(4, "gap")
best = cat.nlargest(4, "gap")
print("\n>> Biggest destroyers of margin share (revenue >> margin):")
for _, r in worst.iterrows():
    print(f"     {r['category']:<24} {r['sales_share']:5.1f}% of sales -> "
          f"{r['margin_share']:5.1f}% of margin  (GM {r['margin_pct']:.1f}%)")
print(">> Quietly carrying the business:")
for _, r in best.iterrows():
    print(f"     {r['category']:<24} {r['sales_share']:5.1f}% of sales -> "
          f"{r['margin_share']:5.1f}% of margin  (GM {r['margin_pct']:.1f}%)")
F["category"] = cat.to_dict("records")


# --------------------------------------------------------------------------
h("3. BRANCH SCORECARD")
# --------------------------------------------------------------------------
bl = ln.groupby("branch_code").agg(sales=("line_total_ugx", "sum"),
                                   margin=("margin_ugx", "sum")).reset_index()
bt = sales_tx.groupby("branch_code").agg(baskets=("transaction_id", "size"),
                                         avg_basket=("gross_amount_ugx", "mean"),
                                         units=("n_units", "mean")).reset_index()
bsh = shr.groupby("branch_code").agg(
    waste=("waste_cost_ugx", "sum"), unexplained=("unexplained_cost_ugx", "sum")).reset_index()
blost = lost.groupby("branch_code").agg(lost_rev=("lost_revenue_ugx", "sum"),
                                        lost_margin=("lost_margin_ugx", "sum")).reset_index()
bs = bl.merge(bt, on="branch_code").merge(bsh, on="branch_code").merge(blost, on="branch_code")
bs = bs.merge(branches[["branch_code", "branch_name", "tills"]], on="branch_code")
bs["margin_pct"] = bs["margin"] / bs["sales"] * 100
bs["shrink_pct_of_sales"] = (bs["waste"] + bs["unexplained"]) / bs["sales"] * 100
bs["unexplained_pct_of_sales"] = bs["unexplained"] / bs["sales"] * 100
bs = bs.sort_values("sales", ascending=False)

print(bs.assign(sales_M=lambda d: (d["sales"]/1e6).round(0),
                margin_pct=lambda d: d["margin_pct"].round(1),
                avg_basket=lambda d: d["avg_basket"].round(0),
                waste_M=lambda d: (d["waste"]/1e6).round(1),
                unexpl_M=lambda d: (d["unexplained"]/1e6).round(1),
                unexpl_pct=lambda d: d["unexplained_pct_of_sales"].round(2),
                lost_M=lambda d: (d["lost_rev"]/1e6).round(0))
      [["branch_name", "sales_M", "margin_pct", "baskets", "avg_basket",
        "waste_M", "unexpl_M", "unexpl_pct", "lost_M"]].to_string(index=False))
F["branches"] = bs.to_dict("records")


# --------------------------------------------------------------------------
h("4. THE INVISIBLE NUMBER -- sales lost to empty shelves")
# --------------------------------------------------------------------------
lost_rev = lost["lost_revenue_ugx"].sum()
lost_mgn = lost["lost_margin_ugx"].sum()
so_rate = inv["is_stockout"].mean() * 100
inv["dom"] = inv["date"].dt.day
me_mask = inv["dom"].ge(25) | inv["dom"].le(3)
so_me = inv.loc[me_mask, "is_stockout"].mean() * 100
so_rest = inv.loc[~me_mask, "is_stockout"].mean() * 100

print(f"Lost revenue (demand that walked out) : {UGX(lost_rev)}")
print(f"Lost gross margin                     : {UGX(lost_mgn)}")
print(f"  = {PCT(lost_rev/net_sales*100)} of turnover, and "
      f"{PCT(lost_mgn/gross_margin*100)} of the margin actually earned")
print(f"\nSKU-days out of stock                 : {so_rate:.2f}%")
print(f"  month-end window (25th - 3rd)       : {so_me:.2f}%")
print(f"  rest of the month                   : {so_rest:.2f}%")
print(f"  -> {so_me/so_rest:.1f}x worse exactly when customers have money")

lost_sku = lost.merge(products[["sku", "product_name", "category", "is_kvi"]], on="sku")
top_lost = lost_sku.groupby(["product_name", "category", "is_kvi"], as_index=False) \
                   .agg(lost_rev=("lost_revenue_ugx", "sum"),
                        lost_units=("lost_sales_units", "sum")) \
                   .nlargest(15, "lost_rev")
print("\nWorst 15 lines for lost sales:")
print(top_lost.assign(lost_M=lambda d: (d["lost_rev"]/1e6).round(1))
      [["product_name", "category", "is_kvi", "lost_units", "lost_M"]].to_string(index=False))

kvi_lost = lost_sku.loc[lost_sku["is_kvi"], "lost_revenue_ugx"].sum()
print(f"\n>> {PCT(kvi_lost/lost_rev*100)} of lost sales sit on 'known value items' -- "
      f"the\n   lines a shopper prices in their head. Running dry on sugar, oil or")
print("   bread does not just lose that sale, it teaches the customer to shop elsewhere.")

F["lost_sales"] = dict(
    lost_revenue=float(lost_rev), lost_margin=float(lost_mgn),
    pct_of_turnover=float(lost_rev / net_sales * 100),
    stockout_rate=float(so_rate), stockout_month_end=float(so_me),
    stockout_rest=float(so_rest), kvi_share=float(kvi_lost / lost_rev * 100),
    top_lost=top_lost.to_dict("records"))


# --------------------------------------------------------------------------
h("5. SHRINKAGE -- waste you can see, and loss you cannot")
# --------------------------------------------------------------------------
tot_waste = shr["waste_cost_ugx"].sum()
tot_unexp = shr["unexplained_cost_ugx"].sum()
print(f"Spoilage / expiry / damage : {UGX(tot_waste)}  ({PCT(tot_waste/net_sales*100)} of sales)")
print(f"Unexplained stock variance : {UGX(tot_unexp)}  ({PCT(tot_unexp/net_sales*100)} of sales)")
print(f"Total shrinkage            : {UGX(tot_waste+tot_unexp)}  "
      f"({PCT((tot_waste+tot_unexp)/net_sales*100)} of sales)")

sc = shr.groupby(["branch_code", "category"], as_index=False)["unexplained_cost_ugx"].sum()
piv = sc.pivot(index="category", columns="branch_code",
               values="unexplained_cost_ugx").fillna(0)
piv["KAB_vs_others"] = piv["KAB"] / (piv[["NAK", "NTI"]].mean(axis=1) + 1)
print("\nUnexplained loss by category and branch (UGX, at cost):")
print(piv.sort_values("KAB", ascending=False).head(8).round(0).to_string())

print(f"\n>> Kabalagala loses {UGX(piv['KAB'].sum())} to unexplained variance against")
print(f"   {UGX(piv['NAK'].sum())} at Nakawa and {UGX(piv['NTI'].sum())} at Ntinda --")
print("   and it is the SMALLEST branch. This is not breakage. It is a control problem.")

# waste concentration
wc = shr.groupby("category", as_index=False)["waste_cost_ugx"].sum()
wc = wc[wc["waste_cost_ugx"] > 0].nlargest(8, "waste_cost_ugx")
print("\nWhere the spoilage actually is:")
print(wc.assign(waste_M=lambda d: (d["waste_cost_ugx"]/1e6).round(1))
      [["category", "waste_M"]].to_string(index=False))

# power outages vs cold chain waste
cold = shr[shr["category"].isin(["Frozen Foods", "Dairy & Eggs", "Butchery & Fish"])]
cw = cold.groupby("date", as_index=False)["waste_cost_ugx"].sum().merge(
    cal[["date", "power_outage_hours"]], on="date")
with_out = cw.loc[cw["power_outage_hours"] > 0, "waste_cost_ugx"].mean()
no_out = cw.loc[cw["power_outage_hours"] == 0, "waste_cost_ugx"].mean()
print(f"\nCold-chain waste on days with a power cut : {UGX(with_out)}/day")
print(f"                        on clean days      : {UGX(no_out)}/day")
print(f"  -> every outage day costs about {UGX(with_out-no_out)} in melted stock")

F["shrinkage"] = dict(
    waste=float(tot_waste), unexplained=float(tot_unexp),
    total_pct_of_sales=float((tot_waste + tot_unexp) / net_sales * 100),
    by_branch_unexplained={k: float(v) for k, v in piv[["KAB", "NAK", "NTI"]].sum().items()},
    outage_day_cost=float(with_out - no_out),
    waste_by_category=wc.to_dict("records"))


# --------------------------------------------------------------------------
h("6. THE SUGAR TRAP -- buying price moved, shelf price did not")
# --------------------------------------------------------------------------
sug = ln[ln["category"] == "Sugar & Sweeteners"].groupby("month").agg(
    sales=("line_total_ugx", "sum"), margin=("margin_ugx", "sum"),
    units=("quantity", "sum")).reset_index()
sug["margin_pct"] = sug["margin"] / sug["sales"] * 100
print(sug.assign(sales_M=lambda d: (d["sales"]/1e6).round(1),
                 margin_M=lambda d: (d["margin"]/1e6).round(2),
                 margin_pct=lambda d: d["margin_pct"].round(1))
      [["month", "units", "sales_M", "margin_M", "margin_pct"]].to_string(index=False))

trough = sug.loc[sug["margin_pct"].idxmin()]
normal = sug.loc[sug["month"] <= "2025-10", "margin_pct"].mean()
lost_sugar = ((normal - sug["margin_pct"]).clip(lower=0) / 100 * sug["sales"]).sum()
print(f"\n>> Sugar margin fell from {normal:.1f}% to {trough['margin_pct']:.1f}% in {trough['month']}.")
print(f"   Mill prices rose in November; the shelf price only caught up in February.")
print(f"   That three-month lag cost roughly {UGX(lost_sugar)} in margin.")
print("   Sugar is a footfall line, so you may CHOOSE to absorb it -- but that")
print("   has to be a decision, not something you find out about in June.")
F["sugar"] = dict(monthly=sug.to_dict("records"), margin_lost=float(lost_sugar),
                  normal_margin=float(normal), trough_margin=float(trough["margin_pct"]),
                  trough_month=str(trough["month"]))


# --------------------------------------------------------------------------
h("7. COST OF GETTING PAID -- payment mix")
# --------------------------------------------------------------------------
# Assumed charges -- MUST be confirmed against the client's actual merchant
# agreements before any of this is presented as fact.
CHARGES = {"Cash": 0.0035, "MTN MoMo": 0.0100, "Airtel Money": 0.0100,
           "Card (Visa/Mastercard)": 0.0300, "Staff/Account Credit": 0.0}
pay = sales_tx.groupby("payment_method", as_index=False).agg(
    value=("gross_amount_ugx", "sum"), baskets=("transaction_id", "size"),
    avg_basket=("gross_amount_ugx", "mean"))
pay["share"] = pay["value"] / pay["value"].sum() * 100
pay["assumed_rate"] = pay["payment_method"].map(CHARGES)
pay["annual_cost"] = pay["value"] * pay["assumed_rate"]
pay = pay.sort_values("value", ascending=False)
print(pay.assign(value_M=lambda d: (d["value"]/1e6).round(0),
                 share=lambda d: d["share"].round(1),
                 avg_basket=lambda d: d["avg_basket"].round(0),
                 rate=lambda d: (d["assumed_rate"]*100).round(2),
                 cost_M=lambda d: (d["annual_cost"]/1e6).round(1))
      [["payment_method", "value_M", "share", "baskets", "avg_basket", "rate",
        "cost_M"]].to_string(index=False))

half1 = sales_tx[sales_tx["date"] < "2026-01-01"]
half2 = sales_tx[sales_tx["date"] >= "2026-01-01"]
mm = lambda d: d.loc[d["payment_method"].isin(["MTN MoMo", "Airtel Money"]),
                     "gross_amount_ugx"].sum() / d["gross_amount_ugx"].sum() * 100
print(f"\nMobile money share  H1 (Jul-Dec): {mm(half1):.1f}%   H2 (Jan-Jun): {mm(half2):.1f}%")
print(f"Total assumed cost of accepting payment: {UGX(pay['annual_cost'].sum())} "
      f"({PCT(pay['annual_cost'].sum()/net_sales*100)} of sales)")
print(f"  = {PCT(pay['annual_cost'].sum()/gross_margin*100)} of your gross margin.")
print("\n>> RATES ABOVE ARE ASSUMPTIONS. Step one of the real engagement is pulling")
print("   your actual MTN/Airtel merchant statements and card MDR schedule.")

F["payments"] = dict(mix=pay.to_dict("records"),
                     total_cost=float(pay["annual_cost"].sum()),
                     mm_h1=float(mm(half1)), mm_h2=float(mm(half2)),
                     pct_of_margin=float(pay["annual_cost"].sum() / gross_margin * 100))


# --------------------------------------------------------------------------
h("8. WHEN THE MONEY COMES IN -- payday, hours, and the queue")
# --------------------------------------------------------------------------
daily = ln.groupby("date", as_index=False)["line_total_ugx"].sum().merge(
    cal[["date", "day_of_month", "dow", "payday_intensity", "is_rainy_day",
         "is_holiday", "election_phase", "is_school_shopping"]], on="date")
daily["is_month_end"] = daily["day_of_month"].ge(25) | daily["day_of_month"].le(3)
me_share = daily.loc[daily["is_month_end"], "line_total_ugx"].sum() / daily["line_total_ugx"].sum() * 100
me_days = daily["is_month_end"].mean() * 100
print(f"Days in the payday window (25th-3rd) : {me_days:.0f}% of the year")
print(f"Sales taken in that window           : {me_share:.1f}% of turnover")
print(f"  -> those days run {me_share/me_days:.2f}x the average day")

dow_sales = daily.groupby("dow", as_index=False)["line_total_ugx"].mean()
dow_sales["day"] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
print("\nAverage day by weekday (UGX m):")
print(dow_sales.assign(m=lambda d: (d["line_total_ugx"]/1e6).round(1))[["day", "m"]].to_string(index=False))

rain = daily.groupby("is_rainy_day", as_index=False)["line_total_ugx"].mean()
rr = rain.set_index("is_rainy_day")["line_total_ugx"]
print(f"\nRainy day vs dry day: {UGX(rr[True])} vs {UGX(rr[False])} "
      f"({(rr[True]/rr[False]-1)*100:+.1f}%)")

# staffing pressure
hr = sales_tx.groupby(["branch_code", "date", "hour"], as_index=False).agg(
    baskets=("transaction_id", "size"))
hr = hr.merge(shifts, on=["branch_code", "date", "hour"], how="left")
hr["baskets_per_cashier"] = hr["baskets"] / hr["cashiers_rostered"]
hp = hr.groupby("hour", as_index=False).agg(
    baskets=("baskets", "mean"), rostered=("cashiers_rostered", "mean"),
    per_cashier=("baskets_per_cashier", "mean"))
print("\nAverage hour, all branches:")
print(hp.assign(baskets=lambda d: d["baskets"].round(1),
                rostered=lambda d: d["rostered"].round(1),
                per_cashier=lambda d: d["per_cashier"].round(1)).to_string(index=False))

peak = hp.nlargest(3, "per_cashier")
quiet = hp.nsmallest(3, "per_cashier")
print(f"\n>> Busiest tills: {', '.join(f'{int(r.hour)}:00' for r in peak.itertuples())} "
      f"at ~{peak['per_cashier'].mean():.0f} baskets/cashier/hour")
print(f">> Quietest    : {', '.join(f'{int(r.hour)}:00' for r in quiet.itertuples())} "
      f"at ~{quiet['per_cashier'].mean():.0f}")
print("   The roster is essentially flat. It does not follow the evening peak,")
print("   the Saturday peak, or the payday peak.")

me_hr = hr.merge(cal[["date", "day_of_month"]], on="date")
me_hr["me"] = me_hr["day_of_month"].ge(25) | me_hr["day_of_month"].le(3)
print(f"\nBaskets per rostered cashier-hour, payday window : "
      f"{me_hr.loc[me_hr['me'],'baskets_per_cashier'].mean():.1f}")
print(f"                                  rest of month  : "
      f"{me_hr.loc[~me_hr['me'],'baskets_per_cashier'].mean():.1f}")

F["timing"] = dict(
    month_end_sales_share=float(me_share), month_end_day_share=float(me_days),
    rain_effect_pct=float((rr[True] / rr[False] - 1) * 100),
    hourly=hp.to_dict("records"),
    dow=dow_sales[["day", "line_total_ugx"]].to_dict("records"),
    per_cashier_month_end=float(me_hr.loc[me_hr["me"], "baskets_per_cashier"].mean()),
    per_cashier_rest=float(me_hr.loc[~me_hr["me"], "baskets_per_cashier"].mean()))


# --------------------------------------------------------------------------
h("9. THE JANUARY ELECTION AND OTHER LOCAL SHOCKS")
# --------------------------------------------------------------------------
ev = daily.groupby("election_phase", as_index=False)["line_total_ugx"].mean()
baseline = daily.loc[daily["election_phase"].isna() | (daily["election_phase"] == ""),
                     "line_total_ugx"].mean()
print(f"Baseline day: {UGX(baseline)}")
for _, r in ev.iterrows():
    if isinstance(r["election_phase"], str) and r["election_phase"]:
        print(f"  {r['election_phase']:<24} {UGX(r['line_total_ugx'])}  "
              f"({(r['line_total_ugx']/baseline-1)*100:+.0f}%)")
sch = daily.groupby("is_school_shopping", as_index=False)["line_total_ugx"].mean()
ss = sch.set_index("is_school_shopping")["line_total_ugx"]
print(f"\nSchool-term shopping window: {UGX(ss[True])}/day vs {UGX(ss[False])} "
      f"({(ss[True]/ss[False]-1)*100:+.0f}%)")
stat = ln[ln["category"] == "Stationery & School"].groupby("month")["line_total_ugx"].sum()
print(f"\nStationery is {PCT(stat.sum()/net_sales*100)} of the year's sales but")
print(f"  {PCT(stat.nlargest(3).sum()/stat.sum()*100)} of it lands in just 3 months:")
print("  " + ", ".join(f"{m} ({v/1e6:.0f}m)" for m, v in stat.nlargest(3).items()))
F["shocks"] = dict(
    baseline_day=float(baseline),
    election=[{"phase": r["election_phase"], "avg": float(r["line_total_ugx"]),
               "vs_baseline_pct": float(r["line_total_ugx"]/baseline*100-100)}
              for _, r in ev.iterrows() if isinstance(r["election_phase"], str) and r["election_phase"]],
    school_uplift_pct=float((ss[True]/ss[False]-1)*100),
    stationery_top3_share=float(stat.nlargest(3).sum()/stat.sum()*100))


# --------------------------------------------------------------------------
h("10. WHAT SELLS WITH WHAT -- basket affinity")
# --------------------------------------------------------------------------
bl2 = ln.loc[~is_return.reindex(ln.index, fill_value=False)
             & ln["transaction_id"].isin(set(sales_tx["transaction_id"])),
             ["transaction_id", "sku", "product_name", "category"]]
top_skus = bl2["sku"].value_counts().nlargest(70).index
sub = bl2[bl2["sku"].isin(top_skus)]
codes = {s: i for i, s in enumerate(top_skus)}
tix = sub["transaction_id"].astype("category")
M = np.zeros((len(tix.cat.categories), len(top_skus)), dtype=bool)
M[tix.cat.codes.values, sub["sku"].map(codes).values] = True
N = M.shape[0]
co = M.T.astype(np.float32) @ M.astype(np.float32)
sup = np.diag(co) / N
lift = (co / N) / (sup[:, None] * sup[None, :])
np.fill_diagonal(lift, 0)
name_of = products.set_index("sku")["product_name"].to_dict()
cat_of = products.set_index("sku")["category"].to_dict()

pairs = []
sk = list(top_skus)
for i in range(len(sk)):
    for j in range(i + 1, len(sk)):
        if co[i, j] / N > 0.004:
            pairs.append((name_of[sk[i]], name_of[sk[j]], cat_of[sk[i]], cat_of[sk[j]],
                          co[i, j] / N * 100, lift[i, j], co[i, j]))
pairs = pd.DataFrame(pairs, columns=["item_a", "item_b", "cat_a", "cat_b",
                                     "support_pct", "lift", "baskets"])
top_pairs = pairs.nlargest(15, "lift")
print("Strongest pairs (lift > 1 means they are bought together more than chance):")
print(top_pairs.assign(support_pct=lambda d: d["support_pct"].round(2),
                       lift=lambda d: d["lift"].round(2))
      [["item_a", "item_b", "support_pct", "lift", "baskets"]].to_string(index=False))

cross = pairs[pairs["cat_a"] != pairs["cat_b"]].nlargest(12, "lift")
print("\nStrongest CROSS-CATEGORY pairs -- the actual merchandising opportunity,")
print("because these items sit in different aisles:")
print(cross.assign(support_pct=lambda d: d["support_pct"].round(2),
                   lift=lambda d: d["lift"].round(2))
      [["item_a", "cat_a", "item_b", "cat_b", "lift", "baskets"]].to_string(index=False))
print("\n>> Within-category lift (beer with beer, rice with posho) tells you the")
print("   basket archetype is real. Cross-category lift tells you where to put a")
print("   secondary display, and which pairs to never let go out of stock together.")
F["affinity"] = top_pairs.to_dict("records")
F["affinity_cross"] = cross.to_dict("records")

# basket size by mission
miss = sales_tx.groupby("shopping_mission", as_index=False).agg(
    baskets=("transaction_id", "size"), avg=("gross_amount_ugx", "mean"),
    total=("gross_amount_ugx", "sum"))
miss["share"] = miss["total"] / miss["total"].sum() * 100
print("\nBasket archetypes:")
print(miss.sort_values("total", ascending=False)
      .assign(avg=lambda d: d["avg"].round(0), share=lambda d: d["share"].round(1),
              total_M=lambda d: (d["total"]/1e6).round(0))
      [["shopping_mission", "baskets", "avg", "total_M", "share"]].to_string(index=False))
F["missions"] = miss.to_dict("records")


# --------------------------------------------------------------------------
h("11. DEAD STOCK -- capital sleeping on the shelf")
# --------------------------------------------------------------------------
sku_sales = ln.groupby("sku", as_index=False).agg(
    sales=("line_total_ugx", "sum"), margin=("margin_ugx", "sum"),
    units=("quantity", "sum"))
sku_sales = sku_sales.merge(products[["sku", "product_name", "category",
                                      "unit_cost_ugx"]], on="sku", how="right").fillna(0)
sku_sales = sku_sales.sort_values("sales", ascending=False)
sku_sales["cum_share"] = sku_sales["sales"].cumsum() / sku_sales["sales"].sum() * 100

# Chain-wide stock on hand: sum the three branches on each date, then average
# over dates. Averaging across branches first would understate cover 3x, since
# unit sales below are chain-wide.
stockv = (inv.groupby(["date", "sku"], as_index=False)["closing_units"].sum()
            .groupby("sku", as_index=False)["closing_units"].mean()
            .merge(products[["sku", "unit_cost_ugx"]], on="sku"))
stockv["stock_value"] = stockv["closing_units"] * stockv["unit_cost_ugx"]
sku_sales = sku_sales.merge(stockv[["sku", "closing_units", "stock_value"]], on="sku")
sku_sales["daily_units"] = sku_sales["units"] / 365
sku_sales["days_cover"] = np.where(sku_sales["daily_units"] > 0,
                                   sku_sales["closing_units"] / sku_sales["daily_units"], 999)

n80 = int((sku_sales["cum_share"] <= 80).sum()) + 1
tail = sku_sales[sku_sales["cum_share"] > 95]
print(f"{n80} SKUs ({n80/len(sku_sales)*100:.0f}% of the range) make 80% of sales.")
print(f"The bottom {len(tail)} SKUs ({len(tail)/len(sku_sales)*100:.0f}% of the range) "
      f"make {PCT(tail['sales'].sum()/sku_sales['sales'].sum()*100)} of sales")
print(f"  but hold {UGX(tail['stock_value'].sum())} of stock at cost.")

slow = sku_sales[(sku_sales["days_cover"] > 60)].nlargest(15, "stock_value")
print("\nSlowest-moving stock by capital tied up:")
print(slow.assign(days_cover=lambda d: d["days_cover"].round(0),
                  stock_value=lambda d: d["stock_value"].round(0),
                  sales_M=lambda d: (d["sales"]/1e6).round(1))
      [["product_name", "category", "sales_M", "days_cover", "stock_value"]].to_string(index=False))
F["dead_stock"] = dict(
    skus_for_80pct=int(n80), total_skus=int(len(sku_sales)),
    tail_skus=int(len(tail)), tail_sales_pct=float(tail["sales"].sum()/sku_sales["sales"].sum()*100),
    tail_stock_value=float(tail["stock_value"].sum()),
    slow_movers=slow[["product_name", "category", "days_cover", "stock_value"]].to_dict("records"))


# --------------------------------------------------------------------------
h("12. WORKING CAPITAL -- who is financing whom")
# --------------------------------------------------------------------------
inv_value = (inv.groupby("date").apply(
    lambda d: (d["closing_units"] * d["sku"].map(
        products.set_index("sku")["unit_cost_ugx"])).sum(), include_groups=False)).mean()
cogs = ln["line_cost_ugx"].sum()
inv_days = inv_value / (cogs / 365)

sup_val = po.groupby("supplier_id", as_index=False)["received_value_ugx"].sum().merge(
    suppliers[["supplier_id", "supplier_name", "credit_days"]], on="supplier_id")
wavg_credit = (sup_val["received_value_ugx"] * sup_val["credit_days"]).sum() / sup_val["received_value_ugx"].sum()

print(f"Average stock on hand at cost : {UGX(inv_value)}")
print(f"Cost of goods sold            : {UGX(cogs)}")
print(f"Inventory days                : {inv_days:.0f} days")
print(f"Weighted supplier credit      : {wavg_credit:.0f} days")
print(f"Cash conversion cycle         : {inv_days - wavg_credit:+.0f} days")
if inv_days < wavg_credit:
    print("\n>> You sell the stock before you pay for it. That is a genuine strength --")
    print("   suppliers are financing your working capital. Protect it: the fastest")
    print("   way to lose it is letting slow lines creep up.")
F["working_capital"] = dict(inventory_value=float(inv_value), cogs=float(cogs),
                            inventory_days=float(inv_days),
                            supplier_credit_days=float(wavg_credit),
                            ccc=float(inv_days - wavg_credit))


# --------------------------------------------------------------------------
h("13. SUPPLIERS -- who is causing your empty shelves")
# --------------------------------------------------------------------------
sp = po.groupby(["supplier_id", "supplier_name"], as_index=False).agg(
    orders=("po_id", "size"), ordered=("qty_ordered", "sum"),
    received=("qty_received", "sum"), value=("received_value_ugx", "sum"),
    lead=("avg_lead_days", "mean"))
sp["fill_rate"] = sp["received"] / sp["ordered"] * 100
sp = sp.merge(suppliers[["supplier_id", "credit_days"]], on="supplier_id")

sup_lost = lost.merge(products[["sku", "supplier_name"]], on="sku") \
               .groupby("supplier_name", as_index=False)["lost_revenue_ugx"].sum()
sp = sp.merge(sup_lost, on="supplier_name", how="left").fillna({"lost_revenue_ugx": 0})
sp = sp.sort_values("lost_revenue_ugx", ascending=False)
print("Suppliers ranked by the sales their short-shipping cost you:")
print(sp.head(12).assign(fill_rate=lambda d: d["fill_rate"].round(1),
                         lead=lambda d: d["lead"].round(1),
                         value_M=lambda d: (d["value"]/1e6).round(0),
                         lost_M=lambda d: (d["lost_revenue_ugx"]/1e6).round(1))
      [["supplier_name", "orders", "fill_rate", "lead", "credit_days",
        "value_M", "lost_M"]].to_string(index=False))
print("\n>> Fill rate is the number to put in front of a supplier at review time.")
print("   'You delivered 82% of what I ordered and it cost me UGX Xm' is a")
print("   different conversation from 'your service has been poor'.")
F["suppliers"] = sp.head(12).to_dict("records")


# --------------------------------------------------------------------------
h("14. TILL-LEVEL CONTROL -- an exception worth a conversation")
# --------------------------------------------------------------------------
till = tx.groupby(["branch_code", "staff_id"], as_index=False).agg(
    tickets=("transaction_id", "size"), voids=("is_voided", "sum"),
    efris=("efris_fiscalised", "mean"), value=("gross_amount_ugx", "sum"))
till["void_pct"] = till["voids"] / till["tickets"] * 100
till["efris_pct"] = till["efris"] * 100
med_void = till["void_pct"].median()
med_efris = till["efris_pct"].median()
till["void_vs_median"] = till["void_pct"] / med_void
till = till.sort_values("void_pct", ascending=False)
print(f"Chain median void rate: {med_void:.2f}%   median EFRIS rate: {med_efris:.1f}%\n")
print(till.head(6).assign(void_pct=lambda d: d["void_pct"].round(2),
                          efris_pct=lambda d: d["efris_pct"].round(1),
                          x=lambda d: d["void_vs_median"].round(1))
      [["branch_code", "staff_id", "tickets", "void_pct", "x", "efris_pct"]].to_string(index=False))

o = till.iloc[0]
otx = tx[tx["staff_id"] == o["staff_id"]]
ev_void = otx[otx["hour"] >= 18]["is_voided"].mean() * 100
day_void = otx[otx["hour"] < 18]["is_voided"].mean() * 100
print(f"\n>> {o['staff_id']} at {o['branch_code']}: {o['void_pct']:.1f}% voids "
      f"({o['void_vs_median']:.0f}x the chain median),")
print(f"   and only {o['efris_pct']:.0f}% of tickets fiscalised against a {med_efris:.0f}% median.")
print(f"   Split by time of day: {day_void:.1f}% voids before 18:00, "
      f"{ev_void:.1f}% after 18:00.")
print(f"   Same branch carries {UGX(piv.loc[:, 'KAB'].sum())} of unexplained stock loss.")
print("\n   Three independent signals pointing at one till on one shift. We are NOT")
print("   alleging anything -- this is what an exception report is for. It tells")
print("   you exactly where to put a supervisor and a camera for two weeks.")
F["till_control"] = dict(
    median_void=float(med_void), median_efris=float(med_efris),
    outlier=dict(staff_id=str(o["staff_id"]), branch=str(o["branch_code"]),
                 void_pct=float(o["void_pct"]), multiple=float(o["void_vs_median"]),
                 efris_pct=float(o["efris_pct"]), evening_void=float(ev_void),
                 day_void=float(day_void)),
    top=till.head(6).to_dict("records"))


# --------------------------------------------------------------------------
h("15. PROMOTIONS -- did they actually pay?")
# --------------------------------------------------------------------------
res = []
for _, p in promos.iterrows():
    sk, s, e = p["sku"], p["start_date"], p["end_date"]
    dur = (e - s).days + 1
    d = ln[ln["sku"] == sk]
    if p["branch_scope"] != "ALL":
        d = d[d["branch_code"] == p["branch_scope"]]
    during = d[(d["date"] >= s) & (d["date"] <= e)]
    pre = d[(d["date"] >= s - pd.Timedelta(days=28)) & (d["date"] < s)]
    post = d[(d["date"] > e) & (d["date"] <= e + pd.Timedelta(days=28))]
    baseu = (pre["quantity"].sum() + post["quantity"].sum()) / 56
    basem = (pre["margin_ugx"].sum() + post["margin_ugx"].sum()) / 56
    du, dm = during["quantity"].sum() / dur, during["margin_ugx"].sum() / dur
    # basket lift: value of baskets containing the item, promo vs baseline
    ids_d = set(during["transaction_id"]);  ids_b = set(pd.concat([pre, post])["transaction_id"])
    bd = sales_tx.loc[sales_tx["transaction_id"].isin(ids_d), "gross_amount_ugx"].mean()
    bb = sales_tx.loc[sales_tx["transaction_id"].isin(ids_b), "gross_amount_ugx"].mean()
    res.append(dict(promo=p["promo_name"], product=p["product_name"],
                    discount=p["discount_pct"] * 100,
                    funded=p["supplier_funded_pct"] * 100, days=dur,
                    units_base=baseu, units_promo=du,
                    unit_lift=(du / baseu - 1) * 100 if baseu else np.nan,
                    margin_base_day=basem, margin_promo_day=dm,
                    incr_margin=(dm - basem) * dur,
                    basket_base=bb, basket_promo=bd,
                    basket_lift=(bd / bb - 1) * 100 if bb else np.nan))
pr = pd.DataFrame(res).sort_values("incr_margin")
print(pr.assign(discount=lambda d: d["discount"].round(0),
                funded=lambda d: d["funded"].round(0),
                unit_lift=lambda d: d["unit_lift"].round(0),
                incr_margin=lambda d: d["incr_margin"].round(0),
                basket_lift=lambda d: d["basket_lift"].round(1))
      [["promo", "discount", "funded", "days", "unit_lift", "incr_margin",
        "basket_lift"]].to_string(index=False))
won = pr[pr["incr_margin"] > 0]["incr_margin"].sum()
lostm = pr[pr["incr_margin"] < 0]["incr_margin"].sum()
print(f"\nPromos that added margin : {UGX(won)}")
print(f"Promos that destroyed it : {UGX(lostm)}")
print(f"Net                      : {UGX(won+lostm)}")

selfp = pr[pr["funded"] <= 25]
fundp = pr[pr["funded"] >= 50]
print(f"\nSelf-funded promos ({len(selfp)}): {UGX(selfp['incr_margin'].sum())}")
print(f"Supplier-funded ({len(fundp)}) : {UGX(fundp['incr_margin'].sum())}")
print("\n>> This is the whole story. 'unit_lift' says the promo moved volume;")
print("   'incr_margin' says whether moving it was worth the discount. Nearly")
print("   every promotion the supplier paid for made money. Nearly every one you")
print("   funded yourself lost money -- you discounted stock you would have sold")
print("   anyway. The rule that falls out: no promotion without a written")
print("   supplier funding agreement behind it.")
F["promotions"] = pr.to_dict("records")


# --------------------------------------------------------------------------
h("16. CUSTOMERS -- who is actually worth keeping")
# --------------------------------------------------------------------------
loy = sales_tx[sales_tx["customer_id"].notna() & (sales_tx["customer_id"] != "")]
cap = len(loy) / len(sales_tx) * 100
cs = loy.groupby("customer_id", as_index=False).agg(
    spend=("gross_amount_ugx", "sum"), visits=("transaction_id", "size"),
    last=("date", "max"), first=("date", "min"))
cs = cs.sort_values("spend", ascending=False)
cs["cum"] = cs["spend"].cumsum() / cs["spend"].sum() * 100
top10 = int(len(cs) * 0.10)
print(f"Loyalty capture: {cap:.0f}% of baskets are identified")
print(f"Identified customers: {len(cs):,}")
print(f"Top 10% of them ({top10:,} people) = {PCT(cs['cum'].iloc[top10-1])} of identified spend")
print(f"Top 20%                            = {PCT(cs['cum'].iloc[int(len(cs)*0.2)-1])}")

asof = sales_tx["date"].max()
cs["days_since"] = (asof - cs["last"]).dt.days
lapsed = cs[(cs["days_since"] > 90) & (cs["visits"] >= 5)]
lapsed_top = lapsed.nlargest(top10, "spend")
print(f"\nCustomers with 5+ visits who have not returned in 90 days: {len(lapsed):,}")
print(f"  their combined historic spend: {UGX(lapsed['spend'].sum())}")
print(f"  ({PCT(lapsed['spend'].sum()/cs['spend'].sum()*100)} of identified spend has gone quiet)")
print("\n>> This is the cheapest growth available to you. Winning back a customer")
print("   who already knows the store costs a fraction of finding a new one --")
print("   and you have their phone number.")
F["customers"] = dict(
    capture_pct=float(cap), identified=int(len(cs)),
    top10_share=float(cs["cum"].iloc[top10-1]),
    top20_share=float(cs["cum"].iloc[int(len(cs)*0.2)-1]),
    lapsed_count=int(len(lapsed)), lapsed_spend=float(lapsed["spend"].sum()),
    lapsed_share=float(lapsed["spend"].sum()/cs["spend"].sum()*100))


# --------------------------------------------------------------------------
h("17. THE PRIZE -- what these findings are worth")
# --------------------------------------------------------------------------
prize = [
    ("Recover half the sales lost to stockouts on top lines",
     lost_mgn * 0.5, "Fix reorder points for the payday window"),
    ("Bring Kabalagala's unexplained loss down to the chain average",
     float(piv["KAB"].sum() - piv[["NAK", "NTI"]].mean(axis=1).sum()) * 0.7,
     "Supervision, till exception reports, stock counts"),
    ("Cut fresh/bakery spoilage by a quarter",
     tot_waste * 0.25, "Order to demand, mark down earlier, fix the chillers"),
    ("Stop the next commodity price lag (sugar was the last one)",
     lost_sugar * 0.8, "Weekly cost-vs-price review on the top 30 lines"),
    ("Kill or shrink the slowest 5% of the range",
     tail["stock_value"].sum() * 0.5, "Frees working capital, not P&L"),
    ("Reverse the loss-making promotions",
     abs(lostm), "Same volume, better terms, or no promo"),
]
tot_prize = sum(v for _, v, _ in prize[:4]) + abs(lostm)
for name, val, how in prize:
    print(f"  {UGX(val):>18}   {name}")
    print(f"  {'':>18}   -> {how}")
print(f"\n  {UGX(tot_prize):>18}   TOTAL annual margin opportunity (excl. capital release)")
print(f"  {'':>18}   = {PCT(tot_prize/gross_margin*100)} of current gross margin")
print(f"  {UGX(tail['stock_value'].sum()*0.5):>18}   one-off working capital release")
F["prize"] = dict(items=[{"name": n, "value": float(v), "how": h_} for n, v, h_ in prize],
                  total=float(tot_prize),
                  pct_of_margin=float(tot_prize / gross_margin * 100))


# --------------------------------------------------------------------------
with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as f:
    json.dump(F, f, indent=1, default=str)
print(f"\n\nWrote {os.path.join(OUT, 'findings.json')}")
