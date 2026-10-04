"""Returns generation (fact_returns) from clean sales lines."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_fact_returns(cfg, scn, sales, internal, stores, products, seed):
    """Draw returns against sold lines: category and Christmas rates, the scenario faulty-batch
    rate, return lag, partial quantities, reasons and occasional returns to another store."""
    rng = np.random.default_rng(seed)
    rc = cfg["returns"]
    end = pd.Timestamp(cfg["calendar"]["end_date"])
    sale_date = internal["transaction_date_ts"]
    cats = products["category"].to_numpy()[internal["prod_idx"].to_numpy()]
    subs = products["subcategory"].to_numpy()[internal["prod_idx"].to_numpy()]

    p = pd.Series(cats).map(rc["base_return_prob"]).to_numpy(dtype=float)
    xmas = ((sale_date.dt.month == 11) & (sale_date.dt.day >= 15)) | ((sale_date.dt.month == 12) & (sale_date.dt.day <= 24))
    p = np.where(xmas, p * rc["christmas_gift_uplift"], p)

    b4 = np.zeros(len(sales), dtype=bool)
    if scn and "B4_faulty_batch_returns" in scn:
        b = scn["B4_faulty_batch_returns"]
        b4 = ((cats == b["category"]) & np.isin(subs, b["subcategories"]) & sales["store_id"].isin(b["stores"]).to_numpy()
              & (sale_date >= pd.Timestamp(b["sales_from"])).to_numpy() & (sale_date <= pd.Timestamp(b["sales_until"])).to_numpy())
        p = np.where(b4, b["return_prob"], p)

    ret = rng.random(len(sales)) < p
    r = sales.loc[ret].copy()
    r_int = internal.loc[ret]
    r_b4 = b4[ret]
    sd = r_int["transaction_date_ts"]

    lag = np.ceil(rng.gamma(rc["lag_gamma_shape"], rc["lag_gamma_scale"], len(r))).astype(int)
    mmdd = rc["christmas_extended_until"]
    xmas_deadline = pd.to_datetime((sd.dt.year + 1).astype(str) + "-" + mmdd)
    xmas_r = (((sd.dt.month == 11) & (sd.dt.day >= 15)) | ((sd.dt.month == 12) & (sd.dt.day <= 24))).to_numpy()
    max_lag = np.where(xmas_r, (xmas_deadline - sd).dt.days, rc["policy_days"])
    lag = np.clip(lag, 1, max_lag)
    rdate = sd + pd.to_timedelta(lag, unit="D")
    # Stores are closed on Christmas Day, so a return due that day lands on the 26th.
    rdate = rdate.where(~((rdate.dt.month == 12) & (rdate.dt.day == 25)), rdate + pd.Timedelta(days=1))
    in_extract = (rdate <= end).to_numpy()

    qty = r["quantity"].to_numpy()
    partial = (rng.random(len(r)) > rc["full_quantity_prob"]) & (qty > 1)
    rqty = np.where(partial, np.maximum(1, np.floor(rng.random(len(r)) * qty).astype(int)), qty)
    refund = np.round(r["revenue"].to_numpy() * rqty / qty, 2)

    reasons = rng.choice(rc["reasons"], size=len(r), p=np.array(rc["reason_probs"]) / sum(rc["reason_probs"]))
    if r_b4.any():
        fp = scn["B4_faulty_batch_returns"]["faulty_reason_prob"]
        reasons = np.where(r_b4 & (rng.random(len(r)) < fp), "Faulty", reasons)

    # returned to another store in the same region occasionally
    region = stores.set_index("store_id")["region"]
    ret_store = r["store_id"].to_numpy().copy()
    move = rng.random(len(r)) < rc["other_store_prob"]
    for i in np.flatnonzero(move):
        peers = stores.loc[(stores["region"] == region[ret_store[i]]) & (stores["store_id"] != ret_store[i]), "store_id"]
        if len(peers):
            ret_store[i] = rng.choice(peers.to_numpy())

    no_receipt = rng.random(len(r)) < rc["no_receipt_prob"]
    out = pd.DataFrame({
        "return_date": rdate.dt.strftime("%Y-%m-%d").to_numpy(),
        "store_id": ret_store,
        "original_transaction_id": np.where(no_receipt, None, r["transaction_id"].to_numpy()),
        "original_line_number": np.where(no_receipt, None, r["line_number"].to_numpy()).astype(object),
        "product_id": r["product_id"].to_numpy(),
        "return_quantity": rqty,
        "refund_value": refund,
        "return_reason": reasons,
        "restockable_flag": np.isin(reasons, rc["restockable_reasons"]),
    })
    out["_unit_cost"] = r["unit_cost"].to_numpy()
    out["_b4"] = r_b4
    out["_sale_line_key"] = (r["transaction_id"] + "|" + r["line_number"].astype(str)).to_numpy()
    out = out[in_extract].sort_values(["return_date", "store_id"]).reset_index(drop=True)
    out.insert(0, "return_id", [f"R{i:07d}" for i in range(1, len(out) + 1)])
    return out
