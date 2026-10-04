"""Phase 9 monitoring KPI layer: governed weekly KPIs, the as-at replay and reconciliation to Phases 4-7.

The SQL views (sql/monitoring) hold additive components only. This module derives every ratio from sums, keeps the
governed definitions (Net Revenue, COGS, Gross Margin, Transactions, Availability, full-week stock-out), and provides
`asat`, the one function that decides what a weekly run could see: for a week w evaluated at run time T, a table row
uses its final values if all of its lines had arrived by T, otherwise its on-time values.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .access import read_csv

# ----------------------------------------------------------------------------- KPI dictionary
KPI_DICTIONARY = [
    # kpi, definition, numerator, denominator, grain, baseline, dimensions, source, refresh, limitations
    ("weekly_net_revenue", "Sales revenue minus refunds (governed BRD 5.1)", "sales_revenue - returns_value", "",
     "store x week; category x week", "Same retail week last year; trailing 13-week median of the YoY",
     "estate, region, format, store, category", "mon.kpi_store_week, mon.kpi_category_week", "Weekly, Monday 06:00",
     "Refunds counted on the return date at the returning store"),
    ("weekly_transactions", "Distinct receipts; at category grain, receipts containing the category", "count distinct transaction_id", "",
     "store x week; category x week", "Same retail week last year; peer gap vs all other stores", "estate, region, format, store, category",
     "mon.kpi_store_week", "Weekly", "Not additive across categories"),
    ("weekly_units", "Units sold", "sum quantity", "", "store x week; category x week; product x week", "Same weeks last year",
     "all", "mon.kpi_*_week", "Weekly", ""),
    ("weekly_upt", "Units per transaction", "units", "transactions", "store x week", "Same week last year", "estate, store",
     "derived", "Weekly", "Ratio of sums"),
    ("weekly_asp", "Average selling price", "sales_revenue", "units", "category x week", "Same weeks last year", "category",
     "derived", "Weekly", "Ratio of sums"),
    ("weekly_gross_margin", "Net revenue minus COGS (COGS = cost_amount - restock_cost_credit)", "net_revenue - cogs", "",
     "category x week (trailing 4 weeks for alerts)", "Same 4 weeks last year", "category", "mon.kpi_category_week", "Weekly",
     "Restock credit follows the return date"),
    ("weekly_gross_margin_pct", "Gross margin / net revenue", "gross_margin", "net_revenue", "category x week (trailing 4 weeks)",
     "Same 4 weeks last year", "category", "derived", "Weekly", "Swings with promotion pulses week to week"),
    ("weekly_return_rate", "Refund value / sales revenue", "returns_value", "sales_revenue", "store x week; category x week",
     "Same weeks last year", "store, category", "derived", "Weekly", ""),
    ("weekly_faulty_rate", "'Faulty' returned units per 100 units sold (return-date basis)", "100 x faulty_units", "units",
     "category x week and store x E&T, trailing 4 weeks", "Same 4 weeks last year (conditional binomial test)", "store, category",
     "mon.kpi_store_category_week, mon.kpi_category_week", "Weekly", "Recorded till reason, not a verified defect"),
    ("weekly_availability", "In-stock store-SKU-weeks / ranged store-SKU-weeks (Sunday snapshot)", "in_stock_cells", "ranged_cells",
     "category x week; supplier x week", "Same week last year and trailing 8 weeks", "category, supplier", "mon.kpi_category_week, mon.kpi_product_week",
     "Weekly", "Weekly snapshot only; partial-week stock-outs not visible"),
    ("weekly_stockout_rate", "1 - availability", "ranged_cells - in_stock_cells", "ranged_cells", "category x week; supplier x week",
     "Same as availability", "category, supplier", "derived", "Weekly", ""),
    ("weekly_full_week_stockouts", "Store-SKU-weeks with no opening stock, nothing received and out of stock at the snapshot",
     "count of cells", "", "product x week (top sellers); category x week", "Prior-year level (near zero)", "product, supplier, category",
     "mon.kpi_product_week", "Weekly", "Sales in the week are zero by construction"),
    ("weekly_promotion_share", "Promoted sales revenue / sales revenue", "promo_revenue", "sales_revenue", "category x week (trailing 4 weeks)",
     "Same 4 weeks last year", "category", "derived", "Weekly", "Promotions run in pulses"),
    ("weekly_discount_rate", "Discount value / gross sales", "discount_amount", "gross_amount", "category x week (trailing 4 weeks)",
     "Same 4 weeks last year", "category", "derived", "Weekly", "No approved promotion plan in the data"),
    ("weekly_data_completeness", "Trading days with sales lines at run time / trading days; on-time lines / final lines",
     "days_with_sales_ontime", "trading_days", "store x week", "Fixed tolerances; trailing 13-week median of line counts",
     "store, estate", "mon.kpi_store_week, reports/phase3 audit files", "Weekly (at run) and retrospective", "Late lines are only known once they arrive"),
]
KPI_COLUMNS = ["kpi", "definition", "numerator", "denominator", "grain", "comparison_baseline", "required_dimensions",
               "data_source", "refresh_expectation", "known_limitations"]


def kpi_dictionary() -> pd.DataFrame:
    return pd.DataFrame(KPI_DICTIONARY, columns=KPI_COLUMNS)


# ----------------------------------------------------------------------------- as-at replay
def asat(df: pd.DataFrame, cols: list[str], run_time: pd.Timestamp) -> pd.DataFrame:
    """Values a run at `run_time` would have seen. Rows whose last line arrived after the run use the on-time
    columns (`<col>_ontime`); others use final values. Columns without an on-time twin are taken as final."""
    out = df.copy()
    late = out["last_extract_timestamp"].notna() & (out["last_extract_timestamp"] > run_time)
    for c in cols:
        twin = f"{c}_ontime"
        if twin in out.columns:
            out[c] = np.where(late, out[twin], out[c])
    return out


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["net_revenue"] = d["sales_revenue"] - d["returns_value"]
    if "cost_amount" in d.columns:
        d["cogs"] = d["cost_amount"] - d["restock_cost_credit"]
        d["gross_margin"] = d["net_revenue"] - d["cogs"]
    return d


def weekly_tables(T: dict) -> dict:
    """Final-value weekly KPI tables (for reconciliation, Power BI-ready extracts and charts)."""
    cal = T["week_calendar"].sort_values("retail_week_key").reset_index(drop=True)
    cal["t"] = range(len(cal))
    sw = add_derived(T["kpi_store_week"]).merge(cal[["retail_week_key", "retail_year", "retail_week", "t", "py_week_key"]],
                                                 on="retail_week_key")
    cw = add_derived(T["kpi_category_week"]).merge(cal[["retail_week_key", "retail_year", "retail_week", "t", "py_week_key"]],
                                                    on="retail_week_key")
    for d in (sw, cw):
        d["upt"] = d["units"] / d["transactions"].replace(0, np.nan)
        d["return_rate"] = d["returns_value"] / d["sales_revenue"].replace(0, np.nan)
        d["discount_rate"] = d["discount_amount"] / d["gross_amount"].replace(0, np.nan)
        d["promotion_share"] = d["promo_revenue"] / d["sales_revenue"].replace(0, np.nan)
        d["gross_margin_pct"] = d["gross_margin"] / d["net_revenue"].replace(0, np.nan)
    cw["availability"] = cw["in_stock_cells"] / cw["ranged_cells"].replace(0, np.nan)
    cw["asp"] = cw["sales_revenue"] / cw["units"].replace(0, np.nan)
    est = sw.groupby(["retail_week_key", "retail_year", "retail_week", "t"], as_index=False)[
        ["sales_revenue", "returns_value", "net_revenue", "transactions", "units", "gross_amount", "discount_amount",
         "promo_revenue", "gross_margin"]].sum()
    est["upt"] = est["units"] / est["transactions"]
    est["gross_margin_pct"] = est["gross_margin"] / est["net_revenue"]
    return {"calendar": cal, "store_week": sw, "category_week": cw, "estate_week": est}


# ----------------------------------------------------------------------------- reconciliation
def reconcile(W: dict, cfg: dict) -> pd.DataFrame:
    rows = []

    def add(check, value, ref, source, tol=0.01):
        diff = abs(float(value) - float(ref))
        rows.append({"group": "KPI reconciliation", "check": check, "value": float(value), "reference": float(ref),
                     "abs_difference": diff, "tolerance": tol, "reference_source": source,
                     "status": "PASS" if diff <= tol else "FAIL"})

    hl = cfg["powerbi"]["headline"]
    sw = W["store_week"]
    h2 = sw[sw["retail_week"] >= 27].groupby("retail_year")["net_revenue"].sum()
    add("H2 2024 net revenue (monitoring layer) = approved headline", h2[2024], hl["net_revenue_py"], "config/powerbi_config.yaml (brief)")
    add("H2 2025 net revenue (monitoring layer) = approved headline", h2[2025], hl["net_revenue_cy"], "config/powerbi_config.yaml (brief)")
    add("H2 change = approved headline", h2[2025] - h2[2024], hl["change"], "config/powerbi_config.yaml (brief)")
    p5 = read_csv("reports/phase5/weekly_yoy_full_year.csv", cfg)
    est = W["estate_week"].set_index("retail_week_key")
    nr = max(abs(est.loc[r.retail_week_key, "net_revenue"] - r.net_revenue_cy) for r in p5.itertuples())
    tx = max(abs(est.loc[r.retail_week_key, "transactions"] - r.transactions_cy) for r in p5.itertuples())
    nrpy = max(abs(est.loc[r.prior_year_week_key, "net_revenue"] - r.net_revenue_py) for r in p5.itertuples())
    add("Weekly estate net revenue 2025, all 52 weeks: max difference to Phase 5", nr, 0, "reports/phase5/weekly_yoy_full_year.csv")
    add("Weekly estate transactions 2025, all 52 weeks: max difference to Phase 5", tx, 0, "reports/phase5/weekly_yoy_full_year.csv", 0)
    add("Weekly estate net revenue 2024 (PY weeks): max difference to Phase 5", nrpy, 0, "reports/phase5/weekly_yoy_full_year.csv")
    cc = read_csv("reports/phase5/category_contribution.csv", cfg).set_index("category")
    cw = W["category_week"]
    h = cw[cw["retail_week"] >= 27].groupby(["retail_year", "category"])[["net_revenue", "in_stock_cells", "ranged_cells",
                                                                            "gross_margin"]].sum()
    for cat in ["Electronics & Tech", "Home & Kitchen"]:
        add(f"{cat} H2 2025 net revenue = Phase 5", h.loc[(2025, cat), "net_revenue"], cc.loc[cat, "net_revenue_cy"],
            "reports/phase5/category_contribution.csv")
        add(f"{cat} H2 2025 availability = Phase 5", h.loc[(2025, cat), "in_stock_cells"] / h.loc[(2025, cat), "ranged_cells"],
            cc.loc[cat, "availability_cy"], "reports/phase5/category_contribution.csv (6 dp)", 1e-6)
        add(f"{cat} H2 2024 availability = Phase 5", h.loc[(2024, cat), "in_stock_cells"] / h.loc[(2024, cat), "ranged_cells"],
            cc.loc[cat, "availability_py"], "reports/phase5/category_contribution.csv (6 dp)", 1e-6)
        add(f"{cat} H2 2025 gross margin = Phase 5", h.loc[(2025, cat), "gross_margin"], cc.loc[cat, "gross_margin_cy"],
            "reports/phase5/category_contribution.csv")
    fw = cw[(cw["retail_week"] >= 27) & (cw["category"] == "Electronics & Tech")].groupby("retail_year")["full_week_stockout_cells"].sum()
    reg = read_csv(cfg["actions"]["inputs"]["phase7_register"], cfg).set_index("id")
    ep = read_csv("reports/phase6/electronics_stockout_episodes.csv", cfg)
    add("E&T full-week stock-outs H2 2025 = Phase 6 (all suppliers)", fw[2025],
        ep[ep["retail_year"] == 2025]["full_weeks_out"].sum(), "reports/phase6/electronics_stockout_episodes.csv", 0)
    add("E&T full-week stock-outs H2 2024 = Phase 6", fw[2024], ep[ep["retail_year"] == 2024]["full_weeks_out"].sum(),
        "reports/phase6/electronics_stockout_episodes.csv", 0)
    fr = read_csv("reports/phase6/faulty_returns_reasons.csv", cfg).set_index("return_reason")
    et = cw[(cw["retail_week"] >= 27) & (cw["category"] == "Electronics & Tech")].groupby("retail_year")["faulty_value"].sum()
    add("E&T 'Faulty' refunds H2 2025 = Phase 6", et[2025], fr.loc["Faulty", "returns_value_cy"], "reports/phase6/faulty_returns_reasons.csv")
    add("E&T 'Faulty' refunds H2 2024 = Phase 6", et[2024], fr.loc["Faulty", "returns_value_py"], "reports/phase6/faulty_returns_reasons.csv")
    hk = cw[(cw["retail_week"] >= 27) & (cw["category"] == "Home & Kitchen")].groupby("retail_year")[["discount_amount", "gross_amount"]].sum()
    for yr, rid in [(2024, "P5-09"), (2025, "P5-10")]:
        add(f"Home & Kitchen H2 {yr} discount rate = Phase 7 register ({rid})", hk.loc[yr, "discount_amount"] / hk.loc[yr, "gross_amount"],
            float(reg.loc[rid, "value"]), "reports/phase7/dashboard_number_register.csv", 1e-9)
    # cluster transactions per store change (Phase 7 register P2-T0 / P2-T1)
    cl = sw[(sw["retail_week"] >= 27) & sw["store_id"].isin(["S03", "S04", "S05"])].groupby("retail_year")["transactions"].sum()
    add("S03-S05 transactions YoY H2 = Phase 7 register (P2-01)", cl[2025] / cl[2024] - 1, float(reg.loc["P2-01", "value"]),
        "reports/phase7/dashboard_number_register.csv", 1e-9)
    return pd.DataFrame(rows)
