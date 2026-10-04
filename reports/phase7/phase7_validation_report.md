# Phase 7 validation report: Power BI dashboard assets

Run: 2026-09-29T19:59:45 | engine: mssql | runtime 182.4 s | overall: **PASS** (102 of 102 checks)

## What was tested here and what was not

| Item | Status in this environment |
|---|---|
| Phase 1-6 freeze (SHA-256 of every frozen file) | Tested: all unchanged |
| Power BI source views `pbi.*` (T-SQL) | Tested on the DuckDB rebuild of the Phase 4 model (same scripts, translated); not run on SQL Server here |
| DAX measure LOGIC (filter semantics, PY shift, inactive relationship, target weeks) | Tested through the Python reference implementation, reconciled to Phase 4, 5 and 6 |
| DAX TEXT (syntax, engine behaviour) | Static checks only (references, columns, parentheses, cycles). **Must be confirmed in Power BI Desktop** with `powerbi/dax/validation_queries.dax` |
| TMDL script, Power Query, theme | Written; **not executed** (no Power BI Desktop) |
| Report pages, slicers, drill-through, tooltips | Specified and drawn as mockups; **not built or tested** |
| Performance Analyzer | **Not run** (needs Power BI Desktop); model profile below instead |

## Headline reconciliation

| Check | Dashboard measure | Reference | Status |
|---|---:|---:|---|
| Headline: H2 2025 net revenue = Phase 7 brief | 9,457,457.050000 | 9,457,457.050000 | PASS |
| Headline: H2 2024 net revenue = Phase 7 brief | 10,188,727.550000 | 10,188,727.550000 | PASS |
| Headline: H2 net revenue change = Phase 7 brief | -731,270.500000 | -731,270.500000 | PASS |
| Headline: YoY % = Phase 7 brief (6 dp) | -7.177251 | -7.177251 | PASS |
| Headline: H2 2024 via the PY measure = H2 2024 filtered directly | 10,188,727.550000 | 10,188,727.550000 | PASS |
| Phase 4: H2 2025 net revenue | 9,457,457.050000 | 9,457,457.050000 | PASS |
| Phase 4: H2 2024 net revenue | 10,188,727.550000 | 10,188,727.550000 | PASS |
| Phase 4: H2 YoY % | -7.177251 | -7.177251 | PASS |
| Phase 6: H2 2025 net revenue | 9,457,457.050000 | 9,457,457.050000 | PASS |
| Phase 6: H2 2024 net revenue | 10,188,727.550000 | 10,188,727.550000 | PASS |
| Phase 6: H2 change | -731,270.500000 | -731,270.500000 | PASS |
| Phase 6: Electronics & Tech net revenue change | -268,518.330000 | -268,518.330000 | PASS |
| Phase 6: Electronics & Tech availability H2 2025 | 0.892808 | 0.892808 | PASS |
| Phase 6: Electronics & Tech availability H2 2024 | 0.953796 | 0.953796 | PASS |
| Phase 6: Voltix Distribution Ltd full-week stock-outs H2 2025 | 674.000000 | 674.000000 | PASS |
| Phase 6: Voltix Distribution Ltd full-week stock-outs H2 2024 | 0.000000 | 0.000000 | PASS |
| Phase 6: Voltix Distribution Ltd availability H2 2025 | 0.827045 | 0.827045 | PASS |
| Phase 6: Investigated cluster: transactions per store H2 2025 | 8,386.666667 | 8,386.666667 | PASS |
| Phase 6: Investigated cluster: transactions YoY % (= per-store change) | -27.757200 | -27.757200 | PASS |
| Phase 6: Matched control: transactions per store H2 2025 | 11,691.000000 | 11,691.000000 | PASS |
| Phase 6: Matched control: transactions YoY % (= per-store change) | -1.114795 | -1.114795 | PASS |
| Phase 6: Electronics & Tech 'Changed mind' returns change | -1,154.300000 | -1,154.300000 | PASS |
| Phase 6: Electronics & Tech 'Damaged' returns change | 484.060000 | 484.060000 | PASS |
| Phase 6: Electronics & Tech 'Faulty' returns change | 31,588.730000 | 31,588.730000 | PASS |
| Phase 6: Electronics & Tech 'Gift return' returns change | -3,261.580000 | -3,261.580000 | PASS |
| Phase 6: Electronics & Tech 'Not as described' returns change | -1,368.280000 | -1,368.280000 | PASS |
| Phase 6: Faulty cohort rate per 100 units by sale month (24 months, largest difference) | 0.000000 | 0.000000 | PASS |
| Phase 6: Home & Kitchen discount rate H2 2024 (1 dp, as reported) | 2.400000 | 2.400000 | PASS |
| Phase 6: Home & Kitchen discount rate H2 2025 (1 dp, as reported) | 11.900000 | 11.900000 | PASS |

Required: H2 2024 €10,188,727.55; H2 2025 €9,457,457.05; change €-731,270.50; YoY -7.177251%.

## All checks by group

| Group | Checks | Passed |
|---|---:|---:|
| Headline | 5 | 5 |
| Phase 4 | 3 | 3 |
| Phase 5 | 26 | 26 |
| Phase 6 | 21 | 21 |
| Weekly | 1 | 1 |
| Stores | 8 | 8 |
| Targets | 2 | 2 |
| Categories | 11 | 11 |
| Attribution | 7 | 7 |
| Evidence | 5 | 5 |
| Promotions | 2 | 2 |
| Guards | 3 | 3 |
| Traceability | 1 | 1 |
| DAX | 7 | 7 |

Failures: none.

Full list: `phase7_validation_checks.csv`.

## Dashboard number register

146 numbers appear on the seven pages. Each has a source: 76 are DAX measures in a stated filter context (evaluated through the reconciled reference), 70 are cells of frozen Phase 5/6 outputs. See `dashboard_number_register.csv`; the tests re-derive every entry from its source.

| Evidence tag | Numbers |
|---|---:|
| FACT | 102 |
| ESTIMATE | 37 |
| ESTIMATE (remainder) | 2 |
| HYPOTHESIS | 2 |
| n/a (partition, not an estimate) | 2 |
| STATISTICAL ASSOCIATION | 1 |

## Power BI Desktop validation cases

`powerbi/dax/validation_queries.dax` holds 55 cases with the expected value of each (from the reconciled reference). Paste it into DAX query view; every row must return PASS. The cases cover the headline, all nine KPI cards, PY time intelligence, the cluster store groups, Electronics availability and stock-outs, 'Faulty' returns, Home & Kitchen discount rate, a sale-cohort value (inactive relationship) and the attribution total.

## Extract traceability

33 Phase 5/6 tables are imported (`powerbi/data/`). Each is a column selection of a frozen file whose SHA-256 matches the Phase 7 freeze manifest (`powerbi/data/extract_manifest.csv`). No Phase 6 figure is recomputed.

## Model profile (performance review without Performance Analyzer)

| Table | Rows | Columns |
|---|---:|---:|
| Date | 732 | 21 |
| Inventory | 939,249 | 9 |
| Product | 601 | 12 |
| Promotion | 138 | 12 |
| Returns | 34,562 | 12 |
| Sales | 1,339,510 | 12 |
| Store | 21 | 12 |
| Targets | 2,077 | 3 |

High-cardinality columns (largest VertiPaq cost): Sales[sales_line_id] 1,339,510; Sales[transaction_key] 835,568. `sales_line_id` and `return_id` are kept only for drill-through and can be removed from the import if the model must be smaller; `transaction_key` is an integer by design so DISTINCTCOUNT stays fast.

## Independence

Files opened during the run: 114 project files; refused: 0. No evaluation-only or answer-key file was opened (audit hook).

Mockups: page1_executive_overview.png, page2_store_customer.png, page3_product_inventory.png, page4_returns_quality.png, page5_promotions.png, page6_evidence_matrix.png, page7_investigation.png.
