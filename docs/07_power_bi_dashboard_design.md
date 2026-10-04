# Phase 7: Power BI Executive Decision-Support Dashboard

| Item | Detail |
|---|---|
| Project | Retail Performance & Root-Cause Analytics System |
| Company | Brightwater Retail Ltd (fictional, synthetic data) |
| Author | Waleed Bin Umer |
| Version | 1.0 (awaiting Phase 7 sign-off) |
| Date | 28 September 2026 |
| Inputs | Phase 4 governed star schema (via `pbi.*` views), frozen Phase 5 and Phase 6 outputs |
| Code | `sql/powerbi/01_powerbi_views.sql`, `src/powerbi/`, `config/powerbi_config.yaml` |
| Build assets | `powerbi/` (DAX, TMDL script, Power Query, theme, model definition, Phase 6 tables, validation queries) |
| Outputs | `reports/phase7/` (validation report and checks, number register, measure and data dictionaries, mockups) |

---

## 0. What exists and what does not

This phase was built in a Linux workspace with no Power BI Desktop, so **no .pbix file was created or opened**. What exists is everything needed to build it, and every number was reconciled here:

| Asset | Where | Tested here? |
|---|---|---|
| Power BI source views `pbi.*` (T-SQL) | `sql/powerbi/01_powerbi_views.sql` | Yes, on the DuckDB rebuild of the Phase 4 model (same scripts, translated). Not run on SQL Server. |
| 92 DAX measures and 1 calculated column (readable listing) | `powerbi/dax/measures.dax` | Logic: yes, through a Python reference implementation reconciled to Phases 4 to 6. DAX text: static checks only. |
| TMDL script that creates the `Measures` table | `powerbi/dax/measures_tmdl.tmdl` | No (needs Desktop's TMDL view). |
| DAX validation queries with expected values | `powerbi/dax/validation_queries.dax` | No: you run them in Desktop. They are the proof that the DAX matches. |
| Power Query (M), one file per table, SQL Server and CSV routes | `powerbi/power_query/` | No. |
| Report theme | `powerbi/brightwater_theme.json` | No. |
| Phase 5/6 tables for the report | `powerbi/data/` (33 CSVs + manifest) | Yes: traced to frozen files by SHA-256. |
| Page mockups (7 pages) | `reports/phase7/mockups/` | Drawn from reconciled numbers; they are wireframes, not screenshots. |
| Number register (146 numbers) | `reports/phase7/dashboard_number_register.csv` | Yes: every number re-derived from its source by the tests. |

Section 13 lists the exact manual steps; section 14 the tests to run in Desktop.

## 1. Purpose and users

**Purpose.** Turn the validated Phase 1 to 6 work into a decision-support product: show what happened to H2 2025 net revenue, when and where, what drove it, how strong the evidence is for each explanation, what is still unknown and what management should investigate next. It must never present an association or a hypothesis as a proven cause.

**Users.**

| User | Uses the dashboard to | Main pages |
|---|---|---|
| CEO / MD, CFO | Understand the decline in about 60 seconds and what is proven | 1, 6, 7 |
| Commercial / Trading director | Categories, promotions, suppliers | 1, 3, 5 |
| Retail Operations director, area managers | Store performance, the S03 to S05 traffic loss | 2 |
| Supply Chain, Buying, Quality | Availability, supplier concentration, returns | 3, 4 |
| Finance / FP&A | Reconciliation, target performance, attribution | 1, 6 |

**The 60-second story (page 1).** Net revenue fell from €10.189M to €9.457M (−€731k, −7.18%). More than half of it is an estimated €397,778 excess decline in three Dublin stores, measured against matched control stores, after a sudden loss of receipts from mid-July; its cause is UNRESOLVED (an external or an unrecorded operational change are hypotheses). A quarter is a Home & Kitchen decline associated with deeper promotions, but the methods disagree. Electronics stock-outs are the only mechanism with root-cause evidence, and they are small. Page 6 grades every explanation; page 7 lists what to find out next.

## 2. Page architecture

The pages follow the management investigation: WHAT → WHEN → WHERE → WHAT DROVE IT → EVIDENCE → UNKNOWNS → NEXT.

| # | Page | Business question | Main visuals |
|---|---|---|---|
| 1 | Executive overview | What happened, when, and what drove it? | 9 KPI cards; weekly Net Revenue H2 2025 vs H2 2024; driver attribution waterfall with evidence colours; evidence legend; Phase 5 volume-vs-price bridge strip |
| 2 | Store & customer diagnostics | Where did customers stop coming, and is the cause known? | Cluster vs matched controls cards; weekly transactions YoY by store group; daily change-point chart; comparison table (cluster vs matched controls vs estate); "Cause not established" callout; data-required panel |
| 3 | Product, category & inventory | Did availability cost Electronics sales, and whose SKUs? | E&T KPI cards; weekly availability Voltix vs other suppliers; top affected SKUs; Voltix stock-out pattern table; lost-sales panel (gross, net, range); required wording |
| 4 | Returns & quality signals | Are 'Faulty' returns a product problem? | 'Faulty' change cards; change by reason; 'Faulty' rate by store; sale-cohort line; "recorded reason is not a verified defect" callout; investigation panel |
| 5 | Promotions & Home & Kitchen | Did the promotion programme cause the H&K decline? | H&K KPI cards (net revenue, units, ASP, gross margin, events, discount rate, promotion share); four methods shown separately with intervals; promotion frequency; sales response; margin and post-promotion panel; association statement |
| 6 | Root-cause evidence matrix | How strong is each explanation? | Matrix D01 to D08 with evidence level, strength bars, cause status, impact, what we know / do not know, data required |
| 7 | Management investigation | What should management find out next, and who owns it? | Priorities table: known, unknown, why it matters, data required, proposed owner |
| T1 | Tooltip: KPI definition | What does this KPI mean? | Measure description text, evidence tag |
| T2 | Tooltip: evidence | How was this figure produced? | Evidence level, method, confidence, data required for the hovered driver |
| D1 | Drill-through: store detail | What does one store look like? | Store KPIs vs PY, weekly trend, category split, returns by reason |
| D2 | Drill-through: SKU detail | What happened to one product? | Sales, availability, full-week stock-outs, returns by reason, promotion share |

Mockups: `reports/phase7/mockups/page1_executive_overview.png` to `page7_investigation.png`.

### Page detail (fields and measures)

**Page 1.**
- **KPI cards:** `[Net Revenue]` (subtitle `[Net Revenue PY]`), `[Net Revenue YoY %]`, `[Net Revenue YoY]`, `[Gross Margin]` with `[Gross Margin %]` and `[Gross Margin % PY]`, `[Gross Margin YoY]`, `[Transactions]`, `[Transactions YoY]` with `[Transactions YoY %]`, `[Returns Value]`, and `[Return Rate]` with `[Return Rate PY]`.
- **Page subtitle:** `[Headline Subtitle]`, which is dynamic.
- **Weekly trend:** a line chart with axis `Date[retail_week]` and values `[Net Revenue]` and `[Net Revenue PY]`, filtered to the selected period.
- **Waterfall:** category `p6_driver_attribution[waterfall_label]` (sort by `sort_order`), value `[Driver Amount]`. The native waterfall cannot hatch bars, so the evidence class is written into each label (for example "Store-cluster excess vs controls [ESTIMATE; cause UNRESOLVED]"); colours from `[Driver Evidence Colour]` repeat it and are never the only signal. Data labels show `[Driver Share of Decline]`. The caption is `[Phase 6 Scope Note]`, and the note "The €397,778 is an ESTIMATE of an observed change (vs matched controls); its cause is UNRESOLVED" sits under the title.
- **Bridge strip:** `p5_revenue_bridge` (transactions, UPT, ASP and returns effects).

**Page 2.**
- **Cards:** `[Transactions YoY %]` filtered to `Store[store_group] = "Investigated cluster"`, and the same measure for `"Matched control"`. `[Cluster Excess (P6)]` with the range from `p6_sensitivity_summary`. The DiD figure from `p6_cluster_did`, with the placebo p and its footnote: it is the smallest attainable p (680 placebo groups, cluster vs all other stores) and overstates significance because Phase 5 selected the stores for falling most.
- **Line chart:** `[Transactions YoY %]` by `Date[retail_week]`, legend `Store[store_group]`, with a filter excluding "Other store" and "Unknown".
- **Change-point chart:** `p6_cluster_onset_daily` (7-day mean in Power Query or DAX). Add a constant line on the onset date from `p6_cluster_onset`. Show the per-store onsets from `p6_cluster_onset_by_store` in a small table.
- **Comparison matrix:** rows are the measures (Net Revenue YoY %, Transactions YoY %, ATV, UPT, ASP, Availability, Promotion Share, Return Rate), using field parameters or one visual per measure. Columns are `Store[store_group]`, with the total as the estate.
- **Callout:** `[Cluster Cause Callout]`. **Data-required panel:** from `p6_investigations` (priority 1).

**Page 3.**
- **Page filter:** `Product[category] = "Electronics & Tech"`.
- **Cards:** `[Net Revenue]`, `[Net Revenue YoY]`, `[Units YoY %]`, `[Transactions YoY %]`, `[ASP]`, `[Availability]` with `[Availability PY]`, and `[Returns Value]`.
- **Availability chart:** `p6_et_weekly_timeline`.
- **Top SKUs:** a bar chart of `p6_et_sku_stockouts[lost_primary_change]` (Top N = 8), coloured by `supplier_name`, with `[High-Seller Share of Lost Sales (P6)]`, `[Top SKU Share of Lost Sales (P6)]` and `[Top 3 SKU Share of Lost Sales (P6)]` as captions.
- **Voltix table:** `[Stock-Out Episodes (P6)]` and `[Mean Episode Weeks (P6)]` by year, `[Full-Week Stock-Outs]` and `[Full-Week Stock-Outs PY]` with `Product[supplier_name] = "Voltix Distribution Ltd"`, and the supplier test from `p6_et_supplier_test`.
- **Lost-sales panel:** `[Lost Sales Gross (P6)]`, `[Lost Sales Net of Deferred Demand (P6)]`, and `[Lost Sales Range Low (P6)]` to `[Lost Sales Range High (P6)]`.
- **Wording box:** `[Voltix Wording]`.

**Page 4.**
- **Cards:** `[Returns Value YoY]`, `[Returns Value YoY %]` and `[Returns Value]` with `Returns[return_reason] = "Faulty"`.
- **Bar by reason:** `[Returns Value YoY]` by `Returns[return_reason]`.
- **Store bars:** `p6_faulty_by_store` (rate per 100, H2 2024 vs H2 2025; Phase 6 used units from the stock system, so it is imported rather than recomputed).
- **Cohort line:** `[Returned Units per 100 Sold (Sale Cohort)]` by `Date[calendar_month]`, legend `Date[calendar_year]`, with `Returns[return_reason] = "Faulty"`. This uses the inactive relationship through `USERELATIONSHIP`. Set the Period slicer's interaction with this visual to None and add a visual-level filter `Date[calendar_year]` in {2024, 2025}, so both years of sale months show.
- **Supplier and product tables:** `p6_faulty_by_supplier` and `p6_faulty_by_product`.
- **Investigation panel:** `p6_investigations` (priority 3).

**Page 5.**
- **Page filter:** `Product[category] = "Home & Kitchen"`.
- **Cards:** `[Net Revenue]`, `[Units YoY %]`, `[ASP]` and `[ASP PY]`, `[Gross Margin YoY]`, `[Promotion Events (P6)]`, `[Discount Rate]` and `[Discount Rate PY]`, and `[Promotion Share]` and `[Promotion Share PY]`.
- **Methods chart:** a bar chart of `[HK Method Effect Guarded]` by `p6_hk_methods[method_code]`, with error bars from `ci_low` and `ci_high`. **Totals are switched off, and the guarded measure returns blank at total level, so the four methods can never be summed.**
- **Frequency and sales:** `p6_hk_weekly` (coverage and discount depth in one chart, sales in another; never a dual axis).
- **Margin and post-promotion panel:** `p6_hk_methods` (M1 gross margin), and `[Post-Promotion Dip (P6)]` by year.
- **Statement:** `[Promotion Wording]`.

**Page 6.** A table visual on `p6_evidence_matrix`:
- **Columns:** driver, evidence_level (background colour from `[Evidence Colour]`, text always shown), evidence_strength (causal-evidence data bars 0 to 3), cause_status, `[Driver Impact (single driver)]`, what_we_know, what_we_do_not_know, additional_data_required. Word wrap on; row height auto.
- **Totals:** switched off. The rows overlap (D02 repeats D01, D04 is part of D03, D06 repeats D05), and the impact measure is blank at total level anyway.
- **Sort:** by `sort_order`.
- **Slicers:** evidence level and driver.
- **Tooltip:** T2.

**Page 7.** A table visual on `p6_investigations`: priority, topic, evidence_level, known, unknown, why_it_matters, `[Investigation Slice (single row)]`, data_required, proposed_owner and owner_note. Totals off (slices overlap).

## 3. Data model

A star schema in **Import mode**, sourced from the `pbi` views over the Phase 4 `dw` schema. The views add no business rule. They provide three conveniences:
- `transaction_key`, an integer surrogate of the receipt id;
- display labels;
- `is_full_week_stockout`, the Phase 5/6 definition.

| Table | Type | Rows | Source |
|---|---|---:|---|
| Date | dimension (day) | 732 | `pbi.dim_date` |
| Store | dimension | 21 | `pbi.dim_store`; `store_group` is a DAX calculated column (LOOKUPVALUE on `p6_store_groups`) |
| Product | dimension | 601 | `pbi.dim_product` |
| Promotion | dimension | 138 | `pbi.dim_promotion` |
| Sales | fact (receipt line) | 1,339,510 | `pbi.fact_sales` |
| Returns | fact (return line) | 34,562 | `pbi.fact_returns` |
| Inventory | fact (weekly snapshot) | 939,249 | `pbi.fact_inventory` |
| Targets | fact (store x week plan) | 2,077 | `pbi.fact_targets` |
| p6_* / p5_* (33 tables) | Phase 5/6 analytical, disconnected | 1 to 362 | `powerbi/data/*.csv` |

**Relationships.** All are many-to-one, single direction, dimension to fact (`powerbi/model_definition.json`):

```
Date[date_key]      1 ──< Sales[date_key]
Date[date_key]      1 ──< Returns[return_date_key]              (active)
Date[date_key]      1 ┄┄< Returns[original_sale_date_key]       (INACTIVE: sale-cohort analysis via USERELATIONSHIP)
Date[date_key]      1 ──< Inventory[snapshot_date_key]
Store[store_key]    1 ──< Sales, Returns, Inventory, Targets
Product[product_key] 1 ──< Sales, Returns, Inventory
Promotion[promotion_key] 1 ──< Sales
Targets: no relationship to Date (weekly grain); DAX maps Date[retail_week_key] with TREATAS.
p6_* / p5_*: no relationships (validated H2 2025 vs H2 2024 results; they must not react to slicers).
```

There are no bidirectional filters and no many-to-many relationships. `Date` is **not** marked as a date table: its unknown member (key −1) has no calendar date, which "Mark as date table" rejects, and no measure needs it because time intelligence uses `same_day_last_year_key` (retail weeks do not align with calendar dates). Sort `month_name` by `calendar_month`, `day_name` by `day_of_week` and `period_label` by `period_sort`, and hide every `*_key` column and every fact column that has a measure.

**The one calculated column.** `Store[store_group]` = LOOKUPVALUE on `p6_store_groups` ("Unknown" for key −1); DAX in `powerbi/dax/measures.dax`. It is a calculated column rather than a Power Query merge, because a query that reads a source and also references another query raises Power BI's Formula.Firewall error.

**Hierarchies (drill-down).**
- Location: `Store[region] > Store[store_label]`.
- Merchandise: `Product[category] > Product[subcategory] > Product[product_label]`.
- Calendar: `Date[retail_year] > Date[retail_half] > Date[retail_week_label] > Date[calendar_date]`.

## 4. DAX measure layer

There are 92 measures in 10 display folders. The full list, with descriptions and dependencies, is `reports/phase7/measure_dictionary.csv`; the DAX itself is `powerbi/dax/measures.dax`. The rules:

- **One definition per KPI, identical to the governed Phase 4 view.**
  - Net Revenue = Sales Revenue − Returns Value.
  - COGS = Cost of Sales − Restock Cost Credit.
  - Gross Margin = Net Revenue − COGS.
  - Every ratio is a `DIVIDE` of summed components, never an average of ratios.
  - Nothing is redefined.
- **Transactions** = `DISTINCTCOUNT(Sales[transaction_key])`. With a category filter this is "transactions containing the category", exactly as Phase 4/5 define it (not additive across categories).
- **Prior year** uses the same days 364 days earlier, so retail weeks align:

  ```
  Net Revenue PY =
  VAR _pyDates = VALUES ( 'Date'[same_day_last_year_key] )
  RETURN CALCULATE ( [Net Revenue], REMOVEFILTERS ( 'Date' ), TREATAS ( _pyDates, 'Date'[date_key] ) )
  ```

  `SAMEPERIODLASTYEAR` would compare calendar dates and misalign retail weeks, which is why it is not used.
- **Returns by sale cohort** use `USERELATIONSHIP ( Returns[original_sale_date_key], 'Date'[date_key] )`.
- **Target Achievement %** follows the Phase 5 definition: net revenue and target over the store-weeks that have a target (`[Net Revenue (Target Weeks)]`). Weeks without a target are excluded from both sides.
- **Guards (blank, never a wrong number).** Returns, stock and targets have no promotion key, so `Returns Value`, `Net Revenue`, `COGS`, availability and stock-out measures return blank when the Promotion table is filtered (use `Sales Revenue` and `Promotion Revenue` with the promotion slicer). Targets are set per store, so the target measures return blank under a Product or Promotion filter.
- **Phase 6 measures** read the imported tables and never recompute an estimate.
  - `[HK Method Effect Guarded]` returns blank at total level, so the four promotion methods cannot be combined.
  - `[Lost Sales Net of Deferred Demand (P6)]` reads the Phase 6 sensitivity variant.
- **Labels:**
  - `[Headline Subtitle]` builds the dynamic subtitle.
  - `[Cluster Cause Callout]`, `[Voltix Wording]` and `[Promotion Wording]` hold the required wording, so it cannot drift between pages.
- **QA measures** (`0 Validation` folder) evaluate the headline in a fixed context, and `[QA Attribution Check]` compares the imported attribution with the model's own H2 change.

**SQL vs DAX split (no duplicated logic).** SQL provides additive columns and conformed keys; DAX does every aggregation and ratio; Python did the statistics (Phase 6), which Power BI imports as results.

## 5. Filter behaviour

| Filter | Affects | Does not affect |
|---|---|---|
| Period (`Date[period_label]`, default H2 2025) | all DAX measures; PY measures shift by 364 days | Phase 6 tables (fixed to H2 2025 vs H2 2024) |
| Region, Store format, Store, Store group | Sales, Returns, Inventory, Targets | Phase 6 tables |
| Category, Subcategory, Product, Supplier | Sales, Returns, Inventory | Phase 6 tables; target measures return blank (targets are per store) |
| Promotion | Sales only | returns, stock and target measures return blank (no promotion key), so Net Revenue is blank too |
| Return reason (`Returns[return_reason]`) | Returns measures | Sales measures |

**Guard rails.**
- Every visual built on a Phase 6 table carries the caption `[Phase 6 Scope Note]` ("Validated Phase 6 result for H2 2025 vs H2 2024. Not affected by slicers.").
- Use **Edit interactions** to set slicers to "None" on those visuals, so the behaviour is explicit.
- Slicers sync across pages 1 to 5 (Period, Region, Store format, Store) through the Sync slicers pane. Category and Supplier are page-level on pages 3 to 5.
- Seven slicers at most per page; filters sit in one row under the title.

## 6. Drill-through and drill-down

- **Drill-down:** the Location and Merchandise hierarchies on the page 2 comparison and the page 3 and 4 charts give Estate → Region → Store and Category → Subcategory → Product.
- **Drill-through D1 (store detail):** the drill-through field is `Store[store_label]`; "Keep all filters" is on. Reachable from any store visual.
- **Drill-through D2 (SKU detail):** the drill-through field is `Product[product_label]`. Reachable from any product or SKU visual, including page 3's top-SKU chart. That chart uses Phase 6's `product_id`; add `Product[product_label]` through a relationship-free lookup (`LOOKUPVALUE`) or drill from a DAX-based top-N visual.
- **Back buttons** on D1 and D2.

## 7. Tooltip logic

- **T1, KPI definition tooltip:** a report page tooltip (320 x 240) assigned to every KPI card. It shows the measure's plain-English definition (the text from `measure_dictionary.csv`, stored in a small disconnected table `kpi_definitions` or typed into the tooltip page), the value, the PY value and the evidence tag (FACT for every model measure).
- **T2, evidence tooltip:** assigned to the page 1 waterfall and the page 6 matrix. It shows evidence_level, cause_status, method, confidence and additional_data_required for the hovered driver, so anyone hovering sees *how* a figure was produced.
- Default tooltips stay on for the charts (value and category), with measure names written in business language.

## 8. Evidence framework on the dashboard

The Phase 6 classes are carried unchanged. Evidence levels are copied from `root_cause_evidence_matrix.csv` at build time, and a check fails if they ever differ.

| Label | Meaning | Visual treatment |
|---|---|---|
| FACT | measured in the governed data | KPI cards; solid bars |
| ESTIMATE | model or counterfactual figure with a range | hatched bars; ranges shown |
| STATISTICAL ASSOCIATION | things move together; not proof | amber, causal-evidence 2 of 3 |
| HYPOTHESIS | plausible, cannot be tested with this data | grey, causal-evidence 0 of 3 |
| UNRESOLVED | size known, cause unknown | dark grey "Unresolved" cause tag; callout on page 2 |
| Root-cause evidence | mechanism visible, quantified, robust | aqua, causal-evidence 3 of 3 (D03 only) |
| Observed change | measured change, no cause claimed | blue, causal-evidence 1 of 3 |

**Rules.**
- A colour is never used without its text label.
- Weak evidence never shares the colour or bar length of strong evidence.
- The required wording is stored in measures, so it is the same everywhere.
- The €397,778 cluster decline is labelled "Observed and quantified; underlying cause UNRESOLVED" wherever it appears, and its figure is tagged ESTIMATE (a DiD counterfactual).
- The causal-evidence bars rank how far a driver's CAUSE is established: an Observed change is a certain measurement but claims no cause, so it scores below a tested association.
- The residual is a remainder of estimates, not a measurement, and is shown in light grey as "not attributed".

## 9. Design decisions

- **Palette.** Blue for current and observed, grey for the prior year and hypotheses, aqua for root-cause evidence, amber for associations, red for adverse movement only. This is the Phase 6 palette, validated for colour-vision deficiency.
- **Typography.** Segoe UI (the Power BI default): 28 pt callouts, 12 pt titles, 10 pt labels.
- **Axes and chart types.** No dual axes (frequency and sales are separate charts). No gauges, pies or 3D. Axes start at zero except availability, which is labelled.
- **Titles.** Titles are questions or conclusions ("What drove the decline"). Subtitles state the source and the evidence class.
- **Estimates.** Estimates always show their range, and "not quantified" is shown instead of an invented number (D08).
- **Visual count.** Each page has 8 to 12 visuals, the level Power BI guidance recommends for performance and readability.
- **Page size.** 16:9 at 1280 x 720, readable on a 14" laptop at 100% zoom.

## 10. Performance considerations

- **Import mode** with a star schema and single-direction relationships.
- **Integer keys.** Integers everywhere, including `transaction_key`, which replaces the text receipt id: 835,568 distinct values. It is a `DENSE_RANK` computed in the view at every refresh: correct for full refresh (the count of receipts is unchanged), but not for incremental refresh, where partitions would rank separately. In production, persist an integer receipt key in `dw.fact_sales` instead (section 16). The gain over a text key is modest, because VertiPaq dictionary-encodes text as well.
- **Cardinality.** The largest columns are `Sales[sales_line_id]` (1.34M distinct) and `Returns[return_id]`. They are only needed for drill-to-detail. Remove them in Power Query if the model must be smaller; no measure uses them.
- **Money columns** are Fixed Decimal (`Currency.Type`), so sums are exact to the cent.
- **Measures instead of calculated columns.** Labels and `is_full_week_stockout` are created upstream in the `pbi` views. The only DAX calculated column is `Store[store_group]`, on a 21-row table, so its cost is negligible.
- **`Net Revenue (Target Weeks)`** iterates store-week target pairs (about 520 per half-year). It is used only by target visuals.
- **`DISTINCTCOUNT` on 1.34M rows** is the most expensive measure. It is used on cards and weekly charts only, never in a large table by line.
- **Performance Analyzer was not run** (no Desktop). Section 14 gives the procedure and the thresholds to record. `reports/phase7/model_profile.csv` lists rows and cardinality per column.

## 11. Validation

`python -m src.powerbi.run_phase7 --engine duckdb` runs the following. The results are in `reports/phase7/phase7_validation_report.md`: 102 of 102 checks pass.

1. The Phase 1 to 6 freeze: 170 files, plus a re-verification of the Phase 6 manifest.
2. The headline against the brief, Phase 4, Phase 5 and Phase 6: H2 2024 €10,188,727.55; H2 2025 €9,457,457.05; change −€731,270.50; YoY −7.177251%.
3. Every Phase 5 headline KPI in both periods, the 26 weekly H2 values, 20 stores × 8 KPIs × 2 periods, 7 categories × 11 KPIs × 2 periods, and estate target achievement. All reconcile exactly.
4. Phase 6 figures the measures reproduce:
   - Electronics revenue change and availability;
   - Voltix full-week stock-outs (674 vs 0);
   - cluster and control transactions per store (−27.8%, −1.1%);
   - 'Faulty' and other return reasons;
   - the 24-month sale-cohort rate;
   - H&K discount rate (2.4% to 11.9%).
5. Attribution:
   - the components sum to the H2 change;
   - the shares sum to 100%;
   - each component matches the brief.
6. Evidence:
   - levels are identical to Phase 6;
   - "Established" appears only for Root-cause evidence;
   - "Unresolved" matches the Phase 6 conclusions;
   - no association or hypothesis is shown as a cause.
7. The four H&K methods are kept separate and disagree in sign.
8. Extract traceability: SHA-256 of each source file.
9. DAX static checks: references exist, columns exist, parentheses balance, no cycles, descriptions are present.
10. Guards: under a Promotion filter, returns, net revenue, margin and availability are blank while Sales Revenue still answers; under a category filter, Target Achievement is blank.

`tests/test_phase7_powerbi.py` repeats these checks and re-derives all 146 register numbers.

## 12. Limitations

- **No .pbix was built.** The DAX, TMDL and M files were not executed. The report layout, interactions, drill-through, tooltips and Performance Analyzer need Power BI Desktop (sections 13 and 14).
- **The DAX logic was validated through a Python reference, not the VertiPaq engine.** `validation_queries.dax` closes that gap once it is run in Desktop.
- **The `pbi` views were executed on DuckDB, not SQL Server.** They use only T-SQL that sqlglot translates, but they should be created and checked on SQL Server (step 1).
- **Phase 6 tables are static.** They describe H2 2025 vs H2 2024 and do not react to slicers. A different period needs a rerun of Phase 6, which the design makes explicit.
- **Proposed owners on page 7 are suggestions** for management to confirm, not findings.
- **The data is synthetic.**

## 13. Manual build steps in Power BI Desktop

1. **SQL Server route (recommended).**
   - Build the Phase 4 model (`python -m src.sql_model.run_model`).
   - Run `sql/powerbi/01_powerbi_views.sql` in SSMS against `BrightwaterRetail`. It creates schema `pbi` and 8 views.
   - Check it with `SELECT COUNT(*) FROM pbi.fact_sales` (expected 1,339,510).
2. **CSV route (no SQL Server).** Run `python -m src.powerbi.run_phase7 --engine duckdb --extract`. It writes the 8 star-schema CSVs to `data/powerbi/`.
3. **Create a new report and set it up.**
   - Open Power BI Desktop and create a new report.
   - File > Options > Current file > Regional settings: English (Ireland). Data load: turn off "Auto date/time" and turn off relationship auto-detection.
   - View > Themes > Browse for themes: `powerbi/brightwater_theme.json`.
4. **Parameters** (Home > Transform data > Manage parameters > New), all of type Text: `ServerName` (localhost), `DatabaseName` (BrightwaterRetail), `ModelFolder` (full path of `data\powerbi`, CSV route only) and `AnalyticsFolder` (full path of `powerbi\data`).
5. **Queries.**
   - For each file in `powerbi/power_query/`, go to Home > New source > Blank query > Advanced editor, paste the file's contents and name the query after the file.
   - Use `Store.sql_server.pq` or `Store.csv.pq` (not both) for each of the 8 star tables.
   - Load all 33 `p6_*` / `p5_*` queries.
   - File > Options > Current file > Privacy: if Power BI asks, set both sources (SQL Server and the folder) to Organizational.
   - Close & Apply.
6. **Relationships** (Model view): create exactly the 12 in `powerbi/model_definition.json`. All are many-to-one and single direction. Make `Returns[original_sale_date_key]` inactive. Delete any auto-detected relationship to a `p6_*` table.
7. **Model settings:**
   - Do not mark `Date` as a date table (section 3).
   - Create the calculated column `Store[store_group]` (DAX at the top of `powerbi/dax/measures.dax`).
   - Set the sort-by columns (section 3).
   - Hide the key columns.
   - Create the three hierarchies.
   - Set money columns to Fixed decimal (the M files already do this).
8. **Measures.**
   - View > TMDL view > New script, paste `powerbi/dax/measures_tmdl.tmdl`, and Apply. This creates the `Measures` table with all 92 measures in folders.
   - If the TMDL view rejects the script (not tested here), create a table with Home > Enter data (name `Measures`) and add each measure from `powerbi/dax/measures.dax`. Tabular Editor's "Import DAX" works too.
9. **Validate before building visuals.** View > DAX query view: paste `powerbi/dax/validation_queries.dax` and run it. **Every row must say PASS**, and `[QA Attribution Check]` must say PASS. Stop and fix if not.
10. **Build pages 1 to 7** following the mockups and section 2. Then build tooltips T1 and T2 (Page information > Allow use as tooltip; canvas type Tooltip) and drill-through pages D1 and D2 (drill-through field as in section 6).
11. **Set interactions:**
    - Edit interactions: slicers have no effect on `p6_*` visuals.
    - Sync slicers across pages 1 to 5.
    - Turn off totals on the methods chart and on the page 6 and page 7 tables.
12. **Save** as `powerbi/Brightwater_Executive_Dashboard.pbix`. Optionally, also save as a Power BI Project (`.pbip`) for version control.

## 14. Tests to run in Power BI Desktop

| # | Test | Pass condition |
|---|---|---|
| 1 | `validation_queries.dax` | 55 of 55 rows PASS (including the Phase 6 table loads and the blank-guard cases); QA Attribution Check = PASS |
| 2 | Headline cards (Period = H2 2025, no other filter) | Net Revenue €9,457,457.05; PY €10,188,727.55; YoY −€731,270.50 and −7.18% (register P1-01 to P1-04) |
| 3 | Store filter: Store = S03 | `[Net Revenue YoY]` = −€171,317.05 (Phase 5 store_contribution) |
| 4 | Store group = Investigated cluster | `[Transactions YoY %]` = −27.76%; Matched control −1.11% |
| 5 | Category = Electronics & Tech | Net Revenue YoY −€268,518.33; Availability 89.3% vs 95.4% |
| 6 | Supplier = Voltix | Full-Week Stock-Outs 674; PY 0 |
| 7 | Return reason = Faulty, category E&T | Returns Value YoY +€31,588.73 |
| 8 | Phase 6 visuals with slicers changed | values do not change; the scope caption is visible |
| 9 | Methods chart total | blank (the four methods are never summed) |
| 10 | Drill-down Estate → Region → Store; Category → Subcategory → Product | totals at each level add up to the parent |
| 11 | Drill-through from S03 and from P00149 | D1 and D2 open filtered; the back button returns |
| 12 | Tooltips | T1 on KPI cards shows the definition; T2 on the waterfall shows the evidence level and method |
| 13 | Performance Analyzer (View > Performance analyzer > Start recording > Refresh visuals) on each page | record the DAX query ms per visual; target < 500 ms per visual and < 3 s per page on a laptop; export the JSON to `reports/phase7/performance_analyzer/` |
| 14 | Accessibility | View > Accessibility; tab order set; alt text on every visual; colour never the only signal (every evidence colour has a text label); contrast of text ≥ 4.5:1 (ink on white) |
| 15 | Laptop readability | 1366 x 768 and 1920 x 1080 at 100% zoom: no truncated titles, cards readable |

## 15. Interview readiness

**What business problem did this dashboard solve?** A retailer's H2 net revenue fell 7.2% (€731k) and management needed to know why, where and what to do. Most dashboards show that revenue fell. This one separates what is proven from what is only associated, so the business does not spend money fixing the wrong cause.

**What did you discover?**
- **Store cluster:** more than half the decline is an estimated €397,778 excess fall in three Dublin stores, measured against matched control stores, after a sudden loss of receipts from mid-July. Prices, promotions, stock and returns there moved like the controls, so nothing in the internal data explains it. An external change (competitor, access works, local events) or an unrecorded operational change are hypotheses, and the cause is unresolved until footfall and store-operations data are checked.
- **Home & Kitchen:** a quarter (€186k) is a Home & Kitchen decline that coincides with much deeper, more frequent promotions (discount rate 2.4% to 11.9%). But two of four analytical methods say the promotions helped, so causality is not established.
- **Electronics stock-outs:** these are the only mechanism with root-cause evidence (about €24k to €44k), concentrated on one supplier's SKUs.
- **'Faulty' returns:** these rose 90%, concentrated in five stores and in products sold from September onward. That is a signal, not a proven defect.

**How did you investigate the revenue decline?**
1. Reconcile the headline to the cent.
2. Decompose it into volume and price (Shapley bridge).
3. Locate it by store and category.
4. Test each candidate with the right method:
   - difference-in-differences against matched control stores with a placebo test;
   - lost-sales baselines for stock-outs;
   - supplier comparisons with bootstrap and permutation tests;
   - four counterfactual methods for promotions.
5. Remove double counting with an exclusive attribution.
6. Stress-test everything with 83 sensitivity variants.

**How did SQL, Python and Power BI work together?**
- **SQL Server:** holds the governed star schema and KPI definitions (one place for Net Revenue, COGS and so on), and exposes clean `pbi` views.
- **Python:** did data quality, reconciliation and the statistics Power BI cannot do (DiD, change points, sensitivity), then exported validated result tables.
- **Power BI:** imports both. DAX recomputes the governed KPIs interactively, and the Phase 6 tables supply the estimates with their evidence labels.

**How did you prevent correlation from being presented as causation?**
- Every figure carries a FACT, ESTIMATE, STATISTICAL ASSOCIATION or HYPOTHESIS tag, and every cause carries a status (Established, Not established, Unresolved).
- Evidence levels come straight from the Phase 6 matrix, and a test fails if the dashboard ever shows an association as a cause.
- The promotion methods are never summed.
- The required wording lives in measures, so it cannot drift.

**How did you validate the numbers?** Everything is checked against the three earlier phases: 102 automated reconciliation checks (headline, weekly, 20 stores, 7 categories, Phase 6 figures, attribution), a register tracing all 146 numbers on the dashboard to a source, SHA-256 freezes of all earlier outputs, and a set of DAX queries with expected values to prove the Power BI engine matches.

**What would management investigate next?**
- **Retail Operations / Commercial:** footfall and competitor data for the three stores.
- **Supply Chain:** purchase orders and ASNs for Voltix SKUs.
- **Quality / Buying:** QA, batch and RMA data for 'Faulty' returns.
- **Commercial / Marketing:** a holdout test for Home & Kitchen promotions.

These are investigation priorities, not actions.

**How would this solution operate in a real retailer?** See section 16. The pipeline would refresh nightly from source systems into the warehouse, data-quality checks would gate the load, the semantic model would refresh on a schedule in the Power BI Service with row-level security by region, and the root-cause analysis would rerun each period with the same freeze and reconciliation discipline.

## 16. Real-world architecture

```
POS / till systems ─┐
Inventory / stock ──┤
Returns system ─────┤     nightly extract (CDC or batch)
Promotion system ───┼──────────────────────────────────►  Staging (SQL Server / Azure SQL / Fabric warehouse)
Product master ─────┤                                            │  data-quality rules (Phase 3), quarantine, audit
Supplier / ERP ─────┘                                            ▼
                                                     Governed star schema + KPI views (Phase 4: dw, mart, pbi)
                                                                 │
                                   ┌─────────────────────────────┴─────────────────────────────┐
                                   ▼                                                           ▼
                     Python root-cause analytics (Phase 5-6)                  Power BI semantic model (Import,
                     scheduled per period; writes result tables               scheduled refresh via gateway,
                     back to the warehouse with run id + evidence level        RLS by region / store)
                                   └─────────────────────────────┬─────────────────────────────┘
                                                                 ▼
                       Executive / Commercial / Store Operations dashboards (Power BI Service app)
```

In production:
- **Automated refresh.** CSV files and manual runs are replaced by scheduled pipelines (SQL Agent, Azure Data Factory or Fabric Data Pipelines). The Power BI dataset refreshes through an on-premises gateway (or directly from the cloud warehouse) after the load succeeds.
- **Results in the warehouse.** Phase 6 outputs become warehouse tables keyed by analysis run, so Power BI reads them from SQL rather than CSV. The dashboard shows the run date and the period analysed.
- **Gated publishing.** Data-quality and reconciliation checks run before publishing. A failed reconciliation blocks the refresh and alerts the BI team.
- **Access and governance.**
  - Row-level security limits store managers to their region.
  - Certified datasets and deployment pipelines (dev, test, prod) with the .pbip project in Git give version control and review.
  - Refresh history and Performance Analyzer baselines are monitored.

## 17. Reproducibility

```
python -m src.powerbi.run_phase7 --engine duckdb            # about 45 s: freeze, model, extracts, checks, assets, mockups
python -m src.powerbi.run_phase7 --engine duckdb --extract  # also writes data/powerbi/*.csv (CSV route)
python -m src.powerbi.run_phase7                            # against the SQL Server model
python -m pytest tests/test_phase7_powerbi.py
```

## 18. Suggested Phase 8

Phase 8 has not been started. A natural next phase, subject to approval, is forecasting and anomaly detection:
- an H1 2026 net revenue baseline with prediction intervals by store and category;
- an automated weekly early-warning check (for example, a change-point monitor on store transactions, reusing the Phase 6 method) that flags a new S03-to-S05-type step within two to three weeks instead of at half-year.

Its results would feed a forecast page on this dashboard, tagged as ESTIMATE.
