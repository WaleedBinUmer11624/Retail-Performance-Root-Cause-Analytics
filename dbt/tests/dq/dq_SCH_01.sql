-- SCH-01: expected columns are present (profiling.profile_table). Checked per raw extract; a table fails
-- when any column of its contract (seeds/dq_contract.csv) is missing from the file.
{% set population %}select distinct table_name from {{ ref('dq_contract') }}{% endset %}
{% set failing %}
    with received as (
    select 'dim_store' as table_name, column_name from (describe {{ ref('stg_raw__dim_store') }})
    union all
    select 'dim_product' as table_name, column_name from (describe {{ ref('stg_raw__dim_product') }})
    union all
    select 'dim_date' as table_name, column_name from (describe {{ ref('stg_raw__dim_date') }})
    union all
    select 'fact_sales' as table_name, column_name from (describe {{ ref('stg_raw__fact_sales') }})
    union all
    select 'fact_sales_late_batch' as table_name, column_name from (describe {{ ref('stg_raw__fact_sales_late_batch') }})
    union all
    select 'fact_inventory' as table_name, column_name from (describe {{ ref('stg_raw__fact_inventory') }})
    union all
    select 'fact_returns' as table_name, column_name from (describe {{ ref('stg_raw__fact_returns') }})
    union all
    select 'fact_promotions' as table_name, column_name from (describe {{ ref('stg_raw__fact_promotions') }})
    union all
    select 'fact_targets' as table_name, column_name from (describe {{ ref('stg_raw__fact_targets') }})
    )
    select distinct c.table_name as row_key
    from {{ ref('dq_contract') }} as c
    left join received as r on r.table_name = c.table_name and r.column_name = c.column_name
    where r.column_name is null
{% endset %}
{{ dq_result('SCH-01', 0, 9, population, failing) }}
