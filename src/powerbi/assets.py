"""Power BI build assets written to powerbi/: Power Query (M) per table, the report theme, the DAX listing and
TMDL script, the model definition (tables, relationships) and the DAX validation queries with expected values.
"""
from __future__ import annotations

import json
import math
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

import pandas as pd

from . import dax as DX
from .model import RELATIONSHIPS, TABLES
from .reference import Ctx, Model, evaluate, h2

MONEY = {"gross_amount", "discount_amount", "sales_revenue", "cost_amount", "refund_value", "restock_cost_credit",
         "target_net_revenue", "list_price"}


def _m_type(col: str, dtype: str) -> str:
    if dtype == "bool":
        return "type logical"
    if col in MONEY:
        return "Currency.Type"
    if dtype.startswith("datetime"):
        return "type date"
    if dtype in ("str", "object", "string"):
        return "type text"
    if dtype.startswith("float"):
        return "type number"
    return "Int64.Type"


def power_query(tables: dict[str, pd.DataFrame], extracts: dict[str, pd.DataFrame], out: Path, database: str) -> list[str]:
    """One .pq file per table. Star-schema tables: SQL Server route and CSV route; Phase 6 tables: CSV (committed)."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    params = ("// Parameters (Home > Transform data > Manage parameters):\n"
              "//   ServerName   (Text)  e.g. localhost\n"
              f"//   DatabaseName (Text)  {database}\n"
              "//   ModelFolder  (Text)  full path of data\\powerbi (CSV route only)\n"
              "//   AnalyticsFolder (Text) full path of powerbi\\data\n")
    for name, (view, _) in TABLES.items():
        df = tables[name]
        types = ",\n        ".join(f'{{"{c}", {_m_type(c, str(t))}}}' for c, t in df.dtypes.astype(str).items())
        schema, item = view.split(".")
        # Store[store_group] is a DAX calculated column (LOOKUPVALUE on p6_store_groups), not a Power Query merge:
        # a query that both reads a source and references another query triggers Formula.Firewall errors.
        merge = ""
        last = "Typed"
        sql = f"""{params}
// {name}: SQL Server route (recommended). Import mode.
let
    Source = Sql.Database(ServerName, DatabaseName),
    Data = Source{{[Schema = "{schema}", Item = "{item}"]}}[Data],
    Typed = Table.TransformColumnTypes(Data, {{
        {types}
    }}){',' if merge else ''}{merge}
in
    {last}
"""
        csv = f"""{params}
// {name}: CSV route (no SQL Server). File written by python -m src.powerbi.run_phase7 --extract
let
    Source = Csv.Document(File.Contents(ModelFolder & "\\{name.lower()}.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {{
        {types}
    }}, "en-US"){',' if merge else ''}{merge}
in
    {last}
"""
        (out / f"{name}.sql_server.pq").write_text(sql, encoding="utf-8")
        (out / f"{name}.csv.pq").write_text(csv, encoding="utf-8")
        written += [f"{name}.sql_server.pq", f"{name}.csv.pq"]
    for name, df in extracts.items():
        if name.startswith("_"):
            continue
        types = ",\n        ".join(f'{{"{c}", {_m_type(c, str(t)) if c not in MONEY else "type number"}}}'
                                   for c, t in df.dtypes.astype(str).items())
        m = f"""{params}
// {name}: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\\{name}.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {{
        {types}
    }}, "en-US")
in
    Typed
"""
        (out / f"{name}.pq").write_text(m, encoding="utf-8")
        written.append(f"{name}.pq")
    return written


THEME = {
    "name": "Brightwater Evidence",
    "dataColors": ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#8F8D87", "#E34948", "#52514E", "#9CC3F0"],
    "background": "#FFFFFF", "foreground": "#0B0B0B", "tableAccent": "#2A78D6",
    "good": "#1BAF7A", "neutral": "#EDA100", "bad": "#E34948",
    "maximum": "#2A78D6", "center": "#F0EFEC", "minimum": "#E34948",
    "textClasses": {
        "callout": {"fontSize": 28, "fontFace": "Segoe UI Semibold", "color": "#0B0B0B"},
        "title": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": "#0B0B0B"},
        "header": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": "#0B0B0B"},
        "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": "#52514E"},
    },
    "visualStyles": {"*": {"*": {
        "background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
        "border": [{"show": False}],
        "title": [{"show": True, "fontColor": {"solid": {"color": "#0B0B0B"}}, "fontSize": 12}],
    }}},
}

# Evidence colours (config/powerbi_config.yaml) are used for evidence labels only, always with text.


def theme(out: Path) -> None:
    out.write_text(json.dumps(THEME, indent=2) + "\n", encoding="utf-8")


def model_definition(tables: dict[str, pd.DataFrame], extracts: dict[str, pd.DataFrame]) -> dict:
    return {
        "storage_mode": "Import",
        "star_schema_tables": {k: {"source_view": v[0], "rows": int(len(tables[k])),
                                   "columns": list(tables[k].columns) + (["store_group"] if k == "Store" else [])}
                               for k, v in TABLES.items()},
        "phase6_tables": {k: {"rows": int(len(v)), "columns": list(v.columns)} for k, v in extracts.items()
                          if not k.startswith("_")},
        "relationships": [{"from": f"{r['from'][0]}[{r['from'][1]}]", "to": f"{r['to'][0]}[{r['to'][1]}]",
                           "cardinality": "many-to-one", "cross_filter": "single", "active": r["active"]}
                          for r in RELATIONSHIPS],
        "mark_as_date_table": {"table": "Date", "column": "calendar_date",
                               "note": "Time intelligence uses Date[same_day_last_year_key], not built-in functions"},
        "hide_in_report_view": ["all *_key columns", "Sales, Returns, Inventory, Targets fact columns (use measures)"],
        "sort_by": {"Date[month_name]": "Date[calendar_month]", "Date[day_name]": "Date[day_of_week]",
                    "Date[period_label]": "Date[retail_year]"},
    }


# ---------------------------------------------------------------------- DAX validation queries
# VertiPaq stores a Currency column as a fixed-point decimal with scale 4, and DAX type propagation
# follows the operands: Money / Money and Whole Number / Whole Number both promote to double, but
# Money / Whole Number stays Currency and the quotient is quantised to 4 decimal places. Only the
# money-over-count ratios are affected; verified in Power BI Desktop against this model:
#   ASP  = 9840827.879999999 / 457916 = 21.490465238165949650  -> Currency -> 21.4905
#   ATV  = 9840827.879999999 / 216027 = 45.553694121568132687  -> Currency -> 45.5537
# Every other ratio measure is money/money (Gross Margin %, Return Rate, Promotion Share, Discount
# Rate) or whole-number/whole-number (UPT, Transactions per Store) and keeps full float64 precision.
# The observed quotients are not exact ties at the 5th decimal, so the data does not discriminate the
# tie rule; ROUND_HALF_EVEN is used, consistent with IEEE 754 round-half-to-even.
#
# This is an engine-typing effect, NOT a business definition change: the business formula stays
# sales_revenue / units, and the reference implementation in reference.py stays full precision so the
# Phase 5 reconciliation (reports/phase5/headline_kpis.csv, tolerance 1e-6) is unaffected. Only the
# expected value of the DAX query is quantised, which is what Power BI actually returns.
CURRENCY_SCALE = Decimal("0.0001")
CURRENCY_RATIO_MEASURES = frozenset({"ASP", "Average Transaction Value"})


def currency(value: float) -> float:
    """Quantise a DAX result that Power BI returns in the Currency type (4 decimal places)."""
    if not math.isfinite(value):
        return value
    with localcontext() as ctx:
        ctx.prec = 50
        q = Decimal(repr(float(value))).quantize(CURRENCY_SCALE, rounding=ROUND_HALF_EVEN)
    return float(q)


def validation_cases(M: Model, cfg: dict, extracts: dict | None = None) -> list[dict]:
    """(label, DAX expression, expected value from the reconciled reference, tolerance)."""
    hd = cfg["powerbi"]["headline"]
    et, hk, sup = (cfg["powerbi"]["focus_category_availability"], cfg["powerbi"]["focus_category_promotions"],
                   cfg["powerbi"]["focus_supplier"])
    H = lambda y: f"'Date'[retail_year] = {y}, 'Date'[retail_half] = \"H2\""  # noqa: E731
    cy, py = h2(hd["retail_year_cy"]), h2(hd["retail_year_py"])
    cases = []

    def add(label, measure, dax_filters, ctx, tol=0.01, scale=1.0):
        v = evaluate(M, measure, ctx)
        if measure in CURRENCY_RATIO_MEASURES:
            v = currency(v)
        cases.append({"label": label, "dax": f"CALCULATE ( [{measure}], {dax_filters} )",
                      "expected": float(scale * v), "tolerance": tol})
    Y, P = H(hd["retail_year_cy"]), H(hd["retail_year_py"])
    for m, tol in (("Net Revenue", 0.01), ("Net Revenue PY", 0.01), ("Net Revenue YoY", 0.01), ("Net Revenue YoY %", 1e-9),
                   ("Sales Revenue", 0.01), ("Returns Value", 0.01), ("Gross Margin", 0.01), ("Gross Margin %", 1e-9),
                   ("Gross Margin PY", 0.01), ("Transactions", 0), ("Transactions PY", 0), ("Units", 0), ("UPT", 1e-9),
                   ("ASP", 1e-9), ("Average Transaction Value", 1e-9), ("Return Rate", 1e-9), ("Promotion Share", 1e-9),
                   ("Discount Rate", 1e-9), ("Availability", 1e-9), ("Availability PY", 1e-9),
                   ("Target Achievement %", 1e-9)):
        add(f"{m} (H2 2025)", m, Y, cy, tol)
    add("Net Revenue (H2 2024, direct filter)", "Net Revenue", P, py)
    for s in cfg["powerbi"]["store_cluster"]:
        add(f"{s} Net Revenue YoY", "Net Revenue YoY", f"{Y}, Store[store_id] = \"{s}\"", cy.with_("Store", store_id=s))
        add(f"{s} Transactions YoY %", "Transactions YoY %", f"{Y}, Store[store_id] = \"{s}\"",
            cy.with_("Store", store_id=s), 1e-9)
    add("Investigated cluster Transactions YoY %", "Transactions YoY %", f"{Y}, Store[store_group] = \"Investigated cluster\"",
        cy.with_("Store", store_group="Investigated cluster"), 1e-9)
    add("Matched control Transactions YoY %", "Transactions YoY %", f"{Y}, Store[store_group] = \"Matched control\"",
        cy.with_("Store", store_group="Matched control"), 1e-9)
    add(f"{et} Net Revenue YoY", "Net Revenue YoY", f"{Y}, Product[category] = \"{et}\"", cy.with_("Product", category=et))
    add(f"{et} Availability", "Availability", f"{Y}, Product[category] = \"{et}\"", cy.with_("Product", category=et), 1e-9)
    add(f"{et} Availability PY", "Availability PY", f"{Y}, Product[category] = \"{et}\"", cy.with_("Product", category=et), 1e-9)
    c_sup = cy.with_("Product", category=et, supplier_name=sup)
    add(f"{sup} Full-Week Stock-Outs", "Full-Week Stock-Outs", f"{Y}, Product[supplier_name] = \"{sup}\"",
        cy.with_("Product", supplier_name=sup), 0)
    add(f"{sup} Full-Week Stock-Outs PY", "Full-Week Stock-Outs PY", f"{Y}, Product[supplier_name] = \"{sup}\"",
        cy.with_("Product", supplier_name=sup), 0)
    del c_sup
    c_f = cy.with_("Product", category=et).with_("Returns", return_reason="Faulty")
    add(f"{et} 'Faulty' Returns Value YoY", "Returns Value YoY",
        f"{Y}, Product[category] = \"{et}\", Returns[return_reason] = \"Faulty\"", c_f)
    add(f"{hk} Discount Rate", "Discount Rate", f"{Y}, Product[category] = \"{hk}\"", cy.with_("Product", category=hk), 1e-9)
    add(f"{hk} Discount Rate PY", "Discount Rate PY", f"{Y}, Product[category] = \"{hk}\"", cy.with_("Product", category=hk), 1e-9)
    add("Week 30 Net Revenue PY", "Net Revenue PY", f"'Date'[retail_year] = {hd['retail_year_cy']}, 'Date'[retail_week] = 30",
        Ctx({"Date": {"retail_year": hd["retail_year_cy"], "retail_week": 30}}))
    add("Sep 2025 sale cohort: returns by sale date (Faulty, E&T)", "Returns Value (by Sale Date)",
        f"'Date'[year_month] = 202509, Product[category] = \"{et}\", Returns[return_reason] = \"Faulty\"",
        Ctx({"Date": {"year_month": 202509}, "Product": {"category": et}, "Returns": {"return_reason": "Faulty"}}))
    # guards: blank (not a wrong number) where a fact has no key for the filter
    cases.append({"label": "Guard: Net Revenue blank under a Promotion filter (1 = blank)",
                  "dax": "IF ( ISBLANK ( CALCULATE ( [Net Revenue], Promotion[member_type] = \"Promotion\" ) ), 1, 0 )",
                  "expected": 1.0, "tolerance": 0})
    cases.append({"label": "Guard: Target Achievement blank under a category filter (1 = blank)",
                  "dax": f"IF ( ISBLANK ( CALCULATE ( [Target Achievement %], {Y}, Product[category] = \"{et}\" ) ), 1, 0 )",
                  "expected": 1.0, "tolerance": 0})
    if extracts is not None:     # imported Phase 6 tables: checks that the CSVs loaded with the right types
        sk = extracts["p6_et_sku_stockouts"]
        tot = float(sk["lost_primary_change"].sum())
        ep = extracts["p6_et_episodes"].set_index(["supplier_name", "retail_year"])
        ss = extracts["p6_sensitivity_summary"].set_index("driver")
        net = extracts["p6_stockout_net_of_recovery"].set_index("driver")
        ev = extracts["p6_hk_events_by_year"].set_index("retail_year")
        for label, dax, exp in (
                ("P6: High-Seller Share of Lost Sales", "[High-Seller Share of Lost Sales (P6)]",
                 float(sk.loc[sk["high_seller"].astype(bool), "lost_primary_change"].sum()) / tot),
                ("P6: Top SKU Share of Lost Sales", "[Top SKU Share of Lost Sales (P6)]",
                 float(sk["lost_primary_change"].max()) / tot),
                ("P6: Top 3 SKU Share of Lost Sales", "[Top 3 SKU Share of Lost Sales (P6)]",
                 float(sk["lost_primary_change"].nlargest(3).sum()) / tot),
                ("P6: Lost Sales Gross", "[Lost Sales Gross (P6)]", float(
                    extracts["p6_et_lost_sales_totals"].set_index("scope").loc["category", "primary_change"])),
                ("P6: Lost Sales Net of Deferred Demand", "[Lost Sales Net of Deferred Demand (P6)]",
                 -float(net.loc["electronics_stockouts_primary", "estimate_eur"])),
                ("P6: Lost Sales Range Low", "[Lost Sales Range Low (P6)]",
                 -float(ss.loc["electronics_stockouts_primary", "range_high_eur"])),
                ("P6: Lost Sales Range High", "[Lost Sales Range High (P6)]",
                 -float(ss.loc["electronics_stockouts_primary", "range_low_eur"])),
                ("P6: Cluster Excess", "[Cluster Excess (P6)]", float(
                    extracts["p6_driver_attribution"].set_index("driver_id").loc["D01", "amount_eur"])),
                (f"P6: {sup} episodes H2 2025", f"CALCULATE ( [Stock-Out Episodes (P6)], p6_et_episodes[supplier_name] = "
                 f"\"{sup}\", p6_et_episodes[retail_year] = 2025 )", float(ep.loc[(sup, 2025), "episodes"])),
                ("P6: Promotion events H2 2025", "CALCULATE ( [Promotion Events (P6)], p6_hk_events_by_year[retail_year] = 2025 )",
                 float(ev.loc[2025, "events"])),
                ("P6: HK Method Effect total is blank (1 = blank)", "IF ( ISBLANK ( [HK Method Effect Guarded] ), 1, 0 )", 1.0),
                ("P6: Driver Impact total is blank (1 = blank)", "IF ( ISBLANK ( [Driver Impact (single driver)] ), 1, 0 )", 1.0)):
            cases.append({"label": label, "dax": dax, "expected": exp, "tolerance": 1e-6})
    return cases


def validation_queries_text(cases: list[dict], attribution_total: float) -> str:
    rows = [f'        ( "{c["label"]}", {c["dax"]}, {c["expected"]!r}, {c["tolerance"]!r} )' for c in cases]
    rows.append(f'        ( "Attribution total (Phase 6 table) = H2 change", [Attribution Total], '
                f'{round(attribution_total, 6)!r}, 0.01 )')
    body = ",\n".join(rows)
    return f"""// Brightwater Retail Phase 7: DAX validation queries.
// Run in Power BI Desktop: View > DAX query view > paste > Run. Every row must show PASS.
// Expected values come from the Python reference implementation, which reconciles to Phase 4, 5 and 6
// (reports/phase7/phase7_validation_checks.csv). Generated by src/powerbi/assets.py; do not edit by hand.

EVALUATE
VAR _cases =
    {{
{body}
    }}
RETURN
    SELECTCOLUMNS (
        _cases,
        "Check", [Value1],
        "Power BI", [Value2],
        "Expected", [Value3],
        "Difference", [Value2] - [Value3],
        "Status", IF ( ABS ( [Value2] - [Value3] ) <= [Value4], "PASS", "FAIL" )
    )
ORDER BY [Status], [Check]

// Second query: the fixed-context QA measures and the attribution check text.
EVALUATE
ROW (
    "QA Net Revenue H2 2025", [QA Net Revenue H2 2025],
    "QA Net Revenue H2 2024", [QA Net Revenue H2 2024],
    "QA Attribution Check", [QA Attribution Check]
)
"""
