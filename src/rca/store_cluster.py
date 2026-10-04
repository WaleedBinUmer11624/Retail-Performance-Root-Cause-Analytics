"""Store-cluster investigation (the stores Phase 5 found carrying half of the decline).

Questions: when does the deterioration start, is it abrupt, which days / hours / categories / baskets does
it affect, and does anything observable (availability, promotions, price, range, returns) explain it once
the cluster is compared with matched control stores?

Methods
  * timing: daily transactions YoY of the cluster minus the control group; single change point (step) vs
    linear ramp vs straight line, compared by BIC
  * difference-in-differences on store-week YoY log ratios (removes seasonality and store level), with a
    pre-trend (parallel trends) check, a weekly event-study gap and permutation placebo inference
  * EUR impact: ratio DiD on sums (counterfactual = cluster prior-year H2 x control YoY x pre-period gap)
Transactions are receipts: no footfall exists, so the unexplained part is classified as unresolved.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.contribution import safe_div

from . import stats as ST

KPI_COLS = ["transactions", "units_sold", "sales_revenue", "returns_value", "net_revenue", "gross_margin",
            "promo_sales_revenue", "discount_value"]


# ----------------------------------------------------------------------------- panels
def daily_yoy(store_day: pd.DataFrame, year: int) -> pd.DataFrame:
    """Store x date of `year` joined to the same weekday one year earlier (same_day_last_year_key)."""
    cy = store_day[store_day["retail_year"] == year]
    py = store_day[KPI_COLS + ["store_key", "date_key"]].rename(
        columns={"date_key": "same_day_last_year_key", **{c: f"{c}_py" for c in KPI_COLS}})
    m = cy.merge(py, on=["store_key", "same_day_last_year_key"], how="inner")
    return m[(m["transactions"] > 0) & (m["transactions_py"] > 0)].copy()


def weekly_panel(store_day: pd.DataFrame, year: int) -> pd.DataFrame:
    """Store x retail week of `year` with the same retail week of the prior year."""
    g = store_day.groupby(["store_id", "retail_year", "retail_week"])[KPI_COLS].sum().reset_index()
    cy = g[g["retail_year"] == year].drop(columns="retail_year")
    py = g[g["retail_year"] == year - 1].drop(columns="retail_year").rename(columns={c: f"{c}_py" for c in KPI_COLS})
    m = cy.merge(py, on=["store_id", "retail_week"], how="inner")
    for c in ("transactions", "net_revenue", "sales_revenue"):
        m[f"ly_{c}"] = np.log(m[c] / m[f"{c}_py"])
    return m


# ----------------------------------------------------------------------------- control groups
def store_features(store_day: pd.DataFrame, stores: pd.DataFrame, py: int, cy: int) -> pd.DataFrame:
    """Pre-period characteristics used for matching (prior year, plus current-year H1 trend)."""
    a = store_day[store_day["retail_year"] == py].groupby("store_id")[["net_revenue", "transactions", "sales_revenue",
                                                                         "units_sold"]].sum()
    h1c = store_day[(store_day["retail_year"] == cy) & (store_day["retail_week"] <= 26)].groupby("store_id")["transactions"].sum()
    h1p = store_day[(store_day["retail_year"] == py) & (store_day["retail_week"] <= 26)].groupby("store_id")["transactions"].sum()
    f = pd.DataFrame({"log_net_revenue": np.log(a["net_revenue"]), "log_transactions": np.log(a["transactions"]),
                      "aov": a["sales_revenue"] / a["transactions"], "upt": a["units_sold"] / a["transactions"],
                      "h1_transactions_yoy": np.log(h1c / h1p)})
    s = stores.set_index("store_id")
    f["is_standard"] = (s["store_format"] == "Standard").astype(float)
    f["is_dublin"] = (s["region"] == "Dublin").astype(float)
    return f.sort_index()


def control_groups(features: pd.DataFrame, stores: pd.DataFrame, cluster: list[str], k: int) -> tuple[dict, pd.DataFrame]:
    s = stores.set_index("store_id")
    non = [x for x in sorted(features.index) if x not in cluster]
    z = (features - features.mean()) / features.std(ddof=0).replace(0, 1)
    dist = pd.DataFrame({c: np.sqrt(((z.loc[non] - z.loc[c]) ** 2).sum(axis=1)) for c in cluster})
    dist["mean_distance"] = dist.mean(axis=1)
    dist = dist.sort_values(["mean_distance"]).rename_axis("store_id")
    groups = {
        "matched": sorted(dist.index[:k].tolist()),
        "standard_non_cluster": sorted([x for x in non if s.loc[x, "store_format"] == "Standard"]),
        "dublin_non_cluster": sorted([x for x in non if s.loc[x, "region"] == "Dublin"]),
        "all_non_cluster": non,
    }
    return groups, dist.reset_index()


# ----------------------------------------------------------------------------- timing
def onset(dy: pd.DataFrame, cluster: list[str], control: list[str], cfg: dict, stores: pd.DataFrame) -> dict:
    """Change point in the daily cluster-minus-control transactions YoY (log)."""

    def series(ids):
        g = dy[dy["store_id"].isin(ids)].groupby("calendar_date")[["transactions", "transactions_py"]].sum()
        return np.log(g["transactions"] / g["transactions_py"])

    gap = (series(cluster) - series(control)).dropna().sort_index()
    y = gap.to_numpy()
    step = ST.step_changepoint(y, cfg["min_segment_days"])
    ramp = ST.ramp_fit(y, cfg["max_ramp_days"], cfg["min_segment_days"])
    lin = ST.linear_fit(y)
    dates = gap.index
    out = {"gap_daily": gap, "step": step, "ramp": ramp, "linear": lin,
           "onset_date": dates[step["index"]], "ramp_start": dates[ramp["start_index"]],
           "ramp_end": dates[min(ramp["end_index"], len(dates) - 1)],
           "abrupt": ramp["ramp_days"] <= cfg["abrupt_max_ramp_days"] and step["bic"] < lin["bic"],
           "best_model": min((("step", step["bic"]), ("ramp", ramp["bic"]), ("linear", lin["bic"])), key=lambda t: t[1])[0]}
    per = []
    for sid in cluster:
        g1 = (series([sid]) - series(control)).dropna().sort_index()
        st = ST.step_changepoint(g1.to_numpy(), cfg["min_segment_days"])
        per.append({"store_id": sid, "onset_date": g1.index[st["index"]].date(), "shift_log": st["shift"],
                    "shift_pct": 100 * (np.exp(st["shift"]) - 1), "r2": st["r2"]})
    out["per_store"] = pd.DataFrame(per)
    return out


# ----------------------------------------------------------------------------- DiD
def did_analysis(wp: pd.DataFrame, cluster: list[str], control: list[str], pre: tuple[int, int], post: tuple[int, int],
                 outcome: str = "ly_transactions") -> dict:
    ispre = wp["retail_week"].between(*pre)
    ispost = wp["retail_week"].between(*post)
    t = wp[wp["store_id"].isin(cluster)].groupby("retail_week")[outcome].mean()
    c = wp[wp["store_id"].isin(control)].groupby("retail_week")[outcome].mean()
    gap = (t - c).dropna()
    pre_gap = gap[gap.index.to_series().between(*pre)]
    post_gap = gap[gap.index.to_series().between(*post)]
    est = float(post_gap.mean() - pre_gap.mean())
    pt = ST.pre_trend(pre_gap)

    def stat(tr, co):
        tt = wp[wp["store_id"].isin(tr)]
        cc = wp[wp["store_id"].isin(co)]
        return ST.did(tt.loc[ispre, outcome], tt.loc[ispost, outcome], cc.loc[ispre, outcome], cc.loc[ispost, outcome])

    return {"did_log": est, "did_pct": 100 * (np.exp(est) - 1), "pre_gap_mean": float(pre_gap.mean()),
            "post_gap_mean": float(post_gap.mean()), "pre_trend": pt, "gap_weekly": gap, "stat": stat}


def ratio_did_eur(wp: pd.DataFrame, cluster: list[str], control: list[str], pre, post, col: str) -> dict:
    """Counterfactual cluster value in the post-period = cluster prior-year x control YoY x pre-period relative gap."""
    def sums(ids, weeks):
        x = wp[wp["store_id"].isin(ids) & wp["retail_week"].between(*weeks)]
        return float(x[col].sum()), float(x[f"{col}_py"].sum())
    tc_pre, tp_pre = sums(cluster, pre)
    cc_pre, cp_pre = sums(control, pre)
    tc_post, tp_post = sums(cluster, post)
    cc_post, cp_post = sums(control, post)
    gap_ratio = (tc_pre / tp_pre) / (cc_pre / cp_pre)
    cf = tp_post * (cc_post / cp_post) * gap_ratio
    return {"actual": tc_post, "prior_year": tp_post, "control_yoy": cc_post / cp_post - 1, "pre_gap_ratio": gap_ratio,
            "counterfactual": cf, "excess": tc_post - cf}


# ----------------------------------------------------------------------------- what else changed
def mechanism_checks(data: dict, cluster: list[str], control: list[str], py: int, cy: int, weeks: tuple[int, int],
                     stores: pd.DataFrame) -> dict:
    sid = stores.set_index("store_key")["store_id"]
    sd = data["store_day"]
    sd = sd[sd["retail_week"].between(*weeks)]
    groups = {"cluster": cluster, "control": control}
    rows = []
    rc = data["receipt"]
    rc = rc[rc["retail_week"].between(*weeks)].assign(store_id=lambda d: d["store_key"].map(sid))
    sc = data["stock_cell_week"]
    sc = sc[sc["retail_week"].between(*weeks)].assign(store_id=lambda d: d["store_key"].map(sid))
    scw = data["store_category_week"]
    scw = scw[scw["retail_week"].between(*weeks)].assign(store_id=lambda d: d["store_key"].map(sid))
    for g, ids in groups.items():
        for yr in (py, cy):
            d = sd[sd["store_id"].isin(ids) & (sd["retail_year"] == yr)]
            r = rc[rc["store_id"].isin(ids) & (rc["retail_year"] == yr)]
            s = sc[sc["store_id"].isin(ids) & (sc["retail_year"] == yr)]
            n_stores = len(ids)
            rows.append({"group": g, "retail_year": yr, "stores": n_stores,
                         "transactions_per_store": d["transactions"].sum() / n_stores,
                         "aov": safe_div(d["sales_revenue"].sum(), d["transactions"].sum()),
                         "upt": safe_div(d["units_sold"].sum(), d["transactions"].sum()),
                         "asp": safe_div(d["sales_revenue"].sum(), d["units_sold"].sum()),
                         "promo_revenue_share": safe_div(d["promo_sales_revenue"].sum(), d["sales_revenue"].sum()),
                         "receipts_with_promo_share": float(r["has_promoted_line"].mean()),
                         "return_rate_value": safe_div(d["returns_value"].sum(), d["sales_revenue"].sum()),
                         "availability": float(s["is_in_stock"].mean()),
                         "ranged_skus_per_store_week": float(s.groupby(["store_id", "retail_week"]).size().mean()),
                         "weekend_transaction_share": safe_div(d.loc[d["is_weekend"] == 1, "transactions"].sum(),
                                                               d["transactions"].sum()),
                         "basket_value_p25": float(r["basket_value"].quantile(0.25)),
                         "basket_value_p50": float(r["basket_value"].quantile(0.5)),
                         "basket_value_p75": float(r["basket_value"].quantile(0.75)),
                         "basket_value_p90": float(r["basket_value"].quantile(0.9)),
                         "units_p50": float(r["units"].quantile(0.5)), "units_p90": float(r["units"].quantile(0.9)),
                         "single_item_receipt_share": float((r["units"] == 1).mean())})
    kpis = pd.DataFrame(rows)
    # difference of changes (cluster change minus control change), per metric
    w = kpis.set_index(["group", "retail_year"]).drop(columns="stores")
    comp = []
    for m in w.columns:
        cc = w.loc[("cluster", cy), m] - w.loc[("cluster", py), m]
        oc = w.loc[("control", cy), m] - w.loc[("control", py), m]
        rel = m in ("transactions_per_store", "aov", "upt", "asp", "ranged_skus_per_store_week") or m.startswith(("basket", "units"))
        cp = 100 * (w.loc[("cluster", cy), m] / w.loc[("cluster", py), m] - 1) if rel else 100 * cc
        op = 100 * (w.loc[("control", cy), m] / w.loc[("control", py), m] - 1) if rel else 100 * oc
        comp.append({"metric": m, "cluster_py": w.loc[("cluster", py), m], "cluster_cy": w.loc[("cluster", cy), m],
                     "control_py": w.loc[("control", py), m], "control_cy": w.loc[("control", cy), m],
                     "unit": "% change" if rel else "pp change", "cluster_change": cp, "control_change": op,
                     "difference": cp - op})
    comp = pd.DataFrame(comp)

    # day-of-week and hour-of-day DiD of transactions
    dow = []
    dsd = sd.copy()
    for dname, grp in dsd.groupby("day_name"):
        vals = {}
        for gname, ids in groups.items():
            x = grp[grp["store_id"].isin(ids)]
            vals[gname] = 100 * (x.loc[x["retail_year"] == cy, "transactions"].sum() /
                                 x.loc[x["retail_year"] == py, "transactions"].sum() - 1)
        dow.append({"day_name": dname, "day_of_week": int(grp["day_of_week"].iloc[0]), "cluster_yoy_pct": vals["cluster"],
                    "control_yoy_pct": vals["control"], "difference_pp": vals["cluster"] - vals["control"]})
    dow = pd.DataFrame(dow).sort_values("day_of_week").reset_index(drop=True)
    hrs = []
    rh = rc.groupby(["hour_of_day", "retail_year", "store_id"]).size().rename("n").reset_index()
    for h, grp in rh.groupby("hour_of_day"):
        vals = {}
        for gname, ids in groups.items():
            x = grp[grp["store_id"].isin(ids)]
            p_ = x.loc[x["retail_year"] == py, "n"].sum()
            vals[gname] = 100 * (x.loc[x["retail_year"] == cy, "n"].sum() / p_ - 1) if p_ else np.nan
        hrs.append({"hour_of_day": int(h), "cluster_yoy_pct": vals["cluster"], "control_yoy_pct": vals["control"],
                    "difference_pp": vals["cluster"] - vals["control"]})
    hrs = pd.DataFrame(hrs)
    # category mix: share of sales and receipts-with-category YoY
    mix = []
    for cat, grp in scw[scw["category"] != "Unknown"].groupby("category"):
        rec = {"category": cat}
        for gname, ids in groups.items():
            x = grp[grp["store_id"].isin(ids)]
            tot = scw[scw["store_id"].isin(ids)]
            for yr in (py, cy):
                rec[f"{gname}_share_{yr}"] = safe_div(x.loc[x["retail_year"] == yr, "sales_revenue"].sum(),
                                                      tot.loc[tot["retail_year"] == yr, "sales_revenue"].sum())
            rec[f"{gname}_sales_yoy_pct"] = 100 * (x.loc[x["retail_year"] == cy, "sales_revenue"].sum() /
                                                   x.loc[x["retail_year"] == py, "sales_revenue"].sum() - 1)
        rec["difference_pp"] = rec["cluster_sales_yoy_pct"] - rec["control_sales_yoy_pct"]
        mix.append(rec)
    mix = pd.DataFrame(mix)
    dissim = 0.5 * float((mix[f"cluster_share_{cy}"] - mix[f"cluster_share_{py}"]).abs().sum())
    dissim_c = 0.5 * float((mix[f"control_share_{cy}"] - mix[f"control_share_{py}"]).abs().sum())
    return {"kpis": kpis, "comparison": comp, "weekday": dow, "hour": hrs, "category_mix": mix,
            "mix_shift_cluster": dissim, "mix_shift_control": dissim_c}


def basket_distribution(receipt: pd.DataFrame, stores: pd.DataFrame, cluster: list[str], control: list[str], py: int,
                        cy: int, weeks: tuple[int, int]) -> pd.DataFrame:
    sid = stores.set_index("store_key")["store_id"]
    r = receipt[receipt["retail_week"].between(*weeks)].assign(store_id=lambda d: d["store_key"].map(sid))
    bands = [0, 10, 20, 40, 80, 160, np.inf]
    labels = ["<10", "10-20", "20-40", "40-80", "80-160", "160+"]
    rows = []
    for g, ids in (("cluster", cluster), ("control", control)):
        for yr in (py, cy):
            x = r[r["store_id"].isin(ids) & (r["retail_year"] == yr)]
            cnt = pd.cut(x["basket_value"], bands, labels=labels, right=False).value_counts().reindex(labels)
            for lab in labels:
                rows.append({"group": g, "retail_year": yr, "basket_value_band": lab, "receipts": int(cnt[lab]),
                             "share": float(cnt[lab] / cnt.sum())})
    out = pd.DataFrame(rows)
    piv = out.pivot_table(index=["group", "basket_value_band"], columns="retail_year", values="receipts").reset_index()
    piv["receipts_yoy_pct"] = 100 * (piv[cy] / piv[py] - 1)
    out = out.merge(piv[["group", "basket_value_band", "receipts_yoy_pct"]], on=["group", "basket_value_band"])
    return out


def investigate(data: dict, cluster: list[str], cfg: dict, py: int, cy: int) -> dict:
    c = cfg["store_cluster"]
    stores = data["stores"]
    feats = store_features(data["store_day"], stores, py, cy)
    groups, dist = control_groups(feats, stores, cluster, c["matched_k"])
    primary = groups[c["primary_control"]]
    wp = weekly_panel(data["store_day"], cy)
    pre, post = tuple(c["pre_weeks"]), tuple(c["post_weeks"])
    dy = daily_yoy(data["store_day"], c["onset_year"])
    res = {"features": feats, "groups": groups, "distances": dist, "primary_control": c["primary_control"],
           "weekly": wp, "onset": onset(dy, cluster, primary, c, stores)}
    dd = {}
    for name, ids in groups.items():
        for outc in ("ly_transactions", "ly_net_revenue"):
            d = did_analysis(wp, cluster, ids, pre, post, outc)
            dd[(name, outc)] = d
    res["did"] = dd
    # permutation placebo over every 3-store group of non-cluster stores (each vs the rest of the non-cluster stores)
    pool = groups["all_non_cluster"]
    dprim = dd[("all_non_cluster", "ly_transactions")]
    res["placebo"] = ST.permutation_placebo(cluster, pool, c["placebo_group_size"], dprim["stat"])
    eur = {}
    for name, ids in groups.items():
        eur[name] = {"net_revenue": ratio_did_eur(wp, cluster, ids, pre, post, "net_revenue"),
                     "transactions": ratio_did_eur(wp, cluster, ids, pre, post, "transactions"),
                     "gross_margin": ratio_did_eur(wp, cluster, ids, pre, post, "gross_margin")}
    res["eur"] = eur
    res["mechanisms"] = mechanism_checks(data, cluster, primary, py, cy, post, stores)
    res["baskets"] = basket_distribution(data["receipt"], stores, cluster, primary, py, cy, post)
    return res
