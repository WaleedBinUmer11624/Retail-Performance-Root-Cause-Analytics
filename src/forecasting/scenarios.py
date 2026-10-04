"""What-if scenarios layered on a baseline forecast.

Inputs: a baseline forecast and per-week additive adjustments. Output: a new adjusted list; the
baseline is never mutated, and the label states the result is a sensitivity, not a causal forecast.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """Named set of weekly additive adjustments with its non-causal label."""
    name: str
    weekly_adjustments: tuple[float, ...]
    label: str = "SCENARIO / SENSITIVITY, NOT A CAUSAL FORECAST"


def apply_scenario(baseline: list[float], scenario: Scenario) -> list[float]:
    """Return the baseline plus the scenario's adjustment for each week."""
    if len(baseline) != len(scenario.weekly_adjustments):
        raise ValueError("Scenario adjustments must match the baseline horizon")
    return [float(value) + float(adjustment) for value, adjustment in zip(baseline, scenario.weekly_adjustments)]
