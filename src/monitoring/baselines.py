"""Leakage-free baselines for weekly monitoring.

Every function walks forward in time: the baseline for week t is built only from weeks strictly before t, and only
from weeks that were valid (not DQ-failed, not themselves anomalous). Anomalous weeks are kept out of later baselines
so that a sustained shift is not absorbed into "normal" after a few weeks; the alert then stays active until an analyst
resolves it (lifecycle status RESOLVED), which in a live system would re-admit the new level.

Baselines compared in the back-test (baseline_comparison.csv):
  B1 same retail week last year          (YoY ratio; handles seasonality; needs a prior year)
  B2 trailing 8-week mean of the level   (reacts to recent level; blind to seasonality)
  B3 trailing 8-week median of the level (as B2, robust to one bad week)
  B4 trailing 13-week median of the YoY  (seasonality handled by YoY, store trend by the median) with pooled MAD scale
  B5 trailing 13-week mean/SD of the YoY (classic rolling z-score)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAD_TO_SD = 1.4826


def robust_walk_forward(panel: pd.DataFrame, value: str = "value", trailing: int = 13, min_valid: int = 8,
                        lookback: int = 26, exclude_low: float = -2.0, exclude_high: float = 3.0,
                        pooled: bool = True, hold_release_weeks: int = 0, hold_release_z: float = -1.0) -> pd.DataFrame:
    """panel: columns entity, t, value, dq_fail (bool). Returns baseline, deviation, robust z and flags per row.

    For each week t (in order): for each entity take the last `trailing` VALID weeks before t within `lookback` weeks;
    baseline = their median; the entity's MAD = median absolute deviation of those weeks. The scale is the pooled
    median of the entities' MADs (or the entity's own MAD when pooled=False) times 1.4826. A week becomes invalid for
    later baselines when its DQ gate failed or its z is anomalous: z <= exclude_low on the adverse side (a stricter
    guard, so a sustained deterioration is not absorbed into "normal") or z >= exclude_high on the other side.

    Hold (hold_release_weeks > 0): once a week is anomalous on the adverse side, the entity's baseline is FROZEN: no
    later week enters it until `hold_release_weeks` consecutive weeks are back above `hold_release_z`. Without the
    hold, the milder weeks of a sustained shift (z between exclude_low and 0) would re-enter and drag the baseline
    down towards the new level, so a real step would slowly look normal (baseline drift).
    """
    p = panel.sort_values(["t", "entity"]).reset_index(drop=True)
    p["baseline"] = np.nan
    p["entity_mad"] = np.nan
    p["scale"] = np.nan
    p["n_valid"] = 0
    p["baseline_frozen"] = False
    valid: dict = {}   # entity -> list of (t, value) valid history
    hold: dict = {}    # entity -> consecutive recovered weeks while frozen (None = not frozen)
    p["baseline_hold"] = False
    for t in sorted(p["t"].unique()):
        idx = p.index[p["t"] == t]
        mads = {}
        for i in idx:
            e = p.at[i, "entity"]
            hist = [v for (tt, v) in valid.get(e, []) if t - lookback <= tt < t][-trailing:]
            if len(hist) < min_valid and len(valid.get(e, [])) >= min_valid:
                # a long anomaly has pushed every valid week out of the lookback: keep the last valid baseline
                # (frozen) instead of dropping the alert; an analyst resolving the alert would reset it.
                hist = [v for (tt, v) in valid[e] if tt < t][-trailing:]
                p.at[i, "baseline_frozen"] = True
            p.at[i, "n_valid"] = len(hist)
            if len(hist) >= min_valid:
                b = float(np.median(hist))
                mad = float(np.median(np.abs(np.array(hist) - b)))
                p.at[i, "baseline"], p.at[i, "entity_mad"] = b, mad
                mads[i] = mad
        if mads:
            pooled_mad = float(np.median(list(mads.values())))
            for i, mad in mads.items():
                s = MAD_TO_SD * (pooled_mad if pooled else mad)
                p.at[i, "scale"] = s if s > 0 else np.nan
        for i in idx:
            e, v = p.at[i, "entity"], p.at[i, value]
            dev = v - p.at[i, "baseline"] if pd.notna(p.at[i, "baseline"]) else np.nan
            z = dev / p.at[i, "scale"] if pd.notna(dev) and pd.notna(p.at[i, "scale"]) else np.nan
            dq_bad = bool(p.at[i, "dq_fail"]) or pd.isna(v)
            bad = dq_bad or (pd.notna(z) and (z <= exclude_low or z >= exclude_high))
            if hold_release_weeks > 0 and not dq_bad and pd.notna(z):
                if z <= exclude_low:
                    hold[e] = 0
                elif hold.get(e) is not None:
                    hold[e] = hold[e] + 1 if z > hold_release_z else 0
                    if hold[e] >= hold_release_weeks:
                        hold[e] = None
                    else:
                        bad = True
            p.at[i, "baseline_hold"] = hold.get(e) is not None
            if not bad:
                valid.setdefault(e, []).append((t, v))
    p["deviation"] = p[value] - p["baseline"]
    p["z"] = p["deviation"] / p["scale"]
    p["baseline_ok"] = p["baseline"].notna()
    return p


def rolling_mean_sd(panel: pd.DataFrame, value: str = "value", trailing: int = 13, min_valid: int = 8) -> pd.DataFrame:
    """Classic rolling z-score (B5): mean and SD of the entity's previous `trailing` weeks (DQ-failed weeks dropped)."""
    p = panel.sort_values(["entity", "t"]).copy()
    v = p[value].where(~p["dq_fail"])
    g = v.groupby(p["entity"])
    p["roll_mean"] = g.transform(lambda s: s.shift(1).rolling(trailing, min_periods=min_valid).mean())
    p["roll_sd"] = g.transform(lambda s: s.shift(1).rolling(trailing, min_periods=min_valid).std())
    p["z_roll"] = (p[value] - p["roll_mean"]) / p["roll_sd"]
    return p


def trailing_level(panel: pd.DataFrame, value: str, weeks: int, how: str = "mean", min_periods: int | None = None) -> pd.Series:
    """Trailing mean or median of the level over the previous `weeks` weeks (B2, B3); shift(1) keeps week t out."""
    p = panel.sort_values(["entity", "t"])
    v = p[value].where(~p["dq_fail"])
    mp = min_periods or max(2, weeks // 2)
    f = (lambda s: s.shift(1).rolling(weeks, min_periods=mp).mean()) if how == "mean" else \
        (lambda s: s.shift(1).rolling(weeks, min_periods=mp).median())
    return v.groupby(p["entity"]).transform(f).reindex(panel.index)


def consecutive(flag: pd.Series, entity: pd.Series, t: pd.Series) -> pd.Series:
    """Length of the current run of consecutive True weeks (per entity, in week order); 0 where False."""
    df = pd.DataFrame({"f": flag.astype(bool).values, "e": entity.values, "t": t.values}, index=flag.index).sort_values(["e", "t"])
    out = np.zeros(len(df), dtype=int)
    prev_e, prev_t, run = None, None, 0
    for k, (f, e, tt) in enumerate(zip(df["f"], df["e"], df["t"])):
        if e != prev_e:
            run = 0
        elif prev_t is not None and tt != prev_t + 1:
            run = 0
        run = run + 1 if f else 0
        out[k] = run
        prev_e, prev_t = e, tt
    return pd.Series(out, index=df.index).reindex(flag.index)
