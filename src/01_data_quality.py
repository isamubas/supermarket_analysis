"""Data quality audit: completeness, uniqueness, referential consistency,
and verification of the derived columns."""
import pandas as pd
import numpy as np
from pathlib import Path

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)

DATA = Path(__file__).resolve().parent.parent / "data" / "supermarket.xls"
df = pd.read_excel(DATA)

print("SHAPE:", df.shape)

print("\n--- MISSING VALUES ---")
missing = df.isna().sum()
print(missing[missing > 0] if missing.sum() else "None")

print("\n--- DUPLICATES ---")
print("full-row duplicates:", df.duplicated().sum())
print("invoiceID unique:", df.invoiceID.nunique(), "of", len(df))

print("\n--- CATEGORICALS ---")
for c in ["branch", "city", "cust_type", "gender", "type", "payment"]:
    print(f"{c} ({df[c].nunique()}): {sorted(df[c].unique().tolist())}")

print("\n--- BRANCH x CITY MAPPING (should be 1:1) ---")
print(pd.crosstab(df.branch, df.city))

print("\n--- DATE COVERAGE ---")
print(df.date.min().date(), "->", df.date.max().date(), "| distinct days:", df.date.nunique())

print("\n--- NUMERIC SUMMARY ---")
print(df[["unit_price", "quantity", "cost", "gross income", "rating"]].describe().round(3))

print("\n--- DERIVED COLUMN CHECKS ---")
calc_cost = (df.unit_price * df.quantity).round(2)
print("cost == unit_price * quantity :", bool(np.isclose(df.cost, calc_cost, atol=0.011).all()),
      "| max abs diff:", float((df.cost - calc_cost).abs().max()))

ratio = df["gross income"] / df.cost
print(f"gross income / cost -> min {ratio.min():.8f}  max {ratio.max():.8f}  "
      f"distinct values: {ratio.round(8).nunique()}")
if ratio.round(8).nunique() == 1:
    print("  >> gross income is a CONSTANT 5% of cost. It carries no independent")
    print("     information, so margin cannot be compared across any segment.")

print("\n--- INVALID VALUES ---")
for c in ["unit_price", "quantity", "cost", "gross income", "rating"]:
    print(f"{c}: values <= 0 -> {(df[c] <= 0).sum()}")
