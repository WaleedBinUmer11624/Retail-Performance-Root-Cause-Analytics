"""Rolling-origin back-testing of weekly forecasters.

Inputs: an ordered weekly series, rolling-origin boundaries and the forecasters to compare.
Outputs: per-origin accuracy metrics, and point-wise out-of-sample errors used to calibrate intervals.
"""
from dataclasses import dataclass

from .metrics import forecast_metrics
from .models import Forecaster


@dataclass(frozen=True)
class RollingOrigin:
    """One back-test split: train on [0, train_end), test on [test_start, test_end)."""
    train_end: int
    test_start: int
    test_end: int


def rolling_origins(
    observation_count: int,
    minimum_training_weeks: int,
    horizon: int,
    step: int,
) -> list[RollingOrigin]:
    """Return origins every `step` weeks, each with a full horizon of actuals after it."""
    if min(observation_count, minimum_training_weeks, horizon, step) < 1:
        raise ValueError("Observation count, training size, horizon and step must be positive")
    return [
        RollingOrigin(origin, origin, origin + horizon)
        for origin in range(minimum_training_weeks, observation_count - horizon + 1, step)
    ]


def _splits(values: list[float], origins: list[RollingOrigin], models: list[Forecaster]):
    """Yield every (origin, model, training, actual, prediction) once, so metrics and point-wise
    errors are produced from exactly the same forecasts rather than from a second run."""
    for origin in origins:
        if origin.train_end != origin.test_start or origin.test_end > len(values):
            raise ValueError("Invalid rolling-origin boundaries")
        training = values[: origin.train_end]
        actual = values[origin.test_start : origin.test_end]
        if not training or len(actual) != origin.test_end - origin.test_start:
            raise ValueError("Backtest split has an empty or incomplete segment")
        for model in models:
            # Only the training slice is passed, so a model cannot see the weeks it is scored on.
            prediction = model.forecast(training, len(actual))
            if len(prediction) != len(actual):
                raise ValueError(f"{model.name} returned {len(prediction)} values for {len(actual)} weeks")
            yield origin, model, list(training), list(actual), [float(value) for value in prediction]


def run_rolling_backtest(
    values: list[float],
    origins: list[RollingOrigin],
    models: list[Forecaster],
    season: int = 52,
    grain: str = "estate_week",
) -> list[dict]:
    """Score every model at every origin; one row of MAE, RMSE, WAPE, MASE and bias each."""
    results = []
    for origin, model, training, actual, prediction in _splits(values, origins, models):
        scores = forecast_metrics(actual, prediction, training, season)
        results.append(
            {
                "model": model.name,
                "forecast_grain": grain,
                "forecast_origin_index": origin.train_end - 1,
                "horizon_weeks": len(actual),
                **scores,
            }
        )
    return results


def run_pointwise_backtest(values: list[float], origins: list[RollingOrigin], models: list[Forecaster]) -> list[dict]:
    """Every out-of-sample prediction, week by week. This is the calibration material for intervals."""
    rows = []
    for origin, model, _training, actual, prediction in _splits(values, origins, models):
        for step, (observed, predicted) in enumerate(zip(actual, prediction), start=1):
            rows.append(
                {
                    "model": model.name,
                    "forecast_origin_index": origin.train_end - 1,
                    "horizon_step": step,
                    "actual": observed,
                    "forecast": predicted,
                    "error": predicted - observed,
                }
            )
    return rows
