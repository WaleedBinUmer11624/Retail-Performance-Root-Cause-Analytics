"""Core simulation: demand lines -> weekly stock constraint -> sold lines + inventory.

Why simulate this way
---------------------
Sales and stock must be consistent with each other, otherwise the stock-out
analysis in Phase 7 would be meaningless. So demand is generated first as
individual customer lines, and each week the lines are served in day order
against the stock actually on the shelf. A line that finds no stock is lost,
unless the customer buys a substitute from the same subcategory (which itself
needs stock). Units sold therefore always equal the units that left the shelf.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _qty_tables(cfg, products):
    cats = list(cfg["categories"])
    cat_code = pd.Categorical(products["category"], categories=cats).codes.astype(np.int64)
    probs = np.array([cfg["categories"][c]["qty_probs"] for c in cats], dtype=float)
    probs = probs / probs.sum(axis=1, keepdims=True)
    cum = np.cumsum(probs, axis=1)
    mean_qty = (probs * np.arange(1, probs.shape[1] + 1)).sum(axis=1)
    return cat_code, cum, mean_qty[cat_code]


def _cum_within_groups(keys: np.ndarray, qty: np.ndarray) -> np.ndarray:
    """Cumulative qty within consecutive runs of equal keys (keys must be sorted)."""
    if len(keys) == 0:
        return qty.copy()
    cq = np.cumsum(qty)
    starts = np.r_[True, keys[1:] != keys[:-1]]
    start_idx = np.flatnonzero(starts)
    gid = np.cumsum(starts) - 1
    return cq - (cq[start_idx] - qty[start_idx])[gid]


def _substitution_index(products, ranged_eff, n_stores):
    """Flattened weighted-choice structure over (store, subcategory) groups."""
    sub_code = pd.Categorical(products["subcategory"]).codes.astype(np.int64)
    n_sub = int(sub_code.max()) + 1
    pop = products["popularity"].to_numpy()
    s_idx, p_idx = np.nonzero(ranged_eff)
    g = s_idx * n_sub + sub_code[p_idx]
    order = np.argsort(g, kind="stable")
    ent_g, ent_p = g[order], p_idx[order]
    w = pop[ent_p]
    cw = np.cumsum(w)
    n_groups = n_stores * n_sub
    first = np.searchsorted(ent_g, np.arange(n_groups), side="left")
    last = np.searchsorted(ent_g, np.arange(n_groups), side="right") - 1
    start_val = np.where(first > 0, cw[np.maximum(first - 1, 0)], 0.0)
    total = np.where(last >= first, cw[np.clip(last, 0, None)] - start_val, 0.0)
    return dict(sub_code=sub_code, n_sub=n_sub, ent_p=ent_p, cw=cw, first=first, last=last,
                start_val=start_val, total=total)


def simulate(cfg, stores, products, weeks, ranged, store_mask, live, E_actual, E_repl,
             fill, day_weights, seed):
    """Serve demand lines in day order against weekly shelf stock; return sold lines and inventory."""
    rng = np.random.default_rng(seed)
    inv = cfg["inventory"]
    W, S, P = E_actual.shape
    SP = S * P
    n_inv_weeks = cfg["calendar"]["inventory_weeks"]

    cat_code, qty_cum, mean_qty = _qty_tables(cfg, products)
    ranged_eff = ranged & store_mask[:, None]
    subx = _substitution_index(products, ranged_eff, S)

    # ---- 1. demand lines -------------------------------------------------
    L = rng.poisson(E_actual).ravel()
    cells = np.repeat(np.arange(W * SP, dtype=np.int64), L)
    n = len(cells)
    w_line = cells // SP
    local = cells % SP
    p_line = local % P
    u = rng.random(n)
    cq = qty_cum[cat_code[p_line]]
    qty = 1 + (u > cq[:, 0]) + (u > cq[:, 1]) + (u > cq[:, 2])
    cdw = np.cumsum(day_weights, axis=1)
    dow = np.minimum((rng.random(n)[:, None] > cdw[w_line]).sum(axis=1), 6)
    order = np.lexsort((dow, cells))
    cells, w_line, local, qty, dow = cells[order], w_line[order], local[order], qty[order], dow[order]
    bounds = np.searchsorted(w_line, np.arange(W + 1))
    log.info("Generated %s demand lines", f"{n:,}")

    # ---- 2. weekly stock loop ------------------------------------------------
    cover = stores["store_format"].map(inv["cover_weeks"]).to_numpy()[:, None]
    opening = np.zeros((S, P), dtype=np.int64)
    sold_parts, lost_parts, inv_parts = [], [], []

    for w in range(W):
        plan = E_repl[w] * mean_qty[None, :] * rng.lognormal(0, inv["forecast_error_sigma"], (S, P))
        oul = np.ceil(plan * cover + inv["safety_z"] * np.sqrt(plan))
        oul = np.where(plan > 0, np.maximum(oul, inv["min_presentation_stock"]), 0).astype(np.int64)
        oul *= ranged_eff & live[w][None, :]
        order_qty = np.maximum(0, oul - opening)
        received = rng.binomial(order_qty, fill[w][None, :]) if w > 0 else np.zeros_like(order_qty)
        if w == 0:
            opening = oul.copy()  # opening stock position at the start of the data
        avail = (opening + received).ravel()

        a, b = bounds[w], bounds[w + 1]
        lc, lq, ld = local[a:b], qty[a:b], dow[a:b]
        in_cell = _cum_within_groups(lc, lq)
        ok = in_cell <= avail[lc]
        sold_units = np.bincount(lc[ok], weights=lq[ok], minlength=SP).astype(np.int64)

        # substitution for lines that found an empty shelf
        rej = np.flatnonzero(~ok)
        try_sub = rej[rng.random(len(rej)) < inv["substitution_rate"]]
        s_r, p_r = lc[try_sub] // P, lc[try_sub] % P
        g = s_r * subx["n_sub"] + subx["sub_code"][p_r]
        valid = subx["total"][g] > 0
        target = subx["start_val"][g] + rng.random(len(g)) * subx["total"][g]
        j = np.clip(np.searchsorted(subx["cw"], target, side="right"), subx["first"][g], subx["last"][g])
        j = np.clip(j, 0, len(subx["ent_p"]) - 1)
        p_sub = subx["ent_p"][j]
        valid &= p_sub != p_r
        try_sub, s_r, p_r, p_sub = try_sub[valid], s_r[valid], p_r[valid], p_sub[valid]
        new_cell = s_r * P + p_sub
        o = np.lexsort((ld[try_sub], new_cell))
        try_sub, new_cell, p_r, p_sub = try_sub[o], new_cell[o], p_r[o], p_sub[o]
        spare = avail - sold_units
        sub_cum = _cum_within_groups(new_cell, lq[try_sub])
        acc = sub_cum <= spare[new_cell]
        sold_units += np.bincount(new_cell[acc], weights=lq[try_sub][acc], minlength=SP).astype(np.int64)
        substituted = np.zeros(b - a, dtype=bool)
        substituted[try_sub[acc]] = True

        sold_parts.append(pd.DataFrame({
            "week_idx": w, "store_idx": np.r_[lc[ok] // P, new_cell[acc] // P],
            "prod_idx": np.r_[lc[ok] % P, p_sub[acc]],
            "dow": np.r_[ld[ok], ld[try_sub][acc]], "qty": np.r_[lq[ok], lq[try_sub][acc]],
            "is_substitute": np.r_[np.zeros(ok.sum(), bool), np.ones(acc.sum(), bool)],
            "orig_prod_idx": np.r_[lc[ok] % P, p_r[acc]],
        }))
        lost = ~ok & ~substituted
        lost_parts.append(pd.DataFrame({"week_idx": w, "store_idx": lc[lost] // P,
                                        "prod_idx": lc[lost] % P, "qty": lq[lost]}))

        # closing stock: shrinkage and range-exit write-offs are adjustments
        closing_pre = (avail - sold_units).reshape(S, P)
        adj = -((closing_pre > 0) & (rng.random((S, P)) < inv["shrinkage_prob"])).astype(np.int64)
        if w > 0:
            exited = live[w - 1] & ~live[w]
            adj[:, exited] = -closing_pre[:, exited]
        closing = closing_pre + adj
        assert (closing >= 0).all()

        if w < n_inv_weeks:
            sold2 = sold_units.reshape(S, P)
            keep = ranged_eff & ((oul > 0) | (opening > 0) | (received > 0) | (closing > 0) | (sold2 > 0))
            s_i, p_i = np.nonzero(keep)
            inv_parts.append(pd.DataFrame({
                "week_idx": w, "store_idx": s_i, "prod_idx": p_i,
                "opening_stock": opening[s_i, p_i], "received_qty": received[s_i, p_i],
                "sold_qty": sold2[s_i, p_i], "adjustment_qty": adj[s_i, p_i],
                "closing_stock": closing[s_i, p_i],
            }))
        opening = closing

    sold = pd.concat(sold_parts, ignore_index=True)
    lost = pd.concat(lost_parts, ignore_index=True)
    inventory = pd.concat(inv_parts, ignore_index=True)
    log.info("Sold lines %s, lost lines %s, inventory rows %s", f"{len(sold):,}", f"{len(lost):,}", f"{len(inventory):,}")
    return sold, lost, inventory, mean_qty
