"""Checks and treatments for dim_store, dim_product and dim_date."""
from __future__ import annotations

import difflib
import re

import numpy as np
import pandas as pd

from .core import DQContext, is_blank, key_of, matches, parse_type, to_num

UNKNOWN = "UNKNOWN"


# ------------------------------------------------------------------ category labels
def _norm(label: str) -> str:
    s = re.sub(r"\band\b", "", str(label).strip().lower())
    return re.sub(r"[^a-z]", "", s)


def canonical_category(label: str, categories: list[str], aliases: dict | None = None) -> str | None:
    """Map a free-text category label to one canonical category, or None if ambiguous.
    Order: explicit alias, exact normalised match, unique first-word match, close fuzzy match."""
    if label is None or str(label).strip() == "":
        return None
    aliases = aliases or {}
    if label in aliases:
        return aliases[label]
    n = _norm(label)
    canon = {_norm(c): c for c in categories}
    if n in canon:
        return canon[n]
    first = [c for c in categories if _norm(c.split()[0]) == n]
    if len(first) == 1:
        return first[0]
    close = difflib.get_close_matches(n, list(canon), n=2, cutoff=0.85)
    if len(close) == 1 or (len(close) == 2 and difflib.SequenceMatcher(None, n, close[0]).ratio()
                           - difflib.SequenceMatcher(None, n, close[1]).ratio() > 0.1):
        return canon[close[0]]
    return None


def category_map(labels: pd.Series, cfg: dict) -> pd.DataFrame:
    """Each distinct raw category label with its canonical category (None if unrecognised)."""
    cats = cfg["domains"]["categories"]
    uniq = pd.Series(labels.unique())
    return pd.DataFrame({"raw_label": uniq,
                         "canonical": uniq.map(lambda x: canonical_category(x, cats, cfg["domains"]["category_aliases"]))})


# ------------------------------------------------------------------ dim_store
def clean_dim_store(raw: pd.DataFrame, ctx: DQContext) -> pd.DataFrame:
    """Apply the dim_store rules (DS-*) and return the curated store table."""
    cfg = ctx.cfg
    df = raw.copy()
    n = len(df)
    ok_id = matches(df["store_id"], cfg["formats"]["store_id"])
    dup = df["store_id"].duplicated(keep=False)
    ctx.result("DS-01", n, int((~ok_id | dup).sum()))
    ctx.log_rows("DS-01", "dim_store", df.loc[~ok_id | dup, "store_id"], "store_id", df.loc[~ok_id | dup, "store_id"])

    text = ["store_id", "store_name", "town", "county", "region", "store_format", "manager_name"]
    padded = pd.Series(False, index=df.index)
    for c in text:
        m = df[c] != df[c].str.strip()
        if m.any():
            ctx.log_rows("DS-02", "dim_store", df.loc[m, "store_id"], c, df.loc[m, c], df.loc[m, c].str.strip())
            df.loc[m, c] = df.loc[m, c].str.strip()
            padded |= m
    ctx.result("DS-02", n, int(padded.sum()))
    ctx.audit_step("dim_store", "DS-02", "STANDARDISE", int(padded.sum()), "text columns", note="trimmed spaces")

    bad = pd.Series(False, index=df.index)
    for c, dom in (("region", cfg["domains"]["regions"]), ("store_format", cfg["domains"]["store_formats"])):
        lookup = {d.lower(): d for d in dom}
        fixed = df[c].str.lower().map(lookup)
        m = df[c] != fixed.fillna(df[c])
        unmapped = fixed.isna()
        if m.any():
            ctx.log_rows("DS-03", "dim_store", df.loc[m, "store_id"], c, df.loc[m, c], fixed[m])
            df.loc[m, c] = fixed[m]
        bad |= m | unmapped
    ctx.result("DS-03", n, int(bad.sum()))
    ctx.audit_step("dim_store", "DS-03", "STANDARDISE", int(bad.sum()), "region, store_format")

    num = {c: to_num(df[c]) for c in ("floor_area_m2", "headcount_fte", "weekly_trading_hours", "latitude", "longitude")}
    implaus = ((num["floor_area_m2"] <= 0) | (num["headcount_fte"] <= 0) | ~num["weekly_trading_hours"].between(40, 168)
               | ~num["latitude"].between(51.3, 55.5) | ~num["longitude"].between(-10.7, -5.9))
    ctx.result("DS-04", n, int(implaus.sum()))
    ctx.log_rows("DS-04", "dim_store", df.loc[implaus, "store_id"])
    for c, v in num.items():
        df[c] = v
    df["open_date"] = pd.to_datetime(df["open_date"], errors="coerce")
    return df


# ------------------------------------------------------------------ dim_product
def clean_dim_product(raw: pd.DataFrame, ctx: DQContext, till_ref: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """till_ref: product_id, year, ref_price, ref_cost (modal price/cost charged at the till)."""
    cfg = ctx.cfg
    df = raw.copy()
    n = len(df)
    df["list_price_num"] = to_num(df["list_price"])
    df["unit_cost_num"] = to_num(df["unit_cost"])

    # DP-01 duplicates: keep the copy whose list price matches the latest till price
    latest = till_ref.sort_values("year").groupby("product_id").last()
    dup = df["product_id"].duplicated(keep=False)
    if dup.any():
        d = df[dup].copy()
        d["gap"] = (d["list_price_num"] - d["product_id"].map(latest["ref_price"])).abs().fillna(np.inf)
        d["order"] = np.arange(len(d))
        keep_idx = d.sort_values(["product_id", "gap", "order"]).groupby("product_id").head(1).index
        drop = d.index.difference(keep_idx)
        ctx.result("DP-01", n, int(len(drop)), evidence=f"{d['product_id'].nunique()} product IDs appear twice")
        ctx.log_rows("DP-01", "dim_product", df.loc[drop, "product_id"], "product_id",
                     action="DEDUPLICATE (kept the copy matching the till price)")
        ctx.add_quarantine("dim_product", raw.loc[drop], "DP-01", "duplicate product record; other copy kept")
        ctx.audit_step("dim_product", "DP-01", "DEDUPLICATE", len(drop), "product_id", "rows", n, n - len(drop))
        df = df.drop(index=drop)
    else:
        ctx.result("DP-01", n, 0)

    # DP-03 whitespace
    padded = pd.Series(False, index=df.index)
    for c in ("product_name", "category", "subcategory", "brand", "supplier_id", "supplier_name", "status"):
        m = df[c] != df[c].str.strip()
        if m.any():
            ctx.log_rows("DP-03", "dim_product", df.loc[m, "product_id"], c, df.loc[m, c], df.loc[m, c].str.strip())
            df.loc[m, c] = df.loc[m, c].str.strip()
            padded |= m
    ctx.result("DP-03", len(df), int(padded.sum()))
    ctx.audit_step("dim_product", "DP-03", "STANDARDISE", int(padded.sum()), "text columns")

    # DP-02 category labels
    cmap = category_map(df["category"], cfg).set_index("raw_label")["canonical"]
    canon = df["category"].map(cmap)
    m = df["category"] != canon.fillna(df["category"])
    ctx.result("DP-02", len(df), int((m | canon.isna()).sum()),
               evidence="; ".join(f"'{k}' -> '{v}'" for k, v in cmap.items() if k != v))
    ctx.log_rows("DP-02", "dim_product", df.loc[m, "product_id"], "category", df.loc[m, "category"], canon[m])
    df.loc[m, "category"] = canon[m]
    ctx.audit_step("dim_product", "DP-02", "STANDARDISE", int(m.sum()), "category")

    # DP-09 subcategory -> one category
    sc = df.groupby("subcategory")["category"].nunique()
    ctx.result("DP-09", df["subcategory"].nunique(), int((sc > 1).sum()))

    # DP-04 supplier
    miss = is_blank(df["supplier_id"]) | is_blank(df["supplier_name"])
    ctx.result("DP-04", len(df), int(miss.sum()))
    ctx.log_rows("DP-04", "dim_product", df.loc[miss, "product_id"], "supplier_id", df.loc[miss, "supplier_id"], UNKNOWN)
    df.loc[miss, ["supplier_id", "supplier_name"]] = [UNKNOWN, "Unknown supplier"]
    ctx.audit_step("dim_product", "DP-04", "UNKNOWN_MEMBER", int(miss.sum()), "supplier_id, supplier_name")

    # DP-05 sign of price and cost, confirmed against the till
    fixed = 0
    for col, refc in (("list_price_num", "ref_price"), ("unit_cost_num", "ref_cost")):
        neg = df[col] <= 0
        if neg.any():
            ref = df["product_id"].map(latest[refc])
            confirm = neg & ((df[col].abs() - ref).abs() <= 0.05 * ref)
            ctx.log_rows("DP-05", "dim_product", df.loc[neg, "product_id"], col.replace("_num", ""), df.loc[neg, col],
                         df.loc[neg, col].where(~confirm[neg], df.loc[neg, col].abs()),
                         action="CORRECT (abs, confirmed by till)")
            df.loc[confirm, col] = df.loc[confirm, col].abs()
            fixed += int(neg.sum())
    ctx.result("DP-05", len(df), fixed)
    ctx.audit_step("dim_product", "DP-05", "CORRECT", fixed, "list_price, unit_cost", note="sign corrected")
    df["list_price"], df["unit_cost"] = df.pop("list_price_num"), df.pop("unit_cost_num")

    m = df["unit_cost"] >= df["list_price"]
    ctx.result("DP-06", len(df), int(m.sum()))
    ctx.log_rows("DP-06", "dim_product", df.loc[m, "product_id"], "unit_cost", df.loc[m, "unit_cost"])

    launch = pd.to_datetime(df["launch_date"], errors="coerce")
    disc = pd.to_datetime(df["discontinued_date"].where(~is_blank(df["discontinued_date"])), errors="coerce")
    bad = (launch.isna() | (disc.notna() & (disc <= launch)) | ~df["status"].isin(cfg["domains"]["product_status"])
           | ((df["status"] == "Discontinued") & disc.isna()))
    ctx.result("DP-07", len(df), int(bad.sum()))
    ctx.log_rows("DP-07", "dim_product", df.loc[bad, "product_id"])
    df["launch_date"], df["discontinued_date"] = launch, disc

    nm = df["product_name"].str.lower()
    same = nm.duplicated(keep=False)
    ctx.result("DP-08", len(df), int(same.sum()), evidence=f"{nm[same].nunique()} names shared by 2+ IDs")
    ctx.log_rows("DP-08", "dim_product", df.loc[same, "product_id"], "product_name", df.loc[same, "product_name"])

    unk = pd.DataFrame([{"source_file": "generated", "source_row": 0, "product_id": UNKNOWN,
                         "product_name": "Unknown product", "category": "Unknown", "subcategory": "Unknown",
                         "brand": "Unknown", "supplier_id": UNKNOWN, "supplier_name": "Unknown supplier",
                         "status": "Unknown"}])
    out = pd.concat([df, unk], ignore_index=True)
    return out, cmap.reset_index()


# ------------------------------------------------------------------ dim_date
def clean_dim_date(raw: pd.DataFrame, ctx: DQContext) -> pd.DataFrame:
    """Type and check the date dimension and return the curated calendar."""
    cfg = ctx.cfg
    df = raw.copy()
    for c, kind in cfg["contract"]["dim_date"]["types"].items():
        if kind in ("int", "date", "bool"):
            df[c], _ = parse_type(df[c], kind)
    start, end = pd.Timestamp(cfg["period"]["start"]), pd.Timestamp(cfg["period"]["end"])
    expected = pd.date_range(start, end)
    ok = (len(df) == len(expected) and df["date"].is_unique and set(df["date"]) == set(expected)
          and df["date_key"].is_unique)
    ctx.result("DD-01", len(df), 0 if ok else abs(len(df) - len(expected)) or 1,
               evidence=f"{len(df)} rows, {start.date()} to {end.date()}")
    bad = ((df["day_of_week"] != df["date"].dt.dayofweek + 1) | (df["is_weekend"] != (df["date"].dt.dayofweek >= 5))
           | (df["date_key"] != df["date"].dt.strftime("%Y%m%d").astype(int))
           | ((df["date"] - df["retail_week_start"]).dt.days.between(0, 6) == False))  # noqa: E712
    ctx.result("DD-02", len(df), int(bad.sum()))
    wk = df.groupby(["retail_year", "retail_week"]).size()
    short = wk[wk != 7]
    ctx.result("DD-03", len(wk), int(len(short)),
               evidence="; ".join(f"retail {y} wk {w}: {d} days" for (y, w), d in short.items()))
    return df


def till_reference(sales: pd.DataFrame) -> pd.DataFrame:
    """Modal unit price and unit cost per product and year, from lines with a positive price.
    Built from the raw POS lines themselves (majority value), so a minority of corrupted lines
    cannot move it."""
    p = to_num(sales["unit_price"])
    c = to_num(sales["unit_cost"])
    t = pd.DataFrame({"product_id": sales["product_id"], "year": sales["transaction_id"].str.slice(4, 8),
                      "p": p, "c": c})
    t = t[(t["p"] > 0) & (t["c"] > 0) & (t["product_id"] != "")]
    g = t.groupby(["product_id", "year"])
    ref = pd.DataFrame({"ref_price": g["p"].agg(lambda x: x.mode().iloc[0]),
                        "ref_cost": g["c"].agg(lambda x: x.mode().iloc[0]),
                        "lines": g.size(),
                        "share_at_ref": g["p"].agg(lambda x: (x == x.mode().iloc[0]).mean())}).reset_index()
    return ref
