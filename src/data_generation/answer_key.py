"""Measure the realised impact of each hidden behaviour (answer key).

These are approximate, simulation-side measurements used ONLY to validate
the Phase 7 root-cause analysis afterwards. They are written to
_scenario_answer_key.csv and must never be read by analysis code.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

H2_WEEKS = {2024: (26, 52), 2025: (78, 104)}  # week_idx ranges [start, end)


def _in_h2(week_idx, year):
    a, b = H2_WEEKS[year]
    return (week_idx >= a) & (week_idx < b)


def _net_revenue(sales, internal, returns, weeks, year):
    a, b = H2_WEEKS[year]
    lo, hi = weeks.loc[a, "week_start"], weeks.loc[b - 1, "week_end"]
    s = sales.loc[_in_h2(internal["week_idx"].to_numpy(), year), "revenue"].sum()
    rd = pd.to_datetime(returns["return_date"])
    r = returns.loc[(rd >= lo) & (rd <= hi), "refund_value"].sum()
    return s, r, s - r


def _h2_revenue(frame, weeks, year):
    """Sales revenue of rows whose transaction date falls in the H2 window."""
    a, b = H2_WEEKS[year]
    lo, hi = weeks.loc[a, "week_start"], weeks.loc[b - 1, "week_end"]
    d = pd.to_datetime(frame["transaction_date"])
    return float(frame.loc[(d >= lo) & (d <= hi), "revenue"].sum())


def build_answer_key(scn, cfg, weeks, stores, products, sales, internal, returns, lost, late, missing,
                     traffic_mult, b2_affected, E_scn, E_base, mean_qty, depth_scn, depth_base):
    """Headline definitions (all on H2 week-aligned net revenue):
      underlying : every sale that really happened (late batch and missing batch included)
      reported   : what the main extract shows (late batch absent, missing batch absent)
      artefact   : reported change minus underlying change (pure data-completeness effect)
    Returns are counted by return date in both views (the returns feed is complete).
    """
    rows = []
    s24, r24, nr24 = _net_revenue(sales, internal, returns, weeks, 2024)
    s25, r25, nr25 = _net_revenue(sales, internal, returns, weeks, 2025)
    late24, late25 = (_h2_revenue(late, weeks, y) if len(late) else 0.0 for y in (2024, 2025))
    miss24, miss25 = (_h2_revenue(missing, weeks, y) if len(missing) else 0.0 for y in (2024, 2025))
    rep24, rep25 = nr24 - late24 - miss24, nr25 - late25 - miss25
    und_pct = 100 * (nr25 / nr24 - 1)
    rep_pct = 100 * (rep25 / rep24 - 1)

    def add(bid, name, eur, method, pp=None):
        rows.append({"behaviour_id": bid, "behaviour": name, "impact_eur": round(eur, 2),
                     "impact_pp_of_h2_2024_net_revenue": round(100 * eur / nr24, 2) if pp is None else pp,
                     "method": method})

    add("HEADLINE", "H2 2024 net revenue (underlying)", nr24, "all sales by transaction week minus returns by return date", np.nan)
    add("HEADLINE", "H2 2024 net revenue (reported)", rep24, "underlying minus missing-batch sales", np.nan)
    add("HEADLINE", "H2 2025 net revenue (underlying)", nr25, "includes the late-arriving batch", round(und_pct, 2))
    add("HEADLINE", "H2 2025 net revenue (reported)", rep25, "late batch not loaded", round(rep_pct, 2))
    add("DQ", "Data-completeness artefact (reported minus underlying YoY)", (rep25 - nr25) - (rep24 - nr24),
        "late batch in H2 2025 and missing batch in H2 2024", round(rep_pct - und_pct, 2))
    add("DQ", "Late batch sales revenue (H2 2025)", late25, "revenue delivered only in fact_sales_late_batch.csv", np.nan)
    add("DQ", "Missing batch sales revenue (H2 2024)", miss24, "never delivered (POS outage)", np.nan)

    # B1 traffic: revenue in affected store-weeks x (1 - 1/multiplier)
    w, s = internal["week_idx"].to_numpy(), internal["store_idx"].to_numpy()
    m = traffic_mult[w, s]
    h25 = _in_h2(w, 2025)
    b1 = -(sales["revenue"].to_numpy()[h25] * (1 / m[h25] - 1)).sum()
    add("B1", "Suburban traffic decline", b1, "sum over H2 2025 lines of revenue * (1/traffic_multiplier - 1)")

    # B2 stock-outs on affected SKUs: change in net lost revenue vs H2 2024
    def lost_net(year):
        price = products["list_price_2025" if year == 2025 else "list_price_2024"].to_numpy()
        lw = lost[_in_h2(lost["week_idx"].to_numpy(), year) & b2_affected[lost["prod_idx"].to_numpy()]]
        gross = (lw["qty"] * price[lw["prod_idx"]] * (1 - depth_scn[lw["week_idx"], lw["store_idx"], lw["prod_idx"]])).sum()
        subs = internal["is_substitute"].to_numpy() & b2_affected[internal["orig_prod_idx"].to_numpy()] & _in_h2(w, year)
        return gross - sales["revenue"].to_numpy()[subs].sum()
    b2 = -(lost_net(2025) - lost_net(2024))
    add("B2", "Supplier stock-outs (affected SKUs)", b2,
        "increase in (unserved demand at selling price - substitute sales) vs H2 2024")

    # B3 promotion change: expected H&K revenue under new vs old promo plan (no noise)
    hk = (products["category"] == scn["B3_home_kitchen_promotion_change"]["category"]).to_numpy()
    a, bnd = H2_WEEKS[2025]
    price = products["list_price_2025"].to_numpy()[hk]
    rev_s = (E_scn[a:bnd][:, :, hk] * mean_qty[hk] * price * (1 - depth_scn[a:bnd][:, :, hk])).sum()
    rev_b = (E_base[a:bnd][:, :, hk] * mean_qty[hk] * price * (1 - depth_base[a:bnd][:, :, hk])).sum()
    b3 = rev_s - rev_b
    add("B3", "Home & Kitchen promotion change", b3,
        "expected H2 2025 H&K sales revenue under the new vs the previous promotion plan")

    # B4 faulty batch returns: refunds above the normal return rate
    b4 = scn["B4_faulty_batch_returns"]
    base_p = cfg["returns"]["base_return_prob"][b4["category"]]
    lo, hi = weeks.loc[a, "week_start"], weeks.loc[bnd - 1, "week_end"]
    rd = pd.to_datetime(returns["return_date"])
    in_w = (rd >= lo) & (rd <= hi) & returns["_b4"]
    b4_eur = -(returns.loc[in_w, "refund_value"].sum() * (1 - base_p / b4["return_prob"]))
    add("B4", "Faulty batch returns", b4_eur, "refunds on affected lines * (1 - base rate / elevated rate)")

    explained = b1 + b2 + b3 + b4_eur
    add("OTHER", "Natural variation, price, mix and other (residual)", (nr25 - nr24) - explained,
        "true change minus B1 to B4")
    return pd.DataFrame(rows)
