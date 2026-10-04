# Phase 6 validation report

- Run: 2026-09-28T11:49:44 (39.6 s), engine: duckdb
- Result: **ALL CHECKS PASSED** (36 of 36)
- Frozen Phase 1-5 files verified: 84 (84 unchanged)

## SQL executed

| Script | Batches | Seconds |
|---|---:|---:|
| `sql/analysis/diagnostics/01_headline_trend.sql` | 5 | 0.04 |
| `sql/analysis/diagnostics/02_store_contribution.sql` | 4 | 0.13 |
| `sql/analysis/diagnostics/03_region_format_analysis.sql` | 2 | 0.05 |
| `sql/analysis/diagnostics/04_category_contribution.sql` | 3 | 0.04 |
| `sql/analysis/diagnostics/05_transaction_basket_analysis.sql` | 3 | 0.07 |
| `sql/analysis/diagnostics/06_returns_diagnostics.sql` | 3 | 0.02 |
| `sql/analysis/diagnostics/07_availability_diagnostics.sql` | 5 | 0.02 |
| `sql/analysis/diagnostics/08_promotion_diagnostics.sql` | 3 | 0.01 |
| `sql/analysis/diagnostics/09_target_performance.sql` | 2 | 0.02 |
| `sql/analysis/rca/01_store_cluster.sql` | 3 | 0.01 |
| `sql/analysis/rca/02_supply_and_returns.sql` | 5 | 0.02 |

## Checks

| Group | Check | Value | Reference | Status |
|---|---|---:|---:|---|
| Headline | H2 2024 net revenue vs Phase 4 | 10,188,727.5500 | 10,188,727.5500 | PASS |
| Headline | H2 2025 net revenue vs Phase 4 | 9,457,457.0500 | 9,457,457.0500 | PASS |
| Headline | H2 YoY % vs Phase 4 | -7.1773 | -7.1773 | PASS |
| Headline | H2 2024 net revenue vs direct fact query | 10,188,727.5500 | 10,188,727.5500 | PASS |
| Headline | H2 2025 net revenue vs direct fact query | 9,457,457.0500 | 9,457,457.0500 | PASS |
| Headline | net_revenue change vs Phase 5 headline | -731,270.5000 | -731,270.5000 | PASS |
| Headline | sales_revenue change vs Phase 5 headline | -716,613.0300 | -716,613.0300 | PASS |
| Headline | returns_value change vs Phase 5 headline | 14,657.4700 | 14,657.4700 | PASS |
| Headline | transactions change vs Phase 5 headline | -13,419.0000 | -13,419.0000 | PASS |
| Overlap | store group x category cells add up to the total change | -731,270.5000 | -731,270.5000 | PASS |
| Overlap | exclusive attribution closes exactly to the total change | -731,270.5000 | -731,270.5000 | PASS |
| Overlap | residual breakdown closes to the residual | -78,521.7935 | -78,521.7935 | PASS |
| Overlap | E&T stock-outs: exclusive amount never exceeds the measured total | 37,235.3468 | 37,235.3468 | PASS |
| Overlap | E&T faulty returns: exclusive amount never exceeds the measured total | 31,588.7300 | 31,588.7300 | PASS |
| Overlap | H&K promotion period: exclusive amount never exceeds the measured total | 186,146.4204 | 186,146.4204 | PASS |
| Periods | rca SQL H2 window (retail weeks 27-52, hard-coded in v_store_category_h2) matches the configuration | 27-52 | 27-52 | PASS |
| Overlap | E&T stock-outs: exclusive = total - overlap with cluster excess | -37,235.3468 | -37,235.3468 | PASS |
| Overlap | E&T faulty returns: exclusive = total - overlap with cluster excess | -31,588.7300 | -31,588.7300 | PASS |
| Overlap | H&K promotion period: exclusive = total - overlap with cluster excess | -186,146.4204 | -186,146.4204 | PASS |
| Overlap | pairwise matrix is symmetric | 0.0000 | 0.0000 | PASS |
| Store cluster | controls exclude every cluster store | 0 | 0 | PASS |
| Store cluster | matched control group has the configured size | 5 | 5 | PASS |
| Store cluster | ratio DiD: actual - counterfactual = excess | -397,778.2093 | -397,778.2093 | PASS |
| Store cluster | cluster H2 net revenue in the weekly panel = governed store view | 1,092,401.6500 | 1,092,401.6500 | PASS |
| Electronics | lost-sales estimates never negative | 0.0000 | 0.0000 | PASS |
| Electronics | category full-week lost sales equal the frozen Phase 5 figure | 37,235.3468 | 37,235.3468 | PASS |
| Electronics | supplier lost-sales shares add up to 100% | 1.0000 | 1.0000 | PASS |
| Returns | store faulty-return changes add up to the category change | 31,588.7300 | 31,588.7300 | PASS |
| Returns | product faulty-return changes add up to the category change | 31,588.7300 | 31,588.7300 | PASS |
| Promotions | M1 bootstrap CI contains the point estimate | -186,146.4204 | -186,146.4204 | PASS |
| Promotions | M1 by-store effects add up to the category effect | -186,146.4204 | -186,146.4204 | PASS |
| Evidence | every driver has one BRD evidence level | 0 | 0 | PASS |
| Evidence | no fragile estimate is labelled Root-cause evidence | 0 | 0 | PASS |
| Sensitivity | every central estimate has variants | 4 | 3 | PASS |
| Scenarios | scenario E equals the sum of the exclusive components | 652,748.7065 | 652,748.7065 | PASS |
| Robustness | no infinite values in result tables | 0 | 0 | PASS |

## Independence from the synthetic ground truth

Files opened were recorded with an audit hook (484 opens). Project data, report and configuration files READ: `config/analytics_config.yaml`, `config/project_config.yaml`, `config/rca_config.yaml`, `config/sql_model_config.yaml`, `data/processed/curated/dim_date.csv`, `data/processed/curated/dim_product.csv`, `data/processed/curated/dim_store.csv`, `data/processed/curated/fact_inventory.csv`, `data/processed/curated/fact_promotions.csv`, `data/processed/curated/fact_returns.csv`, `data/processed/curated/fact_sales.csv`, `data/processed/curated/fact_targets.csv`, `reports/phase3/kpi_reconciliation.csv`, `reports/phase3/lineage.json`, `reports/phase4/kpi_validation_duckdb.csv`, `reports/phase4/reconciliation_results_duckdb.csv`, `reports/phase5/availability_association.csv`, `reports/phase5/availability_diagnostics.csv`, `reports/phase5/category_contribution.csv`, `reports/phase5/category_region_matrix.csv`, `reports/phase5/format_contribution.csv`, `reports/phase5/headline_kpis.csv`, `reports/phase5/headline_trend.csv`, `reports/phase5/input_verification.csv`, `reports/phase5/investigation_shortlist.csv`, `reports/phase5/lost_sales_method_check.csv`, `reports/phase5/phase1_4_input_manifest.csv`, `reports/phase5/phase5_executive_summary.md`, `reports/phase5/product_diagnostics.csv`, `reports/phase5/promotion_diagnostics.csv`, `reports/phase5/promotion_events.csv`, `reports/phase5/range_change.csv`, `reports/phase5/region_contribution.csv`, `reports/phase5/region_format_matrix.csv`, `reports/phase5/returns_attributes.csv`, `reports/phase5/returns_diagnostics.csv`, `reports/phase5/revenue_bridge.csv`, `reports/phase5/store_cluster_weekly.csv`, `reports/phase5/store_contribution.csv`, `reports/phase5/target_performance.csv`, `reports/phase5/target_weekly.csv`, `reports/phase5/transaction_basket_decomposition.csv`, `reports/phase5/trend_profile.csv`, `reports/phase5/validation_checks.csv`, `reports/phase5/weekly_yoy_full_year.csv`, `reports/phase6/phase1_5_input_manifest.csv`. Refused (evaluation-only, raw, sample, quarantine or underscore-prefixed) paths opened: **0**.

## Outputs

| File | Rows |
|---|---:|
| `category_store_contribution.csv` | 160 |
| `cluster_basket_distribution.csv` | 24 |
| `cluster_category_mix.csv` | 7 |
| `cluster_control_groups.csv` | 4 |
| `cluster_did.csv` | 8 |
| `cluster_hour.csv` | 12 |
| `cluster_matching_distances.csv` | 17 |
| `cluster_mechanisms.csv` | 17 |
| `cluster_onset.csv` | 1 |
| `cluster_onset_by_store.csv` | 3 |
| `cluster_onset_daily.csv` | 362 |
| `cluster_placebo.csv` | 1 |
| `cluster_store_features.csv` | 20 |
| `cluster_weekday.csv` | 7 |
| `cluster_weekly_did.csv` | 52 |
| `counterfactual_scenarios.csv` | 6 |
| `driver_attribution.csv` | 5 |
| `driver_overlap_details.csv` | 3 |
| `driver_overlap_matrix.csv` | 4 |
| `driver_perimeter_matrix.csv` | 6 |
| `driver_residual_breakdown.csv` | 4 |
| `electronics_kpis.csv` | 9 |
| `electronics_lost_sales_by_store.csv` | 20 |
| `electronics_lost_sales_totals.csv` | 3 |
| `electronics_range_distribution.csv` | 10 |
| `electronics_recovery.csv` | 20 |
| `electronics_replenishment.csv` | 8 |
| `electronics_sku_stockouts.csv` | 90 |
| `electronics_stockout_episodes.csv` | 8 |
| `electronics_supplier_comparison.csv` | 4 |
| `electronics_supplier_test.csv` | 3 |
| `electronics_weekly_timeline.csv` | 26 |
| `faulty_returns_by_cohort.csv` | 24 |
| `faulty_returns_by_product.csv` | 90 |
| `faulty_returns_by_store.csv` | 20 |
| `faulty_returns_by_store_other_reasons.csv` | 20 |
| `faulty_returns_by_store_supplier.csv` | 80 |
| `faulty_returns_by_supplier.csv` | 4 |
| `faulty_returns_concentration.csv` | 3 |
| `faulty_returns_lag.csv` | 2 |
| `faulty_returns_promotion_status.csv` | 2 |
| `faulty_returns_reasons.csv` | 5 |
| `headline_reconciliation.csv` | 9 |
| `hk_promotion_by_store.csv` | 20 |
| `hk_promotion_counterfactuals.csv` | 6 |
| `hk_promotion_event_study.csv` | 52 |
| `hk_promotion_events_by_year.csv` | 2 |
| `hk_promotion_weekly.csv` | 26 |
| `input_verification.csv` | 84 |
| `root_cause_evidence_matrix.csv` | 9 |
| `sensitivity_analysis.csv` | 83 |
| `sensitivity_summary.csv` | 5 |
| `supplier_comparison_all_categories.csv` | 16 |
| `validation_checks.csv` | 36 |

Figures: `figures/01_root_cause_tree.png`, `figures/02_driver_waterfall.png`, `figures/03_cluster_vs_controls.png`, `figures/04_category_store_heatmap.png`, `figures/05_electronics_availability_timeline.png`, `figures/06_stockout_revenue_overlay.png`, `figures/07_supplier_concentration.png`, `figures/08_faulty_return_concentration.png`, `figures/09_hk_promotion_counterfactual.png`, `figures/10_driver_overlap_matrix.png`, `figures/11_evidence_matrix.png`
