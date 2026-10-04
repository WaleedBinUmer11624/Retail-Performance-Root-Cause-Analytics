"""Python reference implementation of the Power BI DAX measure layer.

This environment cannot run DAX. Every DAX measure in powerbi/dax/measures.dax has a counterpart here with
the SAME filter semantics as the semantic model (single-direction many-to-one relationships, dimension
filters flowing to facts, the inactive cohort relationship, the week mapping for targets and the
same-day-last-year shift for prior-year measures). Evaluating these functions on the pbi tables and
reconciling them to Phase 4, 5 and 6 validates the measure LOGIC. Power BI Desktop must still confirm the
DAX itself (powerbi/dax/validation_queries.dax lists the expected values).

A filter context is a dict: {table: {column: value or list of values}} on the dimension tables
Date, Store, Product, Promotion, plus {"Returns": {"return_reason": ...}} for the fact-level column.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FACT_DATE_COL = {"Sales": "date_key", "Returns": "return_date_key", "Inventory": "snapshot_date_key"}


def _mask(df: pd.DataFrame, flt: dict | None) -> np.ndarray:
    m = np.ones(len(df), dtype=bool)
    for col, val in (flt or {}).items():
        vals = val if isinstance(val, (list, tuple, set, np.ndarray, pd.Index)) else [val]
        m &= df[col].isin(list(vals)).to_numpy()
    return m


@dataclass
class Ctx:
    filters: dict = field(default_factory=dict)
    cohort: bool = False            # USERELATIONSHIP(Returns[original_sale_date_key], Date[date_key])
    date_keys: frozenset | None = None   # explicit date keys (set by the PY shift, like TREATAS)

    def with_(self, table: str, **cols) -> "Ctx":
        f = {k: dict(v) for k, v in self.filters.items()}
        f.setdefault(table, {}).update(cols)
        return Ctx(f, self.cohort, self.date_keys)


class Model:
    def __init__(self, tables: dict[str, pd.DataFrame]):
        self.t = tables

    # ------------------------------------------------------------------ filter propagation
    def _dim_keys(self, table: str, key: str, ctx: Ctx):
        f = ctx.filters.get(table)
        if not f:
            return None
        d = self.t[table]
        return set(d.loc[_mask(d, f), key])

    def _date_keys(self, ctx: Ctx):
        keys = self._dim_keys("Date", "date_key", ctx)
        if ctx.date_keys is not None:
            keys = set(ctx.date_keys) if keys is None else keys & set(ctx.date_keys)
        return keys

    def rows(self, fact: str, ctx: Ctx) -> pd.DataFrame:
        df = self.t[fact]
        m = np.ones(len(df), dtype=bool)
        if fact in FACT_DATE_COL:
            col = "original_sale_date_key" if (fact == "Returns" and ctx.cohort) else FACT_DATE_COL[fact]
            dk = self._date_keys(ctx)
            if dk is not None:
                m &= df[col].isin(dk).to_numpy()
        if fact == "Targets":
            dk = self._date_keys(ctx)
            if dk is not None:   # TREATAS(VALUES('Date'[retail_week_key]), Targets[retail_week_key])
                weeks = set(self.t["Date"].loc[self.t["Date"]["date_key"].isin(dk), "retail_week_key"])
                m &= df["retail_week_key"].isin(weeks).to_numpy()
        for dim, key in (("Store", "store_key"), ("Product", "product_key"), ("Promotion", "promotion_key")):
            if key in df.columns and not (fact != "Sales" and dim == "Promotion"):
                ks = self._dim_keys(dim, key, ctx)
                if ks is not None:
                    m &= df[key].isin(ks).to_numpy()
        if fact in ctx.filters:              # fact-level columns (e.g. Returns[return_reason], Sales[is_promoted])
            m &= _mask(df, ctx.filters[fact])
        return df.loc[m]

    def py_ctx(self, ctx: Ctx) -> Ctx:
        """REMOVEFILTERS('Date') + TREATAS(VALUES('Date'[same_day_last_year_key]), 'Date'[date_key])."""
        keys = self._date_keys(ctx)
        d = self.t["Date"]
        sel = d if keys is None else d[d["date_key"].isin(keys)]
        shifted = frozenset(sel["same_day_last_year_key"].dropna().astype(int))
        f = {k: v for k, v in ctx.filters.items() if k != "Date"}
        return Ctx(f, ctx.cohort, shifted)


def _div(a, b):
    return float(a) / float(b) if b else float("nan")


NAN = float("nan")


def _promo(c):      # ISCROSSFILTERED ( Promotion )
    return "Promotion" in c.filters


def _prod_or_promo(c):   # ISCROSSFILTERED ( Product ) || ISCROSSFILTERED ( Promotion )
    return "Product" in c.filters or "Promotion" in c.filters


# ---------------------------------------------------------------------- base measures (mirror measures.dax)
def sales_revenue(M, c):  return float(M.rows("Sales", c)["sales_revenue"].sum())
def gross_sales(M, c):    return float(M.rows("Sales", c)["gross_amount"].sum())
def discount_value(M, c): return float(M.rows("Sales", c)["discount_amount"].sum())
def cost_of_sales(M, c):  return float(M.rows("Sales", c)["cost_amount"].sum())
def units(M, c):          return float(M.rows("Sales", c)["quantity"].sum())
def transactions(M, c):   return float(M.rows("Sales", c)["transaction_key"].nunique())
def returns_value(M, c):  return NAN if _promo(c) else float(M.rows("Returns", c)["refund_value"].sum())
def returned_units(M, c): return NAN if _promo(c) else float(M.rows("Returns", c)["return_quantity"].sum())
def restock_credit(M, c): return NAN if _promo(c) else float(M.rows("Returns", c)["restock_cost_credit"].sum())
def net_revenue(M, c):    return NAN if _promo(c) else sales_revenue(M, c) - returns_value(M, c)
def cogs(M, c):           return NAN if _promo(c) else cost_of_sales(M, c) - restock_credit(M, c)
def gross_margin(M, c):   return net_revenue(M, c) - cogs(M, c)
def gross_margin_pct(M, c): return _div(gross_margin(M, c), net_revenue(M, c))
def upt(M, c):            return _div(units(M, c), transactions(M, c))
def asp(M, c):            return _div(sales_revenue(M, c), units(M, c))
def atv(M, c):            return _div(sales_revenue(M, c), transactions(M, c))
def return_rate(M, c):    return _div(returns_value(M, c), sales_revenue(M, c))
def promo_revenue(M, c):  return sales_revenue(M, c.with_("Sales", is_promoted=1))
def promo_share(M, c):    return _div(promo_revenue(M, c), sales_revenue(M, c))
def discount_rate(M, c):  return _div(discount_value(M, c), gross_sales(M, c))
def ranged_cells(M, c):   return NAN if _promo(c) else float(len(M.rows("Inventory", c)))
def in_stock_cells(M, c): return NAN if _promo(c) else float(M.rows("Inventory", c)["is_in_stock"].sum())
def availability(M, c):   return _div(in_stock_cells(M, c), ranged_cells(M, c))
def full_week_stockouts(M, c): return NAN if _promo(c) else float(M.rows("Inventory", c)["is_full_week_stockout"].sum())
def target_net_revenue(M, c):
    return NAN if _prod_or_promo(c) else float(M.rows("Targets", c)["target_net_revenue"].sum())
def net_revenue_target_weeks(M, c):
    """Net Revenue over the store-weeks that HAVE a target (Phase 5 diag.v_target_store_h2: weeks without a
    target are excluded from both sides of Target Achievement)."""
    if _prod_or_promo(c):
        return NAN
    pairs = M.rows("Targets", c)[["store_key", "retail_week_key"]].drop_duplicates()
    wk = M.t["Date"].set_index("date_key")["retail_week_key"]
    s = M.rows("Sales", c)
    r = M.rows("Returns", c)
    s = s.assign(retail_week_key=s["date_key"].map(wk)).groupby(["store_key", "retail_week_key"])["sales_revenue"].sum()
    r = r.assign(retail_week_key=r["return_date_key"].map(wk)).groupby(["store_key", "retail_week_key"])["refund_value"].sum()
    idx = pd.MultiIndex.from_frame(pairs)
    return float(s.reindex(idx).fillna(0).sum() - r.reindex(idx).fillna(0).sum())
def target_achievement(M, c): return _div(net_revenue_target_weeks(M, c), target_net_revenue(M, c))
def returns_by_sale_date(M, c): return returns_value(M, Ctx(c.filters, True, c.date_keys))


def py(fn):
    return lambda M, c: fn(M, M.py_ctx(c))


def yoy_abs(fn):
    return lambda M, c: fn(M, c) - fn(M, M.py_ctx(c))


def yoy_pct(fn):
    return lambda M, c: _div(fn(M, c), fn(M, M.py_ctx(c))) - 1


def yoy_pp(fn):
    return lambda M, c: fn(M, c) - fn(M, M.py_ctx(c))


MEASURES = {
    "Sales Revenue": sales_revenue, "Gross Sales": gross_sales, "Discount Value": discount_value,
    "Cost of Sales": cost_of_sales, "Returns Value": returns_value, "Returned Units": returned_units,
    "Restock Cost Credit": restock_credit, "Net Revenue": net_revenue, "COGS": cogs, "Gross Margin": gross_margin,
    "Gross Margin %": gross_margin_pct, "Transactions": transactions, "Units": units, "UPT": upt, "ASP": asp,
    "Average Transaction Value": atv, "Return Rate": return_rate, "Promotion Revenue": promo_revenue,
    "Promotion Share": promo_share, "Discount Rate": discount_rate, "Ranged Store-SKU-Weeks": ranged_cells,
    "In-Stock Store-SKU-Weeks": in_stock_cells, "Availability": availability,
    "Full-Week Stock-Outs": full_week_stockouts, "Target Net Revenue": target_net_revenue,
    "Target Achievement %": target_achievement,
    "Net Revenue (Target Weeks)": net_revenue_target_weeks, "Returns Value (by Sale Date)": returns_by_sale_date,
    "Net Revenue PY": py(net_revenue), "Net Revenue YoY": yoy_abs(net_revenue), "Net Revenue YoY %": yoy_pct(net_revenue),
    "Sales Revenue PY": py(sales_revenue), "Returns Value PY": py(returns_value),
    "Gross Margin PY": py(gross_margin), "Gross Margin YoY": yoy_abs(gross_margin),
    "Gross Margin % PY": py(gross_margin_pct), "Gross Margin % YoY pp": yoy_pp(gross_margin_pct),
    "Transactions PY": py(transactions), "Transactions YoY": yoy_abs(transactions),
    "Transactions YoY %": yoy_pct(transactions), "Units PY": py(units), "Units YoY %": yoy_pct(units),
    "UPT PY": py(upt), "ASP PY": py(asp), "Average Transaction Value PY": py(atv),
    "Return Rate PY": py(return_rate), "Return Rate YoY pp": yoy_pp(return_rate),
    "Promotion Share PY": py(promo_share), "Discount Rate PY": py(discount_rate),
    "Availability PY": py(availability), "Availability YoY pp": yoy_pp(availability),
    "Full-Week Stock-Outs PY": py(full_week_stockouts), "Returns Value YoY": yoy_abs(returns_value),
    "Returns Value YoY %": yoy_pct(returns_value),
}


def evaluate(M: Model, measure: str, ctx: Ctx | None = None) -> float:
    return MEASURES[measure](M, ctx or Ctx())


def h2(year: int) -> Ctx:
    return Ctx({"Date": {"retail_year": year, "retail_half": "H2"}})
