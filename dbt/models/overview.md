{% docs __overview__ %}
# Brightwater: dbt port of the governed layer

A reconciled port of the governed Phase 3 data-quality pipeline and Phase 4 star schema, not a replacement.
The governed build (`src/data_quality`, `src/sql_model`, `sql/`) stays the system of record; every figure here
is tested against it.

| dbt layer | Schema | Governed stage |
|---|---|---|
| staging/raw | `stg_raw` | Phase 3 inputs: the nine raw extracts, as text |
| intermediate/dq | `int_dq` | Phase 3 data-quality stages (`src/data_quality`), in Phase 3 order |
| staging/curated | `stg` | Phase 4 staging: the Phase 3 curated files, as text (`sql/staging/02`) |
| intermediate/dw | `dw` | Phase 4 star schema (`sql/transformations/07`, `08`), generated from the T-SQL |
| marts | `mart` | Phase 4 governed views (`sql/analysis/10`), generated from the T-SQL |
| recon | `recon` | Phase 4 reconciliation and KPI validation (`sql/validation/09`, `11`) |

Tests: the 85 Phase 3 rules (each asserts Phase 3's exact rows_failed and rows_checked), the 45 reconciliation
metrics, the 38 KPI checks, the H1 and H2 2025 headlines, equality with the governed DuckDB results and with the
curated files.
{% enddocs %}
