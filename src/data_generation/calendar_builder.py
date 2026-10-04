"""Calendar: dim_date, retail weeks and within-week day weights.

Retail weeks run Monday to Sunday. Retail year 2024 starts Monday 2024-01-01,
retail year 2025 starts Monday 2024-12-30, so week N of 2025 always has the
same weekdays as week N of 2024. That is what makes the H2 comparison
week-aligned.

Input: the calendar section of the generator config. Outputs: the week table, dim_date and
per-week day weights.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_week_table(cfg: dict) -> pd.DataFrame:
    """One row per simulated week (index 0..W-1)."""
    start = pd.Timestamp(cfg["calendar"]["start_date"])
    n_weeks = cfg["calendar"]["simulated_weeks"]
    week_start = pd.date_range(start, periods=n_weeks, freq="7D")
    idx = np.arange(n_weeks)
    return pd.DataFrame(
        {
            "week_idx": idx,
            "week_start": week_start,
            "week_end": week_start + pd.Timedelta(days=6),
            "retail_year": 2024 + idx // 52,
            "retail_week": idx % 52 + 1,
        }
    )


def build_dim_date(cfg: dict, weeks: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar day with calendar, retail-week, holiday and trading-day attributes."""
    cal = cfg["calendar"]
    dates = pd.date_range(cal["start_date"], cal["end_date"], freq="D")
    holidays = {pd.Timestamp(k): v for k, v in cal["bank_holidays"].items()}
    closed = {pd.Timestamp(d) for d in cal["closed_dates"]}

    day_offset = (dates - pd.Timestamp(cal["start_date"])).days
    week_idx = day_offset // 7
    wk = weeks.set_index("week_idx")

    df = pd.DataFrame({"date": dates})
    df["date_key"] = df["date"].dt.strftime("%Y%m%d").astype(int)
    df["day_of_week"] = df["date"].dt.dayofweek + 1  # 1 = Monday
    df["day_name"] = df["date"].dt.day_name()
    df["is_weekend"] = df["day_of_week"] >= 6
    df["calendar_month"] = df["date"].dt.month
    df["month_name"] = df["date"].dt.month_name()
    df["calendar_quarter"] = df["date"].dt.quarter
    df["calendar_year"] = df["date"].dt.year
    df["retail_year"] = wk.loc[week_idx, "retail_year"].to_numpy()
    df["retail_week"] = wk.loc[week_idx, "retail_week"].to_numpy()
    df["retail_week_start"] = wk.loc[week_idx, "week_start"].to_numpy()
    df["retail_half"] = np.where(df["retail_week"] <= 26, "H1", "H2")
    df["is_bank_holiday"] = df["date"].isin(holidays.keys())
    df["holiday_name"] = df["date"].map(holidays)
    df["is_trading_day"] = ~df["date"].isin(closed)
    df["same_day_last_year"] = df["date"] - pd.Timedelta(days=364)  # week-aligned LY
    cols = ["date_key", "date"] + [c for c in df.columns if c not in ("date_key", "date")]
    return df[cols]


def build_day_weights(cfg: dict, weeks: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return (weights[W,7] normalised within each week, in_extract_share[W]).

    in_extract_share is the share of a week's normal trading that falls inside
    the extract window. Only the final partial week is below 1.
    """
    cal = cfg["calendar"]
    base = np.asarray(cal["day_of_week_weights"], dtype=float)
    mult = cal["day_multipliers"]
    holidays = {pd.Timestamp(k): v for k, v in cal["bank_holidays"].items()}
    closed = {pd.Timestamp(d) for d in cal["closed_dates"]}
    end = pd.Timestamp(cal["end_date"])

    n = len(weeks)
    w = np.tile(base, (n, 1))
    share = np.ones(n)
    for i, ws in enumerate(weeks["week_start"]):
        for d in range(7):
            day = ws + pd.Timedelta(days=d)
            name = holidays.get(day, "")
            if day in closed:
                w[i, d] = 0.0
            elif name == "St Stephen's Day":
                w[i, d] *= mult["st_stephens_day"]
            elif name:
                w[i, d] *= mult["bank_holiday"]
            if day.month == 12 and day.day == 24:
                w[i, d] *= mult["christmas_eve"]
            # Days after the extract end are lost trade, not shifted onto the remaining days.
            if day > end:
                share[i] -= base[d] / base.sum()
                w[i, d] = 0.0
    w = w / w.sum(axis=1, keepdims=True)
    return w, np.clip(share, 0, 1)
