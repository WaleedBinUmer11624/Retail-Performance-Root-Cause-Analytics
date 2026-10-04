"""Phase 8 runner: business action plan, decision support and impact framework.

Usage (from the project root):
    python -m src.actions.run_phase8 --engine duckdb      # rebuild the Phase 4 model locally for the headline check
    python -m src.actions.run_phase8                      # use the SQL Server model built by Phase 4
    python -m src.actions.run_phase8 --record-freeze      # record the Phase 1-7 manifest (once, at phase start)

Stops (exit 1) if any Phase 1-7 file changed or the headline does not reconcile. Writes the management
deliverables and the validation report to reports/phase8/. Adds no analysis: every figure is read from a frozen
Phase 5, 6 or 7 output.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.analytics.model_access import PROJECT_ROOT, InputError
from src.analytics.run_phase5 import OpenRecorder
from src.monitoring.access import classify_opened  # shared runtime-read policy; see src/monitoring/access.py

from . import facts as FC
from . import figures as FG
from . import framework as FW
from . import report as RP
from . import validate as VA
from .access import load_config, recompute_headline, record_freeze, verify_freeze

OUTPUTS = {  # table -> file (the first eight are the brief's deliverables)
    "action_register": "phase8_action_register.csv",
    "plan": "phase8_30_60_90_plan.csv",
    "kpis": "phase8_kpi_monitoring_framework.csv",
    "evidence_to_action": "phase8_evidence_to_action_matrix.csv",
    "decision_log": "phase8_decision_log_template.csv",
    "data_requirements": "phase8_data_requirements.csv",
    "early_warning": "phase8_early_warning_requirements.csv",
    "decision_framework": "phase8_decision_framework.csv",
    "prioritisation": "phase8_prioritisation_matrix.csv",
    "impact": "phase8_impact_framework.csv",
    "scenarios": "phase8_impact_scenarios.csv",
    "frameworks": "phase8_investigation_frameworks.csv",
}
PLAN_FILE = "phase8_executive_action_plan.md"
FIGURE = "figures/phase8_prioritisation_grid.png"
DOC = "docs/08_business_action_and_decision_framework.md"


class Phase8Stop(RuntimeError):
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
    out.to_csv(path, index=False, lineterminator="\n")


def run(engine_name: str = "duckdb", out_dir: Path | None = None, recompute: bool = True, make_figure: bool = True) -> dict:
    if not getattr(run, "_hooked", False):
        sys.addaudithook(OpenRecorder.hook)
        run._hooked = True
    OpenRecorder.paths, OpenRecorder.active = [], True
    log, t0 = Log(), time.time()
    try:
        cfg = load_config()
        out = Path(out_dir) if out_dir else PROJECT_ROOT / cfg["actions"]["outputs"]["reports"]
        out.mkdir(parents=True, exist_ok=True)
        try:
            freeze = verify_freeze(cfg)
        except InputError as e:
            raise Phase8Stop(str(e)) from e
        log(f"freeze verified: {len(freeze)} Phase 1-7 files unchanged (Phase 7 and Phase 6 manifests re-verified)")
        headline = None
        if recompute:
            headline = recompute_headline(engine_name, out / "model_build")
            log("headline recomputed from the Phase 4 model through the pbi views: "
                + ", ".join(f"{int(r.retail_year)} {r.net_revenue:,.2f}" for r in headline.itertuples()))
        F = FC.build(cfg)
        T, ctx = FW.build(cfg, F)
        log(f"framework built: {len(T['action_register'])} actions, {len(T['kpis'])} KPIs, "
            f"{len(T['data_requirements'])} data requirements, {len(T['early_warning'])} early-warning signals")
        fig_rel = FIGURE
        if make_figure:
            FG.prioritisation_grid(T["prioritisation"], out / FIGURE)
        plan_md = RP.executive_plan(T, ctx, fig_rel)
        doc_path = PROJECT_ROOT / DOC
        doc_md = doc_path.read_text(encoding="utf-8") if doc_path.exists() else None
        checks = VA.run(T, ctx, headline, freeze, plan_md, doc_md)
        n_pass = int((checks["status"] == "PASS").sum())
        log(f"validation: {n_pass}/{len(checks)} checks pass")
        if headline is not None:
            h = headline.set_index("retail_year")
            hl = cfg["powerbi"]["headline"]
            if not (abs(h.loc[2025, "net_revenue"] - hl["net_revenue_cy"]) <= 0.01 and
                    abs(h.loc[2024, "net_revenue"] - hl["net_revenue_py"]) <= 0.01):
                raise Phase8Stop("headline does not reconcile:\n" + headline.to_string(index=False))
        # ------------------------------------------------------------ write
        for name, file in OUTPUTS.items():
            _w(T[name], out / file)
        (out / PLAN_FILE).write_text(plan_md, encoding="utf-8")
        used = set().union(*ctx.used.values()) | F.used
        facts_df = F.table()
        facts_df["used_in_outputs"] = facts_df["fact"].isin(used)
        _w(facts_df, out / "phase8_fact_register.csv")
        _w(checks, out / "phase8_validation_checks.csv")
        _w(freeze, out / "input_verification.csv")
        if headline is not None:
            _w(headline, out / "headline_recomputed.csv")
        OpenRecorder.active = False
        opened = classify_opened(OpenRecorder.summary())
        passed = n_pass == len(checks) and not opened["refused"]
        meta = {"run_at": datetime.now().isoformat(timespec="seconds"), "runtime_seconds": round(time.time() - t0, 1),
                "engine": engine_name if recompute else "none (headline from frozen files only)"}
        (out / "phase8_validation_report.md").write_text(validation_report(checks, freeze, headline, T, facts_df,
                                                                          opened, meta), encoding="utf-8")
        log(f"{'PASSED' if passed else 'FAILED'}; outputs in {out}")
        (out / "phase8_run_log.txt").write_text("\n".join(log.lines) + "\n", encoding="utf-8")
        return {"passed": passed, "checks": checks, "tables": T, "ctx": ctx, "facts": F, "plan_md": plan_md,
                "headline": headline, "freeze": freeze, "opened": opened, "out": out}
    finally:
        OpenRecorder.active = False


def validation_report(checks, freeze, headline, T, facts_df, opened, meta) -> str:
    n, p = len(checks), int((checks["status"] == "PASS").sum())
    L = ["# Phase 8 validation report: business action plan and decision framework", "",
         f"Run: {meta['run_at']} | headline engine: {meta['engine']} | runtime {meta['runtime_seconds']} s | "
         f"overall: **{'PASS' if p == n else 'FAIL'}** ({p} of {n} checks)", "",
         "## Freeze", "",
         f"{len(freeze)} Phase 1-7 files match the manifest recorded at the start of Phase 8 "
         "(`phase1_7_input_manifest.csv`); the Phase 7 manifest (Phase 1-6) and the Phase 6 manifest (Phase 1-5) were "
         "re-verified in the same run. Per-file result: `input_verification.csv`.", ""]
    if headline is not None:
        h = headline.set_index("retail_year")
        py, cy = h.loc[2024, "net_revenue"], h.loc[2025, "net_revenue"]
        L += ["## Headline", "",
              "Recomputed from the Phase 4 model with a plain SQL sum over the Power BI source views:", "",
              "| Period | Sales revenue | Returns | Net revenue |", "|---|---:|---:|---:|"]
        for r in headline.itertuples():
            L.append(f"| H2 {int(r.retail_year)} | {r.sales_revenue:,.2f} | {r.returns_value:,.2f} | {r.net_revenue:,.2f} |")
        L += ["", f"Change {cy - py:,.2f}; YoY {100 * (cy - py) / py:.6f}%. Required: H2 2024 10,188,727.55; "
              "H2 2025 9,457,457.05; change -731,270.50; YoY -7.177251%.", ""]
    L += ["## Checks by group", "", "| Group | Checks | Passed |", "|---|---:|---:|"]
    for g, d in checks.groupby("group", sort=False):
        L.append(f"| {g} | {len(d)} | {(d['status'] == 'PASS').sum()} |")
    fails = checks[checks["status"] != "PASS"]
    L += ["", "Failures: " + ("none." if fails.empty else ""), ""]
    if not fails.empty:
        L += [f"- {r.group}: {r.check} ({r.detail})" for r in fails.itertuples()] + [""]
    L += ["Full list: `phase8_validation_checks.csv`.", "", "## Traceability", "",
          f"{int(facts_df['used_in_outputs'].sum())} facts are used in the outputs, each read from a frozen Phase 5, 6 "
          "or 7 file (`phase8_fact_register.csv`: file, row and column, evidence tag). The configuration holds no "
          "typed figure; a check scans it.", "",
          "## Outputs", ""]
    L += [f"- `{f}`: {len(T[k])} rows" for k, f in OUTPUTS.items()]
    L += [f"- `{PLAN_FILE}`", f"- `{FIGURE}`", "", "## Independence", "",
          f"Files opened during the run: {len(opened['project_files'])} project files; refused: {len(opened['refused'])}. "
          "No evaluation-only or answer-key file was opened (audit hook).", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["mssql", "duckdb"], default="mssql")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-figure", action="store_true")
    ap.add_argument("--record-freeze", action="store_true")
    args = ap.parse_args()
    if args.record_freeze:
        df = record_freeze(load_config())
        print(f"Phase 1-7 freeze manifest recorded: {len(df)} files")
        return
    try:
        res = run(args.engine, args.out_dir, make_figure=not args.no_figure)
    except (Phase8Stop, InputError) as e:
        print(f"PHASE 8 STOPPED: {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
