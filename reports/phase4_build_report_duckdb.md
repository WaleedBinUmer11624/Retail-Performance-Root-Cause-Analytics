# Phase 4 model build: duckdb

- Run: 2026-09-28T05:50:12 (13.4 s)
- Engine: DuckDB verification engine: T-SQL parsed by sqlglot (tsql dialect) and executed in DuckDB; @tsql-only batches (constraints, columnstore indexes, THROW) not executed
- Result: **PASSED**
- Curated inputs verified against Phase 3 lineage (SHA-256): 8 files

## Steps

| step | batches | skipped_for_engine | seconds |
|---|---|---|---|
| sql/schema/01_create_database_and_schemas.sql | 0 | 4.0 | 0.0 |
| sql/staging/02_create_staging_tables.sql | 9 | 0.0 | 0.09 |
| @load_staging | 8 |  | 8.84 |
| @load_expected | 45 |  | 0.08 |
| sql/schema/03_create_dimension_tables.sql | 6 | 0.0 | 0.02 |
| sql/schema/04_create_fact_tables.sql | 6 | 0.0 | 0.02 |
| sql/schema/05_create_keys_and_constraints.sql | 0 | 6.0 | 0.0 |
| sql/schema/06_create_indexes.sql | 0 | 2.0 | 0.0 |
| sql/transformations/07_load_dimensions.sql | 6 | 0.0 | 0.08 |
| sql/transformations/08_load_facts.sql | 6 | 2.0 | 2.44 |
| sql/validation/09_reconciliation.sql | 3 | 1.0 | 0.17 |
| sql/analysis/10_analytical_views.sql | 18 | 0.0 | 0.17 |
| sql/validation/11_kpi_validation.sql | 3 | 1.0 | 1.17 |

## Objects

| table_schema | table_name | table_type | row_count |
|---|---|---|---|
| dw | dim_date | TABLE | 732 |
| dw | dim_product | TABLE | 601 |
| dw | dim_promotion | TABLE | 138 |
| dw | dim_retail_week | TABLE | 106 |
| dw | dim_store | TABLE | 21 |
| dw | fact_inventory | TABLE | 939,249 |
| dw | fact_promotion_coverage | TABLE | 49,430 |
| dw | fact_returns | TABLE | 34,562 |
| dw | fact_sales | TABLE | 1,339,510 |
| dw | fact_targets | TABLE | 2,077 |
| mart | kpi_definition | TABLE | 21 |
| mart | v_availability_category_week | VIEW |  |
| mart | v_availability_store_week | VIEW |  |
| mart | v_kpi_category_period | VIEW |  |
| mart | v_kpi_estate_period | VIEW |  |
| mart | v_kpi_segment_period | VIEW |  |
| mart | v_kpi_store_period | VIEW |  |
| mart | v_performance_category_week | VIEW |  |
| mart | v_performance_store_day | VIEW |  |
| mart | v_performance_store_week | VIEW |  |
| mart | v_product_store_week | VIEW |  |
| mart | v_promotion_performance | VIEW |  |
| mart | v_returns_analysis | VIEW |  |
| mart | v_returns_store_day | VIEW |  |
| mart | v_sales_line | VIEW |  |
| mart | v_sales_store_day | VIEW |  |
| mart | v_yoy_segment_period | VIEW |  |
| mart | v_yoy_store_week | VIEW |  |
| recon | actual | TABLE | 45 |
| recon | dw_totals | TABLE | 1 |
| recon | expected | TABLE | 45 |
| recon | kpi_validation_result | TABLE | 38 |
| recon | kv_base | TABLE | 1 |
| recon | kv_category | TABLE | 8 |
| recon | kv_estate | TABLE | 8 |
| recon | kv_segment | TABLE | 32 |
| recon | kv_yoy_estate | TABLE | 5 |
| recon | v_dw_totals | VIEW |  |
| recon | v_kpi_validation | VIEW |  |
| recon | v_reconciliation | VIEW |  |
| stg | dim_date | TABLE | 731 |
| stg | dim_product | TABLE | 601 |
| stg | dim_store | TABLE | 20 |
| stg | fact_inventory | TABLE | 939,249 |
| stg | fact_promotions | TABLE | 49,430 |
| stg | fact_returns | TABLE | 34,562 |
| stg | fact_sales | TABLE | 1,339,510 |
| stg | fact_targets | TABLE | 2,077 |

## Reconciliation against Phase 3

| metric_name | metric_group | expected_value | actual_value | abs_difference | tolerance_abs | status |
|---|---|---|---|---|---|---|
| rows_stg_dim_date | row_count | 731 | 731 | 0 | 0 | PASS |
| rows_stg_dim_store | row_count | 20 | 20 | 0 | 0 | PASS |
| rows_stg_dim_product | row_count | 601 | 601 | 0 | 0 | PASS |
| rows_stg_fact_sales | row_count | 1,339,510 | 1,339,510 | 0 | 0 | PASS |
| rows_stg_fact_returns | row_count | 34,562 | 34,562 | 0 | 0 | PASS |
| rows_stg_fact_inventory | row_count | 939,249 | 939,249 | 0 | 0 | PASS |
| rows_stg_fact_promotions | row_count | 49,430 | 49,430 | 0 | 0 | PASS |
| rows_stg_fact_targets | row_count | 2,077 | 2,077 | 0 | 0 | PASS |
| rows_dw_dim_date | row_count | 731 | 731 | 0 | 0 | PASS |
| rows_dw_dim_store | row_count | 20 | 20 | 0 | 0 | PASS |
| rows_dw_dim_product | row_count | 601 | 601 | 0 | 0 | PASS |
| rows_dw_fact_sales | row_count | 1,339,510 | 1,339,510 | 0 | 0 | PASS |
| rows_dw_fact_returns | row_count | 34,562 | 34,562 | 0 | 0 | PASS |
| rows_dw_fact_inventory | row_count | 939,249 | 939,249 | 0 | 0 | PASS |
| rows_dw_fact_targets | row_count | 2,077 | 2,077 | 0 | 0 | PASS |
| rows_dw_fact_promotion_coverage | row_count | 49,430 | 49,430 | 0 | 0 | PASS |
| rows_dw_dim_promotion | row_count | 136 | 136 | 0 | 0 | PASS |
| unknown_product_sales_lines | unknown_member | 1,293 | 1,293 | 0 | 0 | PASS |
| unknown_promotion_sales_lines | unknown_member | 1 | 1 | 0 | 0 | PASS |
| not_promoted_sales_lines | unknown_member | 1,077,994 | 1,077,994 | 0 | 0 | PASS |
| unknown_store_fact_rows | unknown_member | 0 | 0 | 0 | 0 | PASS |
| unknown_date_fact_rows | unknown_member | 0 | 0 | 0 | 0 | PASS |
| unknown_product_other_fact_rows | unknown_member | 0 | 0 | 0 | 0 | PASS |
| conversion_failures | load_integrity | 0 | 0 | 0 | 0 | PASS |
| sales_lines | kpi | 1,339,510 | 1,339,510 | 0 | 0 | PASS |
| gross_sales | kpi | 39,877,276.35 | 39,877,276.35 | 0 | 0.01 | PASS |
| discount_value | kpi | 1,665,652.67 | 1,665,652.67 | 0 | 0.01 | PASS |
| sales_revenue | kpi | 38,211,623.68 | 38,211,623.68 | 0 | 0.01 | PASS |
| returns_value | kpi | 1,288,620.48 | 1,288,620.48 | 0 | 0.01 | PASS |
| net_revenue | kpi | 36,923,003.2 | 36,923,003.2 | 0 | 0.01 | PASS |
| cogs | kpi | 22,948,014.045 | 22,948,014.045 | 0 | 0.01 | PASS |
| gross_margin | kpi | 13,974,989.155 | 13,974,989.155 | 0 | 0.01 | PASS |
| gross_margin_pct | kpi | 0.37849 | 0.37849 | 0 | 0.000001 | PASS |
| transactions | kpi | 835,568 | 835,568 | 0 | 0 | PASS |
| units | kpi | 1,768,568 | 1,768,568 | 0 | 0 | PASS |
| aov | kpi | 45.731315 | 45.731315 | 0 | 0.000001 | PASS |
| upt | kpi | 2.116606 | 2.116606 | 0 | 0.000001 | PASS |
| asp | kpi | 21.605968 | 21.605968 | 0 | 0.000001 | PASS |
| return_rate_value | kpi | 0.033723 | 0.033723 | 0 | 0.000001 | PASS |
| promo_revenue_share | kpi | 0.15393 | 0.15393 | 0 | 0.000001 | PASS |
| returns_rows | kpi | 34,562 | 34,562 | 0 | 0 | PASS |
| stock_availability_2024 | kpi | 0.955032 | 0.955032 | 0 | 0.000001 | PASS |
| h2_2024_net_revenue | kpi | 10,188,727.55 | 10,188,727.55 | 0 | 0.01 | PASS |
| h2_2025_net_revenue | kpi | 9,457,457.05 | 9,457,457.05 | 0 | 0.01 | PASS |
| h2_yoy_pct | kpi | -7.177251 | -7.177251 | 0 | 0.0001 | PASS |

## KPI layer validation

| check_name | expected_value | actual_value | tolerance | status |
|---|---|---|---|---|
| base: gross_sales | 39,877,276.35 | 39,877,276.35 | 0.01 | PASS |
| base: discount_value | 1,665,652.67 | 1,665,652.67 | 0.01 | PASS |
| base: sales_revenue | 38,211,623.68 | 38,211,623.68 | 0.01 | PASS |
| base: returns_value | 1,288,620.48 | 1,288,620.48 | 0.01 | PASS |
| base: net_revenue | 36,923,003.2 | 36,923,003.2 | 0.01 | PASS |
| base: cogs | 22,948,014.045 | 22,948,014.045 | 0.01 | PASS |
| base: gross_margin | 13,974,989.155 | 13,974,989.155 | 0.01 | PASS |
| base: transactions | 835,568 | 835,568 | 0 | PASS |
| base: units | 1,768,568 | 1,768,568 | 0 | PASS |
| base: sales_lines | 1,339,510 | 1,339,510 | 0 | PASS |
| base: promo_revenue_share | 0.15393 | 0.15393 | 0.000001 | PASS |
| estate H2 2024 net revenue | 10,188,727.55 | 10,188,727.55 | 0.01 | PASS |
| estate H2 2025 net revenue | 9,457,457.05 | 9,457,457.05 | 0.01 | PASS |
| estate H2 YoY % (mart.v_yoy_segment_period) | -7.177251 | -7.177251 | 0.0001 | PASS |
| estate stock availability 2024 | 0.955032 | 0.955032 | 0.000001 | PASS |
| estate FY rows sum to base net revenue | 36,923,003.2 | 36,923,003.2 | 0.01 | PASS |
| estate FY rows sum to base transactions | 835,568 | 835,568 | 0 | PASS |
| segment roll-up = estate: Region | 0 | 0 | 0 | PASS |
| segment roll-up = estate: Format | 0 | 0 | 0 | PASS |
| segment roll-up = estate: Store | 0 | 0 | 0 | PASS |
| segment roll-up = estate: Estate | 0 | 0 | 0 | PASS |
| category roll-up = estate (net and sales revenue) | 0 | 0 | 0 | PASS |
| store-week view sums to base net revenue | 36,923,003.2 | 36,923,003.2 | 0.01 | PASS |
| store-week targets = all targets loaded | 40,150,920 | 40,150,920 | 0.01 | PASS |
| product-store-week view sums to units | 1,768,568 | 1,768,568 | 0 | PASS |
| product-store-week view sums to sales revenue | 38,211,623.68 | 38,211,623.68 | 0.01 | PASS |
| promotion view: promoted revenue = promo sales revenue | 5,881,909.78 | 5,881,909.78 | 0.01 | PASS |
| promotion view: all members sum to sales revenue | 38,211,623.68 | 38,211,623.68 | 0.01 | PASS |
| returns view sums to returns value | 1,288,620.48 | 1,288,620.48 | 0.01 | PASS |
| availability view 2024 = reconciled availability | 0.955032 | 0.955032 | 0.000001 | PASS |
| category availability view = store availability view (cells) | 939,249 | 939,249 | 0 | PASS |
| line-level view row count = fact_sales | 1,339,510 | 1,339,510 | 0 | PASS |
| identity: Sales Revenue = Gross Sales - Discount Value | 0 | 0 | 0 | PASS |
| identity: Net Revenue = Sales Revenue - Returns Value | 0 | 0 | 0 | PASS |
| identity: Gross Margin = Net Revenue - COGS | 0 | 0 | 0 | PASS |
| identity: Sales Revenue = Transactions x UPT x ASP | 0 | 0 | 0 | PASS |
| identity: AOV = UPT x ASP | 0 | 0 | 0 | PASS |
| identity: Gross Margin % x Net Revenue = Gross Margin | 0 | 0 | 0 | PASS |
