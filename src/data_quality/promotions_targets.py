"""Checks and treatments for fact_promotions and fact_targets."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import DQContext, key_of, parse_date_iso, to_num

PROMO_KEY = ["promotion_id", "product_id", "store_id"]
TARGET_KEY = ["store_id", "retail_year", "retail_week"]


def clean_promotions(raw: pd.DataFrame, ctx: DQContext, stores: set, products: set) -> pd.DataFrame:
    """Apply the fact_promotions rules (FP-*) and return curated promotions."""
    cfg = ctx.cfg
    df = raw.copy()
    n = len(df)
    data_cols = [c for c in df.columns if c not in ("source_file", "source_row")]

    # FP-01 exact duplicates
    dup = df.duplicated(subset=data_cols, keep="first")
    ctx.result("FP-01", n, int(dup.sum()))
    ctx.log_rows("FP-01", "fact_promotions", key_of(df[dup], PROMO_KEY))
    ctx.add_quarantine("fact_promotions", df[dup], "FP-01", "exact duplicate row")
    ctx.audit_step("fact_promotions", "FP-01", "DEDUPLICATE", int(dup.sum()), metric="rows", before=n,
                   after=n - int(dup.sum()))
    df = df[~dup].copy()

    df["start_date"] = parse_date_iso(df["start_date"])
    df["end_date"] = parse_date_iso(df["end_date"])
    df["discount_pct"] = to_num(df["discount_pct"])

    # FP-02 end before start: restore from the promotion's modal window
    bad = (df["end_date"] < df["start_date"]) | df["start_date"].isna() | df["end_date"].isna()
    good = df[~bad]
    win = good.groupby("promotion_id").agg(s=("start_date", lambda x: x.mode().iloc[0]),
                                           e=("end_date", lambda x: x.mode().iloc[0]))
    fixable = bad & df["promotion_id"].isin(win.index)
    k = key_of(df[bad], PROMO_KEY)
    ctx.result("FP-02", len(df), int(bad.sum()))
    ctx.log_rows("FP-02", "fact_promotions", k, "start_date/end_date",
                 df.loc[bad, "start_date"].dt.strftime("%Y-%m-%d") + " to " + df.loc[bad, "end_date"].dt.strftime("%Y-%m-%d"),
                 df.loc[bad, "promotion_id"].map(win["s"]).dt.strftime("%Y-%m-%d") + " to "
                 + df.loc[bad, "promotion_id"].map(win["e"]).dt.strftime("%Y-%m-%d"))
    df.loc[fixable, "start_date"] = df.loc[fixable, "promotion_id"].map(win["s"])
    df.loc[fixable, "end_date"] = df.loc[fixable, "promotion_id"].map(win["e"])
    unfix = bad & ~fixable
    ctx.add_quarantine("fact_promotions", raw.loc[df.index[unfix]], "FP-02", "end before start and no other row to restore from")
    df = df[~unfix]
    ctx.audit_step("fact_promotions", "FP-02", "CORRECT", int(fixable.sum()), "start_date, end_date",
                   note="window restored from the promotion's other rows")

    # FP-03 header consistency
    hdr = df.groupby("promotion_id").agg(**{c: (c, "nunique") for c in
                                           ("promotion_name", "promotion_type", "start_date", "end_date")})
    incons = hdr[(hdr > 1).any(axis=1)].index
    m = df["promotion_id"].isin(incons)
    depth = df.groupby("promotion_id").agg(n=("discount_pct", "nunique"), t=("promotion_type", "first"))
    multi = depth[depth["n"] > 1]
    ctx.result("FP-03", df["promotion_id"].nunique(), len(incons),
               evidence=(", ".join(incons[:10]) or "none") + f"; {len(multi)} promotions use more than one depth "
               f"(types: {', '.join(sorted(multi['t'].unique()))}), accepted as tiered pricing")
    ctx.log_rows("FP-03", "fact_promotions", key_of(df[m], PROMO_KEY))

    # FP-04 orphans
    orphan = ~df["product_id"].isin(products) | ~df["store_id"].isin(stores)
    ctx.result("FP-04", len(df), int(orphan.sum()))
    ctx.log_rows("FP-04", "fact_promotions", key_of(df[orphan], PROMO_KEY), "product_id", df.loc[orphan, "product_id"])
    ctx.add_quarantine("fact_promotions", raw.loc[df.index[orphan]], "FP-04", "product or store not in the dimensions")
    ctx.notes["promo_orphan_count"] = int(orphan.sum())
    ctx.audit_step("fact_promotions", "FP-04", "QUARANTINE", int(orphan.sum()), "product_id")
    df = df[~orphan].copy()

    m = ~df["discount_pct"].between(0.0001, cfg["tolerances"]["max_discount_share"]) | \
        ~df["promotion_type"].isin(cfg["domains"]["promotion_types"])
    ctx.result("FP-05", len(df), int(m.sum()))
    ctx.log_rows("FP-05", "fact_promotions", key_of(df[m], PROMO_KEY))

    end = pd.Timestamp(cfg["period"]["end"])
    m = df["end_date"] > end
    ctx.result("FP-06", len(df), int(m.sum()), evidence=f"latest end {df['end_date'].max().date()}")
    return df


def clean_targets(raw: pd.DataFrame, ctx: DQContext, stores: set, dim_date: pd.DataFrame) -> pd.DataFrame:
    """Apply the fact_targets rules and return one curated target per store-week."""
    cfg = ctx.cfg
    df = raw.copy()
    n = len(df)
    df["retail_year"] = to_num(df["retail_year"]).astype("Int64")
    df["retail_week"] = to_num(df["retail_week"]).astype("Int64")
    df["target_net_revenue"] = to_num(df["target_net_revenue"])
    df["week_start_date"] = parse_date_iso(df["week_start_date"])
    df["week_end_date"] = parse_date_iso(df["week_end_date"])
    df["target_set_date"] = parse_date_iso(df["target_set_date"])

    # FT-01 one target per store-week: keep latest version then latest set date
    k = key_of(df, TARGET_KEY)
    dupk = k.duplicated(keep=False)
    df["_v"] = df["target_version"].str.extract(r"(\d+)", expand=False).astype(float)
    order = df.sort_values(["_v", "target_set_date", "source_row"], ascending=False)
    keep = order.drop_duplicates(TARGET_KEY, keep="first").index
    drop = df.index.difference(keep)
    ctx.result("FT-01", n, int(len(drop)), evidence=f"{k[dupk].nunique()} store-weeks with more than one target")
    ctx.log_rows("FT-01", "fact_targets", k[drop], "target_version", df.loc[drop, "target_version"])
    ctx.add_quarantine("fact_targets", raw.loc[drop], "FT-01", "superseded target version")
    ctx.audit_step("fact_targets", "FT-01", "DEDUPLICATE", len(drop), metric="target EUR",
                   before=float(df["target_net_revenue"].sum()), after=float(df.loc[keep, "target_net_revenue"].sum()))
    df = df.loc[keep].drop(columns="_v").sort_values(TARGET_KEY)

    # FT-02 outliers vs the store's median target
    med = df.groupby("store_id")["target_net_revenue"].transform("median")
    ratio = df["target_net_revenue"] / med
    out = ratio > cfg["tolerances"]["target_outlier_ratio"]
    lo, hi = cfg["tolerances"]["target_decimal_shift_band"]
    shift = out & (ratio / 100).between(lo, hi)     # dividing by 100 lands in the store's normal range
    before = float(df["target_net_revenue"].sum())
    kk = key_of(df, TARGET_KEY)
    ctx.result("FT-02", len(df), int(out.sum()), evidence="; ".join(f"{a}: {r:.0f}x median" for a, r in
                                                                   zip(kk[out], ratio[out])))
    ctx.log_rows("FT-02", "fact_targets", kk[out], "target_net_revenue", df.loc[out, "target_net_revenue"],
                 (df.loc[out, "target_net_revenue"] / 100).where(shift[out]))
    df.loc[shift, "target_net_revenue"] = (df.loc[shift, "target_net_revenue"] / 100).round(2)
    other = out & ~shift
    ctx.add_quarantine("fact_targets", raw.loc[df.index[other]], "FT-02", "extreme target outlier")
    df = df[~other]
    ctx.audit_step("fact_targets", "FT-02", "CORRECT", int(shift.sum()), "target_net_revenue", "target EUR",
                   before, float(df["target_net_revenue"].sum()), note="decimal shift divided by 100")

    # FT-03 calendar alignment
    wk = dim_date.groupby(["retail_year", "retail_week"])["date"].agg(["min", "max"])
    j = df.join(wk, on=["retail_year", "retail_week"])
    bad = (j["min"] != j["week_start_date"]) | (j["max"] != j["week_end_date"])
    ctx.result("FT-03", len(df), int(bad.sum()))

    bad = (df["target_net_revenue"] <= 0) | df["target_net_revenue"].isna() | ~df["store_id"].isin(stores)
    ctx.result("FT-04", len(df), int(bad.sum()))
    ctx.log_rows("FT-04", "fact_targets", key_of(df[bad], TARGET_KEY))
    return df


def target_gaps(targets: pd.DataFrame, ctx: DQContext, stores: list, dim_date: pd.DataFrame) -> pd.DataFrame:
    """TC-06: expected = every store x every full retail week of the target years."""
    wk = dim_date.groupby(["retail_year", "retail_week"]).size()
    wk = wk[wk == 7].reset_index()[["retail_year", "retail_week"]]
    wk = wk[wk["retail_year"].isin(targets["retail_year"].dropna().unique())]
    grid = pd.MultiIndex.from_product([stores, range(len(wk))]).to_frame(index=False, name=["store_id", "i"])
    grid = grid.join(wk, on="i").drop(columns="i")
    have = set(zip(targets["store_id"], targets["retail_year"].astype(int), targets["retail_week"].astype(int)))
    miss = grid[[t not in have for t in zip(grid["store_id"], grid["retail_year"], grid["retail_week"])]]
    ctx.result("TC-06", len(grid), len(miss), evidence="; ".join(key_of(miss, TARGET_KEY)))
    ctx.log_rows("TC-06", "fact_targets", key_of(miss, TARGET_KEY), action="GAP (not imputed)")
    return miss.assign(gap_type="missing target")


__all__ = ["clean_promotions", "clean_targets", "target_gaps", "np"]
