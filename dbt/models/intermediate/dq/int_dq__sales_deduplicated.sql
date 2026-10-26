-- One copy of every POS line (after FS-01), with the key and sign treatments in Phase 3 order:
--   FS-02 / FS-03 date taken from the transaction ID, FS-04 store taken from the transaction ID,
--   FS-08 sign-inverted line turned back, FS-12 sign-inverted money fields turned back,
--   FS-09 flag for implausible bulk quantities (quarantined in the next stage).
with base as (
    select r.*,
           {{ to_num('quantity') }} as qty0, {{ to_num('unit_price') }} as price0, {{ to_num('discount') }} as disc0,
           {{ to_num('revenue') }} as rev0, {{ to_num('unit_cost') }} as unit_cost_n, {{ to_num('cost') }} as cost0,
           {{ to_num('margin') }} as margin0,
           {{ parse_iso('transaction_date') }} as iso_dt,
           {{ parse_dmy('transaction_date') }} as dmy_dt,
           {{ matches('transaction_id', '^S\\d{2}-\\d{8}-\\d{5}$') }} and id_dt is not null as tid_ok,
           s.store_id is not null as store_known
    from {{ ref('int_dq__sales_received') }} as r
    left join (select store_id from {{ ref('int_dq__dim_store') }}) as s on s.store_id = r.store_id
    where not r.fs_01_fail
),
dated as (
    select *,
           iso_dt is null and dmy_dt is not null and dmy_dt = id_dt as fs_02_fail,
           not coalesce(coalesce(iso_dt, dmy_dt) between date '{{ var("period_start") }}' and date '{{ var("period_end") }}'
                        and coalesce(iso_dt, dmy_dt) = id_dt, false) as bad_date,
           not store_known or coalesce(store_id <> {{ id_store('transaction_id') }}, true) as fs_04_fail,
           coalesce(qty0 < 0, false) as fs_08_fail
    from base
),
signed as (
    select *,
           bad_date and not fs_02_fail as fs_03_fail,
           case when fs_08_fail then -qty0 else qty0 end as qty1,
           case when fs_08_fail then abs(-disc0) else disc0 end as disc1,
           case when fs_08_fail then -rev0 else rev0 end as rev1,
           case when fs_08_fail then -cost0 else cost0 end as cost1,
           case when fs_08_fail then -margin0 else margin0 end as margin1,
           coalesce(price0 < 0, false) as fs_12_fail
    from dated
)
select source_file, source_row, file_order, received_order, row_key, transaction_id, line_no,
       transaction_date as transaction_date_raw, transaction_time,
       store_id as store_id_raw, product_id as product_id_raw, category as category_raw,
       promotion_id as promotion_id_raw, quantity as quantity_raw, unit_price as unit_price_raw,
       extract_batch_id, extract_timestamp, extract_ts, extract_lag_days, tc_01_fail,
       id_dt as transaction_date,
       case when fs_04_fail then {{ id_store('transaction_id') }} else store_id end as store_id,
       tid_ok,
       fs_02_fail, fs_03_fail, fs_04_fail, fs_08_fail, fs_12_fail,
       qty1 as quantity,
       case when fs_12_fail then abs(price0) else price0 end as unit_price,
       case when fs_12_fail then abs(disc1) else disc1 end as discount,
       case when fs_12_fail then abs(rev1) else rev1 end as revenue,
       unit_cost_n as unit_cost,
       cost1 as cost,
       case when fs_12_fail then {{ np_round('abs(rev1) - cost1') }} else margin1 end as margin,
       rev0 as revenue_received,
       coalesce(qty1 > {{ var('max_plausible_line_quantity') }}, false) as fs_09_fail
from signed
