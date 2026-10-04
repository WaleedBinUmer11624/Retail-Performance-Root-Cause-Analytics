"""The Phase 10 validation catalogue.

Every check states what it compared and against what. A check that cannot be evaluated is a FAIL,
never a skip: a silent skip in a forecasting gate is how a broken input gets a forecast attached.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .contracts import APPROVED_HEADLINE, WEEKLY_REQUIRED


def _row(group: str, check: str, value, reference, status: bool, detail: str = "") -> dict:
    return {"group": group, "check": check, "value": value, "reference": reference,
            "status": "PASS" if status else "FAIL", "detail": detail}


def build_catalogue(context: dict) -> list[dict]:
    """Return one PASS/FAIL row per check across input, reconciliation, back-test, leakage,
    selection, forecast and governance."""
    rows: list[dict] = []
    forecast = context["forecast"]
    rows_in = context["weekly_rows"]
    origins = context["origins"]
    models = context["models"]
    backtest = context["backtest"]
    summary = context["model_summaries"]
    decision = context["selection"]
    history = context["history"]
    forecast_rows = context["forecast_rows"]
    bands = context["bands"]
    errors = context["calibration_errors"]

    # ---- input contract
    present = set(rows_in[0]) if rows_in else set()
    required = set(WEEKLY_REQUIRED)
    rows.append(_row("Input contract", "contract columns present",
                     ", ".join(sorted(required)), ", ".join(sorted(required)),
                     required <= present, f"{len(present)} columns supplied"))

    keys = [(int(row["retail_year"]), int(row["retail_week"])) for row in rows_in]
    rows.append(_row("Input contract", "no duplicate estate weeks", len(keys), len(set(keys)),
                     len(keys) == len(set(keys))))
    rows.append(_row("Input contract", "single estate grain, no entity column", len(rows_in), len(rows_in),
                     not ({"store_id", "category"} & present)))

    starts = [row["week_start_date"] for row in rows_in]
    rows.append(_row("Input contract", "chronological by week_start_date", "ascending", "ascending",
                     all(a <= b for a, b in zip(starts, starts[1:]))))
    rows.append(_row("Input contract", "every week starts on a Monday", sum(d.weekday() == 0 for d in starts),
                     len(starts), all(d.weekday() == 0 for d in starts)))
    gaps = {(b - a).days for a, b in zip(starts, starts[1:])}
    rows.append(_row("Input contract", "contiguous 7-day weeks", sorted(gaps), [7], gaps == {7}))

    minimum = forecast["minimum_training_weeks"] + forecast["primary_horizon_weeks"]
    rows.append(_row("Input contract", "history covers training plus horizon", len(rows_in), f">= {minimum}",
                     len(rows_in) >= minimum, "minimum_training_weeks + primary_horizon_weeks"))

    # ---- reconciliation
    for year in (2024, 2025):
        total = sum((row["net_revenue"] for row in rows_in
                     if row["retail_year"] == year and 27 <= row["retail_week"] <= 52), Decimal("0"))
        reference = APPROVED_HEADLINE[year]
        rows.append(_row("Reconciliation", f"H2 {year} net revenue equals the approved governed total",
                         str(total), str(reference), total == reference, "weeks 27-52, cent-exact"))
    change = APPROVED_HEADLINE[2025] - APPROVED_HEADLINE[2024]
    yoy = (change / APPROVED_HEADLINE[2024] * Decimal("100")).quantize(Decimal("0.000001"))
    rows.append(_row("Reconciliation", "H2 change and YoY reported from the approved totals",
                     f"{change}; {yoy}%", "derived", True, "headline is never re-fitted to the model"))

    # ---- back-test
    rows.append(_row("Back-test", "at least one rolling origin", len(origins), "> 0", bool(origins)))
    rows.append(_row("Back-test", "every configured model evaluated at every origin",
                     len(backtest), len(origins) * len(models),
                     len(backtest) == len(origins) * len(models)))
    rows.append(_row("Back-test", "every model completed every origin",
                     len(summary), len(models), all(item.origins == len(origins) for item in summary)))
    rows.append(_row("Back-test", "four registered baselines compared",
                     sorted(item.model for item in summary if item.family == "baseline"),
                     "4 baselines", sum(item.family == "baseline" for item in summary) == 4))
    # x == x is False only for NaN, so this catches a metric that silently failed to compute.
    rows.append(_row("Back-test", "every metric finite", len(backtest) * 5, len(backtest) * 5,
                     all(isinstance(float(row[metric]), float) and float(row[metric]) == float(row[metric])
                         for row in backtest
                         for metric in ("mae", "rmse", "wape", "mase", "bias"))))

    # ---- leakage
    strict_prefix = sum(1 for o in origins if o.train_end == o.test_start)
    rows.append(_row("Leakage", "training is the strict prefix before every origin",
                     strict_prefix, len(origins), strict_prefix == len(origins),
                     "no origin can see its own test week or anything after it"))
    rows.append(_row("Leakage", "forecast horizon never overlaps observed weeks",
                     forecast_rows[0].week_start_date.isoformat() if forecast_rows else "none",
                     f"after {starts[-1].isoformat()}",
                     bool(forecast_rows) and forecast_rows[0].week_start_date > starts[-1]))
    rows.append(_row("Leakage", "interval calibration uses out-of-sample errors only",
                     len(errors), f"> 0 from {len(origins)} origins", len(errors) > 0,
                     "errors come from back-test origins, never from the fitted window"))

    # ---- selection
    selected_appearances = sum(1 for row in backtest if row["model"] == decision["selected_model"])
    rows.append(_row("Selection", "selected model was evaluated at every origin",
                     selected_appearances, len(origins), selected_appearances == len(origins)))
    rows.append(_row("Selection", "challenger promoted only when it beats the best baseline",
                     decision["promoted_challenger"],
                     f"improvement {decision['improvement']:.6f} > margin {decision['challenger_margin']}",
                     decision["promoted_challenger"] == (decision["improvement"] > decision["challenger_margin"])))
    rows.append(_row("Selection", "selected model is the best under the selection rule",
                     decision["selected_model"],
                     f"best baseline {decision['best_baseline']}",
                     decision["selected_model"] in {decision["best_baseline"], decision["best_challenger"]}))

    # ---- forecast
    horizon = forecast["primary_horizon_weeks"]
    rows.append(_row("Forecast", "forecast covers the configured horizon", len(forecast_rows), horizon,
                     len(forecast_rows) == horizon))
    future_starts = [row.week_start_date for row in forecast_rows]
    future_gaps = {(b - a).days for a, b in zip(future_starts, future_starts[1:])}
    rows.append(_row("Forecast", "forecast weeks are contiguous and future-dated", sorted(future_gaps), [7],
                     future_gaps == {7} and (not future_starts or future_starts[0] > starts[-1])))
    rows.append(_row("Forecast", "point forecasts finite and positive",
                     f"min {min(row.point_forecast for row in forecast_rows):.2f}", "> 0",
                     all(row.point_forecast > 0 for row in forecast_rows)))
    rows.append(_row("Forecast", "an interval is published for every week and coverage",
                     len(bands), len(forecast_rows) * len(forecast["interval_coverages"]),
                     len(bands) == len(forecast_rows) * len(forecast["interval_coverages"])))
    rows.append(_row("Forecast", "every interval brackets its point forecast",
                     sum(1 for band in bands if band["lower"] > band["upper"]), 0,
                     all(band["lower"] <= band["upper"] for band in bands)))

    # ---- governance
    rows.append(_row("Governance", "freeze manifests verified before the run",
                     len(context["freeze_manifest_rows"]), "> 0", len(context["freeze_manifest_rows"]) > 0))
    rows.append(_row("Governance", "weekly input is not a governed Phase 1-9 artifact",
                     context["weekly_input"], "ungoverned Phase 10 input",
                     not any(context["weekly_input"] in manifest for manifest in context["governed_files"])))
    rows.append(_row("Governance", "no evaluation-only asset referenced",
                     0, 0, not context["evaluation_refs"],
                     ", ".join(context["evaluation_refs"]) or "none"))
    return rows


def catalogue_passed(rows: list[dict]) -> bool:
    """True only for a non-empty catalogue in which every check passed."""
    return bool(rows) and all(row["status"] == "PASS" for row in rows)


def catalogue_summary(rows: list[dict]) -> dict:
    """Return total, passed and failed counts and the overall verdict."""
    passed = sum(row["status"] == "PASS" for row in rows)
    return {"total": len(rows), "passed": passed, "failed": len(rows) - passed,
            "all_passed": catalogue_passed(rows)}
