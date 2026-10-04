# Phase 5: Exploratory Business Analysis and Diagnostic Analytics

| Item | Detail |
|---|---|
| Project | Retail Performance & Root-Cause Analytics System |
| Company | Brightwater Retail Ltd (fictional, synthetic data) |
| Author | Waleed Bin Umer |
| Version | 1.0 (awaiting Phase 5 sign-off) |
| Date | 28 September 2026 |
| Inputs | Phase 4 governed model only (built from the frozen Phase 3 curated data), Phase 4 reconciliation results |
| Code | `src/analytics/`, `sql/analysis/diagnostics/01-09`, `config/analytics_config.yaml` |
| Outputs | `reports/phase5/` (tables, figures, executive summary, validation report, run log) |

---

## 1. Objective

This is the first analyst-led investigation of the H2 2025 net revenue decline. It answers three questions: **what changed, where did it change, and which areas deserve deeper root-cause investigation?** Every material finding gets exactly one BRD evidence level (section 9).

Phase 5 is deliberately blind to how the data was generated. It reads only business-visible, governed data and approved KPI definitions. It does not start from an assumed explanation: the diagnostics run on every area (traffic, basket, stores, categories, returns, availability, promotions, targets, range, data coverage) and the evidence rules decide which signals survive.

Phase 5 does **not** produce the final root-cause conclusion, Power BI, forecasts, anomaly detection, a GenAI layer or recommendations. It hands Phase 6 a quantified, evidence-graded shortlist.

## 2. Analytical approach

```
Freeze check (Phase 1-4 input manifest, SHA-256)
   -> Phase 4 model (DuckDB: rebuilt and reconciled by the Phase 4 runner; SQL Server: read, reconciliation must PASS)
   -> diag.* views (sql/analysis/diagnostics/01-09, T-SQL, read only mart.* and dw.*)
   -> headline recomputed and reconciled to Phase 4  (STOP on any difference above tolerance)
   -> Python diagnostics (src/analytics): contribution, Shapley bridge, returns, lost sales, promotions, targets
   -> SQL vs Python cross-checks (64 checks) -> evidence shortlist -> figures -> executive summary
```

The analysis goes from the whole to the parts. First the size and timing of the decline. Then the identity bridge (is it traffic, basket or returns?). Then where it happened: stores, regions and formats first, categories and products second. Last, the candidate mechanisms: availability, promotions and returns. Each step is checked against the one before it. For example, the store cluster is tested for availability changes before availability is offered as an explanation.

Two layers compute the same numbers independently wherever they overlap. The SQL views compute contributions, Shapley effects, rankings and target streaks, and Python recomputes them from the additive components. The validation report shows every difference.

## 3. Comparison periods

| Item | Definition |
|---|---|
| Current period | H2 2025: retail weeks 27 to 52 of retail year 2025 (30 Jun to 28 Dec 2025) |
| Prior period | H2 2024: retail weeks 27 to 52 of retail year 2024 (1 Jul to 29 Dec 2024) |
| Alignment | Week-aligned (BRD sign-off item 2): each week is compared with the same retail week number a year earlier, 364 days apart, same weekdays |
| Source of truth | `config/project_config.yaml` (comparison) |

Six automated checks confirm the alignment: 26 weeks, weeks 27 to 52, 7 days each, prior-year week = same week number, same weekday, 364 days apart. The partial retail week 2026-W01 (29 to 31 Dec 2025) falls outside both periods.

## 4. Input objects

| Layer | Objects |
|---|---|
| Phase 4 governed views | `mart.v_performance_store_day` (atomic base), `mart.v_performance_store_week`, `mart.v_performance_category_week`, `mart.v_availability_store_week`, `mart.v_availability_category_week`, `mart.v_yoy_store_week` |
| Phase 4 star schema | `dw.fact_sales`, `dw.fact_returns`, `dw.fact_inventory`, `dw.fact_promotion_coverage`, `dw.dim_date`, `dw.dim_retail_week`, `dw.dim_store`, `dw.dim_product`, `dw.dim_promotion` |
| Benchmark | `reports/phase4/reconciliation_results_{engine}.csv` (H2 net revenue and YoY) |
| Not used | staging (`stg.*`), `recon.*`, raw files, quarantine, sample data, and every evaluation-only asset (section 12) |

Diagnostic views created by Phase 5 (schema `diag`):

| Script | Views |
|---|---|
| 01 headline trend | `v_estate_week`, `v_h2_week_comparison`, `v_h2_headline`, `v_h2_headline_from_facts` (independent path from the facts), `v_store_week_coverage` |
| 02 store contribution | `v_store_h2_components`, `v_segment_h2_components`, `v_segment_h2_contribution`, `v_store_h2_contribution` |
| 03 region / format | `v_segment_h2_breadth`, `v_region_format_h2` |
| 04 category | `v_category_h2_components`, `v_category_h2_contribution`, `v_product_h2_components` |
| 05 basket | `v_basket_bridge_segment`, `v_basket_bridge_category`, `v_basket_week` |
| 06 returns | `v_returns_h2_store_category`, `v_returns_h2_reason`, `v_returns_h2_attributes` |
| 07 availability | `v_promo_cover_week`, `v_stock_cell_week`, `v_availability_h2_store_category`, `v_availability_week`, `v_availability_h2_supplier` |
| 08 promotions | `v_promo_h2_lines`, `v_promo_h2_scope`, `v_promo_event_week` |
| 09 targets | `v_target_store_week`, `v_target_store_h2` |

The scripts are T-SQL (`CREATE OR ALTER VIEW`). They run unchanged on SQL Server 2022, and through the Phase 4 sqlglot translation layer on DuckDB. Views contain no `ORDER BY` except inside window functions.

## 5. KPI definitions used

All KPIs are the BRD / Phase 4 governed definitions (`mart.kpi_definition`). Ratios are computed from summed components, never averaged.

| KPI | Definition |
|---|---|
| Sales Revenue | Gross Sales - Discount Value |
| Net Revenue | Sales Revenue - Returns Value (returns on the return date at the returning store) |
| Gross Margin, GM % | Net Revenue - COGS; GM / Net Revenue |
| Transactions | Distinct receipts (additive across stores and days, not across categories) |
| AOV, UPT, ASP | Sales Revenue / Transactions; Units / Transactions; Sales Revenue / Units |
| Return Rate % (value / units) | Returns Value / Sales Revenue; Returned units / Units sold |
| Stock Availability %, Stock-out Rate % | In-stock ranged store-SKU-weeks / ranged store-SKU-weeks; 1 - availability |
| Promo Revenue Share %, Promo Discount Cost | Promoted-line Sales Revenue / Sales Revenue; discount on promoted lines |
| Contribution (pp) | Segment EUR change / estate prior-period Net Revenue x 100 (adds up to the estate YoY %) |
| Share of decline | Segment EUR change / estate EUR change (adds up to 100%) |
| Category incidence | Receipts containing the category / all receipts |
| Target Achievement %, Variance, Miss Streak | Net Revenue / Target; Net Revenue - Target; consecutive weeks below target |

Contribution ranks by EUR, not by YoY %. A small store falling 20% can move the estate less than a large store falling 5%. The store table carries both ranks.

## 6. Decomposition methodology

**Identity (BRD 5.1).** Sales Revenue = T x U x P, with T = transactions, U = units per transaction and P = average selling price. Net Revenue = Sales Revenue - Returns.

**Why Shapley.** A sequential decomposition (change T first, then U, then P) gives different answers depending on the order, and leaves an interaction term that has to be allocated arbitrarily. The Shapley value averages each factor's marginal effect over all 6 orders. For three multiplicative factors this has a closed form:

```
effect_T = dT x [ (U0 P0 + U1 P1) / 3 + (U0 P1 + U1 P0) / 6 ]
effect_U = dU x [ (T0 P0 + T1 P1) / 3 + (T0 P1 + T1 P0) / 6 ]
effect_P = dP x [ (T0 U0 + T1 U1) / 3 + (T0 U1 + T1 U0) / 6 ]
returns effect = -(Returns1 - Returns0)
```

The three effects add up exactly to the Sales Revenue change (Shapley efficiency), so the interaction/residual is zero. The bridge carries a residual row only to prove this, and it is tested to be below EUR 0.01 (actual: about 6e-10). The net revenue bridge must reconcile to the net revenue change within EUR 0.01. AOV is split the same way into UPT and ASP parts (two-factor Shapley).

**Segments.** The same formula runs per region, format, store and category, both in SQL (`diag.v_basket_bridge_*`) and in Python. Segment effects do **not** add up to the estate effects: the estate ASP and UPT also move when sales shift between stores or categories (mix). Only net revenue change is additive across segments. For categories, T is the number of receipts containing the category and U is units per such receipt.

**Not in the identity.** Availability and promotions are mechanisms, not factors of the identity. Forcing them in would double count, because a stock-out shows up as fewer transactions or units, and a discount shows up as a lower ASP. They are analysed separately (sections 7 and 8).

## 7. Availability and Estimated Lost Sales (BR-05)

**Measure.** Availability counts ranged store-SKU-weeks with closing stock > 0. A week with zero closing stock is a stock-out week, which includes weeks that sold out part-way through.

**Estimated Lost Sales: an ESTIMATE, never a measured value.** It is computed for every stock-out store-SKU-week in the compared H2 weeks of both years. The weekly snapshot shows three kinds of stock-out week:

| Kind | Snapshot | What it shows |
|---|---|---|
| Full week | Opening stock 0, nothing received | No stock at any point, so sales must be 0. The mechanism is directly visible. |
| Restocked | Opening stock 0, stock received in the week | Out for part of the week (length unknown) |
| Sold out | Opening stock > 0, closing stock 0 | Ran out part-way through; often a high-selling week |

Two figures are reported:

| Figure | Definition | Status |
|---|---|---|
| **Primary estimate** | Full-week stock-outs only: expected units x baseline price (actual sales are 0) | Root-cause evidence when the rule in section 9 passes. Conservative. |
| **Upper bound** | Every stock-out week: max(expected - actual, 0) x baseline price (the literal BR-05 formula) | Hypothesis only; see "Why the upper bound is not evidence" below |

How the expected sales are estimated:

| Step | Rule |
|---|---|
| Baseline weeks | The same store and SKU, in stock and not promoted (no promotion coverage day and no promoted unit), within +/-4 weeks of the stock-out week. The stock-out week itself is never used. |
| Minimum history | At least 3 baseline weeks. If +/-4 weeks gives fewer, the window widens to +/-8, then +/-13 (for long stock-outs). Otherwise there is no estimate, and the gap is counted. |
| Seasonality | Units are deseasonalised with a category x week index (estate mean units per eligible cell). Expected units = mean deseasonalised baseline units x the index of the stock-out week. |
| Promotions | Promoted weeks never enter the baseline. A promoted stock-out week is still estimated at the non-promoted rate, which is conservative (2,074 such cells). |
| Price | Non-promoted revenue / units over the same baseline weeks |
| Comparison | The change in estimated lost sales (H2 2025 minus H2 2024) is the estimated revenue effect of availability. The level is not the effect. |

**Validation.**

- **Back-test of the expected level.** On in-stock, non-promoted H2 weeks, where true sales are known, the estimator predicts 99.3% of actual units in aggregate (WAPE 12.5% at store x category x week). The primary estimate uses exactly this expected level.
- **Coverage.** 99.95% of stock-out weeks have a baseline.
- **Mechanism.** The 794 full-week stock-out cells sold exactly 0 units against 434 expected. Primary estimate: EUR 19 in H2 2024 and EUR 37,280 in H2 2025, almost all of it in Electronics & Tech.
- **Results.** `lost_sales_method_check.csv` (by kind and year, with the back-test).

**Why the upper bound is not evidence.**

- Partial stock-out weeks sold 1.8 to 3.5 times the baseline in aggregate.
- Flooring each week at zero turns week-to-week noise into apparent losses. Applied to in-stock weeks where nothing was lost, the same clipped formula reports about EUR 13 per store-SKU-week.
- The upper bound (EUR 4,461 to EUR 102,112) is therefore reported, but only as a Hypothesis to test with daily stock data.

**Limitations.**

- Substitution to other SKUs is ignored, which overstates the loss.
- Partial-week losses are excluded from the primary estimate, which understates it.
- Baselines around long stock-outs use more distant weeks.
- A few SKUs have no supplier on the product master.

**Association test.** Across stores (n = 20), categories (n = 7) and store x category cells (n = 140), Pearson and Spearman correlations between availability change and revenue change are reported with p-values and labelled "Statistical association". They are never used as causal evidence.

## 8. Promotion baseline methodology

**Scope measures** (from the lines): promo revenue share, promoted units, discount cost, average discount depth, and promoted versus non-promoted line margin, by year, category and promotion type.

**Uplift (BRD 5.4)** is measured per store-SKU promotion event (`dw.fact_promotion_coverage`):

| Step | Rule |
|---|---|
| Promotion weeks | Weeks with at least 4 covered days; partial weeks are excluded from both sides |
| Baseline | Up to 4 weeks immediately before the first promotion week, same store and SKU, in stock and not promoted; at least 2 needed; deseasonalised with the same category x week index |
| Uplift % | (promotion-week units - baseline units) / baseline units, summed over events (ratio of sums) |
| Incremental promo margin | incremental units x (baseline price - unit cost) - promo discount cost (BRD 5.4) |
| Pull-forward | Units in the 2 weeks after the promotion (in stock, not promoted) against the baseline; a negative value means a post-promotion dip |
| Exclusions | Events with no valid baseline, events overlapping another event of the same store-SKU, and events whose SKU was not ranged in a promotion week (counts reported) |
| Year | An event belongs to the H2 of the retail year of its first promotion week |

Measured promotion changes are Observed changes. The claim that promotions caused part of the decline stays a Hypothesis until Phase 6 builds a counterfactual.

## 9. Evidence framework (BRD 6.2)

| Level | Used when | Rule in code (`src/analytics/evidence.py`) |
|---|---|---|
| Observed change | A metric moved | Default for every measured finding |
| Statistical association | Two measures move together across segments | Every correlation; never promoted |
| Root-cause evidence | A mechanism is directly visible and quantified with a disclosed method | Only when that mechanism's rule passes. Stock-outs: no-stock-all-week cells sell <= 60% of expected, back-test bias within +/-15%, coverage >= 90%. Only the full-week estimate qualifies; otherwise the finding becomes a Hypothesis. |
| Hypothesis | A plausible explanation the data cannot confirm | Every interpretation beyond the data; must name the additional data needed |

`investigation_shortlist.csv` has the BRD columns (finding_id, area, finding, metric, financial_impact_eur, contribution_pp, evidence_level, supporting_analysis, business_interpretation, recommended_next_analysis, limitations). It adds three columns:

- `headline`: a one-line summary.
- `impact_basis`: what the EUR figure measures. Findings describe overlapping slices of one decline, so their impacts must not be added together.
- `investigation_priority`: what Phase 6 should look at first, by the size of the net revenue slice a finding explains or would explain. High is 20% or more of the decline, Medium 5% or more, Low below that; Context covers descriptive findings. Evidence strength is not folded in on purpose, because a large slice with weak evidence is exactly what Phase 6 must investigate. Controllability is scored in Phase 6 (BRD Q10).

`financial_impact_eur` holds only effects on the net revenue change. Findings about other quantities (discount cost, target variance, availability %) leave it blank and give the figure in the text.

## 10. Assumptions

1. Receipts (transactions) are a proxy for customer visits. There is no footfall data, so traffic cannot be separated from conversion.
2. `return_reason` is the reason recorded at the till, not a verified fault.
3. A store-SKU is ranged in a week when the weekly stock snapshot has a row for it.
4. Weeks without a target are neither hit nor miss, and they break a miss streak. Persistent underperformance is 8 or more misses in the last 13 weeks (BRD Q9).
5. The "decline cluster" is the smallest set of stores, taken largest decline first, that together cover 50% of the estate decline (`trend.cluster_cover`). It is a description, not a segment chosen in advance.
6. Product drill-down is limited to categories carrying at least 15% of the decline. Products are flagged by rule, not listed by worst YoY.

## 11. Limitations

- Synthetic data. The retail patterns are realistic, but external context (competitors, footfall, weather, local events) does not exist in the model.
- Weekly YoY is volatile (single weeks move by +/-20%). The timing step test is descriptive, not a formal change-point test. A "step change" also needs the step to explain at least 25% of weekly variance. Here it does not (R2 0.12), so the pattern is reported as a persistent decline with no clear trend within H2.
- The diag views that select `*` fix their column list when created. On SQL Server, run `sp_refreshview` (or rerun the scripts) if the Phase 4 views change.
- Target misses were widespread in both years (16 of 20 stores meet the persistent rule in each), so the BRD rule does not discriminate. Target setting should be reviewed.
- Store S13 lacks 2 trading days in week 42 of 2024 (about EUR 11k of prior-year revenue), which slightly flatters its YoY. The Unknown product member carries EUR 11k of prior-year revenue.
- Estimated lost sales and promotion uplift are model-based estimates with the limitations above.
- The model has not been run on SQL Server in this environment (Phase 4 limitation). The Phase 5 SQL is T-SQL and uses the same verification path as Phase 4.

## 12. Independence from the synthetic ground truth

Phase 5 must reach its conclusions from business-visible data only.

1. **Whitelist.** `model_access.allowed_path` accepts only the files in `config/analytics_config.yaml` and the frozen Phase 1 to 4 inputs. It refuses any underscore-prefixed file and any path through `evaluation`, `raw`, `sample` or `quarantine`.
2. **Runtime record.** A Python audit hook records every file opened during the run. The validation report lists the files read, and the run fails if a refused path was opened.
3. **Tests** (`tests/test_phase5_analytics.py`):
   - trace every open during a full run;
   - scan the Phase 5 code, SQL and configuration for evaluation-asset names;
   - scan the diagnostic SQL for file-reading functions (a database engine can open files the Python guard cannot see);
   - forbid imports of the generator, the data-quality package or evaluation code;
   - check that the executive summary uses no evaluation vocabulary.
4. **Not run.** The evaluation script is not run in Phase 5.

## 13. Reproducibility

```
python -m src.analytics.run_phase5 --record-freeze     # once, at the start of Phase 5 (already recorded)
python -m src.analytics.run_phase5 --engine duckdb     # rebuild the Phase 4 model locally and analyse it (about 25 s)
python -m src.analytics.run_phase5                     # SQL Server: analyse the database Phase 4 built
python -m pytest tests/test_phase5_analytics.py        # Phase 5 tests (a full run in a temporary folder)
```

- **Deterministic.** There is no randomness, and rankings break ties by key. Float outputs are rounded to 6 decimals. A test re-runs the pipeline and compares every CSV with the committed outputs.
- **Frozen inputs.** Changing any Phase 1 to 4 input stops the run with the list of changed files. Line endings are normalised, so a Windows checkout verifies.
- **Configurable.** Every threshold is in `config/analytics_config.yaml`.

## 14. Outputs

| File | Content |
|---|---|
| `phase5_executive_summary.md` | Management story (10 questions) |
| `investigation_shortlist.csv` | All findings with evidence levels |
| `headline_kpis.csv`, `headline_trend.csv`, `weekly_yoy_full_year.csv`, `trend_profile.csv` | Headline and timing |
| `store_contribution.csv`, `region_contribution.csv`, `format_contribution.csv`, `region_format_matrix.csv`, `store_cluster_weekly.csv` | Where |
| `category_contribution.csv`, `category_region_matrix.csv`, `product_diagnostics.csv`, `range_change.csv` | What |
| `transaction_basket_decomposition.csv`, `revenue_bridge.csv` | Shapley bridge (estate, region, format, store, category) |
| `returns_diagnostics.csv`, `returns_attributes.csv` | Returns by week, store, region, category, recorded reason and product |
| `availability_diagnostics.csv`, `availability_association.csv`, `lost_sales_method_check.csv` | Availability and ESTIMATED lost sales |
| `promotion_diagnostics.csv`, `promotion_events.csv` | Promotion scope, uplift, margin and pull-forward |
| `target_performance.csv`, `target_weekly.csv` | Targets |
| `phase5_validation_report.md`, `validation_checks.csv`, `input_verification.csv`, `phase1_4_input_manifest.csv`, `phase5_run_log.txt`, `model_build/` | Proof |
| `figures/01-08_*.png` | Charts, each naming its source CSV so it can be rebuilt in Power BI |
