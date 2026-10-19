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
    default = {n: params[n].find("r:DefaultValue/r:Values/r:Value", NS).text for n in ("Year", "Store")}
    assert default == {"Year": "2025", "Store": "ALL"}


def test_half_parameter_cascades_from_the_selected_year():
    """Half lists only the halves with data for the chosen Year, so 2026 cannot offer an empty H2."""
    half = _report().find(".//r:ReportParameter[@Name='Half']", NS)
    assert half.find("r:ValidValues/r:DataSetReference/r:DataSetName", NS).text == "HalfList"
    assert half.find("r:DefaultValue/r:DataSetReference/r:DataSetName", NS).text == "HalfDefault"
    queries = _queries()
    for name in ("HalfList", "HalfDefault"):
        assert re.findall(r"@(\w+)", queries[name]) == ["Year"], name
        assert _sources(queries[name]) == ["rpt.v_half_parameter"], name
    order = [p.get("Name") for p in _report().iterfind(".//r:ReportParameter", NS)]
    assert order.index("Year") < order.index("Half")            # a cascading parameter follows its parent


def test_partial_half_note_is_driven_by_data_and_parameters():
    note = _report().find(".//r:Textbox[@Name='PartialNote']", NS)
    text = note.find(".//r:TextRun/r:Value", NS).text
    assert "Parameters!Half.Value" in text and "Parameters!Year.Value" in text
    assert '"PeriodStatus"' in text
    assert not re.search(r"\bH[12]\b|\b20\d\d\b", text), text
    assert "Fields!is_partial.Value" in note.find("r:Visibility/r:Hidden", NS).text


def test_estate_section_shows_a_message_when_there_is_no_row():
    root = _report()
    grid = root.find(".//r:Rectangle[@Name='EstateGrid']", NS)
    assert grid.find("r:Visibility/r:Hidden", NS).text == '=CountRows("Estate") = 0'
    inside = {tb.get("Name") for tb in grid.iterfind(".//r:Textbox", NS)}
    estate = {tb.get("Name") for tb in root.iterfind(".//r:Textbox", NS) if "\"Estate\")" in "".join(
        v.text or "" for v in tb.iterfind(".//r:TextRun/r:Value", NS))}
    assert estate and estate <= inside
    message = root.find(".//r:Textbox[@Name='EstateNoData']", NS)
    assert message.find(".//r:TextRun/r:Value", NS).text == "No data for this year and half."
    assert message.find("r:Visibility/r:Hidden", NS).text == '=CountRows("Estate") > 0'


def test_every_query_parameter_is_bound_to_a_report_parameter():
    """A query parameter left unbound, or bound to a constant, would ignore the Year, Half or Store choice."""
    report_params = {p.get("Name") for p in _report().iterfind(".//r:ReportParameter", NS)}
    for ds in _report().iterfind(".//r:DataSet", NS):
        query = ds.find("r:Query", NS)
        used = set(re.findall(r"@(\w+)", query.find("r:CommandText", NS).text))
        bound = {qp.get("Name").lstrip("@"): qp.find("r:Value", NS).text
                 for qp in query.iterfind("r:QueryParameters/r:QueryParameter", NS)}
        assert set(bound) == used, (ds.get("Name"), used, bound)
        for name, value in bound.items():
            assert name in report_params and value == f"=Parameters!{name}.Value", (ds.get("Name"), name, value)
    queries = _queries()
    assert {"Year", "Half"} <= set(re.findall(r"@(\w+)", queries["Estate"]))
    assert {"Year", "Half", "Store"} <= set(re.findall(r"@(\w+)", queries["Stores"]))


def test_period_labels_come_from_the_parameters():
    values = {tb.get("Name"): "".join(v.text or "" for v in tb.iterfind(".//r:TextRun/r:Value", NS))
              for tb in _report().iterfind(".//r:Textbox", NS)}
    assert "Parameters!Half.Value" in values["Subtitle"] and "Parameters!Year.Value" in values["Subtitle"]
    for name in ("EstateHdr_2", "EstateHdr_3"):
        assert "Parameters!Half.Value" in values[name] and "Parameters!Year.Value" in values[name], name
    fixed = {n: v for n, v in values.items() if re.search(r"\bH[12] 20\d\d\b", v)}
    assert not fixed, fixed


def test_every_report_query_reads_only_rpt_views():
    queries = _queries()
    assert set(queries) == {"Gate", "Estate", "Stores", "YearList", "HalfList", "HalfDefault", "PeriodStatus", "StoreList"}
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


def test_estate_h1_2025_follows_the_half_parameter(cursor):
    [row] = _run(cursor, "Estate", Year=2025, Half="H1")
    assert row["period"] == "H1"
    assert row["net_revenue_cy"] == Decimal("8629984.78")
    assert row["net_revenue_py"] == Decimal("8507614.03")
    assert round(row["net_revenue_yoy_pct"], 3) == 1.438
    stores = _run(cursor, "Stores", Year=2025, Half="H1", Store="ALL")
    assert sum(r["net_revenue_cy"] for r in stores) == row["net_revenue_cy"]


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


def test_half_list_offers_only_halves_with_data(cursor):
    assert [r["period"] for r in _run(cursor, "HalfList", Year=2025)] == ["H1", "H2"]
    assert [r["period"] for r in _run(cursor, "HalfList", Year=2026)] == ["H1"]
    assert [r["period"] for r in _run(cursor, "HalfDefault", Year=2025)] == ["H2"]
    assert [r["period"] for r in _run(cursor, "HalfDefault", Year=2026)] == ["H1"]


def test_period_status_flags_only_the_partial_half(cursor):
    [partial] = _run(cursor, "PeriodStatus", Year=2026, Half="H1")
    assert (partial["weeks_with_data"], partial["prior_year_weeks_with_data"], partial["is_partial"]) == (1, 26, 1)
    for half in ("H1", "H2"):
        [full] = _run(cursor, "PeriodStatus", Year=2025, Half=half)
        assert full["is_partial"] == 0, half


def test_parameter_lists(cursor):
    assert 2025 in [r["retail_year"] for r in _run(cursor, "YearList")]
    stores = _run(cursor, "StoreList")
    assert stores[0]["store_value"] == "ALL" and len(stores) == 21
