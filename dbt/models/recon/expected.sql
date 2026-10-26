{#- recon.expected: the governed runner step @load_expected (src/sql_model/inputs.py expected_metrics),
    ported to SQL. Expected values come only from Phase 3 outputs: curated row counts from
    reports/phase3/lineage.json, UNKNOWN-member counts from the curated files, and KPI values from
    reports/phase3/kpi_reconciliation.csv (column clean_complete). Each carries its absolute tolerance. -#}
{%- set tol = var('recon_tolerances') -%}
{%- set src_lin = 'reports/phase3/lineage.json (curated row counts)' -%}
{%- set src_cur = 'data/processed/curated (Phase 3 output)' -%}
with lin as (
    select outputs from {{ source('phase3_reports', 'lineage') }}
),
kpi as (
    select kpi, clean_complete from {{ source('phase3_reports', 'kpi_reconciliation') }}
),
rows as (
{%- for t in var('curated_tables') %}
    select 'rows_stg_{{ t }}' as metric_name, 'row_count' as metric_group, cast(outputs.{{ t }}.rows as double) as expected_value,
           {{ tol['row_count'] }} as tolerance_abs, '{{ src_lin }}' as expected_source from lin union all
{%- endfor %}
{%- for m, t in [('dim_date', 'dim_date'), ('dim_store', 'dim_store'), ('dim_product', 'dim_product'),
                 ('fact_sales', 'fact_sales'), ('fact_returns', 'fact_returns'), ('fact_inventory', 'fact_inventory'),
                 ('fact_targets', 'fact_targets'), ('fact_promotion_coverage', 'fact_promotions')] %}
    select 'rows_dw_{{ m }}', 'row_count', cast(outputs.{{ t }}.rows as double), {{ tol['row_count'] }}, '{{ src_lin }}' from lin union all
{%- endfor %}
    select 'rows_dw_dim_promotion', 'row_count', cast(count(distinct promotion_id) as double), {{ tol['row_count'] }},
           '{{ src_cur }}: distinct promotion_id' from {{ ref('stg_fact_promotions') }} union all
    select 'unknown_product_sales_lines', 'unknown_member', cast(count(*) filter (where product_id = 'UNKNOWN') as double),
           {{ tol['row_count'] }}, '{{ src_cur }}: product_id = UNKNOWN' from {{ ref('stg_fact_sales') }} union all
    select 'unknown_promotion_sales_lines', 'unknown_member', cast(count(*) filter (where promotion_id = 'UNKNOWN') as double),
           {{ tol['row_count'] }}, '{{ src_cur }}: promotion_id = UNKNOWN' from {{ ref('stg_fact_sales') }} union all
    select 'not_promoted_sales_lines', 'unknown_member', cast(count(*) filter (where promotion_id is null) as double),
           {{ tol['row_count'] }}, '{{ src_cur }}: promotion_id blank' from {{ ref('stg_fact_sales') }} union all
{%- for name in ['unknown_store_fact_rows', 'unknown_date_fact_rows', 'unknown_product_other_fact_rows', 'conversion_failures'] %}
    select '{{ name }}', '{{ "load_integrity" if name == "conversion_failures" else "unknown_member" }}', 0.0, {{ tol['row_count'] }},
           'must be zero: every curated key is valid (Phase 3 validation)' union all
{%- endfor %}
{%- for name, cls in var('kpi_tolerance_class').items() %}
    select '{{ name }}', 'kpi', cast(clean_complete as double), {{ tol[cls] }},
           'reports/phase3/kpi_reconciliation.csv (clean_complete)' from kpi where kpi = '{{ name }}'
    {%- if not loop.last %} union all{% endif %}
{%- endfor %}
)
select cast(metric_name as varchar) as metric_name, cast(metric_group as varchar) as metric_group,
       cast(expected_value as double) as expected_value, cast(tolerance_abs as double) as tolerance_abs,
       cast(expected_source as varchar) as expected_source
from rows
