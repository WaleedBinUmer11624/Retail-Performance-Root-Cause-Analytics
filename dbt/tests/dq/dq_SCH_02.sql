-- SCH-02: values parse to the contract type, blanks counted separately (profiling.profile_table). Checked
-- on every cell of the nine raw extracts; each column's type comes from seeds/dq_contract.csv (str if absent).
{% set population %}
    select 'dim_store' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__dim_store') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
    union all
    select 'dim_product' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__dim_product') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
    union all
    select 'dim_date' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__dim_date') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
    union all
    select 'fact_sales' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__fact_sales') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
    union all
    select 'fact_sales_late_batch' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__fact_sales_late_batch') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
    union all
    select 'fact_inventory' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__fact_inventory') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
    union all
    select 'fact_returns' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__fact_returns') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
    union all
    select 'fact_promotions' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__fact_promotions') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
    union all
    select 'fact_targets' as table_name, source_row, column_name, value
    from {{ ref('stg_raw__fact_targets') }}
    unpivot include nulls (value for column_name in (columns(* exclude (source_file, source_row))))
{% endset %}
{% set failing %}
    select v.table_name || '|' || v.column_name || '|' || v.source_row as row_key
    from population as v
    left join {{ ref('dq_contract') }} as c on c.table_name = v.table_name and c.column_name = v.column_name
    where case coalesce(c.contract_type, 'str')
             when 'int' then {{ type_failure('v.value', 'int') }}
             when 'decimal' then {{ type_failure('v.value', 'decimal') }}
             when 'date' then {{ type_failure('v.value', 'date') }}
             when 'datetime' then {{ type_failure('v.value', 'datetime') }}
             when 'time' then {{ type_failure('v.value', 'time') }}
             when 'bool' then {{ type_failure('v.value', 'bool') }}
             else false end
{% endset %}
{{ dq_result('SCH-02', 3047, 32979566, population, failing) }}
