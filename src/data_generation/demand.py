"""Expected demand (lines per store-SKU-week) and the seasonality model.

Inputs: generator config, dimension frames, ranging and activity masks. Output: a [week, store, SKU]
array of expected sales lines.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _circ_gauss(week: np.ndarray, centre: float, width: float) -> np.ndarray:
    # Distance wraps around the year, so a peak near week 52 also lifts weeks 1-2.
    d = np.abs(week - centre)
    d = np.minimum(d, 52 - d)
    return np.exp(-0.5 * (d / width) ** 2)


def seasonality_index(cfg: dict) -> dict[str, np.ndarray]:
    """Category -> index over retail weeks 1..52 (array position 0..51), mean 1."""
    s = cfg["seasonality"]
    wk = np.arange(1, 53, dtype=float)
    out = {}
    for cat, c in cfg["categories"].items():
        p = c["season"]
        idx = (
            p["off_season_base"]
            + p["q4_amp"] * _circ_gauss(wk, s["q4_centre_week"], s["q4_width_weeks"])
            + p["bf_amp"] * (wk == s["black_friday_week"])
            + p["summer_amp"] * _circ_gauss(wk, s["summer_centre_week"], s["summer_width_weeks"])
            + p["bts_amp"] * _circ_gauss(wk, s["bts_centre_week"], s["bts_width_weeks"])
            - p["jan_dip"] * np.isin(wk, s["jan_dip_weeks"])
        )
        idx = np.maximum(idx, 0.05)
        out[cat] = idx / idx.mean()
    return out


def lognormal_mean1(rng, sigma, size):
    """Lognormal draws with mean exactly 1, so noise adds spread without shifting the level."""
    return rng.lognormal(-0.5 * sigma**2, sigma, size)


def expected_lines(cfg, stores, products, weeks, ranged, live, store_mask, seed, week_share,
                   promo_mult=None, traffic_mult=None, with_noise=True, include_drift=True):
    """Expected demand lines E[W,S,P].

    Built multiplicatively from: store level, store drift, chain and store-week
    shocks, category share, SKU popularity, seasonality, market trend, price
    elasticity to the 2025 price review, promotions, (scenario) traffic, and
    cell noise.

    The same `seed` is used for every call so that the actual view and the
    planning views share identical store draws:
      with_noise=False              -> no weekly or cell shocks (planning view)
      include_drift=False           -> Finance plan does not know future store trends
    """
    rng = np.random.default_rng(seed)
    v = cfg["volume"]
    W, S, P = len(weeks), len(stores), len(products)
    t_years = (weeks["week_idx"].to_numpy() + 0.5) / 52.0

    store_level = np.array([v["format_factor"][f] * v["region_factor"][r]
                            for f, r in zip(stores["store_format"], stores["region"])])
    store_level = store_level * lognormal_mean1(rng, v["store_factor_sigma"], S)  # location quality (known)
    drift = rng.normal(0, v["store_drift_sigma_per_year"], S)
    chain_noise = lognormal_mean1(rng, v["chain_week_noise_sigma"], W)
    store_week_noise = lognormal_mean1(rng, v["store_week_noise_sigma"], (W, S))
    cell_noise = lognormal_mean1(rng, v["cell_noise_sigma"], (W, S, P))
    store_trend = np.exp(drift[None, :] * t_years[:, None]) if include_drift else np.ones((W, S))
    if not with_noise:
        chain_noise = np.ones(W)
        store_week_noise = np.ones((W, S))
        cell_noise = np.ones((W, S, P))

    # category share allocated over the SKUs ranged in each store AND live that
    # week, so a launch cannibalises its category and a range exit hands its
    # demand to the remaining SKUs (category demand is not created by range
    # changes).
    cats = products["category"].to_numpy()
    pop = products["popularity"].to_numpy()
    alloc = np.zeros((W, S, P))
    for cat, c in cfg["categories"].items():
        m = cats == cat
        wts = ranged[None, :, m] * (pop[m] * live[:, m])[:, None, :]  # [W,S,Pc]
        denom = wts.sum(axis=2, keepdims=True)
        alloc[:, :, m] = c["line_share"] * np.divide(wts, denom, out=np.zeros_like(wts), where=denom > 0)

    # seasonality per product-week
    sidx = seasonality_index(cfg)
    rw = weeks["retail_week"].to_numpy() - 1
    season = np.zeros((W, P))
    for cat in cfg["categories"]:
        m = cats == cat
        season[:, m] = sidx[cat][rw][:, None]

    # market trend and price elasticity to the annual price review
    trend = (1 + v["market_volume_trend_per_year"]) ** t_years
    price_ratio = (products["list_price_2025"] / products["list_price_2024"]).to_numpy()
    is_2025 = (weeks["week_start"] >= pd.Timestamp("2024-12-30")).to_numpy()
    price_vol = np.where(is_2025[:, None], price_ratio[None, :] ** cfg["pricing"]["price_elasticity"], 1.0)

    E = (v["base_weekly_lines_standard_store"]
         * (store_level[None, :] * store_trend * chain_noise[:, None] * store_week_noise
            * week_share[:, None])[:, :, None]
         * alloc
         * (season * trend[:, None] * price_vol)[:, None, :]
         * cell_noise)
    if promo_mult is not None:
        E *= promo_mult
    if traffic_mult is not None:
        E *= traffic_mult[:, :, None]
    E *= store_mask[None, :, None]  # stores outside this run have no demand
    return E
