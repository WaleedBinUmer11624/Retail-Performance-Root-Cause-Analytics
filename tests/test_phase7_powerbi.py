"""Phase 7 tests: freeze, reconciliation of every dashboard measure and number, evidence labels, DAX static checks,
TMDL / Power Query / validation-query assets, independence from evaluation assets, determinism.

The session fixture runs the whole Phase 7 build once (DuckDB engine, about 40 seconds) into temporary folders
while recording every file it opens, then compares the fresh assets with the committed ones.
"""
from __future__ import annotations

import ast
import builtins
import math
import re
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "processed" / "curated"
REPORTS = ROOT / "reports" / "phase7"
PBI = ROOT / "powerbi"
EVALUATION_ASSETS = ("_hidden_scenario", "_scenario_answer_key", "_planted_issues_log", "_generation_manifest",
                     "phase2_calibration_report", "phase2_full_validation", "phase2_full_scale_projection",
                     "phase3_detection_scorecard", "phase3_correction_accuracy", "phase3_extra_findings",
                     "phase3_not_detected", "phase3_freeze", "evaluate_phase3", "reports/evaluation", "evaluation/",
                     "independent_blind_profile", "reconcile_headline", "answer_key", "planted")
CODE = sorted((ROOT / "src" / "powerbi").glob("*.py"))
SQL = sorted((ROOT / "sql" / "powerbi").glob("*.sql"))
CONFIG = [ROOT / "config" / "powerbi_config.yaml"]

from src.powerbi.dax import MEASURES as _DAX_MEASURES  # noqa: E402

MEASURE_NAMES = {m.name for m in _DAX_MEASURES}
needs_curated = pytest.mark.skipif(not (CURATED / "fact_sales.csv").exists(), reason="curated data not present")


@pytest.fixture(scope="session")
def phase7(tmp_path_factory):
    from src.powerbi import run_phase7
    out = tmp_path_factory.mktemp("phase7_reports")
    assets = tmp_path_factory.mktemp("phase7_assets")
    opened = []
    real_open = builtins.open

    def tracing_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    with mock.patch("builtins.open", tracing_open), mock.patch("io.open", tracing_open):
        res = run_phase7.run("duckdb", out_dir=out, make_mockups=False, asset_root=assets)
    res["traced"] = opened
    res["assets"] = assets
    return res


def _cfg():
    from src.powerbi.access import load_config
    return load_config()


# ============================================================================= freeze
def test_freeze_manifest_covers_phase1_6():
    man = pd.read_csv(REPORTS / "phase1_6_input_manifest.csv")
    files = set(man["file"])
    assert len(man) >= 150 and man["sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    for must in ("reports/phase6/root_cause_evidence_matrix.csv", "reports/phase6/driver_attribution.csv",
                 "reports/phase6/phase6_root_cause_report.md", "src/rca/run_phase6.py", "sql/analysis/rca/01_store_cluster.sql",
                 "reports/phase5/headline_kpis.csv", "sql/analysis/10_analytical_views.sql", "tests/test_phase6_rca.py",
                 "data/processed/curated/fact_sales.csv"):
        assert must in files, must


def test_freeze_verifies_on_the_current_tree():
    from src.powerbi.access import verify_freeze
    assert (verify_freeze(_cfg())["status"] == "UNCHANGED").all()


def test_freeze_detects_a_changed_phase6_file(monkeypatch):
    from src.powerbi import access as A
    real = A.sha256_normalised
    monkeypatch.setattr(A, "sha256_normalised",
                        lambda p: "0" * 64 if Path(p).name == "driver_attribution.csv" else real(p))
    with pytest.raises(A.InputError, match="changed"):
        A.verify_freeze(_cfg())


# ============================================================================= reconciliation
@needs_curated
def test_all_checks_pass(phase7):
    c = phase7["checks"]
    assert len(c) >= 90 and (c["status"] == "PASS").all(), c[c["status"] != "PASS"].to_string()
    assert phase7["passed"]
    for g in ("Headline", "Phase 4", "Phase 5", "Phase 6", "Weekly", "Stores", "Categories", "Attribution", "Evidence",
              "Traceability", "DAX", "Targets", "Promotions"):
        assert g in set(c["group"]), g


@needs_curated
def test_headline_exact(phase7):
    from src.powerbi.reference import evaluate, h2
    M = phase7["model"]
    assert evaluate(M, "Net Revenue", h2(2025)) == pytest.approx(9457457.05, abs=0.005)
    assert evaluate(M, "Net Revenue", h2(2024)) == pytest.approx(10188727.55, abs=0.005)
    assert evaluate(M, "Net Revenue PY", h2(2025)) == pytest.approx(10188727.55, abs=0.005)
    assert evaluate(M, "Net Revenue YoY", h2(2025)) == pytest.approx(-731270.50, abs=0.005)
    assert round(100 * evaluate(M, "Net Revenue YoY %", h2(2025)), 6) == -7.177251


@needs_curated
def test_driver_attribution_totals_exactly(phase7):
    at = phase7["extracts"]["p6_driver_attribution"]
    assert abs(at["amount_eur"].sum() + 731270.50) < 0.01
    assert [round(v) for v in at["amount_eur"]] == [-397778, -37235, -31589, -186146, -78522]
    assert [round(100 * v) for v in at["share_of_change"]] == [54, 5, 4, 25, 11]


@needs_curated
def test_py_shift_aligns_retail_weeks(phase7):
    """Every H2 2025 day maps to the same retail week and weekday of H2 2024 (364 days), so PY is week-aligned."""
    d = phase7["tables"]["Date"].set_index("date_key")
    cy = d[(d["retail_year"] == 2025) & (d["retail_half"] == "H2")]
    py = d.loc[cy["same_day_last_year_key"].astype(int)]
    assert (py["retail_year"] == 2024).all() and (py["retail_half"] == "H2").all()
    assert (py["retail_week"].to_numpy() == cy["retail_week"].to_numpy()).all()
    assert (py["day_of_week"].to_numpy() == cy["day_of_week"].to_numpy()).all()


# ============================================================================= register: every number traced
@needs_curated
def test_every_register_number_rederives_from_its_source(phase7):
    reg = pd.read_csv(REPORTS / "dashboard_number_register.csv")
    fresh = phase7["register"].set_index("id")
    assert len(reg) >= 140 and reg["id"].is_unique
    assert set(reg["source_type"]) <= {"DAX", "P5", "P6"}
    for r in reg.itertuples():
        f = fresh.loc[r.id]
        if isinstance(r.value, str) or isinstance(f["value"], str):
            assert str(r.value) == str(f["value"]) or pd.Timestamp(r.value) == pd.Timestamp(f["value"]), r.id
        else:
            assert (pd.isna(r.value) and pd.isna(f["value"])) or abs(float(r.value) - float(f["value"])) < 1e-6, r.id
        if r.source_type in ("P5", "P6"):
            src = pd.read_csv(ROOT / r.source)
            col = re.search(r"column (\w+)", r.context).group(1)
            assert col in src.columns, (r.id, col)
            if "derived:" not in r.context and not isinstance(r.value, str) and pd.notna(r.value):
                assert (src[col] - float(r.value)).abs().min() < 1e-6, r.id
        else:
            assert r.source.startswith("[") and r.source.strip("[]") in MEASURE_NAMES, r.id


@needs_curated
def test_register_matches_brief_highlights(phase7):
    reg = phase7["register"].set_index("id")["display"]
    expect = {"P1-01": "€9.457M", "P1-02": "€10.189M", "P1-03": "-€731k", "P1-04": "-7.18%", "P2-T0": "-27.8%",
              "P2-T1": "-1.1%", "P2-E1": "-€397,778", "P2-E5": "15 Jul 2025", "P2-OS03": "16 Jul", "P2-OS04": "09 Jul",
              "P2-OS05": "21 Jul", "P3-02": "-€268,518", "P3-03": "-11.8%", "P3-07": "95.4%", "P3-08": "89.3%",
              "P3-E2024": "609", "P3-E2025": "1,181", "P3-M2024": "1.1", "P3-M2025": "2.1", "P3-F1": "674",
              "P3-F0": "0", "P3-L1": "€37,235", "P3-L2": "€23,963", "P3-L3": "€23,963", "P3-L4": "€44,460",
              "P3-C1": "61%", "P3-C2": "25%", "P3-C3": "50%", "P4-01": "+€31,589", "P4-02": "+90%", "P5-09": "2.4%",
              "P5-10": "11.9%", "P5-E2024": "2,427", "P5-E2025": "8,848", "P5-M1": "-€186,146", "P5-M4": "-€265,003",
              "P5-M2": "+€97,505", "P5-M3": "+€79,059"}
    for k, v in expect.items():
        assert reg[k] == v, (k, reg[k], v)


# ============================================================================= evidence discipline
@needs_curated
def test_evidence_levels_identical_to_phase6(phase7):
    em = phase7["extracts"]["p6_evidence_matrix"].set_index("driver_id")
    src = pd.read_csv(ROOT / "reports/phase6/root_cause_evidence_matrix.csv").set_index("driver_id")
    assert (em["evidence_level"] == src["evidence_level"]).all()
    assert em.loc["D03", "evidence_level"] == "Root-cause evidence" and em.loc["D03", "cause_status"] == "Established"
    assert em.loc["D01", "cause_status"] == "Unresolved" and "UNRESOLVED" in em.loc["D01", "evidence_display"]
    assert em.loc["D04", "evidence_level"] == "Statistical association" and "NOT proven" in em.loc["D04", "evidence_display"]
    assert "HYPOTHESIS" in em.loc["D05", "evidence_display"]
    assert em.loc["D07", "evidence_level"] == "Statistical association"
    for d in em.index:
        if em.loc[d, "evidence_level"] != "Root-cause evidence":
            assert em.loc[d, "cause_status"] != "Established", d
    assert set(em.index) >= {f"D0{i}" for i in range(1, 9)}


def test_required_wording_is_in_the_measure_layer():
    from src.powerbi.dax import BY_NAME
    assert "Cause not established from available internal data." in BY_NAME["Cluster Cause Callout"].expr
    assert ("Stock-out concentration is associated with Voltix SKUs. Available data cannot determine whether the cause "
            "was supplier performance or Brightwater ordering/replenishment.") in BY_NAME["Voltix Wording"].expr
    assert ("Promotion activity is associated with the Home & Kitchen decline, but causality is not established."
            in BY_NAME["Promotion Wording"].expr)


def test_promotion_methods_are_never_combined():
    from src.powerbi.dax import BY_NAME
    assert "HASONEVALUE ( p6_hk_methods[method_code] )" in BY_NAME["HK Method Effect Guarded"].expr
    methods = pd.read_csv(PBI / "data" / "p6_hk_methods.csv")
    assert list(methods["method_code"]) == ["M1", "M4", "M2", "M3"]
    assert (methods["effect_eur"] < 0).sum() == 2 and (methods["effect_eur"] > 0).sum() == 2


def test_no_causal_overclaims_in_dashboard_text():
    texts = [(PBI / "dax" / "measures.dax").read_text(encoding="utf-8"),
             (ROOT / "src" / "powerbi" / "mockups.py").read_text(encoding="utf-8"),
             pd.read_csv(PBI / "data" / "p6_investigations.csv").to_string(),
             (ROOT / "docs" / "07_power_bi_dashboard_design.md").read_text(encoding="utf-8")]
    joined = " ".join(texts).lower()
    for phrase in ("voltix caused", "caused by the promotion", "promotions caused the decline.", "defective products caused",
                   "competitor caused", "proves", "root cause is the competitor", "cause lies outside",
                   "is a sudden loss of customers"):
        assert phrase not in joined, phrase


# ============================================================================= DAX layer
def test_dax_measure_layer_covers_the_brief():
    from src.powerbi.dax import BY_NAME
    for m in ("Sales Revenue", "Returns Value", "Net Revenue", "Net Revenue PY", "Net Revenue YoY", "Net Revenue YoY %",
              "Gross Margin", "Gross Margin %", "Transactions", "Transactions PY", "Transactions YoY %", "Units", "UPT",
              "ASP", "Average Transaction Value", "Return Rate", "Availability", "Promotion Revenue", "Promotion Share",
              "Discount Rate", "Target Achievement %"):
        assert m in BY_NAME, m
        assert BY_NAME[m].description.strip()


@needs_curated
def test_dax_static_checks(phase7):
    from src.powerbi.dax import static_checks
    sc = pd.DataFrame(static_checks({k: list(v.columns) for k, v in {**phase7["tables"], **{
        k: v for k, v in phase7["extracts"].items() if not k.startswith("_")}}.items()}))
    assert (sc["status"] == "PASS").all(), sc[sc["status"] != "PASS"].to_string()


def test_ratios_are_divides_of_sums_not_averages():
    from src.powerbi.dax import MEASURES
    for m in MEASURES:
        if m.folder.startswith(("1", "2", "3", "4", "5", "6", "7")):
            assert not re.search(r"\bAVERAGEX?\s*\(", m.expr.upper()), m.name
            if m.fmt and "%" in m.fmt and "YoY" not in m.name and "pp" not in m.name and "PY" not in m.name:
                assert "DIVIDE" in m.expr, m.name


def test_py_measures_use_week_aligned_shift_not_calendar_functions():
    from src.powerbi.dax import MEASURES
    text = " ".join(m.expr.upper() for m in MEASURES)
    for fn in ("SAMEPERIODLASTYEAR", "DATEADD", "PARALLELPERIOD"):
        assert fn not in text
    for m in MEASURES:
        if m.name.endswith(" PY"):
            assert "same_day_last_year_key" in m.expr and "REMOVEFILTERS ( 'Date' )" in m.expr, m.name


def test_tmdl_script_structure():
    t = (PBI / "dax" / "measures_tmdl.tmdl").read_text(encoding="utf-8")
    from src.powerbi.dax import MEASURES
    assert t.startswith("createOrReplace\n\n\ttable Measures")
    for m in MEASURES:
        assert f"\t\tmeasure '{m.name}' =" in t, m.name
    assert "\t\tpartition Measures = calculated" in t
    for ln in t.splitlines():
        if ln.strip().startswith(("formatString:", "displayFolder:")):
            assert ln.startswith("\t\t\t") and not ln.startswith("\t\t\t\t"), ln


@needs_curated
def test_dax_validation_queries_match_the_reconciled_reference(phase7):
    q = (PBI / "dax" / "validation_queries.dax").read_text(encoding="utf-8")
    fresh = (phase7["assets"] / "powerbi" / "dax" / "validation_queries.dax").read_text(encoding="utf-8")
    assert q == fresh
    assert len(phase7["cases"]) >= 40 and "EVALUATE" in q and "[QA Attribution Check]" in q
    assert q.count('"PASS"') == 1 and q.count("( \"") == len(phase7["cases"]) + 1
    first = next(c for c in phase7["cases"] if c["label"] == "Net Revenue (H2 2025)")
    assert abs(first["expected"] - 9457457.05) < 0.005


# ============================================================================= Power Query, SQL, model
def test_power_query_files_for_every_table():
    pq = PBI / "power_query"
    for t in ("Date", "Store", "Product", "Promotion", "Sales", "Returns", "Inventory", "Targets"):
        s = (pq / f"{t}.sql_server.pq").read_text(encoding="utf-8")
        c = (pq / f"{t}.csv.pq").read_text(encoding="utf-8")
        assert "Sql.Database(ServerName, DatabaseName)" in s and 'Schema = "pbi"' in s
        assert 'File.Contents(ModelFolder & "\\' in c
    # no query both reads a source and references another query (Formula.Firewall); store_group is a DAX column
    for f in pq.glob("*.pq"):
        assert "NestedJoin" not in f.read_text(encoding="utf-8"), f.name
    from src.powerbi.dax import CALC_COLUMNS
    assert [(t, c) for t, c, _, _ in CALC_COLUMNS] == [("Store", "store_group")]
    assert "LOOKUPVALUE ( p6_store_groups[store_group]" in CALC_COLUMNS[0][2]
    # boolean CSV columns load as logical, so the measures on them work
    assert '{"high_seller", type logical}' in (pq / "p6_et_sku_stockouts.pq").read_text(encoding="utf-8")
    assert "Currency.Type" in (pq / "Sales.sql_server.pq").read_text(encoding="utf-8")
    man = pd.read_csv(PBI / "data" / "extract_manifest.csv")
    for e in man["extract"]:
        assert (pq / e.replace(".csv", ".pq")).exists(), e


def test_model_definition_is_a_single_direction_star():
    import json
    md = json.loads((PBI / "model_definition.json").read_text(encoding="utf-8"))
    rel = md["relationships"]
    assert len(rel) == 12 and all(r["cross_filter"] == "single" and r["cardinality"] == "many-to-one" for r in rel)
    inactive = [r for r in rel if not r["active"]]
    assert inactive == [{"from": "Returns[original_sale_date_key]", "to": "Date[date_key]", "cardinality": "many-to-one",
                         "cross_filter": "single", "active": False}]
    assert not any(r["to"].startswith(("p6_", "p5_")) or r["from"].startswith(("p6_", "p5_")) for r in rel)


def test_pbi_sql_is_valid_tsql_and_reads_only_the_star_schema():
    import sqlglot
    from src.sql_model.scripts import split_batches, strip_comments
    assert [p.name for p in SQL] == ["01_powerbi_views.sql"]
    pattern = re.compile(r"\b(read_csv\w*|read_parquet|read_json\w*|read_text|read_blob|sniff_csv|glob\s*\(|OPENROWSET|"
                         r"OPENDATASOURCE|BULK\s+INSERT|xp_cmdshell|COPY\s+\w+\s+FROM)", re.I)
    body = strip_comments(SQL[0].read_text(encoding="utf-8"))
    assert not pattern.search(body)
    for schema in re.findall(r"\b(FROM|JOIN)\s+(\w+)\.", body):
        assert schema[1] == "dw", schema
    views = []
    for b in split_batches(SQL[0]):
        if b.target == "tsql":
            continue
        txt = strip_comments(b.text)
        assert sqlglot.parse(txt, read="tsql")
        views += re.findall(r"CREATE OR ALTER VIEW (pbi\.\w+)", txt)
    assert sorted(views) == sorted(["pbi.dim_date", "pbi.dim_store", "pbi.dim_product", "pbi.dim_promotion",
                                    "pbi.fact_sales", "pbi.fact_returns", "pbi.fact_inventory", "pbi.fact_targets"])


@needs_curated
def test_transaction_key_preserves_the_receipt_count(phase7):
    s = phase7["tables"]["Sales"]
    assert s["transaction_key"].nunique() == pd.read_csv(CURATED / "fact_sales.csv", usecols=["transaction_id"])[
        "transaction_id"].nunique()


# ============================================================================= independence
def test_phase7_code_never_names_an_evaluation_asset():
    offenders = [f"{f.relative_to(ROOT)}: {a}" for f in CODE + SQL + CONFIG
                 for a in EVALUATION_ASSETS if a in f.read_text(encoding="utf-8")]
    assert not offenders, offenders


def test_phase7_code_does_not_import_generator_evaluation_or_dq_code():
    for f in CODE:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for m in mods:
                assert not any(x in m for x in ("data_generation", "evaluation", "data_quality", "answer")), (f.name, m)


def test_input_guard_refuses_evaluation_and_raw_assets():
    from src.powerbi.access import InputError, allowed_path
    cfg = _cfg()
    for bad in ("data/raw/_planted_issues_log.csv", "data/raw/_scenario_answer_key.csv", "config/_hidden_scenario.yaml",
                "reports/evaluation/phase3_detection_scorecard.csv", "reports/phase2_calibration_report.json",
                "evaluation/evaluate_phase3_detection.py", "data/raw/fact_sales.csv", "data/sample/fact_sales.csv",
                "reports/phase6/phase6_run_log.txt"):
        with pytest.raises(InputError):
            allowed_path(bad, cfg)


@needs_curated
def test_run_never_opens_an_evaluation_asset(phase7):
    traced = [p.replace("\\", "/") for p in phase7["traced"]]
    audited = phase7["opened"]
    bad = [p for p in traced + audited["project_files"] if any(a in p for a in EVALUATION_ASSETS) or
           any(part.startswith("_") and not part.startswith("__") for part in Path(p).parts)]
    assert not bad, bad
    assert not audited["refused"]
    assert not any(p.startswith(("data/raw", "data/sample", "data/processed/quarantine")) for p in audited["project_files"])


def test_phase2_scenario_separation_guard_still_clean():
    from src.data_generation.validate_generated import EVALUATION_ONLY_ASSETS
    for f in CODE + SQL + CONFIG + [ROOT / "docs" / "07_power_bi_dashboard_design.md"]:
        txt = f.read_text(encoding="utf-8")
        assert not any(a in txt for a in EVALUATION_ONLY_ASSETS), f.name


# ============================================================================= determinism and outputs
@needs_curated
def test_assets_and_reports_are_reproducible(phase7):
    fresh = phase7["assets"]
    for rel in sorted([p.relative_to(ROOT) for p in (PBI / "data").glob("*.csv")] +
                      [p.relative_to(ROOT) for p in (PBI / "dax").glob("*")] +
                      [p.relative_to(ROOT) for p in (PBI / "power_query").glob("*.pq")] +
                      [Path("powerbi/brightwater_theme.json"), Path("powerbi/model_definition.json")]):
        assert (ROOT / rel).read_bytes() == (fresh / rel).read_bytes(), rel
    out = Path(phase7["out"])
    for name in ("phase7_validation_checks.csv", "measure_dictionary.csv", "data_dictionary.csv",
                 "dashboard_number_register.csv", "model_profile.csv", "dax_validation_cases.csv"):
        a, b = pd.read_csv(REPORTS / name), pd.read_csv(out / name)
        pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9, atol=1e-6, obj=name)


def test_mockups_and_docs_exist():
    names = sorted(p.name for p in (REPORTS / "mockups").glob("*.png"))
    assert names == ["page1_executive_overview.png", "page2_store_customer.png", "page3_product_inventory.png",
                     "page4_returns_quality.png", "page5_promotions.png", "page6_evidence_matrix.png",
                     "page7_investigation.png"]
    doc = (ROOT / "docs" / "07_power_bi_dashboard_design.md").read_text(encoding="utf-8")
    for h in ("Purpose and users", "Page architecture", "Data model", "DAX measure layer", "Filter behaviour",
              "Drill-through", "Tooltip logic", "Evidence framework", "Design decisions", "Performance considerations",
              "Limitations", "Manual build steps", "Tests to run in Power BI Desktop", "Interview readiness",
              "Real-world architecture"):
        assert h in doc, h
    rep = (REPORTS / "phase7_validation_report.md").read_text(encoding="utf-8")
    assert "not executed" in rep.lower() or "not run" in rep.lower()


def test_no_em_dash_in_phase7_files():
    em_dash = chr(0x2014)
    files = CODE + SQL + CONFIG + [ROOT / "docs" / "07_power_bi_dashboard_design.md", ROOT / "README.md", Path(__file__)] + \
        sorted(REPORTS.glob("*.md")) + sorted(REPORTS.glob("*.csv")) + sorted((PBI / "dax").glob("*")) + \
        sorted((PBI / "power_query").glob("*.pq")) + sorted((PBI / "data").glob("*.csv"))
    # is_file() guards the glob results: powerbi/dax also contains the tmdl_install_temp directory,
    # and read_text() on a directory raises PermissionError. The em-dash assertion itself is unchanged.
    offenders = [str(f.relative_to(ROOT)) for f in files
                 if f.exists() and f.is_file() and em_dash in f.read_text(encoding="utf-8")]
    assert not offenders, offenders


# ============================================================================= Currency type propagation
# Power BI returns 21.4905 / 45.5537 for ASP / ATV, not the full-precision 21.490465238165949 / 45.553694121568132.
# VertiPaq stores Currency as a fixed-point decimal with scale 4, and DAX propagates the type through
# division: Money/Money and Whole Number/Whole Number promote to double, Money/Whole Number stays Currency
# and is quantised to 4 decimal places. These tests pin both halves of that contract.
def test_currency_quantisation_is_four_decimal_places():
    from src.powerbi.assets import currency
    assert currency(21.490465238165949) == 21.4905
    assert currency(45.553694121568132) == 45.5537
    assert currency(9840827.879999999 / 457916) == 21.4905
    assert currency(9840827.879999999 / 216027) == 45.5537
    # values already at 4 dp are untouched, and non-finite values pass through
    assert currency(1.2345) == 1.2345
    assert currency(0.0) == 0.0
    assert math.isnan(currency(float("nan")))


def test_only_money_over_count_measures_are_currency_quantised():
    """ASP and ATV are the only measures that divide a Currency measure by a count measure. Every other
    ratio measure is money/money or whole-number/whole-number and must keep full float64 precision."""
    from src.powerbi.assets import CURRENCY_RATIO_MEASURES
    from src.powerbi.dax import MEASURES
    assert CURRENCY_RATIO_MEASURES == {"ASP", "Average Transaction Value"}
    money = {"Sales Revenue", "Net Revenue", "Gross Margin", "Returns Value"}
    counts = {"Units", "Transactions"}
    for m in MEASURES:
        expr = " ".join(m.expr.split())
        if not expr.startswith("DIVIDE"):
            continue
        args = [a.strip().strip("() ").strip("[] ") for a in expr[len("DIVIDE"):].strip("() ").split(",")]
        num, den = args[0], args[1]
        is_money_over_count = num in money and den in counts
        assert (m.name in CURRENCY_RATIO_MEASURES) == is_money_over_count, m.name


@needs_curated
def test_asp_and_atv_expected_values_match_power_bi_desktop(phase7):
    """The two values Power BI Desktop actually returned when the 92 measures were installed."""
    got = {c["label"]: c["expected"] for c in phase7["cases"]}
    assert got["ASP (H2 2025)"] == 21.4905
    assert got["Average Transaction Value (H2 2025)"] == 45.5537


@needs_curated
def test_business_ratio_formulas_stay_full_precision(phase7):
    """Quantisation is a Power BI rendering effect, so the reconciled reference must still match the
    full-precision Phase 5 SQL results at tolerance 1e-6 (ASP, ATV and every other ratio check)."""
    c = phase7["checks"]
    ratio = c[c["check"].str.contains("ASP|Average Transaction Value|Return Rate|Promotion Share|"
                                      "Discount Rate|Gross Margin %|UPT", regex=True)]
    assert len(ratio) >= 8, ratio["check"].tolist()
    assert (ratio["status"] == "PASS").all(), ratio[ratio["status"] != "PASS"].to_string()


def test_validation_queries_pin_the_currency_values_not_the_float_ones():
    q = (PBI / "dax" / "validation_queries.dax").read_text(encoding="utf-8")
    assert '[ASP], \'Date\'[retail_year] = 2025, \'Date\'[retail_half] = "H2" ), 21.4905, 1e-09' in q
    assert '[Average Transaction Value], \'Date\'[retail_year] = 2025, \'Date\'[retail_half] = "H2" ), 45.5537, 1e-09' in q
    # the full-precision values must be gone, otherwise Power BI would still report a mismatch
    assert "21.49046523816595" not in q
    assert "45.553694121568135" not in q
    # the expected value moved but the tolerance did not: both lines still assert 1e-09
    for line in q.splitlines():
        if '"ASP (H2 2025)"' in line or '"Average Transaction Value (H2 2025)"' in line:
            assert line.rstrip().endswith("1e-09 ),"), line
