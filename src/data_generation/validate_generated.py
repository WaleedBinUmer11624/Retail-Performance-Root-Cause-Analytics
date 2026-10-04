"""Validate a generated dataset (sample or full) against the Phase 1 BRD.

Two views of the data are used:
  raw view    : the files exactly as written (with planted problems)
  clean view  : raw rows minus every row named in _planted_issues_log.csv,
                duplicates collapsed, late batch added back.
Business rules and KPI identities are tested on the clean view. The planted
issue log itself is tested against the raw view (every logged problem must
really be present). This validates the GENERATOR; it is not the Phase 4
data-quality framework.

Usage:  python -m src.data_generation.validate_generated --data data/sample
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config_loader import PROJECT_ROOT, load_generator_config

SALES_KEY = ["transaction_id", "line_number"]


# ---------------------------------------------------------------- loading
@dataclass
class Dataset:
    """Raw and clean views of one generated dataset, plus its issue log and manifest."""
    path: Path
    raw: dict = field(default_factory=dict)
    clean: dict = field(default_factory=dict)
    log: pd.DataFrame | None = None
    manifest: dict | None = None


def _parse_dates(s: pd.Series) -> pd.Series:
    # The raw extract mixes ISO and legacy dd/mm/yyyy dates; accept both.
    iso = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    dmy = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(dmy)


def load_dataset(path: Path) -> Dataset:
    """Read every generated file and build the clean view."""
    ds = Dataset(path=Path(path))
    for f in ("dim_store", "dim_product", "dim_date", "fact_sales", "fact_sales_late_batch", "fact_inventory",
              "fact_returns", "fact_promotions", "fact_targets"):
        ds.raw[f] = pd.read_csv(ds.path / f"{f}.csv", dtype={"transaction_date": str, "original_line_number": "Int64"},
                                keep_default_na=True, low_memory=False)
    ds.log = pd.read_csv(ds.path / "_planted_issues_log.csv", dtype=str, keep_default_na=False)
    ds.manifest = json.loads((ds.path / "_generation_manifest.json").read_text())
    _build_clean(ds)
    return ds


def _keys(log, table, exclude_types=()):
    m = (log["table_name"] == table) & ~log["issue_type"].isin(exclude_types)
    return set(log.loc[m, "row_key"])


def _build_clean(ds: Dataset):
    r, log = ds.raw, ds.log
    # sales: collapse re-sent receipts, drop rows carrying a planted problem.
    # Category-label and legacy-date issues are presentation problems only, so
    # those rows stay (with the label/date standardised) for KPI tests.
    s = pd.concat([r["fact_sales"], r["fact_sales_late_batch"]], ignore_index=True)
    s = s.drop_duplicates(SALES_KEY, keep="first")
    key = s["transaction_id"] + "|" + s["line_number"].astype(str)
    bad = _keys(log, "fact_sales", ("duplicate_transaction", "inconsistent_category_label", "inconsistent_date_format",
                                    "late_arriving_batch", "missing_batch"))
    s = s[~key.isin(bad)].copy()
    s["transaction_date"] = _parse_dates(s["transaction_date"])
    prod = r["dim_product"].drop_duplicates("product_id", keep="first").copy()
    fix = log[(log["table_name"] == "dim_product") & (log["issue_type"] == "inconsistent_category_label")]
    prod["category"] = prod["product_id"].map(fix.set_index("row_key")["original_value"]).fillna(prod["category"])
    s["category"] = s["product_id"].map(prod.set_index("product_id")["category"])
    ds.clean["fact_sales"] = s

    p = r["dim_product"]
    bad_p = _keys(log, "dim_product", ("duplicate_product_record",))
    ds.clean["dim_product"] = p.drop_duplicates("product_id", keep="first").loc[lambda d: ~d["product_id"].isin(bad_p)]
    ds.clean["dim_product_all"] = prod

    inv = r["fact_inventory"]
    ik = inv["store_id"] + "|" + inv["product_id"] + "|" + inv["snapshot_date"]
    bad_i = _keys(log, "fact_inventory")
    ds.clean["fact_inventory"] = inv[~ik.isin(bad_i)].drop_duplicates(["store_id", "product_id", "snapshot_date"])

    ret = r["fact_returns"]
    bad_r = _keys(log, "fact_returns")
    ds.clean["fact_returns"] = ret[~ret["return_id"].isin(bad_r)].drop_duplicates("return_id")

    pr = r["fact_promotions"]
    pk = pr["promotion_id"] + "|" + pr["product_id"] + "|" + pr["store_id"]
    ds.clean["fact_promotions"] = pr[~pk.isin(_keys(log, "fact_promotions"))].drop_duplicates()

    t = r["fact_targets"]
    tk = t["store_id"] + "|" + t["retail_year"].astype(str) + "|" + t["retail_week"].astype(str)
    ds.clean["fact_targets"] = t[~tk.isin(_keys(log, "fact_targets"))]

    st = r["dim_store"].copy()
    st["store_name"] = st["store_name"].str.strip()
    st["region"] = st["region"].replace({"munster": "Munster"})
    ds.clean["dim_store"] = st
    ds.clean["dim_date"] = r["dim_date"].assign(date=pd.to_datetime(r["dim_date"]["date"]))


# ---------------------------------------------------------------- KPIs (BRD section 5)
def compute_kpis(sales: pd.DataFrame, returns: pd.DataFrame) -> dict:
    """BRD KPIs (revenue, margin, basket and return measures) from sales and returns lines."""
    gross = float((sales["quantity"] * sales["unit_price"]).sum())
    disc = float(sales["discount"].sum())
    sales_rev = float(sales["revenue"].sum())
    ret_val = float(returns["refund_value"].sum())
    units = float(sales["quantity"].sum())
    txns = int(sales["transaction_id"].nunique())
    # COGS = cost of units sold minus standard cost of returned-to-stock units
    cost_map = sales.drop_duplicates("product_id").set_index("product_id")["unit_cost"]
    rts = returns[returns["restockable_flag"].astype(str).str.lower() == "true"]
    cogs = float(sales["cost"].sum() - (rts["return_quantity"] * rts["product_id"].map(cost_map).fillna(0)).sum())
    net = sales_rev - ret_val
    return {
        "gross_sales": gross, "discount_value": disc, "sales_revenue": sales_rev, "returns_value": ret_val,
        "net_revenue": net, "units": units, "transactions": txns, "aov": sales_rev / txns, "upt": units / txns,
        "asp": sales_rev / units, "lines_per_transaction": len(sales) / txns, "cogs": cogs,
        "gross_margin": net - cogs, "gross_margin_pct": (net - cogs) / net,
        "return_rate_value": ret_val / sales_rev,
        "promo_revenue_share": float(sales.loc[sales["promotion_id"].notna(), "revenue"].sum()) / sales_rev,
    }


# ---------------------------------------------------------------- checks
class Checker:
    """Accumulates PASS/FAIL check rows."""
    def __init__(self):
        self.results = []

    def check(self, group, name, passed, value="", expected=""):
        """Record one check and return whether it passed."""
        self.results.append({"group": group, "check": name, "status": "PASS" if bool(passed) else "FAIL",
                             "value": value, "expected": expected})
        return bool(passed)

    def frame(self):
        """All recorded checks as a DataFrame."""
        return pd.DataFrame(self.results)


def check_keys(ds, c: Checker):
    """Key uniqueness, dimension sizes and transaction integrity."""
    cl, r = ds.clean, ds.raw
    c.check("keys", "dim_store: 20 unique store_id", r["dim_store"]["store_id"].is_unique and len(r["dim_store"]) == 20,
            len(r["dim_store"]), "20 unique")
    c.check("keys", "dim_product: 600 distinct product_id", r["dim_product"]["product_id"].nunique() == 600,
            r["dim_product"]["product_id"].nunique(), 600)
    d = cl["dim_date"]["date"]
    c.check("keys", "dim_date: 731 contiguous days", len(d) == 731 and d.diff().dropna().eq(pd.Timedelta(days=1)).all(),
            len(d), 731)
    s = cl["fact_sales"]
    c.check("keys", "fact_sales (clean): transaction_id + line_number unique", not s.duplicated(SALES_KEY).any())
    allines = pd.concat([ds.raw["fact_sales"], ds.raw["fact_sales_late_batch"]]).drop_duplicates(SALES_KEY)
    ln = allines.groupby("transaction_id")["line_number"]
    c.check("transaction integrity", "line numbers are 1..n within each transaction",
            (ln.min() == 1).all() and (ln.max() == ln.count()).all())
    one = s.groupby("transaction_id").agg(n_store=("store_id", "nunique"), n_date=("transaction_date", "nunique"))
    c.check("transaction integrity", "each transaction has one store and one date",
            (one["n_store"] == 1).all() and (one["n_date"] == 1).all())
    c.check("transaction integrity", "transaction_id encodes store and date",
            ((s["transaction_id"].str[:3] == s["store_id"])
             & (s["transaction_id"].str[4:12] == s["transaction_date"].dt.strftime("%Y%m%d"))).all())
    inv = cl["fact_inventory"]
    c.check("keys", "fact_inventory (clean): store + product + snapshot unique",
            not inv.duplicated(["store_id", "product_id", "snapshot_date"]).any())
    c.check("keys", "fact_returns (clean): return_id unique", cl["fact_returns"]["return_id"].is_unique)
    c.check("keys", "fact_promotions (clean): promotion + product + store unique",
            not cl["fact_promotions"].duplicated(["promotion_id", "product_id", "store_id"]).any())
    t = cl["fact_targets"]
    exp_t = len(ds.manifest["simulated_stores"]) * 104
    c.check("keys", "fact_targets (clean): one row per store-week", not t.duplicated(["store_id", "retail_year", "retail_week"]).any())
    c.check("keys", "fact_targets: raw rows = stores x 104 - missing + duplicates",
            len(ds.raw["fact_targets"]) == exp_t - 3 + 2, len(ds.raw["fact_targets"]), exp_t - 1)


def check_referential_integrity(ds, c: Checker):
    """Fact keys resolve to dimensions; orphan returns must be planted or point at a missing batch."""
    cl = ds.clean
    s = cl["fact_sales"]
    stores, prods = set(cl["dim_store"]["store_id"]), set(cl["dim_product_all"]["product_id"])
    c.check("referential integrity", "sales.store_id in dim_store", s["store_id"].isin(stores).all())
    c.check("referential integrity", "sales.product_id in dim_product", s["product_id"].isin(prods).all())
    promos = set(ds.raw["fact_promotions"]["promotion_id"])
    c.check("referential integrity", "sales.promotion_id in fact_promotions",
            s.loc[s["promotion_id"].notna(), "promotion_id"].isin(promos).all())
    pk = set(zip(ds.raw["fact_promotions"]["promotion_id"], ds.raw["fact_promotions"]["product_id"],
                 ds.raw["fact_promotions"]["store_id"]))
    planted_promo = {n.replace("original key ", "") for n in
                     ds.log.loc[ds.log["issue_type"] == "unknown_product", "notes"]}
    sp = s[s["promotion_id"].notna()]
    k3 = sp["promotion_id"] + "|" + sp["product_id"] + "|" + sp["store_id"]
    unmatched = [k for k, a, b, d in zip(k3, sp["promotion_id"], sp["product_id"], sp["store_id"]) if (a, b, d) not in pk]
    c.check("referential integrity", "promoted sales line matches its promotion's product and store",
            set(unmatched) <= planted_promo, f"{len(unmatched)} unmatched lines, all from planted promotion rows"
            if set(unmatched) <= planted_promo else unmatched[:5])
    inv = cl["fact_inventory"]
    c.check("referential integrity", "inventory keys in dimensions",
            inv["store_id"].isin(stores).all() and inv["product_id"].isin(prods).all())
    pr = cl["fact_promotions"]
    c.check("referential integrity", "promotion product and store in dimensions",
            pr["product_id"].isin(prods).all() and pr["store_id"].isin(stores).all())

    # returns: every orphan reference must be explained by a planted issue or missing batch
    ret = ds.raw["fact_returns"].drop_duplicates("return_id")
    sale_keys = set(pd.concat([ds.raw["fact_sales"], ds.raw["fact_sales_late_batch"]])
                    .pipe(lambda d: d["transaction_id"] + "|" + d["line_number"].astype(str)))
    has = ret["original_transaction_id"].notna()
    rk = ret.loc[has, "original_transaction_id"] + "|" + ret.loc[has, "original_line_number"].astype(str)
    orphan_ids = set(ret.loc[has].loc[~rk.isin(sale_keys).to_numpy(), "return_id"])
    planted = _keys(ds.log, "fact_returns", ())
    mb_prefix = {k.split("|")[0] + "-" + k.split("|")[1].replace("-", "") for k in
                 ds.log.loc[ds.log["issue_type"] == "missing_batch", "row_key"]}
    explained = {rid for rid in orphan_ids if rid in planted or
                 ret.set_index("return_id").loc[rid, "original_transaction_id"][:12] in mb_prefix}
    c.check("referential integrity", "every orphan return is planted or points at a missing batch",
            orphan_ids == explained, f"{len(orphan_ids)} orphans, {len(explained)} explained")


def check_dates_and_rules(ds, c: Checker, cfg):
    """Date coverage, line arithmetic, returns rules, inventory flow and promotion dates."""
    cl = ds.clean
    s = cl["fact_sales"]
    start, end = pd.Timestamp(cfg["calendar"]["start_date"]), pd.Timestamp(cfg["calendar"]["end_date"])
    c.check("dates", "all clean sales dates parse and are in range",
            s["transaction_date"].notna().all() and s["transaction_date"].between(start, end).all())
    closed = pd.to_datetime(cfg["calendar"]["closed_dates"])
    c.check("dates", "no sales on Christmas Day", not s["transaction_date"].isin(closed).any())
    trading = cl["dim_date"].loc[cl["dim_date"]["is_trading_day"], "date"]
    missing = {tuple(k.split("|")) for k in ds.log.loc[ds.log["issue_type"] == "missing_batch", "row_key"]}
    gaps = []
    for sid in ds.manifest["simulated_stores"]:
        have = set(s.loc[s["store_id"] == sid, "transaction_date"])
        gaps += [(sid, d.strftime("%Y-%m-%d")) for d in trading if d not in have]
    c.check("dates", "every simulated store trades every trading day (except missing batches)",
            set(gaps) <= missing, f"{len(gaps)} gaps", f"only {sorted(missing)}")
    ret = cl["fact_returns"].copy()
    ret["return_date"] = pd.to_datetime(ret["return_date"])
    c.check("dates", "return dates within extract", ret["return_date"].between(start, end).all())

    # line arithmetic
    calc = np.round(s["quantity"] * s["unit_price"] - s["discount"], 2)
    c.check("business rules", "revenue = quantity x unit_price - discount (every clean line)",
            np.isclose(calc, s["revenue"], atol=0.005).all())
    c.check("business rules", "margin = revenue - cost (every clean line)",
            np.isclose(s["revenue"] - s["cost"], s["margin"], atol=0.005).all())
    c.check("business rules", "quantity between 1 and 10, prices positive",
            s["quantity"].between(1, 10).all() and (s["unit_price"] > 0).all() and (s["unit_cost"] > 0).all())
    c.check("business rules", "discount between 0% and 50% of gross",
            ((s["discount"] >= 0) & (s["discount"] <= 0.5 * s["quantity"] * s["unit_price"] + 0.01)).all())
    promo_lines = s[s["promotion_id"].notna()]
    c.check("business rules", "promoted lines carry a discount", (promo_lines["discount"] > 0).mean() > 0.99,
            f"{(promo_lines['discount'] > 0).mean():.4f}", "> 0.99")

    # returns rules
    sales_all = pd.concat([ds.raw["fact_sales"], ds.raw["fact_sales_late_batch"]]).drop_duplicates(SALES_KEY)
    sk = sales_all.set_index(sales_all["transaction_id"] + "|" + sales_all["line_number"].astype(str))
    rr = ret[ret["original_transaction_id"].notna()].copy()
    rr["k"] = rr["original_transaction_id"] + "|" + rr["original_line_number"].astype(str)
    rr = rr[rr["k"].isin(sk.index)]
    sold_q = pd.to_numeric(sk.loc[rr["k"], "quantity"], errors="coerce").to_numpy()
    # sale date from the transaction_id (authoritative): the sale line's own date
    # column may itself carry a planted date problem
    sale_d = pd.to_datetime(rr["original_transaction_id"].str[4:12], format="%Y%m%d").to_numpy()
    ok_q = (rr["return_quantity"].to_numpy() <= sold_q) | ~(sold_q > 0)
    c.check("business rules", "return quantity <= quantity sold", ok_q.all())
    lag = (rr["return_date"].to_numpy() - sale_d) / np.timedelta64(1, "D")
    c.check("business rules", "return date after sale date and within 30 days (Christmas: 31 Jan)",
            ((lag >= 1) & (lag <= 78)).all(), f"lag {np.nanmin(lag):.0f} to {np.nanmax(lag):.0f} days")
    inv = cl["fact_inventory"]
    flow = inv["opening_stock"] + inv["received_qty"] - inv["sold_qty"] + inv["adjustment_qty"]
    c.check("business rules", "inventory: closing = opening + received - sold + adjustment",
            (flow == inv["closing_stock"]).all())
    c.check("business rules", "inventory: no negative stock", (inv[["opening_stock", "closing_stock"]] >= 0).all().all())
    inv2 = inv.sort_values(["store_id", "product_id", "snapshot_date"]).copy()
    inv2["prev_close"] = inv2.groupby(["store_id", "product_id"])["closing_stock"].shift()
    inv2["prev_date"] = inv2.groupby(["store_id", "product_id"])["snapshot_date"].shift()
    consec = (pd.to_datetime(inv2["snapshot_date"]) - pd.to_datetime(inv2["prev_date"])).dt.days == 7
    touched = set(ds.log.loc[ds.log["table_name"] == "fact_inventory", "row_key"])
    ik = inv2["store_id"] + "|" + inv2["product_id"] + "|" + inv2["prev_date"].fillna("")
    chk = consec & ~ik.isin(touched)
    c.check("business rules", "inventory: opening = previous week's closing", (inv2.loc[chk, "opening_stock"]
                                                                              == inv2.loc[chk, "prev_close"]).all())
    pr = cl["fact_promotions"]
    c.check("business rules", "promotions: start_date <= end_date", (pr["start_date"] <= pr["end_date"]).all())


def check_reconciliation(ds, c: Checker):
    """Units in fact_sales must equal sold_qty in fact_inventory for every
    store-SKU-week not touched by a planted problem."""
    raw = pd.concat([ds.raw["fact_sales"], ds.raw["fact_sales_late_batch"]]).drop_duplicates(SALES_KEY)
    log = ds.log
    sl = log[(log["table_name"] == "fact_sales") & log["row_key"].str.count(r"\|").eq(1)
             & log["row_key"].str.contains(r"^S\d\d-")]
    sl = sl[~sl["issue_type"].isin(["duplicate_transaction", "inconsistent_category_label", "inconsistent_date_format"])]
    raw["k"] = raw["transaction_id"] + "|" + raw["line_number"].astype(str)
    touched = raw[raw["k"].isin(sl["row_key"])].copy()
    orig_pid = sl[sl["column_name"] == "product_id"].set_index("row_key")["original_value"]
    touched["product_id"] = touched["k"].map(orig_pid).fillna(touched["product_id"])
    dd = ds.clean["dim_date"].set_index(ds.clean["dim_date"]["date"].dt.strftime("%Y%m%d"))
    wk_end = pd.to_datetime(dd["retail_week_start"]) + pd.Timedelta(days=6)

    def cells(frame):
        d = frame["transaction_id"].str[4:12]
        return set(zip(frame["transaction_id"].str[:3], frame["product_id"], wk_end.loc[d].dt.strftime("%Y-%m-%d")))
    bad = cells(touched)
    mb_weeks = {(k.split("|")[0], wk_end.loc[k.split("|")[1].replace("-", "")].strftime("%Y-%m-%d"))
                for k in log.loc[log["issue_type"] == "missing_batch", "row_key"]}
    bad_inv = {tuple(k.split("|")) for k in log.loc[log["table_name"] == "fact_inventory", "row_key"]}

    s = ds.clean["fact_sales"].copy()
    s["snapshot_date"] = wk_end.loc[s["transaction_date"].dt.strftime("%Y%m%d")].dt.strftime("%Y-%m-%d").to_numpy()
    units = s.groupby(["store_id", "product_id", "snapshot_date"])["quantity"].sum()
    inv = ds.clean["fact_inventory"].set_index(["store_id", "product_id", "snapshot_date"])["sold_qty"]
    j = pd.concat([units.rename("sales_units"), inv.rename("inv_sold")], axis=1).fillna(0)
    j = j[j.index.get_level_values(2) <= "2025-12-28"]
    idx = pd.Series(j.index.to_list(), index=j.index)
    excl = idx.map(lambda t: t in bad or t in bad_inv or (t[0], t[2]) in mb_weeks)
    jj = j[~excl.to_numpy()]
    mism = int((jj["sales_units"] != jj["inv_sold"]).sum())
    c.check("reconciliation", "sales units = inventory sold_qty for untouched store-SKU-weeks", mism == 0,
            f"{len(jj):,} cells, {mism} mismatches", "0 mismatches")


def check_kpis(ds, c: Checker, cfg):
    """KPI identities and expected ranges; returns the computed KPIs."""
    s, r = ds.clean["fact_sales"], ds.clean["fact_returns"]
    k = compute_kpis(s, r)
    c.check("KPI identities", "Sales Revenue = Gross Sales - Discount Value",
            abs(k["sales_revenue"] - (k["gross_sales"] - k["discount_value"])) < 1.0,
            f"{k['sales_revenue']:,.2f} vs {k['gross_sales'] - k['discount_value']:,.2f}")
    c.check("KPI identities", "Sales Revenue = Transactions x UPT x ASP",
            np.isclose(k["transactions"] * k["upt"] * k["asp"], k["sales_revenue"], rtol=1e-9),
            f"{k['transactions'] * k['upt'] * k['asp']:,.2f}")
    c.check("KPI identities", "Net Revenue = Sales Revenue - Returns Value",
            np.isclose(k["net_revenue"], k["sales_revenue"] - k["returns_value"], rtol=1e-12))
    c.check("KPI identities", "Gross Margin = Net Revenue - COGS", np.isclose(k["gross_margin"], k["net_revenue"] - k["cogs"]))
    c.check("KPI identities", "sum(line margin) = sum(revenue) - sum(cost)",
            np.isclose(s["margin"].sum(), s["revenue"].sum() - s["cost"].sum(), atol=0.01 * len(s) ** 0.5))
    c.check("KPI identities", "AOV = UPT x ASP", np.isclose(k["aov"], k["upt"] * k["asp"]))
    ranges = {"aov": (38, 55, "BRD: basket about EUR 45"), "upt": (1.5, 2.5, "retail norm"),
              "asp": (15, 30, "price bands"), "lines_per_transaction": (1.3, 1.9, "config p=0.62"),
              "gross_margin_pct": (0.33, 0.45, "blend of category target margins"),
              "return_rate_value": (0.02, 0.05, "config return probabilities"),
              "promo_revenue_share": (0.08, 0.35, "promotion calendar")}
    for name, (lo, hi, why) in ranges.items():
        c.check("expected ranges", f"{name} in [{lo}, {hi}]", lo <= k[name] <= hi, round(k[name], 4), why)
    return k


def check_availability(ds, c: Checker):
    """2024 stock availability (closing stock > 0) within 92% to 98%."""
    inv = ds.clean["fact_inventory"]
    base = inv[inv["retail_year"] == 2024]
    av = (base["closing_stock"] > 0).mean()
    c.check("expected ranges", "2024 stock availability in [0.92, 0.98]", 0.92 <= av <= 0.98, round(av, 4),
            "normal retail availability")


def check_seasonality(ds, c: Checker):
    """Category seasonal peaks, the Black Friday spike and Saturday as the busiest day."""
    s = ds.clean["fact_sales"]
    d = s.assign(m=s["transaction_date"].dt.month, y=s["transaction_date"].dt.year)
    by = d.groupby(["category", "m"])["revenue"].sum().unstack()
    c.check("seasonality", "Toys & Games: December > 2.5 x June",
            by.loc["Toys & Games", 12] > 2.5 * by.loc["Toys & Games", 6],
            round(by.loc["Toys & Games", 12] / by.loc["Toys & Games", 6], 2))
    g = by.loc["Garden & Outdoor"]
    c.check("seasonality", "Garden & Outdoor: May-June > 2 x Nov-Jan (monthly average)",
            g[[5, 6]].mean() > 2 * g[[11, 12, 1]].mean(), round(g[[5, 6]].mean() / g[[11, 12, 1]].mean(), 2))
    sg = by.loc["Seasonal & Gifts"]
    c.check("seasonality", "Seasonal & Gifts: Q4 > 60% of annual revenue", sg[[10, 11, 12]].sum() / sg.sum() > 0.6,
            round(sg[[10, 11, 12]].sum() / sg.sum(), 3))
    st = by.loc["Stationery & Crafts"]
    c.check("seasonality", "Stationery & Crafts: August > 1.4 x average month", st[8] > 1.4 * st.mean(),
            round(st[8] / st.mean(), 2))
    dd = ds.clean["dim_date"][["date", "retail_week"]]
    e = s[s["category"] == "Electronics & Tech"].merge(dd, left_on="transaction_date", right_on="date")
    wk = e.groupby("retail_week")["revenue"].sum()
    c.check("seasonality", "Electronics: Black Friday week (48) > 1.5 x weeks 40-44 average",
            wk[48] > 1.5 * wk[40:44].mean(), round(wk[48] / wk[40:44].mean(), 2))
    dow = s.groupby(s["transaction_date"].dt.dayofweek)["revenue"].sum()
    c.check("seasonality", "Saturday is the busiest trading day", dow.idxmax() == 5, int(dow.idxmax()), "5 = Saturday")


def check_store_product(ds, c: Checker):
    """Format differences, launch and discontinuation dates, and minimum category revenue share."""
    s = ds.clean["fact_sales"]
    st = ds.clean["dim_store"].set_index("store_id")
    skus = s.groupby("store_id")["product_id"].nunique()
    fmt = st.loc[skus.index, "store_format"]
    if {"Flagship", "Compact"} <= set(fmt):
        c.check("store/product", "compact stores sell fewer distinct SKUs than flagships",
                skus[fmt == "Compact"].max() < skus[fmt == "Flagship"].min(), skus.to_dict())
    rev = s.groupby("store_id")["revenue"].sum()
    if {"Flagship", "Compact"} <= set(fmt):
        c.check("store/product", "flagship revenue > 2 x compact revenue",
                rev[fmt == "Flagship"].min() > 2 * rev[fmt == "Compact"].max(), rev.round(0).to_dict())
    p = ds.clean["dim_product_all"].set_index("product_id")
    j = s.join(p[["launch_date", "discontinued_date"]], on="product_id")
    early = (j["transaction_date"] < pd.to_datetime(j["launch_date"])).sum()
    c.check("store/product", "no sales before a SKU's launch date", early == 0, int(early))
    post = (j["transaction_date"] > pd.to_datetime(j["discontinued_date"]) + pd.Timedelta(days=7)).sum()
    c.check("store/product", "no sales more than a week after discontinuation", post == 0, int(post))
    share = s.groupby("category")["revenue"].sum() / s["revenue"].sum()
    c.check("store/product", "every category has at least 4% of revenue", (share > 0.04).all(), share.round(3).to_dict())


def check_planted_log(ds, c: Checker):
    """Every logged problem must be present in the raw files."""
    log, r = ds.log, ds.raw
    c.check("planted issues", "issue_id unique", log["issue_id"].is_unique, len(log))
    s = r["fact_sales"]
    keys = s["transaction_id"] + "|" + s["line_number"].astype(str)
    dup_keys = set(keys[keys.duplicated()])
    s_idx = s.set_index(keys)
    s_idx = s_idx[~s_idx.index.duplicated(keep="first")]
    ok = True
    probs = []
    for it, grp in log[log["table_name"] == "fact_sales"].groupby("issue_type"):
        if it in ("late_arriving_batch", "missing_batch"):
            continue
        rows = s_idx.loc[s_idx.index.intersection(grp["row_key"])]
        if it == "duplicate_transaction":
            present = set(grp["row_key"]) == dup_keys
        else:
            col = grp["column_name"].iloc[0]
            nulls = {"nan": "", "None": "", "NULL": "", "<NA>": ""}  # pandas reads these tokens as missing
            v = rows[col].astype(object).where(rows[col].notna(), "").astype(str).replace(nulls)
            pv = grp.set_index("row_key").loc[rows.index, "planted_value"].replace(nulls)
            present = len(rows) == len(grp) and (v.to_numpy() == pv.to_numpy()).all() if it not in (
                "price_x100", "negative_price", "zero_price", "extreme_quantity", "revenue_mismatch", "negative_quantity",
                "null_unit_price", "null_discount") else len(rows) == len(grp)
        if not present:
            probs.append(it)
        ok &= bool(present)
    c.check("planted issues", "every planted fact_sales issue is present in the raw file", ok, probs or "all present")
    late = r["fact_sales_late_batch"]
    c.check("planted issues", "late batch rows are absent from the main extract",
            not (s["transaction_id"].isin(late["transaction_id"])).any() if len(late) else True, len(late))
    mb = log[log["issue_type"] == "missing_batch"]["row_key"]
    present = sum(((s["store_id"] == k.split("|")[0]) & (s["transaction_date"] == k.split("|")[1])).sum() for k in mb)
    c.check("planted issues", "missing batch store-days have no sales rows", present == 0, present)
    counts = log.groupby("table_name")["issue_type"].nunique()
    c.check("planted issues", "planted issue types cover every table",
            set(counts.index) >= {"fact_sales", "dim_product", "dim_store", "fact_inventory", "fact_returns",
                                   "fact_promotions", "fact_targets"}, counts.to_dict())


EVALUATION_ONLY_ASSETS = ("_hidden_scenario", "_scenario_answer_key", "_planted_issues_log", "phase2_calibration_report",
                          "phase2_full_validation", "reconcile_headline")


def check_scenario_separation(c: Checker):
    """Phase 3+ code (DQ, ETL, SQL, analytics, BI) must not read any evaluation-only asset.
    Scoring the DQ framework against the planted log is done outside these folders."""
    offenders = []
    for folder in ("src/analytics", "src/data_quality", "src/etl", "src/forecasting", "sql", "notebooks",
                   "experimental", "powerbi"):
        for f in (PROJECT_ROOT / folder).rglob("*"):
            if f.is_file() and f.suffix in {".py", ".sql", ".ipynb", ".md", ".yaml", ".dax"}:
                txt = f.read_text(errors="ignore")
                if any(asset in txt for asset in EVALUATION_ONLY_ASSETS):
                    offenders.append(str(f.relative_to(PROJECT_ROOT)))
    c.check("scenario separation", "no Phase 3+ code references any evaluation-only asset",
            not offenders, offenders or "none")


def _h2_bounds(ds, year):
    dd = ds.clean["dim_date"]
    d = dd.loc[(dd["retail_year"] == year) & (dd["retail_week"] >= 27), "date"]
    return d.min(), d.max()


def headline_from_data(ds) -> dict:
    """H2 net revenue computed from the data files alone (clean view).
    reported   = main extract only (what a pipeline that ignores the late file reports)
    underlying = main extract + late batch
    Returns are counted by return date in both views."""
    s, r = ds.clean["fact_sales"], ds.clean["fact_returns"].copy()
    r["return_date"] = pd.to_datetime(r["return_date"])
    is_late = s["extract_batch_id"].astype(str).str.startswith("LATE-")
    out = {}
    for y in (2024, 2025):
        lo, hi = _h2_bounds(ds, y)
        in_s = s["transaction_date"].between(lo, hi)
        ret = float(r.loc[r["return_date"].between(lo, hi), "refund_value"].sum())
        out[f"underlying_{y}"] = float(s.loc[in_s, "revenue"].sum()) - ret
        out[f"reported_{y}"] = float(s.loc[in_s & ~is_late, "revenue"].sum()) - ret
        out[f"late_{y}"] = float(s.loc[in_s & is_late, "revenue"].sum())
    out["underlying_yoy_pct"] = 100 * (out["underlying_2025"] / out["underlying_2024"] - 1)
    out["reported_yoy_pct"] = 100 * (out["reported_2025"] / out["reported_2024"] - 1)
    return out


def check_headline(ds, c: Checker):
    """Reported vs underlying decline in the sample (not estate-weighted, so no band test here)."""
    h = headline_from_data(ds)
    c.check("headline", "reported H2 decline is larger than underlying decline",
            h["reported_yoy_pct"] < h["underlying_yoy_pct"],
            f"reported {h['reported_yoy_pct']:.2f}%, underlying {h['underlying_yoy_pct']:.2f}%")
    c.check("headline", "underlying minus reported H2 2025 net revenue = late batch revenue",
            abs((h["underlying_2025"] - h["reported_2025"]) - h["late_2025"]) < 0.01, f"EUR {h['late_2025']:,.2f}")
    c.check("headline", "late batch affects H2 2025 only", h["late_2024"] == 0 and h["late_2025"] > 0)
    # cross-check against the evaluation-only answer key (generator validation only)
    ak = pd.read_csv(ds.path / "_scenario_answer_key.csv").set_index("behaviour")
    ak_late = float(ak.loc["Late batch sales revenue (H2 2025)", "impact_eur"])
    c.check("headline", "late batch revenue in the data equals the answer key", abs(ak_late - h["late_2025"]) < 0.01,
            f"data {h['late_2025']:,.2f} vs key {ak_late:,.2f}")
    ak_und = float(ak.loc["H2 2025 net revenue (underlying)", "impact_pp_of_h2_2024_net_revenue"])
    ak_rep = float(ak.loc["H2 2025 net revenue (reported)", "impact_pp_of_h2_2024_net_revenue"])
    c.check("headline", "data-derived underlying YoY within 0.5pp of the answer key",
            abs(h["underlying_yoy_pct"] - ak_und) < 0.5, f"data {h['underlying_yoy_pct']:.2f} vs key {ak_und:.2f}",
            "difference = rows excluded for planted DQ problems")
    c.check("headline", "answer key: reported minus underlying YoY equals the artefact",
            abs((ak_rep - ak_und) - float(ak.loc["Data-completeness artefact (reported minus underlying YoY)",
                                                 "impact_pp_of_h2_2024_net_revenue"])) <= 0.011)
    miss = float(ak.loc["Missing batch sales revenue (H2 2024)", "impact_eur"])
    c.check("headline", "missing batch has revenue in the key but no rows in the data", miss > 0, f"EUR {miss:,.2f}")


def check_calibration_report(c: Checker, path=None):
    """Estate-level calibration (dry run over all 20 stores): BRD band -7.5% to -8.5% reported."""
    path = path or PROJECT_ROOT / "reports" / "phase2_calibration_report.json"
    if not path.exists():
        c.check("calibration", "estate calibration report exists", False, str(path), "run calibrate_scenario")
        return
    r = json.loads(path.read_text())
    lo, hi = r["target_band_reported_yoy_pct"]
    c.check("calibration", "estate reported H2 YoY within BRD band", lo <= r["yoy_pct_reported"] <= hi,
            f"{r['yoy_pct_reported']:.2f}%", f"{lo}% to {hi}%")
    c.check("calibration", "estate underlying decline smaller than reported decline",
            r["yoy_pct_underlying"] > r["yoy_pct_reported"],
            f"underlying {r['yoy_pct_underlying']:.2f}% vs reported {r['yoy_pct_reported']:.2f}%")
    c.check("calibration", "reported = underlying + DQ artefact (pp)",
            abs(r["yoy_pct_reported"] - (r["yoy_pct_underlying"] + r["dq_artefact_pp"])) <= 0.011,
            f"{r['yoy_pct_underlying']} + {r['dq_artefact_pp']}")
    c.check("calibration", "drivers + residual sum to underlying change",
            abs(r["drivers_sum_pp"] - r["yoy_pct_underlying"]) <= 0.05, f"{r['drivers_sum_pp']} vs {r['yoy_pct_underlying']}")
    named = {k: v["pp"] for k, v in r["drivers"].items() if not k.startswith("Natural")}
    c.check("calibration", "every planted business driver reduces revenue", all(v < 0 for v in named.values()), named)
    lines = r["projected_full_row_counts"]["fact_sales.csv"]
    c.check("calibration", "projected full fact_sales rows within 1.2M to 1.5M", 1_200_000 <= lines <= 1_500_000, f"{lines:,}")


def run_all(path: Path) -> tuple[pd.DataFrame, dict]:
    """Run every check group on the dataset at path; return (check frame, KPIs)."""
    cfg = load_generator_config()
    ds = load_dataset(path)
    c = Checker()
    check_keys(ds, c)
    check_referential_integrity(ds, c)
    check_dates_and_rules(ds, c, cfg)
    check_reconciliation(ds, c)
    kpis = check_kpis(ds, c, cfg)
    check_availability(ds, c)
    check_seasonality(ds, c)
    check_store_product(ds, c)
    check_planted_log(ds, c)
    check_headline(ds, c)
    check_calibration_report(c)
    check_scenario_separation(c)
    return c.frame(), kpis


def main():
    """CLI entry point: validate the dataset folder given by --data."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/sample")
    ap.add_argument("--out", default="reports/phase2_sample_validation.csv")
    a = ap.parse_args()
    res, kpis = run_all(PROJECT_ROOT / a.data)
    out = PROJECT_ROOT / a.out
    out.parent.mkdir(exist_ok=True)
    res.to_csv(out, index=False)
    pd.Series(kpis).to_csv(out.with_name(out.stem + "_kpis.csv"), header=["value"])
    print(res.to_string(index=False, max_colwidth=60))
    print(f"\n{(res['status'] == 'PASS').sum()} passed, {(res['status'] == 'FAIL').sum()} failed")


if __name__ == "__main__":
    main()
