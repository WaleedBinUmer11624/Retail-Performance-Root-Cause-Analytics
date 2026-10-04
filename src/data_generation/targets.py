"""Weekly store targets (fact_targets), set by Finance before each retail year.

Method: Finance's planning model = expected demand with no random shocks,
no knowledge of future store trends or scenario events, the promotion plan
known at the time the budget was set, list prices, and normal return rates.
That planned net revenue is uplifted by the plan growth and a small planning
error per store and per week is added (budget phasing is never perfect).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_fact_targets(cfg, E_plan, mean_qty, promo_depth_base, stores, products, weeks, seed):
    """Finance targets from the planning-view demand, which knows no scenario or store drift."""
    rng = np.random.default_rng(seed)
    tc = cfg["targets"]
    n_w = cfg["calendar"]["inventory_weeks"]  # retail years 2024 and 2025 only
    is25 = (weeks["week_start"] >= pd.Timestamp("2024-12-30")).to_numpy()[:n_w]
    price = np.where(is25[:, None], products["list_price_2025"].to_numpy()[None, :],
                     products["list_price_2024"].to_numpy()[None, :])
    ret_p = products["category"].map(cfg["returns"]["base_return_prob"]).to_numpy()
    rev = (E_plan[:n_w] * mean_qty[None, None, :] * price[:, None, :]
           * (1 - promo_depth_base[:n_w]) * (1 - ret_p)[None, None, :]).sum(axis=2)  # [W,S]

    years = weeks["retail_year"].to_numpy()[:n_w]
    growth = np.array([tc["plan_growth"][int(y)] for y in years])
    store_err = {y: rng.lognormal(0, tc["store_plan_error_sigma"], len(stores)) for y in (2024, 2025)}
    serr = np.vstack([store_err[int(y)] for y in years])
    werr = rng.lognormal(0, tc["week_phasing_error_sigma"], rev.shape)
    target = np.round(rev * (1 + growth)[:, None] * serr * werr, -1)

    w_i, s_i = np.meshgrid(np.arange(n_w), np.arange(len(stores)), indexing="ij")
    return pd.DataFrame({
        "store_id": stores["store_id"].to_numpy()[s_i.ravel()],
        "retail_year": years[w_i.ravel()],
        "retail_week": weeks["retail_week"].to_numpy()[w_i.ravel()],
        "week_start_date": weeks["week_start"].dt.strftime("%Y-%m-%d").to_numpy()[w_i.ravel()],
        "week_end_date": weeks["week_end"].dt.strftime("%Y-%m-%d").to_numpy()[w_i.ravel()],
        "target_net_revenue": target.ravel(),
        "target_version": "V1",
        "target_set_date": [tc["set_dates"][int(y)] for y in years[w_i.ravel()]],
    }).sort_values(["store_id", "retail_year", "retail_week"]).reset_index(drop=True)
