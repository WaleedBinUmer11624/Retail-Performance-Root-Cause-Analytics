-- fact_returns through the FR rules (returns_inventory.clean_returns), one row per raw record.
-- Links are tested against every distinct sale line received (FR-04) and against the curated sale
-- lines (FR-05 to FR-10). stage: 'fr_01' duplicate, 'fr_02' reused ID, 'fr_05_06' impossible return,
-- 'kept' curated return.
with raw as (
    select *,
           row_number() over (partition by return_id, return_date, store_id, original_transaction_id, original_line_number,
                                           product_id, return_quantity, refund_value, return_reason, restockable_flag
                              order by source_row) > 1 as fr_01_fail
    from {{ ref('stg_raw__fact_returns') }}
),
unique_rows as (
    select *, count(*) over (partition by return_id) > 1 as fr_02_fail from raw where not fr_01_fail
),
typed as (
    select u.*,
           {{ parse_iso('u.return_date') }} as return_dt,
           {{ to_num('u.return_quantity') }} as qty,
           {{ to_num('u.refund_value') }} as refund,
           not {{ is_blank('u.original_transaction_id') }} as has_receipt,
           coalesce(case when {{ is_blank('u.original_transaction_id') }} then null else u.original_transaction_id end, '')
             || '|' || coalesce(cast(try_cast({{ to_num('u.original_line_number') }} as bigint) as varchar), '<NA>') as sale_key
    from unique_rows as u
),
linked as (
    select t.*,
           not t.fr_02_fail and t.has_receipt and r.row_key is not null as found,
           t.has_receipt and r.row_key is not null and l.row_key is not null as via_late,
           c.row_key is not null and t.has_receipt and r.row_key is not null as is_linked_curated,
           c.quantity as sale_qty, c.revenue as sale_revenue, c.product_id as sale_product, c.store_id as sale_store,
           {{ id_date('t.original_transaction_id') }} as sale_dt
    from typed as t
    left join (select distinct row_key from {{ ref('int_dq__sales_deduplicated') }}) as r on r.row_key = t.sale_key
    left join (select distinct transaction_id || '|' || line_number as row_key
               from {{ ref('stg_raw__fact_sales_late_batch') }}) as l on l.row_key = t.sale_key
    left join (select * from {{ ref('int_dq__sales_curated') }} where stage = 'kept') as c on c.row_key = t.sale_key
),
checked as (
    select *,
           is_linked_curated and coalesce(return_dt < sale_dt, false) as fr_05_fail,
           is_linked_curated and coalesce(qty > sale_qty, false) as fr_06_fail,
           date_diff('day', sale_dt, return_dt) as lag_days,
           case when strftime(sale_dt, '%m-%d') between '{{ var("christmas_return_window")["purchase_from"] }}'
                                                     and '{{ var("christmas_return_window")["purchase_to"] }}'
                then greatest({{ var('return_policy_days') }},
                              date_diff('day', sale_dt, cast((year(sale_dt) + 1) || '-{{ var("christmas_return_window")["return_by"] }}' as date)))
                else {{ var('return_policy_days') }} end as policy_days
    from linked
)
select source_row, return_id as row_key, return_id, store_id, product_id, return_dt as return_date, qty as return_quantity,
       refund as refund_value, return_reason, restockable_flag, original_transaction_id, original_line_number, sale_key,
       has_receipt, found, via_late, is_linked_curated,
       not has_receipt as fr_03_fail,
       has_receipt and not found as fr_04_fail,
       fr_05_fail, fr_06_fail,
       is_linked_curated and not (fr_05_fail or fr_06_fail)
         and coalesce(refund > sale_revenue / sale_quantity_safe * qty + {{ var('money_tolerance') }}, false) as fr_07_fail,
       is_linked_curated and coalesce(sale_product <> 'UNKNOWN' and sale_product <> product_id, false) as fr_08_fail,
       is_linked_curated and coalesce(sale_store <> store_id, true) as fr_09_fail,
       is_linked_curated and not (fr_05_fail or fr_06_fail) and coalesce(lag_days > policy_days, false) as fr_10_fail,
       coalesce(qty <= 0, false) or coalesce(refund <= 0, false) or qty is null
         or coalesce(return_reason not in {{ in_list(var('return_reasons')) }}, true)
         or coalesce(restockable_flag not in ('True', 'False'), true)
         or store_id not in (select store_id from {{ ref('int_dq__dim_store') }}) or store_id is null
         or product_id not in (select product_id from {{ ref('int_dq__dim_product') }} where is_kept and product_id <> 'UNKNOWN')
         or product_id is null
         or not coalesce(return_dt between date '{{ var("period_start") }}' and date '{{ var("period_end") }}', false) as fr_11_fail,
       fr_02_fail,
       case when fr_02_fail then 'fr_02' when fr_05_fail or fr_06_fail then 'fr_05_06' else 'kept' end as stage
from (select *, nullif(sale_qty, 0) as sale_quantity_safe from checked)
