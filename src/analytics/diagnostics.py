"""Diagnostics: products, returns, availability (with Estimated Lost Sales), promotions, targets, associations.

Nothing here asserts a cause. Each function measures a change or an association; the evidence module
decides how strong a claim the numbers support (BRD 6.2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .contribution import safe_div, yoy_pct


# ============================================================================= helpers
def wide_by_year(df: pd.DataFrame, keys: list[str], values: list[str], py: int, cy: int) -> pd.DataFrame:
    """Long (key, retail_year) rows -> one row per key with <value>_py / <value>_cy (missing year = 0)."""
    g = df[df["retail_year"].isin([py, cy])].groupby(keys + ["retail_year"], dropna=False)[values].sum().reset_index()
    a = g[g["retail_year"] == py].set_index(keys)[values].add_suffix("_py")
    b = g[g["retail_year"] == cy].set_index(keys)[values].add_suffix("_cy")
    out = a.join(b, how="outer")
    return out.fillna(0.0).reset_index()


def association(x, y, label_x: str, label_y: str, level: str, alpha: float) -> dict:
    """Pearson and Spearman association. Always labelled 'Statistical association' (never causation)."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 3 or np.std(x) == 0 or np.std(y) == 0:
        pr = sr = pp = sp = np.nan
    else:
        pr, pp = stats.pearsonr(x, y)
        sr, sp = stats.spearmanr(x, y)
    return {"level": level, "x": label_x, "y": label_y, "n": n, "pearson_r": pr, "pearson_p": pp,
            "spearman_rho": sr, "spearman_p": sp,
            "significant_at_alpha": bool(pp < alpha) if not np.isnan(pp) else False,
            "evidence_label": "Statistical association",
            "note": "Correlation across segments; does not establish that one causes the other."}


# ============================================================================= products
def product_drilldown(prod: pd.DataFrame, cat_contrib: pd.DataFrame, lost_by_product: pd.DataFrame,
                      py: int, cy: int, cfg: dict, total_change: float) -> tuple[pd.DataFrame, list[str]]:
    """Products are examined only inside categories carrying a material share of the estate decline."""
    c = cfg["products"]
    material = cat_contrib[(cat_contrib["share_of_change"] >= c["material_category_share"]) &
                           (cat_contrib["net_revenue_change"] < 0)]["category"].tolist()
    vals = ["sales_revenue", "units_sold", "returns_value", "returned_units", "promo_sales_revenue",
            "discount_value", "ranged_cells", "in_stock_cells", "cost_of_sales", "transactions"]
    w = wide_by_year(prod, ["product_key", "product_id", "product_name", "category", "subcategory", "supplier_name"],
                     vals, py, cy)
    w = w[w["category"].isin(material)].copy()
    w["net_revenue_py"] = w["sales_revenue_py"] - w["returns_value_py"]
    w["net_revenue_cy"] = w["sales_revenue_cy"] - w["returns_value_cy"]
    w["net_revenue_change"] = w["net_revenue_cy"] - w["net_revenue_py"]
    w["net_revenue_yoy_pct"] = yoy_pct(w["net_revenue_cy"], w["net_revenue_py"])
    w["share_of_estate_change"] = w["net_revenue_change"] / total_change
    w["availability_py"] = safe_div(w["in_stock_cells_py"], w["ranged_cells_py"])
    w["availability_cy"] = safe_div(w["in_stock_cells_cy"], w["ranged_cells_cy"])
    w["availability_change_pp"] = 100 * (w["availability_cy"] - w["availability_py"])
    w["return_rate_value_py"] = safe_div(w["returns_value_py"], w["sales_revenue_py"])
    w["return_rate_value_cy"] = safe_div(w["returns_value_cy"], w["sales_revenue_cy"])
    w["return_rate_change_pp"] = 100 * (w["return_rate_value_cy"] - w["return_rate_value_py"])
    w["returns_change"] = w["returns_value_cy"] - w["returns_value_py"]
    w["promo_share_py"] = safe_div(w["promo_sales_revenue_py"], w["sales_revenue_py"])
    w["promo_share_cy"] = safe_div(w["promo_sales_revenue_cy"], w["sales_revenue_cy"])
    w["promo_share_change_pp"] = 100 * (w["promo_share_cy"] - w["promo_share_py"])
    w["asp_py"] = safe_div(w["sales_revenue_py"], w["units_sold_py"])
    w["asp_cy"] = safe_div(w["sales_revenue_cy"], w["units_sold_cy"])
    w = w.merge(lost_by_product, on="product_key", how="left")
    for col in ("est_lost_sales_py", "est_lost_sales_cy"):
        w[col] = w[col].fillna(0.0)
    w["est_lost_sales_change"] = w["est_lost_sales_cy"] - w["est_lost_sales_py"]

    # high-impact: the smallest set of decliners covering the configured share of the category's gross decline
    w["flag_high_impact"] = False
    for cat, g in w.groupby("category"):
        dec = g[g["net_revenue_change"] < 0].sort_values(["net_revenue_change", "product_id"])
        if dec.empty:
            continue
        cum = dec["net_revenue_change"].cumsum() / dec["net_revenue_change"].sum()
        n = int(min(c["high_impact_max"], (cum < c["high_impact_cover"]).sum() + 1))
        w.loc[dec.index[:n], "flag_high_impact"] = True
    w["flag_high_pct_low_impact"] = (w["net_revenue_yoy_pct"] <= c["high_pct_min_decline_pct"]) & \
                                    (w["net_revenue_change"].abs() < c["high_pct_max_abs_change"])
    w["flag_availability_affected"] = (w["availability_change_pp"] <= -c["availability_drop_pp"]) & \
                                      (w["est_lost_sales_change"] > 0)
    w["flag_returns_affected"] = (w["return_rate_change_pp"] >= c["returns_rate_rise_pp"]) & \
                                 (w["returns_change"] >= c["returns_min_change_eur"])
    w["flag_promotion_change"] = w["promo_share_change_pp"].abs() >= c["promo_share_change_pp"]
    flags = [f for f in w.columns if f.startswith("flag_")]
    w["flag_list"] = w[flags].apply(lambda r: ";".join(f.replace("flag_", "") for f in flags if r[f]), axis=1)
    keep = w[w[flags].any(axis=1)].copy()
    keep = keep.sort_values(["category", "net_revenue_change", "product_id"], kind="mergesort").reset_index(drop=True)
    return keep, material


# ============================================================================= returns
def _returns_row(level, key, sub, rv0, rv1, s0, s1, ru0, ru1, u0, u1, total_py, total_ret_change):
    rr0, rr1 = safe_div(rv0, s0), safe_div(rv1, s1)
    rate_eff = (rr1 - rr0) * (s0 + s1) / 2 if not (np.isnan(rr0) or np.isnan(rr1)) else np.nan
    vol_eff = (s1 - s0) * (rr0 + rr1) / 2 if not (np.isnan(rr0) or np.isnan(rr1)) else np.nan
    return {"level": level, "key": key, "sub_key": sub,
            "returns_value_py": rv0, "returns_value_cy": rv1, "returns_change": rv1 - rv0,
            "returns_yoy_pct": yoy_pct(rv1, rv0),
            "sales_revenue_py": s0, "sales_revenue_cy": s1,
            "return_rate_value_py": rr0, "return_rate_value_cy": rr1, "return_rate_value_change_pp": 100 * (rr1 - rr0),
            "returned_units_py": ru0, "returned_units_cy": ru1, "units_sold_py": u0, "units_sold_cy": u1,
            "return_rate_units_py": safe_div(ru0, u0), "return_rate_units_cy": safe_div(ru1, u1),
            "return_rate_units_change_pp": 100 * (safe_div(ru1, u1) - safe_div(ru0, u0)),
            "returns_rate_effect": rate_eff, "returns_volume_effect": vol_eff,
            "contribution_pp": -100.0 * (rv1 - rv0) / total_py,
            "share_of_returns_change": (rv1 - rv0) / total_ret_change if total_ret_change else np.nan}


def returns_diagnostics(weeks: pd.DataFrame, store_cat: pd.DataFrame, reason: pd.DataFrame, product: pd.DataFrame,
                        py: int, cy: int, total_py: float, cfg: dict) -> tuple[pd.DataFrame, dict]:
    sc = wide_by_year(store_cat, ["store_id", "store_name", "region", "store_format", "category"],
                      ["sales_revenue", "units_sold", "returns_value", "returned_units", "return_lines"], py, cy)
    T = lambda col: float(sc[col].sum())  # noqa: E731
    ret_change = T("returns_value_cy") - T("returns_value_py")
    rows = [_returns_row("Estate", "Brightwater estate", "", T("returns_value_py"), T("returns_value_cy"),
                         T("sales_revenue_py"), T("sales_revenue_cy"), T("returned_units_py"), T("returned_units_cy"),
                         T("units_sold_py"), T("units_sold_cy"), total_py, ret_change)]
    for r in weeks.sort_values("retail_week").itertuples():
        rows.append(_returns_row("Week", f"W{int(r.retail_week):02d}", "", r.returns_value_py, r.returns_value_cy,
                                 r.sales_revenue_py, r.sales_revenue_cy, r.returned_units_py, r.returned_units_cy,
                                 r.units_sold_py, r.units_sold_cy, total_py, ret_change))
    for level, keys in (("Store", ["store_id"]), ("Region", ["region"]), ("Category", ["category"]),
                        ("Store x Category", ["store_id", "category"])):
        g = sc.groupby(keys, as_index=False)[[c for c in sc.columns if c.endswith(("_py", "_cy"))]].sum()
        for r in g.itertuples(index=False):
            d = r._asdict()
            key = d[keys[0]]
            sub = d[keys[1]] if len(keys) > 1 else ""
            rows.append(_returns_row(level, key, sub, d["returns_value_py"], d["returns_value_cy"], d["sales_revenue_py"],
                                     d["sales_revenue_cy"], d["returned_units_py"], d["returned_units_cy"],
                                     d["units_sold_py"], d["units_sold_cy"], total_py, ret_change))
    rw = wide_by_year(reason, ["return_reason"], ["returns_value", "returned_units", "return_lines"], py, cy)
    for r in rw.sort_values("return_reason").itertuples():
        rows.append(_returns_row("Recorded reason", r.return_reason, "", r.returns_value_py, r.returns_value_cy,
                                 T("sales_revenue_py"), T("sales_revenue_cy"), r.returned_units_py, r.returned_units_cy,
                                 T("units_sold_py"), T("units_sold_cy"), total_py, ret_change))
    crw = wide_by_year(reason, ["category", "return_reason"], ["returns_value", "returned_units"], py, cy)
    cat_sales = sc.groupby("category")[["sales_revenue_py", "sales_revenue_cy", "units_sold_py", "units_sold_cy"]].sum()
    for r in crw.sort_values(["category", "return_reason"]).itertuples():
        cs = cat_sales.loc[r.category]
        rows.append(_returns_row("Category x Reason", r.category, r.return_reason, r.returns_value_py, r.returns_value_cy,
                                 cs["sales_revenue_py"], cs["sales_revenue_cy"], r.returned_units_py, r.returned_units_cy,
                                 cs["units_sold_py"], cs["units_sold_cy"], total_py, ret_change))
    pw = wide_by_year(product, ["product_id", "product_name", "category"],
                      ["returns_value", "sales_revenue", "returned_units", "units_sold"], py, cy)
    pw["returns_change"] = pw["returns_value_cy"] - pw["returns_value_py"]
    material = pw[pw["returns_change"].abs() >= cfg["products"]["returns_min_change_eur"]]
    for r in material.sort_values(["returns_change", "product_id"], ascending=[False, True]).itertuples():
        rows.append(_returns_row("Product", r.product_id, f"{r.product_name} ({r.category})", r.returns_value_py,
                                 r.returns_value_cy, r.sales_revenue_py, r.sales_revenue_cy, r.returned_units_py,
                                 r.returned_units_cy, r.units_sold_py, r.units_sold_cy, total_py, ret_change))
    out = pd.DataFrame(rows)

    # unusual concentrations among store x category cells
    cells = out[out["level"] == "Store x Category"].copy()
    rc = cells["return_rate_value_change_pp"]
    z = (rc - rc.mean()) / rc.std(ddof=1)
    out["rate_change_zscore"] = np.nan
    out.loc[cells.index, "rate_change_zscore"] = z
    share_ok = True
    out["is_concentration"] = False
    gross_up = float(cells.loc[cells["returns_change"] > 0, "returns_change"].sum())
    out["share_of_gross_returns_increase"] = np.nan
    out.loc[cells.index, "share_of_gross_returns_increase"] = cells["returns_change"] / gross_up if gross_up else np.nan
    flag = (z >= cfg["returns"]["zscore"])
    if share_ok and gross_up:
        flag = flag | (cells["returns_change"] / gross_up >= cfg["returns"]["concentration_share"])
    out.loc[cells.index[flag.to_numpy()], "is_concentration"] = True
    conc = out[out["is_concentration"]]
    summary = {"returns_change": ret_change, "gross_increase_store_category": gross_up,
               "concentration_cells": len(conc), "concentration_change": float(conc["returns_change"].sum()),
               "concentration_share_of_gross_increase": float(conc["returns_change"].sum() / gross_up) if gross_up else np.nan,
               "concentration_cells_list": ", ".join(f"{r.key} {r.sub_key}" for r in conc.itertuples())}
    return out, summary


# ============================================================================= availability / lost sales
class Panel:
    """store x product x week arrays built from diag.v_stock_cell_week (ranged cells only)."""

    FIELDS = ("units_sold", "sales_revenue", "promo_units_sold", "discount_value", "cost_of_sales", "promo_days",
              "is_in_stock", "opening_stock", "received_qty", "closing_stock")

    def __init__(self, cells: pd.DataFrame, weeks: pd.DataFrame):
        weeks = weeks.sort_values("retail_week_key").reset_index(drop=True)
        self.week_keys = weeks["retail_week_key"].to_numpy()
        self.week_year = weeks["retail_year"].to_numpy()
        self.week_num = weeks["retail_week"].to_numpy()
        self.stores = np.sort(cells["store_key"].unique())
        self.products = np.sort(cells["product_key"].unique())
        self.s_idx = {k: i for i, k in enumerate(self.stores)}
        self.p_idx = {k: i for i, k in enumerate(self.products)}
        self.w_idx = {k: i for i, k in enumerate(self.week_keys)}
        cat = cells.drop_duplicates("product_key").set_index("product_key")["category"]
        self.category = cat.reindex(self.products).to_numpy()
        self.categories = np.sort(pd.unique(self.category))
        shape = (len(self.stores), len(self.products), len(self.week_keys))
        si = cells["store_key"].map(self.s_idx).to_numpy()
        pi = cells["product_key"].map(self.p_idx).to_numpy()
        wi = cells["retail_week_key"].map(self.w_idx).to_numpy()
        if np.isnan(wi.astype(float)).any():
            raise ValueError("stock cell week not in the week list")
        self.ranged = np.zeros(shape, dtype=bool)
        self.ranged[si, pi, wi] = True
        for f in self.FIELDS:
            a = np.zeros(shape, dtype=float)
            a[si, pi, wi] = cells[f].astype(float).to_numpy()
            setattr(self, f, a)
        self.in_stock = self.ranged & (self.is_in_stock > 0)
        self.stock_out = self.ranged & ~self.in_stock
        self.promoted = (self.promo_days > 0) | (self.promo_units_sold > 0)
        self.eligible = self.in_stock & ~self.promoted       # baseline weeks: in stock, not promoted

    def seasonal_index(self) -> np.ndarray:
        """category x week: mean units per eligible cell (estate). Returned expanded to product x week."""
        p_cat = np.searchsorted(self.categories, self.category)
        n_c, n_w = len(self.categories), len(self.week_keys)
        num = np.zeros((n_c, n_w))
        den = np.zeros((n_c, n_w))
        e = self.eligible
        units = np.where(e, self.units_sold, 0.0).sum(axis=0)          # product x week
        cnt = e.sum(axis=0).astype(float)
        np.add.at(num, p_cat, units)
        np.add.at(den, p_cat, cnt)
        idx = safe_div(num, den)
        # a category-week with no eligible cell borrows the category mean (no information that week)
        cat_mean = np.nanmean(np.where(idx > 0, idx, np.nan), axis=1, keepdims=True)
        idx = np.where(np.isnan(idx) | (idx <= 0), cat_mean, idx)
        self.cat_index = idx
        return idx[p_cat]                                                 # product x week


def _shift(a: np.ndarray, k: int) -> np.ndarray:
    """Value at week w+k placed at w (zeros outside the range)."""
    out = np.zeros_like(a)
    if k > 0:
        out[..., :-k] = a[..., k:]
    elif k < 0:
        out[..., -k:] = a[..., :k]
    else:
        out = a.copy()
    return out


def estimate_expected(panel: Panel, windows: list[int], min_hist: int) -> dict:
    """Expected weekly units and non-promoted price for every cell, from neighbouring eligible weeks.

    For cell (s, p, w): baseline = mean of deseasonalised units over eligible weeks w-K..w-1, w+1..w+K of the
    same store-SKU (the week itself is never used). K is the narrowest window in `windows` giving at least
    `min_hist` eligible weeks. Expected units = baseline x category seasonal index of week w.
    Price = non-promoted revenue / units over the same weeks.
    """
    sidx = panel.seasonal_index()[None, :, :]
    e = panel.eligible.astype(float)
    z = np.where(panel.eligible, panel.units_sold / sidx, 0.0)
    v = np.where(panel.eligible, panel.sales_revenue, 0.0)
    u = np.where(panel.eligible, panel.units_sold, 0.0)
    shape = e.shape
    baseline = np.full(shape, np.nan)
    price = np.full(shape, np.nan)
    window_used = np.zeros(shape, dtype=int)
    n_used = np.zeros(shape, dtype=int)
    sz, sn, sv, su = (np.zeros(shape) for _ in range(4))
    prev = 0
    for K in sorted(windows):
        for k in range(prev + 1, K + 1):
            for off in (k, -k):
                sz += _shift(z, off)
                sn += _shift(e, off)
                sv += _shift(v, off)
                su += _shift(u, off)
        prev = K
        take = np.isnan(baseline) & (sn >= min_hist)
        baseline[take] = sz[take] / sn[take]
        price[take] = safe_div(sv[take], su[take])
        window_used[take] = K
        n_used[take] = sn[take].astype(int)
    expected = baseline * sidx
    return {"expected_units": expected, "price": price, "window": window_used, "n_weeks": n_used,
            "seasonal_index": sidx}


def lost_sales_cells(panel: Panel, est: dict, years: tuple[int, int], week_from: int, week_to: int) -> pd.DataFrame:
    """Stock-out store-SKU-weeks in the compared H2 weeks with their Estimated Lost Sales (ESTIMATE).

    Stock-out weeks (closing stock 0) are of three kinds, visible from the weekly snapshot:
      full_week  opening stock 0 and nothing received: no stock at any point, so sales must be 0
      restocked  opening stock 0, stock received during the week
      sold_out   opening stock > 0, sold out before the snapshot
    est_lost_sales_eur (the PRIMARY estimate) counts full_week cells only: the loss is expected sales,
    because actual sales are 0 by mechanism. For partial weeks the snapshot cannot say how long the SKU
    was out, and per-week (expected - actual) is dominated by noise, so they are kept as an UPPER bound
    (est_lost_sales_upper_eur = max(expected - actual, 0) x price for every stock-out week, the literal
    BR-05 formula) and are not used as evidence."""
    in_h2 = np.isin(panel.week_year, years) & (panel.week_num >= week_from) & (panel.week_num <= week_to)
    mask = panel.stock_out & in_h2[None, None, :]
    s, p, w = np.nonzero(mask)
    exp_u = est["expected_units"][s, p, w]
    act = panel.units_sold[s, p, w]
    opening, received = panel.opening_stock[s, p, w], panel.received_qty[s, p, w]
    kind = np.where((opening <= 0) & (received <= 0), "full_week", np.where(opening <= 0, "restocked", "sold_out"))
    has = ~np.isnan(exp_u)
    price = np.nan_to_num(est["price"][s, p, w], nan=0.0)
    upper_u = np.where(has, np.maximum(exp_u - act, 0.0), np.nan)
    upper_v = np.where(has, upper_u * price, np.nan)
    prim_u = np.where(has, np.where(kind == "full_week", upper_u, 0.0), np.nan)
    prim_v = np.where(has, prim_u * price, np.nan)
    return pd.DataFrame({
        "store_key": panel.stores[s], "product_key": panel.products[p], "category": panel.category[p],
        "retail_week_key": panel.week_keys[w], "retail_year": panel.week_year[w], "retail_week": panel.week_num[w],
        "stockout_type": kind, "opening_stock": opening, "received_qty": received,
        "promoted_week": panel.promoted[s, p, w], "actual_units": act, "actual_revenue": panel.sales_revenue[s, p, w],
        "expected_units": exp_u, "baseline_price": est["price"][s, p, w], "baseline_window_weeks": est["window"][s, p, w],
        "baseline_weeks_used": est["n_weeks"][s, p, w], "has_estimate": has,
        "est_lost_units": prim_u, "est_lost_sales_eur": prim_v,
        "est_lost_units_upper": upper_u, "est_lost_sales_upper_eur": upper_v})


def lost_sales_backtest(panel: Panel, est: dict, years: tuple[int, int], week_from: int, week_to: int) -> dict:
    """Apply the estimator to in-stock, non-promoted H2 weeks, where true sales are known.

    bias_ratio tests the expected level (what the primary, full-week estimate uses). The clipped
    per-week error, max(expected - actual, 0) x price, measures how much 'lost sales' the upper-bound
    formula would report where nothing was lost: the noise floor for partial stock-out weeks."""
    in_h2 = np.isin(panel.week_year, years) & (panel.week_num >= week_from) & (panel.week_num <= week_to)
    m = panel.eligible & in_h2[None, None, :] & ~np.isnan(est["expected_units"])
    act, exp = panel.units_sold[m], est["expected_units"][m]
    price = np.nan_to_num(est["price"][m], nan=0.0)
    clipped = np.maximum(exp - act, 0.0) * price
    s, p, w = np.nonzero(m)
    g = pd.DataFrame({"s": s, "c": panel.category[p], "w": w, "a": act, "e": exp}).groupby(["s", "c", "w"])[["a", "e"]].sum()
    return {"cells": int(m.sum()), "actual_units": float(act.sum()), "expected_units": float(exp.sum()),
            "bias_ratio": float(act.sum() / exp.sum()) if exp.sum() else np.nan,
            "wape_store_category_week": float((g["a"] - g["e"]).abs().sum() / g["a"].sum()) if g["a"].sum() else np.nan,
            "clipped_false_lost_eur_per_cell": float(clipped.mean()) if len(clipped) else np.nan}


def availability_diagnostics(sc_avail: pd.DataFrame, store_contrib: pd.DataFrame, cat_contrib: pd.DataFrame,
                             lost: pd.DataFrame, weeks_avail: pd.DataFrame, store_cat_sales: pd.DataFrame,
                             stores: pd.DataFrame, products: pd.DataFrame, py: int, cy: int,
                             week_from: int, week_to: int, alpha: float, supplier_avail: pd.DataFrame | None = None,
                             product_supplier: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    lost = lost.merge(stores[["store_key", "store_id"]], on="store_key", how="left")
    ls = lost.assign(v=lost["est_lost_sales_eur"].fillna(0.0), vu=lost["est_lost_sales_upper_eur"].fillna(0.0))

    def lost_by(keys, col="v"):
        g = ls.groupby(keys + ["retail_year"])[col].sum().unstack("retail_year")
        g = g.reindex(columns=[py, cy]).fillna(0.0)
        g.columns = ["est_lost_sales_py", "est_lost_sales_cy"]
        return g

    def cov_by(keys):
        g = lost.groupby(keys)["has_estimate"].mean()
        return g.rename("stockout_cells_with_estimate_share")

    av = wide_by_year(sc_avail, ["store_id", "region", "store_format", "category"], ["ranged_cells", "in_stock_cells"], py, cy)
    rows = []

    def add(level, key, sub, g, lost_row, net_py=np.nan, net_cy=np.nan, cov=np.nan):
        a0 = safe_div(g["in_stock_cells_py"], g["ranged_cells_py"])
        a1 = safe_div(g["in_stock_cells_cy"], g["ranged_cells_cy"])
        l0, l1 = (lost_row if lost_row is not None else (0.0, 0.0))
        rows.append({"level": level, "key": key, "sub_key": sub,
                     "ranged_cells_py": g["ranged_cells_py"], "ranged_cells_cy": g["ranged_cells_cy"],
                     "stockout_cells_py": g["ranged_cells_py"] - g["in_stock_cells_py"],
                     "stockout_cells_cy": g["ranged_cells_cy"] - g["in_stock_cells_cy"],
                     "availability_py": a0, "availability_cy": a1, "availability_change_pp": 100 * (a1 - a0),
                     "stockout_rate_py": 1 - a0, "stockout_rate_cy": 1 - a1,
                     "est_lost_sales_py_ESTIMATE": l0, "est_lost_sales_cy_ESTIMATE": l1,
                     "est_lost_sales_change_ESTIMATE": l1 - l0,
                     "stockout_cells_with_estimate_share": cov,
                     "net_revenue_py": net_py, "net_revenue_cy": net_cy,
                     "net_revenue_change": net_cy - net_py if not np.isnan(net_py) else np.nan,
                     "net_revenue_yoy_pct": yoy_pct(net_cy, net_py) if not np.isnan(net_py) else np.nan})

    est = av[[c for c in av.columns if c.endswith(("_py", "_cy"))]].sum()
    lt = ls.groupby("retail_year")["v"].sum().reindex([py, cy]).fillna(0.0)
    ltu = ls.groupby("retail_year")["vu"].sum().reindex([py, cy]).fillna(0.0)
    add("Estate", "Brightwater estate", "", est, (lt[py], lt[cy]),
        float(store_contrib["net_revenue_py"].sum()), float(store_contrib["net_revenue_cy"].sum()),
        float(lost["has_estimate"].mean()))
    sl, sc_ = lost_by(["store_id"]), cov_by(["store_id"])
    sn = store_contrib.set_index("segment_name")
    for sid, g in av.groupby("store_id"):
        gs = g[[c for c in g.columns if c.endswith(("_py", "_cy"))]].sum()
        lr = tuple(sl.loc[sid]) if sid in sl.index else (0.0, 0.0)
        add("Store", sid, "", gs, lr, sn.loc[sid, "net_revenue_py"], sn.loc[sid, "net_revenue_cy"], sc_.get(sid, np.nan))
    cl, cc = lost_by(["category"]), cov_by(["category"])
    cn = cat_contrib.set_index("category")
    for cat, g in av.groupby("category"):
        gs = g[[c for c in g.columns if c.endswith(("_py", "_cy"))]].sum()
        lr = tuple(cl.loc[cat]) if cat in cl.index else (0.0, 0.0)
        add("Category", cat, "", gs, lr, cn.loc[cat, "net_revenue_py"], cn.loc[cat, "net_revenue_cy"], cc.get(cat, np.nan))
    scl, scc = lost_by(["store_id", "category"]), cov_by(["store_id", "category"])
    scs = wide_by_year(store_cat_sales, ["store_id", "category"], ["sales_revenue", "returns_value"], py, cy).set_index(
        ["store_id", "category"])
    for r in av.itertuples(index=False):
        g = pd.Series(r._asdict())
        k = (r.store_id, r.category)
        lr = tuple(scl.loc[k]) if k in scl.index else (0.0, 0.0)
        npy = scs.loc[k, "sales_revenue_py"] - scs.loc[k, "returns_value_py"] if k in scs.index else np.nan
        ncy = scs.loc[k, "sales_revenue_cy"] - scs.loc[k, "returns_value_cy"] if k in scs.index else np.nan
        add("Store x Category", r.store_id, r.category, g, lr, npy, ncy, scc.get(k, np.nan))
    # weekly estate availability in the compared weeks
    wa = weeks_avail[(weeks_avail["retail_week"] >= week_from) & (weeks_avail["retail_week"] <= week_to)]
    ww = wide_by_year(wa, ["retail_week"], ["ranged_cells", "in_stock_cells"], py, cy)
    wl = lost_by(["retail_week"])
    for r in ww.sort_values("retail_week").itertuples(index=False):
        g = pd.Series(r._asdict())
        add("Week", f"W{int(r.retail_week):02d}", "", g, tuple(wl.loc[r.retail_week]) if r.retail_week in wl.index else (0, 0))
    if supplier_avail is not None:
        sw = wide_by_year(supplier_avail, ["supplier_name", "category"], ["ranged_cells", "in_stock_cells"], py, cy)
        lsup = ls.merge(product_supplier[["product_key", "supplier_name"]], on="product_key", how="left")
        lsup = lsup.groupby(["supplier_name", "category", "retail_year"])["v"].sum().unstack("retail_year").reindex(
            columns=[py, cy]).fillna(0.0)
        for r in sw.sort_values(["category", "supplier_name"]).itertuples(index=False):
            g = pd.Series(r._asdict())
            k = (r.supplier_name, r.category)
            add("Supplier x Category", r.supplier_name, r.category, g, tuple(lsup.loc[k]) if k in lsup.index else (0.0, 0.0))
    out = pd.DataFrame(rows)

    # products most affected (by increase in estimated lost sales)
    pl = lost_by(["product_key"])
    pl["est_lost_sales_change"] = pl["est_lost_sales_cy"] - pl["est_lost_sales_py"]
    top = pl.sort_values(["est_lost_sales_change"], ascending=False).head(15).reset_index()
    top = top.merge(products[["product_key", "product_id", "product_name", "category"]], on="product_key", how="left")
    prow = []
    for r in top.itertuples():
        prow.append({"level": "Product (top 15 by increase in estimated lost sales)", "key": r.product_id,
                     "sub_key": f"{r.product_name} ({r.category})",
                     "est_lost_sales_py_ESTIMATE": r.est_lost_sales_py, "est_lost_sales_cy_ESTIMATE": r.est_lost_sales_cy,
                     "est_lost_sales_change_ESTIMATE": r.est_lost_sales_change})
    out = pd.concat([out, pd.DataFrame(prow)], ignore_index=True)

    assoc = []
    st = out[out["level"] == "Store"]
    assoc.append(association(st["availability_change_pp"], st["net_revenue_yoy_pct"], "availability change (pp)",
                             "net revenue YoY %", "Store", alpha))
    ca = out[(out["level"] == "Category") & (out["key"] != "Unknown")]
    assoc.append(association(ca["availability_change_pp"], ca["net_revenue_yoy_pct"], "availability change (pp)",
                             "net revenue YoY %", "Category", alpha))
    sca = out[out["level"] == "Store x Category"]
    assoc.append(association(sca["availability_change_pp"], sca["net_revenue_yoy_pct"], "availability change (pp)",
                             "net revenue YoY %", "Store x Category", alpha))
    assoc.append(association(sca["est_lost_sales_change_ESTIMATE"], sca["net_revenue_change"],
                             "change in estimated lost sales (EUR)", "net revenue change (EUR)", "Store x Category", alpha))
    assoc_df = pd.DataFrame(assoc)
    # upper bound (literal BR-05 over every stock-out week) at estate, store and category level
    out["est_lost_sales_upper_py_ESTIMATE"] = np.nan
    out["est_lost_sales_upper_cy_ESTIMATE"] = np.nan
    for level, keys in (("Store", ["store_id"]), ("Category", ["category"])):
        u = lost_by(keys, "vu")
        m = out["level"] == level
        out.loc[m, "est_lost_sales_upper_py_ESTIMATE"] = out.loc[m, "key"].map(u["est_lost_sales_py"]).fillna(0.0)
        out.loc[m, "est_lost_sales_upper_cy_ESTIMATE"] = out.loc[m, "key"].map(u["est_lost_sales_cy"]).fillna(0.0)
    m = out["level"] == "Estate"
    out.loc[m, "est_lost_sales_upper_py_ESTIMATE"] = float(ltu[py])
    out.loc[m, "est_lost_sales_upper_cy_ESTIMATE"] = float(ltu[cy])
    return out, assoc_df, {"lost_py": float(lt[py]), "lost_cy": float(lt[cy]), "upper_py": float(ltu[py]),
                           "upper_cy": float(ltu[cy])}


# ============================================================================= promotions
def promotion_summary(lines: pd.DataFrame, scope: pd.DataFrame, py: int, cy: int) -> pd.DataFrame:
    rows = []

    def block(level, key, g_all, g_promo, g_non, sc=None):
        for yr in (py, cy):
            a = g_all[g_all["retail_year"] == yr]
            p = g_promo[g_promo["retail_year"] == yr]
            n = g_non[g_non["retail_year"] == yr]
            sales, psales = a["sales_revenue"].sum(), p["sales_revenue"].sum()
            rows.append({"level": level, "key": key, "retail_year": yr,
                         "sales_revenue": sales, "promo_sales_revenue": psales,
                         "promo_revenue_share": safe_div(psales, sales),
                         "non_promo_sales_revenue": n["sales_revenue"].sum(),
                         "promoted_units": p["units_sold"].sum(), "promo_discount_cost": p["discount_value"].sum(),
                         "promo_gross_sales": p["gross_sales"].sum(),
                         "promo_avg_discount_depth": safe_div(p["discount_value"].sum(), p["gross_sales"].sum()),
                         "promo_line_margin_pct": safe_div(p["sales_revenue"].sum() - p["cost_of_sales"].sum(), psales),
                         "non_promo_line_margin_pct": safe_div(n["sales_revenue"].sum() - n["cost_of_sales"].sum(),
                                                               n["sales_revenue"].sum()),
                         "promotions_planned_starting_in_half": (sc[sc["retail_year"] == yr]["promotions"].sum()
                                                                  if sc is not None else np.nan),
                         "store_sku_promo_days_planned": (sc[sc["retail_year"] == yr]["store_sku_promo_days"].sum()
                                                          if sc is not None else np.nan)})

    promo, non = lines[lines["is_promoted"] == 1], lines[lines["is_promoted"] == 0]
    block("Estate", "Brightwater estate", lines, promo, non, scope)
    for cat in sorted(lines["category"].unique()):
        block("Category", cat, lines[lines["category"] == cat], promo[promo["category"] == cat], non[non["category"] == cat],
              scope[scope["promotion_category"] == cat])
    for t in sorted(promo["promotion_type"].unique()):
        pt = promo[promo["promotion_type"] == t]
        block("Promotion type", t, lines, pt, non, scope[scope["promotion_type"] == t])
    return pd.DataFrame(rows)


def promotion_uplift(panel: Panel, est: dict, events: pd.DataFrame, cfg: dict, py: int, cy: int,
                     week_from: int, week_to: int, products: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Event-level uplift vs the pre-promotion baseline, incremental margin and the post-promotion check."""
    c = cfg["promotions"]
    sidx = est["seasonal_index"][0]                                    # product x week
    ev = events.copy()
    ev["s"] = ev["store_key"].map(panel.s_idx)
    ev["p"] = ev["product_key"].map(panel.p_idx)
    ev["w"] = ev["retail_week_key"].map(panel.w_idx)
    ev = ev.dropna(subset=["s", "p", "w"])
    ev[["s", "p", "w"]] = ev[["s", "p", "w"]].astype(int)
    ev["ranged"] = panel.ranged[ev["s"], ev["p"], ev["w"]]
    ekey = ["promotion_key", "store_key", "product_key", "start_date"]
    pw = ev[ev["promo_days_in_week"] >= c["promo_week_min_days"]]
    first = pw.groupby(ekey).agg(s=("s", "first"), p=("p", "first"), w_first=("w", "min"), w_last=("w", "max"),
                                 n_weeks=("w", "nunique"), promotion_type=("promotion_type", "first"),
                                 discount_pct=("discount_pct", "first"), all_ranged=("ranged", "all")).reset_index()
    all_events = ev.groupby(ekey)["w"].min().rename("w_min").reset_index()
    all_events["year"] = panel.week_year[all_events["w_min"]]
    all_events["week"] = panel.week_num[all_events["w_min"]]
    # events sharing a promotion week with another event of the same store-SKU are excluded (double counting)
    dup = pw.groupby(["store_key", "product_key", "retail_week_key"])["promotion_key"].nunique()
    dup_cells = dup[dup > 1].reset_index()[["store_key", "product_key", "retail_week_key"]]
    overl = pw.merge(dup_cells, on=["store_key", "product_key", "retail_week_key"])[ekey].drop_duplicates()
    first = first.merge(overl.assign(overlapping=True), on=ekey, how="left")
    first["overlapping"] = first["overlapping"].fillna(False).astype(bool)
    first["year"] = panel.week_year[first["w_first"]]
    first["week"] = panel.week_num[first["w_first"]]
    first = first[first["year"].isin([py, cy]) & (first["week"] >= week_from) & (first["week"] <= week_to)].copy()

    s, p, f, l = (first[k].to_numpy() for k in ("s", "p", "w_first", "w_last"))
    n_w = len(panel.week_keys)
    z_sum = np.zeros(len(first)); z_n = np.zeros(len(first)); v_sum = np.zeros(len(first)); u_sum = np.zeros(len(first))
    for k in range(1, c["pre_weeks"] + 1):
        w = f - k
        ok = w >= 0
        wc = np.clip(w, 0, n_w - 1)
        el = ok & panel.eligible[s, p, wc]
        z_sum += np.where(el, panel.units_sold[s, p, wc] / sidx[p, wc], 0)
        z_n += el
        v_sum += np.where(el, panel.sales_revenue[s, p, wc], 0)
        u_sum += np.where(el, panel.units_sold[s, p, wc], 0)
    base = np.where(z_n >= c["min_baseline_weeks"], z_sum / np.maximum(z_n, 1), np.nan)
    first["baseline_weeks"] = z_n
    first["baseline_rate"] = base
    # promotion weeks: actual vs expected
    act = np.zeros(len(first)); exp = np.zeros(len(first)); disc = np.zeros(len(first)); promo_rev = np.zeros(len(first))
    max_len = int((l - f).max()) + 1 if len(first) else 0
    for k in range(max_len):
        w = f + k
        ok = w <= l
        wc = np.clip(w, 0, n_w - 1)
        act += np.where(ok, panel.units_sold[s, p, wc], 0)
        exp += np.where(ok, base * sidx[p, wc], 0)
        disc += np.where(ok, panel.discount_value[s, p, wc], 0)
        promo_rev += np.where(ok, panel.sales_revenue[s, p, wc], 0)
    first["promo_units"] = act
    first["baseline_units"] = exp
    first["promo_discount_cost"] = disc
    first["promo_period_revenue"] = promo_rev
    # post-promotion weeks (in stock, not promoted)
    pa = np.zeros(len(first)); pe = np.zeros(len(first)); pn = np.zeros(len(first))
    for k in range(1, c["post_weeks"] + 1):
        w = l + k
        ok = w < n_w
        wc = np.clip(w, 0, n_w - 1)
        el = ok & panel.eligible[s, p, wc]
        pa += np.where(el, panel.units_sold[s, p, wc], 0)
        pe += np.where(el, base * sidx[p, wc], 0)
        pn += el
    first["post_units"] = pa
    first["post_expected_units"] = pe
    first["post_weeks_used"] = pn
    # price and unit cost for the incremental margin
    prod_price = safe_div(np.where(panel.eligible, panel.sales_revenue, 0).sum(axis=(0, 2)),
                          np.where(panel.eligible, panel.units_sold, 0).sum(axis=(0, 2)))
    prod_cost = safe_div(panel.cost_of_sales.sum(axis=(0, 2)), panel.units_sold.sum(axis=(0, 2)))
    bprice = np.where(u_sum > 0, safe_div(v_sum, np.where(u_sum > 0, u_sum, 1)), prod_price[p])
    first["baseline_price"] = bprice
    first["unit_cost"] = prod_cost[p]
    first["incremental_units"] = first["promo_units"] - first["baseline_units"]
    first["incremental_margin_before_discount"] = first["incremental_units"] * (first["baseline_price"] - first["unit_cost"])
    first["incremental_promo_margin"] = first["incremental_margin_before_discount"] - first["promo_discount_cost"]
    first["valid"] = (~np.isnan(base)) & (~first["overlapping"]) & first["all_ranged"]
    first["category"] = panel.category[p]

    valid = first[first["valid"]]
    rows = []

    def agg(level, key, g, yr):
        bu, pu = g["baseline_units"].sum(), g["promo_units"].sum()
        rows.append({"level": level, "key": key, "retail_year": yr, "events": len(g),
                     "promo_weeks": int((g["w_last"] - g["w_first"] + 1).sum()),
                     "promo_units": pu, "baseline_units": bu, "incremental_units": pu - bu,
                     "uplift_pct": 100 * safe_div(pu - bu, bu),
                     "promo_discount_cost": g["promo_discount_cost"].sum(),
                     "incremental_margin_before_discount": g["incremental_margin_before_discount"].sum(),
                     "incremental_promo_margin": g["incremental_promo_margin"].sum(),
                     "post_units": g["post_units"].sum(), "post_expected_units": g["post_expected_units"].sum(),
                     "post_promo_vs_baseline_pct": 100 * safe_div(g["post_units"].sum() - g["post_expected_units"].sum(),
                                                                  g["post_expected_units"].sum()),
                     "avg_discount_pct": g["discount_pct"].mean()})

    long_keys = set(map(tuple, first[ekey].astype(str).to_numpy()))
    for yr in (py, cy):
        fy = first[first["year"] == yr]
        g = valid[valid["year"] == yr]
        ae = all_events[(all_events["year"] == yr) & all_events["week"].between(week_from, week_to)]
        short = sum(tuple(k) not in long_keys for k in ae[ekey].astype(str).to_numpy())
        agg("Estate", "Brightwater estate", g, yr)
        rows[-1].update({"events_total": len(fy) + short, "events_excluded_short": int(short),
                         "events_excluded_no_baseline": int(fy["baseline_rate"].isna().sum()),
                         "events_excluded_overlap": int(fy["overlapping"].sum()),
                         "events_excluded_not_ranged": int((~fy["all_ranged"] & fy["baseline_rate"].notna() &
                                                            ~fy["overlapping"]).sum())})
        for t, gt in g.groupby("promotion_type"):
            agg("Promotion type", t, gt, yr)
        for cat, gc in g.groupby("category"):
            agg("Category", cat, gc, yr)
        bands = pd.cut(g["discount_pct"], [0, 0.15, 0.25, 1.0], labels=["<15%", "15-25%", ">=25%"], right=False)
        for b, gb in g.groupby(bands, observed=True):
            agg("Discount depth", str(b), gb, yr)
    out = pd.DataFrame(rows)
    events_out = first.merge(products[["product_key", "product_id"]], on="product_key", how="left")
    return out, events_out


# ============================================================================= targets
def target_diagnostics(tw: pd.DataFrame, cfg: dict, py: int, cy: int, week_to: int) -> pd.DataFrame:
    """Per store and year: achievement, variance, misses, longest streak, last-N misses (recomputed in Python)."""
    n_last, need = cfg["targets"]["last_n_weeks"], cfg["targets"]["persistent_min_misses"]
    rows = []
    for (yr, sid), g in tw[tw["retail_year"].isin([py, cy])].groupby(["retail_year", "store_id"]):
        g = g.sort_values("retail_week")
        missed = (g["net_revenue"] < g["target_net_revenue"]).to_numpy()
        weeks = g["retail_week"].to_numpy()
        longest = cur = 0
        prev_w = None
        for m, w in zip(missed, weeks):
            if m and prev_w is not None and w == prev_w + 1 and cur > 0:
                cur += 1
            elif m:
                cur = 1
            else:
                cur = 0
            longest = max(longest, cur)
            prev_w = w
        last = weeks > week_to - n_last
        rows.append({"retail_year": yr, "store_id": sid, "store_name": g["store_name"].iloc[0],
                     "region": g["region"].iloc[0], "store_format": g["store_format"].iloc[0],
                     "target_weeks": len(g), "missed_weeks": int(missed.sum()),
                     "net_revenue": g["net_revenue"].sum(), "target_net_revenue": g["target_net_revenue"].sum(),
                     "variance_to_target": g["net_revenue"].sum() - g["target_net_revenue"].sum(),
                     "target_achievement_pct": 100 * safe_div(g["net_revenue"].sum(), g["target_net_revenue"].sum()),
                     "longest_miss_streak": longest,
                     f"last{n_last}_target_weeks": int(last.sum()), f"last{n_last}_missed_weeks": int(missed[last].sum()),
                     "persistent_underperformer": bool(missed[last].sum() >= need)})
    out = pd.DataFrame(rows)
    return out.sort_values(["retail_year", "store_id"]).reset_index(drop=True)

def stockout_mechanism(lost: pd.DataFrame, years: tuple[int, int]) -> dict:
    """Is the stock-out mechanism visible? Actual vs expected sales by type of stock-out week and year.

    A stock-out week has zero closing stock, so it includes weeks that sold out part-way through (often
    high-selling weeks). Weeks that started empty and received nothing show the mechanism directly."""
    le = lost[lost["has_estimate"]]
    names = {"full_week": "no stock all week (opening 0, nothing received)",
             "restocked": "started empty, restocked during week", "sold_out": "sold out during the week (opening stock > 0)"}
    out = {"stockout_cells": int(len(lost)), "cells_with_estimate": int(len(le)),
           "coverage": float(len(le) / len(lost)) if len(lost) else np.nan,
           "promoted_stockout_cells": int(lost["promoted_week"].sum()), "by_type": []}
    for code, name in names.items():
        for yr in years:
            g = le[(le["stockout_type"] == code) & (le["retail_year"] == yr)]
            out["by_type"].append({"type": name, "type_code": code, "retail_year": int(yr), "cells": int(len(g)),
                                   "actual_units": float(g["actual_units"].sum()),
                                   "expected_units": float(g["expected_units"].sum()),
                                   "actual_to_expected": float(safe_div(g["actual_units"].sum(), g["expected_units"].sum())),
                                   "net_shortfall_eur": float(((g["expected_units"] - g["actual_units"]) * g["baseline_price"].fillna(0)).sum()),
                                   "est_lost_sales_eur": float(g["est_lost_sales_eur"].sum()),
                                   "est_lost_sales_upper_eur": float(g["est_lost_sales_upper_eur"].sum()),
                                   "upper_per_cell_eur": float(g["est_lost_sales_upper_eur"].mean()) if len(g) else np.nan})
    full = le[le["stockout_type"] == "full_week"]
    out["full_week_out_cells"] = int(len(full))
    out["full_week_out_actual_units"] = float(full["actual_units"].sum())
    out["full_week_out_expected_units"] = float(full["expected_units"].sum())
    out["full_week_out_actual_to_expected"] = float(safe_div(full["actual_units"].sum(), full["expected_units"].sum()))
    part = le[le["stockout_type"] != "full_week"]
    out["partial_upper_per_cell_eur"] = float(part["est_lost_sales_upper_eur"].mean()) if len(part) else np.nan
    return out


def category_region_matrix(store_cat: pd.DataFrame, py: int, cy: int, total_py: float) -> pd.DataFrame:
    """Category x region net revenue change: is a category's decline estate-wide or local?"""
    g = wide_by_year(store_cat, ["region", "category"], ["sales_revenue", "returns_value"], py, cy)
    g["net_revenue_py"] = g["sales_revenue_py"] - g["returns_value_py"]
    g["net_revenue_cy"] = g["sales_revenue_cy"] - g["returns_value_cy"]
    g["net_revenue_change"] = g["net_revenue_cy"] - g["net_revenue_py"]
    g["net_revenue_yoy_pct"] = yoy_pct(g["net_revenue_cy"], g["net_revenue_py"])
    g["contribution_pp"] = 100 * g["net_revenue_change"] / total_py
    return g[["region", "category", "net_revenue_py", "net_revenue_cy", "net_revenue_change", "net_revenue_yoy_pct",
              "contribution_pp"]].sort_values(["region", "category"]).reset_index(drop=True)

def range_change(prod: pd.DataFrame, py: int, cy: int) -> pd.DataFrame:
    """Assortment churn by category: revenue of products sold in only one of the two periods."""
    w = wide_by_year(prod, ["product_key", "category"], ["sales_revenue", "returns_value", "ranged_cells"], py, cy)
    w["net_py"] = w["sales_revenue_py"] - w["returns_value_py"]
    w["net_cy"] = w["sales_revenue_cy"] - w["returns_value_cy"]
    w["status"] = np.select([(w["sales_revenue_py"] > 0) & (w["sales_revenue_cy"] <= 0),
                             (w["sales_revenue_py"] <= 0) & (w["sales_revenue_cy"] > 0)],
                            ["sold in prior period only", "sold in current period only"], "sold in both periods")
    g = w.groupby(["category", "status"]).agg(products=("product_key", "count"), net_revenue_py=("net_py", "sum"),
                                              net_revenue_cy=("net_cy", "sum")).reset_index()
    g["net_revenue_change"] = g["net_revenue_cy"] - g["net_revenue_py"]
    return g.sort_values(["category", "status"]).reset_index(drop=True)
