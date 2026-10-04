"""Completeness and timeliness checks discoverable from the data itself (TC-02, TC-03, TC-04)."""
from __future__ import annotations

import pandas as pd

from .core import DQContext, id_date, id_store


def store_day_coverage(sales: pd.DataFrame, main_source: str, dim_date: pd.DataFrame, stores: list,
                       inventory: pd.DataFrame, returns_raw: pd.DataFrame, ctx: DQContext) -> pd.DataFrame:
    """TC-02: every store should have POS data on every trading day. Gaps are tested twice:
    as first reported (main extract only) and after the late file is loaded."""
    trading = dim_date.loc[dim_date["is_trading_day"], "date"]
    grid = pd.MultiIndex.from_product([stores, trading], names=["store_id", "date"])
    rev = sales.groupby(["store_id", "transaction_date"])["revenue"].sum()
    rev_main = sales[sales["source_file"] == main_source].groupby(["store_id", "transaction_date"])["revenue"].sum()
    rev.index.names = rev_main.index.names = ["store_id", "date"]
    out = pd.DataFrame(index=grid)
    out["revenue_complete"] = rev.reindex(grid)
    out["revenue_first_reported"] = rev_main.reindex(grid)
    gaps = out[out["revenue_first_reported"].isna()].copy()
    gaps["resolved_by_late_file"] = gaps["revenue_complete"].notna()

    # evidence and estimate for unresolved gaps: same store, same weekday, 4 weeks either side
    daily = rev.rename("rev").reset_index()
    daily["dow"] = daily["date"].dt.dayofweek
    est, inv_units, pos_units, ret_refs = [], [], [], []
    wk_end = dim_date.set_index("date")["retail_week_start"] + pd.Timedelta(days=6)
    rt = returns_raw["original_transaction_id"].fillna("")
    ret_days = pd.Series(list(zip(id_store(rt), id_date(rt)))).value_counts()
    for (s, d) in gaps.index:
        w = daily[(daily["store_id"] == s) & (daily["dow"] == d.dayofweek)
                  & (daily["date"].sub(d).abs() <= pd.Timedelta(days=28)) & (daily["date"] != d)]
        est.append(float(w["rev"].median()) if len(w) else float("nan"))
        we = wk_end.get(d)
        inv_units.append(float(inventory.loc[(inventory["store_id"] == s) & (inventory["snapshot_date"] == we),
                                             "sold_qty"].sum()))
        pos_units.append(float(sales.loc[(sales["store_id"] == s) & (sales["transaction_date"].map(wk_end) == we),
                                         "quantity"].sum()))
        ret_refs.append(int(ret_days.get((s, d), 0)))
    gaps["estimated_revenue"] = est
    gaps["week_stock_sold_units"] = inv_units
    gaps["week_pos_units"] = pos_units
    gaps["returns_referencing_day"] = ret_refs
    gaps = gaps.reset_index()
    unresolved = gaps[~gaps["resolved_by_late_file"]]
    ctx.result("TC-02", len(out), len(gaps), float(unresolved["estimated_revenue"].sum()),
               evidence=(f"{len(gaps)} store-days missing from the main extract; {int(gaps['resolved_by_late_file'].sum())} "
                         f"delivered by the late file; {len(unresolved)} still missing "
                         f"({', '.join(unresolved['store_id'] + ' ' + unresolved['date'].dt.strftime('%Y-%m-%d'))}), "
                         f"estimated EUR {unresolved['estimated_revenue'].sum():,.0f}"))
    ctx.log_rows("TC-02", "fact_sales", gaps["store_id"] + "|" + gaps["date"].dt.strftime("%Y-%m-%d"),
                 action="GAP (resolved by late file)" if unresolved.empty else "GAP")
    return gaps


def low_volume_days(sales: pd.DataFrame, ctx: DQContext) -> pd.DataFrame:
    """TC-03: store-days far below the store's usual revenue for that weekday (8-week window)."""
    ratio_lim = ctx.cfg["tolerances"]["low_volume_day_ratio"]
    d = sales.groupby(["store_id", "transaction_date"])["revenue"].sum().rename("rev").reset_index()
    d["dow"] = d["transaction_date"].dt.dayofweek
    d = d.sort_values(["store_id", "dow", "transaction_date"])
    d["typical"] = (d.groupby(["store_id", "dow"])["rev"]
                    .transform(lambda x: x.rolling(9, center=True, min_periods=5).median()))
    d["ratio"] = d["rev"] / d["typical"]
    low = d[d["ratio"] < ratio_lim]
    ctx.result("TC-03", len(d), len(low), evidence="; ".join(f"{s} {t:%Y-%m-%d} at {r:.0%} of usual"
                                                           for s, t, r in zip(low["store_id"], low["transaction_date"],
                                                                              low["ratio"])))
    ctx.log_rows("TC-03", "fact_sales", low["store_id"] + "|" + low["transaction_date"].dt.strftime("%Y-%m-%d"))
    return low


def batch_structure(main_raw: pd.DataFrame, ctx: DQContext) -> pd.DataFrame:
    """TC-04: one batch per business day, loaded next morning; spot re-sent or split batches."""
    ts = pd.to_datetime(main_raw["extract_timestamp"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    b = pd.DataFrame({"batch": main_raw["extract_batch_id"], "biz_date": id_date(main_raw["transaction_id"]),
                      "hour": ts.dt.hour, "ts": ts})
    g = b.groupby("batch").agg(dates=("biz_date", "nunique"), first=("ts", "min"), last=("ts", "max"),
                               lines=("batch", "size"), hours=("hour", lambda h: ",".join(str(x) for x in sorted(h.unique()))))
    multi_hour = g[g["hours"].str.contains(",")]
    ctx.result("TC-04", len(g), int(((g["dates"] > 1)).sum() + len(multi_hour)),
               evidence=(f"{len(g)} daily batches; batches covering more than one business day: {int((g['dates'] > 1).sum())}; "
                         f"batches with lines extracted at more than one hour (re-sends): {len(multi_hour)}; "
                         f"extract hours seen: {sorted(b['hour'].dropna().astype(int).unique().tolist())}"))
    return g.reset_index()
