"""Rule catalogue: every data-quality rule, its severity, treatment and business rationale.

Severity
  critical  breaks keys or materially misstates a headline KPI if untreated
  high      invalid value that affects KPIs, joins or a business analysis
  medium    recoverable problem with limited KPI effect, or a consistency warning
  low       cosmetic / presentation problem
  info      expected business behaviour, documented so nobody "fixes" it later

Treatment
  CORRECT        value rebuilt deterministically from an authoritative source (logged)
  STANDARDISE    format or label normalised to the canonical value (logged)
  DEDUPLICATE    duplicate copy removed from curated data, kept in quarantine
  IMPUTE         value estimated from a reference; row flagged as imputed
  UNKNOWN_MEMBER foreign key mapped to an explicit UNKNOWN member so totals stay complete
  QUARANTINE     row cannot be trusted as recorded; moved to quarantine, excluded from KPIs
  FLAG           row kept and used, flagged for business review
  INCLUDE        valid data delivered through an exceptional route, loaded with a flag
  GAP            completeness gap reported; nothing is invented
  NONE           check only (or expected behaviour); no change
"""
from __future__ import annotations

import pandas as pd

_R = []


def _add(rule_id, table, dimension, check, severity, treatment, rationale):
    _R.append({"rule_id": rule_id, "table": table, "dimension": dimension, "check": check,
               "severity": severity, "treatment": treatment, "rationale": rationale})


# ---- schema (all tables)
_add("SCH-01", "all", "validity", "Expected columns are present", "critical", "NONE",
     "A missing column breaks every downstream load; the pipeline stops rather than guessing.")
_add("SCH-02", "all", "validity", "Values parse to the contract type (blanks counted separately)", "high", "NONE",
     "Type failures are counted per column in the profile; row-level handling is done by the specific rules below.")

# ---- dim_store
_add("DS-01", "dim_store", "uniqueness", "store_id unique and well formed", "critical", "NONE",
     "store_id is the join key for every fact table.")
_add("DS-02", "dim_store", "validity", "Text fields without leading or trailing spaces", "low", "STANDARDISE",
     "Padded names create duplicate labels in reports and failed joins on name.")
_add("DS-03", "dim_store", "validity", "region, store_format in the canonical domain", "low", "STANDARDISE",
     "A case variant of a region splits that region into two rows in every regional report.")
_add("DS-04", "dim_store", "validity", "Numeric attributes plausible (area, FTE, hours, coordinates in Ireland)", "medium",
     "NONE", "Store attributes feed per-m2 and per-FTE ratios.")

# ---- dim_product
_add("DP-01", "dim_product", "uniqueness", "product_id unique", "critical", "DEDUPLICATE",
     "Duplicate product rows multiply sales on join. Keep the record whose list price agrees with the price "
     "actually charged at the till in the latest year; the other copy is quarantined.")
_add("DP-02", "dim_product", "validity", "category is one of the 7 canonical categories", "medium", "STANDARDISE",
     "Label variants split categories in reporting; mapped to the canonical label (mapping logged).")
_add("DP-03", "dim_product", "validity", "Text fields without leading or trailing spaces", "low", "STANDARDISE",
     "Trailing spaces break name matching and look like different products.")
_add("DP-04", "dim_product", "completeness", "supplier_id and supplier_name present", "medium", "UNKNOWN_MEMBER",
     "Supplier cannot be derived reliably (brands use several suppliers), so it is set to UNKNOWN and flagged.")
_add("DP-05", "dim_product", "accuracy", "list_price and unit_cost positive", "high", "CORRECT",
     "A negative cost is a sign error when its absolute value matches the cost charged at the till; corrected to "
     "the absolute value, otherwise flagged.")
_add("DP-06", "dim_product", "consistency", "unit_cost below list_price", "medium", "FLAG",
     "Negative standard margin on the master record needs buyer review.")
_add("DP-07", "dim_product", "consistency", "Launch/discontinuation dates and status consistent", "medium", "FLAG",
     "Status drives range reporting; dates drive new-line and exit analysis.")
_add("DP-08", "dim_product", "uniqueness", "product_name unique across product IDs", "low", "FLAG",
     "Two IDs with one name may be genuine variants or a re-coded SKU; reported for review, not merged.")
_add("DP-09", "dim_product", "consistency", "Each subcategory belongs to one category", "medium", "NONE",
     "The product hierarchy must be a tree for drill-down.")

# ---- dim_date
_add("DD-01", "dim_date", "completeness", "One row per calendar day for the whole period, keys unique", "critical",
     "NONE", "The calendar drives every time-based join.")
_add("DD-02", "dim_date", "consistency", "Derived attributes agree with the date (weekday, weekend, retail week)",
     "high", "NONE", "Week-aligned YoY depends on the retail week mapping.")
_add("DD-03", "dim_date", "completeness", "Retail weeks have 7 days (partial week at extract end)", "info", "NONE",
     "29-31 Dec 2025 belong to retail 2026 week 1, outside the 104 comparable weeks.")

# ---- fact_sales
_add("FS-01", "fact_sales", "uniqueness", "transaction_id + line_number unique", "critical", "DEDUPLICATE",
     "Re-sent receipt lines double-count revenue. Keep the earliest extracted copy; later copies are quarantined.")
_add("FS-02", "fact_sales", "validity", "transaction_date in ISO format (yyyy-mm-dd)", "medium", "STANDARDISE",
     "Legacy dd/mm/yyyy dates are converted; each is confirmed against the date inside the transaction ID.")
_add("FS-03", "fact_sales", "validity", "transaction_date present, valid, in period and equal to the ID date",
     "high", "CORRECT", "The transaction ID is generated by the till and embeds the business date, so it is the "
     "authoritative source; every valid date in the file agrees with it.")
_add("FS-04", "fact_sales", "integrity", "store_id present, known and equal to the ID store", "high", "CORRECT",
     "The transaction ID embeds the store; used to restore missing or unknown store IDs.")
_add("FS-05", "fact_sales", "completeness", "product_id present", "high", "CORRECT",
     "Restored from a return that references the same sale line (a second system record); otherwise mapped to "
     "UNKNOWN so revenue stays in totals but not in product analysis.")
_add("FS-06", "fact_sales", "integrity", "product_id exists in dim_product", "high", "UNKNOWN_MEMBER",
     "Unknown product codes keep their revenue in totals under an UNKNOWN product member.")
_add("FS-07", "fact_sales", "consistency", "POS category label equals the product master category", "low",
     "STANDARDISE", "The POS category text is denormalised; the product master is the source of truth.")
_add("FS-08", "fact_sales", "validity", "quantity positive (whole line sign-inverted)", "high", "CORRECT",
     "Quantity, discount, revenue, cost and margin are all negated consistently, and returns are recorded in "
     "fact_returns, so these are sign errors. Evidence: the corrected units reconcile to the stock system.")
_add("FS-09", "fact_sales", "accuracy", "quantity at or below the plausible maximum for a store line", "high",
     "QUARANTINE", "Bulk quantities are not recorded as sold by the stock system; the true quantity cannot be "
     "recovered from the record, so the line is excluded from KPIs and kept for investigation.")
_add("FS-10", "fact_sales", "completeness", "unit_price present", "medium", "CORRECT",
     "Derived as (revenue + discount) / quantity and confirmed against the SKU reference price.")
_add("FS-11", "fact_sales", "accuracy", "unit_price above zero", "high", "IMPUTE",
     "A zero price with cost recorded is a pricing failure, not a giveaway. Price imputed from the SKU-year "
     "reference price, discount from the promotion depth (0 if not promoted); row flagged as imputed.")
_add("FS-12", "fact_sales", "validity", "unit_price not negative (money fields sign-inverted)", "high", "CORRECT",
     "Price, discount and revenue are negated consistently while quantity and cost are positive: a sign error.")
_add("FS-13", "fact_sales", "accuracy", "unit_price not about 100x the SKU reference price", "critical",
     "CORRECT", "A misplaced decimal point inflates revenue a hundredfold; price divided by 100 and revenue and "
     "margin recomputed.")
_add("FS-14", "fact_sales", "accuracy", "unit_price within 1% of the SKU-year reference price", "medium", "FLAG",
     "Each SKU sells at one list price per year (discounts are recorded separately); other deviations need review.")
_add("FS-15", "fact_sales", "completeness", "discount present", "medium", "CORRECT",
     "Derived as quantity x unit_price - revenue (revenue and price are present and valid).")
_add("FS-16", "fact_sales", "validity", "discount between 0 and the maximum discount share of gross", "medium",
     "FLAG", "Negative or excessive discounts after sign correction need review.")
_add("FS-17", "fact_sales", "consistency", "revenue = quantity x unit_price - discount", "high", "CORRECT",
     "Where cost + margin also equals quantity x unit_price - discount, the components are confirmed and only "
     "revenue is wrong, so revenue is recomputed.")
_add("FS-18", "fact_sales", "consistency", "margin = revenue - cost and cost = quantity x unit_cost", "medium",
     "CORRECT", "Margin is recomputed after any revenue correction.")
_add("FS-19", "fact_sales", "integrity", "promotion_id exists in fact_promotions", "medium", "CORRECT",
     "Restored when exactly one promotion is active for that store, product and date and its depth matches the "
     "line discount; cleared when the line has no discount (it was not promoted); otherwise UNKNOWN.")
_add("FS-20", "fact_sales", "integrity", "Promoted line's store and product are in that promotion", "medium", "FLAG",
     "Either the promotion file is incomplete or the till applied the wrong promotion. Where a promotion row was "
     "quarantined for an invalid product code (FP-04) and the POS lines of that promotion and store point to exactly "
     "one missing product, the promotion row is restored with that product (two records agree).")
_add("FS-21", "fact_sales", "consistency", "Promoted line carries a discount", "low", "FLAG",
     "A promotion with no discount has no promotional effect.")
_add("FS-22", "fact_sales", "consistency", "Promoted line falls within the promotion dates", "low", "FLAG",
     "Promotion applied outside its window.")
_add("FS-23", "fact_sales", "consistency", "Discount without a promotion_id (non-promotional markdown)", "info",
     "NONE", "Damaged-box and price-match markdowns are legitimate and are not promotions.")
_add("FS-24", "fact_sales", "consistency", "Line unit_cost differs from the product master cost", "info", "NONE",
     "The master holds the current standard cost; the till records the cost of the day (history).")
_add("FS-25", "fact_sales", "accuracy", "Negative line margin", "info", "NONE",
     "Clearance and deep promotions can sell below cost.")
_add("FS-26", "fact_sales", "consistency", "One store, date and time per transaction; line numbers 1..n", "high",
     "FLAG", "Receipt-level integrity underpins transactions, AOV and UPT.")
_add("FS-27", "fact_sales", "consistency", "No sales before launch or more than a week after discontinuation",
     "medium", "FLAG", "Sales outside the product life cycle point to a master-data date error.")
_add("FS-28", "fact_sales", "accuracy", "Line price check impossible (UNKNOWN product, no reference price)", "info",
     "NONE", "Recorded for transparency: these lines cannot be price-checked.")

# ---- timeliness and completeness
_add("TC-01", "fact_sales", "timeliness", "Sales batches arrive within the expected lag", "high", "INCLUDE",
     "Late files are valid sales delivered late. They are loaded with a flag so 'as first reported' and "
     "'complete' figures can both be shown.")
_add("TC-02", "fact_sales", "completeness", "Every store has POS data for every trading day", "critical", "GAP",
     "A store-day with no sales is a missing batch, not a closure, when stock and returns show trading. "
     "Gaps are reported and estimated, never filled with invented rows.")
_add("TC-03", "fact_sales", "completeness", "Store-day revenue not far below the store's usual level", "medium",
     "FLAG", "A partial batch looks like a very low trading day.")
_add("TC-04", "fact_sales", "timeliness", "One extract batch per business day, loaded next morning", "medium",
     "NONE", "Batch structure is the first sign of a missing or re-sent file.")
_add("TC-05", "fact_inventory", "completeness", "No missing week inside a store-SKU stock series", "high", "GAP",
     "Missing snapshots break availability and cover calculations; not imputed.")
_add("TC-06", "fact_targets", "completeness", "A target for every store and retail week", "medium", "GAP",
     "Missing targets make target achievement undefined for that store-week; not imputed.")
_add("TC-07", "fact_inventory", "consistency", "POS units equal stock-system sold units per store-SKU-week",
     "high", "NONE", "Two independent systems must agree; the match rate before and after cleaning measures "
     "whether cleaning moved the data closer to the truth.")

# ---- fact_inventory
_add("FI-01", "fact_inventory", "uniqueness", "No exact duplicate rows", "high", "DEDUPLICATE",
     "Duplicate snapshots double stock and sold units.")
_add("FI-02", "fact_inventory", "uniqueness", "store + product + snapshot_date unique", "critical", "QUARANTINE",
     "Conflicting snapshots for one key cannot both be true.")
_add("FI-03", "fact_inventory", "validity", "Quantities stored as whole numbers", "low", "STANDARDISE",
     "Unit quantities exported as decimals (0.0) are cast to integers.")
_add("FI-04", "fact_inventory", "completeness", "received_qty present", "medium", "CORRECT",
     "Derived from the stock identity: closing - opening + sold - adjustment (must be >= 0).")
_add("FI-05", "fact_inventory", "validity", "closing_stock not negative", "high", "CORRECT",
     "Where the negative value is exactly minus the identity result, it is a sign error and is corrected.")
_add("FI-06", "fact_inventory", "consistency", "closing = opening + received - sold + adjustment", "medium", "CORRECT",
     "Triangulated with the neighbouring weeks: if previous closing + this week's movements = closing, and closing = "
     "next week's opening, the opening is wrong (set to previous closing). If the identity result = next week's "
     "opening, the closing is wrong (set to the identity result). Otherwise flagged; the true field is unknown.")
_add("FI-07", "fact_inventory", "consistency", "opening_stock equals the previous week's closing_stock", "medium",
     "FLAG", "Continuity breaks point to an unrecorded movement or a corrupted snapshot.")
_add("FI-08", "fact_inventory", "validity", "Stock fields in range (no negatives other than adjustments)", "high",
     "FLAG", "Negative stock is physically impossible.")
_add("FI-09", "fact_inventory", "consistency", "Snapshot is a Sunday and matches the retail week", "medium", "NONE",
     "Weekly snapshots must line up with the retail calendar.")
_add("FI-10", "fact_inventory", "integrity", "store_id and product_id exist in the dimensions", "high", "FLAG",
     "Orphan stock rows cannot be reported by store or product.")

# ---- fact_returns
_add("FR-01", "fact_returns", "uniqueness", "No exact duplicate rows", "high", "DEDUPLICATE",
     "Duplicate returns overstate refunds and understate net revenue.")
_add("FR-02", "fact_returns", "uniqueness", "return_id unique", "critical", "QUARANTINE",
     "Two different returns with one ID cannot both be kept.")
_add("FR-03", "fact_returns", "completeness", "Return linked to an original sale", "info", "NONE",
     "No-receipt returns are allowed (BRD assumption 2); they stay in Returns Value.")
_add("FR-04", "fact_returns", "integrity", "Linked sale line exists", "high", "FLAG",
     "The refund was paid, so it stays in Returns Value, but it cannot be tied to a sale.")
_add("FR-05", "fact_returns", "consistency", "Return date after the sale date", "high", "QUARANTINE",
     "A return before its sale is impossible as recorded; excluded from KPIs, value reported for review.")
_add("FR-06", "fact_returns", "consistency", "Returned quantity not above the quantity sold", "high", "QUARANTINE",
     "More units returned than sold is impossible as recorded; excluded from KPIs, value reported for review.")
_add("FR-07", "fact_returns", "consistency", "Refund not above the sale line value for the units returned",
     "medium", "FLAG", "Over-refunds need finance review; kept because the money was paid.")
_add("FR-08", "fact_returns", "consistency", "Returned product equals the product on the sale line", "medium", "FLAG",
     "A mismatch means the link or the product is wrong.")
_add("FR-09", "fact_returns", "consistency", "Returned at a different store from the sale", "info", "NONE",
     "Allowed by policy (BRD assumption 2: returns are recorded where they are returned).")
_add("FR-10", "fact_returns", "consistency", "Return within the returns policy window", "medium", "FLAG",
     "30 days, extended to 31 January for Christmas purchases.")
_add("FR-11", "fact_returns", "validity", "Quantity and refund positive, reason and restockable flag valid, "
     "store and product known", "high", "FLAG", "Domain checks on every return.")
_add("FR-12", "fact_returns", "integrity", "Linked sale only exists in the late sales file", "info", "NONE",
     "Resolved by loading the late file (TC-01).")

# ---- fact_promotions
_add("FP-01", "fact_promotions", "uniqueness", "No exact duplicate rows", "medium", "DEDUPLICATE",
     "Duplicate promotion rows would double promotion counts.")
_add("FP-02", "fact_promotions", "validity", "end_date on or after start_date", "high", "CORRECT",
     "Dates restored from the same promotion's other rows (one promotion has one window); otherwise quarantined.")
_add("FP-03", "fact_promotions", "consistency", "One name, type and window per promotion_id", "medium",
     "FLAG", "Promotion header attributes should be identical on every row. Depth may legitimately vary "
     "(tiered clearance), so it is reported, not flagged.")
_add("FP-04", "fact_promotions", "integrity", "product_id and store_id exist in the dimensions", "medium",
     "QUARANTINE", "Rows for unknown products cannot be analysed; restored only if the POS lines identify the "
     "product (see FS-20).")
_add("FP-05", "fact_promotions", "validity", "discount_pct between 0 and the maximum discount share", "high", "FLAG",
     "Promotion depth drives uplift and discount cost.")
_add("FP-06", "fact_promotions", "validity", "Promotion window inside the extract period", "info", "NONE",
     "Promotions that straddle the period end are valid.")

# ---- fact_targets
_add("FT-01", "fact_targets", "uniqueness", "One target per store and retail week", "high", "DEDUPLICATE",
     "Keep the latest target version (then latest set date); superseded versions are quarantined.")
_add("FT-02", "fact_targets", "accuracy", "Target not an extreme outlier for the store", "high", "CORRECT",
     "A target about 100x the store's median is a misplaced decimal point and is divided by 100; other outliers "
     "are quarantined.")
_add("FT-03", "fact_targets", "consistency", "Week dates match the retail calendar", "medium", "NONE",
     "Targets must join to the calendar on retail year and week.")
_add("FT-04", "fact_targets", "validity", "Target positive and store known", "high", "FLAG",
     "A zero, negative or orphan target makes target achievement meaningless for that store-week.")

CATALOGUE = {r["rule_id"]: r for r in _R}


def catalogue_frame() -> pd.DataFrame:
    """The rule catalogue as a DataFrame, one row per rule."""
    return pd.DataFrame(_R)
