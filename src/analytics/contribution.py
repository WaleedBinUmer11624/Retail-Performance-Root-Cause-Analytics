"""Contribution analysis and the exact revenue bridge.

BRD 5.2
    YoY %                 = (current / prior - 1) x 100
    Contribution (pp)     = segment EUR change / estate prior-period net revenue x 100
    Share of decline      = segment EUR change / estate EUR change
BRD 5.1 identity
    Sales Revenue = Transactions x UPT x ASP;  Net Revenue = Sales Revenue - Returns Value

The Sales Revenue change is split with the three-factor Shapley decomposition: each factor's effect is
the average of its marginal effect over all 6 orders of changing the factors. The effects add up to
the change exactly (Shapley efficiency), so there is no unexplained residual; the residual column in
the bridge only carries floating-point rounding and is tested to be below 1 cent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def safe_div(n, d):
    """n / d with 0 or missing denominators returning NaN (scalar or array-like), never raising."""
    n_arr = np.asarray(n, dtype=float)
    d_arr = np.asarray(d, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where((d_arr == 0) | np.isnan(d_arr), np.nan, n_arr / np.where(d_arr == 0, 1.0, d_arr))
    if np.ndim(out) == 0:
        return float(out)
    if isinstance(n, pd.Series):
        return pd.Series(out, index=n.index)
    return out


def yoy_pct(cy, py):
    r = safe_div(cy, py)
    return 100.0 * (r - 1.0)


def contribution_table(df: pd.DataFrame, key: str | list[str], total_py: float, total_change: float,
                       py_col: str = "net_revenue_py", cy_col: str = "net_revenue_cy") -> pd.DataFrame:
    """Add change, YoY %, contribution (pp), share of change and a deterministic rank.

    Rank 1 = most negative EUR change; ties are broken by the key so the ranking never depends on row order.
    """
    keys = [key] if isinstance(key, str) else list(key)
    out = df.copy()
    out["net_revenue_change"] = out[cy_col] - out[py_col]
    out["net_revenue_yoy_pct"] = yoy_pct(out[cy_col], out[py_col])
    out["contribution_pp"] = 100.0 * out["net_revenue_change"] / total_py
    out["share_of_change"] = out["net_revenue_change"] / total_change if total_change else np.nan
    out = out.sort_values(["net_revenue_change"] + keys, kind="mergesort").reset_index(drop=True)
    out["contribution_rank"] = np.arange(1, len(out) + 1)
    by_pct = out.sort_values(["net_revenue_yoy_pct"] + keys, kind="mergesort")
    out.loc[by_pct.index, "yoy_pct_rank"] = np.arange(1, len(out) + 1)
    out["yoy_pct_rank"] = out["yoy_pct_rank"].astype(int)
    return out


# ----------------------------------------------------------------------------- Shapley
def shapley_three(t0, u0, p0, t1, u1, p1):
    """Exact Shapley split of T1*U1*P1 - T0*U0*P0 into (effect_T, effect_U, effect_P). Works on arrays."""
    t0, u0, p0, t1, u1, p1 = (np.asarray(v, dtype=float) for v in (t0, u0, p0, t1, u1, p1))
    e_t = (t1 - t0) * ((u0 * p0 + u1 * p1) / 3.0 + (u0 * p1 + u1 * p0) / 6.0)
    e_u = (u1 - u0) * ((t0 * p0 + t1 * p1) / 3.0 + (t0 * p1 + t1 * p0) / 6.0)
    e_p = (p1 - p0) * ((t0 * u0 + t1 * u1) / 3.0 + (t0 * u1 + t1 * u0) / 6.0)
    return e_t, e_u, e_p


def shapley_two(u0, p0, u1, p1):
    """Exact Shapley split of U1*P1 - U0*P0 (used for AOV = UPT x ASP)."""
    return (u1 - u0) * (p0 + p1) / 2.0, (p1 - p0) * (u0 + u1) / 2.0


def bridge_effects(t0, units0, sales0, returns0, t1, units1, sales1, returns1) -> dict:
    """Net revenue bridge from additive components (transactions, units, sales, returns)."""
    u0, u1 = units0 / t0, units1 / t1
    p0, p1 = sales0 / units0, sales1 / units1
    e_t, e_u, e_p = shapley_three(t0, u0, p0, t1, u1, p1)
    sales_change = sales1 - sales0
    residual = sales_change - (e_t + e_u + e_p)
    ret = -(returns1 - returns0)
    net_change = (sales1 - returns1) - (sales0 - returns0)
    return {"transactions_effect": float(e_t), "upt_effect": float(e_u), "asp_effect": float(e_p),
            "shapley_residual": float(residual), "sales_revenue_change": float(sales_change),
            "returns_effect": float(ret), "net_revenue_change": float(net_change),
            "reconciliation_difference": float(net_change - (e_t + e_u + e_p + residual + ret)),
            "transactions_py": t0, "transactions_cy": t1, "upt_py": u0, "upt_cy": u1, "asp_py": p0, "asp_cy": p1}


def bridge_table(py: dict, cy: dict, label_py: str, label_cy: str) -> pd.DataFrame:
    """Waterfall rows from prior-year to current-year net revenue."""
    e = bridge_effects(py["transactions"], py["units_sold"], py["sales_revenue"], py["returns_value"],
                       cy["transactions"], cy["units_sold"], cy["sales_revenue"], cy["returns_value"])
    base = py["net_revenue"]
    steps = [
        (f"{label_py} Net Revenue", base, "total", "Measured"),
        ("Transactions effect", e["transactions_effect"], "effect", "Shapley share of the Sales Revenue change"),
        ("UPT effect", e["upt_effect"], "effect", "Shapley share of the Sales Revenue change"),
        ("ASP effect", e["asp_effect"], "effect", "Shapley share of the Sales Revenue change"),
        ("Interaction / residual", e["shapley_residual"], "effect", "Zero by construction (floating-point only)"),
        ("Returns effect", e["returns_effect"], "effect", "Minus the change in Returns Value"),
        (f"{label_cy} Net Revenue", cy["net_revenue"], "total", "Measured"),
    ]
    rows, running = [], 0.0
    total_change = cy["net_revenue"] - base
    for name, value, kind, note in steps:
        if kind == "total":
            running = value
        else:
            running += value
        rows.append({"step": name, "value_eur": value, "kind": kind, "running_total_eur": running,
                     "contribution_pp": 100.0 * value / base if kind == "effect" else np.nan,
                     "share_of_change": value / total_change if kind == "effect" and total_change else np.nan,
                     "method_note": note})
    df = pd.DataFrame(rows)
    df.attrs["effects"] = e
    return df


def segment_bridges(seg: pd.DataFrame) -> pd.DataFrame:
    """Python recomputation of the per-segment bridge (independent of the SQL view)."""
    t0, t1 = seg["transactions_py"].astype(float), seg["transactions_cy"].astype(float)
    u0 = safe_div(seg["units_sold_py"], t0)
    u1 = safe_div(seg["units_sold_cy"], t1)
    p0 = safe_div(seg["sales_revenue_py"], seg["units_sold_py"])
    p1 = safe_div(seg["sales_revenue_cy"], seg["units_sold_cy"])
    e_t, e_u, e_p = shapley_three(t0, u0, p0, t1, u1, p1)
    out = seg.copy()
    out["transactions_effect"], out["upt_effect"], out["asp_effect"] = e_t, e_u, e_p
    out["returns_effect"] = -(seg["returns_value_cy"] - seg["returns_value_py"])
    out["net_revenue_change"] = seg["net_revenue_cy"] - seg["net_revenue_py"]
    out["shapley_residual"] = (seg["sales_revenue_cy"] - seg["sales_revenue_py"]) - (e_t + e_u + e_p)
    out["reconciliation_difference"] = out["net_revenue_change"] - (e_t + e_u + e_p + out["returns_effect"] +
                                                                   out["shapley_residual"])
    return out


def decline_cluster(df: pd.DataFrame, key: str, cover: float) -> list[str]:
    """Smallest set of declining segments (largest decline first) whose decline covers `cover` of the total change."""
    total = df["net_revenue_change"].sum()
    dec = df[df["net_revenue_change"] < 0].sort_values(["net_revenue_change", key], kind="mergesort")
    if total >= 0 or dec.empty:
        return []
    cum = dec["net_revenue_change"].cumsum() / total
    n = int((cum < cover).sum()) + 1
    return dec[key].head(n).tolist()
