"""EW08: data-quality gate at store x retail week.

At each weekly run the gate judges the data the run can see (the as-at replay), so a late batch looks exactly as it
did on the Monday: missing. FAIL checks (the data cannot support a KPI) hold every business alert for the store-week;
WARN checks (data was repaired at load) are shown as caveats. The retrospective check C2 (share of lines that
arrived on time) is only knowable once the late lines arrive; it explains held alerts afterwards.

Row-level repairs come from two frozen sources: the dq_status / flags carried on every dw row, and the Phase 3 issue
log (reports/phase3/dq_issue_log.csv), whose row keys carry the store and date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .access import read_csv

CHECKS = [
    ("C1", "FAIL", "Missing trading days", "A trading day with no sales lines at run time"),
    ("C2", "RETRO", "Late-arriving lines", "Share of the week's final lines that had arrived by the run (retrospective)"),
    ("C3", "FAIL", "Row-count drop", "Lines at run time below half the store's trailing 13-week median and below half the same week last year"),
    ("C4", "WARN", "Duplicate receipts removed", "Re-sent receipt lines removed at load (Phase 3 FS-01)"),
    ("C5", "WARN", "Invalid prices repaired", "Zero, negative or 100x unit prices corrected or imputed (FS-11, FS-12, FS-13)"),
    ("C6", "WARN", "Invalid or missing discounts repaired", "Missing discounts or broken promotion references (FS-15, FS-19)"),
    ("C7", "WARN", "Missing product references", "Lines whose product is not in the product master (UNKNOWN member) above tolerance"),
    ("C8", "FAIL/WARN", "Stale or missing stock snapshots", "No snapshot rows for the store-week (FAIL) or gaps in store-SKU series (TC-05, WARN)"),
    ("C9", "WARN", "Null or corrected fields", "Lines corrected or imputed at load (missing prices, dates or stores repaired) above tolerance"),
    ("C10", "WARN", "Quarantined lines", "Implausible quantities quarantined (FS-09)"),
    ("C11", "WARN", "Returns without a received sale line", "Unlinked returns above tolerance (broken sale reference)"),
    ("C12", "HOLD", "Prior-year returns history incomplete", "Returns-based comparisons (EW05, EW06) whose prior-year window "
     "touches the first weeks of history, when returns of pre-extract sales are missing"),
]


def _issue_counts(cfg: dict, cal: pd.DataFrame) -> pd.DataFrame:
    """Phase 3 issue-log counts per store x retail week for the rules the gate uses."""
    log = read_csv("reports/phase3/dq_issue_log.csv", cfg, low_memory=False, usecols=["rule_id", "table_name", "row_key"])
    s = log[log["table_name"] == "fact_sales"].copy()
    key = s["row_key"].str.extract(r"^(S\d{2})-(\d{8})-")
    s["store_id"], s["date"] = key[0], pd.to_datetime(key[1], format="%Y%m%d", errors="coerce")
    s = s.dropna(subset=["store_id", "date"])
    rules = {"dup": ["FS-01"], "price": ["FS-11", "FS-12", "FS-13"], "discount": ["FS-15", "FS-19"], "quarantine": ["FS-09"]}
    days = pd.DataFrame({"date": pd.date_range(cal["week_start"].min(), cal["week_end"].max())})
    wk = cal[["retail_week_key", "week_start", "week_end"]]
    days = days.merge(wk, how="cross")
    days = days[(days["date"] >= days["week_start"]) & (days["date"] <= days["week_end"])][["date", "retail_week_key"]]
    s = s.merge(days, on="date")
    out = None
    for name, ids in rules.items():
        g = s[s["rule_id"].isin(ids)].groupby(["store_id", "retail_week_key"]).size().rename(f"n_{name}")
        out = g.to_frame() if out is None else out.join(g, how="outer")
    inv = read_csv("reports/phase3/inventory_missing_weeks.csv", cfg)
    inv["date"] = pd.to_datetime(inv["snapshot_date"])
    inv = inv.merge(days, on="date").groupby(["store_id", "retail_week_key"]).size().rename("n_missing_snapshots")
    out = out.join(inv, how="outer").fillna(0).reset_index()
    return out


def dq_store_week(T: dict, W: dict, cfg: dict) -> pd.DataFrame:
    """One row per store x week: the gate as judged at that week's own run, plus the retrospective C2."""
    tol = cfg["monitoring"]["dq"]
    trailing = cfg["monitoring"]["baseline"]["trailing_weeks"]
    cal = W["calendar"]
    sw = T["kpi_store_week"].merge(cal[["retail_week_key", "t"]], on="retail_week_key").sort_values(["store_id", "t"])
    inv = T["inventory_store_week"]
    sw = sw.merge(inv, on=["retail_week_key", "store_id"], how="left")
    late = sw["last_extract_timestamp"].notna() & (sw["last_extract_timestamp"] > sw["run_time"])
    sw["lines_asat"] = np.where(late, sw["lines_ontime"], sw["lines"])
    sw["days_asat"] = np.where(late, sw["days_with_sales_ontime"], sw["days_with_sales"])
    # trailing median of the lines each earlier week showed at ITS run (no future information)
    sw["lines_trailing_median"] = sw.groupby("store_id")["lines_asat"].transform(
        lambda s: s.shift(1).rolling(trailing, min_periods=4).median())
    sw = sw.merge(_issue_counts(cfg, cal), on=["store_id", "retail_week_key"], how="left").fillna(
        {c: 0 for c in ["n_dup", "n_price", "n_discount", "n_quarantine", "n_missing_snapshots"]})
    f, w = tol["fail"], tol["warn"]
    lines = sw["lines"].replace(0, np.nan)
    sw["C1"] = (sw["trading_days"] - sw["days_asat"]) >= f["missing_trading_days"]
    sw["C2_ontime_share"] = (sw["lines_ontime"] / lines).fillna(1.0)
    sw["C2"] = sw["C2_ontime_share"] < f["ontime_line_share_below"]
    py = sw[["store_id", "retail_week_key", "lines"]].rename(columns={"retail_week_key": "py_week_key", "lines": "lines_py"})
    sw = sw.merge(cal[["retail_week_key", "py_week_key"]], on="retail_week_key").merge(py, on=["store_id", "py_week_key"], how="left")
    share = f["row_count_below_share_of_median"]
    sw["C3"] = (sw["lines_asat"] < share * sw["lines_trailing_median"]) & \
        (sw["lines_py"].isna() | (sw["lines_asat"] < share * sw["lines_py"]))
    sw["C4"] = (sw["n_dup"] / lines).fillna(0) > w["duplicates_removed_share_above"]
    sw["C5"] = (sw["n_price"] / lines).fillna(0) > w["invalid_price_share_above"]
    sw["C6"] = (sw["n_discount"] / lines).fillna(0) > w["invalid_discount_share_above"]
    sw["C7"] = (sw["lines_unknown_product"] / lines).fillna(0) > w["unknown_product_share_above"]
    sw["C8_fail"] = sw["snapshot_rows"].fillna(0) == 0
    sw["C8"] = sw["C8_fail"] | (sw["n_missing_snapshots"] > w["missing_inventory_snapshots_above"])
    sw["C9"] = (sw["lines_dq_flagged"] / lines).fillna(0) > w["corrected_line_share_above"]
    sw["C10"] = sw["n_quarantine"] > w["quarantined_lines_above"]
    rets = (sw["returns_unlinked"] / (sw["returned_units"].replace(0, np.nan))).fillna(0)
    sw["C11"] = rets > w["unlinked_return_share_above"]
    fail = sw["C1"] | sw["C3"]
    inv_fail = sw["C8_fail"]
    warn = sw[["C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11"]].any(axis=1)
    sw["dq_sales_status"] = np.where(fail, "FAIL", np.where(warn, "WARN", "PASS"))
    sw["dq_inventory_status"] = np.where(inv_fail, "FAIL", np.where(sw["C8"], "WARN", "PASS"))
    names = {c[0]: c[2] for c in CHECKS}

    def failed(r):
        out = [f"{k} {names[k]}" for k in ["C1", "C3"] if r[k]]
        out += [f"{k} {names[k]}" for k in ["C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11"] if r[k]]
        if r["C2"]:
            out.append(f"C2 {names['C2']} (retrospective: {100 * r['C2_ontime_share']:.0f}% on time)")
        return "; ".join(out)
    sw["dq_checks_failed"] = sw.apply(failed, axis=1)
    # lines the failed week is missing against its trailing median (used for the materiality of window signals)
    sw["lines_expected"] = sw["lines_trailing_median"].fillna(sw["lines_asat"])
    sw["lines_missing"] = np.where(sw["dq_sales_status"] == "FAIL",
                                   np.maximum(0.0, sw["lines_expected"] - sw["lines_asat"]), 0.0)
    cols = ["store_id", "retail_week_key", "t", "trading_days", "days_asat", "lines", "lines_asat", "lines_trailing_median",
            "C2_ontime_share", "n_dup", "n_price", "n_discount", "n_quarantine", "n_missing_snapshots", "snapshot_rows",
            "lines_unknown_product", "lines_dq_flagged", "returns_unlinked", "lines_expected", "lines_missing"] + \
        ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "dq_sales_status", "dq_inventory_status",
         "dq_checks_failed"]
    return sw[cols].reset_index(drop=True)


def estate_dq(dq: pd.DataFrame, stores: list | None = None, inventory_warn_share: float = 0.01) -> pd.DataFrame:
    """Estate (or store-group) gate per week: FAIL if any store in the group failed (totals incomplete)."""
    d = dq if stores is None else dq[dq["store_id"].isin(stores)]
    g = d.groupby("retail_week_key").agg(
        sales_fail=("dq_sales_status", lambda s: (s == "FAIL").sum()),
        sales_warn=("dq_sales_status", lambda s: (s == "WARN").sum()),
        inv_fail=("dq_inventory_status", lambda s: (s == "FAIL").sum()),
        inv_warn=("dq_inventory_status", lambda s: (s == "WARN").sum()),
        lines_expected=("lines_expected", "sum"), lines_missing=("lines_missing", "sum"),
        failing_stores=("store_id", lambda s: ", ".join(sorted(s[d.loc[s.index, "dq_sales_status"] == "FAIL"])))).reset_index()
    g["dq_sales_status"] = np.where(g["sales_fail"] > 0, "FAIL", np.where(g["sales_warn"] > 0, "WARN", "PASS"))
    # a single store-SKU gap is a store caveat, not an estate one: the estate status is WARN only when the missing
    # store-SKU snapshots are a material share of the estate's snapshot cells (review finding m3)
    cells = d.groupby("retail_week_key").agg(missing=("n_missing_snapshots", "sum"), rows=("snapshot_rows", "sum")).reset_index()
    g = g.merge(cells, on="retail_week_key", how="left")
    g["missing_snapshot_share"] = (g["missing"] / g["rows"].replace(0, np.nan)).fillna(0.0)
    g["dq_inventory_status"] = np.where(g["inv_fail"] > 0, "FAIL",
                                        np.where(g["missing_snapshot_share"] > inventory_warn_share, "WARN", "PASS"))
    return g


def check_catalogue(cfg: dict) -> pd.DataFrame:
    tol = cfg["monitoring"]["dq"]
    rows = []
    for cid, sev, name, desc in CHECKS:
        rows.append({"check_id": cid, "severity": sev, "check": name, "description": desc})
    df = pd.DataFrame(rows)
    df["tolerance"] = df["check_id"].map({
        "C1": f">= {tol['fail']['missing_trading_days']} missing trading day",
        "C2": f"< {tol['fail']['ontime_line_share_below']:.0%} of final lines on time",
        "C3": f"< {tol['fail']['row_count_below_share_of_median']:.0%} of trailing median lines and of last year's week",
        "C4": f"> {tol['warn']['duplicates_removed_share_above']:.1%} of lines",
        "C5": f"> {tol['warn']['invalid_price_share_above']:.1%} of lines",
        "C6": f"> {tol['warn']['invalid_discount_share_above']:.1%} of lines",
        "C7": f"> {tol['warn']['unknown_product_share_above']:.1%} of lines",
        "C8": "0 snapshot rows (FAIL); > 0 missing store-SKU weeks (WARN)",
        "C9": f"> {tol['warn']['corrected_line_share_above']:.1%} of lines",
        "C10": "> 0 lines", "C11": f"> {tol['warn']['unlinked_return_share_above']:.0%} of returned units",
        "C12": f"prior-year window within the first {tol['returns_history_warmup_weeks']} weeks of history"})
    df["blocks_business_alerts"] = df["severity"].isin(["FAIL", "FAIL/WARN", "HOLD"])
    return df
