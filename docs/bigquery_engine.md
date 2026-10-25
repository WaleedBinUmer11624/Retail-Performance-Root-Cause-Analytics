# BigQuery build of the star schema (optional third engine)

The Phase 4 star schema (5 dimension and 5 fact tables), its KPI layer and its reconciliation can be
built in Google BigQuery as well as in SQL Server (the target) and DuckDB (the local verification
engine). It is additive: the Phase 4 scripts, the frozen `src/sql_model` code and every manifest are
unchanged. The BigQuery engine reads the same configuration (`config/sql_model_config.yaml`), the same
SHA-256-verified curated files and the same Phase 3 expected values, and applies the same pass
criteria: 45/45 reconciliation checks and 38/38 KPI validation checks. It also checks the governed
estate figures: H2 2025 net revenue EUR 9,457,457.05 (-7.18%) and H1 2025 EUR 8,629,984.78 (+1.438%).

| Item | Location |
| --- | --- |
| Engine and translation rules | `src/bigquery_model/engine.py` |
| Build runner | `src/bigquery_model/run_bigquery.py` |
| Settings (no project ID) | `config/bigquery_config.yaml` |
| Tests | `tests/test_bigquery_model.py` |
| Build outputs | `reports/bigquery/` |
| Optional dependency | `requirements-bigquery.txt` |

## How to rebuild

1. Install the client: `python -m pip install -r requirements-bigquery.txt`.
2. Authenticate with Application Default Credentials only: `gcloud auth application-default login`.
   No key file is used or stored.
3. Give the project ID outside the repository, either as an environment variable
   (`$env:BQ_PROJECT_ID = "your-project-id"` in PowerShell) or in `config/bigquery_local.yaml`
   (`project_id: your-project-id`), which is listed in `.gitignore`.
4. Build and reconcile: `python -m src.bigquery_model.run_bigquery`. Exit code 0 only when every check passes.
5. Remove the datasets when finished: `python -m src.bigquery_model.run_bigquery --teardown`.

The build creates four datasets in location EU: `brightwater_stg`, `brightwater_dw`, `brightwater_mart`
and `brightwater_recon`. A rebuild replaces every table and view. The staged curated files are reused
only when a staging table's recorded SHA-256 and row count match the verified curated file, which
avoids uploading the same 0.3 GB again; otherwise they are reloaded.

## Dialect differences

Each T-SQL statement is parsed with sqlglot's T-SQL dialect and generated in the BigQuery dialect.
sqlglot handles most differences on its own, for example `TRY_CONVERT` to `SAFE_CAST`, `IIF` to `IF`,
`DATEDIFF` to `DATE_DIFF`, `FLOAT` to `FLOAT64`, `[name]` to backquoted names and `SELECT ... INTO` to
`CREATE TABLE ... AS SELECT`. Where the generated SQL is not valid or not equivalent on BigQuery, a
named rule rewrites the parsed statement first. Every application is logged in
`reports/bigquery/translation_rules_bigquery.csv`.

| Rule | What is rewritten, and why |
| --- | --- |
| `R1_national_literal` | T-SQL `N'...'` literals become plain `'...'`: BigQuery has no `N` prefix (syntax error). |
| `R2_decimal_cast` | `CAST(x AS DECIMAL(p,s))` becomes `ROUND(CAST(x AS NUMERIC), s)`. BigQuery rejects parameterized types in `CAST`; T-SQL rounds to `s` places, so the rounding is kept. |
| `R3_text_cast` | `CAST(x AS NVARCHAR(n))` becomes `CAST(x AS STRING)`; the length is not allowed in `CAST`. |
| `R4_dataset_qualify` | BigQuery has datasets, not schemas: `stg`, `dw`, `mart` and `recon` become the prefixed datasets in the configured project. |
| `R5_insert_to_ctas` | No DML in the sandbox: a table's `INSERT` statements are combined with `UNION ALL` into one `CREATE OR REPLACE TABLE ... AS SELECT`, every value cast to the type the Phase 4 DDL declares, in DDL column order. |
| `R6_skip_clear` | `DELETE` and `TRUNCATE` before a reload are skipped: the reload replaces the table. |
| `R7_replace_objects` | `CREATE OR ALTER VIEW` and `SELECT ... INTO` become `CREATE OR REPLACE`, so a rebuild is re-runnable. |
| `R8_table_ddl` | `CREATE TABLE` keeps names and types; keys and other constraints are dropped (BigQuery does not enforce them). |
| `R9_skip_session` | `SET NOCOUNT ON` has no BigQuery equivalent and is skipped. |
| `R10_percentile_cont` | `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x) OVER (...)` becomes `PERCENTILE_CONT(x, 0.5) OVER (...)`: the same exact median, in BigQuery's syntax (no approximation). |
| `R11_time_precision` | `CAST(x AS TIME(0))` becomes `CAST(x AS TIME)` (precision is not allowed in `CAST`). T-SQL also converts `'HH:MM'` text to `TIME`, which BigQuery's cast rejects, so text becomes `COALESCE(SAFE_CAST(x AS TIME), SAFE.PARSE_TIME('%H:%M', x))`. Without this, every curated `transaction_time` (format `HH:MM`) became NULL and the `conversion_failures` check failed with 1,339,510. |
| `R12_concat_to_string` | T-SQL `CONCAT` converts numbers to text implicitly; BigQuery's needs `STRING`, so non-text arguments are cast (NULLs still become empty text). |
| `R13_integer_types` | `TINYINT`, `SMALLINT`, `INT` and `BIT` casts become `INT64`; sqlglot keeps `TINYINT` as `UTINYINT`, which BigQuery does not have. |
| `R14_self_reference_guard` | The UNKNOWN-member guard `INSERT ... WHERE NOT EXISTS (SELECT 1 FROM <same table> ...)` reads the rows written just before. Inside one `CREATE OR REPLACE` the table is still the previous build, so the guard reads a CTE of the earlier rows (same meaning as T-SQL), and the guard row gets a one-row `FROM`. |
| `R15_keep_staging` | `DROP TABLE` of a staging table is skipped and the table is created only if missing. Its rows are always replaced by the load job, or kept only when the recorded SHA-256 and row count match the verified curated file, so the result equals the T-SQL drop and reload. |

Not executed on BigQuery, as on DuckDB: the `@tsql-only` batches, namely database creation (script
01), enforced keys and constraints (05), columnstore indexes (06 and the index maintenance in 08) and
the `THROW` that stops a SQL Server build on a failed check. The pass criteria are applied by the
runner instead, from the same reconciliation views.

## Cost and quota notes

- **Sandbox and free tier only.** The project has no billing account, so BigQuery runs as a sandbox:
  10 GB of storage and 1 TB of queries a month at no cost, and no DML. The build therefore never
  sends `INSERT`, `UPDATE`, `DELETE`, `MERGE` or `TRUNCATE`; data arrives by load jobs (free) and every
  table is built by `CREATE OR REPLACE TABLE ... AS SELECT`.
- **No streaming inserts.** Staging files and the expected values are sent as load jobs.
- **A cap on every query.** Each query job carries `maximum_bytes_billed`
  (`config/bigquery_config.yaml`, 2 GiB), so a query that would scan more fails instead of running.
  The largest build query, the sales fact, reads about 0.24 GB.
- **Sandbox expiry.** Sandbox tables expire after 60 days. Rebuild when needed, or remove the datasets
  with `--teardown`.
- **Location EU** for all datasets and jobs.

## Last verified build

From `reports/bigquery/run_summary_bigquery.json` (2026-10-25, sandbox project, location EU):

| Check | Result |
| --- | --- |
| Reconciliation against Phase 3 | 45/45 PASS |
| KPI layer validation | 38/38 PASS |
| H2 2025 estate net revenue | EUR 9,457,457.05, YoY -7.18% (PASS) |
| H1 2025 estate net revenue | EUR 8,629,984.78, YoY +1.438% (PASS) |
| Objects | 48 (10 dw tables, 17 mart views and 1 table, 3 recon views and 9 tables, 8 stg tables); names, types and row counts identical to the SQL Server build |
| Against DuckDB and SQL Server | 166 values compared: 160 identical; 6 differ by at most 3.6e-15 (floating-point rounding in two ratios, see KI-07) |
| Query bytes billed | 1.72 GB for a full build; largest single query 0.24 GB |

A full build with a fresh upload takes about 8 to 10 minutes; with the staged files reused, the queries
alone take 5 to 15 minutes in the sandbox (job latency varies).

Run the tests with `python -m pytest tests/test_bigquery_model.py`. The offline tests always run; the
live tests query the build and skip unless the client, credentials, project ID and datasets exist.
