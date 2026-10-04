"""Turn sold lines into POS transactions (fact_sales), with prices, discounts and costs."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_fact_sales(cfg, sold, stores, products, weeks, promo_depth, promo_ref, promo_ids, seed):
    """Turn simulated sold units into dated, priced sales lines grouped into transactions."""
    rng = np.random.default_rng(seed)
    df = sold.copy()
    df["transaction_date"] = weeks["week_start"].to_numpy()[df["week_idx"]] + pd.to_timedelta(df["dow"], unit="D")
    end = pd.Timestamp(cfg["calendar"]["end_date"])
    closed = pd.to_datetime(cfg["calendar"]["closed_dates"])
    df = df[(df["transaction_date"] <= end) & ~df["transaction_date"].isin(closed)].reset_index(drop=True)

    # ---- baskets: shuffle lines within store-day, then cut into receipts ----
    df["_r"] = rng.random(len(df))
    df = df.sort_values(["store_idx", "transaction_date", "_r"], kind="stable").reset_index(drop=True)
    new_day = (df["store_idx"].diff() != 0) | (df["transaction_date"].diff() != pd.Timedelta(0))
    starts = new_day.to_numpy() | (rng.random(len(df)) < cfg["volume"]["basket_new_transaction_prob"])
    df["_txn"] = np.cumsum(starts) - 1

    txn = df.groupby("_txn", sort=False).agg(store_idx=("store_idx", "first"),
                                              transaction_date=("transaction_date", "first")).reset_index()
    th = cfg["calendar"]["trading_hours"]
    hw = np.asarray(th["weights"], float)
    hour = rng.choice(th["hours"], size=len(txn), p=hw / hw.sum())
    minute = rng.integers(0, 60, len(txn))
    txn["transaction_time"] = [f"{h:02d}:{m:02d}" for h, m in zip(hour, minute)]
    txn = txn.sort_values(["store_idx", "transaction_date", "transaction_time", "_txn"]).reset_index(drop=True)
    txn["seq"] = txn.groupby(["store_idx", "transaction_date"]).cumcount() + 1
    txn["transaction_id"] = (stores["store_id"].to_numpy()[txn["store_idx"]] + "-"
                             + txn["transaction_date"].dt.strftime("%Y%m%d") + "-"
                             + txn["seq"].astype(str).str.zfill(5))
    df = df.merge(txn[["_txn", "transaction_id", "transaction_time"]], on="_txn", how="left")
    df = df.sort_values(["transaction_id", "_r"]).reset_index(drop=True)
    df["line_number"] = df.groupby("transaction_id").cumcount() + 1

    # ---- prices, discounts, costs -------------------------------------------
    p = df["prod_idx"].to_numpy()
    is25 = (df["transaction_date"] >= pd.Timestamp("2025-01-01")).to_numpy()
    price = np.where(is25, products["list_price_2025"].to_numpy()[p], products["list_price_2024"].to_numpy()[p])
    ucost = np.where(is25, products["unit_cost_2025"].to_numpy()[p], products["unit_cost_2024"].to_numpy()[p])
    w, s = df["week_idx"].to_numpy(), df["store_idx"].to_numpy()
    depth = promo_depth[w, s, p]
    ref = promo_ref[w, s, p]
    pr = cfg["pricing"]
    md = (ref < 0) & (rng.random(len(df)) < pr["markdown_line_share"])
    depth = np.where(md, rng.choice(pr["markdown_depths"], size=len(df)), depth)

    qty = df["qty"].to_numpy()
    gross = qty * price
    discount = np.round(gross * depth, 2)
    revenue = np.round(gross - discount, 2)
    cost = np.round(qty * ucost, 2)

    out = pd.DataFrame({
        "transaction_id": df["transaction_id"],
        "line_number": df["line_number"],
        "transaction_date": df["transaction_date"].dt.strftime("%Y-%m-%d"),
        "transaction_time": df["transaction_time"],
        "store_id": stores["store_id"].to_numpy()[s],
        "product_id": products["product_id"].to_numpy()[p],
        "category": products["category"].to_numpy()[p],
        "quantity": qty,
        "unit_price": price,
        "discount": discount,
        "revenue": revenue,
        "unit_cost": ucost,
        "cost": cost,
        "margin": np.round(revenue - cost, 2),
        "promotion_id": np.where(ref >= 0, promo_ids[np.maximum(ref, 0)], None),
    })
    extract_day = df["transaction_date"] + pd.Timedelta(days=1)
    out["extract_batch_id"] = "B" + extract_day.dt.strftime("%Y%m%d")
    out["extract_timestamp"] = (extract_day + pd.Timedelta(hours=2)
                                + pd.to_timedelta(rng.integers(0, 45, len(df)), unit="m")).dt.strftime("%Y-%m-%d %H:%M:%S")
    internal = df[["week_idx", "store_idx", "prod_idx", "is_substitute", "orig_prod_idx"]].copy()
    internal["transaction_date_ts"] = df["transaction_date"]
    return out, internal
