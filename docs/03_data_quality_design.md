# Phase 3: Data Quality, Cleaning and Validation Design

| Item | Detail |
|---|---|
| Project | Retail Performance & Root-Cause Analytics System |
| Company | Brightwater Retail Ltd (fictional, synthetic data) |
| Author | Waleed Bin Umer |
| Version | 1.0 (awaiting Phase 3 sign-off) |
| Date | 28 September 2026 |
| Depends on | `docs/01_business_requirements.md` (KPIs, BR-10), `docs/02_data_generation_design.md` section 5 (data contract) |
| Results | `reports/data_quality_report.md` |

> Sequencing note: the BRD's deliverable table lists the data-quality framework as deliverable 4 and the data model as deliverable 3. At the project owner's request the data-quality work is delivered first, as Phase 3, so the SQL model is built on trusted data. The deliverable itself (`src/data_quality/`, `reports/data_quality_report.csv`) is unchanged.

---

## 1. Purpose

Treat the files in `data/raw/` as incoming source-system extracts and turn them into trusted, curated tables, without changing the raw files and without consulting anything that describes how the data was made. The output of this phase is the only input to the SQL model and the analysis that follow.

## 2. Principles

1. **Raw is read-only.** Raw files are fingerprinted (SHA-256) before and after each run; a change fails the run.
2. **Detect, classify, then treat.** Every rule has an ID, a severity, a treatment and a written business rationale (`src/data_quality/catalogue.py`).
3. **Correct only with evidence.** A value is changed only when an authoritative source in the data supports the new value. Otherwise the row is flagged, mapped to an UNKNOWN member, reported as a gap or quarantined. Nothing is invented.
4. **Nothing disappears silently.** Every raw row ends up curated or quarantined (tested). Every change is logged at row level and at step level.
5. **Independent of the answer key.** The loader accepts only the nine business extracts in `config/dq_config.yaml`; every file whose name starts with an underscore is refused. Tests scan the code and trace every file opened during a run.
6. **Proportionate.** pandas and plain CSV outputs, all transformations expressible in SQL. No extra infrastructure.

## 3. Pipeline

```
data/raw/*.csv (read as text)
   │  1 fingerprint inputs (SHA-256)
   │  2 profile every column (types, blanks, ranges, duplicates)          -> reports/phase3/profile_*.csv
   │  3 dimensions: dim_store, dim_date, dim_product (+ UNKNOWN member)
   │  4 facts: promotions -> targets -> sales (+ late file) -> returns -> inventory
   │  5 completeness and timeliness: store-day coverage, batches, stock gaps, target gaps
   │  6 reconciliation: POS units vs stock-system units, before and after
   │  7 KPI reconciliation: raw as reported / clean main extract / clean complete
   │  8 validate curated outputs (PASS / WARN / FAIL)
   ▼  9 write curated, quarantine, issue log, audit trail, lineage, report
data/processed/curated/*.csv   data/processed/quarantine/*_quarantine.csv   reports/phase3/*   reports/data_quality_report.*
```

| Module (`src/data_quality/`) | Responsibility |
|---|---|
| `core.py` | Safe loader (whitelist), parsing helpers, `DQContext` (results, issue log, quarantine, audit) |
| `catalogue.py` | The rule catalogue: severity, treatment, rationale |
| `profiling.py` | Pre-cleaning profile of every column |
| `dimensions.py` | Store, product and date rules; category matcher; SKU reference prices from the till |
| `promotions_targets.py` | Promotion and target rules; missing targets |
| `sales.py` | POS line rules in a fixed order; per-row `dq_status` and `dq_rules` |
| `returns_inventory.py` | Returns and stock rules; stock-flow triangulation; POS-to-stock reconciliation |
| `completeness.py` | Store-day coverage, low-volume days, extract batch structure |
| `kpis.py` | BRD section 5 KPIs and the week-aligned H2 figures |
| `validate_curated.py` | Post-cleaning validation |
| `report.py` | Builds the Data Quality Report from the run's outputs |
| `run_dq.py` | Orchestration and CLI |

Commands (from the project root):

```
python -m src.data_quality.run_dq                                   # full data (about 2 minutes)
python -m src.data_quality.run_dq --data data/sample --out tmp/dq   # sample (about 25 seconds)
python -m pytest tests/test_phase3_rules.py tests/test_phase3_pipeline.py
```

## 4. Severity and treatment

| Severity | Meaning |
|---|---|
| critical | Breaks keys or materially misstates a headline KPI if untreated |
| high | Invalid value affecting KPIs, joins or an analysis |
| medium | Recoverable problem with limited KPI effect, or a consistency warning |
| low | Cosmetic or presentation problem |
| info | Expected business behaviour, documented so nobody "fixes" it later |

| Treatment | What happens | Where it shows |
|---|---|---|
| CORRECT | Value rebuilt from an authoritative source | issue log (raw and new value), `dq_status = corrected` |
| STANDARDISE | Format or label normalised | issue log, `dq_status = standardised` |
| DEDUPLICATE | Duplicate copy removed | quarantine file with reason |
| IMPUTE | Value estimated from a reference | `is_imputed = True`, `dq_status = imputed` |
| UNKNOWN_MEMBER | Key mapped to `UNKNOWN` so totals stay complete | issue log; excluded from product analysis |
| QUARANTINE | Row cannot be trusted as recorded; excluded from KPIs | quarantine file with rule and reason |
| FLAG | Row kept and used, marked for review | `dq_rules`, `dq_status = flagged` |
| INCLUDE | Valid data delivered late, loaded with a flag | `is_late_arriving = True` |
| GAP | Missing data reported (and estimated for disclosure), never filled | completeness reports |

## 5. Evidence used for corrections

| Correction | Authoritative source | Why it is safe |
|---|---|---|
| Transaction date and store | The till-generated transaction ID (`Sxx-yyyymmdd-nnnnn`) | 100% of valid in-period dates in the file agree with the ID |
| Revenue | quantity x price - discount, confirmed by cost + margin on the same line | Two independent fields agree; only revenue disagrees |
| Missing price or discount | revenue, discount and quantity on the same line | Arithmetic identity |
| Decimal-shift price | SKU reference price (one list price per SKU per year at the till) | Ratio is exactly 100 |
| Sign-inverted lines | All money fields negated together; returns live in their own file | Correction raises the POS-to-stock match rate |
| Blank or unknown product | A return that references the same sale line | A second system record |
| Unknown promotion code | The one promotion active for that store, product and date whose depth equals the line discount | Unique match on four attributes |
| Promotion row with invalid product | POS lines of that promotion and store point to exactly one missing product | Two files agree |
| Stock opening or closing | Previous week's closing and next week's opening | Two neighbouring snapshots agree |
| Missing received quantity | Stock identity on the same row | Arithmetic identity |
| Target 100x too high | Store's median target | Dividing by 100 lands in the normal range |
| Duplicate product record | Till price in the latest year | The kept record matches what customers paid |

## 6. Completeness and timeliness

- **Extract timeliness:** extract lag = extract date minus business date. The main extract lands the next morning; the late file lands 12 to 25 days later and is loaded with a flag, so reports can show "as first reported" and "complete".
- **Store-day coverage:** every trading store should have POS data on every trading day. A gap is confirmed as missing data (not a closure) when the stock system records sales that week or returns reference receipts from that day. Gaps are estimated for disclosure only.
- **Batch structure:** one batch per business day; extracts at a second hour reveal re-sends.
- **Stock and targets:** missing weeks inside a stock series and missing store-week targets are listed, not imputed.
- **Reconciliation:** POS units and stock-system units per store-SKU-week are compared before and after cleaning. Every remaining mismatch is attributed to a logged cause where one exists.

## 7. Outputs and lineage

| Output | Content |
|---|---|
| `data/processed/curated/` | 8 curated tables, typed, with `dq_status`, `dq_rules`, `source_file`, `source_row` |
| `data/processed/quarantine/` | Rejected rows exactly as received, with `dq_rule_id` and `dq_reason` |
| `reports/phase3/dq_rule_results.csv` | Per rule: rows checked, rows failed, EUR affected, evidence (also `reports/data_quality_report.csv`, the BRD location) |
| `reports/phase3/dq_issue_log.csv` | One line per affected record: rule, key, column, raw value, new value, action |
| `reports/phase3/cleaning_audit_trail.csv` | Ordered treatment steps with rows affected and metric before/after |
| `reports/phase3/kpi_reconciliation.csv` | BRD KPIs in three views |
| `reports/phase3/curated_validation.csv` | Post-cleaning checks |
| `reports/phase3/lineage.json` | Input and output SHA-256, row counts, config and code hashes |
| `reports/phase3/independent_*.csv` | Blind profiling findings and their mapping to rules |

Every curated row can be traced back to its raw line (`source_file`, `source_row`), and every change to it is in the issue log under its natural key.

## 8. Independence and evaluation

- The production code never opens an evaluation-only asset. This is enforced three ways: the loader whitelist, a static test that scans `src/data_quality/` and `config/dq_config.yaml` for asset names and generator imports, and a runtime test that traces every file opened during a pipeline run.
- **Disclosure:** the same AI assistant that built the Phase 2 generator built this pipeline, so general knowledge of the kinds of problems planted cannot be ruled out. To limit this, a separate agent with no access to the generator, its configuration or any evaluation file profiled the raw extracts blind before the rules were written. Its 66 findings are stored with its scripts, and every one maps to a pipeline rule (`reports/phase3/independent_crosscheck.csv`).
- Scoring against the planted-issue log happens only after the Phase 3 outputs are frozen, in `evaluation/evaluate_phase3_detection.py`, outside the production code. Its results are not used to tune the rules.

## 9. Known limitations

- Sales lines whose product cannot be identified stay under the UNKNOWN product: complete in totals, absent from product and category analysis.
- Two store-days of POS data were never delivered; only a re-extract can fix them.
- Returns, stock, promotions and targets carry no extract metadata, so their timeliness cannot be tested.
- Assumptions that need business confirmation are listed in section 7 of the Data Quality Report (sign errors, bulk-quantity threshold, zero-price imputation, impossible returns).
- Checks run on files in pandas. When the data moves to SQL Server, the same rules become SQL validation queries (Phase 4 onward).

## 10. Rule catalogue

The full catalogue with rationale is in `src/data_quality/catalogue.py` and `reports/phase3/dq_rule_catalogue.csv`.

| Rule | Table | Check | Severity | Treatment |
|---|---|---|---|---|
| SCH-01 | all | Expected columns are present | critical | NONE |
| SCH-02 | all | Values parse to the contract type (blanks counted separately) | high | NONE |
| DS-01 | dim_store | store_id unique and well formed | critical | NONE |
| DS-02 | dim_store | Text fields without leading or trailing spaces | low | STANDARDISE |
| DS-03 | dim_store | region, store_format in the canonical domain | low | STANDARDISE |
| DS-04 | dim_store | Numeric attributes plausible (area, FTE, hours, coordinates in Ireland) | medium | NONE |
| DP-01 | dim_product | product_id unique | critical | DEDUPLICATE |
| DP-02 | dim_product | category is one of the 7 canonical categories | medium | STANDARDISE |
| DP-03 | dim_product | Text fields without leading or trailing spaces | low | STANDARDISE |
| DP-04 | dim_product | supplier_id and supplier_name present | medium | UNKNOWN_MEMBER |
| DP-05 | dim_product | list_price and unit_cost positive | high | CORRECT |
| DP-06 | dim_product | unit_cost below list_price | medium | FLAG |
| DP-07 | dim_product | Launch/discontinuation dates and status consistent | medium | FLAG |
| DP-08 | dim_product | product_name unique across product IDs | low | FLAG |
| DP-09 | dim_product | Each subcategory belongs to one category | medium | NONE |
| DD-01 | dim_date | One row per calendar day for the whole period, keys unique | critical | NONE |
| DD-02 | dim_date | Derived attributes agree with the date (weekday, weekend, retail week) | high | NONE |
| DD-03 | dim_date | Retail weeks have 7 days (partial week at extract end) | info | NONE |
| FS-01 | fact_sales | transaction_id + line_number unique | critical | DEDUPLICATE |
| FS-02 | fact_sales | transaction_date in ISO format (yyyy-mm-dd) | medium | STANDARDISE |
| FS-03 | fact_sales | transaction_date present, valid, in period and equal to the ID date | high | CORRECT |
| FS-04 | fact_sales | store_id present, known and equal to the ID store | high | CORRECT |
| FS-05 | fact_sales | product_id present | high | CORRECT |
| FS-06 | fact_sales | product_id exists in dim_product | high | UNKNOWN_MEMBER |
| FS-07 | fact_sales | POS category label equals the product master category | low | STANDARDISE |
| FS-08 | fact_sales | quantity positive (whole line sign-inverted) | high | CORRECT |
| FS-09 | fact_sales | quantity at or below the plausible maximum for a store line | high | QUARANTINE |
| FS-10 | fact_sales | unit_price present | medium | CORRECT |
| FS-11 | fact_sales | unit_price above zero | high | IMPUTE |
| FS-12 | fact_sales | unit_price not negative (money fields sign-inverted) | high | CORRECT |
| FS-13 | fact_sales | unit_price not about 100x the SKU reference price | critical | CORRECT |
| FS-14 | fact_sales | unit_price within 1% of the SKU-year reference price | medium | FLAG |
| FS-15 | fact_sales | discount present | medium | CORRECT |
| FS-16 | fact_sales | discount between 0 and the maximum discount share of gross | medium | FLAG |
| FS-17 | fact_sales | revenue = quantity x unit_price - discount | high | CORRECT |
| FS-18 | fact_sales | margin = revenue - cost and cost = quantity x unit_cost | medium | CORRECT |
| FS-19 | fact_sales | promotion_id exists in fact_promotions | medium | CORRECT |
| FS-20 | fact_sales | Promoted line's store and product are in that promotion | medium | FLAG |
| FS-21 | fact_sales | Promoted line carries a discount | low | FLAG |
| FS-22 | fact_sales | Promoted line falls within the promotion dates | low | FLAG |
| FS-23 | fact_sales | Discount without a promotion_id (non-promotional markdown) | info | NONE |
| FS-24 | fact_sales | Line unit_cost differs from the product master cost | info | NONE |
| FS-25 | fact_sales | Negative line margin | info | NONE |
| FS-26 | fact_sales | One store, date and time per transaction; line numbers 1..n | high | FLAG |
| FS-27 | fact_sales | No sales before launch or more than a week after discontinuation | medium | FLAG |
| FS-28 | fact_sales | Line price check impossible (UNKNOWN product, no reference price) | info | NONE |
| TC-01 | fact_sales | Sales batches arrive within the expected lag | high | INCLUDE |
| TC-02 | fact_sales | Every store has POS data for every trading day | critical | GAP |
| TC-03 | fact_sales | Store-day revenue not far below the store's usual level | medium | FLAG |
| TC-04 | fact_sales | One extract batch per business day, loaded next morning | medium | NONE |
| TC-05 | fact_inventory | No missing week inside a store-SKU stock series | high | GAP |
| TC-06 | fact_targets | A target for every store and retail week | medium | GAP |
| TC-07 | fact_inventory | POS units equal stock-system sold units per store-SKU-week | high | NONE |
| FI-01 | fact_inventory | No exact duplicate rows | high | DEDUPLICATE |
| FI-02 | fact_inventory | store + product + snapshot_date unique | critical | QUARANTINE |
| FI-03 | fact_inventory | Quantities stored as whole numbers | low | STANDARDISE |
| FI-04 | fact_inventory | received_qty present | medium | CORRECT |
| FI-05 | fact_inventory | closing_stock not negative | high | CORRECT |
| FI-06 | fact_inventory | closing = opening + received - sold + adjustment | medium | CORRECT |
| FI-07 | fact_inventory | opening_stock equals the previous week's closing_stock | medium | FLAG |
| FI-08 | fact_inventory | Stock fields in range (no negatives other than adjustments) | high | FLAG |
| FI-09 | fact_inventory | Snapshot is a Sunday and matches the retail week | medium | NONE |
| FI-10 | fact_inventory | store_id and product_id exist in the dimensions | high | FLAG |
| FR-01 | fact_returns | No exact duplicate rows | high | DEDUPLICATE |
| FR-02 | fact_returns | return_id unique | critical | QUARANTINE |
| FR-03 | fact_returns | Return linked to an original sale | info | NONE |
| FR-04 | fact_returns | Linked sale line exists | high | FLAG |
| FR-05 | fact_returns | Return date after the sale date | high | QUARANTINE |
| FR-06 | fact_returns | Returned quantity not above the quantity sold | high | QUARANTINE |
| FR-07 | fact_returns | Refund not above the sale line value for the units returned | medium | FLAG |
| FR-08 | fact_returns | Returned product equals the product on the sale line | medium | FLAG |
| FR-09 | fact_returns | Returned at a different store from the sale | info | NONE |
| FR-10 | fact_returns | Return within the returns policy window | medium | FLAG |
| FR-11 | fact_returns | Quantity and refund positive, reason and restockable flag valid, store and product known | high | FLAG |
| FR-12 | fact_returns | Linked sale only exists in the late sales file | info | NONE |
| FP-01 | fact_promotions | No exact duplicate rows | medium | DEDUPLICATE |
| FP-02 | fact_promotions | end_date on or after start_date | high | CORRECT |
| FP-03 | fact_promotions | One name, type and window per promotion_id | medium | FLAG |
| FP-04 | fact_promotions | product_id and store_id exist in the dimensions | medium | QUARANTINE |
| FP-05 | fact_promotions | discount_pct between 0 and the maximum discount share | high | FLAG |
| FP-06 | fact_promotions | Promotion window inside the extract period | info | NONE |
| FT-01 | fact_targets | One target per store and retail week | high | DEDUPLICATE |
| FT-02 | fact_targets | Target not an extreme outlier for the store | high | CORRECT |
| FT-03 | fact_targets | Week dates match the retail calendar | medium | NONE |
| FT-04 | fact_targets | Target positive and store known | high | FLAG |
