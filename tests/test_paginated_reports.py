"""Paginated report tests: powerbi/paginated/Executive_KPI_Summary.rdl and its rpt views.

The XML checks always run. The database checks run each report query against the local SQL Server
(Windows authentication) and skip when SQL Server, the BrightwaterRetail database or the rpt views
(sql/reporting/01_rpt_views.sql) are not available. Nothing here writes to the database or the repo.
"""
import getpass
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.sql_model.scripts import strip_comments

ROOT = Path(__file__).resolve().parents[1]
RDL = ROOT / "powerbi" / "paginated" / "Executive_KPI_Summary.rdl"
RPT_SQL = ROOT / "sql" / "reporting" / "01_rpt_views.sql"
NS = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}

H2_2025_NET_REVENUE = Decimal("9457457.05")       # governed headline, reports/phase3/kpi_reconciliation.csv
H2_2024_NET_REVENUE = Decimal("10188727.55")
H2_YOY_PCT = -7.177


def _report():
    return ET.parse(RDL).getroot()


def _queries():
    return {ds.get("Name"): ds.find("r:Query/r:CommandText", NS).text for ds in _report().iterfind(".//r:DataSet", NS)}


def _sources(sql):
    """Object names that follow FROM or JOIN."""
    return re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", sql, flags=re.IGNORECASE)


# ============================================================ report definition (always)
def test_rdl_is_well_formed_rdl_2016():
    assert _report().tag == f"{{{NS['r']}}}Report"


def test_data_source_is_local_windows_auth_without_credentials():
    ds = _report().findall(".//r:DataSource", NS)
    assert len(ds) == 1
    conn = ds[0].find("r:ConnectionProperties", NS)
    cs = conn.find("r:ConnectString", NS).text
    assert "Data Source=localhost" in cs and "Initial Catalog=BrightwaterRetail" in cs
    assert conn.find("r:IntegratedSecurity", NS).text == "true"
    text = RDL.read_text(encoding="utf-8")
    for secret in ("User ID", "Password", "Uid=", "Pwd=", "\\Users\\"):
        assert secret.lower() not in text.lower(), secret
    assert getpass.getuser().lower() not in text.lower()


def test_parameters_are_year_half_and_store_with_governed_defaults():
    params = {p.get("Name"): p for p in _report().iterfind(".//r:ReportParameter", NS)}
    assert list(params) == ["Year", "Half", "Store"]
    default = {n: p.find("r:DefaultValue/r:Values/r:Value", NS).text for n, p in params.items()}
    assert default == {"Year": "2025", "Half": "H2", "Store": "ALL"}
    halves = [v.text for v in params["Half"].iterfind(".//r:ParameterValue/r:Value", NS)]
    assert halves == ["H1", "H2"]


def test_every_report_query_reads_only_rpt_views():
    queries = _queries()
    assert set(queries) == {"Gate", "Estate", "Stores", "YearList", "StoreList"}
    for name, sql in queries.items():
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXEC|MERGE|TRUNCATE)\b", sql, re.I), name
        sources = _sources(sql)
        assert sources and all(s.startswith("rpt.") for s in sources), (name, sources)


def test_report_shows_the_validation_gate():
    text = RDL.read_text(encoding="utf-8")
    assert "rpt.v_validation_gate" in _queries()["Gate"]
    assert "Validation gate PASS" in text and "VALIDATION GATE FAILED" in text


def test_rpt_views_are_thin_and_outside_the_governed_build():
    text = RPT_SQL.read_text(encoding="utf-8")
    assert text.count("/*") == text.count("*/")         # SQL Server nests block comments (KI-05)
    sql = strip_comments(text)
    views = re.findall(r"CREATE OR ALTER VIEW\s+([\w.]+)", sql)
    assert views and all(v.startswith("rpt.") for v in views)
    assert all(re.match(r"(mart|recon)\.v_", s) for s in _sources(sql)), _sources(sql)
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|MERGE)\b", sql, re.I)
    assert "reporting" not in (ROOT / "config" / "sql_model_config.yaml").read_text(encoding="utf-8")


def test_no_em_dash_in_report_files():
    for f in (RDL, RPT_SQL, Path(__file__)):
        assert "\u2014" not in f.read_text(encoding="utf-8"), f.name


# ============================================================ against SQL Server (skip when unavailable)
@pytest.fixture(scope="module")
def cursor():
    pyodbc = pytest.importorskip("pyodbc")
    db = yaml.safe_load((ROOT / "config" / "project_config.yaml").read_text(encoding="utf-8"))["database"]
    cs = (f"DRIVER={{{db['driver']}}};SERVER={db['server']};DATABASE={db['database']};"
          "Trusted_Connection=yes;TrustServerCertificate=yes")
    try:
        con = pyodbc.connect(cs, timeout=5, readonly=True)
    except pyodbc.Error as e:
        pytest.skip(f"SQL Server not available: {e.args[0] if e.args else e}")
    cur = con.cursor()
    if cur.execute("SELECT SCHEMA_ID(N'rpt')").fetchone()[0] is None:
        con.close()
        pytest.skip("rpt views not created; run sql/reporting/01_rpt_views.sql")
    yield cur
    con.close()


def _run(cursor, dataset, **params):
    """Run one report query exactly as written in the RDL, binding @parameters in order."""
    sql = _queries()[dataset]
    names = re.findall(r"@(\w+)", sql)
    rows = cursor.execute(re.sub(r"@\w+", "?", sql), *[params[n] for n in names]).fetchall()
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


def test_gate_passes_45_of_45_and_38_of_38(cursor):
    gate = {r["check_set"]: r for r in _run(cursor, "Gate")}
    assert (gate["Reconciliation"]["checks"], gate["Reconciliation"]["passed"]) == (45, 45)
    assert (gate["KPI validation"]["checks"], gate["KPI validation"]["passed"]) == (38, 38)
    assert {r["gate_status"] for r in gate.values()} == {"PASS"}


def test_estate_h2_2025_matches_the_governed_headline(cursor):
    [row] = _run(cursor, "Estate", Year=2025, Half="H2")
    assert row["net_revenue_cy"] == H2_2025_NET_REVENUE
    assert row["net_revenue_py"] == H2_2024_NET_REVENUE
    assert row["net_revenue_change"] == H2_2025_NET_REVENUE - H2_2024_NET_REVENUE
    assert round(row["net_revenue_yoy_pct"], 3) == H2_YOY_PCT


def test_all_stores_sum_to_the_estate(cursor):
    [estate] = _run(cursor, "Estate", Year=2025, Half="H2")
    stores = _run(cursor, "Stores", Year=2025, Half="H2", Store="ALL")
    assert len(stores) == 20
    for col in ("net_revenue_cy", "net_revenue_py", "net_revenue_change"):
        assert sum(r[col] for r in stores) == estate[col], col


def test_store_parameter_filters_to_one_store(cursor):
    everyone = {r["store_label"]: r for r in _run(cursor, "Stores", Year=2025, Half="H2", Store="ALL")}
    label = "S03 Dublin Blanchardstown"
    [row] = _run(cursor, "Stores", Year=2025, Half="H2", Store=label)
    assert row == everyone[label]


def test_period_without_data_returns_no_rows(cursor):
    assert _run(cursor, "Estate", Year=2026, Half="H2") == []
    assert _run(cursor, "Stores", Year=2026, Half="H2", Store="ALL") == []


def test_parameter_lists(cursor):
    assert 2025 in [r["retail_year"] for r in _run(cursor, "YearList")]
    stores = _run(cursor, "StoreList")
    assert stores[0]["store_value"] == "ALL" and len(stores) == 21
