# Phase 4 model build: mssql

- Run: 2026-09-29T18:47:10 (451.8 s)
- Engine: SQL Server
- Result: **FAILED** (09_reconciliation.sql batch 0: ('42000', "[42000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Missing end comment mark '*/'. (113) (SQLExecDirectW)"))
- Curated inputs verified against Phase 3 lineage (SHA-256): 8 files

## Steps

| step | batches | skipped_for_engine | seconds |
|---|---|---|---|
| sql/schema/01_create_database_and_schemas.sql | 4 | 0.0 | 0.8 |
| sql/staging/02_create_staging_tables.sql | 9 | 0.0 | 0.11 |
| @load_staging | 8 |  | 274.51 |
| @load_expected | 45 |  | 0.35 |
| sql/schema/03_create_dimension_tables.sql | 6 | 0.0 | 0.04 |
| sql/schema/04_create_fact_tables.sql | 6 | 0.0 | 0.03 |
| sql/schema/05_create_keys_and_constraints.sql | 6 | 0.0 | 0.14 |
| sql/schema/06_create_indexes.sql | 2 | 0.0 | 0.09 |
| sql/transformations/07_load_dimensions.sql | 6 | 0.0 | 2.58 |
| sql/transformations/08_load_facts.sql | 8 | 0.0 | 170.17 |

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
| recon | actual | TABLE | 0 |
| recon | expected | TABLE | 45 |
| stg | dim_date | TABLE | 731 |
| stg | dim_product | TABLE | 601 |
| stg | dim_store | TABLE | 20 |
| stg | fact_inventory | TABLE | 939,249 |
| stg | fact_promotions | TABLE | 49,430 |
| stg | fact_returns | TABLE | 34,562 |
| stg | fact_sales | TABLE | 1,339,510 |
| stg | fact_targets | TABLE | 2,077 |
