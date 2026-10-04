"""Analytical calibration: projected full-scale KPIs from the expected-demand model.

This does NOT generate the full dataset. It evaluates the noise-free demand
model for all 600 SKUs and multiplies by prices, so the BRD scale assumptions
(lines, revenue, basket, category mix) can be checked from a sample run.

Inputs: generator config and scenario config. Output: a dict of projected full-scale KPIs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import calendar_builder, demand, dimensions, promotions, scenario
from .config_loader import load_generator_config, load_hidden_scenario
from .generate_data import SEED_OFFSETS


def project_full_scale(cfg=None, scn=None) -> dict:
    """Noise-free expected volumes and revenue for all stores, with and without the scenario."""
    cfg = cfg or load_generator_config()
    scn = scn or load_hidden_scenario()
    seed = int(cfg["seed"])
    # Same seed offsets as the generator, so these projections match a real full run.
    sd = {k: seed + v * 1000 for k, v in SEED_OFFSETS.items()}
    weeks = calendar_builder.build_week_table(cfg)
    _, week_share = calendar_builder.build_day_weights(cfg, weeks)
    stores = dimensions.build_dim_store(cfg, np.random.default_rng(sd["store"]))
    products = dimensions.build_dim_product(cfg, np.random.default_rng(sd["product"]))
    ranged = dimensions.build_ranging(cfg, stores, products, np.random.default_rng(sd["ranging"]))
    live = dimensions.product_week_activity(products, weeks)
    full = np.ones(len(stores), dtype=bool)
    ev_b = promotions.plan_promotions(cfg, products, weeks, live, len(stores), sd["promo"])
    ev_a = promotions.plan_promotions(cfg, products, weeks, live, len(stores), sd["promo"],
                                      scenario_b3=scn["B3_home_kitchen_promotion_change"])
    depth_b, _, mult_b = promotions.promo_arrays(ev_b, ranged, len(weeks))
    depth_a, _, mult_a = promotions.promo_arrays(ev_a, ranged, len(weeks))
    traffic = scenario.traffic_multiplier(scn, stores, weeks, sd["traffic"])
    _, b2 = scenario.supplier_fill_rates(cfg, scn, products, weeks, sd["fill"])
    args = (cfg, stores, products, weeks, ranged, live, full, sd["demand"], week_share)
    E_a = demand.expected_lines(*args, promo_mult=mult_a, traffic_mult=traffic, with_noise=False)
    E_0 = demand.expected_lines(*args, promo_mult=mult_b, with_noise=False)

    cats = list(cfg["categories"])
    probs = np.array([cfg["categories"][c]["qty_probs"] for c in cats], float)
    probs /= probs.sum(1, keepdims=True)
    mq = (probs * np.arange(1, 5)).sum(1)[pd.Categorical(products["category"], categories=cats).codes]
    is25 = (weeks["week_start"] >= pd.Timestamp("2024-12-30")).to_numpy()
    price = np.where(is25[:, None], products["list_price_2025"].to_numpy(), products["list_price_2024"].to_numpy())
    ret = products["category"].map(cfg["returns"]["base_return_prob"]).to_numpy()

    def rev(E, depth):
        return E * mq * price[:, None, :] * (1 - depth)

    R_a, R_0 = rev(E_a, depth_a), rev(E_0, depth_b)
    lines_per_txn = 1 / cfg["volume"]["basket_new_transaction_prob"] * 0.94  # store-day truncation
    y24, h24, h25 = slice(0, 52), slice(26, 52), slice(78, 104)
    rev24 = R_a[y24].sum()
    lines = E_a[:105].sum()
    by_cat = pd.Series(R_a[y24].sum(axis=(0, 1)), index=products["category"]).groupby(level=0).sum() / rev24
    s_idx = stores.index[stores["store_id"].isin(scn["B4_faulty_batch_returns"]["stores"])].to_numpy()
    b4 = scn["B4_faulty_batch_returns"]
    b4_mask = ((products["category"] == b4["category"]) & products["subcategory"].isin(b4["subcategories"])).to_numpy()
    h25_rev = R_a[h25].sum()
    return {
        "projected_sales_lines_total": float(lines),
        "projected_transactions_total": float(lines / lines_per_txn),
        "projected_sales_revenue_2024": float(rev24),
        "projected_net_revenue_2024": float((R_a[y24] * (1 - ret)).sum()),
        "projected_aov": float(rev24 / (E_a[y24].sum() / lines_per_txn)),
        "projected_asp": float(rev24 / (E_a[y24] * mq).sum()),
        "category_revenue_share_2024": by_cat.round(3).to_dict(),
        "b2_affected_skus": int(b2.sum()),
        "b2_affected_share_of_h2_2025_revenue": float(R_a[h25][:, :, b2].sum() / h25_rev),
        "b4_affected_share_of_h2_2025_revenue": float(R_a[h25][:, s_idx][:, :, b4_mask].sum() / h25_rev),
        "expected_h2_change_excl_stock_and_returns_pct": float(100 * (R_a[h25].sum() / R_a[h24].sum() - 1)),
        "expected_h2_change_no_scenario_pct": float(100 * (R_0[h25].sum() / R_0[h24].sum() - 1)),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(project_full_scale(), indent=2))
