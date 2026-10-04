"""Tests on the persisted FULL dataset (data/raw). Skipped if it has not been generated.

Evaluation-only: reads the answer key, planted log and calibration report to
confirm the written files reproduce the approved calibration.
"""
import json

import pytest

from src.data_generation.config_loader import PROJECT_ROOT

RAW = PROJECT_ROOT / "data" / "raw"
CALIB = PROJECT_ROOT / "reports" / "phase2_calibration_report.json"

pytestmark = pytest.mark.skipif(not (RAW / "fact_sales.csv").exists(), reason="full dataset not generated")

PLANTED_LOG = RAW / "_planted_issues_log.csv"
requires_planted_log = pytest.mark.skipif(
    not PLANTED_LOG.exists(),
    reason="evaluation-only planted-issues log is not present in this checkout",
)


@pytest.fixture(scope="module")
def full_results():
    """Validation results on data/raw; skipped when the issue log is absent."""
    if not PLANTED_LOG.exists():
        pytest.skip("evaluation-only planted-issues log is not present in this checkout")
    from src.data_generation.validate_generated import run_all
    return run_all(RAW)


@pytest.fixture(scope="module")
def calib():
    """Approved calibration report."""
    return json.loads(CALIB.read_text())


def test_full_validation_suite_passes(full_results):
    res, _ = full_results
    failed = res[res["status"] == "FAIL"]
    assert failed.empty, "\n" + failed.to_string(index=False)


def test_row_counts_match_calibration_projection(calib):
    manifest = json.loads((RAW / "_generation_manifest.json").read_text())
    assert manifest["row_counts"] == calib["projected_full_row_counts"]


def test_persisted_answer_key_matches_calibration(calib):
    import pandas as pd
    ak = pd.read_csv(RAW / "_scenario_answer_key.csv").set_index("behaviour")
    pp = ak["impact_pp_of_h2_2024_net_revenue"]
    assert pp["H2 2025 net revenue (reported)"] == calib["yoy_pct_reported"]
    assert pp["H2 2025 net revenue (underlying)"] == calib["yoy_pct_underlying"]
    assert ak.loc["Data-completeness artefact (reported minus underlying YoY)", "impact_eur"] == calib["dq_artefact_eur"]


@requires_planted_log
def test_headline_recalculated_from_files(calib):
    from src.data_generation.reconcile_headline import reconcile
    rec = reconcile(RAW)
    assert rec["restored_yoy_pct"] == {"reported": calib["yoy_pct_reported"], "underlying": calib["yoy_pct_underlying"]}
    # only planted rows whose discount was overwritten can differ, and only upward
    assert all(0 <= d < 250 for d in rec["difference_eur"].values())
    assert rec["late_batch_h2_2025_from_file"] == calib["late_batch_revenue_h2_2025"]


def test_late_batch_kept_separate():
    import pandas as pd
    late = pd.read_csv(RAW / "fact_sales_late_batch.csv")
    main_ids = set(pd.read_csv(RAW / "fact_sales.csv", usecols=["transaction_id"])["transaction_id"])
    assert len(late) > 0 and not set(late["transaction_id"]) & main_ids
