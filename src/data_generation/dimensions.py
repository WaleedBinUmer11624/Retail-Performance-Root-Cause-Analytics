"""Dimension builders: dim_store, dim_product, store ranging and run-mode store selection.

Inputs: generator config and a seeded RNG per builder. Outputs: store and product frames and
boolean ranging and activity masks.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .reference_data import MANAGER_NAMES, SUBCATEGORY_NOUNS, VARIANTS

VAT_RATE = 0.23


def build_dim_store(cfg: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Store master with format attributes jittered +/-10% per store."""
    stores = {k: v for k, v in cfg["stores"].items() if k.startswith("S")}
    fmt_attr = cfg["stores"]["format_attributes"]
    rows = []
    for i, (sid, (name, town, county, region, fmt, open_year, lat, lon)) in enumerate(stores.items()):
        attr = fmt_attr[fmt]
        rows.append(
            {
                "store_id": sid,
                "store_name": name,
                "town": town,
                "county": county,
                "region": region,
                "store_format": fmt,
                "floor_area_m2": int(round(attr["floor_area_m2"] * rng.uniform(0.9, 1.1), -1)),
                "open_date": pd.Timestamp(year=open_year, month=int(rng.integers(3, 11)), day=int(rng.integers(1, 28))),
                "manager_name": MANAGER_NAMES[i % len(MANAGER_NAMES)],
                "headcount_fte": round(attr["headcount_fte"] * rng.uniform(0.9, 1.1), 1),
                "weekly_trading_hours": attr["weekly_trading_hours"],
                "latitude": lat,
                "longitude": lon,
            }
        )
    return pd.DataFrame(rows)


def _shelf_price(x: np.ndarray) -> np.ndarray:
    """Round a VAT-inclusive price to a retail price point ending in 9 (e.g. 12.49)."""
    return np.maximum(np.round(x * 10) / 10 - 0.01, 0.99)


def build_dim_product(cfg: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Product master: prices, costs, popularity, supplier, launch and discontinuation dates."""
    pcfg, price_cfg = cfg["products"], cfg["pricing"]
    start, end = pd.Timestamp(cfg["calendar"]["start_date"]), pd.Timestamp(cfg["calendar"]["end_date"])
    frames = []
    for cat, c in cfg["categories"].items():
        n = c["sku_count"]
        subcats = list(c["subcategories"])
        w = np.array([c["subcategories"][s]["weight"] for s in subcats])
        # at least two SKUs per subcategory, the rest by weight
        counts = 2 + rng.multinomial(n - 2 * len(subcats), w / w.sum())
        sub = np.repeat(subcats, counts)
        mult = np.array([c["subcategories"][s]["price_mult"] for s in sub])

        lo, hi = c["price_band"]
        raw = c["median_price"] * mult * rng.lognormal(0, price_cfg["price_sigma_within_subcategory"], n)
        raw = np.clip(raw, lo, hi)
        shelf_2024 = _shelf_price(raw * (1 + VAT_RATE))
        shelf_2025 = _shelf_price(shelf_2024 * (1 + price_cfg["price_increase_2025"][cat]))
        shelf_2025 = np.maximum(shelf_2025, shelf_2024)  # prices never fall with the annual review
        list_2024 = np.round(shelf_2024 / (1 + VAT_RATE), 2)
        list_2025 = np.round(shelf_2025 / (1 + VAT_RATE), 2)

        margin = np.clip(c["target_margin"] * rng.lognormal(0, 0.12, n), 0.05, 0.75)
        cost_2024 = np.round(list_2024 * (1 - margin), 2)
        cost_2025 = np.round(cost_2024 * (1 + price_cfg["cost_increase_2025"]), 2)

        pop = rng.lognormal(0, pcfg["sku_popularity_sigma"], n) * list_2024 ** pcfg["price_popularity_exponent"]

        sup_names = list(c["suppliers"])
        sup_p = np.array(list(c["suppliers"].values()))
        supplier = rng.choice(sup_names, size=n, p=sup_p / sup_p.sum())
        brand = rng.choice(c["brands"], size=n)
        names = [
            f"{b} {rng.choice(VARIANTS)} {rng.choice(SUBCATEGORY_NOUNS[s])}" for b, s in zip(brand, sub)
        ]
        frames.append(
            pd.DataFrame(
                {
                    "category": cat,
                    "subcategory": sub,
                    "product_name": names,
                    "brand": brand,
                    "supplier_name": supplier,
                    "list_price_2024": list_2024,
                    "list_price_2025": list_2025,
                    "unit_cost_2024": cost_2024,
                    "unit_cost_2025": cost_2025,
                    "popularity": pop,
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    n = len(df)

    # launch / discontinuation dates (range changes create natural mix shifts)
    launch = start - pd.to_timedelta(rng.integers(60, 1800, n), unit="D")
    is_new = rng.random(n) < pcfg["launch_2025_share"]
    launch = launch.where(~is_new, pd.Timestamp("2025-02-01") + pd.to_timedelta(rng.integers(0, 240, n), unit="D"))
    is_disc = (rng.random(n) < pcfg["discontinued_share"]) & ~is_new
    disc = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    disc[is_disc] = pd.Timestamp("2024-04-01") + pd.to_timedelta(rng.integers(0, 540, is_disc.sum()), unit="D")
    # range changes take effect on Mondays (weekly planogram reset)
    launch = launch.normalize()
    df["launch_date"] = launch - pd.to_timedelta(launch.dayofweek, unit="D")
    disc = disc.dt.normalize()
    df["discontinued_date"] = disc - pd.to_timedelta(disc.dt.dayofweek, unit="D")
    df["status"] = np.where(is_disc, "Discontinued", "Active")

    # business keys
    df["product_id"] = [f"P{i:05d}" for i in range(1, n + 1)]
    sup_ids = {s: f"SUP{i:02d}" for i, s in enumerate(sorted(df["supplier_name"].unique()), start=1)}
    df["supplier_id"] = df["supplier_name"].map(sup_ids)
    df["list_price"] = df["list_price_2025"]      # current price in the product master
    df["unit_cost"] = df["unit_cost_2025"]        # current standard cost
    df["prod_idx"] = np.arange(n)
    assert df["launch_date"].max() <= end
    return df


def build_ranging(cfg: dict, stores: pd.DataFrame, products: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    """Boolean matrix [S, P]: is the SKU ranged (planogrammed) in the store."""
    share = cfg["products"]["ranging_share"]
    S, P = len(stores), len(products)
    ranged = np.zeros((S, P), dtype=bool)
    logpop = np.log(products["popularity"].to_numpy())
    cats = products["category"].to_numpy()
    for s, fmt in enumerate(stores["store_format"]):
        score = logpop + rng.normal(0, 0.5, P)  # local tastes / space
        for cat in np.unique(cats):
            m = np.where(cats == cat)[0]
            k = int(round(share[fmt] * len(m)))
            keep = m[np.argsort(-score[m])[:k]]
            ranged[s, keep] = True
    return ranged


def select_stores(stores: pd.DataFrame, store_ids) -> np.ndarray:
    """Boolean mask [S] of stores simulated in this run ('all' = every store)."""
    if store_ids == "all":
        return np.ones(len(stores), dtype=bool)
    unknown = set(store_ids) - set(stores["store_id"])
    if unknown:
        raise ValueError(f"Unknown store ids in run_modes config: {sorted(unknown)}")
    return stores["store_id"].isin(store_ids).to_numpy()


def product_week_activity(products: pd.DataFrame, weeks: pd.DataFrame) -> np.ndarray:
    """Boolean [W, P]: SKU is live (launched, not discontinued) during the week."""
    ws = weeks["week_start"].to_numpy()[:, None]
    we = weeks["week_end"].to_numpy()[:, None]
    launch = products["launch_date"].to_numpy()[None, :]
    disc = products["discontinued_date"].to_numpy()[None, :]
    live = launch <= we
    ended = ~pd.isna(disc) & (disc <= ws)
    return live & ~ended
