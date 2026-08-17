"""
Load, clean and join the four annexes into one analysis frame.

The four raw files carry a sales ledger, a catalogue, a wholesale price series
and a loss rate, and none of them can answer a margin question alone. This
module is the only place they get joined, so every downstream number rests on
one set of decisions, stated here:

  * A return is stored as a negative quantity on a normal row. Returns are kept
    and netted off revenue rather than dropped, so revenue means money that
    stayed in the till. `is_return` is carried through for reporting.

  * Cost is the wholesale price in force for that item ON THE DATE OF SALE, not
    an average. Where a sold item-day has no quoted wholesale price, the last
    quote for that item is carried forward (then back-filled at the series
    start). `cost_imputed` flags those rows so the margin work can be re-run
    without them.

  * Loss rate is applied as a procurement multiplier, not a discount on margin.
    At a loss rate L, selling 1 kg means buying 1/(1-L) kg, so the true cost of
    a sold kilo is wholesale / (1 - L). Reporting margin against the raw
    wholesale price overstates it on exactly the perishable items where the
    error matters most. Both figures are computed so the gap can be shown.

  * Category names arrive with a non-breaking space (U+00A0) in
    "Flower/Leaf Vegetables". It is normalised, otherwise that category splits
    in two under any groupby.

Run directly to write data/analysis_frame.parquet and print a load summary.
"""

from __future__ import annotations

import os
import zipfile

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
CACHE = os.path.join(DATA, "analysis_frame.parquet")

# Trading window covered by the sales ledger.
START, END = "2020-07-01", "2023-06-30"


def _read_csv(name: str) -> pd.DataFrame:
    """Read an annex whether it is shipped raw or zipped."""
    raw = os.path.join(DATA, f"{name}.csv")
    zipped = os.path.join(DATA, f"{name}.csv.zip")
    if os.path.exists(raw):
        return pd.read_csv(raw)
    with zipfile.ZipFile(zipped) as z:
        with z.open(f"{name}.csv") as fh:
            return pd.read_csv(fh)


def _clean_text(s: pd.Series) -> pd.Series:
    """Strip the non-breaking spaces and stray padding the source ships with."""
    return s.str.replace(" ", " ", regex=False).str.strip()


def load_catalogue() -> pd.DataFrame:
    """Annex 1 + annex 4: one row per item, with category and loss rate."""
    cat = _read_csv("annex1").rename(
        columns={
            "Item Code": "item_code",
            "Item Name": "item_name",
            "Category Code": "category_code",
            "Category Name": "category",
        }
    )
    cat["item_name"] = _clean_text(cat["item_name"])
    cat["category"] = _clean_text(cat["category"])

    loss = _read_csv("annex4").rename(
        columns={"Item Code": "item_code", "Loss Rate (%)": "loss_rate_pct"}
    )[["item_code", "loss_rate_pct"]]

    cat = cat.merge(loss, on="item_code", how="left")
    cat["loss_rate"] = cat["loss_rate_pct"] / 100.0
    return cat


def load_wholesale() -> pd.DataFrame:
    """Annex 3: daily wholesale price per item."""
    wp = _read_csv("annex3").rename(
        columns={
            "Date": "date",
            "Item Code": "item_code",
            "Wholesale Price (RMB/kg)": "wholesale_price",
        }
    )
    wp["date"] = pd.to_datetime(wp["date"])
    return wp.sort_values(["item_code", "date"]).reset_index(drop=True)


def load_sales() -> pd.DataFrame:
    """Annex 2: the transaction ledger."""
    tx = _read_csv("annex2").rename(
        columns={
            "Date": "date",
            "Time": "time",
            "Item Code": "item_code",
            "Quantity Sold (kilo)": "qty_kg",
            "Unit Selling Price (RMB/kg)": "unit_price",
            "Sale or Return": "sale_or_return",
            "Discount (Yes/No)": "discounted",
        }
    )
    tx["date"] = pd.to_datetime(tx["date"])
    tx["is_return"] = tx["sale_or_return"].str.strip().str.lower().eq("return")
    tx["is_discounted"] = tx["discounted"].str.strip().str.lower().eq("yes")

    # Time is HH:MM:SS.mmm. Parse to an hour bucket and a proper timestamp.
    hh = tx["time"].str.slice(0, 2).astype(int)
    mm = tx["time"].str.slice(3, 5).astype(int)
    tx["hour"] = hh
    tx["minute_of_day"] = hh * 60 + mm

    return tx.drop(columns=["sale_or_return", "discounted"])


def _daily_cost_panel(wp: pd.DataFrame, items: np.ndarray) -> pd.DataFrame:
    """
    Expand the wholesale quotes to a dense item x calendar-day panel, carrying
    the last quote forward. Vegetables are not re-quoted every single day, so a
    plain merge leaves holes on exactly the days trading happened.
    """
    calendar = pd.date_range(START, END, name="date")
    panel = (
        wp.set_index(["item_code", "date"])["wholesale_price"]
        .unstack("item_code")
        .reindex(calendar)
    )
    # Items that never appear in annex 3 still need a column.
    panel = panel.reindex(columns=sorted(set(panel.columns) | set(items)))
    quoted = panel.notna()

    panel = panel.ffill().bfill()

    dense = panel.stack(future_stack=True).rename("wholesale_price").reset_index()
    dense.columns = ["date", "item_code", "wholesale_price"]
    flag = quoted.stack(future_stack=True).rename("quoted").reset_index()
    flag.columns = ["date", "item_code", "quoted"]
    dense = dense.merge(flag, on=["date", "item_code"], how="left")
    dense["cost_imputed"] = ~dense["quoted"].fillna(False)
    return dense.drop(columns=["quoted"])


def build_frame() -> pd.DataFrame:
    """Join all four annexes into the single frame every analysis runs on."""
    tx = load_sales()
    cat = load_catalogue()
    wp = load_wholesale()

    cost = _daily_cost_panel(wp, tx["item_code"].unique())

    df = tx.merge(cat, on="item_code", how="left")
    df = df.merge(cost, on=["date", "item_code"], how="left")

    # --- money ------------------------------------------------------------
    df["revenue"] = df["qty_kg"] * df["unit_price"]

    # Cost as quoted, and cost once wastage is paid for.
    df["cost_raw"] = df["qty_kg"] * df["wholesale_price"]
    df["effective_unit_cost"] = df["wholesale_price"] / (1.0 - df["loss_rate"])
    df["cost_true"] = df["qty_kg"] * df["effective_unit_cost"]

    df["profit_raw"] = df["revenue"] - df["cost_raw"]
    df["profit_true"] = df["revenue"] - df["cost_true"]
    df["markup"] = df["unit_price"] / df["wholesale_price"]

    # --- calendar ---------------------------------------------------------
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["year_month"] = df["date"].dt.to_period("M").astype(str)
    df["dow"] = df["date"].dt.dayofweek          # 0 = Monday
    df["dow_name"] = df["date"].dt.day_name()
    df["is_weekend"] = df["dow"] >= 5
    df["day_of_month"] = df["date"].dt.day
    df["season"] = df["month"].map(
        {12: "Winter", 1: "Winter", 2: "Winter",
         3: "Spring", 4: "Spring", 5: "Spring",
         6: "Summer", 7: "Summer", 8: "Summer",
         9: "Autumn", 10: "Autumn", 11: "Autumn"}
    )
    return df


def load(rebuild: bool = False) -> pd.DataFrame:
    """Return the analysis frame, using the parquet cache when it exists."""
    if not rebuild and os.path.exists(CACHE):
        return pd.read_parquet(CACHE)
    df = build_frame()
    try:
        df.to_parquet(CACHE, index=False)
    except Exception:
        pass  # pyarrow absent; recompute each time rather than fail
    return df


def summarise(df: pd.DataFrame) -> str:
    lines = [
        f"rows                 {len(df):,}",
        f"date range           {df.date.min():%Y-%m-%d} to {df.date.max():%Y-%m-%d}",
        f"trading days         {df.date.nunique():,}",
        f"items sold           {df.item_code.nunique()}",
        f"categories           {df.category.nunique()}",
        f"returns              {int(df.is_return.sum()):,}",
        f"discounted lines     {int(df.is_discounted.sum()):,}",
        f"cost imputed (ffill) {df.cost_imputed.mean():.1%} of lines",
        f"net revenue          RMB {df.revenue.sum():,.0f}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    frame = build_frame()
    try:
        frame.to_parquet(CACHE, index=False)
        print(f"wrote {CACHE}")
    except Exception as exc:
        print(f"could not cache parquet ({exc}); frame built in memory only")
    print(summarise(frame))
