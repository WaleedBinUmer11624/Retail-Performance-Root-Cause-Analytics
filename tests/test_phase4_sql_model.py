"""Phase 4 tests: star schema grain, keys, UNKNOWN members, nullability, relationships, KPI identities,
reconciliation, idempotence, T-SQL syntax and isolation from evaluation-only assets.

The model is built once per session on the local verification engine (DuckDB) from the full curated
data. Constraints that DuckDB cannot declare with ALTER TABLE (fact PKs, FKs, CHECKs in script 05) are
parsed from the T-SQL script and verified as queries, so the SQL Server constraints are known to hold.
"""
import ast
import builtins
import re
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest
import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel

from src.sql_model.engines import DuckDBEngine
from src.sql_model.inputs import InputError, load_config, verify_curated
from src.sql_model.scripts import split_batches, strip_comments

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "processed" / "curated"
SQL_FILES = sorted(ROOT.glob("sql/*/[01][0-9]_*.sql"))
KEYS_SQL = ROOT / "sql" / "schema" / "05_create_keys_and_constraints.sql"
EVALUATION_ASSETS = ("_hidden_scenario", "_scenario_answer_key", "_planted_issues_log", "_generation_manifest",
                     "phase2_calibration_report", "phase2_full_validation", "phase2_full_scale_projection",
                     "reconcile_headline", "phase3_detection_scorecard", "phase3_correction_accuracy",
                     "phase3_extra_findings", "phase3_not_detected", "phase3_freeze", "evaluate_phase3",
                     "reports/evaluation", "independent_blind_profile")

needs_curated = pytest.mark.skipif(not (CURATED / "fact_sales.csv").exists(), reason="curated data not present")


# ============================================================ build once
@pytest.fixture(scope="session")
def model(tmp_path_factory):
    """Build the Phase 4 model on DuckDB once per session; yields (result, engine, files opened)."""
    if not (CURATED / "fact_sales.csv").exists():
        pytest.skip("curated data not present")
    from src.sql_model import run_model
    d = tmp_path_factory.mktemp("phase4")
    opened = []
    real_open = builtins.open

    def tracing_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    with mock.patch("builtins.open", tracing_open), mock.patch("io.open", tracing_open):
        res = run_model.run("duckdb", str(d / "model.duckdb"), out_dir=d / "reports", keep_engine=True)
    yield res, res["engine"], opened
    res["engine"].close()


def q(engine, sql):
    """Run SQL and return a DataFrame."""
    return engine.query(sql)


def scalar(engine, sql):
    """Run SQL and return the first cell."""
    return q(engine, sql).iloc[0, 0]


# ============================================================ reconciliation and KPI validation
@needs_curated
def test_build_passed(model):
    res, _, _ = model
    assert res["passed"], res["summary"]


@needs_curated
def test_row_count_reconciliation(model):
    r = model[0]["reconciliation"]
    rc = r[r["metric_group"] == "row_count"]
    assert len(rc) == 17 and (rc["status"] == "PASS").all() and (rc["abs_difference"] == 0).all()


@needs_curated
def test_financial_reconciliation_within_tolerance(model):
    r = model[0]["reconciliation"].set_index("metric_name")
    for m in ("sales_revenue", "returns_value", "net_revenue", "h2_2024_net_revenue", "h2_2025_net_revenue",
              "h2_yoy_pct", "gross_margin", "transactions", "units", "cogs", "gross_sales", "discount_value"):
        assert r.loc[m, "status"] == "PASS", m
        assert r.loc[m, "abs_difference"] <= r.loc[m, "tolerance_abs"], m
    assert r.loc["transactions", "tolerance_abs"] == 0 and r.loc["units", "tolerance_abs"] == 0


@needs_curated
def test_kpi_validation_all_pass(model):
    k = model[0]["kpi_validation"]
    assert len(k) >= 35 and (k["status"] == "PASS").all(), k[k["status"] != "PASS"].to_string()


@needs_curated
def test_tolerance_breach_fails(model):
    """A value outside tolerance must turn the check to FAIL (then the build exits 1 / THROWs on SQL Server)."""
    _, eng, _ = model
    eng.execute("UPDATE recon.expected SET expected_value = expected_value + 0.02 WHERE metric_name = 'net_revenue'")
    eng.execute("UPDATE recon.expected SET expected_value = expected_value + 1 WHERE metric_name = 'rows_dw_fact_sales'")
    try:
        r = q(eng, "SELECT metric_name, status FROM recon.v_reconciliation").set_index("metric_name")["status"]
        assert r["net_revenue"] == "FAIL" and r["rows_dw_fact_sales"] == "FAIL"
        assert (r.drop(["net_revenue", "rows_dw_fact_sales"]) == "PASS").all()
    finally:
        eng.execute("UPDATE recon.expected SET expected_value = expected_value - 0.02 WHERE metric_name = 'net_revenue'")
        eng.execute("UPDATE recon.expected SET expected_value = expected_value - 1 WHERE metric_name = 'rows_dw_fact_sales'")
    assert (q(eng, "SELECT status FROM recon.v_reconciliation")["status"] == "PASS").all()


@needs_curated
def test_missing_metric_fails(model):
    _, eng, _ = model
    eng.execute("INSERT INTO recon.expected VALUES ('phantom_metric', 'kpi', 1, 0, 'test')")
    try:
        r = q(eng, "SELECT metric_name, status FROM recon.v_reconciliation").set_index("metric_name")["status"]
        assert r["phantom_metric"] == "FAIL"
    finally:
        eng.execute("DELETE FROM recon.expected WHERE metric_name = 'phantom_metric'")


# ============================================================ grain, keys, constraints
def _constraints():
    """Parse PRIMARY KEY / FOREIGN KEY / CHECK constraints from script 05 (T-SQL)."""
    pks, fks, checks = [], [], []
    text = strip_comments(KEYS_SQL.read_text())
    for m in re.finditer(r"ALTER TABLE (\S+)\s+ADD CONSTRAINT (\S+)\s+PRIMARY KEY (?:NON)?CLUSTERED \(([^)]+)\)", text):
        pks.append((m.group(1), [c.strip() for c in m.group(3).split(",")]))
    for m in re.finditer(r"ALTER TABLE (\S+)\s+ADD CONSTRAINT (\S+)\s+FOREIGN KEY \((\w+)\)\s+REFERENCES (\S+) \((\w+)\)", text):
        fks.append((m.group(1), m.group(3), m.group(4), m.group(5), m.group(2)))
    for m in re.finditer(r"ALTER TABLE (\S+)\s+ADD CONSTRAINT (\S+)\s+CHECK \((.+)\);", text):
        checks.append((m.group(1), m.group(2), m.group(3)))
    return pks, fks, checks


def test_constraint_script_declares_grain_and_relationships():
    pks, fks, checks = _constraints()
    assert {t for t, _ in pks} == {"dw.fact_sales", "dw.fact_returns", "dw.fact_inventory", "dw.fact_targets",
                                   "dw.fact_promotion_coverage"}
    fk_cols = {(t, c) for t, c, *_ in fks}
    for t in ("dw.fact_sales", "dw.fact_returns", "dw.fact_inventory", "dw.fact_targets", "dw.fact_promotion_coverage"):
        ddl = strip_comments((ROOT / "sql/schema/04_create_fact_tables.sql").read_text())
        block = ddl[ddl.index(f"CREATE TABLE {t} ("):]
        block = block[:block.index(");")]
        key_cols = re.findall(r"^\s+(\w+_key)\s", block, flags=re.MULTILINE)
        assert key_cols and all((t, c) in fk_cols for c in key_cols), (t, key_cols)
    assert len(checks) >= 8


@needs_curated
@pytest.mark.parametrize("table,cols", [("dw.dim_date", ["date_key"]), ("dw.dim_retail_week", ["retail_week_key"]),
                                        ("dw.dim_store", ["store_key"]), ("dw.dim_store", ["store_id"]),
                                        ("dw.dim_product", ["product_key"]), ("dw.dim_product", ["product_id"]),
                                        ("dw.dim_promotion", ["promotion_key"]), ("dw.dim_promotion", ["promotion_id"]),
                                        ("dw.fact_sales", ["sales_line_id"])] + _constraints()[0])
def test_uniqueness_at_declared_grain(model, table, cols):
    _, eng, _ = model
    c = ", ".join(cols)
    dup = scalar(eng, f"SELECT COUNT(*) FROM (SELECT {c} FROM {table} GROUP BY {c} HAVING COUNT(*) > 1) AS d")
    nulls = scalar(eng, f"SELECT COUNT(*) FROM {table} WHERE " + " OR ".join(f"{x} IS NULL" for x in cols))
    assert dup == 0 and nulls == 0


@needs_curated
@pytest.mark.parametrize("fk", _constraints()[1], ids=lambda f: f[4])
def test_foreign_keys_hold(model, fk):
    _, eng, _ = model
    table, col, ref, ref_col, _ = fk
    orphans = scalar(eng, f"SELECT COUNT(*) FROM {table} AS f LEFT JOIN {ref} AS d ON d.{ref_col} = f.{col} "
                          f"WHERE d.{ref_col} IS NULL")
    assert orphans == 0


@needs_curated
@pytest.mark.parametrize("chk", _constraints()[2], ids=lambda c: c[1])
def test_check_constraints_hold(model, chk):
    _, eng, _ = model
    table, _, expr = chk
    bad = scalar(eng, f"SELECT COUNT(*) FROM {table} WHERE NOT ({expr})")
    assert bad == 0


@needs_curated
def test_every_fact_row_joins_exactly_one_member_per_dimension(model):
    _, eng, _ = model
    n = scalar(eng, "SELECT COUNT(*) FROM dw.fact_sales")
    joined = scalar(eng, """SELECT COUNT(*) FROM dw.fact_sales f
        JOIN dw.dim_date d ON d.date_key = f.date_key JOIN dw.dim_store s ON s.store_key = f.store_key
        JOIN dw.dim_product p ON p.product_key = f.product_key JOIN dw.dim_promotion pr ON pr.promotion_key = f.promotion_key
        JOIN dw.dim_retail_week w ON w.retail_week_key = d.retail_week_key""")
    assert joined == n
    n = scalar(eng, "SELECT COUNT(*) FROM dw.fact_inventory")
    joined = scalar(eng, """SELECT COUNT(*) FROM dw.fact_inventory f JOIN dw.dim_date d ON d.date_key = f.snapshot_date_key
        JOIN dw.dim_retail_week w ON w.retail_week_key = f.retail_week_key AND w.retail_week_key = d.retail_week_key""")
    assert joined == n            # snapshot date and week key agree


# ============================================================ UNKNOWN members
@needs_curated
@pytest.mark.parametrize("table,key", [("dw.dim_date", "date_key"), ("dw.dim_retail_week", "retail_week_key"),
                                       ("dw.dim_store", "store_key"), ("dw.dim_product", "product_key"),
                                       ("dw.dim_promotion", "promotion_key")])
def test_unknown_member_exists_once(model, table, key):
    _, eng, _ = model
    r = q(eng, f"SELECT {key} AS k, is_unknown FROM {table} WHERE is_unknown = 1")
    assert r["k"].tolist() == [-1]


@needs_curated
def test_no_promotion_member_is_not_unknown(model):
    _, eng, _ = model
    r = q(eng, "SELECT promotion_key, member_type, is_unknown FROM dw.dim_promotion WHERE promotion_key IN (0, -1) "
               "ORDER BY promotion_key")
    assert r.values.tolist() == [[-1, "Unknown", 1], [0, "No promotion", 0]]


@needs_curated
def test_unknown_member_usage_matches_curated_data(model):
    _, eng, _ = model
    s = pd.read_csv(CURATED / "fact_sales.csv", usecols=["product_id", "promotion_id"], dtype=str, keep_default_na=False)
    assert scalar(eng, "SELECT COUNT(*) FROM dw.fact_sales WHERE product_key = -1") == (s["product_id"] == "UNKNOWN").sum()
    assert scalar(eng, "SELECT COUNT(*) FROM dw.fact_sales WHERE promotion_key = -1") == (s["promotion_id"] == "UNKNOWN").sum()
    assert scalar(eng, "SELECT COUNT(*) FROM dw.fact_sales WHERE promotion_key = 0") == (s["promotion_id"] == "").sum()
    # returns: the sale roles are UNKNOWN exactly when the sale line is not in fact_sales
    bad = scalar(eng, """SELECT COUNT(*) FROM dw.fact_returns WHERE
        (original_sales_line_id IS NULL) <> (original_sale_date_key = -1)
        OR (original_sales_line_id IS NULL) <> (original_sale_store_key = -1)""")
    assert bad == 0


# ============================================================ nullability of mandatory analytical fields
@needs_curated
@pytest.mark.parametrize("table,cols", [
    ("dw.dim_date", ["calendar_date", "day_of_week", "calendar_year", "retail_year", "retail_week", "retail_half",
                     "is_trading_day"]),
    ("dw.dim_retail_week", ["retail_year", "retail_week", "week_start_date", "week_end_date", "retail_half"]),
    ("dw.dim_store", ["store_name", "region", "store_format", "floor_area_m2", "open_date"]),
    ("dw.dim_product", ["product_name", "category", "subcategory", "brand", "list_price", "unit_cost", "launch_date"]),
    ("dw.dim_promotion", ["promotion_name", "promotion_type", "start_date", "end_date", "max_discount_pct"]),
])
def test_mandatory_dimension_attributes_populated(model, table, cols):
    _, eng, _ = model
    cond = " OR ".join(f"{c} IS NULL" for c in cols)
    member = "is_unknown = 0" + (" AND promotion_key > 0" if table == "dw.dim_promotion" else "")
    assert scalar(eng, f"SELECT COUNT(*) FROM {table} WHERE {member} AND ({cond})") == 0


@needs_curated
@pytest.mark.parametrize("table,cols", [
    ("dw.fact_sales", ["transaction_time", "extract_lag_days"]),
    ("dw.fact_targets", ["target_set_date"]),
])
def test_nullable_fact_columns_fully_populated_from_curated(model, table, cols):
    _, eng, _ = model
    assert scalar(eng, f"SELECT COUNT(*) FROM {table} WHERE " + " OR ".join(f"{c} IS NULL" for c in cols)) == 0


# ============================================================ traceability and quarantine exclusion
@needs_curated
@pytest.mark.parametrize("table", ["fact_sales", "fact_returns", "fact_inventory", "fact_targets",
                                   "fact_promotion_coverage"])
def test_every_fact_row_traces_to_one_raw_line(model, table):
    _, eng, _ = model
    dup = scalar(eng, f"SELECT COUNT(*) FROM (SELECT source_file, source_row FROM dw.{table} "
                      f"GROUP BY source_file, source_row HAVING COUNT(*) > 1) AS d")
    missing = scalar(eng, f"SELECT COUNT(*) FROM dw.{table} WHERE source_file IS NULL OR source_row IS NULL")
    assert dup == 0 and missing == 0


@needs_curated
@pytest.mark.parametrize("fact,qfile", [("fact_sales", "fact_sales_quarantine.csv"),
                                        ("fact_returns", "fact_returns_quarantine.csv"),
                                        ("fact_inventory", "fact_inventory_quarantine.csv"),
                                        ("fact_targets", "fact_targets_quarantine.csv"),
                                        ("fact_promotion_coverage", "fact_promotions_quarantine.csv")])
def test_quarantined_rows_never_enter_facts(model, fact, qfile):
    _, eng, _ = model
    qdf = pd.read_csv(ROOT / "data" / "processed" / "quarantine" / qfile, dtype=str, usecols=["source_file", "source_row"])
    f = q(eng, f"SELECT source_file, source_row FROM dw.{fact}")
    fk = set(zip(f["source_file"], f["source_row"].astype(str)))
    assert not fk & set(zip(qdf["source_file"], qdf["source_row"]))


@needs_curated
def test_fact_values_equal_curated_values(model):
    """Business values pass through unchanged (sampled lines compared field by field)."""
    _, eng, _ = model
    cur = pd.read_csv(CURATED / "fact_sales.csv", dtype=str).sample(500, random_state=4)
    f = q(eng, "SELECT transaction_id, line_number, quantity, unit_price, discount_amount, sales_revenue, cost_amount, "
               "margin_amount FROM dw.fact_sales")
    f = f.set_index(f["transaction_id"] + "|" + f["line_number"].astype(str))
    for _, r in cur.iterrows():
        row = f.loc[f"{r['transaction_id']}|{r['line_number']}"]
        assert int(row["quantity"]) == int(r["quantity"])
        for a, b in (("unit_price", "unit_price"), ("discount_amount", "discount"), ("sales_revenue", "revenue"),
                     ("cost_amount", "cost"), ("margin_amount", "margin")):
            assert abs(float(row[a]) - float(r[b])) < 0.005, (a, r["transaction_id"])


@needs_curated
def test_generated_expected_values_script_loads_the_same_expectations(model):
    """The SSMS/sqlcmd path (sql/run_all_sqlcmd.sql) uses the runner-generated expected-values script."""
    res, eng, _ = model
    gen = ROOT / "reports" / "phase4" / "generated" / "recon_expected_values.sql"
    if not gen.exists():
        pytest.skip("generated script not present")
    for b in split_batches(gen):
        eng.run_batch(b)
    r = q(eng, "SELECT status FROM recon.v_reconciliation")
    assert len(r) == len(res["reconciliation"]) and (r["status"] == "PASS").all()


# ============================================================ repeatability
@needs_curated
def test_rebuild_is_idempotent(model):
    """Re-running the load scripts on the existing database gives identical keys and totals."""
    _, eng, _ = model
    snap_sql = {
        "fact_sales": "SELECT COUNT(*) n, SUM(sales_line_id) a, SUM(product_key) b, SUM(promotion_key) c, "
                      "SUM(sales_revenue) d, SUM(store_key) e FROM dw.fact_sales",
        "fact_returns": "SELECT COUNT(*) n, SUM(COALESCE(original_sales_line_id, 0)) a, SUM(restock_cost_credit) b, "
                        "SUM(refund_value) c FROM dw.fact_returns",
        "dim_product": "SELECT COUNT(*) n, SUM(product_key * LENGTH(product_id)) a FROM dw.dim_product",
        "dim_promotion": "SELECT COUNT(*) n, SUM(promotion_key * LENGTH(promotion_id)) a FROM dw.dim_promotion",
        "recon": "SELECT COUNT(*) n, SUM(actual_value) a FROM recon.actual",
    }
    before = {k: q(eng, s).round(6).values.tolist() for k, s in snap_sql.items()}
    for f in ("sql/transformations/07_load_dimensions.sql", "sql/transformations/08_load_facts.sql",
              "sql/validation/09_reconciliation.sql"):
        for b in split_batches(ROOT / f):
            if b.runs_on("duckdb"):
                eng.run_batch(b)
    after = {k: q(eng, s).round(6).values.tolist() for k, s in snap_sql.items()}
    assert before == after
    assert (q(eng, "SELECT status FROM recon.v_reconciliation")["status"] == "PASS").all()


# ============================================================ SQL scripts
def test_every_tsql_statement_parses():
    known_fallbacks = ("ALTER DATABASE", "ALTER INDEX")
    for f in SQL_FILES:
        for b in split_batches(f):
            if b.target == "duckdb":
                continue
            for s in sqlglot.parse(strip_comments(b.text), read="tsql", error_level=ErrorLevel.RAISE):
                if isinstance(s, exp.Command):
                    assert s.sql().upper().startswith(known_fallbacks), (f.name, s.sql()[:80])


def test_every_portable_batch_translates_to_duckdb():
    for f in SQL_FILES:
        for b in split_batches(f):
            if b.runs_on("duckdb"):
                assert DuckDBEngine.translate(b.text), (f.name, b.index)


def test_scripts_run_in_configured_order_and_all_exist():
    cfg, _ = load_config()
    files = [s for s in cfg["scripts"] if not s.startswith("@")]
    assert [int(Path(s).name[:2]) for s in files] == list(range(1, 12))
    assert all((ROOT / s).exists() for s in files)


def test_views_are_created_in_their_own_batch():
    """SQL Server requires CREATE VIEW to be the first statement of a batch."""
    for f in SQL_FILES:
        for b in split_batches(f):
            code = strip_comments(b.text).strip()
            if re.search(r"CREATE OR ALTER VIEW", code, flags=re.IGNORECASE):
                assert code.upper().startswith("CREATE OR ALTER VIEW"), (f.name, b.index)
                assert len(re.findall(r"CREATE OR ALTER VIEW", code, flags=re.IGNORECASE)) == 1


def _view_body(path, view):
    text = strip_comments((ROOT / path).read_text())
    start = text.index(f"CREATE OR ALTER VIEW {view} AS")
    body = text[start:]
    return re.split(r"^\s*GO\s*$", body, maxsplit=1, flags=re.MULTILINE)[0]      # the view's own batch


@pytest.mark.parametrize("path,view", [("sql/analysis/10_analytical_views.sql", "mart.v_sales_store_day"),
                                       ("sql/analysis/10_analytical_views.sql", "mart.v_returns_store_day"),
                                       ("sql/analysis/10_analytical_views.sql", "mart.v_performance_category_week"),
                                       ("sql/validation/09_reconciliation.sql", "recon.v_dw_totals")])
def test_money_sums_are_bounded_before_subtraction(path, view):
    """SQL Server rounds (38,2) - (38,4) to 2 dp (precision > 38). Component sums that are later subtracted
    (sales, cost, returns, restock credit) must be cast to DECIMAL(19,x) first."""
    body = _view_body(path, view)
    money = r"(gross_amount|discount_amount|sales_revenue|cost_amount|refund_value|restock_cost_credit)"
    raw = re.findall(r"(?<!CAST\()SUM\(\s*(?:\w+\.)?" + money + r"\s*\)", body)
    raw += re.findall(r"(?<!CAST\()SUM\(CASE WHEN [^)]*THEN (?:\w+\.)?" + money, body)
    assert not raw, (view, raw)


def test_staging_columns_match_curated_csv_headers():
    """BULK INSERT maps by position, so staging column order must equal the CSV header."""
    ddl = strip_comments((ROOT / "sql/staging/02_create_staging_tables.sql").read_text())
    for t in ("dim_date", "dim_store", "dim_product", "fact_sales", "fact_returns", "fact_inventory", "fact_promotions",
              "fact_targets"):
        block = ddl[ddl.index(f"CREATE TABLE stg.{t} ("):]
        block = block[:block.index(");")]
        cols = [c.strip("[]") for c in re.findall(r"^\s+(\[?\w+\]?)\s+NVARCHAR", block, flags=re.MULTILINE)]
        if (CURATED / f"{t}.csv").exists():
            header = (CURATED / f"{t}.csv").read_text().split("\n", 1)[0].split(",")
            assert cols == header, t


def test_kpi_dictionary_covers_required_kpis():
    text = (ROOT / "sql/analysis/10_analytical_views.sql").read_text()
    for k in ("Gross Sales", "Discount Value", "Sales Revenue", "Returns Value", "Net Revenue", "Transactions",
              "Units Sold", "Average Order Value", "Units per Transaction", "Average Selling Price", "Gross Margin",
              "Gross Margin %", "Return Rate % (value)", "Promo Revenue Share %", "Stock Availability %",
              "Target Achievement %", "YoY Growth %"):
        assert f"(N'{k}'," in text, k


@needs_curated
def test_required_analytical_views_exist(model):
    inv = model[0]["inventory"]
    views = set(inv.loc[inv["table_type"] == "VIEW", "table_name"])
    for v in ("v_performance_store_day", "v_performance_store_week", "v_kpi_segment_period", "v_kpi_estate_period",
              "v_kpi_store_period", "v_yoy_segment_period", "v_yoy_store_week", "v_performance_category_week",
              "v_kpi_category_period", "v_product_store_week", "v_availability_store_week",
              "v_availability_category_week", "v_promotion_performance", "v_returns_analysis", "v_sales_line"):
        assert v in views, v


# ============================================================ anti-leakage
def _phase4_files():
    return (list((ROOT / "src" / "sql_model").glob("*.py")) + SQL_FILES +
            [ROOT / "config" / "sql_model_config.yaml"])


def test_phase4_code_never_names_an_evaluation_asset():
    offenders = [f"{f.name}: {a}" for f in _phase4_files() for a in EVALUATION_ASSETS if a in f.read_text()]
    assert not offenders, offenders


def test_phase4_code_does_not_import_generator_evaluation_or_dq_code():
    for f in (ROOT / "src" / "sql_model").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for m in mods:
                assert not any(x in m for x in ("data_generation", "evaluation", "data_quality")), (f.name, m)


def test_input_guard_refuses_evaluation_assets():
    from src.sql_model.inputs import _allowed
    cfg, _ = load_config()
    for bad in ("data/raw/_planted_issues_log.csv", "data/raw/_scenario_answer_key.csv", "config/_hidden_scenario.yaml",
                "reports/evaluation/phase3_detection_scorecard.csv", "reports/phase2_calibration_report.json",
                "data/raw/fact_sales.csv"):
        with pytest.raises(InputError):
            _allowed(cfg, bad)


def test_curated_hash_guard_detects_changed_input(monkeypatch):
    from src.sql_model import inputs
    cfg, _ = load_config()
    real = inputs.phase3_lineage

    def tampered(c):
        lin = real(c)
        lin["outputs"]["fact_targets"]["sha256"] = "0" * 64
        return lin
    monkeypatch.setattr(inputs, "phase3_lineage", tampered)
    if (CURATED / "fact_targets.csv").exists():
        with pytest.raises(InputError):
            verify_curated(cfg)


@needs_curated
def test_run_never_opens_an_evaluation_asset(model):
    _, _, opened = model
    names = [p.replace("\\", "/") for p in opened]
    bad = [p for p in names if any(a in p for a in EVALUATION_ASSETS) or
           (Path(p).name.startswith("_") and not Path(p).name.startswith("__"))]
    assert not bad, bad
    data_reads = {Path(p).name for p in names if "/data/" in p}
    assert data_reads <= {f"{t}.csv" for t in ("dim_date", "dim_store", "dim_product", "fact_sales", "fact_returns",
                                               "fact_inventory", "fact_promotions", "fact_targets")} | {"model.duckdb"}
    assert any(p.endswith("reports/phase3/kpi_reconciliation.csv") for p in names)

