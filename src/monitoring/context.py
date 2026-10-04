"""Context tables an analyst opens next to an alert (the Alert Investigation page). They describe concentration and
persistence; none of them attributes a cause.

  ew04_sku_alert_context.csv        each top-selling SKU that alerted: supplier, persistence, stock-out cells, exposure
  ew04_supplier_concentration.csv   full-week stock-outs and SKU alerts by supplier (an observation, not a cause)
  ew05_return_context.csv           'Faulty' returns in the flagged window vs the same weeks last year, by supplier,
                                    product, store and reason mix
  ew06_margin_context.csv           GM EUR and GM % beside revenue, per category and window (margin tracked separately)
  ew07_promotion_context.csv        discount rate, promotion share, promotion lines, ASP and units per category window
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .baselines import consecutive

NOT_CAUSE_SUPPLY = ("Supplier-associated stock-outs are an observation; the data does not establish that the supplier "
                    "caused the shortage (no purchase-order or delivery data).")
NOT_CAUSE_RETURNS = "Customer-stated return reason; it does not establish a product defect or a supplier fault."
NOT_CAUSE_PROMO = "Unusual commercial behaviour; the data does not establish that promotions caused the revenue change."


def _lab(cal):
    return dict(zip(cal["retail_week_key"], cal["retail_year"].astype(int).astype(str) + "-W" + cal["retail_week"].astype(int).astype(str).str.zfill(2)))


def stockout_context(T: dict, scored: pd.DataFrame, alerts: pd.DataFrame, cal: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    lab = _lab(cal)
    a = alerts[alerts["signal"] == "EW04"]
    d = scored.copy()
    d["breach_run"] = consecutive(d["breach"] & ~d["dq_fail"].astype(bool), d["entity"], d["t"])
    rows = []
    for sku, g in d[d["entity"].isin(a["entity_id"])].groupby("entity"):
        ga = a[a["entity_id"] == sku]
        wp = ga[ga["severity"].isin(["WARNING", "CRITICAL"])]
        rows.append({
            "product_id": sku, "category": g["category"].iloc[0], "supplier_name": g["supplier_name"].iloc[0],
            "first_alert_week": ga["retail_week"].min(), "first_warning_week": wp["retail_week"].min() if len(wp) else "",
            "alert_weeks": len(ga), "warning_plus_weeks": len(wp),
            "longest_run_of_stockout_weeks": int(g["breach_run"].max()),
            "full_week_stockout_cells_2025": float(g["value"].sum()),
            "max_stores_out_in_a_week": float(g["value"].max()),
            "estimated_exposure_warning_plus_eur": float(wp["estimated_exposure"].sum()),
            "top_seller_rank_pct_best": float(g["rank_pct"].min()),
            "note": NOT_CAUSE_SUPPLY,
        })
    sku = pd.DataFrame(rows).sort_values("estimated_exposure_warning_plus_eur", ascending=False)
    pw = T["kpi_product_week"].merge(cal[["retail_week_key", "retail_year", "retail_week"]], on="retail_week_key")
    pw = pw[pw["retail_week"] >= 27]
    sup = pw.groupby(["category", "supplier_name", "retail_year"])[["full_week_stockout_cells", "in_stock_cells", "ranged_cells"]].sum().reset_index()
    sup = sup.pivot_table(index=["category", "supplier_name"], columns="retail_year",
                          values=["full_week_stockout_cells", "in_stock_cells", "ranged_cells"]).fillna(0)
    sup.columns = [f"{a}_h2_{b}" for a, b in sup.columns]
    sup = sup.reset_index()
    for y in (2024, 2025):
        sup[f"availability_h2_{y}"] = sup[f"in_stock_cells_h2_{y}"] / sup[f"ranged_cells_h2_{y}"].replace(0, np.nan)
    tot = sup.groupby("category")["full_week_stockout_cells_h2_2025"].transform("sum")
    sup["share_of_category_stockouts_h2_2025"] = sup["full_week_stockout_cells_h2_2025"] / tot.replace(0, np.nan)
    if len(sku):
        k = sku.groupby("supplier_name").agg(skus_alerted=("product_id", "nunique"), sku_alert_weeks=("alert_weeks", "sum"))
        sup = sup.merge(k, left_on="supplier_name", right_index=True, how="left").fillna({"skus_alerted": 0, "sku_alert_weeks": 0})
    sup = sup[sup["full_week_stockout_cells_h2_2025"] + sup["full_week_stockout_cells_h2_2024"] > 0].copy()
    sup["note"] = NOT_CAUSE_SUPPLY
    keep = ["category", "supplier_name", "full_week_stockout_cells_h2_2024", "full_week_stockout_cells_h2_2025",
            "share_of_category_stockouts_h2_2025", "availability_h2_2024", "availability_h2_2025", "skus_alerted",
            "sku_alert_weeks", "note"]
    return sku, sup[[c for c in keep if c in sup.columns]].sort_values("full_week_stockout_cells_h2_2025", ascending=False)


def return_context(T: dict, cal: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Electronics & Tech 'Faulty' returns in the weeks EW05 watches for the known episode window vs the same weeks last
    year, by supplier, product and store, plus the reason mix (faulty share of all returned units)."""
    cat = cfg["monitoring"]["signals"]["EW05"]["category"]
    ep = [e for e in cfg["monitoring"]["episodes"] if e["id"] == "EP3"][0]
    cy = cal.loc[(cal["retail_week_key"] >= ep["start_week"]) & (cal["retail_week_key"] <= ep["end_week"])]
    keys = {"cy": set(cy["retail_week_key"]), "py": set(cy["py_week_key"])}
    rp = T["returns_product_week"]
    rp = rp[rp["category"] == cat]
    sales = T["kpi_product_week"]
    sales = sales[sales["category"] == cat]
    ssc = T["kpi_store_category_week"]
    ssc = ssc[ssc["category"] == cat]
    out = []
    for dim, rkey, skey, sdf in [("supplier", "supplier_name", "supplier_name", sales), ("product", "product_id", "product_id", sales),
                                  ("store", "store_id", "store_id", ssc)]:
        parts = []
        for yr, ks in keys.items():
            r = rp[rp["retail_week_key"].isin(ks)].groupby(rkey)[["faulty_units", "returned_units", "faulty_value"]].sum()
            u = sdf[sdf["retail_week_key"].isin(ks)].groupby(skey)["units"].sum().rename("units")
            parts.append(r.join(u, how="outer").fillna(0).add_suffix(f"_{yr}"))
        df = parts[0].join(parts[1], how="outer").fillna(0).reset_index().rename(columns={rkey: "key"})
        df.insert(0, "dimension", dim)
        out.append(df)
    df = pd.concat(out, ignore_index=True)
    for yr in ("cy", "py"):
        df[f"faulty_per_100_sold_{yr}"] = 100 * df[f"faulty_units_{yr}"] / df[f"units_{yr}"].replace(0, np.nan)
        df[f"faulty_share_of_returns_{yr}"] = df[f"faulty_units_{yr}"] / df[f"returned_units_{yr}"].replace(0, np.nan)
    df["faulty_value_change_eur"] = df["faulty_value_cy"] - df["faulty_value_py"]
    tot = df.groupby("dimension")["faulty_value_change_eur"].transform(lambda s: s.clip(lower=0).sum())
    df["share_of_increase"] = df["faulty_value_change_eur"].clip(lower=0) / tot.replace(0, np.nan)
    df["window_cy"] = f"{ep['start_week']}-{ep['end_week']}"
    df["note"] = NOT_CAUSE_RETURNS
    df = df.sort_values(["dimension", "faulty_value_change_eur"], ascending=[True, False])
    # keep every supplier and store; the 15 products with the largest increase
    prod = df[df["dimension"] == "product"].head(15)
    return pd.concat([df[df["dimension"] != "product"], prod], ignore_index=True)


def margin_context(ew06: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    lab = _lab(cal)
    d = ew06.copy()
    d["retail_week"] = d["retail_week_key"].map(lab)
    d["gm_eur_4w"] = d["gross_margin_w"]
    d["gm_eur_4w_py"] = d["gross_margin_w_py"]
    d["gm_eur_change"] = d["gross_margin_w"] - d["gross_margin_w_py"]
    d["gm_eur_change_pct"] = d["gross_margin_w"] / d["gross_margin_w_py"] - 1
    d["net_revenue_change_pct"] = d["revenue_window_yoy"]
    d["gm_pct_4w"], d["gm_pct_4w_py"] = d["gm_pct"], d["gm_pct_py"]
    d["gm_pct_change_pp"] = 100 * (d["gm_pct"] - d["gm_pct_py"])
    d["margin_fell_while_revenue_held"] = (d["gm_eur_change"] < 0) & (d["revenue_window_yoy"] >= 0)
    cols = ["retail_week_key", "retail_week", "entity", "net_revenue_w", "net_revenue_w_py", "net_revenue_change_pct",
            "gm_eur_4w", "gm_eur_4w_py", "gm_eur_change", "gm_eur_change_pct", "gm_pct_4w", "gm_pct_4w_py", "gm_pct_change_pp",
            "margin_fell_while_revenue_held", "dq_status"]
    return d[cols].rename(columns={"entity": "category"}).sort_values(["category", "retail_week_key"])


def promotion_context(ew07: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    lab = _lab(cal)
    d = ew07.copy()
    d["retail_week"] = d["retail_week_key"].map(lab)
    d["discount_rate_4w"], d["discount_rate_4w_py"] = d["disc"], d["disc_py"]
    d["promotion_share_4w"], d["promotion_share_4w_py"] = d["promo_share"], d["promo_share_py"]
    d["promotion_lines_4w"], d["promotion_lines_4w_py"] = d["promo_lines_w"], d["promo_lines_w_py"]
    d["promotion_frequency_ratio"] = d["promo_lines_w"] / d["promo_lines_w_py"].replace(0, np.nan)
    d["asp_4w"] = d["sales_revenue_w"] / d["units_w"].replace(0, np.nan)
    d["asp_4w_py"] = d["sales_revenue_w_py"] / d["units_w_py"].replace(0, np.nan)
    d["units_change_pct"] = d["units_w"] / d["units_w_py"].replace(0, np.nan) - 1
    d["gm_pct_4w"] = d["gross_margin_w"] / d["net_revenue_w"]
    d["gm_pct_4w_py"] = d["gross_margin_w_py"] / d["net_revenue_w_py"]
    d["net_revenue_change_pct"] = d["revenue_window_yoy"]
    d["note"] = NOT_CAUSE_PROMO
    cols = ["retail_week_key", "retail_week", "entity", "discount_rate_4w", "discount_rate_4w_py", "promotion_share_4w",
            "promotion_share_4w_py", "promotion_lines_4w", "promotion_lines_4w_py", "promotion_frequency_ratio", "asp_4w",
            "asp_4w_py", "units_change_pct", "gm_pct_4w", "gm_pct_4w_py", "net_revenue_change_pct", "dq_status", "note"]
    return d[cols].rename(columns={"entity": "category"}).sort_values(["category", "retail_week_key"])
