-- fact_inventory through the FI rules (returns_inventory.clean_inventory), one row per record left after
-- FI-01 (exact duplicates) and FI-02 (conflicting snapshots for one key, see int_dq__inventory_received):
--   FI-04 received_qty derived from the stock identity, FI-05 sign of closing_stock corrected,
--   FI-06 identity breaks triangulated with the neighbouring weeks, then FI-07 to FI-10 on the result.
{%- set int_cols = ['retail_year', 'retail_week', 'opening_stock', 'received_qty', 'sold_qty', 'adjustment_qty', 'closing_stock'] %}
with unique_rows as (
    select * from {{ ref('int_dq__inventory_received') }} where not fi_01_fail
),
typed as (
    select source_row, store_id, product_id, fi_02_fail,
           ({% for c in int_cols %}coalesce(contains({{ c }}, '.'), false){{ ' or ' if not loop.last }}{% endfor %}) as fi_03_fail,
           {% for c in int_cols %}{{ to_num(c) }} as {{ c }},
           {% endfor %}{{ parse_iso('snapshot_date') }} as snapshot_date
    from unique_rows where not fi_02_fail
),
received as (
    select * exclude (received_qty),
           received_qty is null as fi_04_fail,
           received_qty is null and coalesce(closing_stock - opening_stock + sold_qty - adjustment_qty >= 0, false)
             and coalesce(closing_stock >= 0, false) as fi_04_derived,
           case when received_qty is null and coalesce(closing_stock - opening_stock + sold_qty - adjustment_qty >= 0, false)
                     and coalesce(closing_stock >= 0, false)
                then closing_stock - opening_stock + sold_qty - adjustment_qty else received_qty end as received_qty
    from typed
),
signed as (
    select * exclude (closing_stock),
           coalesce(closing_stock < 0, false) as fi_05_fail,
           coalesce(closing_stock < 0 and closing_stock = -(opening_stock + received_qty - sold_qty + adjustment_qty), false)
               as fi_05_fixed,
           case when coalesce(closing_stock < 0 and closing_stock = -(opening_stock + received_qty - sold_qty + adjustment_qty), false)
                then opening_stock + received_qty - sold_qty + adjustment_qty else closing_stock end as closing_stock
    from received
),
neighbours as (
    select *,
           lag(closing_stock) over w as prev_close,
           lag(snapshot_date) over w as prev_date,
           lead(opening_stock) over w as next_open,
           lead(snapshot_date) over w as next_date,
           received_qty - sold_qty + adjustment_qty as flow
    from signed
    window w as (partition by store_id, product_id order by snapshot_date)
),
breaks as (
    select *,
           coalesce(date_diff('day', prev_date, snapshot_date) = 7, false) as has_prev,
           coalesce(date_diff('day', snapshot_date, next_date) = 7, false) as has_next,
           coalesce(opening_stock + flow <> closing_stock, true) as fi_06_fail
    from neighbours
),
triangulated as (
    select *,
           fi_06_fail and has_prev and coalesce(prev_close + flow = closing_stock, false)
             and (not has_next or coalesce(next_open = closing_stock, false)) as fi_06_open_wrong
    from breaks
),
triangulated2 as (
    select *,
           fi_06_fail and not fi_06_open_wrong and has_next and coalesce(next_open = opening_stock + flow, false) as fi_06_close_wrong
    from triangulated
),
corrected as (
    select * exclude (opening_stock, closing_stock),
           case when fi_06_open_wrong then prev_close else opening_stock end as opening_stock,
           case when fi_06_close_wrong then opening_stock + flow else closing_stock end as closing_stock,
           fi_06_fail and not fi_06_open_wrong and not fi_06_close_wrong as fi_06_unresolved
    from triangulated2
),
continuity as (
    select *, lag(closing_stock) over (partition by store_id, product_id order by snapshot_date) as prev_close_after
    from corrected
),
calendar as (
    select calendar_date, retail_year as cal_retail_year, retail_week as cal_retail_week
    from {{ ref('int_dq__dim_date') }}
)
select c.source_row,
       c.store_id || '|' || c.product_id || '|' || coalesce(strftime(c.snapshot_date, '%Y-%m-%d'), '') as row_key,
       c.store_id, c.product_id, c.snapshot_date, c.retail_year, c.retail_week,
       c.opening_stock, c.received_qty, c.sold_qty, c.adjustment_qty, c.closing_stock,
       c.prev_date, c.has_prev,
       c.fi_03_fail, c.fi_04_fail, c.fi_04_derived, c.fi_05_fail, c.fi_05_fixed,
       c.fi_06_fail, c.fi_06_open_wrong, c.fi_06_close_wrong, c.fi_06_unresolved,
       c.has_prev and coalesce(c.opening_stock <> c.prev_close_after, true) as fi_07_fail,
       coalesce(c.opening_stock < 0, false) or coalesce(c.received_qty < 0, false) or coalesce(c.sold_qty < 0, false)
         or coalesce(c.closing_stock < 0, false) or coalesce(c.adjustment_qty > 0, false) as fi_08_fail,
       coalesce(isodow(c.snapshot_date) <> 7, true)
         or coalesce(k.cal_retail_week <> c.retail_week, true)
         or coalesce(k.cal_retail_year <> c.retail_year, true) as fi_09_fail,
       c.store_id not in (select store_id from {{ ref('int_dq__dim_store') }}) or c.store_id is null
         or c.product_id not in (select product_id from {{ ref('int_dq__dim_product') }} where is_kept and product_id <> 'UNKNOWN')
         or c.product_id is null as fi_10_fail
from continuity as c
left join calendar as k on k.calendar_date = c.snapshot_date
