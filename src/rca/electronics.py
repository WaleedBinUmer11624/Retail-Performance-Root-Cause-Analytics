"""Electronics & Tech: category decline, stock-out episodes, lost sales and the supplier comparison.

Reuses the Phase 5 lost-sales estimator (src/analytics/diagnostics.py) unchanged, so Phase 6 estimates
reconcile with Phase 5. The primary lost-sales figure counts only store-SKU-weeks with no stock at any
point (opening 0, nothing received); the literal BR-05 figure over all stock-out weeks is an upper bound.
The supplier comparison is tested at SKU level (bootstrap CI, permutation p-value, leave-one-SKU-out)
so that one SKU cannot make a supplier look systematically worse.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics import diagnostics as D
from src.analytics.contribution import safe_div


def build_estimates(data: dict, windows: list[int], min_hist: int, seasonal: bool, py: int, cy: int,
                    week_from: int, week_to: int, panel: D.Panel | None = None) -> tuple[D.Panel, dict, pd.DataFrame]:
    panel = panel or D.Panel(data["stock_cell_week"], data["weeks"])
    if not seasonal:                                   # sensitivity variant: no seasonal adjustment
        orig = panel.seasonal_index
        panel.seasonal_index = lambda: np.ones((len(panel.products), len(panel.week_keys)))
        est = D.estimate_expected(panel, windows, min_hist)
        panel.seasonal_index = orig
    else:
        est = D.estimate_expected(panel, windows, min_hist)
    lost = D.lost_sales_cells(panel, est, (py, cy), week_from, week_to)
    lost = lost.merge(data["products"][["product_key", "product_id", "supplier_name"]], on="product_key", how="left")
    return panel, est, lost


def lost_totals(lost: pd.DataFrame, py: int, cy: int, mask=None) -> dict:
    x = lost if mask is None else lost[mask]
    g = x.groupby("retail_year")[["est_lost_sales_eur", "est_lost_sales_upper_eur"]].sum().reindex([py, cy]).fillna(0)
    return {"primary_py": float(g.loc[py, "est_lost_sales_eur"]), "primary_cy": float(g.loc[cy, "est_lost_sales_eur"]),
            "upper_py": float(g.loc[py, "est_lost_sales_upper_eur"]), "upper_cy": float(g.loc[cy, "est_lost_sales_upper_eur"]),
            "primary_change": float(g.loc[cy, "est_lost_sales_eur"] - g.loc[py, "est_lost_sales_eur"]),
            "upper_change": float(g.loc[cy, "est_lost_sales_upper_eur"] - g.loc[py, "est_lost_sales_upper_eur"])}


def _cells(data: dict, py: int, cy: int, wf: int, wt: int) -> pd.DataFrame:
    c = data["stock_cell_week"]
    c = c[c["retail_year"].isin([py, cy]) & c["retail_week"].between(wf, wt)]
    return c.merge(data["products"][["product_key", "product_id", "supplier_name"]], on="product_key", how="left")


def category_kpis(data: dict, category: str, py: int, cy: int) -> pd.DataFrame:
    c = data["category_contribution"].set_index("category").loc[category]
    rows = []
    for m, a, b in (("net_revenue", c["net_revenue_py"], c["net_revenue_cy"]),
                    ("sales_revenue", c["sales_revenue_py"], c["sales_revenue_cy"]),
                    ("transactions_with_category", c["transactions_with_category_py"], c["transactions_with_category_cy"]),
                    ("units_sold", c["units_sold_py"], c["units_sold_cy"]), ("asp", c["asp_py"], c["asp_cy"]),
                    ("returns_value", c["returns_value_py"], c["returns_value_cy"]),
                    ("return_rate_value", c["return_rate_value_py"], c["return_rate_value_cy"]),
                    ("availability", c["availability_py"], c["availability_cy"]),
                    ("gross_margin_pct", c["gross_margin_pct_py"], c["gross_margin_pct_cy"])):
        rows.append({"metric": m, "prior": float(a), "current": float(b), "change": float(b - a),
                     "change_pct": 100 * float(safe_div(b - a, a))})
    return pd.DataFrame(rows)


def by_supplier(cells: pd.DataFrame, lost: pd.DataFrame, py: int, cy: int, category: str | None) -> pd.DataFrame:
    c = cells if category is None else cells[cells["category"] == category]
    lo = lost if category is None else lost[lost["category"] == category]
    full = (c["opening_stock"] <= 0) & (c["received_qty"] <= 0) & (c["is_in_stock"] == 0)
    g = c.assign(out=(c["is_in_stock"] == 0).astype(int), full=full.astype(int)).groupby(["supplier_name", "retail_year"]).agg(
        skus=("product_key", "nunique"), ranged_cells=("product_key", "size"), out_cells=("out", "sum"),
        full_week_out_cells=("full", "sum"), units_sold=("units_sold", "sum"), sales_revenue=("sales_revenue", "sum"))
    l = lo.groupby(["supplier_name", "retail_year"])[["est_lost_sales_eur", "est_lost_sales_upper_eur"]].sum()
    g = g.join(l, how="left").fillna(0.0).reset_index()
    w = g.pivot(index="supplier_name", columns="retail_year")
    out = pd.DataFrame(index=w.index)
    for m in ("skus", "ranged_cells", "out_cells", "full_week_out_cells", "sales_revenue", "est_lost_sales_eur",
              "est_lost_sales_upper_eur"):
        out[f"{m}_py"] = w[(m, py)]
        out[f"{m}_cy"] = w[(m, cy)]
    out["availability_py"] = 1 - out["out_cells_py"] / out["ranged_cells_py"]
    out["availability_cy"] = 1 - out["out_cells_cy"] / out["ranged_cells_cy"]
    out["availability_change_pp"] = 100 * (out["availability_cy"] - out["availability_py"])
    out["lost_primary_change"] = out["est_lost_sales_eur_cy"] - out["est_lost_sales_eur_py"]
    out["lost_upper_change"] = out["est_lost_sales_upper_eur_cy"] - out["est_lost_sales_upper_eur_py"]
    out["sales_change"] = out["sales_revenue_cy"] - out["sales_revenue_py"]
    tot = out["lost_primary_change"].sum()
    out["share_of_lost_primary_change"] = out["lost_primary_change"] / tot if tot else np.nan
    return out.reset_index().sort_values("lost_primary_change", ascending=False).reset_index(drop=True)


def sku_table(cells: pd.DataFrame, lost: pd.DataFrame, category: str, py: int, cy: int, top_share: float) -> pd.DataFrame:
    c = cells[cells["category"] == category]
    full = (c["opening_stock"] <= 0) & (c["received_qty"] <= 0) & (c["is_in_stock"] == 0)
    g = c.assign(out=(c["is_in_stock"] == 0).astype(int), full=full.astype(int)).groupby(
        ["product_id", "supplier_name", "retail_year"]).agg(cells=("out", "size"), out=("out", "sum"), full=("full", "sum"),
                                                            revenue=("sales_revenue", "sum"), units=("units_sold", "sum"))
    l = lost[lost["category"] == category].groupby(["product_id", "supplier_name", "retail_year"])[
        ["est_lost_sales_eur", "est_lost_sales_upper_eur"]].sum()
    g = g.join(l, how="left").fillna(0.0).reset_index().pivot(index=["product_id", "supplier_name"], columns="retail_year")
    out = pd.DataFrame(index=g.index)
    for m in ("cells", "out", "full", "revenue", "units", "est_lost_sales_eur", "est_lost_sales_upper_eur"):
        out[f"{m}_py"] = g[(m, py)] if (m, py) in g.columns else 0.0
        out[f"{m}_cy"] = g[(m, cy)] if (m, cy) in g.columns else 0.0
    out = out.fillna(0.0).reset_index()
    out["oos_rate_py"] = safe_div(out["out_py"], out["cells_py"])
    out["oos_rate_cy"] = safe_div(out["out_cy"], out["cells_cy"])
    out["oos_rate_change_pp"] = 100 * (out["oos_rate_cy"] - out["oos_rate_py"])
    out["lost_primary_change"] = out["est_lost_sales_eur_cy"] - out["est_lost_sales_eur_py"]
    out = out.sort_values(["revenue_py", "product_id"], ascending=[False, True]).reset_index(drop=True)
    n_top = max(1, int(np.ceil(top_share * (out["revenue_py"] > 0).sum())))
    out["prior_year_revenue_rank"] = np.arange(1, len(out) + 1)
    out["high_seller"] = out["prior_year_revenue_rank"] <= n_top
    return out


def concentration(sku: pd.DataFrame) -> dict:
    tot_lost = sku["lost_primary_change"].sum()
    tot_full = sku["full_cy"].sum()
    hs = sku[sku["high_seller"]]
    top = sku.sort_values("lost_primary_change", ascending=False)
    return {"high_sellers": int(len(hs)), "skus": int(len(sku)),
            "high_seller_share_of_lost_change": float(hs["lost_primary_change"].sum() / tot_lost) if tot_lost else np.nan,
            "high_seller_share_of_full_week_outs_cy": float(hs["full_cy"].sum() / tot_full) if tot_full else np.nan,
            "high_seller_share_of_revenue_py": float(hs["revenue_py"].sum() / sku["revenue_py"].sum()),
            "top1_sku": top.iloc[0]["product_id"], "top1_share": float(top.iloc[0]["lost_primary_change"] / tot_lost),
            "top3_share": float(top.head(3)["lost_primary_change"].sum() / tot_lost),
            "skus_with_lost_increase": int((sku["lost_primary_change"] > 1).sum())}


def episodes(data: dict, category: str, weeks: pd.DataFrame, py: int, cy: int, wf: int, wt: int) -> pd.DataFrame:
    e = data["stockout_episode"]
    e = e[e["category"] == category].copy()
    wk = weeks.set_index("retail_week_key")
    e["start_year"] = e["first_week_key"].map(wk["retail_year"])
    e["start_week"] = e["first_week_key"].map(wk["retail_week"])
    e = e[e["start_year"].isin([py, cy]) & e["start_week"].between(wf, wt)]
    return e


def episode_summary(ep: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (sup, yr), g in ep.groupby(["supplier_name", "start_year"]):
        rows.append({"supplier_name": sup, "retail_year": int(yr), "episodes": len(g),
                     "mean_weeks_out": float(g["weeks_out"].mean()), "median_weeks_out": float(g["weeks_out"].median()),
                     "max_weeks_out": int(g["weeks_out"].max()), "share_4plus_weeks": float((g["weeks_out"] >= 4).mean()),
                     "full_weeks_out": int(g["full_weeks_out"].sum())})
    return pd.DataFrame(rows).sort_values(["supplier_name", "retail_year"]).reset_index(drop=True)


def recovery(panel: D.Panel, est: dict, ep: pd.DataFrame, weeks_after: int) -> pd.DataFrame:
    """Sales in the weeks after an episode ends (stock back) against the expected rate: pent-up demand or lasting loss?"""
    rows = []
    for r in ep.itertuples():
        s, p = panel.s_idx.get(r.store_key), panel.p_idx.get(r.product_key)
        w_end = panel.w_idx.get(r.last_week_key)
        if s is None or p is None or w_end is None:
            continue
        for k in range(1, weeks_after + 1):
            w = w_end + k
            if w >= len(panel.week_keys) or not panel.ranged[s, p, w]:
                break
            exp = est["expected_units"][s, p, w]
            if np.isnan(exp):
                continue
            price = float(np.nan_to_num(est["price"][s, p, w], nan=0.0))
            rows.append({"supplier_name": r.supplier_name, "retail_year": int(r.start_year), "weeks_after": k,
                         "actual_units": float(panel.units_sold[s, p, w]), "expected_units": float(exp),
                         "received_qty": float(panel.received_qty[s, p, w]),
                         "excess_sales_eur": (float(panel.units_sold[s, p, w]) - float(exp)) * price,
                         "actual_sales_eur": float(panel.units_sold[s, p, w]) * price, "expected_sales_eur": float(exp) * price,
                         "has_full_week": bool(r.full_weeks_out > 0)})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    g = df.groupby(["supplier_name", "retail_year", "weeks_after", "has_full_week"])[
        ["actual_units", "expected_units", "received_qty", "excess_sales_eur", "actual_sales_eur", "expected_sales_eur"]].sum()
    g["actual_to_expected"] = g["actual_units"] / g["expected_units"]
    return g.reset_index()


def replenishment(cells: pd.DataFrame, category: str) -> pd.DataFrame:
    c = cells[cells["category"] == category]
    g = c.assign(receipt=(c["received_qty"] > 0).astype(int)).groupby(["supplier_name", "retail_year"]).agg(
        cell_weeks=("received_qty", "size"), received_units=("received_qty", "sum"), weeks_with_receipt=("receipt", "sum"),
        units_sold=("units_sold", "sum"), mean_opening_stock=("opening_stock", "mean"))
    g["received_per_cell_week"] = g["received_units"] / g["cell_weeks"]
    g["receipt_week_share"] = g["weeks_with_receipt"] / g["cell_weeks"]
    g["received_to_sold"] = g["received_units"] / g["units_sold"]
    return g.reset_index()


def supplier_test(sku: pd.DataFrame, supplier: str, reps: int, seed: int, metric: str = "oos_rate_change_pp") -> dict:
    """Is the supplier's SKU-level deterioration different from the other suppliers' SKUs in the category?"""
    both = sku[(sku["cells_py"] > 0) & (sku["cells_cy"] > 0)].copy()
    a = both.loc[both["supplier_name"] == supplier, metric].to_numpy()
    b = both.loc[both["supplier_name"] != supplier, metric].to_numpy()
    diff = float(a.mean() - b.mean())
    rng = np.random.default_rng(seed)
    boots = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(reps)]
    lab = np.r_[np.ones(len(a)), np.zeros(len(b))].astype(bool)
    vals = np.r_[a, b]
    perm = []
    for _ in range(reps):
        rng.shuffle(lab)
        perm.append(vals[lab].mean() - vals[~lab].mean())
    perm = np.array(perm)
    loo = [float(np.delete(a, i).mean() - b.mean()) for i in range(len(a))] if len(a) > 1 else [diff]
    med_a, med_b = float(np.median(a)), float(np.median(b))
    return {"supplier": supplier, "metric": metric, "supplier_skus": int(len(a)), "other_skus": int(len(b)),
            "supplier_mean": float(a.mean()), "other_mean": float(b.mean()), "difference": diff,
            "ci_low": float(np.percentile(boots, 2.5)), "ci_high": float(np.percentile(boots, 97.5)),
            "permutation_p_two_sided": float((np.sum(np.abs(perm) >= abs(diff)) + 1) / (reps + 1)),
            "leave_one_sku_out_min": float(min(loo)), "leave_one_sku_out_max": float(max(loo)),
            "supplier_median": med_a, "other_median": med_b,
            "supplier_skus_worse_than_other_median": int((a > med_b).sum())}


def weekly_timeline(cells: pd.DataFrame, lost: pd.DataFrame, category: str, supplier: str, py: int, cy: int) -> pd.DataFrame:
    c = cells[cells["category"] == category].assign(is_sup=lambda d: d["supplier_name"] == supplier)
    rows = []
    for (yr, wk), g in c.groupby(["retail_year", "retail_week"]):
        l = lost[(lost["category"] == category) & (lost["retail_year"] == yr) & (lost["retail_week"] == wk)]
        rows.append({"retail_year": int(yr), "retail_week": int(wk),
                     "availability_category": float(g["is_in_stock"].mean()),
                     "availability_supplier": float(g.loc[g["is_sup"], "is_in_stock"].mean()),
                     "availability_other_suppliers": float(g.loc[~g["is_sup"], "is_in_stock"].mean()),
                     "category_sales": float(g["sales_revenue"].sum()),
                     "supplier_sales": float(g.loc[g["is_sup"], "sales_revenue"].sum()),
                     "lost_primary": float(l["est_lost_sales_eur"].sum()), "lost_upper": float(l["est_lost_sales_upper_eur"].sum())})
    t = pd.DataFrame(rows)
    p = t[t["retail_year"] == py].set_index("retail_week")
    q = t[t["retail_year"] == cy].set_index("retail_week")
    out = q.join(p, lsuffix="_cy", rsuffix="_py").reset_index()
    out["category_sales_yoy_pct"] = 100 * (out["category_sales_cy"] / out["category_sales_py"] - 1)
    out["supplier_sales_yoy_pct"] = 100 * (out["supplier_sales_cy"] / out["supplier_sales_py"] - 1)
    return out.drop(columns=["retail_year_cy", "retail_year_py"])


def range_distribution(cells: pd.DataFrame, stores: pd.DataFrame, category: str, py: int, cy: int,
                       exclude_stores: list[str]) -> pd.DataFrame:
    """Partition of the category's sales change (FACT) outside the excluded stores, by supplier and SKU status:
    delisted (ranged in the prior H2 only), new (current H2 only) and continuing SKUs. For continuing SKUs the
    change is split into a distribution effect (fewer or more ranged store-SKU-weeks, at the prior-year sales per
    ranged cell) and a rate effect (sales per ranged cell)."""
    sid = stores.set_index("store_key")["store_id"]
    c = cells[(cells["category"] == category) & ~cells["store_key"].map(sid).isin(exclude_stores)]
    yrs = c.groupby("product_id")["retail_year"].agg(lambda x: set(x))
    status = yrs.map(lambda y: "continuing" if {py, cy} <= y else ("delisted" if py in y else "new"))
    c = c.assign(sku_status=c["product_id"].map(status))
    g = c.groupby(["supplier_name", "sku_status", "retail_year"]).agg(
        skus=("product_id", "nunique"), ranged_cells=("product_key", "size"), sales=("sales_revenue", "sum"))
    w = g.unstack("retail_year").fillna(0)
    out = pd.DataFrame({"skus_py": w[("skus", py)], "skus_cy": w[("skus", cy)],
                        "ranged_cells_py": w[("ranged_cells", py)], "ranged_cells_cy": w[("ranged_cells", cy)],
                        "sales_py": w[("sales", py)], "sales_cy": w[("sales", cy)]}).reset_index()
    out["sales_change"] = out["sales_cy"] - out["sales_py"]
    spc_py = np.where(out["ranged_cells_py"] > 0, out["sales_py"] / out["ranged_cells_py"].where(out["ranged_cells_py"] > 0, 1), 0.0)
    cont = out["sku_status"] == "continuing"
    out["distribution_effect"] = np.where(cont, (out["ranged_cells_cy"] - out["ranged_cells_py"]) * spc_py, np.nan)
    out["rate_effect"] = np.where(cont, out["sales_change"] - out["distribution_effect"], np.nan)
    return out.sort_values(["supplier_name", "sku_status"]).reset_index(drop=True)


def recovery_by_week(rec: pd.DataFrame, supplier: str | None = None) -> pd.DataFrame:
    """Actual-to-expected sales after restock by year and week after the episode (all episodes)."""
    r = rec if supplier is None else rec[rec["supplier_name"] == supplier]
    g = r.groupby(["retail_year", "weeks_after"])[["actual_units", "expected_units"]].sum()
    g["actual_to_expected"] = g["actual_units"] / g["expected_units"]
    return g.reset_index()


def recovery_offset(rec: pd.DataFrame, py: int, cy: int, full_week_only: bool) -> float:
    """Deferred demand: current-year sales after restock above what the PRIOR-YEAR actual-to-expected ratio after
    restock implies (so the normal post-restock bounce and the larger number of episodes are not counted).
    full_week_only=True keeps episodes containing a full-week stock-out (the scope of the primary estimate)."""
    if rec.empty:
        return 0.0
    r = rec[rec["has_full_week"]] if full_week_only else rec
    base = rec[rec["retail_year"] == py]                  # prior-year normal bounce, all episodes
    ratio = float(base["actual_sales_eur"].sum() / base["expected_sales_eur"].sum()) if len(base) else 1.0
    c = r[r["retail_year"] == cy]
    return float(c["actual_sales_eur"].sum() - ratio * c["expected_sales_eur"].sum())


def investigate(data: dict, cfg: dict, py: int, cy: int, wf: int, wt: int, cluster: list[str]) -> dict:
    e = cfg["electronics"]
    cat = e["category"]
    ls = cfg["lost_sales"]
    panel, est, lost = build_estimates(data, ls["windows"], ls["min_history_weeks"], True, py, cy, wf, wt)
    cells = _cells(data, py, cy, wf, wt)
    sup_cat = by_supplier(cells, lost, py, cy, cat)
    sup_all = by_supplier(cells, lost, py, cy, None)
    top_sup = sup_cat.iloc[0]["supplier_name"]
    sku = sku_table(cells, lost, cat, py, cy, e["high_seller_top_share"])
    ep = episodes(data, cat, data["weeks"], py, cy, wf, wt)
    sid = data["stores"].set_index("store_key")["store_id"]
    lost_cat = lost[lost["category"] == cat]
    by_store = lost_cat.assign(store_id=lost_cat["store_key"].map(sid)).groupby(["store_id", "retail_year"])[
        ["est_lost_sales_eur", "est_lost_sales_upper_eur"]].sum().unstack("retail_year").fillna(0)
    by_store.columns = [f"{a}_{'py' if b == py else 'cy'}" for a, b in by_store.columns]
    by_store = by_store.reset_index()
    by_store["in_cluster"] = by_store["store_id"].isin(cluster)
    tests = [supplier_test(sku, top_sup, e["bootstrap_reps"], cfg["seed"], m)
             for m in ("oos_rate_change_pp", "lost_primary_change")]
    non_top = sku[sku["supplier_name"] != top_sup]
    tests_excl = supplier_test(sku[sku["product_id"] != sku.sort_values("lost_primary_change").iloc[-1]["product_id"]],
                               top_sup, e["bootstrap_reps"], cfg["seed"], "oos_rate_change_pp")
    tests_excl["variant"] = "excluding the SKU with the largest lost-sales increase"
    return {"category": cat, "top_supplier": top_sup, "kpis": category_kpis(data, cat, py, cy),
            "panel": panel, "est": est, "lost": lost,
            "totals_category": lost_totals(lost, py, cy, lost["category"] == cat),
            "totals_estate": lost_totals(lost, py, cy),
            "totals_top_supplier": lost_totals(lost, py, cy, (lost["category"] == cat) & (lost["supplier_name"] == top_sup)),
            "by_supplier_category": sup_cat, "by_supplier_all": sup_all, "sku": sku, "concentration": concentration(sku),
            "by_store": by_store, "episodes": ep, "episode_summary": episode_summary(ep),
            "recovery": (rec := recovery(panel, est, ep, e["recovery_weeks"])),
            "recovery_offset_eur": recovery_offset(rec, py, cy, full_week_only=True),
            "recovery_offset_all_eur": recovery_offset(rec, py, cy, full_week_only=False),
            "range_distribution": range_distribution(cells, data["stores"], cat, py, cy, cluster),
            "replenishment": replenishment(cells, cat),
            "supplier_tests": pd.DataFrame(tests + [tests_excl]),
            "timeline": weekly_timeline(cells, lost, cat, top_sup, py, cy),
            "backtest": D.lost_sales_backtest(panel, est, (py, cy), wf, wt),
            "other_suppliers_skus": int(non_top["product_id"].nunique())}
