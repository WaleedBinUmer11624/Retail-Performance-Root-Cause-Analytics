"""Driver overlap and the mutually exclusive attribution.

Phase 5 slices overlap (the store cluster sells Electronics, stock-outs sit inside Electronics, and so on),
so their EUR figures cannot be added. This module
  1. partitions the net revenue change exactly into store group x category group cells (additive by
     construction: every sale and return belongs to one store and one category);
  2. measures each driver estimate inside each cell, and the pairwise overlaps between drivers;
  3. builds one mutually exclusive attribution. The store-cluster excess is defined against control
     stores, so a category driver only overlaps it by the amount it is LARGER in the cluster than the
     control-store rate implies; that amount is removed from the category driver before adding. Category
     drivers do not overlap each other: they sit in different categories (Electronics vs Home & Kitchen) or on
     different ledger lines (lost sales reduce sales; faulty refunds are returns). The residual line closes
     the attribution to the measured total exactly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def perimeter_matrix(sch: pd.DataFrame, stores: pd.DataFrame, cluster: list[str], cats: dict, py: int, cy: int) -> pd.DataFrame:
    sid = stores.set_index("store_key")["store_id"]
    x = sch.assign(store_id=sch["store_key"].map(sid))
    x["store_group"] = np.where(x["store_id"].isin(cluster), "Store cluster", "Other stores")
    x["category_group"] = x["category"].map(lambda c: next((k for k, v in cats.items() if c in v), "Other categories"))
    g = x.groupby(["store_group", "category_group", "retail_year"])["net_revenue"].sum().unstack("retail_year")
    g["net_revenue_change"] = g[cy] - g[py]
    g = g.rename(columns={py: "net_revenue_py", cy: "net_revenue_cy"}).reset_index()
    return g


def driver_by_store(values: pd.Series) -> pd.Series:
    return values.groupby(level=0).sum()


def cluster_overlap(amount_by_store: pd.Series, py_net_by_store: pd.Series, cluster: list[str], control: list[str]) -> dict:
    """Split a driver's amount in the cluster into the part expected at the control-store rate and the part
    above it. Only a cluster amount LARGER than the control-store rate implies (same sign as the driver) is
    already inside the cluster DiD excess, so only that part is removed as overlap. When the cluster has less of
    the driver than the controls, nothing is removed: a driver is never inflated above its measured total."""
    a = amount_by_store.reindex(py_net_by_store.index).fillna(0.0)
    total = float(a.sum())
    in_cluster = float(a[a.index.isin(cluster)].sum())
    rate = float(a[a.index.isin(control)].sum() / py_net_by_store[py_net_by_store.index.isin(control)].sum())
    expected = rate * float(py_net_by_store[py_net_by_store.index.isin(cluster)].sum())
    diff = in_cluster - expected
    same_sign = total != 0 and diff != 0 and (diff > 0) == (total > 0)
    overlap = min(abs(diff), abs(in_cluster)) * (1 if diff > 0 else -1) if same_sign else 0.0
    return {"total": total, "in_cluster": in_cluster, "expected_in_cluster_at_control_rate": expected,
            "cluster_minus_control_rate": diff, "overlap_with_cluster_excess": overlap, "exclusive": total - overlap}


def exclusive_attribution(total: float, cluster_excess: float, drivers: dict) -> pd.DataFrame:
    rows = [{"component": "Store-cluster excess decline (vs matched control stores)", "amount_eur": cluster_excess,
             "overlap_removed_eur": 0.0, "basis": "DiD counterfactual; defined relative to control stores"}]
    for name, d in drivers.items():
        rows.append({"component": name, "amount_eur": d["exclusive"], "overlap_removed_eur": -d["overlap_with_cluster_excess"],
                     "basis": d.get("basis", "")})
    explained = sum(r["amount_eur"] for r in rows)
    rows.append({"component": "Residual: not attributed",
                 "amount_eur": total - explained, "overlap_removed_eur": 0.0,
                 "basis": "Total minus the components above (closes the attribution exactly)"})
    df = pd.DataFrame(rows)
    df["share_of_change"] = df["amount_eur"] / total
    return df


def pairwise_matrix(items: dict) -> pd.DataFrame:
    """items: name -> {'amount': float, 'overlaps': {other_name: eur}}; symmetric matrix of intersections."""
    names = list(items)
    m = pd.DataFrame(0.0, index=names, columns=names)
    for a in names:
        m.loc[a, a] = items[a]["amount"]
        for b, v in items[a].get("overlaps", {}).items():
            m.loc[a, b] = v
            m.loc[b, a] = v
    return m
