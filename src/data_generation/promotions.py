"""Promotion calendar: chain-wide events, fact_promotions rows and demand multipliers.

Promotion mechanics (all parameters in config):
  uplift during promo      = 1 + elasticity * depth + display_effect
  pull-forward after promo = the next `pull_forward_weeks` weeks lose
                             pull_forward_share of the incremental units
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PromoEvent:
    """One planned promotion: category, type, week, depth and the SKUs and stores it covers."""
    category: str
    promo_type: str
    week_idx: int
    duration: int
    skus: np.ndarray         # product indices
    depths: np.ndarray       # depth per SKU
    stores: np.ndarray       # store indices participating
    elasticity: float
    display_effect: float
    pull_forward_share: float
    pull_forward_weeks: int


def _params(cfg: dict, category: str) -> dict:
    p = dict(cfg["promotions"]["default"])
    p.update(cfg["promotions"].get("overrides", {}).get(category, {}))
    return p


def _events_for_regime(category, p, weeks_range, live, cat_idx, pop, n_stores, rng, promo_type="Percent Off"):
    events = []
    first, last = weeks_range
    offset = int(rng.integers(0, p["cadence_weeks"]))
    for w in range(first + offset, last, p["cadence_weeks"]):
        cand = cat_idx[live[w, cat_idx]]
        if len(cand) == 0:
            continue
        k = max(1, int(round(p["sku_coverage"] * len(cat_idx))))
        k = min(k, len(cand))
        wts = np.sqrt(pop[cand])
        skus = rng.choice(cand, size=k, replace=False, p=wts / wts.sum())
        depth = float(rng.choice(p["depths"], p=p["depth_probs"]))
        stores = np.where(rng.random(n_stores) < p["store_participation"])[0]
        events.append(
            PromoEvent(category, promo_type, w, p["duration_weeks"], skus, np.full(k, depth), stores,
                       p["elasticity"], p["display_effect"], p["pull_forward_share"], p["pull_forward_weeks"])
        )
    return events


def plan_promotions(cfg, products, weeks, live, n_stores, seed, scenario_b3=None):
    """Return the list of PromoEvents. Baseline events are identical with or
    without the scenario; the scenario only replaces the affected category's
    events from its start week onwards (drawn from a separate random stream)."""
    rng = np.random.default_rng(seed)
    pop = products["popularity"].to_numpy()
    n_weeks = len(weeks)
    clear = cfg["promotions"]["clearance"]
    clear_weeks = set(weeks.index[weeks["retail_week"].isin(clear["retail_weeks"])])

    events = []
    for cat in cfg["categories"]:
        cat_idx = products.index[products["category"] == cat].to_numpy()
        p = _params(cfg, cat)
        evs = _events_for_regime(cat, p, (0, n_weeks), live, cat_idx, pop, n_stores, rng)
        if cat == clear["category"]:
            evs = [e for e in evs if e.week_idx not in clear_weeks]
        events.extend(evs)

    # post-Christmas clearance
    cat_idx = products.index[products["category"] == clear["category"]].to_numpy()
    base = _params(cfg, clear["category"])
    for w in sorted(clear_weeks):
        cand = cat_idx[live[w, cat_idx]]
        k = int(round(clear["sku_coverage"] * len(cand)))
        skus = rng.choice(cand, size=k, replace=False)
        events.append(PromoEvent(clear["category"], "Clearance", w, 1, skus, rng.choice(clear["depths"], size=k),
                                 np.arange(n_stores), base["elasticity"], base["display_effect"], 0.0, 1))

    if scenario_b3:
        srng = np.random.default_rng(seed + 1)
        cat = scenario_b3["category"]
        start_w = int(np.searchsorted(weeks["week_start"].to_numpy(), np.datetime64(scenario_b3["start_date"])))
        keep = [e for e in events if not (e.category == cat and e.week_idx >= start_w)]
        p = _params(cfg, cat)
        p.update({k: scenario_b3[k] for k in ("cadence_weeks", "duration_weeks", "sku_coverage", "depths",
                                               "depth_probs", "pull_forward_share", "pull_forward_weeks")
                  if k in scenario_b3})
        cat_idx = products.index[products["category"] == cat].to_numpy()
        keep.extend(_events_for_regime(cat, p, (start_w, n_weeks), live, cat_idx, pop, n_stores, srng))
        events = keep

    events.sort(key=lambda e: (e.week_idx, e.category, e.promo_type))
    return events


def promo_arrays(events, ranged, n_weeks):
    """Build depth[W,S,P], event ref[W,S,P] and demand multiplier[W,S,P]."""
    S, P = ranged.shape
    depth = np.zeros((n_weeks, S, P))
    ref = np.full((n_weeks, S, P), -1, dtype=np.int32)
    mult = np.ones((n_weeks, S, P))
    for i, e in enumerate(events):
        sub_r = ranged[np.ix_(e.stores, e.skus)]
        for d in range(e.duration):
            w = e.week_idx + d
            if w >= n_weeks:
                break
            blk = np.where(sub_r, e.depths[None, :], 0.0)
            depth[w][np.ix_(e.stores, e.skus)] = np.where(sub_r, blk, depth[w][np.ix_(e.stores, e.skus)])
            ref[w][np.ix_(e.stores, e.skus)] = np.where(sub_r, i, ref[w][np.ix_(e.stores, e.skus)])
            uplift = 1 + e.elasticity * e.depths + e.display_effect
            mult[w][np.ix_(e.stores, e.skus)] *= np.where(sub_r, uplift[None, :], 1.0)
        # pull-forward dip in the following weeks
        inc = (e.elasticity * e.depths + e.display_effect) * e.duration
        dip = np.maximum(0.2, 1 - e.pull_forward_share * inc / e.pull_forward_weeks)
        for k in range(1, e.pull_forward_weeks + 1):
            w = e.week_idx + e.duration - 1 + k
            if w >= n_weeks:
                break
            mult[w][np.ix_(e.stores, e.skus)] *= np.where(sub_r, dip[None, :], 1.0)
    return depth, ref, mult


def build_fact_promotions(events, ranged, products, stores, weeks) -> pd.DataFrame:
    """One fact_promotions row per event, with ids PR00001 onwards in event order."""
    rows = []
    for i, e in enumerate(events):
        pid = f"PR{i + 1:05d}"
        start = weeks.loc[e.week_idx, "week_start"]
        end_w = min(e.week_idx + e.duration - 1, len(weeks) - 1)
        end = weeks.loc[end_w, "week_end"]
        pct = int(round(float(np.median(e.depths)) * 100))
        name = (f"{e.category} Clearance" if e.promo_type == "Clearance" else f"{e.category} {pct}% Off") + \
               f" wk{weeks.loc[e.week_idx, 'retail_week']} {weeks.loc[e.week_idx, 'retail_year']}"
        s_idx, k_idx = np.nonzero(ranged[np.ix_(e.stores, e.skus)])
        rows.append(pd.DataFrame({
            "promotion_id": pid,
            "promotion_name": name,
            "promotion_type": e.promo_type,
            "product_id": products["product_id"].to_numpy()[e.skus[k_idx]],
            "store_id": stores["store_id"].to_numpy()[e.stores[s_idx]],
            "start_date": start,
            "end_date": end,
            "discount_pct": np.round(e.depths[k_idx], 2),
        }))
    return pd.concat(rows, ignore_index=True)


def promotion_ids(events) -> np.ndarray:
    """Promotion ids in event order; must match build_fact_promotions."""
    return np.array([f"PR{i + 1:05d}" for i in range(len(events))])
