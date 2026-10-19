"""Export governed results to small JSON for the GitHub Pages dashboard (docs/dashboard.html).

Inputs (read only, never modified): governed outputs in powerbi/data/ and reports/phase3, phase5,
phase6 and phase10, plus mart.v_yoy_segment_period for store year on year by retail half. No
governed file holds store results for H1, so that view is read from the Phase 4 model: built in
memory on DuckDB from the frozen curated data (default), or the SQL Server database with
--engine mssql. Either way the model must pass its reconciliation first, and its build output
goes to a temporary folder. Output: docs/data/dashboard.json.

No new calculations: every value is copied from a governed table. The script refuses to write if
the copied values do not reconcile to the governed H2 headline (H2 2025 net revenue 9,457,457.05,
YoY -7.18%) or the H1 estate result (H1 2025 net revenue 8,629,984.78, YoY +1.438%), or if the
per-store, per-category and store-by-category totals disagree with them.

Grain limits, stated in the output so the page can say them too:
  * weekly net revenue by store exists only for H2 (reports/phase5/target_weekly.csv), and three
    H2 2024 store-weeks have no row (missing targets), so single-store weekly lines show gaps;
  * no governed table holds weekly revenue by category, so the category filter acts on H2 totals.

Usage: python tmp/export_web_data.py [--engine duckdb|mssql]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "data" / "dashboard.json"
MAX_BYTES = 2_000_000
HEADLINE_H2_2024 = 10188727.55
HEADLINE_H2_2025 = 9457457.05
HEADLINE_YOY_PCT = -7.18
ESTATE_H1_2025 = 8629984.78
ESTATE_H1_YOY_PCT = 1.438
STORE_HALVES_SQL = """
SELECT segment_type, segment_name, period, net_revenue_cy, net_revenue_py, net_revenue_change, net_revenue_yoy_pct
FROM mart.v_yoy_segment_period
WHERE retail_year = 2025 AND period IN ('H1', 'H2') AND segment_type IN ('Estate', 'Store')
"""

SOURCES = {
    "headline": "reports/phase5/headline_kpis.csv",
    "estate_weekly": "reports/phase10/weekly_estate_history.csv",
    "store_weekly": "reports/phase5/target_weekly.csv",
    "store_totals": "reports/phase5/store_contribution.csv",
    "category_totals": "reports/phase5/category_contribution.csv",
    "store_category_totals": "reports/phase6/category_store_contribution.csv",
    "bridge": "reports/phase5/revenue_bridge.csv",
    "cluster_weekly": "reports/phase5/store_cluster_weekly.csv",
    "cluster_mechanisms": "powerbi/data/p6_cluster_mechanisms.csv",
    "cluster_did": "powerbi/data/p6_cluster_did.csv",
    "lost_sales_totals": "powerbi/data/p6_et_lost_sales_totals.csv",
    "lost_sales_net": "powerbi/data/p6_stockout_net_of_recovery.csv",
    "lost_sales_range": "powerbi/data/p6_sensitivity_summary.csv",
    "evidence": "powerbi/data/p6_evidence_matrix.csv",
    "dq_rules": "reports/phase3/dq_rule_results.csv",
    "dq_validation": "reports/phase3/curated_validation.csv",
    "dq_lineage": "reports/phase3/lineage.json",
    "forecast": "reports/phase10/forecast_weekly.csv",
    "forecast_intervals": "reports/phase10/forecast_intervals.csv",
    "forecast_models": "reports/phase10/forecast_model_comparison.csv",
}


def read(key: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / SOURCES[key])


def records(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    """Rows as dicts; NaN becomes None so JSON stays valid and gaps stay visible."""
    out = []
    for row in df[columns].to_dict("records"):
        out.append({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()})
    return out


def read_store_halves(engine_name: str) -> pd.DataFrame:
    """Store and estate year on year for H1 and H2 2025, read from the reconciled Phase 4 model."""
    from src.analytics.model_access import fetch, load_config, open_model

    cfg, project, _ = load_config()
    with tempfile.TemporaryDirectory() as build_dir:
        engine, _ = open_model(engine_name, cfg, project, out_dir=Path(build_dir))
        try:
            return fetch(engine, STORE_HALVES_SQL)
        finally:
            engine.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["duckdb", "mssql"], default="duckdb")
    args = ap.parse_args()
    failures: list[str] = []

    def check(ok: bool, message: str) -> None:
        print(("PASS " if ok else "FAIL ") + message)
        if not ok:
            failures.append(message)

    headline = read("headline").set_index("metric")
    net = headline.loc["net_revenue"]
    estate = read("estate_weekly")
    store_weekly = read("store_weekly")
    stores = read("store_totals")
    categories = read("category_totals")
    store_cat = read("store_category_totals")
    bridge = read("bridge")

    # ---- reconciliation gates (copied values must reproduce the governed headline)
    h2 = estate[estate.retail_week.between(27, 52)].groupby("retail_year").net_revenue.sum().round(2)
    check(h2.get(2025) == HEADLINE_H2_2025, f"H2 2025 from weekly estate history = {h2.get(2025):,.2f}")
    check(h2.get(2024) == HEADLINE_H2_2024, f"H2 2024 from weekly estate history = {h2.get(2024):,.2f}")
    check(round(net.h2_current, 2) == HEADLINE_H2_2025, "headline_kpis net_revenue H2 2025 = 9,457,457.05")
    check(round(net.yoy_pct, 2) == HEADLINE_YOY_PCT, f"headline_kpis YoY = {net.yoy_pct:.2f}%")
    for name, df in (("store", stores), ("category", categories), ("store x category", store_cat)):
        check(round(df.net_revenue_py.sum(), 2) == HEADLINE_H2_2024 and round(df.net_revenue_cy.sum(), 2) == HEADLINE_H2_2025,
              f"{name} H2 totals sum to the headline")
    totals = bridge[bridge.kind == "total"].value_eur.round(2).tolist()
    check(totals == [HEADLINE_H2_2024, HEADLINE_H2_2025], "revenue bridge starts and ends at the headline")
    lineage = json.loads((ROOT / SOURCES["dq_lineage"]).read_text(encoding="utf-8"))
    check(sum(lineage["quarantine_rows"].values()) == 2380, "lineage quarantine rows total 2,380")

    present = set(zip(store_weekly.retail_year, store_weekly.retail_week, store_weekly.store_id))
    gaps = sorted(k for k in pd.MultiIndex.from_product(
        [[2024, 2025], range(27, 53), sorted(store_weekly.store_id.unique())]) if k not in present)
    check(len(gaps) == 3, f"store weekly gaps are the three known missing-target store-weeks: {gaps}")

    # ---- store results by half (mart view): the H1 estate gate, and both halves agree with the files above
    halves = read_store_halves(args.engine)
    estate_half = halves[halves.segment_type == "Estate"].set_index("period")
    store_half = halves[halves.segment_type == "Store"].copy()
    store_half["store_id"] = store_half.segment_name.str.split(" ", n=1).str[0]
    h1 = estate_half.loc["H1"]
    check(round(h1.net_revenue_cy, 2) == ESTATE_H1_2025, f"mart H1 2025 estate net revenue = {h1.net_revenue_cy:,.2f}")
    check(round(h1.net_revenue_yoy_pct, 3) == ESTATE_H1_YOY_PCT, f"mart H1 2025 estate YoY = {h1.net_revenue_yoy_pct:+.3f}%")
    check(round(estate_half.loc["H2", "net_revenue_cy"], 2) == HEADLINE_H2_2025, "mart H2 2025 estate net revenue = 9,457,457.05")
    for half in ("H1", "H2"):
        rows = store_half[store_half.period == half]
        check(len(rows) == 20 and round(rows.net_revenue_cy.sum(), 2) == round(estate_half.loc[half, "net_revenue_cy"], 2),
              f"mart {half} 2025: 20 stores sum to the estate")
    h2_files = stores.set_index("store_id").net_revenue_cy.round(2)
    h2_mart = store_half[store_half.period == "H2"].set_index("store_id").net_revenue_cy.round(2)
    check(h2_mart.sort_index().equals(h2_files.sort_index()), "mart H2 store net revenue matches store_contribution.csv")

    if failures:
        print(f"NOT WRITTEN: {len(failures)} reconciliation check(s) failed")
        return 1

    lost_totals = read("lost_sales_totals").set_index("scope").loc["category"]
    lost_net = read("lost_sales_net").set_index("driver").loc["electronics_stockouts_primary"]
    lost_range = read("lost_sales_range").set_index("driver").loc["electronics_stockouts_primary"]
    evidence = read("evidence").sort_values("sort_order")
    rules = read("dq_rules")
    validation = read("dq_validation")
    models = read("forecast_models")

    data = {
        "meta": {
            "note": "Brightwater Retail Ltd is fictional; all data is synthetic.",
            "period": {"current": "H2 2025", "prior": "H2 2024", "weeks": "retail weeks 27 to 52"},
            "grain_limits": [
                "Weekly net revenue by store is governed for H2 only; three H2 2024 store-weeks have no row "
                "(S03 week 28, S17 week 29, S09 week 30: missing targets), so those points are gaps.",
                "No governed table holds weekly revenue by category; the category filter applies to H2 totals.",
            ],
            "sources": SOURCES,
            "checks": "H2 2025 = 9,457,457.05 and YoY = -7.18%, H1 2025 = 8,629,984.78 and YoY = +1.438%, "
                      "reconciled before export",
        },
        "headline": {m: {"prior": float(headline.loc[m, "h2_prior"]), "current": float(headline.loc[m, "h2_current"]),
                         "change": float(headline.loc[m, "change"]),
                         "yoy_pct": None if pd.isna(headline.loc[m, "yoy_pct"]) else float(headline.loc[m, "yoy_pct"])}
                     for m in ("net_revenue", "transactions", "gross_margin_pct", "return_rate_value", "aov")},
        "estate_weekly": records(estate, ["retail_year", "retail_week", "week_start_date", "net_revenue", "transactions"]),
        "store_weekly": records(store_weekly, ["retail_year", "retail_week", "store_id", "net_revenue"]),
        "store_weekly_gaps": [{"retail_year": y, "retail_week": w, "store_id": s} for y, w, s in gaps],
        "stores": records(stores.sort_values("store_id"), [
            "store_id", "store_name", "region", "store_format", "net_revenue_py", "net_revenue_cy",
            "net_revenue_change", "net_revenue_yoy_pct", "share_of_change",
            "transactions_py", "transactions_cy", "transactions_yoy_pct"]),
        "store_halves_2025": records(store_half.sort_values(["store_id", "period"]), [
            "store_id", "period", "net_revenue_py", "net_revenue_cy", "net_revenue_change", "net_revenue_yoy_pct"]),
        "categories": records(categories.sort_values("category"), [
            "category", "net_revenue_py", "net_revenue_cy", "net_revenue_change", "net_revenue_yoy_pct",
            "share_of_change"]),
        "store_category": records(store_cat, ["store_id", "category", "net_revenue_py", "net_revenue_cy",
                                              "net_revenue_change", "in_cluster"]),
        "bridge": records(bridge, ["step", "value_eur", "kind", "running_total_eur", "share_of_change"]),
        "cluster_weekly": records(read("cluster_weekly"), [
            "retail_week", "cluster_net_revenue_yoy_pct", "cluster_transactions_yoy_pct",
            "rest_net_revenue_yoy_pct", "rest_transactions_yoy_pct"]),
        "cluster_mechanisms": records(read("cluster_mechanisms"), [
            "metric", "cluster_change", "control_change", "difference"]),
        "cluster_excess_eur": float(read("cluster_did").set_index(["control_group", "outcome"])
                                    .loc[("matched", "ly_net_revenue"), "ratio_did_excess"]),
        "lost_sales": {
            "gross_eur": float(lost_totals.primary_change),
            "net_of_deferred_demand_eur": float(lost_net.estimate_eur),
            "range_low_eur": float(lost_range.range_low_eur),
            "range_high_eur": float(lost_range.range_high_eur),
        },
        "evidence": records(evidence, ["driver_id", "driver", "evidence_level", "cause_status",
                                       "financial_impact_eur", "impact_range", "what_we_know", "what_we_do_not_know"]),
        "dq": {
            "rules": records(rules, ["rule_id", "table", "severity", "status"]),
            "validation_status": validation.status.tolist(),
            "quarantine_rows": lineage["quarantine_rows"],
        },
        "forecast": {
            "points": records(read("forecast"), ["horizon_step", "week_start_date", "model", "point_forecast"]),
            "intervals": records(read("forecast_intervals"), ["week_start_date", "coverage", "lower", "upper"]),
            "models": records(models, ["model", "family", "mean_wape", "mean_mae"]),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > MAX_BYTES:
        print(f"NOT WRITTEN: {len(text):,} bytes exceeds {MAX_BYTES:,}")
        return 1
    OUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}: {OUT.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
