"""Calibration tests: the estate-level H2 headline must match the signed-off BRD.

These tests read the calibration report and the answer key. That is allowed
here because they validate the GENERATOR (evaluation-only). Phase 3+ analysis
code must never read these assets.
"""
import json

import pytest

from src.data_generation.config_loader import CONFIG_DIR, PROJECT_ROOT

REPORT = PROJECT_ROOT / "reports" / "phase2_calibration_report.json"


@pytest.fixture(scope="module")
def report():
    """Calibration report; skipped until the calibration dry run has been run."""
    if not REPORT.exists():
        pytest.skip("Run: python -m src.data_generation.calibrate_scenario")
    return json.loads(REPORT.read_text())


def test_reported_decline_in_brd_band(report):
    assert -8.5 <= report["yoy_pct_reported"] <= -7.5


def test_apparent_and_underlying_are_distinct(report):
    # the data-completeness artefact makes the reported decline worse than the true one
    assert report["yoy_pct_reported"] < report["yoy_pct_underlying"] < 0
    assert report["dq_artefact_pp"] < 0
    assert report["yoy_pct_reported"] == pytest.approx(report["yoy_pct_underlying"] + report["dq_artefact_pp"], abs=0.011)


def test_artefact_eur_matches_batches(report):
    # artefact = late batch missing from H2 2025, partly offset by the missing batch shrinking the H2 2024 base
    assert report["late_batch_revenue_h2_2025"] > 0 and report["missing_batch_revenue_h2_2024"] > 0
    assert report["dq_artefact_eur"] == pytest.approx(
        -report["late_batch_revenue_h2_2025"] + report["missing_batch_revenue_h2_2024"], abs=0.02)


def test_underlying_decline_is_mostly_business_drivers(report):
    named = sum(v["pp"] for k, v in report["drivers"].items() if not k.startswith("Natural"))
    assert named < report["yoy_pct_underlying"]          # drivers explain more than the net decline
    assert report["drivers_sum_pp"] == pytest.approx(report["yoy_pct_underlying"], abs=0.05)


def test_projected_volume(report):
    assert 1_200_000 <= report["projected_full_row_counts"]["fact_sales.csv"] <= 1_500_000


@pytest.mark.slow
@pytest.mark.skipif(not (CONFIG_DIR / "_hidden_scenario.yaml").exists(),
                    reason="needs the private scenario file config/_hidden_scenario.yaml, kept out of the repository by design so the blind evaluation stays blind (KI-09)")
def test_dry_run_reproduces_report(report):
    """The full pipeline is deterministic: a fresh dry run must give identical headline figures."""
    from src.data_generation.generate_data import run

    ak = run("full", write_files=False)["answer_key"].set_index("behaviour")["impact_pp_of_h2_2024_net_revenue"]
    assert ak["H2 2025 net revenue (reported)"] == report["yoy_pct_reported"]
    assert ak["H2 2025 net revenue (underlying)"] == report["yoy_pct_underlying"]
