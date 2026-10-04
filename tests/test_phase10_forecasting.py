"""Phase 10 forecasting tests: input contract, baselines, leakage-safe back-testing, selection,
intervals, scenarios, governance gates and the committed outputs in reports/phase10."""
import csv
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.forecasting import run_phase10
from src.forecasting.baselines import moving_average, naive, seasonal_naive, trend
from src.forecasting.backtest import rolling_origins, run_pointwise_backtest, run_rolling_backtest
from src.forecasting.checks import build_catalogue, catalogue_passed, catalogue_summary
from src.forecasting.config import load_config, validate_config
from src.forecasting.contracts import (APPROVED_HEADLINE, DataContractError, reconcile_h2_headline,
                                      validate_weekly_rows)
from src.forecasting.features import build_past_only_features, validate_future_features
from src.forecasting.forecast import build_forecast, build_intervals, calibration_errors, project_week_labels
from src.forecasting.intervals import empirical_interval
from src.forecasting.metrics import forecast_metrics
from src.forecasting.models import HoltLinearForecaster, model_registry
from src.forecasting.scenarios import Scenario, apply_scenario
from src.forecasting.selection import ModelSummary, select_model, summarise
from src.forecasting.validation import preflight, sha256_file, verify_manifest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "phase10"
WEEKLY_INPUT = REPORTS / "weekly_estate_history.csv"
CONFIG = load_config(ROOT / "config" / "forecasting_config.yaml")
FORECAST_CFG = CONFIG["forecast"]


def estate_rows(count=8):
    """Contract-valid weekly estate rows from Monday 2024-01-01, for synthetic contract tests."""
    rows = []
    start = date(2024, 1, 1)
    for index in range(count):
        year = 2024 + index // 52
        week = index % 52 + 1
        rows.append(
            {
                "retail_year": str(year),
                "retail_week": str(week),
                "week_start_date": (start + timedelta(weeks=index)).isoformat(),
                "net_revenue": str(100 + index),
            }
        )
    return rows


def test_config_loads_and_registry_is_explicit():
    config = load_config(ROOT / "config" / "forecasting_config.yaml")
    validate_config(config)
    names = [model.name for model in model_registry()]
    assert names == ["B1_naive", "B2_seasonal_naive", "B3_moving_average", "B4_trend", "holt_linear"]


def test_contract_rejects_missing_required_columns():
    with pytest.raises(DataContractError, match="Missing required columns"):
        validate_weekly_rows([{"net_revenue": "10"}])


def test_contract_accepts_ordered_weekly_series():
    assert len(validate_weekly_rows(estate_rows())) == 8


def test_contract_rejects_duplicate_week():
    rows = estate_rows()
    rows[1] = dict(rows[0])
    with pytest.raises(DataContractError, match="Duplicate week/entity"):
        validate_weekly_rows(rows)


def test_contract_rejects_missing_week():
    rows = estate_rows()
    rows.pop(3)
    with pytest.raises(DataContractError, match="Missing or irregular"):
        validate_weekly_rows(rows)


def test_contract_supports_store_panels_within_each_week():
    rows = []
    for week_row in estate_rows(3):
        for store in ("S01", "S02"):
            rows.append({**week_row, "store_id": store})
    assert len(validate_weekly_rows(rows, grain="store")) == 6


def test_contract_rejects_out_of_order_weeks():
    rows = []
    for week_row in estate_rows(2):
        for store in ("S01", "S02"):
            rows.append({**week_row, "store_id": store})
    rows[0], rows[1] = rows[1], rows[0]
    with pytest.raises(DataContractError, match="sorted"):
        validate_weekly_rows(rows, grain="store")


def test_naive_baseline_repeats_last_observation():
    assert naive([2, 4, 7], 3) == [7.0, 7.0, 7.0]


def test_seasonal_naive_repeats_approved_week_lag():
    assert seasonal_naive(list(range(1, 9)), 3, season=4) == [5.0, 6.0, 7.0]


def test_seasonal_naive_requires_a_full_season():
    with pytest.raises(ValueError, match="requires at least"):
        seasonal_naive([1, 2, 3], 1, season=4)


def test_moving_average_baseline_uses_trailing_window():
    assert moving_average([1, 2, 3, 4, 100], 2, window=4) == [27.25, 27.25]


def test_trend_baseline_extrapolates_linear_history():
    assert trend([2, 4, 6], 2, window=3) == pytest.approx([8, 10])


def test_rolling_origins_keep_training_before_test():
    origins = rolling_origins(40, minimum_training_weeks=20, horizon=5, step=3)
    assert origins
    assert all(origin.train_end == origin.test_start < origin.test_end <= 40 for origin in origins)


def test_backtest_does_not_pass_future_values_to_model():
    class BoundaryModel:
        name = "boundary"

        def forecast(self, history, horizon):
            assert len(history) == 20
            assert history == list(range(20))
            return [20.0] * horizon

    origins = rolling_origins(30, minimum_training_weeks=20, horizon=5, step=20)
    result = run_rolling_backtest(list(map(float, range(30))), origins, [BoundaryModel()], season=3)
    assert result[0]["forecast_origin_index"] == 19


def test_features_are_unchanged_when_future_values_are_appended():
    history = [float(value) for value in range(1, 10)]
    before = build_past_only_features(history, target_index=8)
    after = build_past_only_features(history + [10000.0], target_index=8)
    assert before == after


def test_observed_only_future_features_require_supplied_scenarios():
    with pytest.raises(ValueError, match="Observed-only"):
        validate_future_features(["retail_week", "availability"], set())
    validate_future_features(["retail_week", "availability"], {"availability"})


def test_metrics_calculate_mae_rmse_wape_mase_and_bias():
    metrics = forecast_metrics([15, 16], [14, 15], [10, 12, 14], season=2)
    assert metrics["mae"] == 1
    assert metrics["rmse"] == 1
    assert metrics["wape"] == pytest.approx(2 / 31)
    assert metrics["mase"] == pytest.approx(0.25)
    assert metrics["bias"] == -1


def test_metrics_reject_zero_actual_denominator():
    with pytest.raises(ValueError, match="WAPE is undefined"):
        forecast_metrics([0, 0], [1, 1], [1, 2, 3], season=2)


def test_holt_candidate_is_deterministic():
    model = HoltLinearForecaster(alpha=0.3, beta=0.1)
    first = model.forecast([10, 12, 14, 16, 18], 3)
    second = model.forecast([10, 12, 14, 16, 18], 3)
    assert first == second
    assert len(first) == 3


def test_empirical_intervals_are_ordered_and_need_calibration():
    lower, upper = empirical_interval(100.0, list(range(20)), 0.8)
    assert lower <= 100 <= upper
    with pytest.raises(ValueError, match="Calibration errors are required"):
        empirical_interval(100.0, [], 0.8)


def test_scenario_does_not_mutate_baseline_or_claim_causality():
    baseline = [100.0, 110.0]
    scenario = Scenario("availability sensitivity", (5.0, 5.0))
    result = apply_scenario(baseline, scenario)
    assert result == [105.0, 115.0]
    assert baseline == [100.0, 110.0]
    assert "NOT A CAUSAL FORECAST" in scenario.label


def test_scenario_requires_matching_horizon():
    with pytest.raises(ValueError, match="match the baseline horizon"):
        apply_scenario([1, 2], Scenario("mismatch", (1,)))


def test_manifest_verification_detects_checksum_change(tmp_path):
    dependency = tmp_path / "frozen.txt"
    dependency.write_text("unchanged", encoding="utf-8")
    digest = sha256_file(dependency)
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(f"path,sha256\nfrozen.txt,{digest}\n", encoding="utf-8")
    assert verify_manifest(tmp_path, manifest) == []
    dependency.write_text("changed", encoding="utf-8")
    assert "Frozen dependency checksum mismatch: frozen.txt" in verify_manifest(tmp_path, manifest)


def test_manifest_never_hashes_evaluation_only_dependency(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("path,sha256\nconfig/_hidden_scenario.yaml,abc\n", encoding="utf-8")
    assert "prohibited evaluation-only" in verify_manifest(tmp_path, manifest)[0]


def test_preflight_reports_missing_inputs_without_creating_outputs(tmp_path):
    config = {
        "forecast": {
            "weekly_input": "reports/phase5/weekly_yoy_full_year.csv",
            "phase4_reconciliation_candidates": ["reports/phase4/reconciliation.csv"],
            "freeze_manifests": ["reports/phase9/phase1_8_dependency_manifest.csv"],
            "outputs": {"backtest": "reports/phase10/forecast_backtest_results.csv"},
        }
    }
    missing, issues = preflight(tmp_path, config)
    assert "reports/phase5/weekly_yoy_full_year.csv" in missing
    assert any(item.startswith("one Phase 4 reconciliation artifact") for item in missing)
    assert not issues
    assert not (tmp_path / "reports/phase10").exists()


def test_forecast_horizon_is_positive():
    with pytest.raises(ValueError, match="positive integer"):
        naive([1], 0)


# ============================================================================= committed artefacts and the gate
needs_weekly = pytest.mark.skipif(not WEEKLY_INPUT.exists(), reason="weekly estate history not built yet")


def _weekly_rows():
    with WEEKLY_INPUT.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@needs_weekly
def test_weekly_input_is_contract_shaped_estate_grain():
    rows = validate_weekly_rows(_weekly_rows(), grain="estate", require_contiguous=True,
                                min_rows=FORECAST_CFG["minimum_training_weeks"])
    keys = [(row["retail_year"], row["retail_week"]) for row in rows]
    assert len(keys) == len(set(keys)), "estate weeks must be unique"
    assert not ({"store_id", "category"} & set(rows[0])), "the grain must be the estate, not a store panel"


@needs_weekly
def test_weekly_input_is_chronological_and_contiguous():
    starts = [date.fromisoformat(row["week_start_date"]) for row in _weekly_rows()]
    assert starts == sorted(starts), "weeks must be chronological"
    assert all(day.weekday() == 0 for day in starts), "every retail week starts on a Monday"
    assert {(b - a).days for a, b in zip(starts, starts[1:])} == {7}, "no missing or duplicated week"


@needs_weekly
def test_weekly_input_reconciles_cent_exact_to_the_governed_h2_headline():
    rows = validate_weekly_rows(_weekly_rows(), grain="estate", require_contiguous=True, min_rows=1)
    headline = reconcile_h2_headline(rows)
    assert headline["h2_2024"] == APPROVED_HEADLINE[2024] == Decimal("10188727.55")
    assert headline["h2_2025"] == APPROVED_HEADLINE[2025] == Decimal("9457457.05")
    assert headline["change"] == Decimal("-731270.50")


@needs_weekly
def test_history_is_deep_enough_for_the_configured_rolling_origins():
    rows = _weekly_rows()
    origins = rolling_origins(len(rows), FORECAST_CFG["minimum_training_weeks"],
                              FORECAST_CFG["primary_horizon_weeks"],
                              FORECAST_CFG["rolling_origin_step_weeks"])
    assert len(origins) >= 4, "more origins means a more credible back-test"
    assert origins[0].train_end == FORECAST_CFG["minimum_training_weeks"]
    assert origins[-1].test_end <= len(rows)
    for origin in origins:
        assert origin.train_end == origin.test_start, "training must stop where testing starts"


@needs_weekly
def test_seasonal_naive_is_evaluable_at_every_origin():
    rows = _weekly_rows()
    origins = rolling_origins(len(rows), FORECAST_CFG["minimum_training_weeks"],
                              FORECAST_CFG["primary_horizon_weeks"],
                              FORECAST_CFG["rolling_origin_step_weeks"])
    assert min(origin.train_end for origin in origins) >= FORECAST_CFG["seasonal_period_weeks"]


@needs_weekly
def test_pointwise_backtest_only_contains_out_of_sample_errors():
    values = [float(row["net_revenue"]) for row in _weekly_rows()]
    origins = rolling_origins(len(values), FORECAST_CFG["minimum_training_weeks"],
                              FORECAST_CFG["primary_horizon_weeks"],
                              FORECAST_CFG["rolling_origin_step_weeks"])
    models = model_registry()
    rows = run_pointwise_backtest(values, origins, models)
    assert len(rows) == len(origins) * len(models) * FORECAST_CFG["primary_horizon_weeks"]
    for row in rows:
        assert row["error"] == pytest.approx(row["forecast"] - row["actual"])
    assert {row["model"] for row in rows} == {model.name for model in models}


@needs_weekly
def test_committed_backtest_covers_every_model_at_every_origin():
    origins = rolling_origins(len(_weekly_rows()), FORECAST_CFG["minimum_training_weeks"],
                              FORECAST_CFG["primary_horizon_weeks"],
                              FORECAST_CFG["rolling_origin_step_weeks"])
    backtest = pd.read_csv(REPORTS / "forecast_backtest_results.csv")
    assert set(backtest["model"]) == {model.name for model in model_registry()}
    assert len(backtest) == len(origins) * len(model_registry())
    for model in backtest["model"].unique():
        seen = sorted(backtest.loc[backtest["model"] == model, "forecast_origin_index"])
        assert seen == sorted(origin.train_end - 1 for origin in origins)


# ============================================================================= model selection rule
def _summary(name, wape, mase=1.0, rmse=1.0, mae=1.0, origins=4):
    return ModelSummary(model=name, family="baseline" if name.startswith("B") else "challenger", origins=origins,
                        mean_metrics={"mae": mae, "rmse": rmse, "wape": wape, "mase": mase, "bias": 0.0})


SELECTION_RULE = {"metric": "wape", "challenger_margin": 0.0, "tie_breakers": ["mase", "rmse", "mae"]}


def test_challenger_is_not_promoted_when_it_loses():
    summaries = [_summary("B1_naive", 0.20), _summary("B2_seasonal_naive", 0.10), _summary("M1_holt", 0.30)]
    decision = select_model(summaries, ["B1_naive", "B2_seasonal_naive", "M1_holt"], SELECTION_RULE)
    assert decision["selected_model"] == "B2_seasonal_naive"
    assert decision["promoted_challenger"] is False
    assert decision["improvement"] == pytest.approx(0.10 - 0.30)


def test_challenger_is_promoted_only_when_it_strictly_beats_the_baseline():
    summaries = [_summary("B1_naive", 0.20), _summary("B2_seasonal_naive", 0.10), _summary("M1_holt", 0.09)]
    decision = select_model(summaries, ["B1_naive", "B2_seasonal_naive", "M1_holt"], SELECTION_RULE)
    assert decision["selected_model"] == "M1_holt" and decision["promoted_challenger"] is True


def test_a_tie_does_not_promote_the_challenger():
    summaries = [_summary("B2_seasonal_naive", 0.10), _summary("M1_holt", 0.10)]
    decision = select_model(summaries, ["B2_seasonal_naive", "M1_holt"], SELECTION_RULE)
    assert decision["promoted_challenger"] is False
    assert decision["selected_model"] == "B2_seasonal_naive", "ties keep the incumbent baseline"


def test_selection_requires_a_model_at_every_origin():
    summaries = [_summary("B2_seasonal_naive", 0.10, origins=4), _summary("M1_holt", 0.05, origins=3)]
    with pytest.raises(ValueError, match="every rolling origin"):
        select_model(summaries, ["B2_seasonal_naive", "M1_holt"], SELECTION_RULE, expected_origins=4)


def test_selection_is_independent_of_the_order_rows_arrive_in():
    summaries = [_summary("B2_seasonal_naive", 0.10), _summary("M1_holt", 0.30), _summary("B1_naive", 0.20)]
    order = ["B1_naive", "B2_seasonal_naive", "M1_holt"]
    first = select_model(summaries, order, SELECTION_RULE)
    second = select_model(list(reversed(summaries)), order, SELECTION_RULE)
    assert first["selected_model"] == second["selected_model"]


def test_summarise_averages_metrics_over_origins():
    rows = [{"model": "B1_naive", "mae": 1.0, "rmse": 2.0, "wape": 0.1, "mase": 3.0, "bias": -1.0},
            {"model": "B1_naive", "mae": 3.0, "rmse": 4.0, "wape": 0.3, "mase": 5.0, "bias": 1.0}]
    item = summarise(rows, ["B1_naive"])[0]
    assert item.origins == 2 and item.metric("mae") == 2.0 and item.metric("wape") == pytest.approx(0.2)


# ============================================================================= forecast horizon and intervals
def test_week_labels_roll_over_the_year_boundary():
    labels = project_week_labels(date(2025, 12, 22), 52, 3)
    assert labels == [(1, date(2025, 12, 29)), (2, date(2026, 1, 5)), (3, date(2026, 1, 12))]


def test_forecast_is_projected_beyond_the_observed_history():
    history = [float(index) for index in range(1, 61)]
    rows = build_forecast(history, date(2025, 12, 22), 52, 13, model_registry()[1])
    assert len(rows) == 13
    assert rows[0].week_start_date == date(2025, 12, 29)
    assert rows[0].retail_week == 1


def test_intervals_are_calibrated_from_out_of_sample_errors_only():
    errors = [-100.0, -50.0, 20.0, 80.0, 5.0, -5.0, 30.0, 60.0, 10.0, 40.0,
              -70.0, 15.0, -25.0, 90.0, 35.0, -15.0, 55.0, 5.0, -35.0, 45.0]
    rows = [SimpleNamespace(point_forecast=1000.0, week_start_date=date(2026, 1, 5))]
    bands = build_intervals(rows, errors, [0.8, 0.95])
    assert len(bands) == 2
    for band in bands:
        assert band["lower"] <= 1000.0 <= band["upper"]
    assert bands[1]["lower"] < bands[0]["lower"], "a wider coverage must give a wider band"
    assert bands[1]["upper"] - bands[0]["upper"] == pytest.approx(bands[0]["lower"] - bands[1]["lower"])


def test_calibration_errors_rejects_a_model_that_never_ran():
    with pytest.raises(ValueError, match="No back-test errors"):
        calibration_errors([{"model": "B1_naive", "forecast_origin_index": 0, "horizon_step": 1,
                             "error": 1.0}], "M1_missing")


# ============================================================================= the published gate
@needs_weekly
def test_committed_validation_catalogue_is_fully_passed():
    checks = pd.read_csv(REPORTS / "phase10_validation_checks.csv")
    summary = catalogue_summary(checks.to_dict("records"))
    assert summary["total"] >= 25
    assert summary["all_passed"], checks.loc[checks["status"] != "PASS"].to_string(index=False)


@needs_weekly
def test_catalogue_fails_loudly_rather_than_skipping_a_broken_series():
    rows = _weekly_rows()
    for row in rows:
        if row["retail_year"] == "2024" and 27 <= int(row["retail_week"]) <= 52:
            row["net_revenue"] = str(Decimal(row["net_revenue"]) + Decimal("1000000"))
            break
    normalised = validate_weekly_rows(rows, grain="estate", require_contiguous=True, min_rows=1)
    with pytest.raises(DataContractError, match="H2 headline mismatch"):
        reconcile_h2_headline(normalised)


@needs_weekly
def test_phase10_never_reads_a_governed_phase5_weekly_table():
    assert FORECAST_CFG["weekly_input"] == "reports/phase10/weekly_estate_history.csv"
    assert not FORECAST_CFG["weekly_input"].startswith("reports/phase5")


@needs_weekly
def test_no_phase10_artifact_is_frozen_by_a_historical_manifest():
    governed = set()
    for manifest in FORECAST_CFG["freeze_manifests"]:
        with (ROOT / manifest).open(encoding="utf-8-sig", newline="") as stream:
            governed |= {row["file"] for row in csv.DictReader(stream)}
    assert FORECAST_CFG["weekly_input"] not in governed
    assert not [name for name in governed if name.startswith("reports/phase10/")]


@needs_weekly
def test_provenance_records_the_authoritative_read_only_source():
    provenance = pd.read_csv(REPORTS / "weekly_estate_history_provenance.csv").set_index("record")["value"]
    assert "mart.v_performance_store_week" in provenance["authoritative_source"]
    assert provenance["database_writes"].startswith("none")
    assert provenance["row_count"] == str(len(_weekly_rows()))
    assert provenance["h2_2024_net_revenue"] == "10188727.55"
    assert provenance["h2_2025_net_revenue"] == "9457457.05"


@needs_weekly
def test_forecast_outputs_cover_the_configured_horizon_and_coverages():
    forecast = pd.read_csv(REPORTS / "forecast_weekly.csv")
    selected = pd.read_csv(REPORTS / "forecast_selected_model.csv").set_index("field").loc["selected_model", "value"]
    assert len(forecast) == FORECAST_CFG["primary_horizon_weeks"]
    assert set(forecast["model"]) == {selected}
    bands = pd.read_csv(REPORTS / "forecast_intervals.csv")
    assert sorted(bands["coverage"].unique()) == sorted(FORECAST_CFG["interval_coverages"])
    joined = forecast.merge(bands, on=["week_start_date", "model"])
    assert len(joined) == len(forecast) * len(FORECAST_CFG["interval_coverages"])
    assert (joined["lower"] <= joined["point_forecast"]).all() and (joined["point_forecast"] <= joined["upper"]).all()


@needs_weekly
def test_runner_is_deterministic_across_repeated_runs():
    artifacts = ["forecast_backtest_results.csv", "forecast_model_comparison.csv", "forecast_selected_model.csv",
                 "forecast_weekly.csv", "forecast_intervals.csv", "phase10_validation_checks.csv"]
    before = {name: sha256_file(REPORTS / name) for name in artifacts}
    assert run_phase10.main(["--project-root", str(ROOT)]) == 0
    assert {name: sha256_file(REPORTS / name) for name in artifacts} == before


def test_source_refuses_a_database_that_is_not_the_governed_warehouse():
    from src.forecasting.source import open_read_only_engine
    with pytest.raises(ValueError, match="Refusing to read"):
        open_read_only_engine({"database": {"server": "localhost", "database": "SomeOtherDb",
                                            "driver": "ODBC Driver 18 for SQL Server",
                                            "trusted_connection": True, "trust_server_certificate": True}})
    with pytest.raises(ValueError, match="Windows authentication"):
        open_read_only_engine({"database": {"server": "localhost", "database": "BrightwaterRetail",
                                            "driver": "ODBC Driver 18 for SQL Server",
                                            "trusted_connection": False, "trust_server_certificate": True,
                                            "uid": "sa", "pwd": "secret"}})
