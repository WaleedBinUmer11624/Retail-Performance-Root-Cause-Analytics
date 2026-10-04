"""H2 week-aligned comparison: period checks, headline KPIs, weekly trend and its profile.

Comparison basis (BRD sign-off item 2): retail weeks 27 to 52 of the current retail year against the
same retail weeks of the prior retail year. Retail weeks run Monday to Sunday, so every compared week
has the same weekdays and the comparison is free of day-of-week mix.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .contribution import safe_div, yoy_pct


@dataclass(frozen=True)
class Periods:
    cy_year: int
    py_year: int
    week_from: int
    week_to: int

    @property
    def n_weeks(self) -> int:
        return self.week_to - self.week_from + 1

    @property
    def label_cy(self) -> str:
        return f"H2 {self.cy_year}"

    @property
    def label_py(self) -> str:
        return f"H2 {self.py_year}"


def load_periods(project: dict) -> Periods:
    c, p = project["comparison"]["current_period"], project["comparison"]["prior_period"]
    if (c["retail_week_from"], c["retail_week_to"]) != (p["retail_week_from"], p["retail_week_to"]):
        raise ValueError("current and prior comparison periods must cover the same retail weeks")
    if c["retail_year"] != p["retail_year"] + 1:
        raise ValueError("the prior period must be the retail year before the current period")
    return Periods(int(c["retail_year"]), int(p["retail_year"]), int(c["retail_week_from"]), int(c["retail_week_to"]))


def check_week_alignment(weeks: pd.DataFrame, periods: Periods) -> pd.DataFrame:
    """weeks = diag.v_h2_week_comparison rows for the current year. Returns one row per check."""
    w = weeks.sort_values("retail_week")
    start_cy, start_py = pd.to_datetime(w["week_start_cy"]), pd.to_datetime(w["week_start_py"])
    checks = [
        ("26 current-year weeks selected", len(w) == periods.n_weeks, f"{len(w)} weeks"),
        ("weeks are retail weeks 27 to 52", list(w["retail_week"]) == list(range(periods.week_from, periods.week_to + 1)),
         f"{int(w['retail_week'].min())} to {int(w['retail_week'].max())}"),
        ("every compared week has 7 days in both years", bool((w["days_cy"] == 7).all() and (w["days_py"] == 7).all()),
         f"{int(w['days_cy'].sum())} vs {int(w['days_py'].sum())} days"),
        ("prior-year week is the same retail week number",
         bool((w["week_key_py"] % 100 == w["retail_week"]).all() and (w["week_key_py"] // 100 == periods.py_year).all()),
         "week_key_py = prior year, same week"),
        ("compared weeks start on the same weekday", bool((start_cy.dt.dayofweek == start_py.dt.dayofweek).all()),
         f"weekday {sorted(set(start_cy.dt.dayofweek))} vs {sorted(set(start_py.dt.dayofweek))}"),
        ("compared weeks are 364 days apart", bool(((start_cy - start_py).dt.days == 364).all()),
         f"{sorted(set((start_cy - start_py).dt.days))} days"),
    ]
    return pd.DataFrame(checks, columns=["check", "passed", "detail"])


HEADLINE_METRICS = [
    # metric, label, kind (money/count/ratio/pct), sign of its effect on net revenue (for contribution)
    ("sales_revenue", "Sales Revenue (EUR)", "money", 1),
    ("returns_value", "Returns Value (EUR)", "money", -1),
    ("net_revenue", "Net Revenue (EUR)", "money", 1),
    ("gross_margin", "Gross Margin (EUR)", "money", None),
    ("gross_margin_pct", "Gross Margin %", "pct", None),
    ("transactions", "Transactions", "count", None),
    ("units_sold", "Units Sold", "count", None),
    ("aov", "Average Order Value (EUR)", "ratio", None),
    ("upt", "Units per Transaction", "ratio", None),
    ("asp", "Average Selling Price (EUR)", "ratio", None),
    ("return_rate_value", "Return Rate % (value)", "pct", None),
    ("return_rate_units", "Return Rate % (units)", "pct", None),
    ("promo_revenue_share", "Promo Revenue Share %", "pct", None),
    ("discount_value", "Discount Value (EUR)", "money", None),
]


def headline_components(h: pd.DataFrame, periods: Periods) -> tuple[dict, dict]:
    """Recompute every headline KPI in Python from the additive components (not from the view's ratios)."""
    out = []
    for year in (periods.py_year, periods.cy_year):
        r = h[h["retail_year"] == year]
        if len(r) != 1:
            raise ValueError(f"headline: expected one row for retail year {year}, found {len(r)}")
        r = r.iloc[0]
        d = {k: float(r[k]) for k in ("sales_revenue", "returns_value", "net_revenue", "gross_margin", "transactions",
                                      "units_sold", "returned_units", "promo_sales_revenue", "discount_value", "cogs",
                                      "weeks", "days", "trading_store_days")}
        d["gross_margin_pct"] = safe_div(d["gross_margin"], d["net_revenue"])
        d["aov"] = safe_div(d["sales_revenue"], d["transactions"])
        d["upt"] = safe_div(d["units_sold"], d["transactions"])
        d["asp"] = safe_div(d["sales_revenue"], d["units_sold"])
        d["return_rate_value"] = safe_div(d["returns_value"], d["sales_revenue"])
        d["return_rate_units"] = safe_div(d["returned_units"], d["units_sold"])
        d["promo_revenue_share"] = safe_div(d["promo_sales_revenue"], d["sales_revenue"])
        out.append(d)
    return out[0], out[1]


def headline_table(py: dict, cy: dict, periods: Periods) -> pd.DataFrame:
    rows = []
    for key, label, kind, sign in HEADLINE_METRICS:
        a, b = py[key], cy[key]
        change = b - a
        rows.append({
            "metric": key, "label": label, "unit": {"money": "EUR", "count": "count", "ratio": "EUR or units",
                                                     "pct": "ratio (0-1)"}[kind],
            periods.label_py: a, periods.label_cy: b, "change": change,
            "yoy_pct": yoy_pct(b, a) if kind != "pct" else np.nan,
            "change_pp": 100.0 * change if kind == "pct" else np.nan,
            "contribution_pp": (100.0 * sign * change / py["net_revenue"]) if sign is not None else np.nan,
        })
    return pd.DataFrame(rows)


def weekly_trend(wk: pd.DataFrame, total_py_net: float, rolling: int) -> pd.DataFrame:
    w = wk.sort_values("retail_week").reset_index(drop=True).copy()
    w["net_revenue_change"] = w["net_revenue_cy"] - w["net_revenue_py"]
    w["net_revenue_yoy_pct"] = yoy_pct(w["net_revenue_cy"], w["net_revenue_py"])
    w["sales_revenue_yoy_pct"] = yoy_pct(w["sales_revenue_cy"], w["sales_revenue_py"])
    w["transactions_yoy_pct"] = yoy_pct(w["transactions_cy"], w["transactions_py"])
    w["returns_value_change"] = w["returns_value_cy"] - w["returns_value_py"]
    w["contribution_pp"] = 100.0 * w["net_revenue_change"] / total_py_net
    w["cumulative_change"] = w["net_revenue_change"].cumsum()
    w["cumulative_yoy_pct"] = yoy_pct(w["net_revenue_cy"].cumsum(), w["net_revenue_py"].cumsum())
    w[f"rolling_{rolling}w_yoy_pct"] = yoy_pct(w["net_revenue_cy"].rolling(rolling).sum(),
                                               w["net_revenue_py"].rolling(rolling).sum())
    w["share_of_change"] = w["net_revenue_change"] / w["net_revenue_change"].sum()
    return w


def sustained_onset(values: pd.Series, weeks: pd.Series) -> int | None:
    """First week from which the series stays below zero until the end (None if it ends above zero)."""
    v = values.to_numpy()
    if len(v) == 0 or not v[-1] < 0:
        return None
    i = len(v) - 1
    while i > 0 and v[i - 1] < 0:
        i -= 1
    return int(weeks.iloc[i])


def step_test(y: np.ndarray, min_seg: int) -> dict:
    """Best single split of a series into two constant levels (least squares) vs a straight line."""
    n = len(y)
    x = np.arange(n, dtype=float)
    sst = float(((y - y.mean()) ** 2).sum())
    best = None
    for k in range(min_seg, n - min_seg + 1):
        a, b = y[:k], y[k:]
        sse = float(((a - a.mean()) ** 2).sum() + ((b - b.mean()) ** 2).sum())
        if best is None or sse < best[0] - 1e-12:
            best = (sse, k, a.mean(), b.mean())
    slope, intercept = np.polyfit(x, y, 1)
    sse_lin = float(((y - (slope * x + intercept)) ** 2).sum())
    r = np.corrcoef(x, y)[0, 1] if n > 2 else np.nan
    from scipy import stats
    t_p = stats.pearsonr(x, y).pvalue if n > 2 else np.nan
    return {"split_index": best[1], "mean_before": best[2], "mean_after": best[3], "step": best[3] - best[2],
            "r2_step": 1 - best[0] / sst if sst else np.nan, "r2_linear": 1 - sse_lin / sst if sst else np.nan,
            "slope_per_week": slope, "linear_r": r, "linear_p": t_p}


def trend_profile(w: pd.DataFrame, cfg_trend: dict) -> dict:
    rolling = cfg_trend["rolling_weeks"]
    yo = w["net_revenue_yoy_pct"].to_numpy(dtype=float)
    st = step_test(yo, cfg_trend["step_min_segment_weeks"])
    split_week = int(w["retail_week"].iloc[st["split_index"]])
    total = float(w["net_revenue_change"].sum())
    neg = w[w["net_revenue_change"] < 0]
    top = w.nsmallest(cfg_trend["top_weeks"], ["net_revenue_change"])
    half = len(w) // 2
    first, second = w.iloc[:half], w.iloc[half:]
    share_neg = len(neg) / len(w)
    abrupt = (abs(st["step"]) >= cfg_trend["abrupt_min_step_pp"] and st["r2_step"] > st["r2_linear"]
              and st["r2_step"] >= cfg_trend["step_min_r2"])
    if abrupt:
        shape = "a step change"
    elif st["linear_p"] < 0.05 and st["slope_per_week"] < 0:
        shape = "a gradual deterioration"
    elif share_neg >= 0.75:
        shape = "a persistent decline with no clear trend within the period"
    else:
        shape = "no clear time pattern"
    return {
        "weeks": len(w), "weeks_negative": len(neg), "share_weeks_negative": share_neg,
        "persistence": "persistent" if share_neg >= 0.75 else ("mostly negative" if share_neg >= 0.5 else "intermittent"),
        "first_negative_week": int(neg["retail_week"].min()) if len(neg) else None,
        "sustained_onset_week_rolling": sustained_onset(w[f"rolling_{rolling}w_yoy_pct"].fillna(0), w["retail_week"]),
        "sustained_onset_week_weekly": sustained_onset(w["net_revenue_yoy_pct"], w["retail_week"]),
        "top_negative_weeks": [int(x) for x in top["retail_week"]],
        "top_negative_weeks_change": float(top["net_revenue_change"].sum()),
        "top_negative_weeks_share": float(top["net_revenue_change"].sum() / total) if total else np.nan,
        "first_half_yoy_pct": float(yoy_pct(first["net_revenue_cy"].sum(), first["net_revenue_py"].sum())),
        "second_half_yoy_pct": float(yoy_pct(second["net_revenue_cy"].sum(), second["net_revenue_py"].sum())),
        "first_half_weeks": f"{int(first['retail_week'].min())}-{int(first['retail_week'].max())}",
        "second_half_weeks": f"{int(second['retail_week'].min())}-{int(second['retail_week'].max())}",
        "step_split_week": split_week, "step_mean_before_pct": st["mean_before"], "step_mean_after_pct": st["mean_after"],
        "step_pp": st["step"], "r2_step": st["r2_step"], "r2_linear": st["r2_linear"],
        "slope_pp_per_week": st["slope_per_week"], "slope_p_value": st["linear_p"], "shape": shape,
    }


def full_year_context(ew: pd.DataFrame, periods: Periods, rolling: int) -> pd.DataFrame:
    """Weekly YoY for all 52 weeks of the current year (context: did the decline start before H2?)."""
    cy = ew[(ew["retail_year"] == periods.cy_year) & (ew["is_comparable_week"] == 1)][
        ["retail_week", "retail_week_key", "prior_year_week_key", "net_revenue", "transactions"]]
    py = ew[["retail_week_key", "net_revenue", "transactions"]].rename(
        columns={"retail_week_key": "prior_year_week_key", "net_revenue": "net_revenue_py", "transactions": "transactions_py"})
    m = cy.merge(py, on="prior_year_week_key", how="inner").rename(
        columns={"net_revenue": "net_revenue_cy", "transactions": "transactions_cy"}).sort_values("retail_week")
    m["net_revenue_yoy_pct"] = yoy_pct(m["net_revenue_cy"], m["net_revenue_py"])
    m[f"rolling_{rolling}w_yoy_pct"] = yoy_pct(m["net_revenue_cy"].rolling(rolling).sum(),
                                               m["net_revenue_py"].rolling(rolling).sum())
    m["transactions_yoy_pct"] = yoy_pct(m["transactions_cy"], m["transactions_py"])
    m["half"] = np.where(m["retail_week"] >= periods.week_from, "H2", "H1")
    return m.reset_index(drop=True)


def check_headline_against_phase4(py: dict, cy: dict, facts: pd.DataFrame, bench: pd.DataFrame, periods: Periods,
                       tol: dict) -> pd.DataFrame:
    """Recomputed headline vs (a) an independent path straight from the facts and (b) the Phase 4 benchmark."""
    b = bench.set_index("metric_name")
    f = facts.set_index("retail_year")
    yoy = 100.0 * (cy["net_revenue"] / py["net_revenue"] - 1)
    rows = []

    def add(name, value, reference, source, tolerance):
        diff = abs(value - reference)
        rows.append({"check": name, "recomputed": value, "reference": reference, "abs_difference": diff,
                     "tolerance": tolerance, "reference_source": source, "status": "PASS" if diff <= tolerance else "FAIL"})

    src = str(bench["source_file"].iloc[0])
    add(f"{periods.label_py} net revenue vs Phase 4", py["net_revenue"],
        float(b.loc[f"h2_{periods.py_year}_net_revenue", "actual_value"]), src, tol["eur"])
    add(f"{periods.label_cy} net revenue vs Phase 4", cy["net_revenue"],
        float(b.loc[f"h2_{periods.cy_year}_net_revenue", "actual_value"]), src, tol["eur"])
    add("H2 YoY % vs Phase 4", yoy, float(b.loc["h2_yoy_pct", "actual_value"]), src, tol["yoy_pct_points"])
    add(f"{periods.label_py} net revenue vs direct fact query", py["net_revenue"], float(f.loc[periods.py_year, "net_revenue"]),
        "diag.v_h2_headline_from_facts", tol["eur"])
    add(f"{periods.label_cy} net revenue vs direct fact query", cy["net_revenue"], float(f.loc[periods.cy_year, "net_revenue"]),
        "diag.v_h2_headline_from_facts", tol["eur"])
    for key, t in (("sales_revenue", tol["eur"]), ("returns_value", tol["eur"]), ("transactions", 0), ("units_sold", 0)):
        for year, d in ((periods.py_year, py), (periods.cy_year, cy)):
            add(f"H2 {year} {key} vs direct fact query", d[key], float(f.loc[year, key]), "diag.v_h2_headline_from_facts", t)
    return pd.DataFrame(rows)


def cluster_weekly(sw: pd.DataFrame, cluster: list[str], rolling: int) -> pd.DataFrame:
    """Weekly YoY of a group of stores against the rest of the estate (same weeks, same definitions)."""
    sw = sw.assign(group=np.where(sw["store_id"].isin(cluster), "cluster", "rest"))
    g = sw.groupby(["retail_week", "group"])[["net_revenue_cy", "net_revenue_py", "transactions_cy",
                                               "transactions_py"]].sum().unstack("group")
    out = pd.DataFrame({"retail_week": g.index})
    for grp in ("cluster", "rest"):
        cyv, pyv = g[("net_revenue_cy", grp)].to_numpy(), g[("net_revenue_py", grp)].to_numpy()
        out[f"{grp}_net_revenue_yoy_pct"] = yoy_pct(cyv, pyv)
        out[f"{grp}_transactions_yoy_pct"] = yoy_pct(g[("transactions_cy", grp)].to_numpy(), g[("transactions_py", grp)].to_numpy())
        out[f"{grp}_rolling_{rolling}w_yoy_pct"] = yoy_pct(pd.Series(cyv).rolling(rolling).sum().to_numpy(),
                                                           pd.Series(pyv).rolling(rolling).sum().to_numpy())
        out[f"{grp}_net_revenue_change"] = cyv - pyv
    out.attrs["cluster"] = cluster
    return out
