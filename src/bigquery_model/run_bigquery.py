"""Build the Phase 4 star schema and KPI layer in BigQuery, then reconcile it to Phase 3.

Usage (from the project root, with Application Default Credentials and BQ_PROJECT_ID set):
    python -m src.bigquery_model.run_bigquery              # build, reconcile, write reports/bigquery/
    python -m src.bigquery_model.run_bigquery --teardown   # delete the four BigQuery datasets

Same inputs, scripts and pass criteria as src/sql_model/run_model.py (config/sql_model_config.yaml):
the curated files are verified against their Phase 3 SHA-256 first, the expected values come from
the same Phase 3 outputs, and the build passes only when every reconciliation and KPI validation
check passes. In addition, the H1 and H2 2025 estate net revenue must match the governed figures.
Exit code 1 if any check fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.sql_model.engines import EngineError
from src.sql_model.inputs import PROJECT_ROOT, expected_metrics, load_config, read_curated, verify_curated
from src.sql_model.run_model import write_report
from src.sql_model.scripts import split_batches

from .engine import RULES, SCHEMAS, BigQueryEngine
from .settings import credentials_available, load_bq_config, redact, resolve_project

# Governed estate results (reports/phase3/kpi_reconciliation.csv and the Phase 4 mart), checked to the cent.
HEADLINES = {
    ("H2", "net_revenue_cy"): 9457457.05, ("H2", "yoy_pct_2dp"): -7.18,
    ("H1", "net_revenue_cy"): 8629984.78, ("H1", "yoy_pct_3dp"): 1.438,
}


def headline_checks(engine: BigQueryEngine) -> pd.DataFrame:
    df = engine.query("SELECT period, net_revenue_cy, net_revenue_yoy_pct FROM mart.v_yoy_segment_period "
                      "WHERE segment_type = N'Estate' AND retail_year = 2025 AND period IN (N'H1', N'H2')")
    got = df.set_index("period")
    rows = []
    for (half, metric), expected in HEADLINES.items():
        if metric == "net_revenue_cy":
            actual = round(float(got.loc[half, "net_revenue_cy"]), 2)
        else:
            actual = round(float(got.loc[half, "net_revenue_yoy_pct"]), 2 if metric.endswith("2dp") else 3)
        rows.append({"check": f"estate {half} 2025 {metric}", "expected": expected, "actual": actual,
                     "status": "PASS" if actual == expected else "FAIL"})
    return pd.DataFrame(rows)


def object_inventory(engine: BigQueryEngine) -> pd.DataFrame:
    """Tables and views per dataset; table row counts come from metadata, so no query bytes are used."""
    rows = []
    for schema in SCHEMAS:
        for t in engine.client.list_tables(f"{engine.project}.{engine.dataset(schema)}"):
            table = engine.client.get_table(t.reference)
            rows.append({"table_schema": schema, "table_name": t.table_id,
                         "table_type": "VIEW" if table.table_type == "VIEW" else "TABLE",
                         "row_count": None if table.table_type == "VIEW" else int(table.num_rows)})
    return pd.DataFrame(rows).sort_values(["table_schema", "table_type", "table_name"]).reset_index(drop=True)


def engine_comparison(recon: pd.DataFrame | None, kpival: pd.DataFrame | None) -> pd.DataFrame:
    """Every reconciliation and KPI validation value against the committed DuckDB and SQL Server results."""
    out = []
    phase4 = PROJECT_ROOT / "reports" / "phase4"
    for kind, df, key in (("reconciliation", recon, "metric_name"), ("kpi_validation", kpival, "check_name")):
        if df is None:
            continue
        bq = df.set_index(key)["actual_value"].astype(float)
        for other in ("duckdb", "mssql"):
            path = phase4 / f"{'reconciliation_results' if kind == 'reconciliation' else 'kpi_validation'}_{other}.csv"
            if not path.exists():
                continue
            ref = pd.read_csv(path).set_index(key)["actual_value"].astype(float)
            for name in sorted(set(bq.index) | set(ref.index)):
                a, b = bq.get(name), ref.get(name)
                out.append({"check_set": kind, "name": name, "other_engine": other, "bigquery": a, "other": b,
                            "abs_difference": None if a is None or b is None else abs(a - b)})
    return pd.DataFrame(out)


def run(out_dir: Path | None = None) -> dict:
    cfg, _ = load_config()
    bq_cfg = load_bq_config()
    project = resolve_project(bq_cfg)
    if not project:
        raise SystemExit(f"Set {bq_cfg['project_id_env']} or create {bq_cfg['local_config']} (project_id: ...)")
    if not credentials_available():
        raise SystemExit("No Application Default Credentials: run gcloud auth application-default login")
    out_dir = Path(out_dir) if out_dir else PROJECT_ROOT / bq_cfg["outputs"]["reports"]
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    log, error = [], None
    input_check = verify_curated(cfg)                       # refuse to build from altered curated data
    engine = BigQueryEngine(project, bq_cfg["dataset_prefix"], bq_cfg["location"], bq_cfg["maximum_bytes_billed"])
    curated = {}
    try:
        engine.ensure_datasets()
        for step in cfg["scripts"]:
            t0 = time.time()
            if step == "@load_staging":
                for t in cfg["inputs"]["curated_tables"]:
                    curated[t] = read_curated(cfg, t)        # the same text values DuckDB and SQL Server receive
                    rows = engine.load_csv_file(f"stg.{t}", PROJECT_ROOT / cfg["inputs"]["curated_dir"] / f"{t}.csv",
                                                input_check[t]["sha256"], len(curated[t]))
                    if rows != len(curated[t]):
                        raise EngineError(f"stg.{t}: load job wrote {rows} rows, the curated file has {len(curated[t])}")
                log.append({"step": step, "batches": len(curated), "seconds": round(time.time() - t0, 2)})
                continue
            if step == "@load_expected":
                exp = expected_metrics(cfg, curated)
                engine.load_table("recon.expected", exp)
                log.append({"step": step, "batches": len(exp), "seconds": round(time.time() - t0, 2)})
                continue
            all_batches = split_batches(PROJECT_ROOT / step)
            batches = [b for b in all_batches if b.target == "both"]
            for b in batches:
                engine.run_batch(b)
            log.append({"step": step, "batches": len(batches), "skipped_for_engine": len(all_batches) - len(batches),
                        "seconds": round(time.time() - t0, 2)})
    except Exception as e:  # noqa: BLE001
        error = redact(str(e), project)

    recon = _safe(lambda: engine.query("SELECT * FROM recon.v_reconciliation"))
    kpival = _safe(lambda: engine.query("SELECT * FROM recon.kpi_validation_result"))
    heads = _safe(lambda: headline_checks(engine))
    inventory = _safe(lambda: object_inventory(engine))
    ok = error is None and all(df is not None for df in (recon, kpival, heads)) \
        and (recon["status"] == "PASS").all() and (kpival["status"] == "PASS").all() and (heads["status"] == "PASS").all()
    jobs = pd.DataFrame(engine.jobs)
    summary = {"run_at": datetime.now().isoformat(timespec="seconds"), "engine": engine.name,
               "engine_note": ("BigQuery (dialect bigquery, location " + bq_cfg["location"] + ", datasets "
                               + bq_cfg["dataset_prefix"] + "*): T-SQL parsed by sqlglot (tsql dialect) and generated "
                               "for BigQuery, with the rewrite rules in docs/bigquery_engine.md; no DML (load jobs and "
                               "CREATE OR REPLACE TABLE AS SELECT); @tsql-only batches not executed"),
               "runtime_seconds": round(time.time() - t_start, 1), "passed": bool(ok), "error": error,
               "curated_inputs_verified": input_check,
               "reconciliation": None if recon is None else recon["status"].value_counts().to_dict(),
               "kpi_validation": None if kpival is None else kpival["status"].value_counts().to_dict(),
               "headline_checks": None if heads is None else heads.to_dict("records"),
               "query_bytes_processed": None if jobs.empty else int(jobs["bytes_processed"].fillna(0).sum()),
               "query_bytes_billed": None if jobs.empty else int(jobs["bytes_billed"].fillna(0).sum()),
               "maximum_bytes_billed_per_query": int(bq_cfg["maximum_bytes_billed"])}
    rules = pd.DataFrame(engine.rule_log)
    if not rules.empty:
        rules["why"] = rules["rule"].map(RULES)
    outputs = {"run_log": pd.DataFrame(log), "reconciliation_results": recon, "kpi_validation": kpival,
               "object_inventory": inventory, "headline_checks": heads, "translation_rules": rules, "jobs": jobs,
               "engine_comparison": engine_comparison(recon, kpival)}
    for name, df in outputs.items():
        if df is not None:
            df.map(lambda v: redact(v, project)).to_csv(out_dir / f"{name}_bigquery.csv", index=False)
    (out_dir / "run_summary_bigquery.json").write_text(redact(json.dumps(summary, indent=2, default=str), project))
    res = {"summary": summary, "reconciliation": recon, "kpi_validation": kpival, "inventory": inventory,
           "headline_checks": heads, "passed": ok}
    write_report(res, pd.DataFrame(log), out_dir / "phase4_build_report_bigquery.md")
    engine.close()
    return res


def teardown():
    bq_cfg = load_bq_config()
    project = resolve_project(bq_cfg)
    engine = BigQueryEngine(project, bq_cfg["dataset_prefix"], bq_cfg["location"], bq_cfg["maximum_bytes_billed"])
    for s in SCHEMAS:
        engine.client.delete_dataset(f"{project}.{engine.dataset(s)}", delete_contents=True, not_found_ok=True)
        print(f"deleted dataset {engine.dataset(s)}")


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teardown", action="store_true", help="delete the BigQuery datasets this build creates")
    a = ap.parse_args()
    if a.teardown:
        teardown()
        return
    res = run()
    s = res["summary"]
    print(json.dumps({k: s[k] for k in ("engine", "runtime_seconds", "passed", "error", "reconciliation",
                                         "kpi_validation", "headline_checks", "query_bytes_billed")}, indent=2))
    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
