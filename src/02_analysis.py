"""Descriptive analysis by segment, with a significance test attached to every
comparison so that noise is never reported as a finding."""
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

DATA = Path(__file__).resolve().parent.parent / "data" / "supermarket.xls"
df = pd.read_excel(DATA)

df["revenue"] = df["cost"]                       # unit_price * quantity (net sales)
df["billed"] = df["cost"] + df["gross income"]   # what the customer pays (1.05x)
df["hour"] = pd.to_datetime(df["time"].astype(str), format="mixed").dt.hour
df["weekday"] = df["date"].dt.day_name()
df["month"] = df["date"].dt.strftime("%Y-%m")


def block(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def verdict(p):
    return "SIGNIFICANT" if p < 0.05 else "NOT significant - this is noise"


print("TOTAL NET SALES: %.2f | TOTAL BILLED: %.2f | GROSS INCOME: %.2f"
      % (df.revenue.sum(), df.billed.sum(), df["gross income"].sum()))
print("AVG TRANSACTION: %.2f | AVG BASKET UNITS: %.2f | AVG RATING: %.2f"
      % (df.revenue.mean(), df.quantity.mean(), df.rating.mean()))

block("BRANCH / CITY")
g = df.groupby(["branch", "city"]).agg(
    txns=("invoiceID", "count"), revenue=("revenue", "sum"),
    avg_txn=("revenue", "mean"), units=("quantity", "sum"),
    rating=("rating", "mean")).round(2)
g["rev_share_%"] = (g.revenue / g.revenue.sum() * 100).round(1)
print(g.sort_values("revenue", ascending=False))
f, p = stats.f_oneway(*[x.revenue.values for _, x in df.groupby("branch")])
print(f"\nANOVA revenue ~ branch: F={f:.3f} p={p:.4f} -> {verdict(p)}")
f, p = stats.f_oneway(*[x.rating.values for _, x in df.groupby("branch")])
print(f"ANOVA rating  ~ branch: F={f:.3f} p={p:.4f} -> {verdict(p)}")

block("PRODUCT LINE")
g = df.groupby("type").agg(
    txns=("invoiceID", "count"), revenue=("revenue", "sum"),
    avg_txn=("revenue", "mean"), units=("quantity", "sum"),
    rating=("rating", "mean")).round(2)
g["rev_share_%"] = (g.revenue / g.revenue.sum() * 100).round(1)
print(g.sort_values("revenue", ascending=False))
f, p = stats.f_oneway(*[x.revenue.values for _, x in df.groupby("type")])
print(f"\nANOVA revenue ~ product line: F={f:.3f} p={p:.4f} -> {verdict(p)}")

block("PRODUCT LINE x BRANCH (revenue)")
print(df.pivot_table(index="type", columns="branch", values="revenue", aggfunc="sum").round(0))

block("CUSTOMER TYPE / GENDER / PAYMENT")
for c in ["cust_type", "gender", "payment"]:
    g = df.groupby(c).agg(
        txns=("invoiceID", "count"), revenue=("revenue", "sum"),
        avg_txn=("revenue", "mean"), rating=("rating", "mean")).round(2)
    g["rev_share_%"] = (g.revenue / g.revenue.sum() * 100).round(1)
    print(f"\n[{c}]")
    print(g.sort_values("revenue", ascending=False))

a = df[df.cust_type == "Member"].revenue
b = df[df.cust_type == "Normal"].revenue
t, p = stats.ttest_ind(a, b, equal_var=False)
print(f"\nMember vs Normal avg txn: {a.mean():.2f} vs {b.mean():.2f} "
      f"| t={t:.3f} p={p:.4f} -> {verdict(p)}")

block("TIME PATTERNS")
print("[by hour]")
print(df.groupby("hour").agg(txns=("invoiceID", "count"), revenue=("revenue", "sum")).round(0))
order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
print("\n[by weekday]")
print(df.groupby("weekday").agg(txns=("invoiceID", "count"),
                                revenue=("revenue", "sum")).reindex(order).round(0))
print("\n[by month, normalised for month length]")
days = {"2019-01": 31, "2019-02": 28, "2019-03": 30}
m = df.groupby("month").agg(revenue=("revenue", "sum"), txns=("invoiceID", "count"))
m["days"] = m.index.map(days)
m["rev_per_day"] = (m.revenue / m.days).round(0)
m["txn_per_day"] = (m.txns / m.days).round(2)
print(m)

block("RATINGS")
print(df.rating.describe().round(2))
r, p = stats.pearsonr(df.rating, df.revenue)
print(f"\ncorr(rating, revenue):  r={r:.4f} p={p:.4f} -> {verdict(p)}")
r, p = stats.pearsonr(df.rating, df.quantity)
print(f"corr(rating, quantity): r={r:.4f} p={p:.4f} -> {verdict(p)}")
print("\nrating by product line:")
print(df.groupby("type").rating.agg(["mean", "std", "count"]).round(2)
      .sort_values("mean", ascending=False))
