"""Small, transparent statistical helpers (no black boxes): change points, ramps, DiD, resampling."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd


def step_changepoint(y: np.ndarray, min_seg: int) -> dict:
    """Single mean shift minimising squared error. Returns index of the first 'after' point."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    cs, cs2 = np.cumsum(y), np.cumsum(y ** 2)
    best = None
    for k in range(min_seg, n - min_seg + 1):
        s1, s2 = cs[k - 1], cs[-1] - cs[k - 1]
        q1, q2 = cs2[k - 1], cs2[-1] - cs2[k - 1]
        sse = (q1 - s1 ** 2 / k) + (q2 - s2 ** 2 / (n - k))
        if best is None or sse < best[0] - 1e-12:
            best = (sse, k)
    sse, k = best
    sst = float(((y - y.mean()) ** 2).sum())
    return {"index": k, "mean_before": float(y[:k].mean()), "mean_after": float(y[k:].mean()),
            "shift": float(y[k:].mean() - y[:k].mean()), "sse": float(sse), "r2": 1 - sse / sst if sst else np.nan,
            "bic": n * np.log(sse / n) + 3 * np.log(n)}


def ramp_fit(y: np.ndarray, max_ramp: int, min_seg: int) -> dict:
    """Level a before, level b after, linear transition of length L (0 = step) starting at t0. Grid search."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    t = np.arange(n)
    best = None
    for L in range(0, max_ramp + 1, 1):
        for t0 in range(min_seg, n - min_seg - L + 1):
            x = np.clip((t - t0) / L, 0, 1) if L > 0 else (t >= t0).astype(float)
            X = np.column_stack([np.ones(n), x])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            sse = float(((y - X @ coef) ** 2).sum())
            if best is None or sse < best[0] - 1e-9:
                best = (sse, L, t0, coef)
    sse, L, t0, coef = best
    return {"ramp_days": int(L), "start_index": int(t0), "end_index": int(t0 + L), "level_before": float(coef[0]),
            "level_after": float(coef[0] + coef[1]), "sse": sse, "bic": n * np.log(sse / n) + 4 * np.log(n)}


def linear_fit(y: np.ndarray) -> dict:
    y = np.asarray(y, dtype=float)
    n = len(y)
    x = np.arange(n)
    slope, intercept = np.polyfit(x, y, 1)
    sse = float(((y - (slope * x + intercept)) ** 2).sum())
    return {"slope": float(slope), "sse": sse, "bic": n * np.log(sse / n) + 2 * np.log(n)}


def did(treated_pre: np.ndarray, treated_post: np.ndarray, control_pre: np.ndarray, control_post: np.ndarray) -> float:
    return float((np.mean(treated_post) - np.mean(treated_pre)) - (np.mean(control_post) - np.mean(control_pre)))


def pre_trend(gap: pd.Series) -> dict:
    """Slope of the treated-minus-control gap over the pre-period (parallel-trends check)."""
    from scipy import stats
    x = np.arange(len(gap))
    res = stats.linregress(x, gap.to_numpy(dtype=float))
    return {"slope_per_week": float(res.slope), "p_value": float(res.pvalue), "r": float(res.rvalue)}


def bootstrap_ci(values: np.ndarray, stat, reps: int, seed: int, alpha: float = 0.05) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    values = np.asarray(values)
    n = len(values)
    out = np.array([stat(values[rng.integers(0, n, n)]) for _ in range(reps)])
    return float(np.nanpercentile(out, 100 * alpha / 2)), float(np.nanpercentile(out, 100 * (1 - alpha / 2)))


def permutation_placebo(treated: list[str], pool: list[str], size: int, statistic) -> dict:
    """Placebo inference: the actual statistic (treated vs the whole pool) against the same statistic for every
    size-k group drawn from the pool (each vs the rest of the pool). One-sided: how often is a placebo as low?"""
    actual = statistic(treated, list(pool))
    placebo = np.array([statistic(list(g), [u for u in pool if u not in g])
                        for g in itertools.combinations(sorted(pool), size)])
    return {"actual": float(actual), "placebo_n": int(len(placebo)),
            "p_value_one_sided": float((np.sum(placebo <= actual) + 1) / (len(placebo) + 1)),
            "placebo_min": float(placebo.min()), "placebo_p05": float(np.percentile(placebo, 5)),
            "placebo_median": float(np.median(placebo))}


def robust_summary(values: list[float], central: float, max_rel: float) -> dict:
    v = np.asarray([x for x in values if x is not None and not np.isnan(x)], dtype=float)
    same_sign = bool((np.sign(v) == np.sign(central)).all()) if central else False
    within = bool((np.abs(v - central) <= max_rel * abs(central)).all()) if central else False
    return {"n_variants": int(len(v)), "min": float(v.min()), "max": float(v.max()), "central": float(central),
            "same_sign": same_sign, "within_band": within, "robust": same_sign and within}
