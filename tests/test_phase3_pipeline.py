"""Phase 3 pipeline tests: end-to-end on the sample, isolation from evaluation assets, and regression
protection on the full curated outputs."""
import ast
import builtins
import json
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from src.data_quality.catalogue import CATALOGUE
from src.data_quality.core import sha256

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
PHASE3_CODE = ROOT / "src" / "data_quality"
FULL_REPORTS = ROOT / "reports" / "phase3"
GOLDEN = ROOT / "tests" / "golden" / "phase3_rule_counts.json"
EVALUATION_ASSETS = ("_hidden_scenario", "_scenario_answer_key", "_planted_issues_log", "_generation_manifest",
                     "phase2_calibration_report", "phase2_full_validation", "reconcile_headline",
                     "phase3_detection_scorecard", "evaluate_phase3")


# ------------------------------------------------------------------ isolation (static)
def test_phase3_code_never_names_an_evaluation_asset():
    offenders = []
    for f in list(PHASE3_CODE.glob("*.py")) + [ROOT / "config" / "dq_config.yaml"]:
        txt = f.read_text()
        offenders += [f"{f.name}: {a}" for a in EVALUATION_ASSETS if a in txt]
    assert not offenders, offenders


def test_phase3_code_does_not_import_generator_or_evaluation():
    for f in PHASE3_CODE.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for m in mods:
                assert "data_generation" not in m and "evaluation" not in m, f"{f.name} imports {m}"


# ------------------------------------------------------------------ end-to-end on the sample
@pytest.fixture(scope="session")
def sample_run(tmp_path_factory):
    """One pipeline run on the sample; returns the result, files opened and raw hashes before and after."""
    if not (SAMPLE / "fact_sales.csv").exists():
        pytest.skip("sample not generated")
    from src.data_quality import run_dq

    out = tmp_path_factory.mktemp("dq_sample")
    opened = []
    real_open = builtins.open

    def tracing_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    before = {f.name: sha256(f) for f in SAMPLE.glob("*.csv")}
    with mock.patch("builtins.open", tracing_open):
        res = run_dq.run(SAMPLE, out)
    after = {f.name: sha256(f) for f in SAMPLE.glob("*.csv")}
    return res, out, opened, before, after


def test_pipeline_never_opens_an_evaluation_asset(sample_run):
    _, _, opened, _, _ = sample_run
    names = [Path(p).name for p in opened]
    bad = [n for n in names if (n.startswith("_") and not n.startswith("__")) or any(a in n for a in EVALUATION_ASSETS)]
    assert not bad, bad
    assert any(n == "fact_sales.csv" for n in names)          # the tracer really saw the reads


def test_raw_files_unchanged(sample_run):
    res, _, _, before, after = sample_run
    assert before == after and res["summary"]["raw_unchanged"]


def test_curated_validation_has_no_failures(sample_run):
    v = sample_run[0]["validation"]
    assert not (v["status"] == "FAIL").any(), v[v["status"] == "FAIL"].to_string()


def test_every_raw_row_is_curated_or_quarantined(sample_run):
    v = sample_run[0]["validation"]
    rc = v[v["group"] == "row conservation"]
    assert len(rc) == 8 and (rc["status"] == "PASS").all()


def test_outputs_written_and_quarantine_is_explained(sample_run):
    res, out, _, _, _ = sample_run
    for t in ("dim_store", "dim_product", "dim_date", "fact_sales", "fact_inventory", "fact_returns", "fact_promotions",
              "fact_targets"):
        assert (out / "curated" / f"{t}.csv").exists()
    for f in (out / "quarantine").glob("*.csv"):
        q = pd.read_csv(f, dtype=str)
        assert q["dq_rule_id"].notna().all() and q["dq_reason"].notna().all()
        for rid in q["dq_rule_id"].unique():
            assert all(r in CATALOGUE for r in rid.split("/"))


def test_issue_log_and_audit_trail_are_complete(sample_run):
    res = sample_run[0]
    issues, audit, results = res["issues"], res["audit"], res["results"]
    assert set(issues["rule_id"]) <= set(CATALOGUE)
    assert set(results["rule_id"]) == set(CATALOGUE)
    assert (audit["rows_affected"] >= 0).all()
    # every rule that changed data appears in the audit trail
    changed = set(results.loc[(results["rows_failed"] > 0) & results["treatment"].isin(
        ["CORRECT", "DEDUPLICATE", "STANDARDISE", "IMPUTE", "QUARANTINE"]), "rule_id"])
    audited = {r for x in audit["rule_id"] for r in x.split("/")}
    assert changed <= audited, changed - audited


def test_kpi_reconciliation_identities(sample_run):
    k = sample_run[0]["kpis"]
    for view in ("raw_as_reported", "clean_main_only", "clean_complete"):
        c = k[view]
        assert abs(c["net_revenue"] - (c["sales_revenue"] - c["returns_value"])) < 0.01
        assert abs(c["aov"] - c["upt"] * c["asp"]) < 1e-9
    # the late file only adds revenue; cleaning the main extract never adds sales lines
    assert k.loc["sales_revenue", "clean_complete"] > k.loc["sales_revenue", "clean_main_only"]
    assert k.loc["sales_lines", "clean_main_only"] <= k.loc["sales_lines", "raw_as_reported"]


def test_curated_sales_trustworthy(sample_run):
    s = sample_run[0]["curated"]["fact_sales"]
    assert not s.duplicated(["transaction_id", "line_number"]).any()
    assert (s["quantity"] > 0).all() and (s["unit_price"] > 0).all()
    assert ((s["quantity"] * s["unit_price"] - s["discount"]).round(2) - s["revenue"]).abs().max() <= 0.011


def test_pos_to_stock_reconciliation_improves(sample_run):
    before, after = sample_run[0]["recon"]
    assert after["match_rate"] > before["match_rate"]
    assert after["explained"].get("unexplained", 0) <= 0.01 * after["mismatched"] + 5


# ------------------------------------------------------------------ regression protection on the full run
full = pytest.mark.skipif(not (FULL_REPORTS / "dq_rule_results.csv").exists(), reason="full DQ run not present")


@full
def test_full_run_rule_counts_match_golden():
    """Any change in what the rules detect must be deliberate: update tests/golden when it is."""
    if not GOLDEN.exists():
        pytest.skip("golden file not created")
    gold = json.loads(GOLDEN.read_text())
    cur = pd.read_csv(FULL_REPORTS / "dq_rule_results.csv").set_index("rule_id")["rows_failed"].to_dict()
    diffs = {k: (gold.get(k), cur.get(k)) for k in set(gold) | set(cur) if gold.get(k) != cur.get(k)}
    assert not diffs, diffs


@full
def test_full_run_validation_and_lineage():
    v = pd.read_csv(FULL_REPORTS / "curated_validation.csv")
    assert not (v["status"] == "FAIL").any()
    lin = json.loads((FULL_REPORTS / "lineage.json").read_text())
    assert lin["raw_unchanged"]
    for t, meta in lin["inputs"].items():            # raw files are still the ones the run read
        assert sha256(ROOT / "data" / "raw" / meta["file"]) == meta["sha256"], t
    for t, meta in lin["outputs"].items():           # curated files are the ones the run wrote
        assert sha256(ROOT / meta["path"]) == meta["sha256"], t
