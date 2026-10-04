# Phase 3 Reproducibility Diagnosis

**Mode:** Diagnostic only. No curated CSV, lineage, manifest, configuration, or analytical output was modified. No Phase 4+ pipeline was run.

## Finding

The frozen curated hashes differ from the staged hashes solely because of record line endings. All eight staged files use CRLF; changing only each CRLF pair to LF, while preserving every other byte, reproduces the exact historical SHA-256 in `reports/phase3/lineage.json` for every table. This proves the staged table bytes have the historical content, field order, row order, values, quoting, and null/numeric/date serialization; only line terminators differ.

No historical curated CSV files were present in the 11 candidate RPRCA/retail project archives inspected. The historical canonical-content fingerprint therefore cannot be computed directly from an archived table. However, the line-ending-normalized file hashes match the frozen hashes exactly, a stronger byte-preserving content check than a separate canonical fingerprint comparison would provide.

## Per-Table Results

`Canonical fingerprint` is SHA-256 over JSON Lines built from the staged records after applying the approved column/type order, normalizing null/date/datetime/time/numeric/boolean values, and sorting by the configured business key. Historical canonical fingerprints are unavailable because no historical curated CSVs were found.

| Table | Historical rows | Staged rows | Approved key duplicate groups / extra rows | Null counts in staged CSV | Staged canonical fingerprint |
|---|---:|---:|---:|---|---|
| dim_store | 20 | 20 | 0 / 0 | none | `969415dc817319fd8d81f2d47a44f5b48897f2429de5a1f0136e8b8900b616c8` |
| dim_product | 601 | 601 | 0 / 0 | list_price 1; unit_cost 1; launch_date 1; discontinued_date 577 | `2af2444bc36adba9f177f166a9e5259a67f51678b74309f33ef53bbc2989776d` |
| dim_date | 731 | 731 | 0 / 0 | holiday_name 711 | `aaed679d23cd2358b4263e4e920a20bb11027d51ace5ae7bd301f4aa7d24c561` |
| fact_sales | 1,339,510 | 1,339,510 | 0 / 0 | promotion_id 1,077,994; dq_rules 1,308,464 | `404af824ceb9736d3e8b8bda804a6a0a5c05fea94829201d03cffced519db4ac` |
| fact_inventory | 939,249 | 939,249 | 0 / 0 | dq_rules 937,839 | `ec89cb9a55eeae87b2e803065783089a7325218760ddb6644f8587a34b687943` |
| fact_returns | 34,562 | 34,562 | 0 / 0 | original_transaction_id 1,049; original_line_number 1,049; dq_rules 34,418 | `dc8b094c70b1dff77e4c6314b5e9765402128837b6f2110e9a6296f412ccf645` |
| fact_promotions | 49,430 | 49,430 | 0 / 0 | none | `975c388c3eccaed918e8b8bda804b6e3d2e0c960bc844e8e96d2099fa18` |
| fact_targets | 2,077 | 2,077 | 0 / 0 | none | `c7e1f8e6884892429a0c91d3565c626643c4957ae3e86b89fc8ac2e71e115338` |

Historical and staged SHA-256 evidence, including the newline-normalized hash:

| Table | Historical SHA-256 | Staged SHA-256 | Staged SHA-256 after CRLF-to-LF only | Match |
|---|---|---|---|---|
| dim_store | `5b2aacd7d1b3d12890964edf61c6f56fc8952c6d4f3ea8f107857c900b77a1cf` | `55764c2c5b7725c165ffc4a43911f8e46f0780593bcfea180b468d1deeaadde5` | `5b2aacd7d1b3d12890964edf61c6f56fc8952c6d4f3ea8f107857c900b77a1cf` | Yes |
| dim_product | `be934d7735c669e30a5947a5a7d4f54615f156965f1e7c0c2029ab645c17551f` | `5b60c2e717f3fc9f24c2c1aa0df0d9760d400d00dfd1e6d58d8157ef3aef2605` | `be934d7735c669e30a5947a5a7d4f54615f156965f1e7c0c2029ab645c17551f` | Yes |
| dim_date | `9ea2455ab6daf1b9d0e4c8ad34d3edc273872f3bd0ebd6c8c661a87fd24576b4` | `6fbbe7273950ae4084b1f605b83ca232b610b012aedd896f95e656912f94861e` | `9ea2455ab6daf1b9d0e4c8ad34d3edc273872f3bd0ebd6c8c661a87fd24576b4` | Yes |
| fact_sales | `3b3e2f4382881ef2765f869583d06d58a3b4d6363a3d39baa9af049f7ce767bb` | `66191d809733a6a971954ca2d79a3565695c1c965c24f6f39429ea9d7b473a95` | `3b3e2f4382881ef2765f869583d06d58a3b4d6363a3d39baa9af049f7ce767bb` | Yes |
| fact_inventory | `9b78c9096d5f7eb9ca3a6859b8965b9238fcee2dabe51c0b320faf8df7455edb` | `04cf14a89a929ccb7921af066e9d17ada61621ccd5876e1a8e340b5299865374` | `9b78c9096d5f7eb9ca3a6859b8965b9238fcee2dabe51c0b320faf8df7455edb` | Yes |
| fact_returns | `efc8b4f1dcf8750df1330ea136b8e56c50ce61c5013764f54d80e52d2893b02f` | `7f7334d28f37ae63d6d1132cd600d38bcb14f2c2ca12a31ffa52620e231a2630` | `efc8b4f1dcf8750df1330ea136b8e56c50ce61c5013764f54d80e52d2893b02f` | Yes |
| fact_promotions | `20dd3e783dec853569fa5744b480c4835fc5e6e8792bc762bd1583326697ab7f` | `22b33fa1ae5ad7e86e2efd747b0577e975b4339aa290aed253706e51409f4bc8` | `20dd3e783dec853569fa5744b480c4835fc5e6e8792bc762bd1583326697ab7f` | Yes |
| fact_targets | `3d37b1b814e797e710b5dc1ebb986c6f3bc86ff3433200902420970f48a70050` | `aeeef8b8e1d60115025542ae52e1a946b8fca4469a7734cb478274dab63c0e87` | `3d37b1b814e797e710b5dc1ebb986c6f3bc86ff3433200902420970f48a70050` | Yes |

**Note:** These SHA values are copied from the existing Phase 3 lineage and the staged run metadata; the staged files themselves were not modified during fingerprinting.

## Schema, Keys, and Dtypes

Historical curated CSVs were absent, so historical physical schemas/dtypes cannot be directly inspected. The approved schema below comes from `config/dq_config.yaml`. Current CSV column order is reported exactly; the canonical fingerprint orders provenance columns first, then configured contract columns, then any extra columns alphabetically. Pandas inferred dtypes shown are from a 10,000-row sample of the staged CSV. The CSVs are physically text; the contract types are the semantic dtypes.

- **dim_store** — key `store_id`; columns: `source_file, source_row, store_id, store_name, town, county, region, store_format, floor_area_m2, open_date, manager_name, headcount_fte, weekly_trading_hours, latitude, longitude`. Contract: provenance string/integer; IDs and labels string; `floor_area_m2`, `weekly_trading_hours` integer; `open_date` date; `headcount_fte`, `latitude`, `longitude` decimal. Inferred sample: strings for text/date, `int64` for source row/floor area/trading hours, `float64` for decimal fields.
- **dim_product** — key `product_id`; columns: `source_file, source_row, product_id, product_name, category, subcategory, brand, supplier_id, supplier_name, list_price, unit_cost, launch_date, discontinued_date, status`. Contract: provenance string/integer; IDs and labels string; `list_price`, `unit_cost` decimal; launch/discontinued dates date. Inferred sample: strings for text/date, `int64` source row, `float64` prices/cost.
- **dim_date** — key `date_key`; columns: `source_file, source_row, date_key, date, day_of_week, day_name, is_weekend, calendar_month, month_name, calendar_quarter, calendar_year, retail_year, retail_week, retail_week_start, retail_half, is_bank_holiday, holiday_name, is_trading_day, same_day_last_year`. Contract: provenance string/integer; `date_key`, day/month/quarter/year/week values integer; date fields date; day/month/half/holiday labels string; flags boolean. Inferred sample: strings for dates/labels, `int64` for integer fields, `bool` for flags.
- **fact_sales** — key `(transaction_id, line_number)`; actual CSV columns: `transaction_id, line_number, transaction_date, transaction_time, store_id, product_id, category, quantity, unit_price, discount, revenue, unit_cost, cost, margin, promotion_id, extract_batch_id, extract_timestamp, extract_lag_days, is_late_arriving, is_imputed, dq_status, dq_rules, source_file, source_row`. Canonical fingerprint order moves `source_file, source_row` first, then the configured contract columns and alphabetical extras. Contract: IDs/category/status/rules/batch string; line number, quantity, source row and lag integer; transaction date date; transaction time time; extract timestamp datetime; financial fields decimal; late/imputed flags boolean. Inferred sample: string fields and date/time/timestamp strings, integer fields `int64`, financial fields `float64`, flags `bool`.
- **fact_inventory** — key `(store_id, product_id, snapshot_date)`; columns: `source_file, source_row, snapshot_date, retail_year, retail_week, store_id, product_id, opening_stock, received_qty, sold_qty, adjustment_qty, closing_stock, dq_rules, dq_status`. Contract: date date; year/week and stock quantities integer; IDs and DQ fields string. Inferred sample: strings for IDs/date/DQ, `int64` for row/year/week/stock.
- **fact_returns** — key `return_id`; columns: `source_file, source_row, return_id, return_date, store_id, original_transaction_id, original_line_number, product_id, return_quantity, refund_value, return_reason, restockable_flag, is_linked, dq_rules, dq_status`. Contract: IDs/reason/DQ string; dates date; line number/quantity integers; refund decimal; restockable/linked flags boolean. Inferred sample: strings for IDs/date/reason/DQ; `int64` source row/quantity; nullable original line number `float64`; refund `float64`; flags `bool`.
- **fact_promotions** — key `(promotion_id, product_id, store_id)`; columns: `source_file, source_row, promotion_id, promotion_name, promotion_type, product_id, store_id, start_date, end_date, discount_pct`. Contract: identifiers/labels string; start/end dates date; discount percentage decimal. Inferred sample: string fields/dates, `int64` provenance, `float64` percentage.
- **fact_targets** — key `(store_id, retail_year, retail_week)`; columns: `source_file, source_row, store_id, retail_year, retail_week, week_start_date, week_end_date, target_net_revenue, target_version, target_set_date`. Contract: identifiers/version string; year/week/source row integer; date fields date; target revenue decimal. Inferred sample: strings for labels/dates, `int64` numeric keys/source row, `float64` target.

All eight staged tables have zero duplicate groups and zero duplicate extra rows under their configured keys. Null counts above reflect the contract’s null tokens; they occur in nullable fields such as no-promotion IDs, no DQ rule, undated/unknown product attributes, and optional return linkage.

## Historical Archive Search

Searched central-directory names only in the available `Retail_Performance_Root_Cause_Analytics` and `RPRCA_phase2` through `RPRCA_phase9` archives, including the raw Phase 2 archive. None contains any of the eight `data/processed/curated/*.csv` files. Phase 3–9 archives contain `reports/phase3/lineage.json`; Phase 5–9 archives also contain the Phase 1–4 freeze manifest. No archived curated file was extracted or opened because none was listed.

## Environment and Byte Reproducibility

- **Current:** CPython 3.14.5 x64, pandas 3.0.6, DuckDB 1.5.6.
- **Historical Python:** Not recorded. `docs/01_business_requirements.md` says Python 3.11+; it does not identify the actual run version.
- **Historical pandas:** Not recorded. The Phase 9 `requirements.txt` specifies `pandas>=2.2`, not a pin. The Phase 3 lineage has no Python/pandas/dependency-version fields.
- **Current staged CSV format:** UTF-8, no BOM, comma delimiter, CRLF record terminators, final newline present, and zero quote characters in each curated file. The historical files were not present, but the exact historical hashes are reproduced after CRLF-to-LF normalization, proving delimiter, quoting, values, and all other bytes match the frozen payloads.
- **Historical report CSVs:** Approved report CSVs use LF. The staged report CSVs use CRLF. Their parsed tables match exactly; for the compared files, the size delta equals one byte per record terminator.
- **Serialization test:** For every curated file, only CRLF pairs were normalized to LF while hashing. Each normalized hash equals its historical frozen SHA-256. No columns, row values/order, quoting, numeric/date/null representations, or other bytes were changed by this check.

This rules out a content mismatch: the staged CSV payloads are byte-identical to the frozen historical payloads after line-ending normalization. It also rules out row-order, column-order, quoting, float, integer, datetime, null, or schema serialization changes as the cause of the frozen hash failures. The evidence identifies LF versus CRLF as the exact byte-level difference. It does not establish which historical Python/pandas version or OS produced LF; those were not recorded.

## Contract-Level Comparisons

Staged Phase 3 report tables were compared with the approved historical reports as parsed values and row order. Exact matches were found for profile tables/columns, DQ rule catalogue/results, row-level issue log, cleaning audit, KPI reconciliation, curated validation, POS-stock mismatch detail, completeness, batches, missing inventory weeks, low-volume days, missing targets, category mapping, SKU reference prices, and the data-quality rule report.

- 85 DQ rules: all compared rule rows checked/failed, revenue impact, evidence, and catalogue fields match.
- 21 KPI rows: `raw_as_reported`, `clean_main_only`, and `clean_complete` values match exactly.
- 53 curated validation checks: check names, statuses, and values match exactly (51 PASS, 2 WARN, 0 FAIL).
- Lineage summary: raw input file hashes/rows, quarantine counts, 85 rules evaluated, 46 rules with findings, 38,138 issue rows, DQ pass rate 39.47%, raw unchanged, 51 PASS/2 WARN, and POS-stock reconciliation values all match.
- Raw/current fact coverage in the staged output: date dimension spans 2024-01-01 through 2025-12-31 (731 unique dates); sales span the same dates. Staged fact_sales has 1,339,510 rows, 835,568 distinct transaction IDs, EUR 38,211,623.68 revenue, and 1,768,568 units. Returns total EUR 1,288,620.48 and 41,904 units. Inventory spans 2024-01-07 through 2025-12-28.
- Key uniqueness and referential integrity pass in all 51 curated validation checks. Row conservation passes for all eight tables. Quarantine counts match historical lineage: product 10, promotions 4, targets 2, sales 2,005, returns 171, inventory 188.

The report-level and frozen-contract evidence strongly supports analytical equivalence. Historical table bytes are unavailable, so no independently computed historical canonical fingerprint exists; the normalized SHA match nevertheless verifies every non-line-ending byte against the historical frozen hash.

## Conclusion and Options

**Root cause:** The staged outputs were serialized with CRLF line endings on Windows; the frozen historical hashes were computed over LF line endings. CRLF-to-LF normalization alone reproduces all eight frozen hashes exactly. This is a serialization/environment mismatch, not changed analytical content.

- **Option A — restore historical curated files:** unavailable; no candidate approved archive contains those files.
- **Option B — reproduce historical serialization:** recommended after approval. Make Phase 3 CSV output line terminators explicitly LF, rerun to staging, verify all eight frozen hashes, and only then let the approved Phase 4 hash gate run. Do not change lineage or expected hashes.
- **Option C — create a new governed freeze:** unnecessary based on the exact normalized-hash evidence; would require separate explicit approval and is not recommended here.

No source, configuration, staged CSV, lineage, manifest, or existing report was modified. This diagnostic is the only new file. **PHASE 4 READY: NO** until the Phase 3 runner itself emits the existing frozen hashes without post-processing; Phase 4 and later phases were not run.
