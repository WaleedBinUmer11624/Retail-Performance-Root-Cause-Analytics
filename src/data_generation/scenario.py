"""Hidden scenario behaviours (answer key inputs).

Each function turns a behavioural description from config/_hidden_scenario.yaml
into simulation inputs (multipliers, fill rates, probabilities). None of them
targets a revenue outcome: impacts are measured after the simulation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _week_of(weeks: pd.DataFrame, date: str) -> int:
    return int(np.searchsorted(weeks["week_start"].to_numpy(), np.datetime64(date), side="right") - 1)


def traffic_multiplier(scn: dict | None, stores, weeks, seed) -> np.ndarray:
    """B1: footfall multiplier [W, S]."""
    mult = np.ones((len(weeks), len(stores)))
    if not scn or "B1_suburban_traffic_decline" not in scn:
        return mult
    b = scn["B1_suburban_traffic_decline"]
    rng = np.random.default_rng(seed)
    w0 = _week_of(weeks, b["start_date"])
    for sid in b["stores"]:
        s = int(np.where(stores["store_id"] == sid)[0][0])
        long_run = rng.uniform(*b["traffic_multiplier_range"])
        ramp = int(rng.integers(b["ramp_weeks_range"][0], b["ramp_weeks_range"][1] + 1))
        w = np.arange(w0, len(weeks))
        progress = np.minimum(1.0, (w - w0 + 1) / ramp)
        noise = rng.lognormal(0, b["weekly_noise_sigma"], len(w))
        mult[w, s] = (1 - (1 - long_run) * progress) * noise
    return mult


def supplier_fill_rates(cfg, scn, products, weeks, seed) -> tuple[np.ndarray, np.ndarray]:
    """Order fill rate [W, P] and the B2-affected SKU mask [P]."""
    rng = np.random.default_rng(seed)
    inv = cfg["inventory"]
    suppliers = products["supplier_name"].to_numpy()
    uniq = np.unique(suppliers)
    sup_fill = np.clip(rng.normal(inv["supplier_fill_rate_mean"], inv["supplier_fill_rate_sd"],
                                  (len(weeks), len(uniq))), 0.80, 1.0)
    fill = sup_fill[:, np.searchsorted(uniq, suppliers)]
    affected = np.zeros(len(products), dtype=bool)
    if scn and "B2_supplier_disruption" in scn:
        b = scn["B2_supplier_disruption"]
        cat = products["category"] == b["category"]
        rank = products.loc[cat, "popularity"].rank(ascending=False, pct=True)
        top = pd.Series(False, index=products.index)
        top[rank.index] = rank <= b["sku_popularity_top_share"]
        affected = ((products["supplier_name"] == b["supplier"]) & cat & top).to_numpy()
        w_start, w_full, w_rec = (_week_of(weeks, b[k]) for k in ("start_date", "full_disruption_until", "recovery_until"))
        n_a = affected.sum()
        for w in range(w_start, min(w_rec, len(weeks) - 1) + 1):
            mean = b["fill_rate_during_mean"] if w <= w_full else b["fill_rate_recovery_mean"]
            fill[w, affected] = np.clip(rng.normal(mean, b["fill_rate_during_sd"], n_a), 0.02, 1.0)
    return fill, affected
