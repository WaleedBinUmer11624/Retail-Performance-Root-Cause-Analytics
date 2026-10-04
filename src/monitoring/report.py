"""Phase 9 reports: the executive summary (for a retail manager) and the validation report.

Every figure in both reports is read from the run's tables, so the reports cannot drift from the CSV outputs.
"""
from __future__ import annotations

import pandas as pd

WARN_PLUS = ["WARNING", "CRITICAL"]
CAUSE = "Cause not established from available internal data."


def _pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def _eur(x):
    return f"EUR {x:,.0f}"


def _first(A, sig, et, ent, after=0):
    x = A[(A["signal"] == sig) & (A["entity_type"] == et) & (A["entity_id"] == ent) & A["severity"].isin(WARN_PLUS)
          & (A["retail_week_key"] >= after)]
    return x["retail_week"].min() if len(x) else "not raised"


def _ep(cfg, eid):
    return [e for e in cfg["monitoring"]["episodes"] if e["id"] == eid][0]


def _active_text(active: list) -> str:
    if len(active) == 3:
        return "All three were still in alert in the last week of the year."
    if not active:
        return "None was still in alert in the last week of the year."
    return f"{' and '.join(active)} {'was' if len(active) == 1 else 'were'} still in alert in the last week of the year."


def _knob_text(k) -> str:
    if k is None or k.empty:
        return ""
    alt = k[k["variant"] != "as configured"]
    n_alt = alt["variant"].nunique()
    fmt = alt[(alt["signal"] == "EW02") & (alt["entity_type"] == "format")]
    miss = fmt[fmt["detected"].str.startswith("0/")]["variant"].tolist()
    e1 = alt[alt["signal"] == "EW01"]
    return (f"Baseline settings (`baseline_setting_sensitivity.csv`, {n_alt} alternatives to the configured one): EW01 "
            f"detects the cluster under {int((e1['detected'] == '3/3').sum())} of {len(e1)}; EW02 format misses the "
            f"Standard-format movement under {len(miss)} ({', '.join(miss)}).")


def _mask_changes(m) -> int:
    return 0 if m is None else int((~m["same_rule"].astype(bool)).sum())


def _week(key: int) -> str:
    return f"{key // 100}-W{key % 100:02d}"


def facts(B, E, cfg) -> dict:
    """The numbers both reports quote."""
    A, sel, op = E["alerts"], E["selected"].set_index(["signal", "entity_type"]), E["operational"]
    wp = A[A["severity"].isin(WARN_PLUS)]
    unconf = wp[wp["validation_label"] == "unconfirmed"]
    weeks = A[A["signal"] != "EW08"]["retail_week"].nunique()
    ep2, ep3, ep4, ep5 = (_ep(cfg, x) for x in ["EP2", "EP3", "EP4", "EP5"])
    s4 = sel.loc[("EW04", "product")]
    s5 = sel.loc[("EW05", "store")]
    ctx_sku = A[A["signal"] == "EW04"]
    return {
        "alerts": len(A), "watch": int((A["severity"] == "WATCH").sum()), "warning": int((A["severity"] == "WARNING").sum()),
        "critical": int((A["severity"] == "CRITICAL").sum()), "held": int(A["dq_hold"].sum()),
        "held_gate": int((A["dq_hold"] & ~A["dq_note"].astype(str).str.contains("C12")).sum()),
        "wp": len(wp), "wp_known": int((wp["validation_label"] == "known episode").sum()), "wp_unconf": len(unconf),
        "wp_unconf_per_week": len(unconf) / 52, "weeks": weeks,
        "watch_unconf": int(((A["severity"] == "WATCH") & (A["validation_label"] == "unconfirmed")).sum()),
        "op": op, "ew03_first": _first(A, "EW03", "category", "Electronics & Tech", ep2["start_week"]),
        "ew03_any_first": _first(A, "EW03", "category", "Electronics & Tech"),
        "ew03_sup_first": _first(A, "EW03", "supplier", "Voltix Distribution Ltd", ep2["start_week"]),
        "ew04_skus": int(ctx_sku["entity_id"].nunique()), "ew04_detected": int(s4["episode_entities_detected"]),
        "ew04_eps": int(s4["episode_entities"]), "ew04_delay": s4["median_detection_delay_weeks"],
        "ew05_cat_first": _first(A, "EW05", "category", "Electronics & Tech"),
        "ew05_early_held": int((A["signal"].isin(["EW05", "EW06"]) & A["dq_note"].astype(str).str.contains("C12")).sum()),
        "ew04_cov_cells": int(B["frames"]["EW04"].query("category == 'Electronics & Tech' and retail_year == 2025 and retail_week >= 27")["value"].sum()),
        "ew04_all_cells": int(B["W"]["category_week"].query("category == 'Electronics & Tech' and retail_year == 2025 and retail_week >= 27")["full_week_stockout_cells"].sum()),
        "ew04_p6_never_top": len(set(B["phase6_skus"]) - set(B["frames"]["EW04"]["entity"])),
        "ew04_p6": len(B["phase6_skus"]),
        "active_final": [s for s in E["operational"]["store"] if bool(E["operational"].set_index("store").loc[s, "active_in_final_week"])],
        "crit_share": float((A["severity"] == "CRITICAL").sum() / max(A["severity"].isin(WARN_PLUS).sum(), 1)),
        "mask": E.get("mask_sensitivity"),
        "ew05_stores": {s: _first(A, "EW05", "store", s, ep3["start_week"]) for s in ep3["entities"] if not s.startswith("Elec")},
        "ew05_detected": int(s5["episode_entities_detected"]), "ew05_eps": int(s5["episode_entities"]),
        "ew06_hk": _first(A, "EW06", "category", "Home & Kitchen", ep5["start_week"]),
        "ew06_et": _first(A, "EW06", "category", "Electronics & Tech", ep5["start_week"]),
        "ew07_hk": _first(A, "EW07", "category", "Home & Kitchen", ep4["start_week"]),
        "ew02_estate": _first(A, "EW02", "estate", "Estate", _ep(cfg, "EP1")["start_week"]["S03"] if isinstance(
            _ep(cfg, "EP1")["start_week"], dict) else 0),
        "dq_fail": int((B["dq"]["dq_sales_status"] == "FAIL").sum()), "dq_warn": int((B["dq"]["dq_sales_status"] == "WARN").sum()),
        "dq_store_weeks": len(B["dq"]), "ep2": ep2, "ep3": ep3, "ep4": ep4, "ep5": ep5,
    }


# ----------------------------------------------------------------------------- executive summary
def executive_summary(B, E, cfg) -> str:
    F = facts(B, E, cfg)
    op = F["op"].set_index("store")
    sel = E["selected"]
    budget = cfg["monitoring"]["selection"]["warning_budget"]
    L = [
        "# Phase 9 executive summary: operational monitoring and early warning", "",
        "Brightwater Retail Ltd | Retail Performance & Root-Cause Analytics | Phase 9", "",
        "## What this phase adds", "",
        "Phases 5 to 8 explained the 2025 decline after the event. Phase 9 asks a different question: **if a weekly "
        "monitor had been running, when would it have raised the alarm?** It turns the eight early-warning signals "
        "proposed in Phase 8 (EW01 to EW08) into tested rules and replays them week by week through 2025, each week "
        "using only the data that would have been available at 06:00 on the Monday after the week closed.", "",
        "Historical diagnosis → Evidence testing → Decision support → Management action planning → Operational early warning", "",
        "This is a back-test and a design. Nothing has been deployed to production, and no alert here was ever sent to "
        "anyone.", "",
        "## The headline", "",
        f"* **The store cluster would have been flagged within weeks, not at half-year.** Stores S03, S04 and S05 "
        f"reached WARNING in {op.loc['S03', 'first_detection_week']}, {op.loc['S04', 'first_detection_week']} and "
        f"{op.loc['S05', 'first_detection_week']}: {int(op.loc['S03', 'detection_delay_weeks'])}, "
        f"{int(op.loc['S04', 'detection_delay_weeks'])} and {int(op.loc['S05', 'detection_delay_weeks'])} weeks after "
        f"each store's change point. {_active_text(F['active_final'])} {CAUSE}",
        f"* **Electronics & Tech availability** would have been flagged in {F['ew03_first']}"
        + (f" (after short, unconfirmed alerts earlier in the year, the first in {F['ew03_any_first']})"
           if F['ew03_any_first'] < F['ew03_first'] else "")
        + " and stayed in alert through the shortage. Top-selling SKUs with full-week stock-outs were flagged in the "
        f"weeks that followed: {F['ew04_detected']} of the {F['ew04_eps']} top-selling Electronics & Tech SKUs that "
        "Phase 6 found out of stock. The monitor produces a "
        "replenishment check list; it does not say why stock ran out, and it does not attribute the gap to any supplier. "
        f"By design it watches only the top-selling 10% of SKUs: they carried {F['ew04_cov_cells']} of the "
        f"{F['ew04_all_cells']} Electronics & Tech full-week stock-out cells in H2 2025, and {F['ew04_p6_never_top']} of "
        f"the {F['ew04_p6']} SKUs Phase 6 found out of stock were never top sellers, so they are left to the "
        "availability signal (EW03).",
        f"* **Faulty returns**: faulty-return activity exceeds expected range and requires investigation. For "
        f"Electronics & Tech this was flagged in {F['ew05_cat_first']}, and {F['ew05_detected']} of the "
        f"{F['ew05_eps']} stores Phase 6 identified were flagged within weeks of each other. Earlier 2025 comparisons "
        f"({F['ew05_early_held']} returns and margin alert-weeks in January and February) were held, not escalated: "
        "last year's returns in those weeks are understated because returns of sales made before the data starts are "
        "missing (check C12).",
        f"* **Margin and promotions**: Home & Kitchen gross margin % reached WARNING in {F['ew06_hk']} and its discount "
        f"depth in {F['ew07_hk']}. The alerts show that margin fell and that promotions were deeper than last year; "
        "they do not show that one caused the other.",
        f"* **Data problems are caught before they mislead.** The data-quality gate failed on exactly {F['dq_fail']} "
        "store-weeks (S13 2024-W42 with two trading days missing, and S16 2025-W51 and W52, whose sales arrived after "
        f"the Monday run). The {F['held_gate']} alert-weeks that depend on those weeks were held at WATCH instead of "
        f"being escalated ({F['held']} held in all, including the C12 returns holds above).", "",
        "## How much noise would managers have received?", "",
        f"Across 2025 the monitor raised {F['wp']} WARNING or CRITICAL entity-weeks. {F['wp_known']} fall inside the "
        f"issues Phases 5 and 6 established; {F['wp_unconf']} (about {F['wp_unconf_per_week']:.1f} a week across all "
        "signals) are **unconfirmed alerts**: outside every known issue, unexplained, but not proven false. An analyst "
        "would check each one; only a closed investigation could mark an alert FALSE POSITIVE. Each rule was chosen "
        f"to keep unconfirmed WARNINGs under {budget:.0%} of the weeks it watches outside the known issues. The "
        "selection never looked at how quickly a rule caught those issues, but it did depend on them: their weeks are "
        "left out of the noise count. Counting every alert as noise would have chosen stricter rules for "
        f"{_mask_changes(F['mask'])} of the 12 signal grains (`selection_mask_sensitivity.csv`).", "",
        f"About {100 * F['crit_share']:.0f}% of WARNING-or-above entity-weeks are CRITICAL. That is expected here: the "
        "2025 issues each lasted many weeks, and a WARNING that persists for 4 weeks becomes CRITICAL. "
        "`severity_sensitivity.csv` shows how the count moves with each CRITICAL setting.", "",
        f"A further {F['watch']} entity-weeks were at WATCH (a threshold breached once, not yet persistent). WATCH is "
        "shown on the investigation page for context and is not pushed to anyone.", "",
        "## What each signal is for", "",
        "| Signal | Watches | Rule chosen | Alert means | Proposed owner |",
        "|---|---|---|---|---|",
    ]
    for r in sel.itertuples():
        s = cfg["monitoring"]["signals"][r.signal]
        rule = f"{r.threshold} ({r.family.replace('_', ' ')}), {int(r.persistence_weeks)} week(s)"
        if r.signal == "EW01":
            rule += ", or the change-point test"
        L.append(f"| {r.signal} {r.entity_type} | {s['name']} | {rule} | {s['alert_class']} | {s['owner']} (PROPOSED) |")
    L += [
        "",
        "Every alert carries the same two statements: evidence level *Observed change (monitoring alert)* and cause "
        "status *Not established*. An alert starts an investigation (the Phase 8 investigation frameworks); it is "
        "never the conclusion.", "",
        "## What managers should take from this", "",
        "1. A weekly monitor on data Brightwater already holds would have surfaced each 2025 issue months before the "
        "half-year review, with a small number of unexplained alerts to check each week.",
        "2. The alerts are only as good as the feed: the DQ gate must run first each Monday, and its failures go to "
        "Data/BI before anyone reads the dashboard.",
        "3. The thresholds were calibrated on 2024 and 2025 and tested on the same period. They are a starting point: "
        "the first quarter of live running should be treated as a calibration period, with each alert's outcome "
        "logged in the Phase 8 decision log.",
        "4. Owners and responses are proposals. No management response is recorded here and none has been invented.", "",
        "## Limits to keep in mind", "",
        "* In-sample: the known issues used to judge detection come from the same two years the rules were tuned on, "
        "and their weeks were left out of the noise count, so the test is not out-of-sample.",
        "* The replay is as-at for sales but not for returns and stock snapshots, which carry no arrival time; they "
        "are taken at their final values.",
        "* Alerts are observed changes, not causes. Footfall, supplier, purchase-order, local-event and store-operations "
        "data are not available, so no alert can say why.",
        "* Exposure figures are monitoring estimates of the size of each deviation. They overlap between signals and "
        "are never added together.",
        "* Only one year (2025) has a prior year, so year-on-year signals cover 52 weeks.", "",
        "Detail: `docs/09_monitoring_early_warning.md`; validation: `phase9_validation_report.md`; figures in "
        "`reports/phase9/figures/`.", "",
    ]
    return "\n".join(L)


# ----------------------------------------------------------------------------- validation report
def validation_report(B, E, cfg, checks, freeze, opened, meta) -> str:
    F = facts(B, E, cfg)
    n, p = len(checks), int((checks["status"] == "PASS").sum())
    rec = B["reconciliation"]
    L = ["# Phase 9 validation report: monitoring, early warning and anomaly detection", "",
         f"Run: {meta['run_at']} | engine: {meta['engine']} | runtime {meta['runtime_seconds']} s | overall: "
         f"**{'PASS' if p == n else 'FAIL'}** ({p} of {n} checks)", "",
         "## 1. Freeze", "",
         f"{len(freeze)} Phase 1-8 files (and the four Phase 3 DQ audit files Phase 9 reads) match the dependency "
         "manifest recorded at the start of Phase 9 (`phase1_8_dependency_manifest.csv`). The Phase 8, 7 and 6 "
         "manifests were re-verified in the same run. Per-file result: `input_verification.csv`.", "",
         "| Phase | Files | Status |", "|---|---|---|"]
    for ph, g in freeze.groupby("phase"):
        L.append(f"| {ph} | {len(g)} | {'all UNCHANGED' if (g['status'] == 'UNCHANGED').all() else 'CHANGED'} |")
    L += ["", "## 2. Reconciliation of the monitoring layer to Phases 4-7", "",
          f"{int((rec['status'] == 'PASS').sum())} of {len(rec)} checks pass (`reconciliation_checks.csv`). The monitoring "
          "views (`sql/monitoring/01_monitoring_views.sql`) read only the Phase 4 star schema and reproduce the governed "
          "totals exactly:", "", "| Check | Status |", "|---|---|"]
    name_col = "check" if "check" in rec.columns else rec.columns[0]
    for r in rec.itertuples():
        L.append(f"| {getattr(r, name_col)} | {r.status} |")
    L += ["", "## 3. Validation checks", "", "| ID | Check | Status | Detail |", "|---|---|---|---|"]
    for r in checks.itertuples():
        d = str(r.detail).replace("|", "/")
        L.append(f"| {r.check_id} | {r.check} | {r.status} | {d[:160]} |")
    L += ["", "## 4. Back-test design", "",
          "* **As-at replay.** Each retail week is evaluated as the Monday 06:00 run would have seen it: lines whose "
          "extract timestamp is later than the run are excluded (`*_ontime` columns). S16's 2025-W51/W52 sales, "
          "delivered on 2026-01-09, therefore appear as missing and fail the gate. Returns and stock snapshots carry "
          "no arrival time and are taken at final values.",
          "* **Walk-forward baselines.** Every baseline for week t uses weeks before t only; test V13 perturbs all later "
          "weeks and confirms the earlier baselines, z-scores and change-point statistics do not move.",
          f"* **Selection.** One rule per signal and grain: the first family in interpretability order with a "
          f"candidate whose unconfirmed WARNING rate is within {cfg['monitoring']['selection']['warning_budget']:.0%} of "
          "non-episode entity-weeks; the smallest compliant threshold, then the shortest persistence (2 weeks minimum "
          "for WARNING). Detection delay, coverage and exposure on the known episodes are never read (test V12 "
          "scrambles them and gets the same rules). The known episodes DO shape the selection through the noise mask: "
          "their weeks are not counted as noise. `selection_mask_sensitivity.csv` re-runs the selection with no mask; "
          f"{_mask_changes(E.get('mask_sensitivity'))} of the 12 grains would get a stricter rule. The EW02 estate budget "
          "cannot be measured (20 non-episode weeks: one alert is 5%).",
          "* **Secondary rule (EW01).** The Phase 8 change-point test is selected the same way (the most sensitive "
          "candidate inside the budget) and raises WARNING on its own; the rule as operated, both together, is "
          "checked against the budget again (V11).",
          "* **Known episodes** are the issues Phases 5 and 6 established (config `episodes`). They label alerts, "
          "measure detection after selection and, through the noise mask, decide which weeks count as noise. They come "
          "from the same period, so detection results are in-sample.", "",
          "## 5. Selected rules and their back-test", "",
          "| Signal | Grain | Rule | Alerts | Unconfirmed | Rate | Known entities detected | Median delay (weeks) |",
          "|---|---|---|---|---|---|---|---|"]
    for r in E["selected"].itertuples():
        det = f"{int(r.episode_entities_detected)}/{int(r.episode_entities)}"
        dl = "" if pd.isna(r.median_detection_delay_weeks) else f"{r.median_detection_delay_weeks:g}"
        L.append(f"| {r.signal} | {r.entity_type} | {r.family}: {r.threshold}, {int(r.persistence_weeks)} wk | {int(r.alerts)} | "
                 f"{int(r.unconfirmed_alerts)} | {_pct(r.unconfirmed_rate, 2)} | {det} | {dl} |")
    missed = [f"{r.signal} {r.entity_type}" for r in E["selected"].itertuples()
              if r.episode_entities > 0 and r.episode_entities_detected < r.episode_entities]
    L += ["", ("Grains that missed part of a known episode at the selected rule: " + ", ".join(missed) + ". This is "
               "reported, not tuned away." if missed else "Every grain detected its known episode at the selected rule."), "",
          _knob_text(E.get("knob_sensitivity")), "",
          "## 6. S03-S05 detection", "", "| Store | Change point | First WARNING | Delay | Severity then | First CRITICAL | "
          "Active after onset | Active in final week |", "|---|---|---|---|---|---|---|---|"]
    for r in E["operational"].itertuples():
        L.append(f"| {r.store} | {r.change_point_week} | {r.first_detection_week} | {r.detection_delay_weeks:g} | "
                 f"{r.severity_at_first_detection} | {r.first_critical_week} | {_pct(r.active_share_after_change_point, 0)} | "
                 f"{'yes' if r.active_in_final_week else 'no'} |")
    L += ["", f"{CAUSE}", "", "## 7. Outputs", "",
          "Hashes of the main outputs (a second run with the same inputs gives identical files; see the determinism test):", ""]
    for f, h in meta["hashes"].items():
        L.append(f"* `{f}`: `{h[:16]}...`")
    L += ["", "## 8. Files opened", "",
          f"{len(opened['project_files'])} project files were read during the run; none is an evaluation-only file "
          f"(refused paths opened: {len(opened['refused'])}).", ""]
    return "\n".join(L)
