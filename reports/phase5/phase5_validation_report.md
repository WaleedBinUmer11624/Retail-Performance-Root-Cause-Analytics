# Phase 5 validation report

- Run: 2026-09-28T07:43:14 (22.9 s), engine: duckdb
- Result: **ALL CHECKS PASSED** (64 of 64 checks pass)
- Comparison: H2 2025 vs H2 2024, retail weeks 27 to 52, week-aligned

## 1. Frozen inputs (Phase 1 to 4)

34 files verified against `reports/phase5/phase1_4_input_manifest.csv` (SHA-256, line endings normalised): 34 unchanged, 0 changed. Full list: `input_verification.csv`.

The model was rebuilt from the frozen curated data with the Phase 4 runner (DuckDB verification engine; curated files verified against Phase 3 lineage) and passed its own reconciliation: 45 of 45 reconciliation checks and 38 of 38 KPI checks pass. Build log: `model_build/`.

## 2. Objects used

Phase 4 governed layer: `mart.v_performance_store_day`, `mart.v_performance_store_week`, `mart.v_performance_category_week`, `mart.v_availability_store_week`, `mart.v_availability_category_week`, `mart.v_yoy_store_week`; star schema `dw.fact_sales`, `dw.fact_returns`, `dw.fact_inventory`, `dw.fact_promotion_coverage`, `dw.dim_date`, `dw.dim_retail_week`, `dw.dim_store`, `dw.dim_product`, `dw.dim_promotion`. Phase 5 diagnostic views (schema `diag`) are created by:

| Script | Batches | Seconds |
|---|---:|---:|
| `sql/analysis/diagnostics/01_headline_trend.sql` | 5 | 0.04 |
| `sql/analysis/diagnostics/02_store_contribution.sql` | 4 | 0.12 |
| `sql/analysis/diagnostics/03_region_format_analysis.sql` | 2 | 0.05 |
| `sql/analysis/diagnostics/04_category_contribution.sql` | 3 | 0.04 |
| `sql/analysis/diagnostics/05_transaction_basket_analysis.sql` | 3 | 0.06 |
| `sql/analysis/diagnostics/06_returns_diagnostics.sql` | 3 | 0.02 |
| `sql/analysis/diagnostics/07_availability_diagnostics.sql` | 5 | 0.02 |
| `sql/analysis/diagnostics/08_promotion_diagnostics.sql` | 3 | 0.01 |
| `sql/analysis/diagnostics/09_target_performance.sql` | 2 | 0.02 |

## 3. Checks

| Check | Group | Value | Reference | Difference | Tolerance | Status |
|---|---|---:|---:|---:|---:|---|
| 26 current-year weeks selected | Period | 26 weeks |  |  |  | PASS |
| weeks are retail weeks 27 to 52 | Period | 27 to 52 |  |  |  | PASS |
| every compared week has 7 days in both years | Period | 182 vs 182 days |  |  |  | PASS |
| prior-year week is the same retail week number | Period | week_key_py = prior year, same week |  |  |  | PASS |
| compared weeks start on the same weekday | Period | weekday [0] vs [0] |  |  |  | PASS |
| compared weeks are 364 days apart | Period | [364] days |  |  |  | PASS |
| H2 2024 net revenue vs Phase 4 | Headline vs Phase 4 | 10,188,727.55 | 10,188,727.55 | 0 | 0.01 | PASS |
| H2 2025 net revenue vs Phase 4 | Headline vs Phase 4 | 9,457,457.05 | 9,457,457.05 | 0 | 0.01 | PASS |
| H2 YoY % vs Phase 4 | Headline vs Phase 4 | -7.177251 | -7.177251 | 0 | 0.0001 | PASS |
| H2 2024 net revenue vs direct fact query | Headline vs Phase 4 | 10,188,727.55 | 10,188,727.55 | 0 | 0.01 | PASS |
| H2 2025 net revenue vs direct fact query | Headline vs Phase 4 | 9,457,457.05 | 9,457,457.05 | 0 | 0.01 | PASS |
| H2 2024 sales_revenue vs direct fact query | Headline vs Phase 4 | 10,557,440.91 | 10,557,440.91 | 0 | 0.01 | PASS |
| H2 2025 sales_revenue vs direct fact query | Headline vs Phase 4 | 9,840,827.88 | 9,840,827.88 | 0 | 0.01 | PASS |
| H2 2024 returns_value vs direct fact query | Headline vs Phase 4 | 368,713.36 | 368,713.36 | 0 | 0.01 | PASS |
| H2 2025 returns_value vs direct fact query | Headline vs Phase 4 | 383,370.83 | 383,370.83 | 0 | 0.01 | PASS |
| H2 2024 transactions vs direct fact query | Headline vs Phase 4 | 229,446 | 229,446 | 0 | 0 | PASS |
| H2 2025 transactions vs direct fact query | Headline vs Phase 4 | 216,027 | 216,027 | 0 | 0 | PASS |
| H2 2024 units_sold vs direct fact query | Headline vs Phase 4 | 487,993 | 487,993 | 0 | 0 | PASS |
| H2 2025 units_sold vs direct fact query | Headline vs Phase 4 | 457,916 | 457,916 | 0 | 0 | PASS |
| weekly changes add up to the H2 change | Contribution | -731,270.5 | -731,270.5 | 0 | 0.01 | PASS |
| store EUR changes add up to the estate change | Contribution | -731,270.5 | -731,270.5 | 0 | 0.01 | PASS |
| store contributions (pp) add up to the estate YoY % | Contribution | -7.177251 | -7.177251 | 0 | 0.0001 | PASS |
| store shares of change add up to 100% | Contribution | 1 | 1 | 0 | 0 | PASS |
| region EUR changes add up to the estate change | Contribution | -731,270.5 | -731,270.5 | 0 | 0.01 | PASS |
| region contributions (pp) add up to the estate YoY % | Contribution | -7.177251 | -7.177251 | 0 | 0.0001 | PASS |
| region shares of change add up to 100% | Contribution | 1 | 1 | 0 | 0 | PASS |
| format EUR changes add up to the estate change | Contribution | -731,270.5 | -731,270.5 | 0 | 0.01 | PASS |
| format contributions (pp) add up to the estate YoY % | Contribution | -7.177251 | -7.177251 | 0 | 0.0001 | PASS |
| format shares of change add up to 100% | Contribution | 1 | 1 | 0 | 0 | PASS |
| category EUR changes add up to the estate change | Contribution | -731,270.5 | -731,270.5 | 0 | 0.01 | PASS |
| category contributions (pp) add up to the estate YoY % | Contribution | -7.177251 | -7.177251 | 0 | 0.0001 | PASS |
| category shares of change add up to 100% | Contribution | 1 | 1 | 0 | 0 | PASS |
| store contribution (pp), max abs difference | SQL vs Python | 0 | 0 | 0 | 0.000001 | PASS |
| store share of change, max abs difference | SQL vs Python | 0 | 0 | 0 | 0.000001 | PASS |
| store ranking identical (EUR contribution) | SQL vs Python | 0 | 0 | 0 | 0 | PASS |
| store ranking identical (YoY %) | SQL vs Python | 0 | 0 | 0 | 0 | PASS |
| category contribution (pp), max abs difference | SQL vs Python | 0 | 0 | 0 | 0.000001 | PASS |
| category ranking identical | SQL vs Python | 0 | 0 | 0 | 0 | PASS |
| Shapley residual (estate) | Bridge | 0 | 0 | 0 | 0.01 | PASS |
| transactions + UPT + ASP + residual + returns = net revenue change | Bridge | -731,270.5 | -731,270.5 | 0 | 0.01 | PASS |
| waterfall ends at the current-period net revenue | Bridge | 9,457,457.05 | 9,457,457.05 | 0 | 0.01 | PASS |
| AOV change = UPT part + ASP part | Bridge | -0.459054 | -0.459054 | 0 | 0 | PASS |
| segment bridges reconcile (max abs difference) | Bridge | 0 | 0 | 0 | 0.01 | PASS |
| segment transactions_effect (max abs difference) | SQL vs Python | 0 | 0 | 0 | 0.01 | PASS |
| segment upt_effect (max abs difference) | SQL vs Python | 0 | 0 | 0 | 0.01 | PASS |
| segment asp_effect (max abs difference) | SQL vs Python | 0 | 0 | 0 | 0.01 | PASS |
| segment returns_effect (max abs difference) | SQL vs Python | 0 | 0 | 0 | 0.01 | PASS |
| category bridges reconcile (max abs difference) | Bridge | 0 | 0 | 0 | 0.01 | PASS |
| category transactions_effect (max abs difference) | SQL vs Python | 0 | 0 | 0 | 0.01 | PASS |
| category upt_effect (max abs difference) | SQL vs Python | 0 | 0 | 0 | 0.01 | PASS |
| category asp_effect (max abs difference) | SQL vs Python | 0 | 0 | 0 | 0.01 | PASS |
| targets: missed_weeks identical for every store and year | SQL vs Python | 0 | 0 | 0 | 0 | PASS |
| targets: longest_miss_streak identical for every store and year | SQL vs Python | 0 | 0 | 0 | 0 | PASS |
| targets: last13_missed_weeks identical for every store and year | SQL vs Python | 0 | 0 | 0 | 0 | PASS |
| store returns add up to the estate returns | Returns | 383,370.83 | 383,370.83 | 0 | 0.01 | PASS |
| recorded-reason returns add up to the estate returns | Returns | 383,370.83 | 383,370.83 | 0 | 0.01 | PASS |
| estate returns equal the headline returns | Returns | 383,370.83 | 383,370.83 | 0 | 0.01 | PASS |
| store ranged cells add up to the estate | Availability | 235,637 | 235,637 | 0 | 0 | PASS |
| estimated lost sales are never negative | Lost sales | 0 | 0 | 0 | 0 | PASS |
| stock-out weeks with a baseline (coverage) | Lost sales | 0.999521 | 1 | 0.000479 | 0.1 | PASS |
| back-test: actual / expected on in-stock weeks | Lost sales | 0.993221 | 1 | 0.006779 | 0.15 | PASS |
| every finding has exactly one allowed evidence level | Evidence | 0 | 0 | 0 | 0 | PASS |
| finding ids are unique | Evidence | 0 | 0 | 0 | 0 | PASS |
| no infinite values (division by zero) in any result table | Robustness | 0 | 0 | 0 | 0 | PASS |

## 4. Independence from the synthetic ground truth

Every file opened during this run was recorded with a Python audit hook (391 opens). Project data, report and configuration files READ: `config/analytics_config.yaml`, `config/project_config.yaml`, `config/sql_model_config.yaml`, `data/processed/curated/dim_date.csv`, `data/processed/curated/dim_product.csv`, `data/processed/curated/dim_store.csv`, `data/processed/curated/fact_inventory.csv`, `data/processed/curated/fact_promotions.csv`, `data/processed/curated/fact_returns.csv`, `data/processed/curated/fact_sales.csv`, `data/processed/curated/fact_targets.csv`, `reports/phase3/kpi_reconciliation.csv`, `reports/phase3/lineage.json`, `reports/phase4/kpi_validation_duckdb.csv`, `reports/phase4/reconciliation_results_duckdb.csv`, `reports/phase5/phase1_4_input_manifest.csv`. Files written inside the project: 44. Refused (evaluation-only, raw, sample or underscore-prefixed) paths opened: **0**. The tests repeat this check and also scan the Phase 5 code, SQL and configuration for evaluation-asset names and imports (`tests/test_phase5_analytics.py`).

## 5. Outputs

| File | Rows |
|---|---:|
| `availability_association.csv` | 4 |
| `availability_diagnostics.csv` | 228 |
| `category_contribution.csv` | 8 |
| `category_region_matrix.csv` | 40 |
| `format_contribution.csv` | 3 |
| `headline_kpis.csv` | 14 |
| `headline_trend.csv` | 26 |
| `input_verification.csv` | 34 |
| `investigation_shortlist.csv` | 25 |
| `lost_sales_method_check.csv` | 7 |
| `product_diagnostics.csv` | 65 |
| `promotion_diagnostics.csv` | 26 |
| `promotion_events.csv` | 26,278 |
| `range_change.csv` | 21 |
| `region_contribution.csv` | 5 |
| `region_format_matrix.csv` | 10 |
| `returns_attributes.csv` | 2 |
| `returns_diagnostics.csv` | 320 |
| `revenue_bridge.csv` | 7 |
| `store_cluster_weekly.csv` | 26 |
| `store_contribution.csv` | 20 |
| `target_performance.csv` | 40 |
| `target_weekly.csv` | 1,037 |
| `transaction_basket_decomposition.csv` | 37 |
| `trend_profile.csv` | 25 |
| `validation_checks.csv` | 64 |
| `weekly_yoy_full_year.csv` | 52 |

Figures: `figures/01_weekly_net_revenue.png`, `figures/02_revenue_bridge.png`, `figures/03_store_contribution.png`, `figures/04_category_contribution.png`, `figures/05_basket_kpis.png`, `figures/06_availability_vs_revenue.png`, `figures/07_returns_trend.png`, `figures/08_target_heatmap.png`

