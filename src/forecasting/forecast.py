"""The forward forecast and its intervals.

Point forecasts come from the selected model applied to the whole observed series. Interval radii
come from the out-of-sample errors that same model produced during the rolling-origin back-test,
so the band is calibrated on weeks the model never saw and is never widened to look good.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .intervals import empirical_interval


@dataclass(frozen=True)
class ForecastRow:
    """One future retail week and its point forecast."""
    retail_week: int
    week_start_date: date
    point_forecast: float


def project_week_labels(last_start: date, last_week: int, horizon: int) -> list[tuple[int, date]]:
    """The retail weeks that follow the observed series, rolling 52 -> 1 at the year boundary."""
    labels = []
    start, week = last_start, last_week
    for _ in range(horizon):
        start = start + timedelta(days=7)
        week = 1 if week >= 52 else week + 1
        labels.append((week, start))
    return labels


def build_forecast(history: list[float], last_start: date, last_week: int, horizon: int, model) -> list[ForecastRow]:
    """Forecast `horizon` weeks past the observed series with the selected model."""
    predictions = [float(value) for value in model.forecast(history, horizon)]
    if len(predictions) != horizon:
        raise ValueError("Selected model did not return the requested horizon")
    return [
        ForecastRow(retail_week=week, week_start_date=start, point_forecast=value)
        for (week, start), value in zip(project_week_labels(last_start, last_week, horizon), predictions)
    ]


def calibration_errors(pointwise_rows: list[dict], model: str) -> list[float]:
    """Signed out-of-sample errors this model made, in origin then horizon-step order."""
    errors = [
        float(row["error"])
        for row in sorted(pointwise_rows, key=lambda item: (item["model"], item["forecast_origin_index"],
                                                            item["horizon_step"]))
        if row["model"] == model
    ]
    if not errors:
        raise ValueError(f"No back-test errors available to calibrate intervals for {model}")
    return errors


def build_intervals(rows: list[ForecastRow], errors: list[float], coverages: list[float]) -> list[dict]:
    """One interval band per forecast week and coverage level."""
    bands = []
    for row in rows:
        for coverage in coverages:
            lower, upper = empirical_interval(row.point_forecast, errors, coverage)
            bands.append({"week_start_date": row.week_start_date, "coverage": coverage,
                          "lower": lower, "upper": upper})
    return bands
