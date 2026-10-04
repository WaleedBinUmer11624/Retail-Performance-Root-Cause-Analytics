"""Baseline forecasting methods that any challenger model must beat.

Input: a weekly history and a horizon in weeks. Output: a list of point forecasts, one per week.
"""
from math import fsum


def _check(history: list[float], horizon: int) -> None:
    if not history:
        raise ValueError("Forecast history must not be empty")
    if horizon < 1:
        raise ValueError("horizon must be a positive integer")


def naive(history: list[float], horizon: int) -> list[float]:
    """Repeat the last observed week."""
    _check(history, horizon)
    return [float(history[-1])] * horizon


def seasonal_naive(history: list[float], horizon: int, season: int = 52) -> list[float]:
    """Repeat the same week one season earlier."""
    _check(history, horizon)
    # Refuse rather than fall back: a partial season would silently become a different method.
    if season < 1 or len(history) < season:
        raise ValueError(f"Seasonal naive requires at least {season} observed weeks")
    return [float(history[-season + index % season]) for index in range(horizon)]


def moving_average(history: list[float], horizon: int, window: int = 4) -> list[float]:
    """Project the mean of the trailing window as a flat line."""
    _check(history, horizon)
    if window < 1:
        raise ValueError("window must be positive")
    value = fsum(history[-window:]) / min(len(history), window)
    return [value] * horizon


def trend(history: list[float], horizon: int, window: int = 26) -> list[float]:
    """Extrapolate an ordinary least-squares line fitted to the trailing window."""
    _check(history, horizon)
    sample = [float(value) for value in history[-window:]]
    count = len(sample)
    if count < 2:
        return [sample[-1]] * horizon
    x_mean = (count - 1) / 2
    y_mean = fsum(sample) / count
    denominator = fsum((index - x_mean) ** 2 for index in range(count))
    slope = fsum((index - x_mean) * (value - y_mean) for index, value in enumerate(sample)) / denominator
    intercept = y_mean - slope * x_mean
    return [intercept + slope * (count - 1 + step) for step in range(1, horizon + 1)]
