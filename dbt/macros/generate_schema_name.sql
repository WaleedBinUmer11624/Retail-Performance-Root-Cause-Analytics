{#- Use the configured schema as is (stg, dw, mart, recon, ...), matching the governed
    database layout, instead of dbt's default "<target schema>_<custom schema>". -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
