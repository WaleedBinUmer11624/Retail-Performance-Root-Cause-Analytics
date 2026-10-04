"""Phase 7 runner: builds and validates the Power BI dashboard assets.

Usage (from the project root):
    python -m src.powerbi.run_phase7 --engine duckdb          # rebuild the Phase 4 model locally, build + validate
    python -m src.powerbi.run_phase7                          # use the SQL Server model built by Phase 4
    python -m src.powerbi.run_phase7 --engine duckdb --extract  # also write the star-schema CSVs to data/powerbi/
    python -m src.powerbi.run_phase7 --record-freeze          # record the Phase 1-6 manifest (once, at phase start)

Stops (exit 1) if any Phase 1-6 file changed, or if any reconciliation or static DAX check fails.
Power BI Desktop itself is not available here: the .pbix is built by hand from these assets (docs/07).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.analytics.model_access import PROJECT_ROOT, InputError
from src.analytics.run_phase5 import OpenRecorder

from . import assets as AS
from . import dax as DX
from . import dictionary as DD
from . import extracts as EX
from . import mockups as MK
from . import model as MD
from . import register as RG
from . import validate as VA
from .access import load_config, open_pbi_model, record_freeze, verify_freeze
from .reference import Model


class Phase7Stop(RuntimeError):
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


def build(engine_name: str, cfg: dict, log: Log, extract_model: bool, work_dir: Path, root: Path):
    engine, info, sql_log = open_pbi_model(engine_name, cfg, work_dir)
    try:
        t0 = time.time()
        tables = MD.load_tables(engine)
        load_s = time.time() - t0
    finally:
        engine.close()
    log(f"model loaded from pbi views: {sum(len(v) for v in tables.values()):,} rows in {load_s:.1f}s")
    ext_dir = root / cfg["powerbi"]["outputs"]["analytics_extracts"]
    extracts, manifest = EX.build(cfg, ext_dir)
    extracts["_manifest"] = manifest
    log(f"{len(manifest)} Phase 5/6 analytical extracts written to {ext_dir}")
    model_files = None
    if extract_model:
        model_files = MD.write_extracts(tables, root / cfg["powerbi"]["outputs"]["model_extracts"])
        log(f"star-schema CSVs written to {cfg['powerbi']['outputs']['model_extracts']}")
    # Power Query merge: Store <- p6_store_groups
    sg = extracts["p6_store_groups"]
    ptables = dict(tables)
    ptables["Store"] = tables["Store"].merge(sg, on="store_id", how="left").fillna({"store_group": "Unknown"})
    return tables, ptables, extracts, manifest, model_files, info, sql_log


def run(engine_name: str = "duckdb", out_dir: Path | None = None, make_mockups: bool = True,
        extract_model: bool = False, asset_root: Path | None = None) -> dict:
    """asset_root: where powerbi/ (and data/powerbi, mockups) are written; the project root by default. The tests
    point it at a temporary folder and compare the fresh assets with the committed ones."""
    sys.addaudithook(OpenRecorder.hook) if not getattr(run, "_hooked", False) else None
    run._hooked = True
    OpenRecorder.paths, OpenRecorder.active = [], True
    log = Log()
    t0 = time.time()
    try:
        cfg = load_config()
        out = Path(out_dir) if out_dir else PROJECT_ROOT / cfg["powerbi"]["outputs"]["reports"]
        out.mkdir(parents=True, exist_ok=True)
        freeze = verify_freeze(cfg)
        log(f"freeze verified: {len(freeze)} Phase 1-6 files unchanged (and the Phase 6 manifest re-verified)")
        root = Path(asset_root) if asset_root else PROJECT_ROOT
        tables, ptables, extracts, manifest, model_files, info, sql_log = build(
            engine_name, cfg, log, extract_model, out, root)
        M = Model(ptables)
        schema = MD.schema(ptables)
        schema.update({k: list(v.columns) for k, v in extracts.items() if not k.startswith("_")})
        checks = VA.run(M, cfg, extracts, schema)
        log(f"reconciliation and static DAX checks: {(checks['status'] == 'PASS').sum()}/{len(checks)} pass")
        reg = RG.build(M, cfg)
        log(f"dashboard number register: {len(reg)} numbers, every one with a source")
        # ------------------------------------------------------------ assets
        pbi = root / cfg["powerbi"]["outputs"]["powerbi_dir"]
        (pbi / "dax").mkdir(parents=True, exist_ok=True)
        (pbi / "dax" / "measures.dax").write_text(DX.to_dax_listing(), encoding="utf-8")
        (pbi / "dax" / "measures_tmdl.tmdl").write_text(DX.to_tmdl(), encoding="utf-8")
        cases = AS.validation_cases(M, cfg, extracts)
        (pbi / "dax" / "validation_queries.dax").write_text(
            AS.validation_queries_text(cases, float(extracts["p6_driver_attribution"]["amount_eur"].sum())), encoding="utf-8")
        pq = AS.power_query(tables, extracts, pbi / "power_query", cfg["project"]["database"]["database"])
        AS.theme(pbi / "brightwater_theme.json")
        (pbi / "model_definition.json").write_text(json.dumps(AS.model_definition(tables, extracts), indent=2) + "\n",
                                                    encoding="utf-8")
        log(f"assets: {len(DX.MEASURES)} DAX measures, {len(pq)} Power Query files, theme, model definition, "
            f"{len(cases)} DAX validation cases")
        # ------------------------------------------------------------ reports
        _w(checks, out / "phase7_validation_checks.csv")
        _w(DX.dictionary(), out / "measure_dictionary.csv")
        _w(DD.data_dictionary(ptables, extracts, manifest), out / "data_dictionary.csv")
        _w(reg, out / "dashboard_number_register.csv")
        prof = DD.model_profile(tables)
        _w(prof, out / "model_profile.csv")
        _w(freeze, out / "input_verification.csv")
        _w(pd.DataFrame(cases), out / "dax_validation_cases.csv")
        figs = []
        if make_mockups:
            figs = MK.make_all(M, reg, cfg, extracts, root / cfg["powerbi"]["outputs"]["mockups"])
            log(f"{len(figs)} page mockups drawn")
        OpenRecorder.active = False
        opened = OpenRecorder.summary()
        passed = bool((checks["status"] == "PASS").all()) and not opened["refused"]
        meta = {"run_at": datetime.now().isoformat(timespec="seconds"), "runtime_seconds": round(time.time() - t0, 1),
                "engine": info["engine"], "sql": sql_log}
        (out / "phase7_validation_report.md").write_text(
            validation_report(cfg, checks, freeze, reg, cases, prof, manifest, opened, meta, figs), encoding="utf-8")
        log(f"{'PASSED' if passed else 'FAILED'}; outputs in {out}")
        (out / "phase7_run_log.txt").write_text("\n".join(log.lines) + "\n", encoding="utf-8")
        return {"passed": passed, "checks": checks, "register": reg, "model": M, "tables": ptables, "extracts": extracts,
                "opened": opened, "out": out, "cases": cases, "mockups": figs}
    finally:
        OpenRecorder.active = False


def validation_report(cfg, checks, freeze, reg, cases, prof, manifest, opened, meta, figs) -> str:
    hd = cfg["powerbi"]["headline"]
    L = []
    A = L.append
    ok = (checks["status"] == "PASS").all()
    A("# Phase 7 validation report: Power BI dashboard assets")
    A("")
    A(f"Run: {meta['run_at']} | engine: {meta['engine']} | runtime {meta['runtime_seconds']} s | overall: "
      f"**{'PASS' if ok else 'FAIL'}** ({(checks['status'] == 'PASS').sum()} of {len(checks)} checks)")
    A("")
    A("## What was tested here and what was not")
    A("")
    A("| Item | Status in this environment |")
    A("|---|---|")
    A("| Phase 1-6 freeze (SHA-256 of every frozen file) | Tested: all unchanged |")
    A("| Power BI source views `pbi.*` (T-SQL) | Tested on the DuckDB rebuild of the Phase 4 model (same scripts, translated); "
      "not run on SQL Server here |")
    A("| DAX measure LOGIC (filter semantics, PY shift, inactive relationship, target weeks) | Tested through the Python "
      "reference implementation, reconciled to Phase 4, 5 and 6 |")
    A("| DAX TEXT (syntax, engine behaviour) | Static checks only (references, columns, parentheses, cycles). "
      "**Must be confirmed in Power BI Desktop** with `powerbi/dax/validation_queries.dax` |")
    A("| TMDL script, Power Query, theme | Written; **not executed** (no Power BI Desktop) |")
    A("| Report pages, slicers, drill-through, tooltips | Specified and drawn as mockups; **not built or tested** |")
    A("| Performance Analyzer | **Not run** (needs Power BI Desktop); model profile below instead |")
    A("")
    A("## Headline reconciliation")
    A("")
    h = checks[checks["group"].isin(["Headline", "Phase 4", "Phase 6"])]
    A("| Check | Dashboard measure | Reference | Status |")
    A("|---|---:|---:|---|")
    for r in h.itertuples():
        A(f"| {r.group}: {r.check} | {r.value:,.6f} | {r.reference:,.6f} | {r.status} |")
    A("")
    A(f"Required: H2 2024 €{hd['net_revenue_py']:,.2f}; H2 2025 €{hd['net_revenue_cy']:,.2f}; change "
      f"€{hd['change']:,.2f}; YoY {hd['yoy_pct']}%.")
    A("")
    A("## All checks by group")
    A("")
    A("| Group | Checks | Passed |")
    A("|---|---:|---:|")
    for g, d in checks.groupby("group", sort=False):
        A(f"| {g} | {len(d)} | {(d['status'] == 'PASS').sum()} |")
    A("")
    fails = checks[checks["status"] != "PASS"]
    A("Failures: none." if fails.empty else "Failures:\n\n" + fails.to_string(index=False))
    A("")
    A("Full list: `phase7_validation_checks.csv`.")
    A("")
    A("## Dashboard number register")
    A("")
    A(f"{len(reg)} numbers appear on the seven pages. Each has a source: {int((reg['source_type'] == 'DAX').sum())} "
      f"are DAX measures in a stated filter context (evaluated through the reconciled reference), "
      f"{int(reg['source_type'].isin(['P6', 'P5']).sum())} are cells of frozen Phase 5/6 outputs. "
      "See `dashboard_number_register.csv`; the tests re-derive every entry from its source.")
    A("")
    A("| Evidence tag | Numbers |")
    A("|---|---:|")
    for t, n in reg["evidence_tag"].value_counts().items():
        A(f"| {t} | {n} |")
    A("")
    A("## Power BI Desktop validation cases")
    A("")
    A(f"`powerbi/dax/validation_queries.dax` holds {len(cases) + 1} cases with the expected value of each (from the "
      "reconciled reference). Paste it into DAX query view; every row must return PASS. The cases cover the headline, "
      "all nine KPI cards, PY time intelligence, the cluster store groups, Electronics availability and stock-outs, "
      "'Faulty' returns, Home & Kitchen discount rate, a sale-cohort value (inactive relationship) and the attribution total.")
    A("")
    A("## Extract traceability")
    A("")
    A(f"{len(manifest)} Phase 5/6 tables are imported (`powerbi/data/`). Each is a column selection of a frozen file whose "
      "SHA-256 matches the Phase 7 freeze manifest (`powerbi/data/extract_manifest.csv`). No Phase 6 figure is recomputed.")
    A("")
    A("## Model profile (performance review without Performance Analyzer)")
    A("")
    t = prof.groupby("table").agg(rows=("rows", "first"), columns=("column", "size")).reset_index()
    A("| Table | Rows | Columns |")
    A("|---|---:|---:|")
    for r in t.itertuples():
        A(f"| {r.table} | {r.rows:,} | {r.columns} |")
    hi = prof[(prof["distinct_values"] > 100000)].sort_values("distinct_values", ascending=False)
    A("")
    A("High-cardinality columns (largest VertiPaq cost): " + "; ".join(
        f"{r.table}[{r.column}] {r.distinct_values:,}" for r in hi.itertuples()) + ". `sales_line_id` and `return_id` "
      "are kept only for drill-through and can be removed from the import if the model must be smaller; "
      "`transaction_key` is an integer by design so DISTINCTCOUNT stays fast.")
    A("")
    A("## Independence")
    A("")
    A(f"Files opened during the run: {len(opened['project_files'])} project files; refused: {len(opened['refused'])}. "
      "No evaluation-only or answer-key file was opened (audit hook).")
    A("")
    A(f"Mockups: {', '.join(figs) if figs else 'not drawn in this run'}.")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["mssql", "duckdb"], default="mssql")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-mockups", action="store_true")
    ap.add_argument("--extract", action="store_true", help="also write the star-schema CSVs to data/powerbi/")
    ap.add_argument("--record-freeze", action="store_true")
    a = ap.parse_args()
    if a.record_freeze:
        print(f"recorded {len(record_freeze(load_config()))} files")
        return
    try:
        res = run(a.engine, a.out_dir, not a.no_mockups, a.extract)
    except (InputError, Phase7Stop) as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        sys.exit(1)
    if not res["passed"]:
        print(res["checks"][res["checks"]["status"] != "PASS"].to_string(index=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
