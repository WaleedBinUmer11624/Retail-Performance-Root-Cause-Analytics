"""The DAX measure layer, defined once here and written out as:
  * powerbi/dax/measures.dax          readable listing (one block per measure, with its description)
  * powerbi/dax/measures_tmdl.tmdl    a TMDL `createOrReplace` script for Power BI Desktop's TMDL view
  * reports/phase7/measure_dictionary.csv
Each core measure names its Python reference (src/powerbi/reference.py) so its logic is reconciled to
Phase 4, 5 and 6 in this environment. The DAX text itself can only be executed in Power BI Desktop.

Business logic lives in ONE place: the additive columns come from the governed Phase 4 star schema (pbi
views); every ratio is a DIVIDE of summed components here, never an average of ratios; Phase 6 figures
are read from the imported Phase 6 tables, never recomputed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

EUR = "€#,0"
EUR2 = "€#,0.00"
PCT = "0.0%"
PCT2 = "0.00%"
INT = "#,0"
DEC2 = "#,0.00"
PP = "+0.0;-0.0;0.0"


@dataclass
class Measure:
    name: str
    expr: str
    fmt: str
    folder: str
    description: str
    reference: str | None = None        # name in reference.MEASURES, or None for Phase 6 / text measures
    kind: str = "FACT"                  # evidence tag of what the measure returns


def _py(base: str, fmt: str, folder: str, desc: str) -> Measure:
    return Measure(f"{base} PY", f"""
VAR _pyDates = VALUES ( 'Date'[same_day_last_year_key] )
RETURN
    CALCULATE ( [{base}], REMOVEFILTERS ( 'Date' ), TREATAS ( _pyDates, 'Date'[date_key] ) )""", fmt, folder,
                   f"{base} for the same days one year earlier (364 days, so retail weeks align). {desc}", f"{base} PY")


def _yoy(base: str, fmt: str, folder: str) -> list[Measure]:
    return [Measure(f"{base} YoY", f"[{base}] - [{base} PY]", fmt, folder,
                    f"{base} change against the same period one year earlier.", f"{base} YoY"),
            Measure(f"{base} YoY %", f"DIVIDE ( [{base}] - [{base} PY], [{base} PY] )", PCT2, folder,
                    f"{base} growth against the same period one year earlier. Blank when the prior year is blank.",
                    f"{base} YoY %")]


PROMO_GUARD = "Returns, stock and targets have no promotion key, so it is blank when the Promotion table is filtered."

F_REV, F_MAR, F_TRX, F_RET, F_AVL, F_PRO, F_TGT = ("1 Revenue", "2 Margin", "3 Customers and baskets", "4 Returns",
                                                    "5 Availability", "6 Promotions", "7 Targets")
F_P6, F_TXT, F_QA = "8 Phase 6 evidence (fixed H2 2025 vs H2 2024)", "9 Labels and subtitles", "0 Validation"

MEASURES: list[Measure] = [
    # ---------------------------------------------------------------- revenue
    Measure("Sales Revenue", "SUM ( Sales[sales_revenue] )", EUR, F_REV,
            "Line revenue after discount (gross amount minus discount), counted on the sale date at the selling store.",
            "Sales Revenue"),
    Measure("Gross Sales", "SUM ( Sales[gross_amount] )", EUR, F_REV, "Quantity x unit price, before discount.",
            "Gross Sales"),
    Measure("Discount Value", "SUM ( Sales[discount_amount] )", EUR, F_REV, "Discount given on sales lines.",
            "Discount Value"),
    Measure("Returns Value", "IF ( ISCROSSFILTERED ( Promotion ), BLANK (), SUM ( Returns[refund_value] ) )", EUR, F_RET,
            "Refunds, counted on the return date at the returning store (BRD assumption 2). " + PROMO_GUARD,
            "Returns Value"),
    Measure("Net Revenue", "IF ( ISCROSSFILTERED ( Promotion ), BLANK (), [Sales Revenue] - [Returns Value] )", EUR, F_REV,
            "Governed headline KPI (BRD 5.1): Sales Revenue minus Returns Value. " + PROMO_GUARD, "Net Revenue"),
    _py("Net Revenue", EUR, F_REV, "Drives every YoY comparison."),
    *_yoy("Net Revenue", EUR, F_REV),
    _py("Sales Revenue", EUR, F_REV, ""),
    # ---------------------------------------------------------------- margin
    Measure("Cost of Sales", "SUM ( Sales[cost_amount] )", EUR, F_MAR, "Quantity x standard unit cost on the sale date.",
            "Cost of Sales"),
    Measure("Restock Cost Credit", "IF ( ISCROSSFILTERED ( Promotion ), BLANK (), SUM ( Returns[restock_cost_credit] ) )",
            EUR, F_MAR, "Cost credited back for returned units that go back to stock. " + PROMO_GUARD,
            "Restock Cost Credit"),
    Measure("COGS", "IF ( ISCROSSFILTERED ( Promotion ), BLANK (), [Cost of Sales] - [Restock Cost Credit] )", EUR, F_MAR,
            "Cost of goods sold net of returned-to-stock units (governed definition). " + PROMO_GUARD, "COGS"),
    Measure("Gross Margin", "[Net Revenue] - [COGS]", EUR, F_MAR, "Net Revenue minus COGS (governed definition).",
            "Gross Margin"),
    Measure("Gross Margin %", "DIVIDE ( [Gross Margin], [Net Revenue] )", PCT, F_MAR,
            "Gross Margin as a share of Net Revenue; ratio of sums, never an average of ratios.", "Gross Margin %"),
    _py("Gross Margin", EUR, F_MAR, ""),
    Measure("Gross Margin YoY", "[Gross Margin] - [Gross Margin PY]", EUR, F_MAR,
            "Gross Margin change against the same period one year earlier.", "Gross Margin YoY"),
    _py("Gross Margin %", PCT, F_MAR, ""),
    Measure("Gross Margin % YoY pp", "( [Gross Margin %] - [Gross Margin % PY] ) * 100", PP, F_MAR,
            "Change in Gross Margin % in percentage points.", None),
    # ---------------------------------------------------------------- customers and baskets
    Measure("Transactions", "DISTINCTCOUNT ( Sales[transaction_key] )", INT, F_TRX,
            "Receipts. With a product or category filter this is 'transactions containing the selection' "
            "(not additive across categories).", "Transactions"),
    _py("Transactions", INT, F_TRX, ""),
    *_yoy("Transactions", INT, F_TRX),
    Measure("Units", "SUM ( Sales[quantity] )", INT, F_TRX, "Units sold.", "Units"),
    _py("Units", INT, F_TRX, ""),
    Measure("Units YoY %", "DIVIDE ( [Units] - [Units PY], [Units PY] )", PCT2, F_TRX, "Units growth year on year.",
            "Units YoY %"),
    Measure("UPT", "DIVIDE ( [Units], [Transactions] )", DEC2, F_TRX, "Units per transaction.", "UPT"),
    _py("UPT", DEC2, F_TRX, ""),
    Measure("ASP", "DIVIDE ( [Sales Revenue], [Units] )", EUR2, F_TRX, "Average selling price per unit.", "ASP"),
    _py("ASP", EUR2, F_TRX, ""),
    Measure("Average Transaction Value", "DIVIDE ( [Sales Revenue], [Transactions] )", EUR2, F_TRX,
            "Sales Revenue per receipt (the governed AOV). Undefined for category filters (use ASP).",
            "Average Transaction Value"),
    _py("Average Transaction Value", EUR2, F_TRX, ""),
    Measure("Stores Trading", "DISTINCTCOUNT ( Sales[store_key] )", INT, F_TRX, "Stores with sales in the selection.",
            None),
    Measure("Transactions per Store", "DIVIDE ( [Transactions], [Stores Trading] )", INT, F_TRX,
            "Receipts per trading store; compares store groups of different sizes.", None),
    Measure("Transactions per Store YoY %", """
VAR _cy = [Transactions per Store]
VAR _py = CALCULATE ( [Transactions per Store], REMOVEFILTERS ( 'Date' ),
                      TREATAS ( VALUES ( 'Date'[same_day_last_year_key] ), 'Date'[date_key] ) )
RETURN DIVIDE ( _cy - _py, _py )""", PCT, F_TRX, "Year-on-year change in receipts per trading store.", None),
    # ---------------------------------------------------------------- returns
    Measure("Returned Units", "IF ( ISCROSSFILTERED ( Promotion ), BLANK (), SUM ( Returns[return_quantity] ) )", INT,
            F_RET, "Units returned (return date). " + PROMO_GUARD, "Returned Units"),
    _py("Returns Value", EUR, F_RET, ""),
    *_yoy("Returns Value", EUR, F_RET),
    Measure("Return Rate", "DIVIDE ( [Returns Value], [Sales Revenue] )", PCT2, F_RET,
            "Returns Value as a share of Sales Revenue in the same period (governed return rate, value basis).",
            "Return Rate"),
    _py("Return Rate", PCT2, F_RET, ""),
    Measure("Return Rate YoY pp", "( [Return Rate] - [Return Rate PY] ) * 100", PP, F_RET,
            "Change in Return Rate in percentage points.", None),
    Measure("Returns Value (by Sale Date)",
            "CALCULATE ( [Returns Value], USERELATIONSHIP ( Returns[original_sale_date_key], 'Date'[date_key] ) )",
            EUR, F_RET, "Refunds placed on the ORIGINAL sale date (sale cohort view); uses the inactive relationship.",
            "Returns Value (by Sale Date)"),
    Measure("Returned Units (by Sale Date)",
            "CALCULATE ( [Returned Units], USERELATIONSHIP ( Returns[original_sale_date_key], 'Date'[date_key] ) )",
            INT, F_RET, "Returned units placed on the original sale date.", None),
    Measure("Returned Units per 100 Sold (Sale Cohort)", "DIVIDE ( [Returned Units (by Sale Date)], [Units] ) * 100",
            DEC2, F_RET, "Returned units per 100 units sold, both on the sale date: the cohort rate used in Phase 6.",
            None),
    # ---------------------------------------------------------------- availability
    Measure("Ranged Store-SKU-Weeks", "IF ( ISCROSSFILTERED ( Promotion ), BLANK (), COUNTROWS ( Inventory ) )", INT, F_AVL,
            "Weekly stock snapshots of ranged store-SKUs. " + PROMO_GUARD, "Ranged Store-SKU-Weeks"),
    Measure("In-Stock Store-SKU-Weeks", "IF ( ISCROSSFILTERED ( Promotion ), BLANK (), SUM ( Inventory[is_in_stock] ) )", INT,
            F_AVL, "Snapshots with closing stock above zero. " + PROMO_GUARD, "In-Stock Store-SKU-Weeks"),
    Measure("Availability", "DIVIDE ( [In-Stock Store-SKU-Weeks], [Ranged Store-SKU-Weeks] )", PCT, F_AVL,
            "Stock Availability % (BRD 5.3): share of ranged store-SKU-weeks in stock at the weekly snapshot.",
            "Availability"),
    _py("Availability", PCT, F_AVL, ""),
    Measure("Availability YoY pp", "( [Availability] - [Availability PY] ) * 100", PP, F_AVL,
            "Change in Availability in percentage points.", None),
    Measure("Full-Week Stock-Outs", "IF ( ISCROSSFILTERED ( Promotion ), BLANK (), SUM ( Inventory[is_full_week_stockout] ) )",
            INT, F_AVL,
            "Store-SKU-weeks with no opening stock, nothing received and out of stock at the snapshot "
            "(Phase 5/6 definition).", "Full-Week Stock-Outs"),
    _py("Full-Week Stock-Outs", INT, F_AVL, ""),
    # ---------------------------------------------------------------- promotions
    Measure("Promotion Revenue", "CALCULATE ( [Sales Revenue], KEEPFILTERS ( Sales[is_promoted] = 1 ) )", EUR, F_PRO,
            "Sales Revenue on promoted lines.", "Promotion Revenue"),
    Measure("Promotion Share", "DIVIDE ( [Promotion Revenue], [Sales Revenue] )", PCT, F_PRO,
            "Promoted share of Sales Revenue (governed promo revenue share).", "Promotion Share"),
    _py("Promotion Share", PCT, F_PRO, ""),
    Measure("Discount Rate", "DIVIDE ( [Discount Value], [Gross Sales] )", PCT, F_PRO,
            "Discount as a share of gross sales (the Phase 6 discount-rate definition).", "Discount Rate"),
    _py("Discount Rate", PCT, F_PRO, ""),
    # ---------------------------------------------------------------- targets
    Measure("Target Net Revenue", """
IF (
    ISCROSSFILTERED ( Product ) || ISCROSSFILTERED ( Promotion ),
    BLANK (),
    CALCULATE (
        SUM ( Targets[target_net_revenue] ),
        TREATAS ( VALUES ( 'Date'[retail_week_key] ), Targets[retail_week_key] )
    )
)""", EUR, F_TGT, "Finance weekly Net Revenue target for the retail weeks in the selection (a partial week "
               "selection returns the whole week's target). Targets are set per store only, so the measure is blank "
               "under a product or promotion filter.", "Target Net Revenue"),
    Measure("Net Revenue (Target Weeks)", """
IF ( ISCROSSFILTERED ( Product ) || ISCROSSFILTERED ( Promotion ), BLANK (),
VAR _pairs =
    CALCULATETABLE (
        SUMMARIZE ( Targets, Targets[store_key], Targets[retail_week_key] ),
        TREATAS ( VALUES ( 'Date'[retail_week_key] ), Targets[retail_week_key] )
    )
RETURN
    SUMX (
        _pairs,
        VAR _s = Targets[store_key]
        VAR _w = Targets[retail_week_key]
        RETURN CALCULATE ( [Net Revenue], Store[store_key] = _s, 'Date'[retail_week_key] = _w )
    )
)""", EUR, F_TGT, "Net Revenue over the store-weeks that have a Finance target (weeks without a target are "
               "excluded from Target Achievement, as in Phase 5). Blank under a product or promotion filter.",
            "Net Revenue (Target Weeks)"),
    Measure("Target Achievement %", "DIVIDE ( [Net Revenue (Target Weeks)], [Target Net Revenue] )", PCT, F_TGT,
            "Net Revenue as a share of target over store-weeks with a target (BRD 5.4; Phase 5 definition).",
            "Target Achievement %"),
    Measure("Variance to Target", "[Net Revenue (Target Weeks)] - [Target Net Revenue]", EUR, F_TGT,
            "Net Revenue minus target, over store-weeks with a target.", None),
    # ---------------------------------------------------------------- Phase 6 evidence (imported, fixed period)
    Measure("Driver Amount", "SUM ( p6_driver_attribution[amount_eur] )", EUR, F_P6,
            "Exclusive attribution of the H2 net revenue change (Phase 6). Not affected by slicers.", None, "mixed"),
    Measure("Driver Share of Decline", "SUM ( p6_driver_attribution[share_of_change] )", PCT, F_P6,
            "Share of the H2 net revenue change (Phase 6).", None, "mixed"),
    Measure("Attribution Total", "CALCULATE ( [Driver Amount], REMOVEFILTERS ( p6_driver_attribution ) )", EUR, F_P6,
            "Sum of all attribution components; equals the H2 change exactly.", None, "FACT"),
    Measure("Driver Impact (single driver)", """
IF ( HASONEVALUE ( p6_evidence_matrix[driver_id] ), SUM ( p6_evidence_matrix[financial_impact_eur] ) )""", EUR, F_P6,
            "Impact of ONE driver (Phase 6). Blank at total level: the rows overlap (D02 repeats D01, D04 is part of "
            "D03, D06 repeats D05) and must never be added.", None, "mixed"),
    Measure("Investigation Slice (single row)", """
IF ( HASONEVALUE ( p6_investigations[priority] ), SUM ( p6_investigations[slice_of_decline_eur] ) )""", EUR, F_P6,
            "Size of the slice an investigation would explain. Blank at total level (slices overlap).", None, "mixed"),
    Measure("Evidence Level", "SELECTEDVALUE ( p6_evidence_matrix[evidence_level] )", "", F_P6,
            "BRD evidence level of the selected driver (Phase 6).", None, "label"),
    Measure("Evidence Colour", "SELECTEDVALUE ( p6_evidence_matrix[evidence_colour], \"#8F8D87\" )", "", F_P6,
            "Colour for conditional formatting; always shown together with the text label.", None, "label"),
    Measure("Driver Evidence Colour", """
VAR _lvl = SELECTEDVALUE ( p6_driver_attribution[evidence_level] )
RETURN SWITCH ( _lvl, "Root-cause evidence", "#1BAF7A", "Observed change", "#2A78D6",
                "Statistical association", "#EDA100", "Hypothesis", "#8F8D87", "#C9C7C1" )""", "", F_P6,
            "Colour of an attribution bar by evidence level (residual in light grey).", None, "label"),
    Measure("Cluster Excess (P6)",
            "CALCULATE ( [Driver Amount], p6_driver_attribution[driver_id] = \"D01\" )", EUR, F_P6,
            "Store-cluster excess decline vs matched control stores (Phase 6 ESTIMATE).", None, "ESTIMATE"),
    Measure("Lost Sales Gross (P6)",
            "CALCULATE ( SUM ( p6_et_lost_sales_totals[primary_change] ), p6_et_lost_sales_totals[scope] = \"category\" )",
            EUR, F_P6, "Increase in Electronics sales lost in full-week stock-outs (Phase 6 ESTIMATE).", None, "ESTIMATE"),
    Measure("Lost Sales Net of Deferred Demand (P6)", """
- CALCULATE ( SUM ( p6_stockout_net_of_recovery[estimate_eur] ),
              p6_stockout_net_of_recovery[driver] = "electronics_stockouts_primary" )""", EUR, F_P6,
            "Lost sales after netting off demand that returned after restock (Phase 6 ESTIMATE).", None, "ESTIMATE"),
    Measure("Lost Sales Range Low (P6)", """
- CALCULATE ( MAX ( p6_sensitivity_summary[range_high_eur] ),
              p6_sensitivity_summary[driver] = "electronics_stockouts_primary" )""", EUR, F_P6,
            "Low end of the stock-out sensitivity range (Phase 6).", None, "ESTIMATE"),
    Measure("Lost Sales Range High (P6)", """
- CALCULATE ( MIN ( p6_sensitivity_summary[range_low_eur] ),
              p6_sensitivity_summary[driver] = "electronics_stockouts_primary" )""", EUR, F_P6,
            "High end of the stock-out sensitivity range (Phase 6).", None, "ESTIMATE"),
    Measure("SKU Lost Sales Change (P6)", "SUM ( p6_et_sku_stockouts[lost_primary_change] )", EUR, F_P6,
            "Increase in estimated full-week lost sales by SKU (Phase 6 ESTIMATE).", None, "ESTIMATE"),
    Measure("High-Seller Share of Lost Sales (P6)", """
DIVIDE (
    CALCULATE ( [SKU Lost Sales Change (P6)], REMOVEFILTERS ( p6_et_sku_stockouts ), p6_et_sku_stockouts[high_seller] = TRUE () ),
    CALCULATE ( [SKU Lost Sales Change (P6)], REMOVEFILTERS ( p6_et_sku_stockouts ) )
)""", PCT, F_P6, "Share of the lost-sales increase on the top 10% SKUs by prior-year revenue (Phase 6).", None,
            "ESTIMATE"),
    Measure("Top SKU Share of Lost Sales (P6)", """
DIVIDE (
    MAXX ( ALL ( p6_et_sku_stockouts ), p6_et_sku_stockouts[lost_primary_change] ),
    CALCULATE ( [SKU Lost Sales Change (P6)], REMOVEFILTERS ( p6_et_sku_stockouts ) )
)""", PCT, F_P6, "Share of the lost-sales increase on the single largest SKU (Phase 6).", None, "ESTIMATE"),
    Measure("Top 3 SKU Share of Lost Sales (P6)", """
DIVIDE (
    SUMX (
        TOPN ( 3, ALL ( p6_et_sku_stockouts ), p6_et_sku_stockouts[lost_primary_change], DESC ),
        p6_et_sku_stockouts[lost_primary_change]
    ),
    CALCULATE ( [SKU Lost Sales Change (P6)], REMOVEFILTERS ( p6_et_sku_stockouts ) )
)""", PCT, F_P6, "Share of the lost-sales increase on the three largest SKUs (Phase 6).", None, "ESTIMATE"),
    Measure("Stock-Out Episodes (P6)", "SUM ( p6_et_episodes[episodes] )", INT, F_P6,
            "Stock-out episodes (runs of consecutive out-of-stock weeks), by supplier and year (Phase 6 FACT).", None),
    Measure("Mean Episode Weeks (P6)", "AVERAGE ( p6_et_episodes[mean_weeks_out] )", "0.0", F_P6,
            "Mean episode length in weeks; use with one supplier and one year selected (Phase 6 FACT).", None),
    Measure("Promotion Events (P6)", "SUM ( p6_hk_events_by_year[events] )", INT, F_P6,
            "Home & Kitchen promotion events analysed in Phase 6, by year (FACT).", None),
    Measure("Post-Promotion Dip (P6)", "SUM ( p6_hk_events_by_year[post_dip_revenue] )", EUR, F_P6,
            "Revenue shortfall after promotions against event baselines (Phase 6 ESTIMATE).", None, "ESTIMATE"),
    Measure("HK Method Effect", "SUM ( p6_hk_methods[effect_eur] )", EUR, F_P6,
            "Effect of the Home & Kitchen promotion change by method (Phase 6). Never summed across methods.",
            None, "ESTIMATE"),
    Measure("HK Method Effect Guarded", """
IF ( HASONEVALUE ( p6_hk_methods[method_code] ), [HK Method Effect] )""", EUR, F_P6,
            "Blank at total level, so the four methods are never combined into one number.", None, "ESTIMATE"),
    # ---------------------------------------------------------------- labels and dynamic subtitles
    Measure("Selected Period", """
VAR _p = SELECTEDVALUE ( 'Date'[period_label] )
RETURN IF ( ISBLANK ( _p ), "Multiple periods selected", _p )""", "", F_TXT,
            "Period in the current filter context.", None, "label"),
    Measure("Headline Subtitle", """
"Net revenue " & FORMAT ( [Net Revenue PY] / 1000000, "€#,0.000" ) & "M to "
    & FORMAT ( [Net Revenue] / 1000000, "€#,0.000" ) & "M ("
    & FORMAT ( [Net Revenue YoY] / 1000, "+€#,0;-€#,0" ) & "k, "
    & FORMAT ( [Net Revenue YoY %], "+0.00%;-0.00%" ) & ")"
""", "", F_TXT,
            "Dynamic headline for the selected period, e.g. 'Net revenue €10.189M to €9.457M (-€731k, -7.18%)'.",
            None, "label"),
    Measure("Phase 6 Scope Note",
            "\"Validated Phase 6 result for H2 2025 vs H2 2024. Not affected by slicers.\"", "", F_TXT,
            "Caption for every visual built on imported Phase 6 tables.", None, "label"),
    Measure("Cluster Cause Callout",
            "\"Cause not established from available internal data.\"", "", F_TXT,
            "Required callout on the store page (Phase 6: cause UNRESOLVED).", None, "label"),
    Measure("Voltix Wording",
            "\"Stock-out concentration is associated with Voltix SKUs. Available data cannot determine whether the cause "
            "was supplier performance or Brightwater ordering/replenishment.\"", "", F_TXT,
            "Required wording on the inventory page (Phase 6 D04: Statistical association).", None, "label"),
    Measure("Promotion Wording",
            "\"Promotion activity is associated with the Home & Kitchen decline, but causality is not established.\"",
            "", F_TXT, "Required wording on the promotions page (Phase 6 D07).", None, "label"),
    # ---------------------------------------------------------------- validation (fixed context)
    Measure("QA Net Revenue H2 2025", """
CALCULATE ( [Net Revenue], REMOVEFILTERS (), 'Date'[retail_year] = 2025, 'Date'[retail_half] = "H2" )""",
            EUR2, F_QA, "Fixed-context check value: must equal €9,457,457.05 (Phase 4, 5, 6).", None),
    Measure("QA Net Revenue H2 2024", """
CALCULATE ( [Net Revenue], REMOVEFILTERS (), 'Date'[retail_year] = 2024, 'Date'[retail_half] = "H2" )""",
            EUR2, F_QA, "Fixed-context check value: must equal €10,188,727.55.", None),
    Measure("QA Attribution Check", """
VAR _change = [QA Net Revenue H2 2025] - [QA Net Revenue H2 2024]
VAR _attr = [Attribution Total]
RETURN IF ( ABS ( _change - _attr ) < 0.01, "PASS: attribution = H2 change",
            "FAIL: attribution differs from H2 change by " & FORMAT ( _attr - _change, "€#,0.00" ) )""", "", F_QA,
            "Compares the imported Phase 6 attribution with the model's own H2 change.", None),
]

BY_NAME = {m.name: m for m in MEASURES}

# Calculated columns (the only ones in the model): a low-cardinality dimension attribute from Phase 6.
CALC_COLUMNS = [
    ("Store", "store_group", """
VAR _g = LOOKUPVALUE ( p6_store_groups[store_group], p6_store_groups[store_id], Store[store_id] )
RETURN IF ( ISBLANK ( _g ), "Unknown", _g )""",
     "Phase 6 store group (Investigated cluster, Matched control, Other store; Unknown for key -1). A calculated "
     "column rather than a Power Query merge, which would combine two sources in one query (Formula.Firewall)."),
]


def references(expr: str) -> tuple[set[str], set[tuple[str, str]]]:
    """Measures ([Name]) and columns (Table[col] or 'Table'[col]) referenced by a DAX expression."""
    text = re.sub(r'"[^"]*"', '""', expr)
    cols = {(t.strip("'"), c) for t, c in re.findall(r"('[^']+'|\b[A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]", text)}
    col_spans = {m.span(2) for m in re.finditer(r"('[^']+'|\b[A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]", text)}
    meas = set()
    for m in re.finditer(r"\[([^\]]+)\]", text):
        if (m.start() + 1, m.end() - 1) not in col_spans:
            meas.add(m.group(1))
    return meas, cols


def static_checks(schema: dict[str, list[str]]) -> list[dict]:
    """Checks that do not need Power BI: every referenced measure exists (no self-reference cycles), every
    referenced column exists in the model schema, parentheses balance, names are unique, formats set."""
    rows = []
    names = [m.name for m in MEASURES]

    def add(measure, check, ok, detail=""):
        rows.append({"measure": measure, "check": check, "status": "PASS" if ok else "FAIL", "detail": detail})
    add("*", "measure names are unique", len(names) == len(set(names)))
    graph = {}
    for m in MEASURES:
        meas, cols = references(m.expr)
        graph[m.name] = meas
        missing_m = sorted(x for x in meas if x not in BY_NAME)
        add(m.name, "referenced measures exist", not missing_m, ", ".join(missing_m))
        missing_c = sorted(f"{t}[{c}]" for t, c in cols if t not in schema or c not in schema[t])
        add(m.name, "referenced columns exist in the model", not missing_c, ", ".join(missing_c))
        stripped = re.sub(r'"[^"]*"', '""', m.expr)
        add(m.name, "parentheses balance", stripped.count("(") == stripped.count(")"))
        add(m.name, "has a description", bool(m.description.strip()))
    # cycle detection (DFS)
    state = {}

    def visit(n, path):
        if state.get(n) == 1:
            return path + [n]
        if state.get(n) == 2:
            return None
        state[n] = 1
        for d in graph.get(n, ()):
            cyc = visit(d, path + [n])
            if cyc:
                return cyc
        state[n] = 2
        return None
    cyc = None
    for n in graph:
        cyc = cyc or visit(n, [])
    add("*", "no circular measure references", cyc is None, " -> ".join(cyc or []))
    return rows


def _indent(expr: str, n: int) -> str:
    lines = expr.strip("\n").splitlines()
    return "\n".join(("\t" * n) + ln if ln.strip() else "" for ln in lines)


def to_dax_listing() -> str:
    out = ["// Brightwater Retail: Power BI measure layer (Phase 7).",
           "// Generated from src/powerbi/dax.py. Home table: Measures. Paste each measure or use measures_tmdl.tmdl.",
           "// Money columns should be typed Fixed Decimal Number in Power Query so totals reconcile to the cent.", ""]
    out += ["// ============================== Calculated column (create on the table named)", ""]
    for t, c, e, d in CALC_COLUMNS:
        out += [f"// {d}", f"// Table: {t}", f"{c} =" + "\n" + e.strip("\n"), ""]
    folder = None
    for m in MEASURES:
        if m.folder != folder:
            out += ["", f"// ============================== {m.folder}", ""]
            folder = m.folder
        out.append(f"// {m.description}")
        if m.fmt:
            out.append(f"// Format: {m.fmt}")
        body = m.expr.strip("\n")
        out.append(f"{m.name} =" + ("\n" + body if "\n" in body else " " + body))
        out.append("")
    return "\n".join(out) + "\n"


def to_tmdl() -> str:
    """TMDL script for Power BI Desktop's TMDL view: creates (or replaces) a calculated 'Measures' table that holds
    every measure in display folders. Not executed in this environment (no Power BI Desktop)."""
    out = ["createOrReplace", "", "\ttable Measures", ""]
    for m in MEASURES:
        body = m.expr.strip("\n")
        out.append(f"\t\t/// {m.description}")
        if "\n" in body:
            out.append(f"\t\tmeasure '{m.name}' =")
            out.append(_indent(body, 4))
        else:
            out.append(f"\t\tmeasure '{m.name}' = {body}")
        if m.fmt:
            out.append(f"\t\t\tformatString: {m.fmt}")
        out.append(f"\t\t\tdisplayFolder: {m.folder}")
        out.append("")
    out += ["\t\tcolumn Measures", "\t\t\tdataType: string", "\t\t\tisHidden", "\t\t\tisNameInferred",
            "\t\t\tsourceColumn: [Measures]", "",
            "\t\tpartition Measures = calculated", "\t\t\tmode: import",
            "\t\t\tsource = ROW ( \"Measures\", \"\" )", ""]
    return "\n".join(out) + "\n"


def dictionary():
    import pandas as pd
    rows = []
    for m in MEASURES:
        meas, cols = references(m.expr)
        rows.append({"measure": m.name, "display_folder": m.folder, "format": m.fmt, "evidence_tag": m.kind,
                     "description": m.description, "dax": " ".join(m.expr.split()),
                     "depends_on_measures": ", ".join(sorted(meas)),
                     "depends_on_columns": ", ".join(sorted(f"{t}[{c}]" for t, c in cols)),
                     "python_reference": m.reference or "",
                     "validated_here": "logic reconciled via Python reference" if m.reference
                     else ("static checks only" if m.folder not in (F_P6, F_TXT) else "source table traced; static checks")})
    return pd.DataFrame(rows)
