"""Phase 6 runner: root-cause investigation and causal diagnostics.

Usage (from the project root):
    python -m src.rca.run_phase6                     # SQL Server model built by Phase 4
    python -m src.rca.run_phase6 --engine duckdb     # rebuild the Phase 4 model locally, then investigate
    python -m src.rca.run_phase6 --record-freeze     # record the Phase 1-5 manifest (once, at phase start)

Stops (exit 1) if any Phase 1-5 input or output changed, if the headline does not reconcile to Phase 4 and
Phase 5, or if any validation check fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.analytics.contribution import decline_cluster
from src.analytics.model_access import PROJECT_ROOT, InputError
from src.analytics.period_comparison import load_periods
from src.analytics.run_phase5 import OpenRecorder
from src.monitoring.access import classify_opened  # shared runtime-read policy; see src/monitoring/access.py

from . import electronics as EL
from . import evidence as EV
from . import overlap as OV
from . import promotions_rca as PR
from . import returns_rca as RR
from . import scenarios as SN
from . import sensitivity as SE
from . import store_cluster as SC
from .access import load_config, load_data, open_rca_model, read_csv, record_freeze, verify_freeze


class Phase6Stop(RuntimeError):
    pass


class Log:
    def __init__(self):
        self.t0, self.lines = time.time(), []

    def __call__(self, msg):
        line = f"[{time.time() - self.t0:7.1f}s] {msg}"
        self.lines.append(line)
        print(line, flush=True)


def headline(data: dict, cfg: dict, per) -> tuple[dict, dict, pd.DataFrame]:
    """Recompute the H2 headline from the governed views; reconcile to Phase 4 and to the frozen Phase 5 outputs."""
    h = data["h2_headline"].set_index("retail_year")
    f = data["h2_headline_from_facts"].set_index("retail_year")
    keys = ["sales_revenue", "returns_value", "net_revenue", "transactions", "units_sold", "gross_margin", "cogs"]
    py = {k: float(h.loc[per.py_year, k]) for k in keys}
    cy = {k: float(h.loc[per.cy_year, k]) for k in keys}
    for d in (py, cy):
        d["aov"] = d["sales_revenue"] / d["transactions"]
        d["return_rate_value"] = d["returns_value"] / d["sales_revenue"]
    tol = cfg["sql_model"]["tolerances"]
    b4 = read_csv("reports/phase4/reconciliation_results_duckdb.csv", cfg).set_index("metric_name")["actual_value"]
    p5 = read_csv(cfg["rca"]["inputs"]["phase5_headline"], cfg).set_index("metric")
    yoy = 100 * (cy["net_revenue"] / py["net_revenue"] - 1)
    rows = []

    def add(name, value, ref, source, t):
        rows.append({"check": name, "recomputed": value, "reference": float(ref), "abs_difference": abs(value - float(ref)),
                     "tolerance": t, "reference_source": source, "status": "PASS" if abs(value - float(ref)) <= t else "FAIL"})
    add(f"{per.label_py} net revenue vs Phase 4", py["net_revenue"], b4[f"h2_{per.py_year}_net_revenue"], "Phase 4", tol["eur"])
    add(f"{per.label_cy} net revenue vs Phase 4", cy["net_revenue"], b4[f"h2_{per.cy_year}_net_revenue"], "Phase 4", tol["eur"])
    add("H2 YoY % vs Phase 4", yoy, b4["h2_yoy_pct"], "Phase 4", tol["yoy_pct_points"])
    add(f"{per.label_py} net revenue vs direct fact query", py["net_revenue"], f.loc[per.py_year, "net_revenue"], "facts", tol["eur"])
    add(f"{per.label_cy} net revenue vs direct fact query", cy["net_revenue"], f.loc[per.cy_year, "net_revenue"], "facts", tol["eur"])
    for m in ("net_revenue", "sales_revenue", "returns_value", "transactions"):
        add(f"{m} change vs Phase 5 headline", cy[m] - py[m], p5.loc[m, "change"], "Phase 5 headline_kpis.csv",
            tol["eur"] if m != "transactions" else 0)
    bridge = read_csv(cfg["rca"]["inputs"]["phase5_bridge"], cfg)
    return py, cy, pd.DataFrame(rows).assign(phase5_bridge_rows=len(bridge))


def analyse(engine, cfg: dict, log: Log) -> dict:
    per = load_periods(cfg["project"])
    pyr, cyr, wf, wt = per.py_year, per.cy_year, per.week_from, per.week_to
    data = load_data(engine)
    log(f"data loaded: {sum(len(v) for v in data.values()):,} rows")
    py, cy, rec = headline(data, cfg, per)
    if (rec["status"] != "PASS").any():
        raise Phase6Stop("headline does not reconcile:\n" + rec.to_string(index=False))
    total = cy["net_revenue"] - py["net_revenue"]
    log(f"headline reconciled: {total:,.2f} ({100 * total / py['net_revenue']:+.6f}%)")
    R = {"periods": per, "py": py, "cy": cy, "headline_recon": rec, "data": data}

    # the cluster: the Phase 5 hand-off must equal an independent recomputation
    p5 = read_csv(cfg["rca"]["inputs"]["phase5_store_contribution"], cfg)
    cluster = sorted(p5.loc[p5["in_decline_cluster"], "store_id"].tolist())
    seg = data["segment_contribution"]
    st = seg[(seg["segment_type"] == "Store") & (seg["retail_year"] == cyr)].rename(columns={"segment_name": "store_id"})
    recomputed = sorted(decline_cluster(st, "store_id", cfg["analytics"]["trend"]["cluster_cover"]))
    if recomputed != cluster:
        raise Phase6Stop(f"store cluster differs from Phase 5: {recomputed} vs {cluster}")
    R["cluster"] = cluster

    R["store_cluster"] = sc = SC.investigate(data, cluster, cfg["rca"], pyr, cyr)
    prim = sc["primary_control"]
    log(f"store cluster: onset {sc['onset']['onset_date']:%Y-%m-%d}, excess {sc['eur'][prim]['net_revenue']['excess']:,.0f}")
    R["electronics"] = el = EL.investigate(data, cfg["rca"], pyr, cyr, wf, wt, cluster)
    log(f"electronics: full-week lost-sales change {el['totals_category']['primary_change']:,.0f}")
    R["returns"] = rt = RR.investigate(data, cfg["rca"], pyr, cyr, wf, wt, cluster)
    R["promotions"] = pr = PR.investigate(data, cfg["rca"], cfg["analytics"], el["panel"], el["est"], pyr, cyr, wf, wt, cluster)
    log(f"promotions: M1 {pr['m1']['effect_eur']:,.0f}, M4 {pr['m4']['effect_eur_volume_held']:,.0f}, "
        f"M2 {pr['m2']['effect_eur']:,.0f}, M3 {pr['m3']['effect_eur']:,.0f}")

    f = rt["faulty"].groupby("return_retail_year")["refund_value"].sum()
    R["central"] = {"cluster_excess": sc["eur"][prim]["net_revenue"]["excess"],
                    "stockouts_primary": -el["totals_category"]["primary_change"],
                    "stockouts_upper": -el["totals_category"]["upper_change"],
                    "promotion": pr["m1"]["effect_eur"],
                    "faulty_returns": -float(f.get(cyr, 0) - f.get(pyr, 0))}

    # ---- overlap
    sid = data["stores"].set_index("store_key")["store_id"]
    sch = data["store_category_h2"]
    py_net = sch[sch["retail_year"] == pyr].assign(store_id=lambda d: d["store_key"].map(sid)).groupby("store_id")["net_revenue"].sum()
    control = sc["groups"][prim]
    lost = el["lost"]
    lost_cat = lost[lost["category"] == el["category"]].assign(store_id=lambda d: d["store_key"].map(sid))
    lp = lost_cat.groupby(["store_id", "retail_year"])["est_lost_sales_eur"].sum().unstack().reindex(columns=[pyr, cyr]).fillna(0)
    so_store = -(lp[cyr] - lp[pyr])
    fs = rt["by_store"].set_index("store_id")["value_change"]
    promo_store = pr["by_store"].set_index("store_id")["m1_effect_eur"]
    d_so = OV.cluster_overlap(so_store, py_net, cluster, control)
    d_fr = OV.cluster_overlap(-fs, py_net, cluster, control)
    d_pr = OV.cluster_overlap(promo_store, py_net, cluster, control)
    d_so["basis"] = "Full-week lost sales change (ESTIMATE), all stores, minus the cluster's above-control share"
    d_fr["basis"] = "'Faulty' refund change in the category, minus the cluster's above-control share"
    d_pr["basis"] = "M1 category DiD effect, minus the cluster's above-control share"
    attr = OV.exclusive_attribution(total, R["central"]["cluster_excess"],
                                    {f"{el['category']} full-week stock-outs (ESTIMATE)": d_so,
                                     f"{rt['category']} '{rt['reason']}' returns increase": d_fr,
                                     f"{pr['category']} category-specific change (promotion period)": d_pr})
    cats = {el["category"]: [el["category"]], pr["category"]: [pr["category"]]}
    perim = OV.perimeter_matrix(sch, data["stores"], cluster, cats, pyr, cyr)
    # where the residual sits: outside the cluster, each category group's change minus the drivers measured there;
    # the remainder is the cluster's change at the control-store rate net of its driver amounts
    pc = perim.set_index(["store_group", "category_group"])["net_revenue_change"]
    nc = lambda s_: float(s_[~s_.index.isin(cluster)].sum())  # noqa: E731
    resid = float(attr.iloc[-1]["amount_eur"])
    rb = [{"part": f"Other stores: {el['category']} change not explained by stock-outs or 'Faulty' returns",
           "amount_eur": float(pc[("Other stores", el["category"])]) - nc(so_store) - nc(-fs.reindex(py_net.index).fillna(0))},
          {"part": f"Other stores: {pr['category']} change not explained by the category-specific (M1) change",
           "amount_eur": float(pc[("Other stores", pr["category"])]) - nc(promo_store)},
          {"part": "Other stores: other categories (no driver identified)",
           "amount_eur": float(pc[("Other stores", "Other categories")])}]
    rb.append({"part": "Store cluster: change at the control-store rate, net of the cluster's driver amounts",
               "amount_eur": resid - sum(r["amount_eur"] for r in rb)})
    residual_breakdown = pd.DataFrame(rb)
    residual_breakdown["share_of_residual"] = residual_breakdown["amount_eur"] / resid
    # pairwise: stock-outs x faulty returns on the same store-SKUs (different ledger lines, reported for transparency)
    fr_sku = rt["faulty"].groupby(["store_id", "product_id", "return_retail_year"])["refund_value"].sum().unstack().fillna(0)
    fr_up = fr_sku[(fr_sku.get(cyr, 0) - fr_sku.get(pyr, 0)) > 0].index
    lc = lost_cat.groupby(["store_id", "product_id", "retail_year"])["est_lost_sales_eur"].sum().unstack().reindex(
        columns=[pyr, cyr]).fillna(0)
    lc_ch = -(lc[cyr] - lc[pyr])
    so_on_fr_skus = float(lc_ch[lc_ch.index.isin(fr_up)].sum())
    items = {
        "Store-cluster excess": {"amount": R["central"]["cluster_excess"],
                                 "overlaps": {"E&T stock-outs": d_so["overlap_with_cluster_excess"],
                                              "E&T faulty returns": d_fr["overlap_with_cluster_excess"],
                                              "H&K promotion period": d_pr["overlap_with_cluster_excess"]}},
        "E&T stock-outs": {"amount": d_so["total"], "overlaps": {"E&T faulty returns": 0.0, "H&K promotion period": 0.0}},
        "E&T faulty returns": {"amount": d_fr["total"], "overlaps": {"H&K promotion period": 0.0}},
        "H&K promotion period": {"amount": d_pr["total"], "overlaps": {}},
    }
    R["overlap"] = {"attribution": attr, "perimeter": perim, "pairwise": OV.pairwise_matrix(items),
                    "details": pd.DataFrame([{"driver": k, **{kk: vv for kk, vv in v.items() if kk != 'basis'}}
                                             for k, v in (("E&T stock-outs", d_so), ("E&T faulty returns", d_fr),
                                                          ("H&K promotion period", d_pr))]),
                    "stockouts_on_faulty_return_skus": so_on_fr_skus, "residual_breakdown": residual_breakdown}
    log("overlap and exclusive attribution built")

    # ---- scenario inputs
    sd = data["store_day"]
    h1 = sd[sd["retail_week"] <= 26].groupby(["store_id", "retail_year"])["transactions"].sum().unstack()
    h2 = sd[sd["retail_week"].between(wf, wt)].groupby(["store_id", "retail_year"])[
        ["transactions", "sales_revenue", "returns_value", "net_revenue", "gross_margin"]].sum().unstack()
    t_cf = h2[("transactions", pyr)] * h1[cyr] / h1[pyr]
    net_per_tx = h2[("net_revenue", cyr)] / h2[("transactions", cyr)]
    gm_rate = h2[("gross_margin", cyr)] / h2[("net_revenue", cyr)]
    a2 = float(((t_cf - h2[("transactions", cyr)]) * net_per_tx).sum())
    R["scenario_a2"] = {"revenue_impact": a2, "margin_impact": float(((t_cf - h2[("transactions", cyr)]) * net_per_tx * gm_rate).sum())}
    rr_py = py["returns_value"] / py["sales_revenue"]
    c_rev = cy["returns_value"] - rr_py * cy["sales_revenue"]
    rd = data["return_detail"]
    rdh = rd[rd["return_retail_week"].between(wf, wt) & (rd["return_retail_year"] == cyr)]
    restock_ratio = float(rdh["restock_cost_credit"].sum() / rdh["refund_value"].sum())
    R["scenario_c"] = {"revenue_impact": c_rev, "margin_impact": c_rev * (1 - restock_ratio),
                       "faulty_only": -R["central"]["faulty_returns"]}
    et = sch[(sch["category"] == el["category"]) & (sch["retail_year"] == cyr)]
    R["et_line_margin_rate"] = float(1 - et["cogs"].sum() / et["sales_revenue"].sum())
    rc = read_csv("reports/phase5/range_change.csv", cfg)
    rce = rc[rc["category"] == el["category"]].set_index("status")
    R["range_summary"] = {"text": "; ".join(f"{s}: {int(r.products)} SKUs, change EUR {r.net_revenue_change:,.0f}"
                                            for s, r in rce.iterrows())}

    # ---- sensitivity, scenarios, evidence
    R["sensitivity"], R["sensitivity_summary"] = SE.run(data, cfg, R, pyr, cyr, wf, wt, cluster)
    log(f"sensitivity: {len(R['sensitivity'])} variants")
    R["scenarios"] = SN.build(R)
    R["evidence"] = EV.build(R)
    return R


def checks(R: dict, cfg: dict) -> pd.DataFrame:
    rows = []

    def add(group, check, value, ref, tol, passed=None):
        diff = abs(value - ref) if isinstance(value, (int, float)) and isinstance(ref, (int, float)) else np.nan
        rows.append({"group": group, "check": check, "value": value, "reference": ref, "difference": diff, "tolerance": tol,
                     "status": "PASS" if (passed if passed is not None else diff <= tol) else "FAIL"})
    for r in R["headline_recon"].itertuples():
        add("Headline", r.check, r.recomputed, r.reference, r.tolerance, r.status == "PASS")
    total = R["cy"]["net_revenue"] - R["py"]["net_revenue"]
    perim = R["overlap"]["perimeter"]
    add("Overlap", "store group x category cells add up to the total change", float(perim["net_revenue_change"].sum()), total, 0.01)
    attr = R["overlap"]["attribution"]
    add("Overlap", "exclusive attribution closes exactly to the total change", float(attr["amount_eur"].sum()), total, 0.01)
    add("Overlap", "residual breakdown closes to the residual", float(R["overlap"]["residual_breakdown"]["amount_eur"].sum()),
        float(attr.iloc[-1]["amount_eur"]), 0.01)
    for r in R["overlap"]["details"].itertuples():
        add("Overlap", f"{r.driver}: exclusive amount never exceeds the measured total", abs(r.exclusive), abs(r.total), 0,
            abs(r.exclusive) <= abs(r.total) + 1e-9)
    per = R["periods"]
    add("Periods", "rca SQL H2 window (retail weeks 27-52, hard-coded in v_store_category_h2) matches the configuration",
        f"{per.week_from}-{per.week_to}", "27-52", 0, (per.week_from, per.week_to) == (27, 52))
    for r in R["overlap"]["details"].itertuples():
        add("Overlap", f"{r.driver}: exclusive = total - overlap with cluster excess", r.exclusive,
            r.total - r.overlap_with_cluster_excess, 1e-6)
    pw = R["overlap"]["pairwise"]
    add("Overlap", "pairwise matrix is symmetric", float((pw - pw.T).abs().to_numpy().max()), 0.0, 1e-9)
    sc = R["store_cluster"]
    prim = sc["primary_control"]
    add("Store cluster", "controls exclude every cluster store", len(set(sc["groups"][prim]) & set(R["cluster"])), 0, 0)
    add("Store cluster", "matched control group has the configured size", len(sc["groups"]["matched"]),
        cfg["rca"]["store_cluster"]["matched_k"], 0)
    e = sc["eur"][prim]["net_revenue"]
    add("Store cluster", "ratio DiD: actual - counterfactual = excess", e["actual"] - e["counterfactual"], e["excess"], 1e-6)
    wk = sc["weekly"]
    cl_w = wk[wk["store_id"].isin(R["cluster"]) & wk["retail_week"].between(27, 52)]
    add("Store cluster", "cluster H2 net revenue in the weekly panel = governed store view",
        float(cl_w["net_revenue"].sum()),
        float(R["data"]["segment_contribution"].query("segment_type == 'Store' and segment_name in @R['cluster']")["net_revenue_cy"].sum()),
        0.01)
    el = R["electronics"]
    add("Electronics", "lost-sales estimates never negative", float(np.nanmin(el["lost"]["est_lost_sales_eur"])), 0.0, 0,
        bool(np.nanmin(el["lost"]["est_lost_sales_eur"]) >= 0))
    p5 = read_csv("reports/phase5/availability_diagnostics.csv", cfg)
    p5e = p5[(p5["level"] == "Category") & (p5["key"] == el["category"])].iloc[0]
    add("Electronics", "category full-week lost sales equal the frozen Phase 5 figure",
        el["totals_category"]["primary_cy"], float(p5e["est_lost_sales_cy_ESTIMATE"]), 0.01)
    sup = el["by_supplier_category"]
    add("Electronics", "supplier lost-sales shares add up to 100%", float(sup["share_of_lost_primary_change"].sum()), 1.0, 1e-9)
    rt = R["returns"]
    add("Returns", "store faulty-return changes add up to the category change", float(rt["by_store"]["value_change"].sum()),
        -R["central"]["faulty_returns"], 0.01)
    add("Returns", "product faulty-return changes add up to the category change", float(rt["by_product"]["value_change"].sum()),
        -R["central"]["faulty_returns"], 0.01)
    pr = R["promotions"]
    add("Promotions", "M1 bootstrap CI contains the point estimate", pr["m1"]["effect_eur"], pr["m1"]["effect_eur"], 0,
        pr["m1"]["ci_eur"][0] <= pr["m1"]["effect_eur"] <= pr["m1"]["ci_eur"][1])
    add("Promotions", "M1 by-store effects add up to the category effect", float(pr["by_store"]["m1_effect_eur"].sum()),
        pr["m1"]["effect_eur"], 0.01)
    ev = R["evidence"]
    add("Evidence", "every driver has one BRD evidence level", int((~ev["evidence_level"].isin(EV.LEVELS)).sum()), 0, 0)
    add("Evidence", "no fragile estimate is labelled Root-cause evidence",
        int(((ev["evidence_level"] == "Root-cause evidence") &
             ev["driver_id"].map({"D03": "electronics_stockouts_primary", "D07": "home_kitchen_promotion"}).map(
                 R["sensitivity_summary"].set_index("driver")["robust"]).eq(False)).sum()), 0, 0)
    add("Sensitivity", "every central estimate has variants", int(R["sensitivity_summary"]["n_variants"].min()), 3, 0,
        int(R["sensitivity_summary"]["n_variants"].min()) >= 3)
    sn = R["scenarios"]
    add("Scenarios", "scenario E equals the sum of the exclusive components",
        float(sn.set_index("scenario").loc["E", "revenue_impact_eur"]), -float(attr["amount_eur"].iloc[:-1].sum()), 0.01)
    inf = 0
    for k, v in R.items():
        if isinstance(v, pd.DataFrame):
            num = v.select_dtypes(include=[np.number])
            inf += int(np.isinf(num.to_numpy(dtype=float)).sum()) if not num.empty else 0
    add("Robustness", "no infinite values in result tables", inf, 0, 0)
    return pd.DataFrame(rows)


_HOOKED = False


def run(engine_name: str = "duckdb", out_dir: Path | None = None, make_figures: bool = True) -> dict:
    global _HOOKED
    if not _HOOKED:
        sys.addaudithook(OpenRecorder.hook)
        _HOOKED = True
    OpenRecorder.paths = []
    OpenRecorder.active = True
    log = Log()
    t0 = time.time()
    try:
        cfg = load_config()
        out = Path(out_dir) if out_dir else PROJECT_ROOT / cfg["rca"]["outputs"]["reports"]
        out.mkdir(parents=True, exist_ok=True)
        freeze = verify_freeze(cfg)
        log(f"freeze verified: {len(freeze)} Phase 1-5 files unchanged")
        engine, info, sql_log = open_rca_model(engine_name, cfg, out)
        try:
            R = analyse(engine, cfg, log)
        finally:
            engine.close()
        ch = checks(R, cfg)
        log(f"checks: {(ch['status'] == 'PASS').sum()}/{len(ch)} pass")
        from .report import write_outputs
        files, figs = write_outputs(R, ch, freeze, out, make_figures)
        OpenRecorder.active = False
        opened = classify_opened(OpenRecorder.summary())
        meta = {"run_at": datetime.now().isoformat(timespec="seconds"), "runtime_seconds": round(time.time() - t0, 1),
                "engine": info["engine"], "sql": sql_log}
        from .report import validation_report
        (out / "phase6_validation_report.md").write_text(validation_report(R, ch, freeze, files, figs, opened, meta),
                                                         encoding="utf-8")
        passed = bool((ch["status"] == "PASS").all()) and not opened["refused"]
        log(f"{'PASSED' if passed else 'FAILED'}; outputs in {out}")
        (out / "phase6_run_log.txt").write_text("\n".join(log.lines) + "\n", encoding="utf-8")
        return {"passed": passed, "R": R, "checks": ch, "files": files, "figures": figs, "opened": opened, "out": out}
    finally:
        OpenRecorder.active = False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["mssql", "duckdb"], default="mssql")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--record-freeze", action="store_true")
    a = ap.parse_args()
    if a.record_freeze:
        df = record_freeze(load_config())
        print(f"recorded {len(df)} files")
        return
    try:
        res = run(a.engine, a.out_dir, not a.no_figures)
    except (InputError, Phase6Stop) as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        sys.exit(1)
    if not res["passed"]:
        print(res["checks"][res["checks"]["status"] != "PASS"].to_string(index=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
