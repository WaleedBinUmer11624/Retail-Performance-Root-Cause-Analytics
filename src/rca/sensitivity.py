"""Sensitivity analysis: every estimated impact re-run under reasonable alternative assumptions.

A result is called robust only if every variant has the same sign and lies within the configured band
around the central estimate. Lost-sales variants that leave more than 10% of stock-out weeks without a
baseline are reported but not used for the robustness verdict (they are incomplete estimates, the same
coverage rule Phase 5 applied). A result that flips sign or moves a lot is reported as a range and is not
used as strong evidence.
"""
from __future__ import annotations

import pandas as pd

from . import electronics as EL
from . import promotions_rca as PR
from . import store_cluster as SC
from .stats import robust_summary


def run(data: dict, cfg: dict, res: dict, py: int, cy: int, wf: int, wt: int, cluster: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = cfg["rca"]["sensitivity"]
    rows = []
    sc = res["store_cluster"]
    wp = sc["weekly"]
    post = tuple(cfg["rca"]["store_cluster"]["post_weeks"])
    for g in s["control_groups"]:
        for pre in s["pre_windows"]:
            e = SC.ratio_did_eur(wp, cluster, sc["groups"][g], tuple(pre), post, "net_revenue")
            rows.append({"driver": "store_cluster_excess", "method": "ratio DiD (net revenue)",
                         "variant": f"control={g}; pre=weeks {pre[0]}-{pre[1]}", "estimate_eur": e["excess"]})
    # post window starting at the detected onset week instead of week 27
    onset_week = int(data["store_day"].set_index("calendar_date").loc[sc["onset"]["onset_date"], "retail_week"].iloc[0])
    e = SC.ratio_did_eur(wp, cluster, sc["groups"][cfg["rca"]["store_cluster"]["primary_control"]],
                         (1, max(onset_week - 1, 2)), (onset_week, 52), "net_revenue")
    rows.append({"driver": "store_cluster_excess", "method": "ratio DiD (net revenue)",
                 "variant": f"pre=weeks 1-{onset_week - 1}; post=weeks {onset_week}-52 (onset-based)",
                 "estimate_eur": e["excess"]})

    el = res["electronics"]
    panel = el["panel"]
    cat = el["category"]
    for w in s["lost_sales_windows"]:
        for mh in s["lost_sales_min_history"]:
            for seas in s["lost_sales_seasonality"]:
                _, _, lost = EL.build_estimates(data, w, mh, seas, py, cy, wf, wt, panel=panel)
                t = EL.lost_totals(lost, py, cy, lost["category"] == cat)
                lc = lost[(lost["category"] == cat) & (lost["retail_year"] == cy)]
                cov = float(lc["has_estimate"].mean())
                v = f"windows={w}; min history={mh}; seasonality={'on' if seas else 'off'}"
                rows.append({"driver": "electronics_stockouts_primary", "method": "full-week lost sales change",
                             "variant": v, "estimate_eur": -t["primary_change"], "coverage": cov})
                rows.append({"driver": "electronics_stockouts_upper", "method": "BR-05 upper bound change",
                             "variant": v, "estimate_eur": -t["upper_change"], "coverage": cov})

    # deferred demand: sales above expected in the weeks after stock returned (change vs prior year) netted off
    off = el["recovery_offset_eur"]
    t = el["totals_category"]
    rows.append({"driver": "electronics_stockouts_primary", "method": "full-week lost sales change net of recovery",
                 "variant": "minus post-episode sales above expected (deferred demand)",
                 "estimate_eur": -(t["primary_change"] - off), "coverage": 1.0})
    rows.append({"driver": "electronics_stockouts_upper", "method": "BR-05 upper bound change net of recovery",
                 "variant": "minus post-episode sales above expected (deferred demand)",
                 "estimate_eur": -(t["upper_change"] - el["recovery_offset_all_eur"]), "coverage": 1.0})

    pr = res["promotions"]
    c = cfg["rca"]["promotions"]
    for name, ctl in s["promo_control_sets"].items():
        for pre in s["pre_windows"]:
            g = PR.gaps(pr["panel"], c["category"], ctl, "ly_sales_revenue")
            d = PR.m1_did(g, tuple(pre), tuple(c["post_weeks"]))
            ap = g[g["retail_week"].between(*c["post_weeks"])]
            rows.append({"driver": "home_kitchen_promotion", "method": "M1 category DiD",
                         "variant": f"controls={name}; pre=weeks {pre[0]}-{pre[1]}",
                         "estimate_eur": PR.eur_from_log(ap["sales_revenue_cy"], d)})
    m4 = pr["m4"]
    rows.append({"driver": "home_kitchen_promotion", "method": "M4 discount-rate accounting",
                 "variant": "net volume response = 0 (units unchanged)", "estimate_eur": m4["effect_eur_volume_held"]})
    for v, lab in zip(m4["ci_eur"], ("net volume response = M1 units CI bound A", "net volume response = M1 units CI bound B")):
        rows.append({"driver": "home_kitchen_promotion", "method": "M4 discount-rate accounting", "variant": lab,
                     "estimate_eur": v})
    rows.append({"driver": "home_kitchen_promotion", "method": "M2 dose-response (lags 0-2)", "variant": "store FE",
                 "estimate_eur": pr["m2"]["effect_eur"]})
    for k in s["promo_event_pre_weeks"]:
        m3 = PR.m3_events(data, panel, el["est"], cfg["analytics"], c["category"], py, cy, wf, wt, pre_weeks=k)
        rows.append({"driver": "home_kitchen_promotion", "method": "M3 event-level net programme revenue",
                     "variant": f"pre-promotion baseline weeks={k}", "estimate_eur": m3["effect_eur"]})

    rt = res["returns"]
    f = rt["faulty"]
    tot = f.groupby("return_retail_year")["refund_value"].sum()
    rows.append({"driver": "electronics_faulty_returns", "method": "value change", "variant": "all E&T 'Faulty' returns",
                 "estimate_eur": -(tot.get(cy, 0) - tot.get(py, 0))})
    for key in ("by_product", "by_store", "by_supplier"):
        t = rt[key]
        rows.append({"driver": "electronics_faulty_returns", "method": "excess over prior-year rate",
                     "variant": f"rates {key.replace('by_', 'per ')}", "estimate_eur": -float(t["excess_value_eur"].sum())})
    df = pd.DataFrame(rows)

    c = res["central"]
    central = {"store_cluster_excess": c["cluster_excess"], "electronics_stockouts_primary": c["stockouts_primary"],
               "electronics_stockouts_upper": c["stockouts_upper"], "home_kitchen_promotion": c["promotion"],
               "electronics_faulty_returns": c["faulty_returns"]}
    summ = []
    band = s["robust_max_relative_spread"]
    min_cov = s["min_coverage"]
    df["eligible_for_robustness"] = df.get("coverage", pd.Series(1.0, index=df.index)).fillna(1.0) >= min_cov
    for drv, g in df.groupby("driver"):
        ok = g[g["eligible_for_robustness"]]
        r = robust_summary(ok["estimate_eur"].tolist(), central[drv], band)
        summ.append({"driver": drv, **r, "variants_excluded_low_coverage": int((~g["eligible_for_robustness"]).sum()),
                     "min_all_variants": float(g["estimate_eur"].min()), "max_all_variants": float(g["estimate_eur"].max())})
    return df, pd.DataFrame(summ)
