{#- Use the configured schema as is (stg, dw, mart, recon, ...), matching the governed
    database layout, instead of dbt's default "<target schema>_<custom schema>". -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {#- The port's SQL is DuckDB SQL (it reads the CSV files with read_csv), so it cannot run on another target.
        Stop at parse time, before any connection, with the alternative. -#}
    {%- if target.type != 'duckdb' -%}
        {{ exceptions.raise_compiler_error("The dbt port runs on DuckDB only: its models read the CSV files with DuckDB "
            ~ "(target '" ~ target.name ~ "' is " ~ target.type ~ "). Use the default target (--target duckdb). The "
            ~ "BigQuery build of the star schema is python -m src.bigquery_model.run_bigquery (docs/bigquery_engine.md).") }}
    {%- endif -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
