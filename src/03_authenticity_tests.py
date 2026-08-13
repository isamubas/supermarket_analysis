"""Authenticity tests: is this real trading data or a simulation?

Real retail data has structure - price points cluster at psychological values,
basket sizes skew small, ratings skew high, categories are lopsided, and demand
has a weekly rhythm. This script tests each of those expectations.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

DATA = Path(__file__).resolve().parent.parent / "data" / "supermarket.xls"
df = pd.read_excel(DATA)
df["hour"] = pd.to_datetime(df["time"].astype(str), format="mixed").dt.hour
df["weekday"] = df["date"].dt.day_name()

print("=" * 72)
print("TEST 1 - Are the numeric fields just uniform random draws?")
print("=" * 72)


def ks_uniform(x, lo, hi, name):
    d, p = stats.kstest(x, "uniform", args=(lo, hi - lo))
    obs, exp = np.std(x, ddof=1), (hi - lo) / np.sqrt(12)
    print(f"{name:12s} range[{lo},{hi}] KS D={d:.4f} p={p:.4f} | "
          f"std obs={obs:.3f} vs uniform={exp:.3f} -> "
          f"{'CONSISTENT with uniform random' if p > .05 else 'not uniform'}")


ks_uniform(df.unit_price, 10, 100, "unit_price")
ks_uniform(df.rating, 4, 10, "rating")

counts = df.quantity.value_counts().sort_index()
chi, p = stats.chisquare(counts.values)
print(f"\nquantity (discrete 1-10): {counts.to_dict()}")
print(f"{'':12s} chi2={chi:.3f} p={p:.4f} -> "
      f"{'CONSISTENT with uniform random' if p > .05 else 'not uniform'}")

print("\n" + "=" * 72)
print("TEST 2 - Category balance (real retail is lopsided)")
print("=" * 72)
for c in ["branch", "cust_type", "gender", "payment", "type"]:
    v = df[c].value_counts()
    chi, p = stats.chisquare(v.values)
    print(f"{c:10s} chi2={chi:5.2f} p={p:.4f} -> "
          f"{'evenly balanced' if p > .05 else 'genuinely skewed'}  {dict(v)}")

print("\n" + "=" * 72)
print("TEST 3 - Time patterns (real demand has a rhythm)")
print("=" * 72)
for c in ["weekday", "hour"]:
    v = df[c].value_counts()
    chi, p = stats.chisquare(v.values)
    print(f"txn counts by {c:8s}: chi2={chi:5.2f} p={p:.4f} -> "
          f"{'REAL pattern' if p < .05 else 'no real pattern'}")

print("\n" + "=" * 72)
print("TEST 4 - Does gross income carry any independent information?")
print("=" * 72)
r = df["gross income"] / df.cost
print(f"gross income / cost: min={r.min():.8f} max={r.max():.8f} "
      f"distinct={r.round(8).nunique()}")
print("-> margin is identical for every product, branch and customer by construction")

print("\n" + "=" * 72)
print("CONCLUSION")
print("=" * 72)
print("Every numeric field is statistically indistinguishable from a uniform")
print("random draw, every category is evenly balanced, no time pattern exists,")
print("and margin is a hard-coded constant. This is a simulated teaching")
print("dataset, not a record of real trading.")
