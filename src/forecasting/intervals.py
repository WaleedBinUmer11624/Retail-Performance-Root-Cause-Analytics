"""Empirical prediction intervals from out-of-sample back-test errors.

Inputs: a point forecast, calibration errors and a target coverage. Output: a (lower, upper) pair.
"""
from math import ceil


def empirical_interval(point_forecast: float, calibration_errors: list[float], coverage: float) -> tuple[float, float]:
    """Symmetric interval whose radius is the coverage quantile of absolute errors."""
    if not 0 < coverage < 1:
        raise ValueError("coverage must be between 0 and 1")
    if not calibration_errors:
        raise ValueError("Calibration errors are required; intervals cannot be invented")
    # Conformal (n + 1) rank: refuse a coverage the sample is too small to support.
    rank = ceil((len(calibration_errors) + 1) * coverage)
    if rank > len(calibration_errors):
        raise ValueError("Insufficient calibration errors for requested interval coverage")
    absolute_errors = sorted(abs(float(error)) for error in calibration_errors)
    radius = absolute_errors[rank - 1]
    return point_forecast - radius, point_forecast + radius
