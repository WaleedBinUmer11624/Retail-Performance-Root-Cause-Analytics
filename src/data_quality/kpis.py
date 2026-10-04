"""BRD KPI definitions (section 5) used to reconcile figures before and after cleaning.

The same formulas are applied to three views:
  raw_as_reported   main extract and returns read at face value (what a spreadsheet process would show)
  clean_main_only   curated data without the late file (isolates the effect of cleaning)
  clean_complete    curated data including the late file (the trusted figure)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import parse_date_dmy, parse_date_iso, to_num


def kpis(sales: pd.DataFrame, returns: pd.DataFrame, inventory: pd.DataFrame | None = None) -> dict:
    """Headline KPIs from typed sales, returns and, optionally, inventory frames."""
    q, p = sales["quantity"], sales["unit_price"]
    gross = float((q * p).sum())
    disc = float(sales["discount"].sum())
    srev = float(sales["revenue"].sum())
    ret = float(returns["refund_value"].sum())
    units = float(q.sum())
    tx = int(sales["transaction_id"].nunique())
    cost_map = sales.groupby("product_id")["unit_cost"].median()
    rts = returns[returns["restockable_flag"].astype(str).str.lower() == "true"]
    cogs = float(sales["cost"].sum() - (rts["return_quantity"].astype(float) * rts["product_id"].map(cost_map).fillna(0)).sum())
    net = srev - ret
    promo = sales["promotion_id"].notna() & (sales["promotion_id"].astype(str) != "")
    out = {"sales_lines": len(sales), "gross_sales": gross, "discount_value": disc, "sales_revenue": srev,
           "returns_value": ret, "net_revenue": net, "cogs": cogs, "gross_margin": net - cogs,
           "gross_margin_pct": (net - cogs) / net if net else np.nan, "transactions": tx, "units": units,
           "aov": srev / tx, "upt": units / tx, "asp": srev / units, "return_rate_value": ret / srev,
           "promo_revenue_share": float(sales.loc[promo, "revenue"].sum()) / srev, "returns_rows": len(returns)}
    if inventory is not None:
        inv = inventory[inventory["retail_year"].astype(float) == 2024]
        out["stock_availability_2024"] = float((inv["closing_stock"].astype(float) > 0).mean())
    return out


def h2_net_revenue(sales: pd.DataFrame, returns: pd.DataFrame, dim_date: pd.DataFrame) -> dict:
    """Week-aligned H2 (retail weeks 27-52) net revenue per retail year; returns by return date."""
    out = {}
    for y in (2024, 2025):
        d = dim_date.loc[(dim_date["retail_year"] == y) & (dim_date["retail_week"].between(27, 52)), "date"]
        lo, hi = d.min(), d.max()
        s = float(sales.loc[sales["transaction_date"].between(lo, hi), "revenue"].sum())
        r = float(returns.loc[returns["return_date"].between(lo, hi), "refund_value"].sum())
        out[f"h2_{y}_net_revenue"] = s - r
    out["h2_yoy_pct"] = 100 * (out["h2_2025_net_revenue"] / out["h2_2024_net_revenue"] - 1)
    return out


def naive_views(main_raw: pd.DataFrame, returns_raw: pd.DataFrame, inventory_raw: pd.DataFrame) -> tuple:
    """Face-value parse of the raw text: numbers as they are, blanks as zero, no de-duplication,
    dates parsed where possible (unparseable dates silently fall out of period totals)."""
    s = pd.DataFrame({c: to_num(main_raw[c]).fillna(0) for c in
                      ("quantity", "unit_price", "discount", "revenue", "unit_cost", "cost", "margin")})
    s["transaction_id"] = main_raw["transaction_id"]
    s["product_id"] = main_raw["product_id"]
    s["promotion_id"] = main_raw["promotion_id"]
    s["transaction_date"] = parse_date_iso(main_raw["transaction_date"]).fillna(parse_date_dmy(main_raw["transaction_date"]))
    r = pd.DataFrame({"refund_value": to_num(returns_raw["refund_value"]).fillna(0),
                      "return_quantity": to_num(returns_raw["return_quantity"]).fillna(0),
                      "product_id": returns_raw["product_id"], "restockable_flag": returns_raw["restockable_flag"],
                      "return_date": parse_date_iso(returns_raw["return_date"])})
    inv = pd.DataFrame({"retail_year": to_num(inventory_raw["retail_year"]),
                        "closing_stock": to_num(inventory_raw["closing_stock"])})
    return s, r, inv


KPI_LABELS = {
    "sales_lines": ("Sales lines", "{:,.0f}"), "gross_sales": ("Gross Sales (EUR)", "{:,.2f}"),
    "discount_value": ("Discount Value (EUR)", "{:,.2f}"), "sales_revenue": ("Sales Revenue (EUR)", "{:,.2f}"),
    "returns_value": ("Returns Value (EUR)", "{:,.2f}"), "net_revenue": ("Net Revenue (EUR)", "{:,.2f}"),
    "cogs": ("COGS (EUR)", "{:,.2f}"), "gross_margin": ("Gross Margin (EUR)", "{:,.2f}"),
    "gross_margin_pct": ("Gross Margin %", "{:.2%}"), "transactions": ("Transactions", "{:,.0f}"),
    "units": ("Units", "{:,.0f}"), "aov": ("AOV (EUR)", "{:,.2f}"), "upt": ("UPT", "{:.3f}"),
    "asp": ("ASP (EUR)", "{:,.2f}"), "return_rate_value": ("Return Rate % (value)", "{:.2%}"),
    "promo_revenue_share": ("Promo Revenue Share %", "{:.2%}"), "returns_rows": ("Returns rows", "{:,.0f}"),
    "stock_availability_2024": ("Stock Availability % (2024)", "{:.2%}"),
    "h2_2024_net_revenue": ("H2 2024 Net Revenue (EUR)", "{:,.2f}"),
    "h2_2025_net_revenue": ("H2 2025 Net Revenue (EUR)", "{:,.2f}"), "h2_yoy_pct": ("H2 YoY %", "{:.2f}%"),
}
