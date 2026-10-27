{#- Pre-flight check, run once before any model (on-run-start in dbt_project.yml). It stops the run with one
    plain instruction instead of a DuckDB error per model when:
      * dbt was started outside the dbt folder (the input paths are relative to it),
      * the data release was not extracted, or was extracted into a subfolder (README Step 4),
      * Phase 3 has not run, so the curated files are missing (README Step 5),
      * a Phase 3 report the reconciliation reads is missing.
    It also notes the DuckDB version when it differs from the one the port was verified with. -#}
{% macro check_inputs() %}
  {%- if not execute -%}{{ return('') }}{%- endif -%}
  {%- set root = var('project_root') -%}
  {%- set curated = [] -%}
  {%- for t in var('curated_tables') -%}{%- do curated.append('data/processed/curated/' ~ t ~ '.csv') -%}{%- endfor -%}
  {%- set groups = [
        ('project', ['dbt/dbt_project.yml'],
         "dbt must run from the dbt folder of the project: cd dbt, then run the command again "
         ~ "(the input paths are relative to that folder). To run it from elsewhere, pass "
         ~ "--vars \"{project_root: '<full path to the project folder>'}\"."),
        ('raw', ['data/raw/dim_store.csv', 'data/raw/dim_product.csv', 'data/raw/dim_date.csv',
                 'data/raw/fact_sales.csv', 'data/raw/fact_sales_late_batch.csv', 'data/raw/fact_inventory.csv',
                 'data/raw/fact_returns.csv', 'data/raw/fact_promotions.csv', 'data/raw/fact_targets.csv'],
         "The raw data is missing from data/raw. Download and extract the data release first (README Step 4)."),
        ('curated', curated,
         "The curated data is missing from data/processed/curated. Run Phase 3 first: "
         ~ "python -m src.data_quality.run_dq, then git checkout -- reports (README Step 5)."),
        ('reports', ['reports/phase3/lineage.json', 'reports/phase3/kpi_reconciliation.csv',
                     'reports/phase3/dq_rule_results.csv', 'reports/phase3/dq_rule_catalogue.csv',
                     'reports/phase4/reconciliation_results_duckdb.csv', 'reports/phase4/kpi_validation_duckdb.csv'],
         "A committed report is missing. Restore the reports with git checkout -- reports (README Step 5).")
      ] -%}
  {%- set checks = [] -%}
  {%- for group, files, _ in groups -%}
    {%- for f in files -%}
      {%- do checks.append("select '" ~ group ~ "' as grp, '" ~ f ~ "' as file, (select count(*) from glob('"
                           ~ root ~ "/" ~ f ~ "')) as found") -%}
    {%- endfor -%}
  {%- endfor -%}
  {%- set missing = run_query(checks | join(' union all ')) -%}
  {%- set absent = {} -%}
  {%- for row in missing.rows -%}
    {%- if row[2] == 0 -%}{%- do absent.setdefault(row[0], []).append(row[1]) -%}{%- endif -%}
  {%- endfor -%}
  {%- for group, files, message in groups -%}
    {%- if group in absent -%}
      {%- set extra = '' -%}
      {%- if group == 'raw' -%}
        {%- set nested = run_query("select file from glob('" ~ root ~ "/*/data/raw/fact_sales.csv') as g(file) union all "
                                   ~ "select file from glob('" ~ root ~ "/data/*/data/raw/fact_sales.csv') as g(file)") -%}
        {%- if nested.rows | length > 0 -%}
          {%- set extra = " The zip looks extracted into a subfolder (found " ~ nested.rows[0][0]
                          ~ "): extract it in the project folder itself, so that data/raw is directly inside it." -%}
        {%- endif -%}
      {%- endif -%}
      {{ exceptions.raise_compiler_error(message ~ extra ~ " Missing: " ~ (absent[group][:3] | join(', '))
                                         ~ ('' if absent[group] | length <= 3 else ' and ' ~ (absent[group] | length - 3) ~ ' more') ~ ".") }}
    {%- endif -%}
  {%- endfor -%}
  {%- set version = run_query("select version()").rows[0][0] -%}
  {%- if version != 'v1.5.6' -%}
    {{ log("Note: DuckDB " ~ version ~ " is in use; the dbt port was verified with DuckDB v1.5.6 (requirements-dbt.txt).", info=True) }}
  {%- endif -%}
  {{ return('') }}
{% endmacro %}
