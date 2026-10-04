"""Forecaster interface, the baseline and Holt models, and the explicit model registry.

Input: a weekly history and a horizon. Output: point forecasts. model_registry() fixes the
candidate set so selection cannot pick up an unreviewed model.
"""
from dataclasses import dataclass

from .baselines import moving_average, naive, seasonal_naive, trend


class Forecaster:
    """Interface: forecast `horizon` weeks from `history`."""
    def forecast(self, history: list[float], horizon: int) -> list[float]:
        """Return one point forecast per week of the horizon."""
        raise NotImplementedError


@dataclass(frozen=True)
class BaselineForecaster(Forecaster):
    """Named wrapper that dispatches to one of the baseline methods."""
    name: str
    method: str
    window: int = 4
    season: int = 52

    def forecast(self, history: list[float], horizon: int) -> list[float]:
        """Run the configured baseline method."""
        if self.method == "naive":
            return naive(history, horizon)
        if self.method == "seasonal_naive":
            return seasonal_naive(history, horizon, self.season)
        if self.method == "moving_average":
            return moving_average(history, horizon, self.window)
        if self.method == "trend":
            return trend(history, horizon, self.window)
        raise ValueError(f"Unknown baseline method: {self.method}")


@dataclass(frozen=True)
class HoltLinearForecaster(Forecaster):
    """Holt linear exponential smoothing with fixed alpha (level) and beta (trend)."""
    alpha: float = 0.3
    beta: float = 0.1
    name: str = "holt_linear"

    def __post_init__(self) -> None:
        if not 0 < self.alpha <= 1 or not 0 < self.beta <= 1:
            raise ValueError("Holt smoothing parameters must be in (0, 1]")

    def forecast(self, history: list[float], horizon: int) -> list[float]:
        """Smooth level and trend through the history, then extend the trend."""
        if not history or horizon < 1:
            raise ValueError("Holt forecast requires history and a positive horizon")
        values = [float(value) for value in history]
        level = values[0]
        # Seed the trend from the average step over the first few weeks, not a single noisy step.
        trend = (values[min(len(values) - 1, 3)] - values[0]) / min(len(values) - 1, 3) if len(values) > 1 else 0.0
        for actual in values[1:]:
            previous_level = level
            level = self.alpha * actual + (1 - self.alpha) * (level + trend)
            trend = self.beta * (level - previous_level) + (1 - self.beta) * trend
        return [level + step * trend for step in range(1, horizon + 1)]


def model_registry(season: int = 52, moving_window: int = 4, trend_window: int = 26) -> list[Forecaster]:
    """Return the four baselines (B1 to B4) and the Holt challenger, in a fixed order."""
    return [
        BaselineForecaster("B1_naive", "naive"),
        BaselineForecaster("B2_seasonal_naive", "seasonal_naive", season=season),
        BaselineForecaster("B3_moving_average", "moving_average", window=moving_window),
        BaselineForecaster("B4_trend", "trend", window=trend_window),
        HoltLinearForecaster(),
    ]
