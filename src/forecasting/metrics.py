"""Forecast accuracy metrics.

Inputs: actuals, forecasts and the training history. Output: MAE, RMSE, WAPE, MASE and bias, where
errors are forecast minus actual, so positive bias means over-forecasting.
"""
from math import fsum, sqrt


def _paired(actual: list[float], forecast: list[float]) -> None:
    if not actual or len(actual) != len(forecast):
        raise ValueError("actual and forecast must be non-empty and have equal length")


def forecast_metrics(actual: list[float], forecast: list[float], training: list[float], season: int = 52) -> dict[str, float]:
    """Return accuracy metrics for one forecast against its actuals."""
    _paired(actual, forecast)
    errors = [float(prediction) - float(observed) for observed, prediction in zip(actual, forecast)]
    absolute = [abs(error) for error in errors]
    # MASE scales by the in-sample seasonal naive error, or lag 1 when history is under a season.
    scale_lag = season if len(training) > season else 1
    if len(training) <= scale_lag:
        raise ValueError("Training history is too short to calculate MASE")
    scale = fsum(abs(training[index] - training[index - scale_lag]) for index in range(scale_lag, len(training))) / (len(training) - scale_lag)
    if scale == 0:
        raise ValueError("MASE scale is zero")
    denominator = fsum(abs(value) for value in actual)
    if denominator == 0:
        raise ValueError("WAPE is undefined when all actual values are zero")
    return {
        "mae": fsum(absolute) / len(absolute),
        "rmse": sqrt(fsum(error * error for error in errors) / len(errors)),
        "wape": fsum(absolute) / denominator,
        "mase": (fsum(absolute) / len(absolute)) / scale,
        "bias": fsum(errors) / len(errors),
    }
