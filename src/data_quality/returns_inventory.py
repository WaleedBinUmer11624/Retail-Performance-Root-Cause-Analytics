"""Checks and treatments for fact_returns and fact_inventory, plus POS-to-stock reconciliation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import DQContext, id_date, is_blank, key_of, parse_date_iso, to_num
from .dimensions import UNKNOWN

INV_KEY = ["store_id", "product_id", "snapshot_date"]


# ------------------------------------------------------------------ returns
def clean_returns(raw: pd.DataFrame, ctx: DQContext, sales: pd.DataFrame, stores: set, products: set,
                  late_keys: set) -> pd.DataFrame:
    """Apply the fact_returns rules against curated sales and dimensions; return curated returns."""
    cfg = ctx.cfg
    T = "fact_returns"
    df = raw.copy()
    n = len(df)
    data_cols = [c for c in df.columns if c not in ("source_file", "source_row")]

    dup = df.duplicated(subset=data_cols, keep="first")
    ctx.result("FR-01", n, int(dup.sum()), float(to_num(df.loc[dup, "refund_value"]).sum()))
    ctx.log_rows("FR-01", T, df.loc[dup, "return_id"])
    ctx.add_quarantine(T, df[dup], "FR-01", "exact duplicate row")
    before = float(to_num(df["refund_value"]).sum())
    df = df[~dup].copy()
    ctx.audit_step(T, "FR-01", "DEDUPLICATE", int(dup.sum()), "all", "returns value EUR", before,
                   float(to_num(df["refund_value"]).sum()))

    conflict = df["return_id"].duplicated(keep=False)
    ctx.result("FR-02", len(df), int(conflict.sum()))
    ctx.log_rows("FR-02", T, df.loc[conflict, "return_id"])
    ctx.add_quarantine(T, df[conflict], "FR-02", "return_id reused for different returns")
    df = df[~conflict].copy()

    df["return_date"] = parse_date_iso(df["return_date"])
    df["return_quantity"] = to_num(df["return_quantity"])
    df["refund_value"] = to_num(df["refund_value"])
    df["original_line_number"] = to_num(df["original_line_number"]).astype("Int64")
    df["original_transaction_id"] = df["original_transaction_id"].where(~is_blank(df["original_transaction_id"]), None)
    flags = pd.Series("", index=df.index)

    def flag(rule, m):
        flags.loc[m] = flags.loc[m] + np.where(flags.loc[m] == "", "", ";") + rule

    has = df["original_transaction_id"].notna()
    ctx.result("FR-03", len(df), int((~has).sum()), float(df.loc[~has, "refund_value"].sum()),
               evidence=f"{(~has).mean():.1%} of returns have no receipt")

    rk = (df["original_transaction_id"].fillna("") + "|" + df["original_line_number"].astype(str))
    all_keys = ctx.notes["sales_all_keys"]
    found = has & rk.isin(all_keys)
    orphan = has & ~found
    s = sales.set_index(sales["transaction_id"] + "|" + sales["line_number"].astype(str))
    pos_days = set(zip(sales["store_id"], sales["transaction_date"]))
    ref_day = list(zip(df["original_transaction_id"].fillna("").str.slice(0, 3), id_date(df["original_transaction_id"].fillna(""))))
    no_pos_day = orphan & pd.Series([d not in pos_days for d in ref_day], index=df.index)
    ctx.result("FR-04", int(has.sum()), int(orphan.sum()), float(df.loc[orphan, "refund_value"].sum()),
               evidence=f"{int(no_pos_day.sum())} point to a store-day with no POS data at all (see TC-02); "
                        f"{int((orphan & ~no_pos_day).sum())} point to a line number that does not exist")
    ctx.log_rows("FR-04", T, df.loc[orphan, "return_id"], "original_transaction_id",
                 rk[orphan])
    flag("FR-04", orphan)
    via_late = found & rk.isin(late_keys)
    ctx.result("FR-12", int(found.sum()), int(via_late.sum()))

    linked = found & rk.isin(s.index)          # sale line present in curated sales
    L = s.loc[rk[linked]]
    sale_d = id_date(df.loc[linked, "original_transaction_id"])
    before_sale = pd.Series(False, index=df.index)
    before_sale[linked] = (df.loc[linked, "return_date"] < sale_d).to_numpy()
    ctx.result("FR-05", int(linked.sum()), int(before_sale.sum()), float(df.loc[before_sale, "refund_value"].sum()))
    ctx.log_rows("FR-05", T, df.loc[before_sale, "return_id"], "return_date", df.loc[before_sale, "return_date"],
                 action="QUARANTINE")

    over = pd.Series(False, index=df.index)
    over[linked] = (df.loc[linked, "return_quantity"].to_numpy() > L["quantity"].to_numpy())
    ctx.result("FR-06", int(linked.sum()), int(over.sum()), float(df.loc[over, "refund_value"].sum()))
    ctx.log_rows("FR-06", T, df.loc[over, "return_id"], "return_quantity", df.loc[over, "return_quantity"],
                 action="QUARANTINE")

    q = before_sale | over
    before = float(df["refund_value"].sum())
    ctx.add_quarantine(T, raw.loc[df.index[q]], "FR-05/FR-06", "impossible return as recorded")
    ctx.audit_step(T, "FR-05/FR-06", "QUARANTINE", int(q.sum()), "all", "returns value EUR", before,
                   float(df.loc[~q, "refund_value"].sum()))

    unit_val = pd.Series(np.nan, index=df.index)
    unit_val[linked] = (L["revenue"] / L["quantity"]).to_numpy()
    overref = linked & ~q & (df["refund_value"] > unit_val * df["return_quantity"] + cfg["tolerances"]["money"])
    ctx.result("FR-07", int(linked.sum()), int(overref.sum()),
               float((df.loc[overref, "refund_value"] - unit_val[overref] * df.loc[overref, "return_quantity"]).sum()))
    ctx.log_rows("FR-07", T, df.loc[overref, "return_id"], "refund_value", df.loc[overref, "refund_value"])
    flag("FR-07", overref)

    sp = pd.Series(None, index=df.index, dtype=object)
    sp[linked] = L["product_id"].to_numpy()
    pm = linked & (sp != UNKNOWN) & (sp != df["product_id"])
    ctx.result("FR-08", int(linked.sum()), int(pm.sum()))
    ctx.log_rows("FR-08", T, df.loc[pm, "return_id"], "product_id", df.loc[pm, "product_id"], sp[pm])
    flag("FR-08", pm & ~q)

    ss = pd.Series(None, index=df.index, dtype=object)
    ss[linked] = L["store_id"].to_numpy()
    other = linked & (ss != df["store_id"])
    ctx.result("FR-09", int(linked.sum()), int(other.sum()))

    lag = pd.Series(np.nan, index=df.index)
    lag[linked] = (df.loc[linked, "return_date"] - sale_d).dt.days.to_numpy()
    xm = cfg["timeliness"]["christmas_return_window"]
    sd = pd.Series(pd.NaT, index=df.index)
    sd[linked] = sale_d.to_numpy()
    mmdd = sd.dt.strftime("%m-%d")
    xmas = linked & mmdd.between(xm["purchase_from"], xm["purchase_to"])
    limit = pd.Series(cfg["timeliness"]["return_policy_days"], index=df.index, dtype=float)
    xlimit = (pd.to_datetime((sd.dt.year + 1).astype("Int64").astype(str) + "-" + xm["return_by"], errors="coerce") - sd).dt.days
    limit[xmas] = np.maximum(limit[xmas], xlimit[xmas])
    late_ret = linked & ~q & (lag > limit)
    ctx.result("FR-10", int(linked.sum()), int(late_ret.sum()))
    ctx.log_rows("FR-10", T, df.loc[late_ret, "return_id"], "return_date", df.loc[late_ret, "return_date"])
    flag("FR-10", late_ret)

    start, end = pd.Timestamp(cfg["period"]["start"]), pd.Timestamp(cfg["period"]["end"])
    dom = ((df["return_quantity"] <= 0) | (df["refund_value"] <= 0) | df["return_quantity"].isna()
           | ~df["return_reason"].isin(cfg["domains"]["return_reasons"]) | ~df["restockable_flag"].isin(["True", "False"])
           | ~df["store_id"].isin(stores) | ~df["product_id"].isin(products) | ~df["return_date"].between(start, end))
    ctx.result("FR-11", len(df), int(dom.sum()))
    ctx.log_rows("FR-11", T, df.loc[dom, "return_id"])
    flag("FR-11", dom & ~q)

    df["is_linked"] = found
    df["restockable_flag"] = df["restockable_flag"].map({"True": True, "False": False})
    df["dq_rules"] = flags
    df["dq_status"] = np.where(flags == "", "clean", "flagged")
    df["return_quantity"] = df["return_quantity"].astype("Int64")
    return df[~q].reset_index(drop=True)


# ------------------------------------------------------------------ inventory
INT_COLS = ["retail_year", "retail_week", "opening_stock", "received_qty", "sold_qty", "adjustment_qty", "closing_stock"]


def clean_inventory(raw: pd.DataFrame, ctx: DQContext, stores: set, products: set,
                    dim_date: pd.DataFrame) -> pd.DataFrame:
    """Apply the fact_inventory rules and return curated weekly stock snapshots."""
    T = "fact_inventory"
    df = raw.copy()
    n = len(df)
    data_cols = [c for c in df.columns if c not in ("source_file", "source_row")]

    dup = df.duplicated(subset=data_cols, keep="first")
    ctx.result("FI-01", n, int(dup.sum()))
    ctx.log_rows("FI-01", T, key_of(df[dup], INV_KEY))
    ctx.add_quarantine(T, df[dup], "FI-01", "exact duplicate row")
    df = df[~dup].copy()
    ctx.audit_step(T, "FI-01", "DEDUPLICATE", int(dup.sum()), metric="rows", before=n, after=len(df))

    k = key_of(df, INV_KEY)
    kd = k.duplicated(keep=False)
    ctx.result("FI-02", len(df), int(kd.sum()))
    ctx.log_rows("FI-02", T, k[kd])
    ctx.add_quarantine(T, df[kd], "FI-02", "conflicting snapshots for one key")
    df = df[~kd].copy()

    dec = pd.Series(False, index=df.index)
    for c in INT_COLS:
        dec |= df[c].str.contains(r"\.", regex=True)
    ctx.result("FI-03", len(df), int(dec.sum()),
               evidence="columns stored with decimals: " + ", ".join(c for c in INT_COLS if df[c].str.contains(r"\.").any()))
    ctx.audit_step(T, "FI-03", "STANDARDISE", int(dec.sum()), "received_qty", note="cast to integer")
    for c in INT_COLS:
        df[c] = to_num(df[c])
    df["snapshot_date"] = parse_date_iso(df["snapshot_date"])
    flags = pd.Series("", index=df.index)

    def flag(rule, m):
        flags.loc[m] = flags.loc[m] + np.where(flags.loc[m] == "", "", ";") + rule

    kk = key_of(df.assign(snapshot_date=df["snapshot_date"].dt.strftime("%Y-%m-%d")), INV_KEY)

    miss = df["received_qty"].isna()
    derived = (df["closing_stock"] - df["opening_stock"] + df["sold_qty"] - df["adjustment_qty"])
    ok = miss & (derived >= 0) & df["closing_stock"].ge(0)
    ctx.result("FI-04", len(df), int(miss.sum()), evidence=f"{int(ok.sum())} derived, {int((derived[ok] > 0).sum())} "
               "of them non-zero")
    ctx.log_rows("FI-04", T, kk[ok], "received_qty", "", derived[ok])
    df.loc[ok, "received_qty"] = derived[ok]
    flag("FI-04", ok)
    ctx.audit_step(T, "FI-04", "CORRECT", int(ok.sum()), "received_qty", note="from the stock identity")

    ident = df["opening_stock"] + df["received_qty"] - df["sold_qty"] + df["adjustment_qty"]
    negc = df["closing_stock"] < 0
    sign = negc & (df["closing_stock"] == -ident)
    ctx.result("FI-05", len(df), int(negc.sum()), evidence=f"{int(sign.sum())} are exactly minus the identity value")
    ctx.log_rows("FI-05", T, kk[negc], "closing_stock", df.loc[negc, "closing_stock"], ident[negc].where(sign[negc]))
    df.loc[sign, "closing_stock"] = ident[sign]
    flag("FI-05", sign)
    ctx.audit_step(T, "FI-05", "CORRECT", int(sign.sum()), "closing_stock", note="sign corrected")

    # FI-06 triangulate identity breaks with the neighbouring weeks
    df = df.sort_values(["store_id", "product_id", "snapshot_date"])
    kk = kk.loc[df.index]
    g = df.groupby(["store_id", "product_id"])
    prev_close, prev_date = g["closing_stock"].shift(), g["snapshot_date"].shift()
    next_open, next_date = g["opening_stock"].shift(-1), g["snapshot_date"].shift(-1)
    has_prev = (df["snapshot_date"] - prev_date).dt.days == 7
    has_next = (next_date - df["snapshot_date"]).dt.days == 7
    flow = df["received_qty"] - df["sold_qty"] + df["adjustment_qty"]
    ident = df["opening_stock"] + flow
    brk = ident != df["closing_stock"]
    open_wrong = brk & has_prev & (prev_close + flow == df["closing_stock"]) & (~has_next | (next_open == df["closing_stock"]))
    close_wrong = brk & ~open_wrong & has_next & (next_open == ident)
    unresolved = brk & ~open_wrong & ~close_wrong
    ctx.result("FI-06", len(df), int(brk.sum()),
               evidence=f"{int(open_wrong.sum())} opening_stock corrected to the previous closing; {int(close_wrong.sum())} "
                        f"closing_stock corrected to the identity result; {int(unresolved.sum())} unresolved and flagged")
    ctx.log_rows("FI-06", T, kk[open_wrong], "opening_stock", df.loc[open_wrong, "opening_stock"], prev_close[open_wrong],
                 action="CORRECT (triangulated)")
    ctx.log_rows("FI-06", T, kk[close_wrong], "closing_stock", df.loc[close_wrong, "closing_stock"], ident[close_wrong],
                 action="CORRECT (triangulated)")
    ctx.log_rows("FI-06", T, kk[unresolved], "closing_stock", df.loc[unresolved, "closing_stock"], ident[unresolved],
                 action="FLAG")
    df.loc[open_wrong, "opening_stock"] = prev_close[open_wrong]
    df.loc[close_wrong, "closing_stock"] = ident[close_wrong]
    flag("FI-06", brk)
    ctx.audit_step(T, "FI-06", "CORRECT", int((open_wrong | close_wrong).sum()), "opening_stock, closing_stock",
                   note=f"{int(unresolved.sum())} rows left flagged")

    g = df.groupby(["store_id", "product_id"])
    prev_close = g["closing_stock"].shift()
    consec = has_prev
    cont = consec & (df["opening_stock"] != prev_close)
    ctx.result("FI-07", int(consec.sum()), int(cont.sum()), evidence="tested after FI-06 corrections")
    ctx.log_rows("FI-07", T, kk[cont], "opening_stock", df.loc[cont, "opening_stock"], prev_close[cont])
    flag("FI-07", cont)

    gap = prev_date.notna() & ((df["snapshot_date"] - prev_date).dt.days > 7)
    missing = []
    for (s, p, d0, d1) in zip(df.loc[gap, "store_id"], df.loc[gap, "product_id"], prev_date[gap], df.loc[gap, "snapshot_date"]):
        for d in pd.date_range(d0 + pd.Timedelta(days=7), d1 - pd.Timedelta(days=7), freq="7D"):
            missing.append((s, p, d.strftime("%Y-%m-%d")))
    miss_df = pd.DataFrame(missing, columns=INV_KEY)
    ctx.result("TC-05", len(df) + len(miss_df), len(miss_df),
               evidence=f"{int(gap.sum())} series with an internal gap")
    ctx.log_rows("TC-05", T, key_of(miss_df, INV_KEY), action="GAP (not imputed)")

    neg = (df[["opening_stock", "received_qty", "sold_qty", "closing_stock"]] < 0).any(axis=1) | (df["adjustment_qty"] > 0)
    ctx.result("FI-08", len(df), int(neg.sum()))
    ctx.log_rows("FI-08", T, kk[neg])
    flag("FI-08", neg)

    dd = dim_date.set_index("date")
    bad = ((df["snapshot_date"].dt.dayofweek != 6) | (df["snapshot_date"].map(dd["retail_week"]) != df["retail_week"])
           | (df["snapshot_date"].map(dd["retail_year"]) != df["retail_year"]))
    ctx.result("FI-09", len(df), int(bad.sum()))
    orph = ~df["store_id"].isin(stores) | ~df["product_id"].isin(products)
    ctx.result("FI-10", len(df), int(orph.sum()))
    ctx.log_rows("FI-10", T, kk[orph])
    flag("FI-10", orph)

    for c in INT_COLS:
        df[c] = df[c].astype("Int64")
    df["dq_rules"] = flags.loc[df.index]
    unres = pd.Series(False, index=df.index)
    unres[unresolved[unresolved].index] = True
    df["dq_status"] = np.where(df["dq_rules"] == "", "clean",
                               np.where(unres | df["dq_rules"].str.contains("FI-07|FI-08|FI-10"), "flagged", "corrected"))
    ctx.notes["inventory_missing_weeks"] = miss_df
    return df.reset_index(drop=True)


def reconcile_pos_to_stock(sales: pd.DataFrame, inventory: pd.DataFrame, dim_date: pd.DataFrame,
                           last_week_end: pd.Timestamp) -> dict:
    """TC-07: compare POS units with stock-system sold units per store-SKU-week."""
    wk_end = dim_date.set_index("date")["retail_week_start"] + pd.Timedelta(days=6)
    s = sales.assign(snapshot_date=sales["transaction_date"].map(wk_end))
    s = s[s["snapshot_date"] <= last_week_end]
    units = s.groupby(["store_id", "product_id", "snapshot_date"])["quantity"].sum()
    inv = inventory[inventory["snapshot_date"] <= last_week_end].set_index(INV_KEY)["sold_qty"]
    inv = inv[~inv.index.duplicated()]
    j = pd.concat([units.rename("pos"), inv.rename("stock")], axis=1).fillna(0)
    j = j[(j["pos"] != 0) | (j["stock"] != 0)]
    mism = j[j["pos"] != j["stock"]]
    return {"cells": int(len(j)), "matching": int(len(j) - len(mism)), "mismatched": int(len(mism)),
            "match_rate": float(1 - len(mism) / len(j)), "pos_units": float(j["pos"].sum()),
            "stock_units": float(j["stock"].sum()), "mismatch_frame": mism.reset_index()}
