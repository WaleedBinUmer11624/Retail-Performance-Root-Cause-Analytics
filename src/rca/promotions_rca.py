"""Home & Kitchen promotion investigation: three counterfactuals and their uncertainty.

M1  Category difference-in-differences inside the same store-weeks. For every store-week the YoY log change
    of Home & Kitchen sales is compared with the average YoY log change of the control categories in the
    same store and week. Store-week effects (traffic, including the store cluster, local events, seasonality
    that is common to categories, week alignment) cancel. delta = mean gap in the post-period minus the mean
    gap in the pre-period. It measures the H&K-specific change in H2, whatever caused it (promotions and any
    other H&K-specific factor), so it is an upper-bound style estimate for the promotion effect.
M2  Dose-response. Within H&K store-weeks, the same gap is regressed on the change in promotion coverage
    (share of ranged SKU-days on promotion) and the change in discount depth, with store fixed effects.
    The counterfactual sets both changes to zero. This isolates the part associated with the promotion
    pattern, but it is still an association across store-weeks, not an experiment.
M3  Event level (Phase 5 method, reused). Per store-SKU promotion event: incremental revenue against a
    pre-promotion baseline, minus the post-promotion dip, minus cannibalisation of non-promoted H&K SKUs
    in heavily promoted store-weeks. Net programme revenue per year; the counterfactual difference is the
    current programme's net contribution minus the prior programme's.
Uncertainty: store bootstrap for M1 and M2, variants in the sensitivity analysis, and the spread across
methods. None of these proves causality: they are quasi-experimental estimates under stated assumptions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics import diagnostics as D
from src.analytics.contribution import safe_div


def store_cat_week(data: dict, py: int, cy: int) -> pd.DataFrame:
    sid = data["stores"].set_index("store_key")["store_id"]
    s = data["store_category_week"].assign(store_id=lambda d: d["store_key"].map(sid))
    c = data["stock_cell_week"]
    cov = c.groupby(["store_key", "category", "retail_year", "retail_week"]).agg(
        ranged_cells=("product_key", "size"), promo_days=("promo_days", "sum"), in_stock=("is_in_stock", "mean")).reset_index()
    cov["promo_coverage"] = cov["promo_days"] / (7 * cov["ranged_cells"])
    s = s.merge(cov.drop(columns=["promo_days"]), on=["store_key", "category", "retail_year", "retail_week"], how="left")
    s["gross_margin"] = s["sales_revenue"] - s["cost_of_sales"]
    s["discount_depth"] = safe_div(s["discount_value"], s["gross_sales"])
    return s[s["retail_year"].isin([py, cy]) & s["retail_week"].between(1, 52)]


def yoy_panel(scw: pd.DataFrame, py: int, cy: int) -> pd.DataFrame:
    keys = ["store_id", "category", "retail_week"]
    vals = ["sales_revenue", "units_sold", "gross_margin", "gross_sales", "discount_value", "promo_coverage",
            "discount_depth", "in_stock", "transactions_with_category"]
    a = scw[scw["retail_year"] == cy].set_index(keys)[vals]
    b = scw[scw["retail_year"] == py].set_index(keys)[vals]
    m = a.join(b, lsuffix="_cy", rsuffix="_py", how="inner").reset_index()
    for v in ("sales_revenue", "units_sold", "gross_margin", "transactions_with_category"):
        ok = (m[f"{v}_cy"] > 0) & (m[f"{v}_py"] > 0)
        m[f"ly_{v}"] = np.where(ok, np.log(m[f"{v}_cy"].where(ok, 1) / m[f"{v}_py"].where(ok, 1)), np.nan)
    m["d_coverage"] = m["promo_coverage_cy"] - m["promo_coverage_py"]
    m["d_depth"] = m["discount_depth_cy"].fillna(0) - m["discount_depth_py"].fillna(0)
    m["d_in_stock"] = m["in_stock_cy"] - m["in_stock_py"]
    return m


def gaps(yp: pd.DataFrame, category: str, controls: list[str], outcome: str) -> pd.DataFrame:
    t = yp[yp["category"] == category].set_index(["store_id", "retail_week"])
    c = yp[yp["category"].isin(controls)].groupby(["store_id", "retail_week"])[outcome].mean()
    g = t[[outcome, "d_coverage", "d_depth", "d_in_stock", "sales_revenue_cy", "sales_revenue_py", "gross_margin_cy",
           "units_sold_cy"]].join(c.rename("control"), how="inner")
    g["gap"] = g[outcome] - g["control"]
    return g.dropna(subset=["gap"]).reset_index()


def m1_did(g: pd.DataFrame, pre, post) -> float:
    return float(g.loc[g["retail_week"].between(*post), "gap"].mean() - g.loc[g["retail_week"].between(*pre), "gap"].mean())


def eur_from_log(actual: pd.Series, delta: float) -> float:
    """Actual minus counterfactual, where counterfactual = actual x exp(-delta)."""
    return float((actual * (1 - np.exp(-delta))).sum())


def boot_by_store(g: pd.DataFrame, fn, reps: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    stores = np.array(sorted(g["store_id"].unique()))
    grp = {s: d for s, d in g.groupby("store_id")}
    vals = []
    for _ in range(reps):
        pick = rng.choice(stores, len(stores))
        vals.append(fn(pd.concat([grp[s] for s in pick], ignore_index=True)))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def m2_dose(g: pd.DataFrame, post, lags: int = 2) -> dict:
    """gap ~ change in promotion coverage (this week and `lags` previous weeks, to catch post-promotion dips)
    + change in discount depth + change in availability + store fixed effects. The counterfactual sets every
    promotion change to zero; the estimate is the sales that association attributes to the changed pattern."""
    x = g.sort_values(["store_id", "retail_week"]).copy()
    cov_cols = ["d_coverage"]
    for k in range(1, lags + 1):
        x[f"d_coverage_lag{k}"] = x.groupby("store_id")["d_coverage"].shift(k)
        cov_cols.append(f"d_coverage_lag{k}")
    cols = cov_cols + ["d_depth", "d_in_stock"]
    x = x.dropna(subset=cols + ["gap"])
    dm = x[cols + ["gap"]] - x.groupby("store_id")[cols + ["gap"]].transform("mean")
    X = dm[cols].to_numpy()
    y = dm["gap"].to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    r2 = 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum()
    b = dict(zip(cols, beta))
    p = x[x["retail_week"].between(*post)]
    promo_part = sum(b[c_] * p[c_] for c_ in cov_cols) + b["d_depth"] * p["d_depth"]
    effect = float((p["sales_revenue_cy"] * (1 - np.exp(-promo_part))).sum())
    return {**{f"beta_{k}": float(v) for k, v in b.items()}, "beta_coverage_total": float(sum(b[c_] for c_ in cov_cols)),
            "r2_within": float(r2), "effect_eur": effect,
            "mean_d_coverage_post": float(p["d_coverage"].mean()), "mean_d_depth_post": float(p["d_depth"].mean())}


def m4_price_accounting(scw: pd.DataFrame, category: str, py: int, cy: int, post, net_volume_log: float) -> dict:
    """If the discount rate had stayed at the prior-year rate on the same gross sales, and the extra promotions
    produced the net volume change measured by M1 (units, relative to control categories), how much revenue
    would the category have had? effect = actual - counterfactual."""
    x = scw[(scw["category"] == category) & scw["retail_week"].between(*post)]
    g = x.groupby("retail_year")[["gross_sales", "discount_value", "sales_revenue", "gross_margin"]].sum()
    rate_py = g.loc[py, "discount_value"] / g.loc[py, "gross_sales"]
    rate_cy = g.loc[cy, "discount_value"] / g.loc[cy, "gross_sales"]
    gross_cf = g.loc[cy, "gross_sales"] * np.exp(-net_volume_log)
    sales_cf = gross_cf * (1 - rate_py)
    return {"discount_rate_py": float(rate_py), "discount_rate_cy": float(rate_cy),
            "gross_sales_cy": float(g.loc[cy, "gross_sales"]), "counterfactual_sales": float(sales_cf),
            "effect_eur": float(g.loc[cy, "sales_revenue"] - sales_cf),
            "effect_eur_volume_held": float(-(rate_cy - rate_py) * g.loc[cy, "gross_sales"]),
            "margin_effect_eur_volume_held": float(-(rate_cy - rate_py) * g.loc[cy, "gross_sales"])}


def m3_events(data: dict, panel: D.Panel, est: dict, a_cfg: dict, category: str, py: int, cy: int, wf: int, wt: int,
              pre_weeks: int | None = None) -> dict:
    cfg = {"promotions": dict(a_cfg["promotions"])}
    if pre_weeks:
        cfg["promotions"]["pre_weeks"] = pre_weeks
    ev = data["promo_event_week"]
    ev = ev[ev["product_key"].isin(data["products"].loc[data["products"]["category"] == category, "product_key"])]
    agg, events = D.promotion_uplift(panel, est, ev, cfg, py, cy, wf, wt, data["products"])
    v = events[events["valid"]].copy()
    # how often does an event's pre-promotion baseline sit right after another promotion of the same store-SKU?
    ev_sorted = events.sort_values(["store_key", "product_key", "w_first"])
    prev_end = ev_sorted.groupby(["store_key", "product_key"])["w_last"].shift(1)
    gap_w = ev_sorted["w_first"] - prev_end
    ev_sorted["prior_promo_within_pre_window"] = gap_w.le(cfg["promotions"]["pre_weeks"] + cfg["promotions"]["post_weeks"])
    contam = ev_sorted[ev_sorted["valid"]].groupby("year")["prior_promo_within_pre_window"].mean()
    v["incremental_revenue"] = v["promo_period_revenue"] - v["baseline_units"] * v["baseline_price"]
    v["post_dip_revenue"] = (v["post_expected_units"] - v["post_units"]) * v["baseline_price"]
    rows = []
    for yr in (py, cy):
        g = v[v["year"] == yr]
        rows.append({"retail_year": yr, "events": len(g), "promo_period_revenue": g["promo_period_revenue"].sum(),
                     "baseline_revenue": (g["baseline_units"] * g["baseline_price"]).sum(),
                     "incremental_revenue": g["incremental_revenue"].sum(), "post_dip_revenue": g["post_dip_revenue"].sum(),
                     "discount_cost": g["promo_discount_cost"].sum(),
                     "incremental_promo_margin": g["incremental_promo_margin"].sum(),
                     "uplift_pct": 100 * safe_div(g["promo_units"].sum() - g["baseline_units"].sum(), g["baseline_units"].sum())})
    out = pd.DataFrame(rows)
    can = cannibalisation(panel, est, category, py, cy, wf, wt)
    out = out.merge(can, on="retail_year", how="left")
    out["net_programme_revenue"] = out["incremental_revenue"] - out["post_dip_revenue"] - out["cannibalised_revenue"]
    ny = out.set_index("retail_year")["net_programme_revenue"]
    return {"by_year": out, "effect_eur": float(ny[cy] - ny[py]), "events": v,
            "baseline_contamination_share": {int(k): float(x) for k, x in contam.items()}}


def cannibalisation(panel: D.Panel, est: dict, category: str, py: int, cy: int, wf: int, wt: int) -> pd.DataFrame:
    """Non-promoted, in-stock SKUs of the category: actual vs expected units in store-weeks by promotion intensity.
    Cannibalised revenue = shortfall of non-promoted SKUs in promoted store-weeks, relative to their ratio in
    store-weeks with no promotion in the category."""
    pidx = np.where(panel.category == category)[0]
    promoted = panel.promoted[:, pidx, :]
    n_promo = promoted.sum(axis=1)                                         # store x week
    exp = est["expected_units"][:, pidx, :]
    elig = panel.eligible[:, pidx, :] & ~np.isnan(exp)
    act = np.where(elig, panel.units_sold[:, pidx, :], 0.0)
    ex = np.where(elig, exp, 0.0)
    price = np.nan_to_num(est["price"][:, pidx, :], nan=0.0)
    rows = []
    for yr in (py, cy):
        wm = (panel.week_year == yr) & (panel.week_num >= wf) & (panel.week_num <= wt)
        a_sw, e_sw = act[:, :, wm].sum(axis=1), ex[:, :, wm].sum(axis=1)
        v_sw = (ex[:, :, wm] * price[:, :, wm]).sum(axis=1)
        npw = n_promo[:, wm]
        none = npw == 0
        base_ratio = a_sw[none].sum() / e_sw[none].sum() if e_sw[none].sum() else 1.0
        some = npw > 0
        ratio_promo = a_sw[some].sum() / e_sw[some].sum() if e_sw[some].sum() else np.nan
        shortfall = max(0.0, base_ratio - ratio_promo) if not np.isnan(ratio_promo) else 0.0
        rows.append({"retail_year": yr, "nonpromo_ratio_no_promo_weeks": float(base_ratio),
                     "nonpromo_ratio_promo_weeks": float(ratio_promo), "cannibalised_revenue": float(shortfall * v_sw[some].sum()),
                     "store_weeks_with_promo_share": float(some.mean())})
    return pd.DataFrame(rows)


def investigate(data: dict, cfg: dict, a_cfg: dict, panel: D.Panel, est: dict, py: int, cy: int, wf: int, wt: int,
                cluster: list[str]) -> dict:
    c = cfg["promotions"]
    cat = c["category"]
    pre, post = tuple(c["pre_weeks"]), tuple(c["post_weeks"])
    scw = store_cat_week(data, py, cy)
    yp = yoy_panel(scw, py, cy)
    g = gaps(yp, cat, c["control_categories"], "ly_sales_revenue")
    gu = gaps(yp, cat, c["control_categories"], "ly_units_sold")
    gm = gaps(yp, cat, c["control_categories"], "ly_gross_margin")
    d_sales = m1_did(g, pre, post)
    actual_post = g[g["retail_week"].between(*post)]
    e_sales = eur_from_log(actual_post["sales_revenue_cy"], d_sales)
    ci_log = boot_by_store(g, lambda x: m1_did(x, pre, post), c["bootstrap_reps"], cfg["seed"])
    ci_eur = tuple(eur_from_log(actual_post["sales_revenue_cy"], v) for v in ci_log)
    d_units = m1_did(gu, pre, post)
    ci_units = boot_by_store(gu, lambda x: m1_did(x, pre, post), c["bootstrap_reps"], cfg["seed"])
    d_gm = m1_did(gm, pre, post)
    gm_post = gm[gm["retail_week"].between(*post)]
    e_gm_logdid = eur_from_log(gm_post["gross_margin_cy"], d_gm)
    # consistent margin effect: revenue effect minus the cost saved by the relative unit change (cost follows units)
    cost_post = float((actual_post["sales_revenue_cy"] - actual_post["gross_margin_cy"]).sum())
    e_gm = e_sales - cost_post * (1 - np.exp(-d_units))
    event_study = g.groupby("retail_week")["gap"].mean().rename("gap_sales").to_frame().join(
        gu.groupby("retail_week")["gap"].mean().rename("gap_units"))
    by_store = []
    for s, x in actual_post.groupby("store_id"):
        by_store.append({"store_id": s, "in_cluster": s in cluster, "m1_effect_eur": eur_from_log(x["sales_revenue_cy"], d_sales)})
    m2 = m2_dose(g, post)
    m2_ci = boot_by_store(g, lambda x: m2_dose(x, post)["effect_eur"], c["bootstrap_reps"], cfg["seed"])
    m3 = m3_events(data, panel, est, a_cfg, cat, py, cy, wf, wt)
    m4 = m4_price_accounting(scw, cat, py, cy, post, d_units)
    m4_lo = m4_price_accounting(scw, cat, py, cy, post, ci_units[0])
    m4_hi = m4_price_accounting(scw, cat, py, cy, post, ci_units[1])
    m4["ci_eur"] = tuple(sorted((m4_lo["effect_eur"], m4_hi["effect_eur"])))
    by_store_m4 = []
    for s_, x in scw[(scw["category"] == cat) & scw["retail_week"].between(*post)].groupby("store_id"):
        gy = x.groupby("retail_year")[["gross_sales", "discount_value"]].sum()
        if py in gy.index and cy in gy.index:
            by_store_m4.append({"store_id": s_, "m4_effect_eur_volume_held":
                                -(gy.loc[cy, "discount_value"] / gy.loc[cy, "gross_sales"] - m4["discount_rate_py"]) *
                                gy.loc[cy, "gross_sales"]})
    weekly = actual_post.groupby("retail_week")[["sales_revenue_cy", "sales_revenue_py"]].sum()
    weekly["counterfactual_m1"] = weekly["sales_revenue_cy"] * np.exp(-d_sales)
    intensity = yp[yp["category"] == cat].groupby("retail_week")[["promo_coverage_cy", "promo_coverage_py", "discount_depth_cy",
                                                                   "discount_depth_py"]].mean()
    weekly = weekly.join(intensity, how="left").reset_index()
    pre_trend = np.polyfit(np.arange(len(event_study.loc[pre[0]:pre[1]])),
                           event_study.loc[pre[0]:pre[1], "gap_sales"].to_numpy(), 1)[0]
    return {"category": cat, "controls": c["control_categories"], "panel": yp, "gaps": g,
            "m1": {"delta_log_sales": d_sales, "delta_pct_sales": 100 * (np.exp(d_sales) - 1), "effect_eur": e_sales,
                   "ci_log": ci_log, "ci_eur": ci_eur, "delta_log_units": d_units, "delta_pct_units": 100 * (np.exp(d_units) - 1),
                   "ci_log_units": ci_units,
                   "price_component_log": d_sales - d_units, "delta_log_margin": d_gm, "margin_effect_eur": e_gm, "margin_effect_eur_log_did": e_gm_logdid,
                   "pre_trend_slope_per_week": float(pre_trend)},
            "m2": {**m2, "ci_eur": m2_ci}, "m3": m3, "m4": m4, "event_study": event_study.reset_index(),
            "by_store": pd.DataFrame(by_store).merge(pd.DataFrame(by_store_m4), on="store_id", how="left"), "weekly": weekly}
