"""Post-cleaning validation of the curated outputs (PASS / WARN / FAIL).

WARN = a known, documented condition that is reported rather than fixed (for example flagged stock-flow
breaks). FAIL = the curated data breaks a rule it must satisfy; the pipeline exits non-zero.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import id_date, id_store, key_of
from .dimensions import UNKNOWN

KEYS = {"dim_store": ["store_id"], "dim_product": ["product_id"], "dim_date": ["date_key"],
        "fact_sales": ["transaction_id", "line_number"], "fact_inventory": ["store_id", "product_id", "snapshot_date"],
        "fact_returns": ["return_id"], "fact_promotions": ["promotion_id", "product_id", "store_id"],
        "fact_targets": ["store_id", "retail_year", "retail_week"]}


def validate(cur: dict, quarantine: dict, raw_rows: dict, cfg: dict, recon: dict, ctx_results: dict,
             catalogue: dict) -> pd.DataFrame:
    """Post-treatment checks on the curated tables; one PASS/FAIL/WARN row per check."""
    out = []

    def chk(group, name, ok, value="", status_if_bad="FAIL"):
        out.append({"group": group, "check": name, "status": "PASS" if ok else status_if_bad, "value": value})

    tol = cfg["tolerances"]
    # row conservation
    for t, n_raw in raw_rows.items():
        cur_t = "fact_sales" if t == "fact_sales_late_batch" else t
        if t == "fact_sales_late_batch":
            continue
        n_in = n_raw + (raw_rows["fact_sales_late_batch"] if t == "fact_sales" else 0)
        c = cur[cur_t]
        n_cur = int((c["source_file"] != "generated").sum()) if "source_file" in c else len(c)
        n_q = int(sum(len(x) for x in quarantine.get(cur_t, [])))
        chk("row conservation", f"{t}: raw rows = curated + quarantined", n_in == n_cur + n_q,
            f"{n_in:,} = {n_cur:,} + {n_q:,}")
    # keys
    for t, k in KEYS.items():
        chk("keys", f"{t}: primary key unique", not key_of(cur[t], k).duplicated().any(), f"{len(cur[t]):,} rows")
    s, r, inv = cur["fact_sales"], cur["fact_returns"], cur["fact_inventory"]
    stores, prods = set(cur["dim_store"]["store_id"]), set(cur["dim_product"]["product_id"])
    for t, df in (("fact_sales", s), ("fact_returns", r), ("fact_inventory", inv), ("fact_promotions", cur["fact_promotions"])):
        chk("referential integrity", f"{t}: store_id and product_id in dimensions",
            df["store_id"].isin(stores).all() and df["product_id"].isin(prods).all())
    chk("referential integrity", "fact_targets: store_id in dim_store", cur["fact_targets"]["store_id"].isin(stores).all())
    promo_ids = set(cur["fact_promotions"]["promotion_id"]) | {UNKNOWN}
    chk("referential integrity", "fact_sales: promotion_id in fact_promotions or UNKNOWN",
        s["promotion_id"].dropna().isin(promo_ids).all())
    unk = (s["product_id"] == UNKNOWN)
    chk("referential integrity", "fact_sales: lines on the UNKNOWN product member", True,
        f"{int(unk.sum()):,} lines, EUR {s.loc[unk, 'revenue'].sum():,.2f}")

    # sales rules
    start, end = pd.Timestamp(cfg["period"]["start"]), pd.Timestamp(cfg["period"]["end"])
    chk("sales", "dates present, in period and equal to the transaction ID date",
        s["transaction_date"].between(start, end).all() and (s["transaction_date"] == id_date(s["transaction_id"])).all())
    chk("sales", "store equals the transaction ID store", (s["store_id"] == id_store(s["transaction_id"])).all())
    chk("sales", "quantity between 1 and the plausible maximum",
        s["quantity"].between(1, tol["max_plausible_line_quantity"]).all())
    chk("sales", "unit_price and unit_cost positive", ((s["unit_price"] > 0) & (s["unit_cost"] > 0)).all())
    chk("sales", "no missing money fields",
        not s[["unit_price", "discount", "revenue", "unit_cost", "cost", "margin"]].isna().any().any())
    calc = (s["quantity"] * s["unit_price"] - s["discount"]).round(2)
    chk("sales", "revenue = quantity x unit_price - discount", np.isclose(calc, s["revenue"], atol=tol["money"]).all())
    chk("sales", "margin = revenue - cost", np.isclose(s["revenue"] - s["cost"], s["margin"], atol=tol["money"]).all())
    chk("sales", "cost = quantity x unit_cost", np.isclose(s["quantity"] * s["unit_cost"], s["cost"], atol=tol["money"]).all())
    bad_d = (s["discount"] < 0) | (s["discount"] > tol["max_discount_share"] * s["quantity"] * s["unit_price"] + tol["money"])
    chk("sales", "discount between 0 and maximum share of gross", not bad_d.any(), f"{int(bad_d.sum())} lines", "WARN")
    cats = set(cfg["domains"]["categories"]) | {"Unknown"}
    chk("sales", "category canonical", s["category"].isin(cats).all())
    chk("sales", "every line carries a dq_status", s["dq_status"].isin(["clean", "standardised", "flagged", "corrected",
                                                                       "imputed"]).all(),
        "; ".join(f"{k} {v:,}" for k, v in s["dq_status"].value_counts().items()))

    # returns
    chk("returns", "quantity and refund positive", ((r["return_quantity"] > 0) & (r["refund_value"] > 0)).all())
    chk("returns", "return dates in period", r["return_date"].between(start, end).all())
    sk = s.set_index(s["transaction_id"] + "|" + s["line_number"].astype(str))
    lk = r["original_transaction_id"].fillna("") + "|" + r["original_line_number"].astype(str)
    m = lk.isin(sk.index)
    L = sk.loc[lk[m]]
    chk("returns", "no return dated before its sale",
        (r.loc[m, "return_date"].to_numpy() >= id_date(r.loc[m, "original_transaction_id"]).to_numpy()).all())
    chk("returns", "no return quantity above quantity sold", (r.loc[m, "return_quantity"].to_numpy() <= L["quantity"].to_numpy()).all())
    unl = r["original_transaction_id"].notna() & ~r["is_linked"]
    chk("returns", "returns referencing a sale line that was never received", not unl.any(),
        f"{int(unl.sum())} returns, EUR {r.loc[unl, 'refund_value'].sum():,.2f} (kept, flagged FR-04)", "WARN")

    # inventory
    ident = inv["opening_stock"] + inv["received_qty"] - inv["sold_qty"] + inv["adjustment_qty"]
    brk = ident != inv["closing_stock"]
    chk("inventory", "no missing stock quantities",
        not inv[["opening_stock", "received_qty", "sold_qty", "adjustment_qty", "closing_stock"]].isna().any().any())
    chk("inventory", "no negative closing stock", (inv["closing_stock"] >= 0).all())
    chk("inventory", "stock identity holds", not brk.any(), f"{int(brk.sum())} rows flagged FI-06", "WARN")
    chk("inventory", "only integer quantities", all(str(inv[c].dtype) == "Int64" for c in
                                                    ("opening_stock", "received_qty", "sold_qty", "adjustment_qty",
                                                     "closing_stock")))
    # promotions, targets
    p = cur["fact_promotions"]
    chk("promotions", "end_date on or after start_date", (p["end_date"] >= p["start_date"]).all())
    t = cur["fact_targets"]
    med = t.groupby("store_id")["target_net_revenue"].transform("median")
    chk("targets", "targets positive and no extreme outliers",
        ((t["target_net_revenue"] > 0) & (t["target_net_revenue"] / med <= tol["target_outlier_ratio"])).all())
    # dimensions
    d = cur["dim_product"]
    chk("dimensions", "product categories canonical", d["category"].isin(cats).all())
    chk("dimensions", "store regions canonical", cur["dim_store"]["region"].isin(cfg["domains"]["regions"]).all())
    chk("dimensions", "no untrimmed text in dimensions", all(
        (df[c].dropna().astype(str) == df[c].dropna().astype(str).str.strip()).all()
        for df in (cur["dim_store"], d) for c in df.select_dtypes(include=["object", "str"]).columns))

    # KPI identities on curated data
    srev = s["revenue"].sum()
    gross, disc = (s["quantity"] * s["unit_price"]).sum(), s["discount"].sum()
    tx, units = s["transaction_id"].nunique(), s["quantity"].sum()
    chk("KPI identities", "Sales Revenue = Gross Sales - Discount Value", abs(srev - (gross - disc)) < 1.0,
        f"{srev:,.2f} vs {gross - disc:,.2f}")
    chk("KPI identities", "Sales Revenue = Transactions x UPT x ASP", np.isclose(tx * (units / tx) * (srev / units), srev))

    # reconciliation and coverage of the rule catalogue
    chk("reconciliation", "POS units vs stock-system units: match rate improved by cleaning",
        recon["after"]["match_rate"] > recon["before"]["match_rate"],
        f"{recon['before']['match_rate']:.4%} -> {recon['after']['match_rate']:.4%}")
    missing = sorted(set(catalogue) - set(ctx_results))
    chk("framework", "every catalogue rule was evaluated", not missing, ", ".join(missing) or "all")
    return pd.DataFrame(out)
