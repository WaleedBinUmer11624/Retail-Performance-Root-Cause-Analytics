"""Faulty-return investigation (Electronics & Tech).

'Faulty' is the reason recorded at the till. It is NOT verified product failure: confirming a defect needs
QA inspection results, batch / lot or serial numbers, supplier defect reports and warranty / RMA outcomes.
This module measures where the recorded increase sits: product, supplier, store, sale cohort, lag and
promotion status, and whether the increase is broad-based or concentrated. Rates use units sold in the
same scope as the denominator; excess returns are measured against the prior-year rate of the same scope, and the
increase is tested with a conditional binomial test that treats both years' rates as uncertain.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from src.analytics.contribution import safe_div


def _h2(df: pd.DataFrame, year_col: str, week_col: str, py: int, cy: int, wf: int, wt: int) -> pd.DataFrame:
    return df[df[year_col].isin([py, cy]) & df[week_col].between(wf, wt)]


def reason_table(rd: pd.DataFrame, category: str, py: int, cy: int) -> pd.DataFrame:
    x = rd[rd["category"] == category]
    g = x.groupby(["return_reason", "return_retail_year"]).agg(value=("refund_value", "sum"),
                                                               units=("return_quantity", "sum")).unstack().fillna(0)
    out = pd.DataFrame({"returns_value_py": g[("value", py)], "returns_value_cy": g[("value", cy)],
                        "returned_units_py": g[("units", py)], "returned_units_cy": g[("units", cy)]})
    out["value_change"] = out["returns_value_cy"] - out["returns_value_py"]
    out["value_change_pct"] = 100 * (out["returns_value_cy"] / out["returns_value_py"] - 1)
    return out.reset_index()


def rate_table(ret: pd.DataFrame, units: pd.DataFrame, key: str, py: int, cy: int) -> pd.DataFrame:
    """Faulty returned units per 100 units sold, by `key`, with the excess over the prior-year rate and a conditional
    (binomial) test of the rate increase."""
    r = ret.groupby([key, "return_retail_year"]).agg(units=("return_quantity", "sum"), value=("refund_value", "sum"))
    r = r.unstack().fillna(0)
    u = units.groupby([key, "retail_year"])["units_sold"].sum().unstack().fillna(0)
    out = pd.DataFrame({"returned_units_py": r[("units", py)] if ("units", py) in r else 0,
                        "returned_units_cy": r[("units", cy)] if ("units", cy) in r else 0,
                        "returns_value_py": r[("value", py)] if ("value", py) in r else 0,
                        "returns_value_cy": r[("value", cy)] if ("value", cy) in r else 0}).join(
        u.rename(columns={py: "units_sold_py", cy: "units_sold_cy"})[["units_sold_py", "units_sold_cy"]], how="outer").fillna(0)
    out["rate_per_100_py"] = 100 * safe_div(out["returned_units_py"], out["units_sold_py"])
    out["rate_per_100_cy"] = 100 * safe_div(out["returned_units_cy"], out["units_sold_cy"])
    base_rate = out["returned_units_py"].sum() / out["units_sold_py"].sum()
    rate_py = np.where(out["units_sold_py"] > 0, out["returned_units_py"] / out["units_sold_py"].replace(0, np.nan), base_rate)
    rate_py = np.nan_to_num(rate_py, nan=base_rate)
    out["expected_units_cy_at_py_rate"] = rate_py * out["units_sold_cy"]
    out["excess_units"] = out["returned_units_cy"] - out["expected_units_cy_at_py_rate"]
    avg_price = safe_div(out["returns_value_cy"].sum(), out["returned_units_cy"].sum())
    out["excess_value_eur"] = out["excess_units"] * avg_price
    # conditional test of two Poisson counts with exposure: given all returns in both years, is the current-year
    # share larger than its share of units sold? (both years' rates are treated as uncertain)
    n = (out["returned_units_cy"] + out["returned_units_py"]).round().astype(int)
    k = out["returned_units_cy"].round().astype(int)
    share = safe_div(out["units_sold_cy"], out["units_sold_cy"] + out["units_sold_py"])
    ok = (out["units_sold_py"] > 0) & (out["units_sold_cy"] > 0) & (n > 0)
    out["p_increase"] = np.where(ok, stats.binom.sf(k - 1, n.clip(lower=1), np.clip(np.nan_to_num(share, nan=0.5), 1e-12, 1)),
                                 np.nan)
    out["value_change"] = out["returns_value_cy"] - out["returns_value_py"]
    return out.reset_index().sort_values("value_change", ascending=False).reset_index(drop=True)


def concentration(t: pd.DataFrame, key: str, top_k: int) -> dict:
    inc = t[t["value_change"] > 0].sort_values("value_change", ascending=False)
    gross = inc["value_change"].sum()
    net = t["value_change"].sum()
    shares = inc["value_change"] / gross if gross else inc["value_change"] * np.nan
    return {"dimension": key, "entities": int(len(t)), "entities_with_increase": int(len(inc)),
            "net_increase": float(net), "gross_increase": float(gross),
            "top_k": top_k, "top_k_share_of_gross": float(shares.head(top_k).sum()),
            "top_k": top_k, "top_entities": ", ".join(map(str, inc[key].head(top_k))),
            "hhi_of_increase": float((shares ** 2).sum()),
            "entities_significant_p01": int((t["p_increase"] < 0.01).sum())}


def investigate(data: dict, cfg: dict, py: int, cy: int, wf: int, wt: int, cluster: list[str]) -> dict:
    c = cfg["returns"]
    cat, reason = c["category"], c["reason"]
    rd = _h2(data["return_detail"], "return_retail_year", "return_retail_week", py, cy, wf, wt)
    rd = rd.assign(return_retail_year=rd["return_retail_year"].astype(int))
    reasons = reason_table(rd, cat, py, cy)
    f = rd[(rd["category"] == cat) & (rd["return_reason"] == reason)]
    sid = data["stores"].set_index("store_key")["store_id"]
    cells = data["stock_cell_week"]
    cells = cells[cells["retail_year"].isin([py, cy]) & cells["retail_week"].between(wf, wt) & (cells["category"] == cat)]
    units = cells.merge(data["products"][["product_key", "product_id", "supplier_name"]], on="product_key").assign(
        store_id=lambda d: d["store_key"].map(sid))
    by_product = rate_table(f, units, "product_id", py, cy)
    by_supplier = rate_table(f, units, "supplier_name", py, cy)
    by_store = rate_table(f, units, "store_id", py, cy)
    by_store["in_cluster"] = by_store["store_id"].isin(cluster)
    # store x supplier: is the store concentration product-specific or store-wide?
    f2 = f.assign(cell=f["store_id"] + " | " + f["supplier_name"])
    u2 = units.assign(cell=units["store_id"] + " | " + units["supplier_name"])
    by_store_supplier = rate_table(f2, u2, "cell", py, cy)
    by_store_supplier[["store_id", "supplier_name"]] = by_store_supplier["cell"].str.split(" \\| ", expand=True)
    # other reasons in the same stores (does the store pattern hold only for 'Faulty'?)
    oth = rd[(rd["category"] == cat) & (rd["return_reason"] != reason)]
    by_store_other = rate_table(oth, units, "store_id", py, cy)
    # sale cohorts (sale month): returned units / units sold in that month, all E&T returns with a linked sale date
    psm = data["product_sale_month"].merge(data["products"][["product_key", "category"]], on="product_key")
    sold = psm[psm["category"] == cat].groupby("sale_year_month")["units_sold"].sum()
    fl = data["return_detail"]
    fl = fl[(fl["category"] == cat) & (fl["return_reason"] == reason) & fl["sale_year_month"].notna()]
    coh = fl.groupby("sale_year_month").agg(returned_units=("return_quantity", "sum"), value=("refund_value", "sum"))
    coh = coh.join(sold, how="left")
    coh["rate_per_100"] = 100 * coh["returned_units"] / coh["units_sold"]
    coh = coh.reset_index()
    coh["sale_year_month"] = coh["sale_year_month"].astype(int)
    lag = f.groupby("return_retail_year")["days_sale_to_return"].describe()[["count", "mean", "25%", "50%", "75%", "max"]]
    ks = stats.ks_2samp(f.loc[f["return_retail_year"] == py, "days_sale_to_return"].dropna(),
                        f.loc[f["return_retail_year"] == cy, "days_sale_to_return"].dropna())
    promo = f.groupby(["return_retail_year", "sale_was_promoted"])["refund_value"].sum().unstack().fillna(0)
    linked = f.groupby("return_retail_year")["is_linked_line"].mean()
    conc = pd.DataFrame([concentration(by_product, "product_id", c["top_k"]),
                         concentration(by_supplier, "supplier_name", c["top_k"]),
                         concentration(by_store, "store_id", c["top_k"])])
    top_stores = by_store[by_store["p_increase"] < 0.01]["store_id"].tolist()
    in_top = f[f["store_id"].isin(top_stores)]
    share_top_stores = float((in_top.loc[in_top["return_retail_year"] == cy, "refund_value"].sum() -
                              in_top.loc[in_top["return_retail_year"] == py, "refund_value"].sum()) /
                             (f.loc[f["return_retail_year"] == cy, "refund_value"].sum() -
                              f.loc[f["return_retail_year"] == py, "refund_value"].sum()))
    sup_in_top = by_store_supplier[by_store_supplier["store_id"].isin(top_stores)].groupby("supplier_name")[
        "value_change"].sum().sort_values(ascending=False)
    oth_sig = by_store_other[by_store_other["store_id"].isin(top_stores)]
    other_reason_rate_change_sig = float(100 * (oth_sig["returned_units_cy"].sum() / oth_sig["units_sold_cy"].sum() -
                                                oth_sig["returned_units_py"].sum() / oth_sig["units_sold_py"].sum()))
    fault_sig = by_store[by_store["store_id"].isin(top_stores)]
    fault_rate_change_sig = float(100 * (fault_sig["returned_units_cy"].sum() / fault_sig["units_sold_cy"].sum() -
                                         fault_sig["returned_units_py"].sum() / fault_sig["units_sold_py"].sum()))
    return {"category": cat, "reason": reason, "other_reason_rate_change_sig_pp": other_reason_rate_change_sig,
            "faulty_rate_change_sig_pp": fault_rate_change_sig, "reasons": reasons, "faulty": f, "by_product": by_product,
            "by_supplier": by_supplier, "by_store": by_store, "by_store_supplier": by_store_supplier,
            "by_store_other_reasons": by_store_other, "cohort": coh, "lag": lag.reset_index(),
            "lag_ks_p": float(ks.pvalue), "promotion_status": promo.reset_index(), "linked_share": linked.to_dict(),
            "concentration": conc, "significant_stores": top_stores, "share_of_increase_in_significant_stores": share_top_stores,
            "supplier_split_in_significant_stores": sup_in_top.reset_index()}
