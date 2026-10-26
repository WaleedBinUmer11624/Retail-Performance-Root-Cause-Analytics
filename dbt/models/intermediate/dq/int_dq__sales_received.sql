-- Every POS line received: the main extract plus the late file (sales.clean_sales, load step), with
-- typed working columns, the TC-01 lag and the FS-01 duplicate flag (later copies of a line;
-- the earliest extracted copy is kept, ties broken by file order).
with lines as (
    select *, 1 as file_order from {{ ref('stg_raw__fact_sales') }}
    union all by name
    select *, 2 as file_order from {{ ref('stg_raw__fact_sales_late_batch') }}
),
typed as (
    select *,
           try_cast({{ to_num('line_number') }} as bigint) as line_no,
           {{ parse_datetime('extract_timestamp') }} as extract_ts,
           {{ id_date('transaction_id') }} as id_dt,
           row_number() over (order by file_order, source_row) as received_order
    from lines
)
select *,
       coalesce(transaction_id, '') || '|' || coalesce(cast(line_no as varchar), '<NA>') as row_key,
       date_diff('day', id_dt, cast(extract_ts as date)) as extract_lag_days,
       coalesce(date_diff('day', id_dt, cast(extract_ts as date)) > {{ var('expected_max_lag_days') }}, false) as tc_01_fail,
       row_number() over (partition by coalesce(transaction_id, '') || '|' || coalesce(cast(line_no as varchar), '<NA>')
                          order by extract_ts nulls last, received_order) > 1 as fs_01_fail
from typed
