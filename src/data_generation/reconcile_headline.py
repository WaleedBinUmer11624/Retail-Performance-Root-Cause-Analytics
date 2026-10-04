"""Recalculate the H2 headline from the PERSISTED files and reconcile it to the answer key.

EVALUATION ONLY: this module reads _planted_issues_log.csv and
_scenario_answer_key.csv. It exists to prove that the written dataset
reproduces the approved calibration. Phase 3+ code must never import it.

Three views of H2 net revenue are computed from the files:
  naive     : raw main extract taken at face value (duplicates, wrong prices and
              all), which is what an unvalidated report would show
  clean     : rows carrying a planted problem excluded (Phase 4 style, lossy)
  restored  : every planted problem reversed using the log; should reproduce the
              answer key. A few planted rows lost their original discount, so a
              small, quantified residual remains.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

H2 = {2024: ("2024-07-01", "2024-12-29"), 2025: ("2025-06-30", "2025-12-28")}
SALES_KEY = ["transaction_id", "line_number"]


def _txn_date(tid: pd.Series) -> pd.Series:
    """The transaction_id encodes the trading date; it is never corrupted."""
    return pd.to_datetime(tid.str[4:12], format="%Y%m%d")


def _net(sales: pd.DataFrame, sales_date: pd.Series, returns: pd.DataFrame, ret_date: pd.Series, year: int) -> float:
    lo, hi = (pd.Timestamp(x) for x in H2[year])
    s = sales.loc[sales_date.between(lo, hi), "revenue"].sum()
    r = returns.loc[ret_date.between(lo, hi), "refund_value"].sum()
    return float(s - r)


def reconcile(data_dir) -> dict:
    """Compute naive, clean and restored H2 net revenue from the written files and compare
    them with the answer key."""
    sales = pd.read_csv(data_dir / "fact_sales.csv", dtype={"transaction_date": str}, low_memory=False)
    late = pd.read_csv(data_dir / "fact_sales_late_batch.csv", dtype={"transaction_date": str}, low_memory=False)
    rets = pd.read_csv(data_dir / "fact_returns.csv", low_memory=False)
    log = pd.read_csv(data_dir / "_planted_issues_log.csv", dtype=str, keep_default_na=False)
    ak = pd.read_csv(data_dir / "_scenario_answer_key.csv").set_index("behaviour")

    # ---- naive: files at face value (unparseable dates dropped by the date filter)
    nd = pd.to_datetime(sales["transaction_date"], format="%Y-%m-%d", errors="coerce")
    rd = pd.to_datetime(rets["return_date"], errors="coerce")
    naive = {y: _net(sales, nd, rets, rd, y) for y in (2024, 2025)}

    # ---- restored: reverse every planted problem
    s = sales.drop_duplicates(SALES_KEY, keep="first").copy()        # re-sent receipts
    s["k"] = s["transaction_id"] + "|" + s["line_number"].astype(str)
    sl = log[log["table_name"] == "fact_sales"]
    orig = {it: g.set_index("row_key")["original_value"] for it, g in sl.groupby("issue_type")}
    unrecoverable = 0.0

    def fix(issue, fn):
        if issue in orig:
            m = s["k"].isin(orig[issue].index)
            s.loc[m, "revenue"] = fn(s.loc[m], orig[issue].reindex(s.loc[m, "k"]).to_numpy())

    fix("revenue_mismatch", lambda d, o: o.astype(float))
    fix("negative_quantity", lambda d, o: -d["revenue"])
    fix("negative_price", lambda d, o: -d["revenue"])
    fix("price_x100", lambda d, o: np.round(d["quantity"] * o.astype(float) - d["discount"], 2))
    # these two had their discount zeroed when planted; the original discount is not in the log
    for issue, qty_src in (("zero_price", "row"), ("extreme_quantity", "log")):
        if issue in orig:
            m = s["k"].isin(orig[issue].index)
            o = orig[issue].reindex(s.loc[m, "k"]).to_numpy().astype(float)
            q = s.loc[m, "quantity"] if qty_src == "row" else o
            p = o if issue == "zero_price" else s.loc[m, "unit_price"]
            s.loc[m, "revenue"] = np.round(q * p, 2)          # gross; true value = gross - unknown discount
            unrecoverable += float(len(o))
    sd = _txn_date(s["transaction_id"])
    ld = _txn_date(late["transaction_id"])

    r = rets.drop_duplicates("return_id", keep="first").copy()
    rb = log[(log["table_name"] == "fact_returns") & (log["issue_type"] == "return_before_sale")]
    r.loc[r["return_id"].isin(rb["row_key"]), "return_date"] = r["return_id"].map(
        rb.set_index("row_key")["original_value"])
    rrd = pd.to_datetime(r["return_date"])

    restored_rep = {y: _net(s, sd, r, rrd, y) for y in (2024, 2025)}
    lo, hi = (pd.Timestamp(x) for x in H2[2025])
    late25 = float(late.loc[ld.between(lo, hi), "revenue"].sum())
    missing24 = float(ak.loc["Missing batch sales revenue (H2 2024)", "impact_eur"])   # never delivered
    restored_und = {2024: restored_rep[2024] + missing24, 2025: restored_rep[2025] + late25}

    key = {
        "reported_2024": float(ak.loc["H2 2024 net revenue (reported)", "impact_eur"]),
        "reported_2025": float(ak.loc["H2 2025 net revenue (reported)", "impact_eur"]),
        "underlying_2024": float(ak.loc["H2 2024 net revenue (underlying)", "impact_eur"]),
        "underlying_2025": float(ak.loc["H2 2025 net revenue (underlying)", "impact_eur"]),
    }
    got = {"reported_2024": restored_rep[2024], "reported_2025": restored_rep[2025],
           "underlying_2024": restored_und[2024], "underlying_2025": restored_und[2025]}
    yoy = lambda a, b: 100 * (b / a - 1)
    return {
        "restored_from_files": {k: round(v, 2) for k, v in got.items()},
        "answer_key": key,
        "difference_eur": {k: round(got[k] - key[k], 2) for k in key},
        "restored_yoy_pct": {"reported": round(yoy(got["reported_2024"], got["reported_2025"]), 2),
                             "underlying": round(yoy(got["underlying_2024"], got["underlying_2025"]), 2)},
        "late_batch_h2_2025_from_file": round(late25, 2),
        "missing_batch_h2_2024_from_key_only": round(missing24, 2),
        "rows_with_unrecoverable_discount": int(unrecoverable),
        "naive_face_value": {"h2_2024": round(naive[2024], 2), "h2_2025": round(naive[2025], 2),
                             "yoy_pct": round(yoy(naive[2024], naive[2025]), 2)},
    }


if __name__ == "__main__":
    import json
    import sys
    from .config_loader import PROJECT_ROOT
    print(json.dumps(reconcile(PROJECT_ROOT / (sys.argv[1] if len(sys.argv) > 1 else "data/raw")), indent=2))
