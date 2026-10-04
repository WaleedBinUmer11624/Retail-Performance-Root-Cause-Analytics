"""Leakage-safe feature construction for weekly forecasting.

Inputs: a weekly value series or a retail calendar week. Outputs: lag and rolling features built
only from earlier weeks, calendar features, and a guard against assuming unknown future drivers.
"""
from datetime import date


# Calendar fields are known ahead of time; observed measures exist only once a week has happened.
KNOWN_IN_ADVANCE = {"retail_year", "retail_week", "week_start_date", "month", "quarter"}
OBSERVED_ONLY = {
    "net_revenue",
    "transactions",
    "units",
    "gross_margin",
    "returns",
    "availability",
    "promotion_share",
    "discount_rate",
}


def build_past_only_features(values: list[float], target_index: int) -> dict[str, float | None]:
    """Lag 1, 4 and 52 and a 4-week mean for target_index, using only values before it."""
    if target_index < 0 or target_index > len(values):
        raise ValueError("target_index must identify the next point or a point in the series")
    history = values[:target_index]
    lag_1 = history[-1] if history else None
    lag_4 = history[-4] if len(history) >= 4 else None
    lag_52 = history[-52] if len(history) >= 52 else None
    rolling_4 = sum(history[-4:]) / 4 if len(history) >= 4 else None
    return {"lag_1": lag_1, "lag_4": lag_4, "lag_52": lag_52, "rolling_mean_4": rolling_4}


def retail_calendar_features(week_start_date: date, retail_week: int) -> dict[str, int]:
    """Retail week, month and quarter for a Monday week start."""
    if week_start_date.weekday() != 0 or not 1 <= retail_week <= 53:
        raise ValueError("Expected a Monday retail week start and a week number from 1 to 53")
    month = week_start_date.month
    return {"retail_week": retail_week, "month": month, "quarter": (month - 1) // 3 + 1}


def validate_future_features(feature_names: list[str], supplied_future_values: set[str]) -> None:
    """Raise if a feature needs an observed-only value that no scenario has supplied."""
    unavailable = [
        name
        for name in feature_names
        if name in OBSERVED_ONLY and name not in supplied_future_values
    ]
    if unavailable:
        raise ValueError(
            "Observed-only features cannot be assumed in the future: "
            + ", ".join(sorted(unavailable))
        )
