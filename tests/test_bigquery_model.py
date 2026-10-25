"""BigQuery engine tests: the optional third build of the Phase 4 model (src/bigquery_model).

Offline checks always run: configuration, translation of every Phase 4 batch, the documented rewrite
rules, and the engine's free-tier behaviour against a fake client. The live checks query the BigQuery
build and skip cleanly unless the client library, Application Default Credentials, a project ID
(environment or untracked local file) and the built datasets are all present.
"""
import re
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.bigquery_model.engine import RULES, SCHEMAS, BigQueryEngine
from src.bigquery_model.settings import credentials_available, load_bq_config, resolve_project
from src.sql_model.scripts import split_batches

ROOT = Path(__file__).resolve().parents[1]
BQ_CFG = load_bq_config()
PHASE4_CFG = yaml.safe_load((ROOT / "config" / "sql_model_config.yaml").read_text(encoding="utf-8"))
DOC = ROOT / "docs" / "bigquery_engine.md"
TOLERANCE = 0.01                                     # EUR; the Phase 4 money tolerance


def _strip_strings(sql: str) -> str:
    return re.sub(r"'(?:[^'\\]|\\.)*'", "''", sql)


@pytest.fixture(scope="module")
def translated():
    """Every Phase 4 batch that runs on BigQuery, translated without a network connection."""
    eng = BigQueryEngine("proj", BQ_CFG["dataset_prefix"], BQ_CFG["location"], 1, connect=False)
    out = []
    for step in PHASE4_CFG["scripts"]:
        if step.startswith("@"):
            continue
        for b in split_batches(ROOT / step):
            if b.target == "both":
                out += [(step, s) for s in eng.translate(b.text, f"{step} {b.index}")]
    return eng, out


# ============================================================ configuration (always)
def test_config_is_free_tier_eu_and_capped():
    assert BQ_CFG["location"] == "EU"
    assert 0 < BQ_CFG["maximum_bytes_billed"] <= 10 * 1024 ** 3
    assert "project_id" not in BQ_CFG and BQ_CFG["project_id_env"]


def test_local_project_config_is_git_ignored():
    ignored = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert BQ_CFG["local_config"] in ignored


def test_project_id_is_not_written_to_tracked_bigquery_files():
    project = resolve_project(BQ_CFG)
    if not project:
        pytest.skip("no project ID configured on this machine")
    files = [ROOT / "config" / "bigquery_config.yaml", DOC, Path(__file__), *sorted((ROOT / "src" / "bigquery_model").glob("*.py")),
             *sorted((ROOT / BQ_CFG["outputs"]["reports"]).glob("*"))]
    offenders = [f.name for f in files if f.is_file() and project in f.read_text(encoding="utf-8", errors="ignore")]
    assert not offenders, offenders


# ============================================================ translation (always)
def test_every_phase4_batch_translates_without_bigquery_incompatibilities(translated):
    _, steps = translated
    queries = [s.sql for _, s in steps if s.kind == "query"]
    assert queries
    forbidden = {"N prefix": r"\bN''", "parameterized CAST": r"AS (NUMERIC|BIGNUMERIC|STRING|TIME|DATETIME)\(",
                 "T-SQL conversion": r"TRY_CONVERT|\bCONVERT\(", "WITHIN GROUP": r"WITHIN GROUP", "OR ALTER": r"OR ALTER",
                 "unqualified schema": r"(?<![\w`.])(stg|dw|mart|recon)\.(?=\w)"}
    for sql in queries:
        bare = _strip_strings(sql)
        for name, rx in forbidden.items():
            assert not re.search(rx, bare), (name, sql[:200])


def test_no_dml_is_sent_to_bigquery(translated):
    """The sandbox allows no DML: every write is a load job or CREATE OR REPLACE TABLE AS SELECT."""
    _, steps = translated
    for _, s in steps:
        if s.kind == "query":
            assert not re.match(r"\s*(INSERT|DELETE|UPDATE|MERGE|TRUNCATE)\b", s.sql, re.I), s.sql[:120]


def test_every_star_schema_table_is_built_by_one_ctas(translated):
    _, steps = translated
    built = [re.match(r"CREATE OR REPLACE TABLE `proj`\.(\w+)\.(\w+) AS", s.sql) for step, s in steps
             if s.kind == "query" and "transformations" in step]
    tables = {m.group(2) for m in built if m}
    assert tables == {"dim_date", "dim_retail_week", "dim_store", "dim_product", "dim_promotion",
                      "fact_sales", "fact_returns", "fact_inventory", "fact_targets", "fact_promotion_coverage"}
    assert len([m for m in built if m]) == 10


def test_decimal_casts_keep_tsql_rounding():
    eng = BigQueryEngine("proj", "p_", "EU", 1, connect=False)
    (step,) = eng.translate("SELECT CAST(x AS DECIMAL(19,2)) AS a, TRY_CONVERT(DECIMAL(5,4), y) AS b FROM dw.t")
    assert "ROUND(CAST(x AS NUMERIC), 2)" in step.sql and "ROUND(SAFE_CAST(y AS NUMERIC), 4)" in step.sql


def test_median_uses_the_exact_bigquery_form(translated):
    _, steps = translated
    sql = " ".join(s.sql for _, s in steps if s.kind == "query")
    assert "PERCENTILE_CONT(CAST(unit_cost AS FLOAT64), 0.5) OVER (PARTITION BY product_key)" in sql
    assert "APPROX_QUANTILES" not in sql


def test_every_applied_rewrite_rule_is_documented(translated):
    eng, _ = translated
    doc = DOC.read_text(encoding="utf-8")
    assert {r["rule"] for r in eng.rule_log} <= set(RULES)
    for rule in RULES:
        assert rule in doc, rule


# ============================================================ free-tier behaviour (fake client)
class _Job:
    statement_type, total_bytes_processed, total_bytes_billed, output_rows = "SELECT", 0, 0, 0

    def result(self):
        class _Rows(list):
            schema = []
        return _Rows()


class _FakeClient:
    def __init__(self):
        self.query_configs, self.loads = [], []

    def query(self, sql, job_config=None, location=None):
        self.query_configs.append((job_config, location))
        return _Job()

    def load_table_from_file(self, fh, table, job_config=None, location=None):
        self.loads.append((table, job_config, location))
        return _Job()

    def insert_rows(self, *a, **k):            # streaming inserts are a paid feature and must never be used
        raise AssertionError("streaming insert used")

    insert_rows_json = insert_rows_from_dataframe = insert_rows


def test_every_query_job_is_capped_and_loads_are_load_jobs():
    pytest.importorskip("google.cloud.bigquery")
    client = _FakeClient()
    eng = BigQueryEngine("proj", "p_", "EU", BQ_CFG["maximum_bytes_billed"], client=client)
    eng.translate("CREATE TABLE recon.expected (metric_name NVARCHAR(50), expected_value FLOAT)")
    eng.execute("DROP VIEW IF EXISTS mart.v_x")
    eng.query("SELECT 1 AS one")
    eng.load_table("recon.expected", pd.DataFrame({"metric_name": ["a"], "expected_value": [1.0]}))
    assert client.query_configs and all(cfg.maximum_bytes_billed == BQ_CFG["maximum_bytes_billed"] and loc == "EU"
                                        for cfg, loc in client.query_configs)
    (table, job_config, loc), = client.loads
    assert table == "proj.p_recon.expected" and loc == "EU" and job_config.write_disposition == "WRITE_TRUNCATE"


# ============================================================ the live BigQuery build (skip when unavailable)
@pytest.fixture(scope="module")
def live():
    if not credentials_available():
        pytest.skip("BigQuery client or Application Default Credentials not available")
    project = resolve_project(BQ_CFG)
    if not project:
        pytest.skip(f"no BigQuery project ID ({BQ_CFG['project_id_env']} or {BQ_CFG['local_config']})")
    eng = BigQueryEngine(project, BQ_CFG["dataset_prefix"], BQ_CFG["location"], BQ_CFG["maximum_bytes_billed"])
    try:
        for s in SCHEMAS:
            eng.client.get_dataset(f"{project}.{eng.dataset(s)}")
    except Exception:  # noqa: BLE001
        eng.close()
        pytest.skip("BigQuery datasets not built; run python -m src.bigquery_model.run_bigquery")
    yield eng
    eng.close()


def test_live_reconciliation_passes_45_of_45(live):
    recon = live.query("SELECT metric_name, status FROM recon.v_reconciliation")
    assert len(recon) == 45 and (recon["status"] == "PASS").all(), recon[recon["status"] != "PASS"]


def test_live_kpi_validation_passes_38_of_38(live):
    kv = live.query("SELECT check_name, status FROM recon.kpi_validation_result")
    assert len(kv) == 38 and (kv["status"] == "PASS").all(), kv[kv["status"] != "PASS"]


def test_live_h1_and_h2_2025_match_the_governed_figures(live):
    df = live.query("SELECT period, net_revenue_cy, net_revenue_yoy_pct FROM mart.v_yoy_segment_period "
                    "WHERE segment_type = N'Estate' AND retail_year = 2025 AND period IN (N'H1', N'H2')").set_index("period")
    assert round(float(df.loc["H2", "net_revenue_cy"]), 2) == 9457457.05
    assert round(float(df.loc["H2", "net_revenue_yoy_pct"]), 2) == -7.18
    assert round(float(df.loc["H1", "net_revenue_cy"]), 2) == 8629984.78
    assert round(float(df.loc["H1", "net_revenue_yoy_pct"]), 3) == 1.438


def test_live_results_match_duckdb_and_sql_server(live):
    recon = live.query("SELECT metric_name, actual_value, tolerance_abs FROM recon.v_reconciliation").set_index("metric_name")
    for engine in ("duckdb", "mssql"):
        ref = pd.read_csv(ROOT / "reports" / "phase4" / f"reconciliation_results_{engine}.csv").set_index("metric_name")
        assert set(ref.index) == set(recon.index), engine
        diff = (recon["actual_value"].astype(float) - ref["actual_value"].astype(float)).abs()
        tolerance = recon["tolerance_abs"].astype(float).reindex(diff.index)
        assert (diff <= tolerance).all(), (engine, diff[diff > 0].to_dict())
