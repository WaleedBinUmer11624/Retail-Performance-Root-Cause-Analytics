"""Phase 9 runner: operational monitoring, early warning and anomaly detection (back-test replay).

Usage (from the project root):
    python -m src.monitoring.run_phase9 --engine duckdb    # rebuild the Phase 4 model locally, add the mon views
    python -m src.monitoring.run_phase9                    # use the SQL Server model built by Phase 4
    python -m src.monitoring.run_phase9 --record-freeze    # record the Phase 1-8 manifest (once, at phase start)

Stops (exit 1) if any Phase 1-8 file changed or the monitoring KPIs do not reconcile to Phases 4-7. Replays the weekly
run for every complete retail week (each week as the Monday 06:00 run would have seen it), back-tests every candidate
rule, selects one rule per signal without using the known episodes, scores severity, applies the DQ gate and writes
the alert tables, evaluation tables, figures and reports to reports/phase9/. Nothing is deployed.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.analytics.model_access import PROJECT_ROOT, InputError
from src.analytics.run_phase5 import OpenRecorder

from . import alerts as AL
from . import backtest as BT
from . import baselines as BL
from . import context as CX
from . import dq as DQ
from . import evaluate as EV
from . import figures as FG
from . import kpis as K
from . import report as RP
from . import signals as S
from .access import classify_opened, load_config, load_monitoring_tables, read_csv, record_freeze, verify_freeze

SIGNAL_ORDER = ["EW01", "EW02", "EW03", "EW04", "EW05", "EW06", "EW07", "EW08"]
FIGURES = {
    "transactions": "figures/p9_01_weekly_transactions_early_warning.png",
    "cluster": "figures/p9_02_s03_s05_detection_timeline.png",
    "availability": "figures/p9_03_availability_early_warning.png",
    "stockouts": "figures/p9_04_top_seller_stockout_early_warning.png",
    "returns": "figures/p9_05_faulty_return_early_warning.png",
    "margin": "figures/p9_06_margin_early_warning.png",
    "severity": "figures/p9_07_alert_severity_distribution.png",
    "sensitivity": "figures/p9_08_threshold_sensitivity.png",
    "heatmap": "figures/p9_09_alert_heatmap_store_week.png",
    "dq": "figures/p9_10_dq_health.png",
}
DOC = "docs/09_monitoring_early_warning.md"
FORBIDDEN = ["supplier defect detected", "defect detected", "caused by", "proves", "proof of", "root cause is",
             "voltix caused", "because of voltix", "promotion caused", chr(0x2014)]


class Phase9Stop(RuntimeError):
    pass


class Log:
    def __init__(self):
        self.t0, self.lines = time.time(), []

    def __call__(self, msg):
        line = f"[{time.time() - self.t0:7.1f}s] {msg}"
        self.lines.append(line)
        print(line, flush=True)


def _w(df: pd.DataFrame, path: Path):
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(6)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- analysis (no file writes)
def build_signals(T: dict, cfg: dict) -> dict:
    W = K.weekly_tables(T)
    rec = K.reconcile(W, cfg)
    dq = DQ.dq_store_week(T, W, cfg)
    est = DQ.estate_dq(dq, inventory_warn_share=cfg["monitoring"]["dq"]["estate_inventory_warn_share"])
    sku = read_csv("reports/phase6/electronics_sku_stockouts.csv", cfg)
    p6 = sorted(sku.loc[sku["full_cy"] > 0, "product_id"])
    frames = {
        "EW01": S.ew01(T, W, dq, cfg), "EW02": S.ew02(T, W, dq, cfg), "EW03": S.ew03(T, W, est, cfg),
        "EW04": S.ew04(T, W, est, cfg, p6), "EW05": S.ew05(T, W, dq, est, cfg), "EW06": S.ew06(T, W, est, cfg),
        "EW07": S.ew07(T, W, est, cfg), "EW08": S.ew08(dq, cfg),
    }
    return {"W": W, "reconciliation": rec, "dq": dq, "estate_dq": est, "frames": frames, "phase6_skus": p6}


def _score_all(frames: dict, sel: pd.DataFrame, cfg: dict) -> dict:
    scored = {}
    for r in sel.itertuples():
        f = frames[r.signal]
        f = f[f["entity_type"] == r.entity_type]
        scored[(r.signal, r.entity_type)] = AL.score(f, pd.Series(r._asdict()), cfg)
    return scored


def operational_burden(scored: dict) -> pd.DataFrame:
    """Unconfirmed WARNING+ rate of the rule as operated (primary rule, secondary change-point rule, record and
    continuation logic together), on the same non-episode, DQ-passed, evaluable entity-weeks as the selection."""
    rows = []
    for (sig, et), d in scored.items():
        ev = d["baseline_ok"].fillna(False).astype(bool) & ~d["dq_fail"].astype(bool) & ~d["in_episode"]
        u = ev & (d["level"] >= 2)
        rows.append({"signal": sig, "entity_type": et, "non_episode_entity_weeks": int(ev.sum()),
                     "operational_unconfirmed_warning_plus": int(u.sum()),
                     "operational_unconfirmed_rate": float(u.sum() / max(ev.sum(), 1))})
    return pd.DataFrame(rows)


def mask_sensitivity(frames: dict, R: pd.DataFrame, sel: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Review finding M4: the budget is measured on NON-episode entity-weeks, so the known episodes do shape the
    selection through that mask. This re-runs the selection with no mask (every alert counts as noise) and shows
    which rules would change and what detection they would give."""
    R0 = pd.concat([BT.run_candidates(frames[s].assign(in_episode=False), s, cfg) for s in SIGNAL_ORDER], ignore_index=True)
    s0 = BT.select(R0, cfg)
    key = ["signal", "entity_type"]
    rows = []
    for r in sel.itertuples():
        z = s0[(s0["signal"] == r.signal) & (s0["entity_type"] == r.entity_type)].iloc[0]
        det = R[(R["signal"] == r.signal) & (R["entity_type"] == r.entity_type) & (R["rule_column"] == z["rule_column"])
                & (R["persistence_weeks"] == z["persistence_weeks"])].iloc[0]
        rows.append({"signal": r.signal, "entity_type": r.entity_type,
                     "rule_with_episode_mask": f"{r.family}: {r.threshold}, {int(r.persistence_weeks)} wk",
                     "rule_without_mask": f"{z['family']}: {z['threshold']}, {int(z['persistence_weeks'])} wk",
                     "same_rule": bool(z["rule_column"] == r.rule_column and z["persistence_weeks"] == r.persistence_weeks),
                     "non_episode_entity_weeks": int(r.non_episode_entity_weeks),
                     "budget_measurable": bool(r.non_episode_entity_weeks * cfg["monitoring"]["selection"]["warning_budget"] >= 1),
                     "detected_with_mask": f"{int(r.episode_entities_detected)}/{int(r.episode_entities)}",
                     "delay_with_mask": r.median_detection_delay_weeks,
                     "detected_without_mask": f"{int(det['episode_entities_detected'])}/{int(det['episode_entities'])}",
                     "delay_without_mask": det["median_detection_delay_weeks"]})
    return pd.DataFrame(rows)


def severity_sensitivity(frames: dict, sel: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Review finding m4: how many WARNING+ and CRITICAL entity-weeks each CRITICAL criterion setting produces."""
    import copy
    base = cfg["monitoring"]["severity"]
    variants = [("as configured", {}), ("persistence 3 weeks", {"critical_persistence_weeks": 3}),
                ("persistence 6 weeks", {"critical_persistence_weeks": 6}),
                ("breadth rule off", {"critical_breadth_entities": 10 ** 6}), ("breadth 5 entities", {"critical_breadth_entities": 5}),
                ("exposure 0.5 week", {"critical_exposure_weeks_of_revenue": 0.5}),
                ("exposure 2 weeks", {"critical_exposure_weeks_of_revenue": 2.0}),
                ("exposure rule off", {"critical_exposure_weeks_of_revenue": 10 ** 6}),
                ("record rule off", {"record_min_history": 10 ** 9})]
    rows = []
    for name, ch in variants:
        c = copy.deepcopy(cfg)
        c["monitoring"]["severity"] = {**base, **ch}
        sc = _score_all(frames, sel, c)
        for (sig, et), d in sc.items():
            ev = d["baseline_ok"].fillna(False).astype(bool)
            rows.append({"variant": name, "signal": sig, "entity_type": et,
                         "warning_plus": int(((d["level"] >= 2) & ev).sum()), "critical": int(((d["level"] >= 3) & ev).sum()),
                         "critical_unconfirmed": int(((d["level"] >= 3) & ev & ~d["in_episode"]).sum())})
    return pd.DataFrame(rows)


def knob_sensitivity(T: dict, B: dict, R: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Review follow-up N2: the baseline freeze (EW01, EW02) and the EW03 trailing guard were added after the review;
    this re-runs those signals and their selection under neighbouring settings."""
    import copy
    W, dq, est = B["W"], B["dq"], B["estate_dq"]
    variants = [("as configured", {}), ("hold release 2 weeks", {"hold_release_weeks": 2}),
                ("hold release 6 weeks", {"hold_release_weeks": 6}), ("release z -1.5", {"hold_release_z": -1.5}),
                ("release z -0.5", {"hold_release_z": -0.5}), ("no freeze", {"hold_release_weeks": 0}),
                ("EW03 guard 0.5pp", {"trailing_guard_pp": 0.5}), ("EW03 guard 2pp", {"trailing_guard_pp": 2.0}),
                ("EW03 no guard", {"trailing_guard_pp": 1000.0})]
    rows = []
    for name, ch in variants:
        c = copy.deepcopy(cfg)
        c["monitoring"]["baseline"].update(ch)
        fr = {"EW01": S.ew01(T, W, dq, c), "EW02": S.ew02(T, W, dq, c), "EW03": S.ew03(T, W, est, c)}
        Rv = pd.concat([BT.run_candidates(f, s, c) for s, f in fr.items()], ignore_index=True)
        for r in BT.select(Rv, c).itertuples():
            rows.append({"variant": name, "signal": r.signal, "entity_type": r.entity_type,
                         "selected_rule": f"{r.family}: {r.threshold}, {int(r.persistence_weeks)} wk",
                         "unconfirmed_rate": r.unconfirmed_rate, "alerts": int(r.alerts),
                         "detected": f"{int(r.episode_entities_detected)}/{int(r.episode_entities)}",
                         "median_delay_weeks": r.median_detection_delay_weeks,
                         "episode_weeks_active_share": r.episode_weeks_active_share})
    return pd.DataFrame(rows)


def evaluate(T: dict, B: dict, cfg: dict, extra: bool = True) -> dict:
    frames, W = B["frames"], B["W"]
    cal = W["calendar"]
    R = pd.concat([BT.run_candidates(frames[s], s, cfg) for s in SIGNAL_ORDER], ignore_index=True)
    sel = BT.select(R, cfg)
    sec = BT.select_secondary(R, cfg)
    sel["confirm_column"], sel["confirm_threshold"], sel["confirm_unconfirmed_rate"] = None, None, np.nan
    for r in sec.itertuples():
        m = (sel["signal"] == r.signal) & (sel["entity_type"] == r.entity_type)
        sel.loc[m, "confirm_column"] = r.rule_column
        sel.loc[m, "confirm_threshold"] = f"{r.family} delta {r.threshold}"
        sel.loc[m, "confirm_unconfirmed_rate"] = r.unconfirmed_rate
    scored = _score_all(frames, sel, cfg)
    burden = operational_burden(scored)
    sel = sel.merge(burden[["signal", "entity_type", "operational_unconfirmed_rate"]], on=["signal", "entity_type"], how="left")
    A = AL.alert_table(scored, cfg, T["week_calendar"])
    summ = AL.alert_summary(A, sel, scored).merge(burden, on=["signal", "entity_type"], how="left")
    ew01_sel = sel[sel["signal"] == "EW01"].iloc[0]
    cl = BT.cluster_detection(frames["EW01"], R[R["signal"] == "EW01"], ew01_sel, cal, cfg, ew01_sel["confirm_column"])
    op = EV.operational_detection(scored[("EW01", "store")], A, cal, cfg)
    base = BT.baseline_comparison(T, W, B["dq"], frames["EW01"], cfg)
    maps = EV.related_entities(T)
    fp_detail, fp_summary = EV.false_positive_analysis(A, cal, maps)
    delta = int(str(ew01_sel["confirm_column"]).replace("b_cp", "")) if isinstance(ew01_sel["confirm_column"], str) else 6
    cp = EV.changepoint_estimates(frames["EW01"], cal, delta=delta)
    E = {"results": R, "selected": sel, "secondary": sec, "scored": scored, "alerts": A, "summary": summ, "cluster": cl,
         "operational": op, "baselines": base, "fp_detail": fp_detail, "fp_summary": fp_summary, "changepoints": cp,
         "sensitivity": BT.sensitivity_view(R)}
    if extra:
        E["mask_sensitivity"] = mask_sensitivity(frames, R, sel, cfg)
        E["severity_sensitivity"] = severity_sensitivity(frames, sel, cfg)
        E["knob_sensitivity"] = knob_sensitivity(T, B, R, cfg)
    return E


# ----------------------------------------------------------------------------- dictionaries
PHASE8_ADAPTATION = {
    "EW01": ("IMPLEMENTED WITH ADAPTATION",
             "Phase 8 named 'matched peer stores' without defining them; the peer group is every other store "
             "(leave-one-out), excluding DQ-failed stores. Two rules raise WARNING, each selected on the same noise budget: "
             "the peer-gap threshold with persistence, and the Phase 8 change-point test (weekly series, switched off "
             "once the store is back within half the step). CRITICAL needs both to agree in the same week, or the "
             "persistence, breadth or exposure criteria."),
    "EW02": ("IMPLEMENTED WITH ADAPTATION",
             "Same concept (YoY against its recent range) with a robust statistic (median and MAD). Region and format "
             "grains added, as the Phase 9 brief requires."),
    "EW03": ("IMPLEMENTED WITH ADAPTATION",
             "Below BOTH baselines, as in Phase 8. The back-test selected 2 consecutive weeks instead of the concept's 4 "
             "(4 weeks is in the sensitivity table)."),
    "EW04": ("IMPLEMENTED WITH ADAPTATION",
             "Full-week stock-outs of the top 10% of SKUs, as in Phase 8. Weeks of cover not implemented: it needs "
             "daily demand and open orders (Phase 8 data requirement). The baseline is zero stock-outs, the same test "
             "as the Phase 8 threshold concept."),
    "EW05": ("IMPLEMENTED WITH ADAPTATION",
             "Phase 8 proposed store-month; Phase 9 requires the retail week, so a trailing 4-week window is tested "
             "weekly against the same 4 weeks last year (return-date basis). Supplier and product splits are context "
             "(ew05_return_context.csv), not separate alerts. An estate category level is added."),
    "EW06": ("IMPLEMENTED", "Gross margin % of 4-week windows against the same weeks last year; GM EUR change reported "
             "beside it and tracked separately from revenue."),
    "EW07": ("IMPLEMENTED WITH ADAPTATION",
             "The approved promotion plan (DR29) does not exist, so the prior year is the baseline, as Phase 8 allows "
             "until then. Discount rate is the alert metric; promotion share and promotion lines are context."),
    "EW08": ("IMPLEMENTED WITH ADAPTATION",
             "Phase 8 proposed a daily store-day check; the weekly run applies a store-week gate whose first check (C1) "
             "counts trading days with no sales, so a day-level gap is caught. A daily run would reuse C1 per day."),
}


def signal_dictionary(cfg: dict, sel: pd.DataFrame) -> pd.DataFrame:
    p8 = read_csv("reports/phase8/phase8_early_warning_requirements.csv", cfg).set_index("signal_id")
    rows = []
    for sid in SIGNAL_ORDER:
        s = cfg["monitoring"]["signals"][sid]
        for r in sel[sel["signal"] == sid].itertuples():
            st, dev = PHASE8_ADAPTATION[sid]
            rows.append({
                "signal": sid, "entity_type": r.entity_type, "name": s["name"],
                "phase8_metric": p8.loc[sid, "metric"], "phase8_grain": p8.loc[sid, "grain"],
                "phase8_baseline": p8.loc[sid, "baseline_concept"], "phase8_threshold": p8.loc[sid, "threshold_concept"],
                "implemented_metric": s["metric"], "grain": s["grain"], "grain_reason": s["grain_reason"],
                "baseline": s["baseline"], "selected_rule": f"{r.family}: {r.threshold}, {int(r.persistence_weeks)} week(s)",
                "selection_reason": r.selection_reason, "within_budget": r.within_budget,
                "unconfirmed_rate": r.unconfirmed_rate, "evidence_level": s["evidence_level"],
                "alert_class": s["alert_class"], "message": s["wording"], "proposed_owner": s["owner"] + " (PROPOSED)",
                "data_required": s["data_required"], "phase8_status": st, "adaptation": dev,
            })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- checks
def no_leakage_check(B: dict, cfg: dict, cut_t: int | None = None) -> bool:
    """Perturb every EW01 value after a cut-off week; the baselines, z-scores and change-point statistics up to the cut
    must not move (walk-forward, no leakage)."""
    f = B["frames"]["EW01"].copy()
    bl = cfg["monitoring"]["baseline"]
    cut = cut_t or int(f["t"].quantile(0.6))
    g = f[["entity", "t", "value", "dq_fail"]].copy()
    g2 = g.copy()
    g2.loc[g2["t"] > cut, "value"] = g2.loc[g2["t"] > cut, "value"] - 5.0
    kw = dict(trailing=bl["trailing_weeks"], min_valid=bl["min_valid_weeks"], exclude_low=bl["guard_z_adverse"],
              exclude_high=bl["guard_z_other"], hold_release_weeks=bl["hold_release_weeks"], hold_release_z=bl["hold_release_z"])
    a, b = BL.robust_walk_forward(g, **kw), BL.robust_walk_forward(g2, **kw)
    a, b = a[a["t"] <= cut].sort_values(["entity", "t"]), b[b["t"] <= cut].sort_values(["entity", "t"])
    ok = np.allclose(a["baseline"].fillna(-9), b["baseline"].fillna(-9)) and np.allclose(a["z"].fillna(-9), b["z"].fillna(-9))
    c = S.online_changepoint(g.assign(), cfg["monitoring"]["signals"]["EW01"]["candidates"]["changepoint_min_segment"], [6])
    d = S.online_changepoint(g2.assign(), cfg["monitoring"]["signals"]["EW01"]["candidates"]["changepoint_min_segment"], [6])
    c, d = c[c["t"] <= cut].sort_values(["entity", "t"]), d[d["t"] <= cut].sort_values(["entity", "t"])
    return bool(ok and np.allclose(c["cp_stat"].fillna(-9), d["cp_stat"].fillna(-9)))


def validation_checks(T, B, E, cfg, freeze, fig_paths, text_outputs: dict, opened: dict | None) -> pd.DataFrame:
    A, sel, dq = E["alerts"], E["selected"], B["dq"]
    cal = T["week_calendar"]
    rows = []

    def add(cid, name, ok, detail=""):
        rows.append({"check_id": cid, "check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    add("V01", "Phase 1-8 files unchanged since the Phase 9 freeze", (freeze["status"] == "UNCHANGED").all(),
        f"{len(freeze)} files")
    rec = B["reconciliation"]
    add("V02", "Monitoring KPIs reconcile to Phases 4-7", (rec["status"] == "PASS").all(),
        f"{int((rec['status'] == 'PASS').sum())}/{len(rec)}")
    add("V03", "alert_id is unique", A["alert_id"].is_unique, f"{len(A)} alerts")
    add("V04", "Every alert has a valid severity and lifecycle status NEW",
        A["severity"].isin(["WATCH", "WARNING", "CRITICAL"]).all() and (A["status"] == "NEW").all())
    fail_keys = set(zip(dq.loc[dq["dq_sales_status"] == "FAIL", "store_id"], dq.loc[dq["dq_sales_status"] == "FAIL", "retail_week_key"]))
    held_ok = A.loc[A["dq_hold"], "severity"].eq("WATCH").all()
    store_fail = A[(A["entity_type"] == "store") & (A["signal"] != "EW08")]
    in_fail = [(e, k) in fail_keys for e, k in zip(store_fail["entity_id"], store_fail["retail_week_key"])]
    add("V05", "DQ gate: held alerts are capped at WATCH and no store alert above WATCH in a failed store-week",
        held_ok and store_fail.loc[in_fail, "severity"].eq("WATCH").all(), f"{int(A['dq_hold'].sum())} held")
    e8 = A[A["signal"] == "EW08"]
    add("V06", "EW08 alerts are exactly the failed store-weeks",
        set(zip(e8["entity_id"], e8["retail_week_key"])) == fail_keys, ", ".join(f"{s} {k}" for s, k in sorted(fail_keys)))
    w1 = cfg["monitoring"]["signals"]["EW01"]["wording"]
    w5 = cfg["monitoring"]["signals"]["EW05"]["wording"]
    add("V07", "Required wordings used (EW01 cause wording, EW05 faulty-return wording)",
        A.loc[A["signal"] == "EW01", "message"].str.contains("Cause not established from available internal data.", regex=False).all()
        and A.loc[A["signal"] == "EW05", "message"].str.contains(w5, regex=False).all() and w1.endswith(
            "Cause not established from available internal data."))
    blob = " ".join(A["message"].astype(str)).lower() + " " + " ".join(t.lower() for t in text_outputs.values())
    bad = [p for p in FORBIDDEN if p in blob]
    add("V08", "No causal, defect or supplier-blame wording and no em dash in alerts and reports", not bad, ", ".join(bad))
    add("V09", "No fabricated management responses (owner, acknowledged, resolved all empty)",
        (A["owner"] == "").all() and (A["acknowledged_at"] == "").all() and (A["resolved_at"] == "").all())
    add("V10", "Owners are proposed roles", A["proposed_owner"].str.endswith("(PROPOSED)").all())
    budget = cfg["monitoring"]["selection"]["warning_budget"]
    sec = E["secondary"]
    add("V11", "Every selected rule, the secondary change-point rule and each rule as operated stay inside the budget",
        sel["within_budget"].all() and sec["within_budget"].all() and (sel["operational_unconfirmed_rate"] <= budget).all(),
        "; ".join(f"{r.signal}/{r.entity_type} {r.unconfirmed_rate:.2%} (operated {r.operational_unconfirmed_rate:.2%})"
                  for r in sel.itertuples()))
    add("V12", "Selection reads only the noise budget: scrambling every detection metric (delay, coverage, exposure) "
        "gives the same rules (the episode mask's own effect is reported in selection_mask_sensitivity.csv)",
        _selection_independent(B, cfg, sel))
    add("V13", "No leakage: perturbing later weeks leaves earlier baselines, z-scores and change-point statistics unchanged",
        no_leakage_check(B, cfg))
    full = cal[(cal["days_in_week"] == 7)]["retail_week_key"]
    biz = A[A["signal"] != "EW08"]
    add("V14", "Week alignment: every alert is on a complete retail week; business alerts in 2025 (the year with a prior year)",
        A["retail_week_key"].isin(full).all() and biz["retail_week"].str.startswith("2025").all())
    c = cal[cal["retail_year"] == 2025].merge(cal[["retail_week_key", "retail_week"]].rename(
        columns={"retail_week_key": "py_week_key", "retail_week": "py_rw"}), on="py_week_key", how="left")
    add("V15", "Prior-year logic: each 2025 week maps to the same retail week of 2024", (c["retail_week"] == c["py_rw"]).all())
    add("V16", "Exposure is never totalled across signals (no all-signal total in any output)",
        "TOTAL" not in set(E["summary"]["signal"]))
    op = E["operational"]
    add("V17", "S03, S04 and S05 each detected by the operational EW01 rule",
        (op["first_detection_week"] != "not detected").all(),
        "; ".join(f"{r.store} {r.first_detection_week}" for r in op.itertuples()))
    add("V18", "Ten figures written", all(Path(p).exists() for p in fig_paths) and len(fig_paths) == 10)
    if opened is not None:
        add("V19", "No evaluation-only or refused path opened", not opened["refused"], ", ".join(opened["refused"]))
    if "context" in E:
        p6 = read_csv("reports/phase6/electronics_supplier_comparison.csv", cfg).set_index("supplier_name")
        sup = E["context"]["supplier"].set_index("supplier_name")
        v = "Voltix Distribution Ltd"
        ok = (abs(sup.loc[v, "full_week_stockout_cells_h2_2025"] - p6.loc[v, "full_week_out_cells_cy"]) < 1e-9 and
              abs(sup.loc[v, "full_week_stockout_cells_h2_2024"] - p6.loc[v, "full_week_out_cells_py"]) < 1e-9 and
              abs(sup.loc[v, "availability_h2_2025"] - p6.loc[v, "availability_cy"]) < 1e-6)
        add("V21", "Stock-out context reproduces Phase 6 supplier figures (Voltix full-week stock-outs and availability)", ok,
            f"Voltix full-week stock-out cells H2: {sup.loc[v, 'full_week_stockout_cells_h2_2024']:.0f} -> "
            f"{sup.loc[v, 'full_week_stockout_cells_h2_2025']:.0f}")
    lc = AL.lifecycle_table()
    add("V20", "Lifecycle has the seven required statuses",
        list(lc["status"]) == ["NEW", "ACKNOWLEDGED", "INVESTIGATING", "ACTIONED", "MONITORING", "RESOLVED", "FALSE POSITIVE"])
    return pd.DataFrame(rows)


def _selection_independent(B: dict, cfg: dict, sel: pd.DataFrame) -> bool:
    """The selection reads only the non-episode burden; scrambling which weeks are 'episode' changes the burden, so
    instead verify select() on results where every episode-derived column is overwritten gives the same rules."""
    R = pd.concat([BT.run_candidates(B["frames"][s], s, cfg) for s in SIGNAL_ORDER], ignore_index=True)
    ep_cols = [c for c in R.columns if c.startswith(("episode_", "median_detection", "max_detection", "known_episode",
                                                       "pre_onset"))]
    R2 = R.copy()
    rng = np.random.default_rng(0)
    for c in ep_cols:
        R2[c] = rng.random(len(R2))
    a = BT.select(R, cfg)[["signal", "entity_type", "rule_column", "persistence_weeks"]].reset_index(drop=True)
    b = BT.select(R2, cfg)[["signal", "entity_type", "rule_column", "persistence_weeks"]].reset_index(drop=True)
    return a.equals(b) and a.equals(sel[["signal", "entity_type", "rule_column", "persistence_weeks"]].reset_index(drop=True))


# ----------------------------------------------------------------------------- figures
def make_figures(T, B, E, cfg, out: Path) -> list:
    cal, sc, sel = B["W"]["calendar"], E["scored"], E["selected"].set_index(["signal", "entity_type"])
    ep1 = [e for e in cfg["monitoring"]["episodes"] if e["id"] == "EP1"][0]
    p = {k: out / v for k, v in FIGURES.items()}
    A = E["alerts"]

    def first(sig, et, ent, after=0):
        x = A[(A["signal"] == sig) & (A["entity_type"] == et) & (A["entity_id"] == ent) & A["severity"].isin(["WARNING", "CRITICAL"])
              & (A["retail_week_key"] >= after)]
        return x["retail_week"].min() if len(x) else "none"
    FG.fig_transactions(sc[("EW02", "estate")], cal, float(sel.loc[("EW02", "estate"), "threshold"]), p["transactions"],
                        first("EW02", "estate", "Estate"))
    FG.fig_cluster(sc[("EW01", "store")], cal, ep1["start_week"], float(sel.loc[("EW01", "store"), "threshold"]), p["cluster"])
    FG.fig_availability(sc[("EW03", "category")], cal, "Electronics & Tech", float(sel.loc[("EW03", "category"), "threshold"]),
                        p["availability"], first("EW03", "category", "Electronics & Tech"))
    e4 = A[A["signal"] == "EW04"].merge(T["kpi_product_week"][["product_id", "category"]].drop_duplicates(),
                                        left_on="entity_id", right_on="product_id")
    share = e4["category"].value_counts(normalize=True)
    note = f"{100 * share.iloc[0]:.0f}% of SKU alert-weeks in {share.index[0]}" if len(share) else "no alerts"
    FG.fig_stockouts(sc[("EW04", "product")], cal, p["stockouts"], note)
    ep3 = [e for e in cfg["monitoring"]["episodes"] if e["id"] == "EP3"][0]
    FG.fig_returns(sc[("EW05", "category")], cal, "Electronics & Tech", p["returns"],
                   first("EW05", "category", "Electronics & Tech"))
    FG.fig_margin(sc[("EW06", "category")], cal, ["Home & Kitchen", "Electronics & Tech"],
                  float(sel.loc[("EW06", "category"), "threshold"]), p["margin"])
    FG.fig_severity(E["summary"], p["severity"])
    s1 = sel.loc[("EW01", "store")]
    FG.fig_sensitivity(E["sensitivity"], s1["family"], {"thr": float(s1["threshold"])},
                       cfg["monitoring"]["selection"]["warning_budget"], p["sensitivity"])
    FG.fig_heatmap(sc[("EW01", "store")], cal, p["heatmap"])
    FG.fig_dq(B["dq"].merge(cal[["retail_week_key"]], on="retail_week_key"), cal, p["dq"])
    return list(p.values())


def monitoring_extract(E: dict) -> pd.DataFrame:
    """Power BI-ready fact: one row per evaluated signal x entity x week (value, baseline, severity, DQ)."""
    keep = ["signal", "entity_type", "entity", "retail_week_key", "value", "baseline", "deviation", "actual_value",
            "baseline_value", "exposure", "dq_status", "dq_hold", "in_episode", "severity", "persistence_weeks", "rule"]
    out = []
    for d in E["scored"].values():
        out.append(d[[c for c in keep if c in d.columns]])
    df = pd.concat(out, ignore_index=True).rename(columns={"entity": "entity_id", "in_episode": "known_episode_week"})
    return df.sort_values(["signal", "entity_type", "entity_id", "retail_week_key"]).reset_index(drop=True)


# ----------------------------------------------------------------------------- run
def run(engine_name: str = "duckdb", out_dir: Path | None = None, make_figs: bool = True, write_reports: bool = True) -> dict:
    if not getattr(run, "_hooked", False):
        sys.addaudithook(OpenRecorder.hook)
        run._hooked = True
    OpenRecorder.paths, OpenRecorder.active = [], True
    log, t0 = Log(), time.time()
    try:
        cfg = load_config()
        out = Path(out_dir) if out_dir else PROJECT_ROOT / cfg["monitoring"]["outputs"]["reports"]
        out.mkdir(parents=True, exist_ok=True)
        try:
            freeze = verify_freeze(cfg)
        except InputError as e:
            raise Phase9Stop(str(e)) from e
        log(f"freeze verified: {len(freeze)} Phase 1-8 files unchanged (Phase 8 manifest chain re-verified)")
        T, info, sql_log = load_monitoring_tables(engine_name, cfg, out / "model_build")
        log(f"model open ({engine_name}); monitoring SQL: {sum(s['batches'] for s in sql_log)} batches")
        B = build_signals(T, cfg)
        rec = B["reconciliation"]
        if not (rec["status"] == "PASS").all():
            raise Phase9Stop("monitoring KPIs do not reconcile:\n" + rec[rec["status"] != "PASS"].to_string(index=False))
        log(f"reconciliation: {len(rec)}/{len(rec)} PASS; DQ gate FAIL store-weeks: "
            f"{int((B['dq']['dq_sales_status'] == 'FAIL').sum())}")
        E = evaluate(T, B, cfg)
        A = E["alerts"]
        log(f"back-test: {len(E['results'])} candidate rules; {len(A)} alerts "
            + ", ".join(f"{k} {v}" for k, v in A["severity"].value_counts().items()))
        cal = B["W"]["calendar"]
        figs = make_figures(T, B, E, cfg, out) if make_figs else []
        if figs:
            log(f"figures: {len(figs)}")
        ctx = CX.return_context(T, cal, cfg)
        sku_ctx, sup_ctx = CX.stockout_context(T, E["scored"][("EW04", "product")], A, cal)
        E["context"] = {"sku": sku_ctx, "supplier": sup_ctx, "returns": ctx,
                        "margin": CX.margin_context(B["frames"]["EW06"], cal),
                        "promotion": CX.promotion_context(B["frames"]["EW07"], cal)}
        sigdict = signal_dictionary(cfg, E["selected"])
        tables = {
            "weekly_alerts.csv": A,
            "alert_summary.csv": E["summary"],
            "alert_backtest_results.csv": E["results"],
            "threshold_sensitivity.csv": E["sensitivity"],
            "signal_dictionary.csv": sigdict,
            "selected_rules.csv": E["selected"],
            "s03_s05_detection.csv": pd.concat([E["operational"], E["cluster"]], ignore_index=True),
            "selection_mask_sensitivity.csv": E["mask_sensitivity"],
            "severity_sensitivity.csv": E["severity_sensitivity"],
            "baseline_setting_sensitivity.csv": E["knob_sensitivity"],
            "baseline_comparison.csv": E["baselines"],
            "false_positive_analysis.csv": E["fp_detail"],
            "false_positive_summary.csv": E["fp_summary"],
            "changepoint_estimates.csv": E["changepoints"],
            "monitoring_kpi_dictionary.csv": K.kpi_dictionary(),
            "dq_check_catalogue.csv": DQ.check_catalogue(cfg),
            "dq_store_week_health.csv": B["dq"],
            "alert_lifecycle.csv": AL.lifecycle_table(),
            "ew04_sku_alert_context.csv": sku_ctx,
            "ew04_supplier_concentration.csv": sup_ctx,
            "ew05_return_context.csv": ctx,
            "ew06_margin_context.csv": E["context"]["margin"],
            "ew07_promotion_context.csv": E["context"]["promotion"],
            "reconciliation_checks.csv": rec,
            "input_verification.csv": freeze,
            "data/monitoring_signal_week.csv": monitoring_extract(E),
            "data/week_calendar.csv": T["week_calendar"],
        }
        for f, df in tables.items():
            _w(df, out / f)
        texts = {}
        if write_reports:
            texts["exec"] = RP.executive_summary(B, E, cfg)
            (out / "phase9_executive_summary.md").write_text(texts["exec"], encoding="utf-8")
        doc_path = PROJECT_ROOT / DOC
        if doc_path.exists():
            texts["doc"] = doc_path.read_text(encoding="utf-8")
        OpenRecorder.active = False
        opened = classify_opened(OpenRecorder.summary())
        checks = validation_checks(T, B, E, cfg, freeze, figs if make_figs else [out / v for v in FIGURES.values()],
                                   texts, opened)
        n_pass = int((checks["status"] == "PASS").sum())
        log(f"validation: {n_pass}/{len(checks)} checks pass")
        _w(checks, out / "phase9_validation_checks.csv")
        hashes = {f: _sha(out / f) for f in ["weekly_alerts.csv", "alert_summary.csv", "alert_backtest_results.csv"]}
        passed = n_pass == len(checks)
        meta = {"run_at": datetime.now().isoformat(timespec="seconds"), "runtime_seconds": round(time.time() - t0, 1),
                "engine": engine_name, "hashes": hashes}
        if write_reports:
            (out / "phase9_validation_report.md").write_text(RP.validation_report(B, E, cfg, checks, freeze, opened, meta),
                                                             encoding="utf-8")
        log(f"{'PASSED' if passed else 'FAILED'}; outputs in {out}")
        (out / "phase9_run_log.txt").write_text("\n".join(log.lines) + "\n", encoding="utf-8")
        return {"passed": passed, "checks": checks, "T": T, "B": B, "E": E, "freeze": freeze, "opened": opened,
                "out": out, "hashes": hashes}
    finally:
        OpenRecorder.active = False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--engine", default="sqlserver", choices=["duckdb", "sqlserver"])
    ap.add_argument("--record-freeze", action="store_true")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config()
    if a.record_freeze:
        m = record_freeze(cfg)
        print(f"recorded {len(m)} files in {cfg['monitoring']['inputs']['freeze_manifest']}")
        return 0
    try:
        r = run(a.engine, Path(a.out_dir) if a.out_dir else None, make_figs=not a.no_figures)
    except Phase9Stop as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
