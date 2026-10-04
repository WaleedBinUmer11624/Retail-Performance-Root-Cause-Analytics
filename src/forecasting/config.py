"""Load and validate the Phase 10 forecasting configuration.

Input: the forecasting YAML file. Output: the parsed configuration dict, or ValueError naming the
first setting that breaks the approved scope (net revenue, estate-week grain, positive windows).
"""
from pathlib import Path

import yaml


def load_config(path: Path) -> dict:
    """Read the YAML configuration and validate it before returning it."""
    with path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    validate_config(config)
    return config


def validate_config(config: dict) -> None:
    """Raise ValueError unless the configuration matches the approved Phase 10 scope."""
    if not isinstance(config, dict) or config.get("phase") != 10:
        raise ValueError("Configuration must declare phase: 10")
    forecast = config.get("forecast")
    if not isinstance(forecast, dict):
        raise ValueError("Configuration is missing the forecast section")
    if forecast.get("target") != "net_revenue":
        raise ValueError("The primary target must be net_revenue")
    if forecast.get("grain") != "estate_week":
        raise ValueError("The primary grain must be estate_week")
    horizon = forecast.get("primary_horizon_weeks")
    if not isinstance(horizon, int) or horizon < 1:
        raise ValueError("primary_horizon_weeks must be a positive integer")
    if horizon not in forecast.get("supported_horizons_weeks", []):
        raise ValueError("The primary horizon must be in supported_horizons_weeks")
    for name in (
        "minimum_training_weeks",
        "seasonal_period_weeks",
        "rolling_origin_step_weeks",
        "moving_average_window_weeks",
        "trend_window_weeks",
    ):
        if not isinstance(forecast.get(name), int) or forecast[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    coverages = forecast.get("interval_coverages", [])
    if not coverages or any(not 0 < value < 1 for value in coverages):
        raise ValueError("interval_coverages must contain values between 0 and 1")
    for name in ("weekly_input", "phase4_reconciliation_candidates", "freeze_manifests"):
        if not forecast.get(name):
            raise ValueError(f"Configuration is missing forecast.{name}")
