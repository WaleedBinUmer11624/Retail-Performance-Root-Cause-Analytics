"""Checks and treatments for POS sales lines (fact_sales + fact_sales_late_batch).

Order of treatment matters and is fixed:
  union main + late file -> de-duplicate -> keys (date, store) -> sign errors -> bulk quantities
  -> product keys -> missing price/discount -> reference-price checks -> line arithmetic
  -> category -> promotions -> receipt integrity -> life cycle -> final gate
Every step writes the rows it touched to the issue log and the revenue before/after to the audit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import (DQContext, id_date, id_store, is_blank, key_of, matches, parse_date_dmy, parse_date_iso,
                   to_num)
from .dimensions import UNKNOWN, category_map

KEY = ["transaction_id", "line_number"]
MONEY = ["unit_price", "discount", "revenue", "unit_cost", "cost", "margin"]
STATUS_ORDER = ["imputed", "corrected", "flagged", "standardised", "clean"]


class _Tags:
    """Collects rule IDs per row so each curated row carries its own DQ history."""

    def __init__(self):
        self.parts = []

    def add(self, rule_id: str, idx):
        if len(idx):
            self.parts.append(pd.Series(rule_id, index=pd.Index(idx)))

    def frame(self, index) -> pd.Series:
        if not self.parts:
            return pd.Series("", index=index)
        s = pd.concat(self.parts)
        s = s[s.index.isin(index)]
        return s.groupby(level=0).agg(lambda x: ";".join(sorted(set(x)))).reindex(index, fill_value="")


def _rev(df):
    return round(float(df["revenue"].fillna(0).sum()), 2)


def clean_sales(main: pd.DataFrame, late: pd.DataFrame, ctx: DQContext, stores: set, dim_product: pd.DataFrame,
                promotions: pd.DataFrame, till_ref: pd.DataFrame, raw_returns: pd.DataFrame) -> pd.DataFrame:
    """Merge the main and late extracts, apply every fact_sales rule and return curated sales."""
    cfg, tol = ctx.cfg, ctx.cfg["tolerances"]
    T = "fact_sales"
    tags = _Tags()

    # ---------------- load: typed working columns next to the raw text
    df = pd.concat([main, late], ignore_index=True)
    df["line_number"] = to_num(df["line_number"]).astype("Int64")
    raw_text = df[["transaction_date", "store_id", "product_id", "category", "quantity", "unit_price", "discount",
                   "revenue", "promotion_id"]].copy()
    for c in ["quantity"] + MONEY:
        df[c] = to_num(df[c])
    df["extract_timestamp"] = pd.to_datetime(df["extract_timestamp"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    df["rk"] = key_of(df, KEY)
    main_rev = _rev(df[df["source_file"] == main["source_file"].iloc[0]])

    # ---------------- TC-01 late-arriving file
    idd = id_date(df["transaction_id"])
    lag = (df["extract_timestamp"].dt.normalize() - idd).dt.days
    late_m = lag > cfg["timeliness"]["expected_max_lag_days"]
    df["is_late_arriving"] = late_m
    df["extract_lag_days"] = lag
    in_late_file = df["source_file"] == late["source_file"].iloc[0]
    ctx.result("TC-01", len(df), int(late_m.sum()), float(df.loc[late_m, "revenue"].sum()),
               evidence=(f"{int(in_late_file.sum()):,} lines in the late file, extract lag "
                         f"{int(lag[in_late_file].min())} to {int(lag[in_late_file].max())} days; main extract lag "
                         f"{int(lag[~in_late_file].min())} to {int(lag[~in_late_file].max())} days; "
                         f"late lines sharing a key with the main extract: "
                         f"{int(df.loc[in_late_file, 'rk'].isin(df.loc[~in_late_file, 'rk']).sum())}"))
    ctx.log_rows("TC-01", T, df.loc[late_m, "rk"], "extract_timestamp", df.loc[late_m, "extract_timestamp"],
                 action="INCLUDE (flag is_late_arriving)")
    tags.add("TC-01", df.index[late_m])
    ctx.audit_step(T, "TC-01", "INCLUDE", int(in_late_file.sum()), "all", "sales revenue EUR", main_rev, _rev(df),
                   note="late sales file appended to the main extract")

    # ---------------- FS-01 duplicates: keep the earliest extracted copy
    before = _rev(df)
    df["_ord"] = np.arange(len(df))
    order = df.sort_values(["rk", "extract_timestamp", "_ord"])
    dup = order.duplicated("rk", keep="first")
    dup_idx = order.index[dup.to_numpy()]
    ctx.result("FS-01", len(df), len(dup_idx), float(df.loc[dup_idx, "revenue"].sum()),
               evidence=f"{df.loc[dup_idx, 'transaction_id'].nunique():,} receipts re-sent")
    ctx.log_rows("FS-01", T, df.loc[dup_idx, "rk"], "", action="DEDUPLICATE (later copy quarantined)")
    ctx.add_quarantine(T, main.iloc[:0].reindex(columns=main.columns).pipe(
        lambda _: _raw_rows(df, dup_idx, main, late)), "FS-01", "duplicate line, earlier copy kept")
    df = df.drop(index=dup_idx)
    ctx.audit_step(T, "FS-01", "DEDUPLICATE", len(dup_idx), "all", "sales revenue EUR", before, _rev(df))
    all_keys = set(df["rk"])            # every distinct sale line received (used by returns)

    # ---------------- FS-02 / FS-03 dates (authoritative: date inside the transaction ID)
    idd = id_date(df["transaction_id"])
    ok_tid = matches(df["transaction_id"], cfg["formats"]["transaction_id"]) & idd.notna()
    iso = parse_date_iso(df["transaction_date"])
    dmy = parse_date_dmy(df["transaction_date"])
    start, end = pd.Timestamp(cfg["period"]["start"]), pd.Timestamp(cfg["period"]["end"])
    legacy = iso.isna() & dmy.notna() & (dmy == idd)
    parsed = iso.fillna(dmy)
    agree = parsed.notna() & parsed.between(start, end)
    agree_rate = float((parsed[agree] == idd[agree]).mean())
    bad_date = ~(parsed.notna() & parsed.between(start, end) & (parsed == idd))
    ctx.result("FS-02", len(df), int(legacy.sum()), evidence="every legacy date equals the ID date")
    ctx.log_rows("FS-02", T, df.loc[legacy, "rk"], "transaction_date", df.loc[legacy, "transaction_date"],
                 idd[legacy].dt.strftime("%Y-%m-%d"))
    tags.add("FS-02", df.index[legacy])
    fixable = bad_date & ~legacy & ok_tid
    ctx.result("FS-03", len(df), int((bad_date & ~legacy).sum()), float(df.loc[bad_date & ~legacy, "revenue"].sum()),
               evidence=f"{agree_rate:.4%} of valid in-period dates equal the ID date; malformed IDs: "
                        f"{int((~ok_tid).sum())}")
    ctx.log_rows("FS-03", T, df.loc[fixable, "rk"], "transaction_date", df.loc[fixable, "transaction_date"],
                 idd[fixable].dt.strftime("%Y-%m-%d"))
    tags.add("FS-03", df.index[fixable])
    df["transaction_date"] = idd
    ctx.audit_step(T, "FS-02", "STANDARDISE", int(legacy.sum()), "transaction_date")
    ctx.audit_step(T, "FS-03", "CORRECT", int(fixable.sum()), "transaction_date", note="date taken from transaction_id")
    unrec = ~ok_tid
    if unrec.any():
        ctx.add_quarantine(T, _raw_rows(df, df.index[unrec], main, late), "FS-03", "no valid date and malformed ID")
        df = df[~unrec]

    # ---------------- FS-04 store
    ids = id_store(df["transaction_id"])
    bad = ~df["store_id"].isin(stores) | (df["store_id"] != ids)
    ctx.result("FS-04", len(df), int(bad.sum()), float(df.loc[bad, "revenue"].sum()),
               evidence=f"blank {int(is_blank(df.loc[bad, 'store_id']).sum())}, unknown code "
                        f"{int((~is_blank(df.loc[bad, 'store_id']) & ~df.loc[bad, 'store_id'].isin(stores)).sum())}, "
                        f"different known store {int((df.loc[bad, 'store_id'].isin(stores)).sum())}")
    ctx.log_rows("FS-04", T, df.loc[bad, "rk"], "store_id", df.loc[bad, "store_id"], ids[bad])
    tags.add("FS-04", df.index[bad])
    df.loc[bad, "store_id"] = ids[bad]
    ctx.audit_step(T, "FS-04", "CORRECT", int(bad.sum()), "store_id", note="store taken from transaction_id")

    # ---------------- FS-08 whole line sign-inverted
    before = _rev(df)
    neg = df["quantity"] < 0
    ctx.result("FS-08", len(df), int(neg.sum()), float(df.loc[neg, "revenue"].abs().sum()))
    ctx.log_rows("FS-08", T, df.loc[neg, "rk"], "quantity", df.loc[neg, "quantity"], -df.loc[neg, "quantity"])
    for c in ("quantity", "discount", "revenue", "cost", "margin"):
        df.loc[neg, c] = -df.loc[neg, c]
    df.loc[neg, "discount"] = df.loc[neg, "discount"].abs()
    tags.add("FS-08", df.index[neg])
    ctx.audit_step(T, "FS-08", "CORRECT", int(neg.sum()), "quantity, discount, revenue, cost, margin",
                   "sales revenue EUR", before, _rev(df), note="sign inverted back")

    # ---------------- FS-12 negative price (money fields inverted, quantity positive)
    before = _rev(df)
    negp = df["unit_price"] < 0
    ctx.result("FS-12", len(df), int(negp.sum()), float(df.loc[negp, "revenue"].abs().sum()))
    ctx.log_rows("FS-12", T, df.loc[negp, "rk"], "unit_price", df.loc[negp, "unit_price"], -df.loc[negp, "unit_price"])
    for c in ("unit_price", "discount", "revenue"):
        df.loc[negp, c] = df.loc[negp, c].abs()
    df.loc[negp, "margin"] = (df.loc[negp, "revenue"] - df.loc[negp, "cost"]).round(2)
    tags.add("FS-12", df.index[negp])
    ctx.audit_step(T, "FS-12", "CORRECT", int(negp.sum()), "unit_price, discount, revenue, margin",
                   "sales revenue EUR", before, _rev(df))

    # ---------------- FS-09 bulk quantities -> quarantine
    before = _rev(df)
    bulk = df["quantity"] > tol["max_plausible_line_quantity"]
    ctx.result("FS-09", len(df), int(bulk.sum()), float(df.loc[bulk, "revenue"].sum()),
               evidence="quantities: " + ", ".join(str(int(x)) for x in sorted(df.loc[bulk, "quantity"].unique())))
    ctx.log_rows("FS-09", T, df.loc[bulk, "rk"], "quantity", df.loc[bulk, "quantity"], action="QUARANTINE")
    ctx.add_quarantine(T, _raw_rows(df, df.index[bulk], main, late), "FS-09", "implausible bulk quantity")
    df = df[~bulk]
    ctx.audit_step(T, "FS-09", "QUARANTINE", int(bulk.sum()), "all", "sales revenue EUR", before, _rev(df))

    # ---------------- FS-05 / FS-06 product keys
    products = set(dim_product["product_id"]) - {UNKNOWN}
    blank = is_blank(df["product_id"])
    r = raw_returns[~is_blank(raw_returns["original_transaction_id"]) & ~is_blank(raw_returns["product_id"])]
    rmap = (r.assign(rk=r["original_transaction_id"] + "|" + r["original_line_number"])
            .groupby("rk")["product_id"].agg(lambda x: x.iloc[0] if x.nunique() == 1 else None).dropna())
    rec = df.loc[blank, "rk"].map(rmap)
    rec = rec[rec.isin(products)]
    ctx.result("FS-05", len(df), int(blank.sum()), float(df.loc[blank, "revenue"].sum()),
               evidence=f"{len(rec)} restored from the linked return, {int(blank.sum()) - len(rec)} set to UNKNOWN")
    ctx.log_rows("FS-05", T, df.loc[rec.index, "rk"], "product_id", "", rec, action="CORRECT (from linked return)")
    unk_blank = df.index[blank].difference(rec.index)
    ctx.log_rows("FS-05", T, df.loc[unk_blank, "rk"], "product_id", "", UNKNOWN, action="UNKNOWN_MEMBER")
    df.loc[rec.index, "product_id"] = rec
    df.loc[unk_blank, "product_id"] = UNKNOWN
    tags.add("FS-05", df.index[blank])
    orphan = ~df["product_id"].isin(products) & (df["product_id"] != UNKNOWN)
    rec6 = df.loc[orphan, "rk"].map(rmap)
    rec6 = rec6[rec6.isin(products)]
    ctx.result("FS-06", len(df), int(orphan.sum()), float(df.loc[orphan, "revenue"].sum()),
               evidence=f"{df.loc[orphan, 'product_id'].nunique()} unknown product codes; {len(rec6)} restored from the "
                        f"linked return, {int(orphan.sum()) - len(rec6)} set to UNKNOWN")
    ctx.log_rows("FS-06", T, df.loc[rec6.index, "rk"], "product_id", df.loc[rec6.index, "product_id"], rec6,
                 action="CORRECT (from linked return)")
    un6 = df.index[orphan].difference(rec6.index)
    ctx.log_rows("FS-06", T, df.loc[un6, "rk"], "product_id", df.loc[un6, "product_id"], UNKNOWN)
    df.loc[rec6.index, "product_id"] = rec6
    df.loc[un6, "product_id"] = UNKNOWN
    tags.add("FS-06", df.index[orphan])
    ctx.audit_step(T, "FS-05", "CORRECT/UNKNOWN_MEMBER", int(blank.sum()), "product_id")
    ctx.audit_step(T, "FS-06", "UNKNOWN_MEMBER", int(orphan.sum()), "product_id")

    # ---------------- FS-10 / FS-15 missing price / discount
    mp = df["unit_price"].isna() & df["revenue"].notna() & df["discount"].notna() & (df["quantity"] > 0)
    newp = ((df["revenue"] + df["discount"]) / df["quantity"]).round(2)
    ctx.result("FS-10", len(df), int(df["unit_price"].isna().sum()))
    ctx.log_rows("FS-10", T, df.loc[mp, "rk"], "unit_price", "", newp[mp])
    df.loc[mp, "unit_price"] = newp[mp]
    tags.add("FS-10", df.index[mp])
    md = df["discount"].isna() & df["revenue"].notna() & df["unit_price"].notna()
    newd = (df["quantity"] * df["unit_price"] - df["revenue"]).round(2).clip(lower=0)
    ctx.result("FS-15", len(df), int(df["discount"].isna().sum()),
               evidence=f"{int((newd[md] > 0).sum())} of the restored discounts are non-zero")
    ctx.log_rows("FS-15", T, df.loc[md, "rk"], "discount", "", newd[md])
    df.loc[md, "discount"] = newd[md]
    tags.add("FS-15", df.index[md])
    ctx.audit_step(T, "FS-10", "CORRECT", int(mp.sum()), "unit_price", note="(revenue + discount) / quantity")
    ctx.audit_step(T, "FS-15", "CORRECT", int(md.sum()), "discount", note="quantity x price - revenue")

    # ---------------- reference-price checks: FS-13, FS-11, FS-14, FS-28
    year = df["transaction_id"].str.slice(4, 8)
    ref = till_ref.set_index(["product_id", "year"])["ref_price"]
    df["ref_price"] = pd.MultiIndex.from_arrays([df["product_id"], year]).map(ref)
    ratio = df["unit_price"] / df["ref_price"]

    before = _rev(df)
    lo, hi = tol["decimal_shift_ratio"]
    shift = ratio.between(lo, hi)
    ctx.result("FS-13", len(df), int(shift.sum()), float(df.loc[shift, "revenue"].sum()),
               evidence=f"price/reference ratio {ratio[shift].min():.1f} to {ratio[shift].max():.1f}")
    newp = (df.loc[shift, "unit_price"] / 100).round(2)
    ctx.log_rows("FS-13", T, df.loc[shift, "rk"], "unit_price", df.loc[shift, "unit_price"], newp)
    df.loc[shift, "unit_price"] = newp
    gross = df["quantity"] * df["unit_price"]
    scaled_disc = shift & (df["discount"] > tol["max_discount_share"] * gross)
    df.loc[scaled_disc, "discount"] = (df.loc[scaled_disc, "discount"] / 100).round(2)
    df.loc[shift, "revenue"] = (df.loc[shift, "quantity"] * df.loc[shift, "unit_price"] - df.loc[shift, "discount"]).round(2)
    df.loc[shift, "margin"] = (df.loc[shift, "revenue"] - df.loc[shift, "cost"]).round(2)
    tags.add("FS-13", df.index[shift])
    ctx.audit_step(T, "FS-13", "CORRECT", int(shift.sum()), "unit_price, revenue, margin", "sales revenue EUR",
                   before, _rev(df), note=f"price / 100; discount also rescaled on {int(scaled_disc.sum())} lines")

    before = _rev(df)
    zero = (df["unit_price"] == 0)
    can = zero & df["ref_price"].notna()
    pk = promotions.set_index(["promotion_id", "store_id", "product_id"])["discount_pct"]
    pk = pk[~pk.index.duplicated()]
    depth = pd.MultiIndex.from_arrays([df["promotion_id"], df["store_id"], df["product_id"]]).map(pk)
    depth = pd.Series(depth, index=df.index).fillna(0.0)
    ctx.result("FS-11", len(df), int(zero.sum()), float((df.loc[can, "quantity"] * df.loc[can, "ref_price"]).sum()),
               evidence=f"{int(can.sum())} imputed; {int((can & (depth > 0)).sum())} with promotion depth; "
                        f"{int((zero & ~can).sum())} without a reference price quarantined")
    df.loc[can, "unit_price"] = df.loc[can, "ref_price"]
    df.loc[can, "discount"] = (df.loc[can, "quantity"] * df.loc[can, "unit_price"] * depth[can]).round(2)
    df.loc[can, "revenue"] = (df.loc[can, "quantity"] * df.loc[can, "unit_price"] - df.loc[can, "discount"]).round(2)
    df.loc[can, "margin"] = (df.loc[can, "revenue"] - df.loc[can, "cost"]).round(2)
    ctx.log_rows("FS-11", T, df.loc[can, "rk"], "unit_price", "0", df.loc[can, "unit_price"], action="IMPUTE")
    tags.add("FS-11", df.index[can])
    df["is_imputed"] = False
    df.loc[can, "is_imputed"] = True
    if (zero & ~can).any():
        ctx.add_quarantine(T, _raw_rows(df, df.index[zero & ~can], main, late), "FS-11", "zero price, no reference")
        df = df[~(zero & ~can)]
    ctx.audit_step(T, "FS-11", "IMPUTE", int(can.sum()), "unit_price, discount, revenue, margin", "sales revenue EUR",
                   before, _rev(df), note="reference price x quantity less promotion depth")

    ratio = df["unit_price"] / df["ref_price"]
    dev = df["ref_price"].notna() & ((ratio - 1).abs() > tol["price_reference"])
    ctx.result("FS-14", len(df), int(dev.sum()), float(df.loc[dev, "revenue"].sum()))
    ctx.log_rows("FS-14", T, df.loc[dev, "rk"], "unit_price", df.loc[dev, "unit_price"])
    tags.add("FS-14", df.index[dev])
    noref = df["ref_price"].isna()
    ctx.result("FS-28", len(df), int(noref.sum()), float(df.loc[noref, "revenue"].sum()))

    # ---------------- FS-17 / FS-18 line arithmetic
    before = _rev(df)
    calc = (df["quantity"] * df["unit_price"] - df["discount"]).round(2)
    mism = (calc - df["revenue"]).abs() > tol["money"]
    confirmed = mism & ((calc - (df["cost"] + df["margin"])).abs() <= tol["money"])
    ctx.result("FS-17", len(df), int(mism.sum()), float((df.loc[mism, "revenue"] - calc[mism]).abs().sum()),
               evidence=f"{int(confirmed.sum())} confirmed by cost + margin and corrected; "
                        f"{int((mism & ~confirmed).sum())} unconfirmed and quarantined")
    ctx.log_rows("FS-17", T, df.loc[mism, "rk"], "revenue", df.loc[mism, "revenue"], calc[mism].where(confirmed[mism]))
    df.loc[confirmed, "revenue"] = calc[confirmed]
    tags.add("FS-17", df.index[confirmed])
    unconf = mism & ~confirmed
    if unconf.any():
        ctx.add_quarantine(T, _raw_rows(df, df.index[unconf], main, late), "FS-17", "revenue does not reconcile")
        df = df[~unconf]
    ctx.audit_step(T, "FS-17", "CORRECT", int(confirmed.sum()), "revenue", "sales revenue EUR", before, _rev(df),
                   note="revenue recomputed from confirmed components")
    mg = (df["revenue"] - df["cost"]).round(2)
    badm = (mg - df["margin"]).abs() > tol["money"]
    badc = ((df["quantity"] * df["unit_cost"]).round(2) - df["cost"]).abs() > tol["money"]
    ctx.result("FS-18", len(df), int((badm | badc).sum()), evidence=f"cost != quantity x unit_cost on {int(badc.sum())}")
    ctx.log_rows("FS-18", T, df.loc[badm, "rk"], "margin", df.loc[badm, "margin"], mg[badm])
    df.loc[badm, "margin"] = mg[badm]
    tags.add("FS-18", df.index[badm | badc])
    ctx.audit_step(T, "FS-18", "CORRECT", int(badm.sum()), "margin", note="margin = revenue - cost")

    # ---------------- FS-16 discount range
    gross = df["quantity"] * df["unit_price"]
    bad = (df["discount"] < -tol["money"]) | (df["discount"] > tol["max_discount_share"] * gross + tol["money"])
    ctx.result("FS-16", len(df), int(bad.sum()))
    ctx.log_rows("FS-16", T, df.loc[bad, "rk"], "discount", df.loc[bad, "discount"])
    tags.add("FS-16", df.index[bad])

    # ---------------- FS-07 category from the product master
    pcat = dim_product.set_index("product_id")["category"]
    cmap = category_map(df["category"], cfg).set_index("raw_label")["canonical"]
    pos_canon = df["category"].map(cmap)
    final = df["product_id"].map(pcat)
    final = final.where(df["product_id"] != UNKNOWN, pos_canon.fillna("Unknown"))
    diff = df["category"] != final
    conflict = diff & pos_canon.notna() & (pos_canon != final) & (df["product_id"] != UNKNOWN)
    ctx.result("FS-07", len(df), int(diff.sum()),
               evidence=f"{int(conflict.sum())} lines whose standardised POS label names a different category; "
                        f"variants: " + ", ".join(f"'{k}'" for k, v in cmap.items() if k != v))
    ctx.log_rows("FS-07", T, df.loc[diff, "rk"], "category", df.loc[diff, "category"], final[diff])
    df["category"] = final
    tags.add("FS-07", df.index[diff])
    ctx.audit_step(T, "FS-07", "STANDARDISE", int(diff.sum()), "category", note="category from product master")

    # ---------------- promotions FS-19 .. FS-23
    has = ~is_blank(df["promotion_id"])
    pids = set(promotions["promotion_id"])
    unknown_p = has & ~df["promotion_id"].isin(pids)
    u = df.loc[unknown_p, ["rk", "store_id", "product_id", "transaction_date", "quantity", "unit_price", "discount"]]
    u = u.reset_index().merge(promotions[["promotion_id", "store_id", "product_id", "start_date", "end_date", "discount_pct"]],
                              on=["store_id", "product_id"], how="left")
    u = u[(u["transaction_date"] >= u["start_date"]) & (u["transaction_date"] <= u["end_date"])
          & ((u["discount"] / (u["quantity"] * u["unit_price"]) - u["discount_pct"]).abs() <= 0.011)]
    u = u.groupby("index").filter(lambda x: len(x) == 1).set_index("index")
    recovered = u["promotion_id"]
    no_disc = unknown_p & (df["discount"] <= 0) & ~df.index.isin(recovered.index)
    to_unknown = unknown_p & ~no_disc & ~df.index.isin(recovered.index)
    ctx.result("FS-19", int(has.sum()), int(unknown_p.sum()), float(df.loc[unknown_p, "revenue"].sum()),
               evidence=f"{df.loc[unknown_p, 'promotion_id'].nunique()} unknown codes; {len(recovered)} restored from the "
                        f"one active promotion whose depth matches the discount; {int(no_disc.sum())} cleared (no discount, "
                        f"so not a promoted line); {int(to_unknown.sum())} set to UNKNOWN")
    ctx.log_rows("FS-19", T, df.loc[recovered.index, "rk"], "promotion_id", df.loc[recovered.index, "promotion_id"],
                 recovered, action="CORRECT (active promotion, depth matches)")
    ctx.log_rows("FS-19", T, df.loc[no_disc, "rk"], "promotion_id", df.loc[no_disc, "promotion_id"], "",
                 action="CORRECT (cleared, no discount)")
    ctx.log_rows("FS-19", T, df.loc[to_unknown, "rk"], "promotion_id", df.loc[to_unknown, "promotion_id"], UNKNOWN,
                 action="UNKNOWN_MEMBER")
    df.loc[recovered.index, "promotion_id"] = recovered
    df.loc[no_disc, "promotion_id"] = ""
    df.loc[to_unknown, "promotion_id"] = UNKNOWN
    tags.add("FS-19", df.index[unknown_p])
    ctx.audit_step(T, "FS-19", "CORRECT/UNKNOWN_MEMBER", int(unknown_p.sum()), "promotion_id")

    has = ~is_blank(df["promotion_id"])
    known = has & (df["promotion_id"] != UNKNOWN)
    testable = known & (df["product_id"] != UNKNOWN)
    pk3 = set(zip(promotions["promotion_id"], promotions["store_id"], promotions["product_id"]))
    notin = testable & pd.Series([t not in pk3 for t in zip(df["promotion_id"], df["store_id"], df["product_id"])],
                                 index=df.index)
    # a promotion row quarantined for an invalid product (FP-04) is restored when the POS lines of that
    # promotion and store identify exactly one product missing from the promotion
    orphans = pd.concat(ctx.quarantine.get("fact_promotions", [pd.DataFrame(columns=["dq_rule_id"])]))
    orphans = orphans[orphans["dq_rule_id"] == "FP-04"]
    restored = []
    for _, o in orphans.iterrows():
        m = notin & (df["promotion_id"] == o["promotion_id"]) & (df["store_id"] == o["store_id"])
        cand = df.loc[m, "product_id"].unique()
        if len(cand) == 1:
            restored.append({**o.to_dict(), "product_id_raw": o["product_id"], "product_id": cand[0],
                             "pos_lines": int(m.sum())})
            notin &= ~m
    ctx.notes["restored_promotions"] = restored
    ctx.result("FS-20", int(known.sum()), int(notin.sum()),
               evidence=f"{int((known & ~testable).sum())} promoted lines on the UNKNOWN product cannot be tested; "
                        f"{sum(r['pos_lines'] for r in restored)} lines resolved by restoring {len(restored)} promotion rows "
                        "(FP-04)")
    ctx.log_rows("FS-20", T, df.loc[notin, "rk"], "promotion_id", df.loc[notin, "promotion_id"])
    tags.add("FS-20", df.index[notin])
    nod = known & (df["discount"] <= 0)
    ctx.result("FS-21", int(known.sum()), int(nod.sum()))
    ctx.log_rows("FS-21", T, df.loc[nod, "rk"], "discount", df.loc[nod, "discount"])
    tags.add("FS-21", df.index[nod])
    win = promotions.groupby("promotion_id").agg(s=("start_date", "min"), e=("end_date", "max"))
    ps, pe = df["promotion_id"].map(win["s"]), df["promotion_id"].map(win["e"])
    outw = known & ((df["transaction_date"] < ps) | (df["transaction_date"] > pe))
    ctx.result("FS-22", int(known.sum()), int(outw.sum()))
    ctx.log_rows("FS-22", T, df.loc[outw, "rk"], "transaction_date", df.loc[outw, "transaction_date"])
    tags.add("FS-22", df.index[outw])
    md = ~has & (df["discount"] > 0)
    ctx.result("FS-23", len(df), int(md.sum()), float(df.loc[md, "discount"].sum()),
               evidence="discount / gross on these lines: " + ", ".join(
                   f"{k:.0%} ({v})" for k, v in (df.loc[md, "discount"] / (df.loc[md, "quantity"] * df.loc[md, "unit_price"]))
                   .round(2).value_counts().head(4).items()))

    # ---------------- info: cost history, negative margin
    mcost = df["product_id"].map(dim_product.set_index("product_id")["unit_cost"])
    cdiff = mcost.notna() & ((df["unit_cost"] - mcost).abs() > tol["money"])
    ctx.result("FS-24", len(df), int(cdiff.sum()), evidence=f"{cdiff[df['transaction_date'].dt.year == 2024].mean():.1%} "
               f"of 2024 lines, {cdiff[df['transaction_date'].dt.year == 2025].mean():.1%} of 2025 lines")
    negm = df["margin"] < 0
    ctx.result("FS-25", len(df), int(negm.sum()), evidence=f"{(negm & (df['discount'] > 0)).mean() / max(negm.mean(), 1e-9):.1%}"
               " of them are discounted lines")

    # ---------------- FS-26 receipt integrity
    g = df.groupby("transaction_id")
    agg = g.agg(ns=("store_id", "nunique"), nd=("transaction_date", "nunique"), nt=("transaction_time", "nunique"),
                mn=("line_number", "min"), mx=("line_number", "max"), n=("line_number", "size"))
    bad_t = agg[(agg["ns"] > 1) | (agg["nd"] > 1) | (agg["nt"] > 1)].index
    # line-number gaps are expected where a line was quarantined, so test on all distinct lines received
    allk = pd.Series(sorted(all_keys))
    lg = pd.DataFrame({"t": allk.str.split("|").str[0], "l": allk.str.split("|").str[1].astype(int)}) \
        .groupby("t")["l"].agg(["min", "max", "size"])
    gap_t = lg[(lg["min"] != 1) | (lg["max"] != lg["size"])].index
    m = df["transaction_id"].isin(set(bad_t) | set(gap_t))
    ctx.result("FS-26", len(agg), len(set(bad_t) | set(gap_t)),
               evidence=f"{len(bad_t)} receipts with mixed store/date/time; {len(gap_t)} with line-number gaps")
    ctx.log_rows("FS-26", T, df.loc[m, "rk"])
    tags.add("FS-26", df.index[m])

    # ---------------- FS-27 life cycle
    pl = dim_product.set_index("product_id")
    la, di = df["product_id"].map(pl["launch_date"]), df["product_id"].map(pl["discontinued_date"])
    lc = (df["transaction_date"] < la) | (df["transaction_date"] > di + pd.Timedelta(days=7))
    ctx.result("FS-27", len(df), int(lc.sum()))
    ctx.log_rows("FS-27", T, df.loc[lc, "rk"], "transaction_date", df.loc[lc, "transaction_date"])
    tags.add("FS-27", df.index[lc])

    # ---------------- final gate: no curated line may have a missing money field
    miss = df[["quantity"] + MONEY].isna().any(axis=1)
    if miss.any():
        ctx.add_quarantine(T, _raw_rows(df, df.index[miss], main, late), "FS-10", "money field unrecoverable")
        df = df[~miss]

    df["dq_rules"] = tags.frame(df.index)
    df["dq_status"] = _status(df["dq_rules"], ctx)
    df["promotion_id"] = df["promotion_id"].where(~is_blank(df["promotion_id"]), None)
    df["quantity"] = df["quantity"].astype(int)
    cols = ["transaction_id", "line_number", "transaction_date", "transaction_time", "store_id", "product_id", "category",
            "quantity", "unit_price", "discount", "revenue", "unit_cost", "cost", "margin", "promotion_id",
            "extract_batch_id", "extract_timestamp", "extract_lag_days", "is_late_arriving", "is_imputed",
            "dq_status", "dq_rules", "source_file", "source_row"]
    ctx.notes["sales_all_keys"] = all_keys
    ctx.notes["sales_raw_text"] = raw_text
    return df[cols].sort_values(KEY).reset_index(drop=True)


def _raw_rows(df, idx, main, late):
    """Original raw text for quarantined rows (quarantine keeps the record exactly as received)."""
    src = df.loc[idx, ["source_file", "source_row"]]
    both = pd.concat([main, late], ignore_index=True).set_index(["source_file", "source_row"])
    return both.loc[list(zip(src["source_file"], src["source_row"]))].reset_index()


def _status(rules: pd.Series, ctx: DQContext) -> pd.Series:
    def one(r):
        if not r:
            return "clean"
        tr = {ctx.catalogue[x]["treatment"] for x in r.split(";")}
        if "IMPUTE" in tr:
            return "imputed"
        if tr & {"CORRECT", "UNKNOWN_MEMBER"}:
            return "corrected"
        if tr & {"FLAG", "INCLUDE"}:
            return "flagged"
        return "standardised"
    return rules.map(one)
