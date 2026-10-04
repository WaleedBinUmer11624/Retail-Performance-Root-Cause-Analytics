# Data Quality Report: Brightwater Retail raw extracts

| Item | Detail |
|---|---|
| Phase | 3: data quality, cleaning and validation |
| Run | 2026-09-28T01:12:59 (117.4 s) |
| Inputs | 9 raw source extracts in `data/raw/` (read-only, SHA-256 verified before and after) |
| Outputs | `data/processed/curated/`, `data/processed/quarantine/`, `reports/phase3/` |
| Code | `src/data_quality/` (rules in `catalogue.py`, settings in `config/dq_config.yaml`) |

## 1. Summary

- **85 rules** were run across 9 extracts: 30 passed, **46 found problems** and 9 documented expected behaviour. DQ check pass rate on the raw extracts (BRD 5.5): 39.47%. After cleaning, 0 of 53 curated validation checks fail.
- Problems found: 4 critical, 23 high, 13 medium and 6 low rules failed. Substantive record-level findings (critical to medium, excluding the summary checks SCH-02 and TC-07): **15,997**; low-severity format and label fixes: 959,066 (almost all one inventory column exported as 0.0 instead of 0, and category label variants). Revenue on records that failed a check (BRD 5.5): EUR 731,602.
- Nothing was silently deleted. 38,138 row-level issues are logged with the raw and new value; 2,380 rows went to quarantine with a rule and a reason; every raw row is accounted for as curated or quarantined.
- **Net Revenue (all periods)** moves from EUR 37,347,682 at face value to EUR 36,923,003 trusted (-1.14%). The largest single error was a misplaced decimal point on 134 prices, worth EUR 365,681 of false revenue.
- **H2 week-aligned YoY** is -7.80% at face value, -7.83% after cleaning the main extract and -7.18% once the late-arriving sales file is loaded. The +0.65pp between the last two is a data-completeness effect, not trading. Phase 3 does not interpret the trading change itself.
- Stock and POS systems now agree on 99.47% of store-SKU-weeks (was 98.46%); 3 of the remaining 2,610 mismatches have no logged cause.
- Curated validation: 51 PASS, 2 WARN (known, documented conditions), 0 FAIL.

## 2. Approach

1. **Profile before touching anything.** Every column of every extract is read as text and profiled: blanks, type failures, distinct values, ranges, untrimmed text, duplicate keys (`profile_columns.csv`, `profile_tables.csv`).
2. **Detect with explicit rules.** Each rule has an ID, a severity, a treatment and a business rationale (`dq_rule_catalogue.csv`). Rules come from the BRD, the data contract in `docs/02` section 5, and profiling.
3. **Treat in a fixed order, and only with evidence.** A value is corrected only when an authoritative source exists in the data: the date and store inside the till's transaction ID, cost + margin confirming price and discount, the neighbouring stock weeks, a return that references the same sale line, the SKU's single list price for the year. Where no such source exists the row is flagged, mapped to an UNKNOWN member or quarantined; values are never invented.
4. **Keep everything auditable.** Raw files are never written. Each change is in the issue log (row level) and the audit trail (step level, with revenue before and after). Curated rows carry `dq_status` and `dq_rules`.
5. **Validate the result** against the contract, reconcile KPIs before and after, and reconcile POS units against the independent stock system.
6. **Stay independent of the answer key.** The loader only accepts the 9 business extracts; files starting with an underscore are refused, and tests check both the code text and every file opened at run time.

Severity: **critical** breaks keys or materially misstates a headline KPI; **high** is an invalid value affecting KPIs or joins; **medium** is recoverable with limited KPI effect; **low** is cosmetic. Treatments: CORRECT, STANDARDISE, DEDUPLICATE, IMPUTE, UNKNOWN_MEMBER, QUARANTINE, FLAG, INCLUDE (late data), GAP (reported, not filled).

## 3. Issues discovered

Rules that found at least one problem, most severe first. EUR = revenue on the affected lines (for sales) or refund value (for returns).

| Rule | Severity | Table | Check | Rows | EUR | Treatment | Treatment applied |
|---|---|---|---|---|---|---|---|
| DP-01 | critical | dim_product | product_id unique | 10 |  | DEDUPLICATE | 10 product IDs appear twice |
| FS-01 | critical | fact_sales | transaction_id + line_number unique | 1,965 | EUR 54,496 | DEDUPLICATE | 1,251 receipts re-sent |
| FS-13 | critical | fact_sales | unit_price not about 100x the SKU reference price | 134 | EUR 365,681 | CORRECT | price/reference ratio 100.0 to 100.0 |
| TC-02 | critical | fact_sales | Every store has POS data for every trading day | 15 | EUR 7,766 | GAP | 15 store-days missing from the main extract; 13 delivered by the late file; 2 still missing (S13 2024-10-15, S13 2024-10-16), estimated EUR 7,766 |
| DP-05 | high | dim_product | list_price and unit_cost positive | 1 |  | CORRECT | A negative cost is a sign error when its absolute value matches the cost charged at the till; corrected to the absolute value, otherwise flagged. |
| FI-01 | high | fact_inventory | No exact duplicate rows | 188 |  | DEDUPLICATE | Duplicate snapshots double stock and sold units. |
| FI-05 | high | fact_inventory | closing_stock not negative | 188 |  | CORRECT | 188 are exactly minus the identity value |
| FP-02 | high | fact_promotions | end_date on or after start_date | 2 |  | CORRECT | Dates restored from the same promotion's other rows (one promotion has one window); otherwise quarantined. |
| FR-01 | high | fact_returns | No exact duplicate rows | 69 | EUR 3,414 | DEDUPLICATE | Duplicate returns overstate refunds and understate net revenue. |
| FR-04 | high | fact_returns | Linked sale line exists | 144 | EUR 5,027 | FLAG | 5 point to a store-day with no POS data at all (see TC-02); 139 point to a line number that does not exist |
| FR-05 | high | fact_returns | Return date after the sale date | 35 | EUR 1,631 | QUARANTINE | A return before its sale is impossible as recorded; excluded from KPIs, value reported for review. |
| FR-06 | high | fact_returns | Returned quantity not above the quantity sold | 67 | EUR 1,980 | QUARANTINE | More units returned than sold is impossible as recorded; excluded from KPIs, value reported for review. |
| FS-03 | high | fact_sales | transaction_date present, valid, in period and equal to the ID date | 201 | EUR 6,023 | CORRECT | 100.0000% of valid in-period dates equal the ID date; malformed IDs: 0 |
| FS-04 | high | fact_sales | store_id present, known and equal to the ID store | 803 | EUR 21,850 | CORRECT | blank 669, unknown code 134, different known store 0 |
| FS-05 | high | fact_sales | product_id present | 1,070 | EUR 31,279 | CORRECT | 37 restored from the linked return, 1033 set to UNKNOWN |
| FS-06 | high | fact_sales | product_id exists in dim_product | 267 | EUR 8,875 | UNKNOWN_MEMBER | 49 unknown product codes; 7 restored from the linked return, 260 set to UNKNOWN |
| FS-08 | high | fact_sales | quantity positive (whole line sign-inverted) | 535 | EUR 15,809 | CORRECT | Quantity, discount, revenue, cost and margin are all negated consistently, and returns are recorded in fact_returns, so these are sign errors. |
| FS-09 | high | fact_sales | quantity at or below the plausible maximum for a store line | 40 | EUR 121,112 | QUARANTINE | quantities: 96, 120, 144, 250 |
| FS-11 | high | fact_sales | unit_price above zero | 134 | EUR 3,628 | IMPUTE | 134 imputed; 28 with promotion depth; 0 without a reference price quarantined |
| FS-12 | high | fact_sales | unit_price not negative (money fields sign-inverted) | 67 | EUR 2,510 | CORRECT | Price, discount and revenue are negated consistently while quantity and cost are positive: a sign error. |
| FS-17 | high | fact_sales | revenue = quantity x unit_price - discount | 535 | EUR 6,682 | CORRECT | 535 confirmed by cost + margin and corrected; 0 unconfirmed and quarantined |
| FT-01 | high | fact_targets | One target per store and retail week | 2 |  | DEDUPLICATE | 2 store-weeks with more than one target |
| FT-02 | high | fact_targets | Target not an extreme outlier for the store | 1 |  | CORRECT | S09|2025|43: 105x median |
| SCH-02 | high | all | Values parse to the contract type (blanks counted separately) | 3,047 |  | NONE | fact_sales.transaction_date: 3047 |
| TC-01 | high | fact_sales | Sales batches arrive within the expected lag | 2,270 | EUR 66,143 | INCLUDE | 2,270 lines in the late file, extract lag 12 to 25 days; main extract lag 1 to 1 days; late lines sharing a key with the main extract: 0 |
| TC-05 | high | fact_inventory | No missing week inside a store-SKU stock series | 462 |  | GAP | 462 series with an internal gap |
| TC-07 | high | fact_inventory | POS units equal stock-system sold units per store-SKU-week | 2,610 |  | NONE | match rate 98.4605% before cleaning, 99.4695% after (7,589 -> 2,610 store-SKU-weeks); remaining: sales line with UNKNOWN product in that store-week (FS-05/FS-06) 2157; mi... |
| DP-02 | medium | dim_product | category is one of the 7 canonical categories | 12 |  | STANDARDISE | 'Home and Kitchen' -> 'Home & Kitchen'; 'HOME & KITCHEN' -> 'Home & Kitchen'; 'Home&Kitchen' -> 'Home & Kitchen'; 'Electronic & Tech' -> 'Electronics & Tech'; 'Electronic... |
| DP-04 | medium | dim_product | supplier_id and supplier_name present | 5 |  | UNKNOWN_MEMBER | Supplier cannot be derived reliably (brands use several suppliers), so it is set to UNKNOWN and flagged. |
| FI-04 | medium | fact_inventory | received_qty present | 282 |  | CORRECT | 282 derived, 147 of them non-zero |
| FI-06 | medium | fact_inventory | closing = opening + received - sold + adjustment | 940 |  | CORRECT | 926 opening_stock corrected to the previous closing; 0 closing_stock corrected to the identity result; 14 unresolved and flagged |
| FI-07 | medium | fact_inventory | opening_stock equals the previous week's closing_stock | 1 |  | FLAG | tested after FI-06 corrections |
| FP-01 | medium | fact_promotions | No exact duplicate rows | 4 |  | DEDUPLICATE | Duplicate promotion rows would double promotion counts. |
| FP-04 | medium | fact_promotions | product_id and store_id exist in the dimensions | 3 |  | QUARANTINE | 3 of 3 restored from POS lines |
| FS-02 | medium | fact_sales | transaction_date in ISO format (yyyy-mm-dd) | 2,966 |  | STANDARDISE | every legacy date equals the ID date |
| FS-10 | medium | fact_sales | unit_price present | 401 |  | CORRECT | Derived as (revenue + discount) / quantity and confirmed against the SKU reference price. |
| FS-15 | medium | fact_sales | discount present | 1,337 |  | CORRECT | 271 of the restored discounts are non-zero |
| FS-19 | medium | fact_sales | promotion_id exists in fact_promotions | 267 | EUR 7,697 | CORRECT | 49 unknown codes; 58 restored from the one active promotion whose depth matches the discount; 208 cleared (no discount, so not a promoted line); 1 set to UNKNOWN |
| TC-04 | medium | fact_sales | One extract batch per business day, loaded next morning | 571 |  | NONE | 729 daily batches; batches covering more than one business day: 0; batches with lines extracted at more than one hour (re-sends): 571; extract hours seen: [2, 5] |
| TC-06 | medium | fact_targets | A target for every store and retail week | 3 |  | GAP | S03|2024|28; S09|2024|30; S17|2024|29 |
| DP-03 | low | dim_product | Text fields without leading or trailing spaces | 2 |  | STANDARDISE | Trailing spaces break name matching and look like different products. |
| DP-08 | low | dim_product | product_name unique across product IDs | 36 |  | FLAG | 18 names shared by 2+ IDs |
| DS-02 | low | dim_store | Text fields without leading or trailing spaces | 1 |  | STANDARDISE | Padded names create duplicate labels in reports and failed joins on name. |
| DS-03 | low | dim_store | region, store_format in the canonical domain | 1 |  | STANDARDISE | A case variant of a region splits that region into two rows in every regional report. |
| FI-03 | low | fact_inventory | Quantities stored as whole numbers | 938,967 |  | STANDARDISE | columns stored with decimals: received_qty |
| FS-07 | low | fact_sales | POS category label equals the product master category | 20,059 |  | STANDARDISE | 0 lines whose standardised POS label names a different category; variants: 'TOYS & GAMES', 'Home&Kitchen', 'Home and Kitchen', 'Stationary & Crafts', 'Electronics', 'SEAS... |

## 4. What happened to the rows

| Table | Raw rows | Curated rows | Changed (corrected / standardised / imputed) | of which imputed | Kept and flagged | Quarantined |
|---|---|---|---|---|---|---|
| fact_sales (+ late file) | 1,341,515 | 1,339,510 | 28,776 | 134 | 2,270 | 2,005 |
| fact_inventory | 939,437 | 939,249 | 1,396 | 0 | 14 | 188 |
| fact_returns | 34,733 | 34,562 | 0 | 0 | 144 | 171 |
| fact_promotions | 49,434 | 49,430 | 5 | 0 | 0 | 4 |
| fact_targets | 2,079 | 2,077 | 1 | 0 | 0 | 2 |
| dim_product | 610 | 600 | 20 | 0 | 36 | 10 |
| dim_store | 20 | 20 | 2 | 0 | 0 | 0 |
| dim_date | 731 | 731 | 0 | 0 | 0 | 0 |

Sales line status: clean 1,308,464, standardised 23,025, corrected 5,617, flagged 2,270, imputed 134. `standardised` means only a label or format changed (for example the category text). The flagged sales lines are the late-arriving file, kept and marked `is_late_arriving`.

## 5. KPI impact before and after cleaning

*Raw as reported* reads the main extract and returns at face value (duplicates in, blanks as zero, unparseable dates dropped from period totals): what a spreadsheet built from the exports would show. *Clean, main extract* applies every rule but leaves out the late file. *Clean, complete* adds the late file.

| KPI | Raw as reported | Clean, main extract | Clean, complete | Change |
|---|---|---|---|---|
| Sales lines | 1,339,245 | 1,337,240 | 1,339,510 | +265 |
| Gross Sales (EUR) | 40,294,255.42 | 39,807,469.46 | 39,877,276.35 | -416,979.07 |
| Discount Value (EUR) | 1,661,271.50 | 1,661,988.81 | 1,665,652.67 | +4,381.17 |
| Sales Revenue (EUR) | 38,643,327.63 | 38,145,480.65 | 38,211,623.68 | -431,703.95 |
| Returns Value (EUR) | 1,295,646.12 | 1,288,620.48 | 1,288,620.48 | -7,025.64 |
| Net Revenue (EUR) | 37,347,681.51 | 36,856,860.17 | 36,923,003.20 | -424,678.31 |
| COGS (EUR) | 22,990,703.46 | 22,908,298.92 | 22,948,014.05 | -42,689.42 |
| Gross Margin (EUR) | 14,356,978.04 | 13,948,561.25 | 13,974,989.16 | -381,988.89 |
| Gross Margin % | 38.44% | 37.85% | 37.85% | -0.59pp |
| Transactions | 834,184 | 834,168 | 835,568 | +1,384 |
| Units | 1,772,499 | 1,765,505 | 1,768,568 | -3,931 |
| AOV (EUR) | 46.32 | 45.73 | 45.73 | -0.59 |
| UPT | 2.125 | 2.116 | 2.117 | -0.008 |
| ASP (EUR) | 21.80 | 21.61 | 21.61 | -0.20 |
| Return Rate % (value) | 3.35% | 3.38% | 3.37% | +0.02pp |
| Promo Revenue Share % | 15.39% | 15.40% | 15.39% | +0.00pp |
| Returns rows | 34,733 | 34,562 | 34,562 | -171 |
| Stock Availability % (2024) | 95.48% | 95.50% | 95.50% | +0.02pp |
| H2 2024 Net Revenue (EUR) | 10,309,576.19 | 10,188,727.55 | 10,188,727.55 | -120,848.64 |
| H2 2025 Net Revenue (EUR) | 9,505,708.40 | 9,391,314.02 | 9,457,457.05 | -48,251.35 |
| H2 YoY % | -7.80% | -7.83% | -7.18% | +0.62pp |

**Sales Revenue bridge (all periods), from the audit trail:**

| Step | Rows | Before | After | Change |
|---|---|---|---|---|
| TC-01 INCLUDE | 2,270 | 38,643,327.63 | 38,709,470.66 | +66,143.03 |
| FS-01 DEDUPLICATE | 1,965 | 38,709,470.66 | 38,654,975.11 | -54,495.55 |
| FS-08 CORRECT | 535 | 38,654,975.11 | 38,686,592.43 | +31,617.32 |
| FS-12 CORRECT | 67 | 38,686,592.43 | 38,691,612.91 | +5,020.48 |
| FS-09 QUARANTINE | 40 | 38,691,612.91 | 38,570,500.43 | -121,112.48 |
| FS-13 CORRECT | 134 | 38,570,500.43 | 38,208,367.34 | -362,133.09 |
| FS-11 IMPUTE | 134 | 38,208,367.34 | 38,211,851.13 | +3,483.79 |
| FS-17 CORRECT | 535 | 38,211,851.13 | 38,211,623.68 | -227.45 |

## 6. Completeness and timeliness

- **Late-arriving sales file (TC-01):** 2,270 lines in the late file, extract lag 12 to 25 days; main extract lag 1 to 1 days; late lines sharing a key with the main extract: 0. Loaded with `is_late_arriving = True`, worth EUR 66,143.
- **Missing store-days (TC-02):** 15 store-days missing from the main extract; 13 delivered by the late file; 2 still missing (S13 2024-10-15, S13 2024-10-16), estimated EUR 7,766.
  - S13 2024-10-15: no POS data at all; the stock system shows 1,336 units sold that week against 1,015 in POS, and 1 return references receipts from that day, so the store traded. Estimated missing revenue EUR 3,597 (same weekday, 4 weeks either side). Not imputed.
  - S13 2024-10-16: no POS data at all; the stock system shows 1,336 units sold that week against 1,015 in POS, and 4 returns reference receipts from that day, so the store traded. Estimated missing revenue EUR 4,168 (same weekday, 4 weeks either side). Not imputed.
- **Batch structure (TC-04):** 729 daily batches; batches covering more than one business day: 0; batches with lines extracted at more than one hour (re-sends): 571; extract hours seen: [2, 5]. The 05:00 extracts carry the re-sent duplicate lines (FS-01).
- **Stock snapshots (TC-05):** 462 store-SKU-weeks missing inside otherwise continuous series (`inventory_missing_weeks.csv`); not imputed.
- **Targets (TC-06):** missing store-weeks S03|2024|28; S09|2024|30; S17|2024|29; not imputed.
- **Low-volume days (TC-03):** 0 store-days below 30% of the store's usual same-weekday revenue (no partial batches detected).
- **POS vs stock system (TC-07):** match rate 98.4605% before cleaning, 99.4695% after (7,589 -> 2,610 store-SKU-weeks); remaining: sales line with UNKNOWN product in that store-week (FS-05/FS-06) 2157; missing stock snapshot (TC-05) 251; missing POS store-day (TC-02) 157; quarantined sales line (FS-09) 40; unexplained 3; flagged stock row (FI-04..FI-07) 2.
- Returns, stock, promotions and targets carry no extract timestamps, so their timeliness cannot be tested.

## 7. Unresolved issues and assumptions

**Unresolved (reported, not fixed):**

- 1,293 sales lines (EUR 38,665) have no identifiable product (blank or unknown code, no linked return). They stay in totals under the UNKNOWN product and are excluded from product and category analysis.
- 2 store-days of POS data were never delivered (estimated EUR 7,766). A re-extract should be requested from the source system.
- 144 returns (EUR 5,027) reference sale lines that were never received; kept in Returns Value because the refund was paid.
- 14 stock rows still break the stock identity after triangulation and are flagged.
- 462 missing stock snapshots and 3 missing targets remain gaps.
- 1 promoted line(s) keep an UNKNOWN promotion.

**Assumptions (judgement calls a business owner should confirm):**

1. The transaction ID is authoritative for date and store (every valid date in the file agrees with it).
2. Negative quantity and negative price lines are sign errors, not till refunds: all money fields are negated together, returns live in their own file, and correcting them raises the POS-to-stock match rate.
3. Quantities above 20 on a store POS line are not real; the true quantity is unknown, so those lines are quarantined rather than guessed.
4. A zero price is a pricing failure, not a giveaway; the SKU's list price for the year is imputed and the line is flagged `is_imputed` (discount from the promotion depth when a matching promotion exists).
5. Impossible returns (dated before the sale, or more units than sold) are quarantined; over-refunds and unlinked returns are kept because money was paid out.
6. Where a product master record is duplicated, the copy whose list price matches the till price is kept.
7. Superseded target versions: the highest version, then the latest set date, wins.
8. Estimates for missing store-days are for disclosure only and are never added to the data.

## 8. Validation results

| group | check | status | value |
|---|---|---|---|
| row conservation | dim_store: raw rows = curated + quarantined | PASS | 20 = 20 + 0 |
| row conservation | dim_product: raw rows = curated + quarantined | PASS | 610 = 600 + 10 |
| row conservation | dim_date: raw rows = curated + quarantined | PASS | 731 = 731 + 0 |
| row conservation | fact_sales: raw rows = curated + quarantined | PASS | 1,341,515 = 1,339,510 + 2,005 |
| row conservation | fact_inventory: raw rows = curated + quarantined | PASS | 939,437 = 939,249 + 188 |
| row conservation | fact_returns: raw rows = curated + quarantined | PASS | 34,733 = 34,562 + 171 |
| row conservation | fact_promotions: raw rows = curated + quarantined | PASS | 49,434 = 49,430 + 4 |
| row conservation | fact_targets: raw rows = curated + quarantined | PASS | 2,079 = 2,077 + 2 |
| keys | dim_store: primary key unique | PASS | 20 rows |
| keys | dim_product: primary key unique | PASS | 601 rows |
| keys | dim_date: primary key unique | PASS | 731 rows |
| keys | fact_sales: primary key unique | PASS | 1,339,510 rows |
| keys | fact_inventory: primary key unique | PASS | 939,249 rows |
| keys | fact_returns: primary key unique | PASS | 34,562 rows |
| keys | fact_promotions: primary key unique | PASS | 49,430 rows |
| keys | fact_targets: primary key unique | PASS | 2,077 rows |
| referential integrity | fact_sales: store_id and product_id in dimensions | PASS |  |
| referential integrity | fact_returns: store_id and product_id in dimensions | PASS |  |
| referential integrity | fact_inventory: store_id and product_id in dimensions | PASS |  |
| referential integrity | fact_promotions: store_id and product_id in dimensions | PASS |  |
| referential integrity | fact_targets: store_id in dim_store | PASS |  |
| referential integrity | fact_sales: promotion_id in fact_promotions or UNKNOWN | PASS |  |
| referential integrity | fact_sales: lines on the UNKNOWN product member | PASS | 1,293 lines, EUR 38,664.54 |
| sales | dates present, in period and equal to the transaction ID date | PASS |  |
| sales | store equals the transaction ID store | PASS |  |
| sales | quantity between 1 and the plausible maximum | PASS |  |
| sales | unit_price and unit_cost positive | PASS |  |
| sales | no missing money fields | PASS |  |
| sales | revenue = quantity x unit_price - discount | PASS |  |
| sales | margin = revenue - cost | PASS |  |
| sales | cost = quantity x unit_cost | PASS |  |
| sales | discount between 0 and maximum share of gross | PASS | 0 lines |
| sales | category canonical | PASS |  |
| sales | every line carries a dq_status | PASS | clean 1,308,464; standardised 23,025; corrected 5,617; flagged 2,270; imputed 134 |
| returns | quantity and refund positive | PASS |  |
| returns | return dates in period | PASS |  |
| returns | no return dated before its sale | PASS |  |
| returns | no return quantity above quantity sold | PASS |  |
| returns | returns referencing a sale line that was never received | WARN | 144 returns, EUR 5,027.48 (kept, flagged FR-04) |
| inventory | no missing stock quantities | PASS |  |
| inventory | no negative closing stock | PASS |  |
| inventory | stock identity holds | WARN | 14 rows flagged FI-06 |
| inventory | only integer quantities | PASS |  |
| promotions | end_date on or after start_date | PASS |  |
| targets | targets positive and no extreme outliers | PASS |  |
| dimensions | product categories canonical | PASS |  |
| dimensions | store regions canonical | PASS |  |
| dimensions | no untrimmed text in dimensions | PASS |  |
| KPI identities | Sales Revenue = Gross Sales - Discount Value | PASS | 38,211,623.68 vs 38,211,623.68 |
| KPI identities | Sales Revenue = Transactions x UPT x ASP | PASS |  |
| reconciliation | POS units vs stock-system units: match rate improved by cleaning | PASS | 98.4605% -> 99.4695% |
| framework | every catalogue rule was evaluated | PASS | all |
| lineage | raw input files unchanged by the run | PASS | SHA-256 before = after |

## 9. Independent cross-check

Before the rules were written, a separate agent with no access to the generator, its configuration or any evaluation file profiled the same 9 extracts blind and listed 66 findings (`reports/phase3/independent_blind_profile_findings.csv`, scripts alongside). All 66 map to a pipeline rule (`independent_crosscheck.csv`). Counts differ only where the pipeline measures after an upstream fix (for example, 12 of the profiler's 79 'returned more than sold' cases were caused by sign-inverted sale lines and disappear once those are corrected).

## 10. Artefacts (data lineage and audit)

| File | Content |
|---|---|
| `data/processed/curated/*.csv` | 8 curated tables with `dq_status`, `dq_rules`, `source_file`, `source_row` |
| `data/processed/quarantine/*_quarantine.csv` | Rejected rows exactly as received, with `dq_rule_id` and `dq_reason` |
| `reports/phase3/profile_tables.csv`, `profile_columns.csv` | Pre-cleaning profile |
| `reports/phase3/dq_rule_catalogue.csv` | Every rule: severity, treatment, rationale |
| `reports/phase3/dq_rule_results.csv` (= `reports/data_quality_report.csv`) | Rows checked and failed, EUR affected, evidence |
| `reports/phase3/dq_issue_log.csv` | One line per affected record: rule, key, column, raw value, new value, action |
| `reports/phase3/cleaning_audit_trail.csv` | Ordered treatment steps with rows affected and metric before/after |
| `reports/phase3/kpi_reconciliation.csv` | BRD KPIs in the three views |
| `reports/phase3/curated_validation.csv` | Post-cleaning checks (PASS/WARN/FAIL) |
| `reports/phase3/completeness_store_days.csv`, `inventory_missing_weeks.csv`, `missing_targets.csv`, `extract_batches.csv`, `low_volume_store_days.csv` | Completeness and timeliness detail |
| `reports/phase3/pos_stock_mismatches.csv` | Remaining POS vs stock mismatches with their explanation |
| `reports/phase3/category_mapping.csv`, `sku_reference_prices.csv` | Reference data used by the rules |
| `reports/phase3/lineage.json` | Input and output SHA-256, row counts, config and code hashes |
| `logs/dq_run_*.log` | Run log |

## Appendix: expected behaviour documented (no action)

| Rule | Check | Rows | Why it is not an error |
|---|---|---|---|
| DD-03 | Retail weeks have 7 days (partial week at extract end) | 1 | 29-31 Dec 2025 belong to retail 2026 week 1, outside the 104 comparable weeks. |
| FP-06 | Promotion window inside the extract period | 797 | Promotions that straddle the period end are valid. |
| FR-03 | Return linked to an original sale | 1,049 | No-receipt returns are allowed (BRD assumption 2); they stay in Returns Value. |
| FR-09 | Returned at a different store from the sale | 1,943 | Allowed by policy (BRD assumption 2: returns are recorded where they are returned). |
| FR-12 | Linked sale only exists in the late sales file | 59 | Resolved by loading the late file (TC-01). |
| FS-23 | Discount without a promotion_id (non-promotional markdown) | 16,079 | Damaged-box and price-match markdowns are legitimate and are not promotions. |
| FS-24 | Line unit_cost differs from the product master cost | 681,910 | The master holds the current standard cost; the till records the cost of the day (history). |
| FS-25 | Negative line margin | 8,396 | Clearance and deep promotions can sell below cost. |
| FS-28 | Line price check impossible (UNKNOWN product, no reference price) | 1,293 | Recorded for transparency: these lines cannot be price-checked. |
