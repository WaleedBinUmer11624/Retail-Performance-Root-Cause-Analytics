"""Plant realistic data-quality problems in the clean data and log every one.

Principle: each planted issue is recorded in data/raw/_planted_issues_log.csv
with the table, the row key, the column, the original and planted values and
the data-quality check that should catch it (used to score Phase 4).
Row-level issues are drawn from disjoint rows so one row carries one planted
problem, which keeps the evaluation unambiguous.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CATEGORY_VARIANTS = {
    "Home & Kitchen": ["Home and Kitchen", "HOME & KITCHEN", "Home & Kitchen ", "Home&Kitchen"],
    "Electronics & Tech": ["Electronics", "ELECTRONICS & TECH", "Electronic & Tech", "Electronics & Tech "],
    "Health & Beauty": ["Health and Beauty", "Health & Beauty ", "HEALTH & BEAUTY", "Health/Beauty"],
    "Toys & Games": ["Toys", "Toys and Games", "TOYS & GAMES", "Toys & Games "],
    "Garden & Outdoor": ["Garden", "Garden & Outdoors", "GARDEN & OUTDOOR", "Garden and Outdoor"],
    "Stationery & Crafts": ["Stationary & Crafts", "Stationery", "STATIONERY & CRAFTS", "Stationery and Crafts"],
    "Seasonal & Gifts": ["Seasonal", "Seasonal and Gifts", "SEASONAL & GIFTS", "Gifts & Seasonal"],
}


class PlantedIssueLog:
    """Row-level record of every planted data quality issue, used only to score detection."""
    COLUMNS = ["issue_id", "table_name", "file_name", "issue_type", "row_key", "column_name",
               "original_value", "planted_value", "expected_check", "notes"]

    def __init__(self):
        self._parts: list[pd.DataFrame] = []

    def add(self, table, file, issue_type, keys, column, original, planted, check, notes=""):
        """Log one issue type planted on the given row keys."""
        keys = pd.Series(keys).astype(str).to_numpy()
        n = len(keys)
        if n == 0:
            return
        self._parts.append(pd.DataFrame({
            "table_name": table, "file_name": file, "issue_type": issue_type, "row_key": keys,
            "column_name": column,
            "original_value": pd.Series(original if np.ndim(original) else [original] * n).astype(str).to_numpy(),
            "planted_value": pd.Series(planted if np.ndim(planted) else [planted] * n).astype(str).to_numpy(),
            "expected_check": check, "notes": notes,
        }))

    def to_frame(self) -> pd.DataFrame:
        """All logged issues with sequential DQ ids."""
        df = pd.concat(self._parts, ignore_index=True) if self._parts else pd.DataFrame(columns=self.COLUMNS[1:])
        df.insert(0, "issue_id", [f"DQ{i:06d}" for i in range(1, len(df) + 1)])
        return df[self.COLUMNS]


class RowPicker:
    """Draws disjoint row positions so each row carries at most one planted issue."""

    def __init__(self, n, rng, excluded=None):
        self.free = np.ones(n, dtype=bool)
        if excluded is not None:
            self.free[excluded] = False
        self.rng = rng

    def pick(self, rate=None, count=None, within=None):
        """Draw free rows by rate or count, optionally within a mask, and mark them used."""
        pool = np.flatnonzero(self.free if within is None else (self.free & within))
        k = count if count is not None else max(1, int(round(rate * len(self.free))))
        k = min(k, len(pool))
        idx = np.sort(self.rng.choice(pool, size=k, replace=False)) if k else np.array([], dtype=int)
        self.free[idx] = False
        return idx


def _sales_key(df, idx):
    return (df["transaction_id"].iloc[idx] + "|" + df["line_number"].iloc[idx].astype(str)).to_numpy()


def corrupt_sales(sales, cfg, stores, products, log, rng, file="fact_sales.csv"):
    """Plant the configured sales issues (price, sign, date, category, duplicate and others)."""
    q = cfg["data_quality_issues"]["fact_sales"]
    df = sales.copy()
    df["unit_price"] = df["unit_price"].astype(float)
    df["discount"] = df["discount"].astype(float)
    df["store_id"] = df["store_id"].astype(object)
    df["product_id"] = df["product_id"].astype(object)
    pick = RowPicker(len(df), rng)
    T = "fact_sales"

    # legacy till export format (a whole store for a period) - systematic, not random
    m = (df["store_id"] == q["legacy_date_format_store"]) & (df["transaction_date"] <= q["legacy_date_format_until"])
    idx = np.flatnonzero(m.to_numpy())
    pick.free[idx] = False
    orig = df.loc[m, "transaction_date"].to_numpy()
    df.loc[m, "transaction_date"] = pd.to_datetime(df.loc[m, "transaction_date"]).dt.strftime("%d/%m/%Y")
    log.add(T, file, "inconsistent_date_format", _sales_key(df, idx), "transaction_date", orig,
            df.loc[m, "transaction_date"].to_numpy(), "date_format_validity", "legacy till exported DD/MM/YYYY")

    def one(issue, rate, column, fn, check, notes=""):
        i = pick.pick(rate=rate)
        orig = df[column].iloc[i].to_numpy().copy()
        fn(i)
        log.add(T, file, issue, _sales_key(df, i), column, orig, df[column].iloc[i].to_numpy(), check, notes)
        return i

    col = df.columns.get_loc

    def setter(column, value_fn):
        def _set(i):
            df.iloc[i, col(column)] = value_fn(i)
        return _set

    def recompute(i):
        """Till recalculates revenue and margin from the (wrong) price or quantity."""
        g = df["quantity"].iloc[i].to_numpy() * df["unit_price"].iloc[i].to_numpy()
        df.iloc[i, col("revenue")] = np.round(g - df["discount"].iloc[i].to_numpy(), 2)
        df.iloc[i, col("margin")] = np.round(df["revenue"].iloc[i].to_numpy() - df["cost"].iloc[i].to_numpy(), 2)

    one("missing_product_id", q["missing_product_id_rate"], "product_id",
        setter("product_id", lambda i: None), "null_check_product_id")
    one("missing_store_id", q["missing_store_id_rate"], "store_id",
        setter("store_id", lambda i: None), "null_check_store_id", "store recoverable from transaction_id prefix")
    one("invalid_store_id", q["invalid_store_id_rate"], "store_id",
        setter("store_id", lambda i: "S21"), "referential_integrity_store")
    bad_p = [f"P{v:05d}" for v in range(90001, 90050)]
    one("invalid_product_id", q["invalid_product_id_rate"], "product_id",
        setter("product_id", lambda i: rng.choice(bad_p, len(i))), "referential_integrity_product")
    one("null_unit_price", q["null_unit_price_rate"], "unit_price",
        setter("unit_price", lambda i: np.nan), "null_check_unit_price",
        "price recoverable as (revenue + discount) / quantity")
    one("null_discount", q["null_discount_rate"], "discount",
        setter("discount", lambda i: np.nan), "null_check_discount",
        "discount recoverable as quantity * unit_price - revenue")

    def x100(i):
        df.iloc[i, col("unit_price")] = np.round(df["unit_price"].iloc[i].to_numpy() * 100, 2)
        recompute(i)
    one("price_x100", q["price_x100_rate"], "unit_price", x100, "price_anomaly", "cents keyed as euros")

    def zero(i):
        df.iloc[i, col("unit_price")] = 0.0
        df.iloc[i, col("discount")] = 0.0
        recompute(i)
    one("zero_price", q["zero_price_rate"], "unit_price", zero, "price_anomaly")

    def neg_price(i):
        df.iloc[i, col("unit_price")] = -df["unit_price"].iloc[i].to_numpy()
        df.iloc[i, col("discount")] = -df["discount"].iloc[i].to_numpy()
        recompute(i)
    one("negative_price", q["negative_price_rate"], "unit_price", neg_price, "negative_value_price")

    def neg_qty(i):
        for c in ("quantity", "discount", "revenue", "cost", "margin"):
            df.iloc[i, col(c)] = -df[c].iloc[i].to_numpy()
    one("negative_quantity", q["negative_quantity_rate"], "quantity", neg_qty, "negative_value_quantity",
        "return keyed at till as a negative sale")

    bad_dates = np.array(["2025-13-07", "31/02/2025", "", "00-00-0000", "2024-06-31", "NULL"])
    one("malformed_date", q["malformed_date_rate"], "transaction_date",
        setter("transaction_date", lambda i: rng.choice(bad_dates, len(i))), "date_validity")

    def out_of_range(i):
        d = pd.to_datetime(df["transaction_date"].iloc[i])
        choice = rng.random(len(i)) < 0.5
        new = np.where(choice, "1900-01-01", (d + pd.DateOffset(years=27)).dt.strftime("%Y-%m-%d"))
        df.iloc[i, col("transaction_date")] = new
    one("out_of_range_date", q["out_of_range_date_rate"], "transaction_date", out_of_range, "date_range")

    def extreme(i):
        qv = rng.choice([96, 120, 144, 250], len(i))
        u = df["unit_price"].iloc[i].to_numpy()
        df.iloc[i, col("quantity")] = qv
        df.iloc[i, col("discount")] = 0.0
        df.iloc[i, col("revenue")] = np.round(qv * u, 2)
        df.iloc[i, col("cost")] = np.round(qv * df["unit_cost"].iloc[i].to_numpy(), 2)
        df.iloc[i, col("margin")] = np.round(df["revenue"].iloc[i].to_numpy() - df["cost"].iloc[i].to_numpy(), 2)
    one("extreme_quantity", q["extreme_quantity_rate"], "quantity", extreme, "quantity_outlier")

    def rev_mismatch(i):
        off = np.round(rng.uniform(0.5, 25, len(i)) * rng.choice([-1, 1], len(i)), 2)
        df.iloc[i, col("revenue")] = np.round(df["revenue"].iloc[i].to_numpy() + off, 2)
    one("revenue_mismatch", q["revenue_mismatch_rate"], "revenue", rev_mismatch, "revenue_calculation")

    bad_promo = [f"PR9{v:04d}" for v in range(1, 50)]
    one("orphan_promotion_id", q["orphan_promotion_id_rate"], "promotion_id",
        setter("promotion_id", lambda i: rng.choice(bad_promo, len(i))), "referential_integrity_promotion")

    def cat_variant(i):
        cats = df["category"].iloc[i].to_numpy()
        df.iloc[i, col("category")] = [rng.choice(CATEGORY_VARIANTS[c]) for c in cats]
    one("inconsistent_category_label", q["inconsistent_category_rate"], "category", cat_variant, "category_domain")

    # whole receipts re-sent by the till (duplicate transactions)
    txn_ids = df["transaction_id"].unique()
    k = max(1, int(round(q["duplicate_transaction_rate"] * len(txn_ids))))
    dup_ids = rng.choice(txn_ids, size=k, replace=False)
    dups = df[df["transaction_id"].isin(dup_ids)].copy()
    dups["extract_timestamp"] = (pd.to_datetime(dups["extract_timestamp"]) + pd.Timedelta(hours=3)).dt.strftime("%Y-%m-%d %H:%M:%S")
    log.add(T, file, "duplicate_transaction", (dups["transaction_id"] + "|" + dups["line_number"].astype(str)).to_numpy(),
            "*", "", "extra copy", "duplicate_check_sales", "receipt re-sent in a later extract run")
    df = pd.concat([df, dups], ignore_index=True)
    return df


def corrupt_dim_product(prod, cfg, log, rng, file="dim_product.csv"):
    """Plant product master issues."""
    q = cfg["data_quality_issues"]["dim_product"]
    df = prod.copy()
    df["supplier_id"] = df["supplier_id"].astype(object)
    df["supplier_name"] = df["supplier_name"].astype(object)
    pick = RowPicker(len(df), rng)
    T = "dim_product"
    i = pick.pick(count=q["duplicate_product_records"])
    dup = df.iloc[i].copy()
    dup["product_name"] = [n.upper() if j % 2 else n + " " for j, n in enumerate(dup["product_name"])]
    dup["list_price"] = dup["list_price_2024"]  # stale price on the duplicate record
    log.add(T, file, "duplicate_product_record", dup["product_id"], "product_id", "", "second record",
            "duplicate_check_product", "second master record with name variant and stale price")
    i = pick.pick(count=q["inconsistent_category_records"])
    orig = df["category"].iloc[i].to_numpy()
    new = [rng.choice(CATEGORY_VARIANTS[c]) for c in orig]
    df.iloc[i, df.columns.get_loc("category")] = new
    log.add(T, file, "inconsistent_category_label", df["product_id"].iloc[i], "category", orig, new, "category_domain")
    i = pick.pick(count=q["missing_supplier_records"])
    log.add(T, file, "missing_supplier", df["product_id"].iloc[i], "supplier_id", df["supplier_id"].iloc[i].to_numpy(), "",
            "null_check_supplier")
    df.iloc[i, df.columns.get_loc("supplier_id")] = None
    df.iloc[i, df.columns.get_loc("supplier_name")] = None
    i = pick.pick(count=q["negative_cost_records"])
    orig = df["unit_cost"].iloc[i].to_numpy()
    df.iloc[i, df.columns.get_loc("unit_cost")] = -orig
    log.add(T, file, "negative_unit_cost", df["product_id"].iloc[i], "unit_cost", orig, -orig, "negative_value_cost")
    return pd.concat([df, dup], ignore_index=True)


def corrupt_dim_store(store, cfg, log, file="dim_store.csv"):
    """Plant fixed store master issues; deterministic, so no RNG is needed."""
    df = store.copy()
    T = "dim_store"
    df.loc[df["store_id"] == "S12", "store_name"] = "Athlone "
    log.add(T, file, "whitespace_in_name", ["S12"], "store_name", "Athlone", "Athlone ", "text_standardisation")
    df.loc[df["store_id"] == "S16", "region"] = "munster"
    log.add(T, file, "inconsistent_region_label", ["S16"], "region", "Munster", "munster", "region_domain")
    return df


def corrupt_inventory(inv, cfg, log, rng, file="fact_inventory.csv"):
    """Plant inventory snapshot issues."""
    q = cfg["data_quality_issues"]["fact_inventory"]
    df = inv.copy()
    df["received_qty"] = df["received_qty"].astype(float)
    pick = RowPicker(len(df), rng)
    T = "fact_inventory"
    key = lambda d, i: (d["store_id"].iloc[i] + "|" + d["product_id"].iloc[i] + "|" + d["snapshot_date"].iloc[i]).to_numpy()
    c = df.columns.get_loc

    i = pick.pick(rate=q["negative_stock_rate"], within=(df["closing_stock"] > 0).to_numpy())
    orig = df["closing_stock"].iloc[i].to_numpy()
    df.iloc[i, c("closing_stock")] = -orig
    log.add(T, file, "negative_stock", key(df, i), "closing_stock", orig, -orig, "negative_value_stock")

    i = pick.pick(rate=q["broken_flow_rate"], within=(df["opening_stock"] > 0).to_numpy())
    orig = df["opening_stock"].iloc[i].to_numpy()
    new = orig + rng.choice([-3, -2, 2, 3, 5, 8], len(i))
    new = np.maximum(new, 0)
    df.iloc[i, c("opening_stock")] = new
    log.add(T, file, "broken_stock_flow", key(df, i), "opening_stock", orig, new, "inventory_flow_consistency",
            "opening stock does not equal prior week closing stock")

    i = pick.pick(rate=q["null_received_rate"])
    orig = df["received_qty"].iloc[i].to_numpy()
    df.iloc[i, c("received_qty")] = np.nan
    log.add(T, file, "null_received_qty", key(df, i), "received_qty", orig, "", "null_check_received")

    i = pick.pick(rate=q["missing_snapshot_rate"])
    log.add(T, file, "missing_snapshot_row", key(df, i), "*", "row present", "row removed", "inventory_completeness")
    removed = np.zeros(len(df), bool)
    removed[i] = True

    i = pick.pick(rate=q["duplicate_snapshot_rate"])
    dups = df.iloc[i].copy()
    log.add(T, file, "duplicate_snapshot", key(df, i), "*", "", "extra copy", "duplicate_check_inventory")
    return pd.concat([df[~removed], dups], ignore_index=True)


def corrupt_returns(ret, sales_clean, cfg, log, rng, file="fact_returns.csv"):
    """Plant returns issues: invalid sale references, excess quantities, returns dated before
    the sale, and duplicate returns."""
    q = cfg["data_quality_issues"]["fact_returns"]
    df = ret.copy()
    df["original_transaction_id"] = df["original_transaction_id"].astype(object)
    has_ref = df["original_transaction_id"].notna().to_numpy()
    pick = RowPicker(len(df), rng)
    T = "fact_returns"
    c = df.columns.get_loc

    i = pick.pick(rate=q["invalid_transaction_ref_rate"], within=has_ref)
    orig = df["original_transaction_id"].iloc[i].to_numpy()
    new = np.array([o[:-5] + str(90000 + int(rng.integers(0, 9999))) for o in orig])
    df.iloc[i, c("original_transaction_id")] = new
    log.add(T, file, "invalid_transaction_reference", df["return_id"].iloc[i], "original_transaction_id", orig, new,
            "referential_integrity_return_sale")

    i = pick.pick(rate=q["qty_exceeds_sold_rate"], within=has_ref)
    orig = df["return_quantity"].iloc[i].to_numpy()
    new = orig + rng.integers(1, 4, len(i))
    df.iloc[i, c("return_quantity")] = new
    log.add(T, file, "return_qty_exceeds_sold", df["return_id"].iloc[i], "return_quantity", orig, new,
            "return_quantity_vs_sale")

    i = pick.pick(rate=q["return_before_sale_rate"], within=has_ref)
    sale_date = pd.to_datetime(df["_sale_line_key"].iloc[i].str.split("-").str[1], format="%Y%m%d")
    orig = df["return_date"].iloc[i].to_numpy()
    new = (sale_date - pd.to_timedelta(rng.integers(1, 10, len(i)), unit="D")).dt.strftime("%Y-%m-%d").to_numpy()
    df.iloc[i, c("return_date")] = new
    log.add(T, file, "return_before_sale", df["return_id"].iloc[i], "return_date", orig, new, "return_date_vs_sale")

    i = pick.pick(rate=q["duplicate_return_rate"])
    dups = df.iloc[i].copy()
    log.add(T, file, "duplicate_return", df["return_id"].iloc[i], "*", "", "extra copy", "duplicate_check_returns")
    return pd.concat([df, dups], ignore_index=True)


def corrupt_promotions(promo, cfg, log, rng, file="fact_promotions.csv"):
    """Plant promotion calendar issues."""
    q = cfg["data_quality_issues"]["fact_promotions"]
    df = promo.copy()
    pick = RowPicker(len(df), rng)
    T = "fact_promotions"
    key = lambda d, i: (d["promotion_id"].iloc[i] + "|" + d["product_id"].iloc[i] + "|" + d["store_id"].iloc[i]).to_numpy()
    c = df.columns.get_loc
    i = pick.pick(count=q["end_before_start_records"])
    s, e = df["start_date"].iloc[i].to_numpy().copy(), df["end_date"].iloc[i].to_numpy().copy()
    df.iloc[i, c("start_date")] = e
    df.iloc[i, c("end_date")] = s
    log.add(T, file, "end_before_start", key(df, i), "end_date", e, s, "promotion_date_logic")
    i = pick.pick(count=q["unknown_product_records"])
    orig = df["product_id"].iloc[i].to_numpy()
    new = [f"P{v:05d}" for v in rng.integers(91000, 91999, len(i))]
    k_orig = key(df, i)
    df.iloc[i, c("product_id")] = new
    log.add(T, file, "unknown_product", key(df, i), "product_id", orig, new, "referential_integrity_product",
            "original key " + pd.Series(k_orig))
    i = pick.pick(count=q["duplicate_rows"])
    dups = df.iloc[i].copy()
    log.add(T, file, "duplicate_promotion_row", key(df, i), "*", "", "extra copy", "duplicate_check_promotions")
    return pd.concat([df, dups], ignore_index=True)


def corrupt_targets(tgt, cfg, log, rng, file="fact_targets.csv"):
    """Plant target file issues."""
    q = cfg["data_quality_issues"]["fact_targets"]
    df = tgt.copy()
    pick = RowPicker(len(df), rng)
    T = "fact_targets"
    key = lambda d, i: (d["store_id"].iloc[i] + "|" + d["retail_year"].iloc[i].astype(str) + "|"
                        + d["retail_week"].iloc[i].astype(str)).to_numpy()
    i = pick.pick(count=q["x100_rows"])
    orig = df["target_net_revenue"].iloc[i].to_numpy()
    df.iloc[i, df.columns.get_loc("target_net_revenue")] = orig * 100
    log.add(T, file, "target_x100", key(df, i), "target_net_revenue", orig, orig * 100, "target_outlier")
    i = pick.pick(count=q["missing_rows"])
    log.add(T, file, "missing_target_row", key(df, i), "*", "row present", "row removed", "target_completeness")
    removed = np.zeros(len(df), bool)
    removed[i] = True
    i = pick.pick(count=q["duplicate_rows"])
    dups = df.iloc[i].copy()
    dups["target_version"] = "V2"
    dups["target_net_revenue"] = np.round(dups["target_net_revenue"] * rng.uniform(0.95, 1.05, len(i)), -1)
    log.add(T, file, "duplicate_target", key(df, i), "*", "", "second version", "duplicate_check_targets",
            "re-forecast loaded without retiring V1")
    return pd.concat([df[~removed], dups], ignore_index=True)


def split_late_and_missing_batches(sales, cfg, scn, log):
    """B5 late batch -> separate file; configured store-days removed entirely.

    Returns (main extract, late batch, missing rows). Missing rows are never
    written anywhere; they are returned only so the answer key can measure the
    size of the artefact."""
    df = sales
    late = pd.DataFrame(columns=df.columns)
    missing = []
    if scn and "B5_late_arriving_batch" in scn:
        b = scn["B5_late_arriving_batch"]
        m = ((df["store_id"] == b["store_id"]) & (df["transaction_date"] >= b["from_date"])
             & (df["transaction_date"] <= b["to_date"]))
        late = df[m].copy()
        late["extract_batch_id"] = "LATE-" + pd.Timestamp(b["late_extract_timestamp"]).strftime("%Y%m%d")
        late["extract_timestamp"] = b["late_extract_timestamp"]
        g = late.groupby("transaction_date").size()
        log.add("fact_sales", "fact_sales.csv", "late_arriving_batch",
                b["store_id"] + "|" + g.index.to_series(), "*", "rows expected in main extract",
                "rows delivered in fact_sales_late_batch.csv", "completeness_store_day",
                "row count " + g.astype(str).to_numpy())
        df = df[~m]
    for mb in cfg["data_quality_issues"]["missing_batches"]:
        m = (df["store_id"] == mb["store_id"]) & (df["transaction_date"] == mb["date"])
        log.add("fact_sales", "fact_sales.csv", "missing_batch", [f"{mb['store_id']}|{mb['date']}"], "*",
                f"{int(m.sum())} rows", "never delivered", "completeness_store_day", "POS outage, not recoverable")
        missing.append(df[m])
        df = df[~m]
    missing = pd.concat(missing) if missing else pd.DataFrame(columns=df.columns)
    return df.reset_index(drop=True), late.reset_index(drop=True), missing
