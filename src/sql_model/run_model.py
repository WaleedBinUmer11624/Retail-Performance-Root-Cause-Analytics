"""Build the Phase 4 star schema and KPI layer, then reconcile it to Phase 3.

Usage (from the project root):
    python -m src.sql_model.run_model                      # SQL Server (config/project_config.yaml: database)
    python -m src.sql_model.run_model --engine duckdb      # local verification engine (no SQL Server needed)

Steps (config/sql_model_config.yaml): scripts 01-11 in order, plus two runner steps:
  @load_staging   curated CSVs -> stg.* (after verifying their SHA-256 against Phase 3 lineage)
  @load_expected  Phase 3 trusted values + tolerances -> recon.expected
Exit code 1 if any reconciliation or KPI validation check fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from .engines import DuckDBEngine, EngineError, SqlServerEngine
from .inputs import PROJECT_ROOT, expected_metrics, load_config, read_curated, verify_curated
from .scripts import split_batches

SCHEMAS = ("stg", "dw", "mart", "recon")
SCRIPTED_DATABASE = "BrightwaterRetail"


def make_engine(name: str, project: dict, duckdb_path: str = ":memory:"):
    if name == "duckdb":
        return DuckDBEngine(duckdb_path)
    if name == "mssql":
        if project["database"]["database"] != SCRIPTED_DATABASE:
            raise ValueError(f"config database must be {SCRIPTED_DATABASE} (the name used by script 01)")
        return SqlServerEngine(project["database"], database="master")
    raise ValueError(name)


def object_inventory(engine) -> pd.DataFrame:
    objs = engine.query(
        "SELECT table_schema, table_name, table_type FROM information_schema.tables "
        "WHERE table_schema IN ('stg', 'dw', 'mart', 'recon')")
    objs["table_type"] = objs["table_type"].str.upper().str.replace("BASE TABLE", "TABLE")
    counts = []
    for _, r in objs.iterrows():
        if r["table_type"] == "TABLE":
            n = engine.query(f"SELECT COUNT(*) AS n FROM {r['table_schema']}.{r['table_name']}")["n"].iloc[0]
            counts.append(int(n))
        else:
            counts.append(None)
    objs["row_count"] = counts
    return objs.sort_values(["table_schema", "table_type", "table_name"]).reset_index(drop=True)


def run(engine_name: str = "duckdb", duckdb_path: str = ":memory:", out_dir: Path | None = None,
        expected_override: dict | None = None, keep_engine: bool = False) -> dict:
    cfg, project = load_config()
    out_dir = Path(out_dir) if out_dir else PROJECT_ROOT / cfg["outputs"]["reports"]
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    log = []
    input_check = verify_curated(cfg)                     # refuse to build from altered curated data
    engine = make_engine(engine_name, project, duckdb_path)
    curated = {}
    error = None
    try:
        for step in cfg["scripts"]:
            t0 = time.time()
            if step == "@load_staging":
                for t in cfg["inputs"]["curated_tables"]:
                    curated[t] = read_curated(cfg, t)
                    engine.load_table(f"stg.{t}", curated[t])
                log.append({"step": step, "batches": len(curated), "seconds": round(time.time() - t0, 2)})
                continue
            if step == "@load_expected":
                exp = expected_metrics(cfg, curated)
                if expected_override:                      # used by tests to prove a breach fails the build
                    for k, v in expected_override.items():
                        exp.loc[exp["metric_name"] == k, "expected_value"] = v
                engine.execute("DELETE FROM recon.expected")
                engine.load_table("recon.expected", exp)
                write_expected_sql(exp, out_dir / "generated" / "recon_expected_values.sql")
                log.append({"step": step, "batches": len(exp), "seconds": round(time.time() - t0, 2)})
                continue
            batches = [b for b in split_batches(PROJECT_ROOT / step) if b.runs_on(engine.name)]
            for b in batches:
                engine.run_batch(b)
            if engine.name == "mssql" and step.endswith("01_create_database_and_schemas.sql"):
                engine.use(project["database"]["database"])
            skipped = len(split_batches(PROJECT_ROOT / step)) - len(batches)
            log.append({"step": step, "batches": len(batches), "skipped_for_engine": skipped,
                        "seconds": round(time.time() - t0, 2)})
    except EngineError as e:                              # on SQL Server a failed reconciliation THROWs here
        error = str(e)

    recon = _safe_query(engine, "SELECT * FROM recon.v_reconciliation")
    kpival = _safe_query(engine, "SELECT * FROM recon.kpi_validation_result")
    inventory = _safe_query_fn(lambda: object_inventory(engine))
    ok = error is None and recon is not None and kpival is not None \
        and (recon["status"] == "PASS").all() and (kpival["status"] == "PASS").all()

    summary = {"run_at": datetime.now().isoformat(timespec="seconds"), "engine": engine.name,
               "engine_note": ("SQL Server" if engine.name == "mssql" else
                               "DuckDB verification engine: T-SQL parsed by sqlglot (tsql dialect) and executed in "
                               "DuckDB; @tsql-only batches (constraints, columnstore indexes, THROW) not executed"),
               "runtime_seconds": round(time.time() - t_start, 1), "passed": bool(ok), "error": error,
               "curated_inputs_verified": input_check,
               "reconciliation": None if recon is None else recon["status"].value_counts().to_dict(),
               "kpi_validation": None if kpival is None else kpival["status"].value_counts().to_dict()}
    if out_dir is not None:
        pd.DataFrame(log).to_csv(out_dir / f"run_log_{engine.name}.csv", index=False)
        if recon is not None:
            recon.to_csv(out_dir / f"reconciliation_results_{engine.name}.csv", index=False)
        if kpival is not None:
            kpival.to_csv(out_dir / f"kpi_validation_{engine.name}.csv", index=False)
        if inventory is not None:
            inventory.to_csv(out_dir / f"object_inventory_{engine.name}.csv", index=False)
        (out_dir / f"run_summary_{engine.name}.json").write_text(json.dumps(summary, indent=2, default=str))
    res = {"summary": summary, "reconciliation": recon, "kpi_validation": kpival, "inventory": inventory,
           "log": pd.DataFrame(log), "passed": ok, "engine": engine if keep_engine else None}
    write_report(res, pd.DataFrame(log), out_dir / f"phase4_build_report_{engine.name}.md")
    if not keep_engine:
        engine.close()
    return res


def write_expected_sql(exp: pd.DataFrame, path: Path):
    """The same expected values as T-SQL, for the SSMS / sqlcmd build path (sql/run_all_sqlcmd.sql)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    esc = lambda v: str(v).replace("'", "''")  # noqa: E731
    rows = [f"(N'{esc(r.metric_name)}', N'{esc(r.metric_group)}', {r.expected_value!r}, {r.tolerance_abs!r}, "
            f"N'{esc(r.expected_source)}')" for r in exp.itertuples()]
    path.write_text("/* Generated by src/sql_model/run_model.py from Phase 3 trusted outputs. Do not edit. */\n"
                    "SET NOCOUNT ON;\nDELETE FROM recon.expected;\n"
                    "INSERT INTO recon.expected (metric_name, metric_group, expected_value, tolerance_abs, expected_source)"
                    " VALUES\n" + ",\n".join(rows) + ";\nGO\n")


def write_report(res: dict, log: pd.DataFrame, path: Path):
    s, recon, kv, inv = res["summary"], res["reconciliation"], res["kpi_validation"], res["inventory"]

    def table(df, cols, fmt=None):
        fmt = fmt or {}
        out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for _, r in df.iterrows():
            out.append("| " + " | ".join(fmt.get(c, str)(r[c]) if pd.notna(r[c]) else "" for c in cols) + " |")
        return "\n".join(out)
    num = lambda v: f"{v:,.6f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"  # noqa: E731
    L = [f"# Phase 4 model build: {s['engine']}", "",
         f"- Run: {s['run_at']} ({s['runtime_seconds']} s)",
         f"- Engine: {s['engine_note']}",
         f"- Result: **{'PASSED' if s['passed'] else 'FAILED'}**" + (f" ({s['error']})" if s["error"] else ""),
         f"- Curated inputs verified against Phase 3 lineage (SHA-256): {len(s['curated_inputs_verified'])} files", "",
         "## Steps", "", table(log.fillna(""), list(log.columns)), ""]
    if inv is not None:
        L += ["## Objects", "", table(inv, ["table_schema", "table_name", "table_type", "row_count"],
                                      {"row_count": lambda v: f"{int(v):,}"}), ""]
    if recon is not None:
        L += ["## Reconciliation against Phase 3", "",
              table(recon, ["metric_name", "metric_group", "expected_value", "actual_value", "abs_difference",
                            "tolerance_abs", "status"],
                    {c: num for c in ("expected_value", "actual_value", "abs_difference", "tolerance_abs")}), ""]
    if kv is not None:
        L += ["## KPI layer validation", "",
              table(kv, ["check_name", "expected_value", "actual_value", "tolerance", "status"],
                    {c: num for c in ("expected_value", "actual_value", "tolerance")}), ""]
    path.write_text("\n".join(L))


def _safe_query(engine, sql):
    try:
        return engine.query(sql)
    except Exception:  # noqa: BLE001
        return None


def _safe_query_fn(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["mssql", "duckdb"], default="mssql")
    ap.add_argument("--duckdb-path", default=":memory:", help="DuckDB file to keep the verification database")
    a = ap.parse_args()
    res = run(a.engine, a.duckdb_path)
    s = res["summary"]
    print(json.dumps({k: s[k] for k in ("engine", "runtime_seconds", "passed", "error", "reconciliation",
                                         "kpi_validation")}, indent=2))
    if res["reconciliation"] is not None:
        bad = res["reconciliation"][res["reconciliation"]["status"] != "PASS"]
        if len(bad):
            print(bad.to_string(index=False))
    if res["kpi_validation"] is not None:
        bad = res["kpi_validation"][res["kpi_validation"]["status"] != "PASS"]
        if len(bad):
            print(bad.to_string(index=False))
    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
