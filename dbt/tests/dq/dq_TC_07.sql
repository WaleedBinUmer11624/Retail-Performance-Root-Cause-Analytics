-- TC-07: POS units equal stock-system sold units per store-SKU-week (returns_inventory.reconcile_pos_to_stock),
-- on the curated sales and stock up to the last full retail week. Checked on every store-SKU-week with units
-- on either side.
{% set population %}
    with calendar as (
        select calendar_date, retail_week_start + interval 6 day as week_end from {{ ref('int_dq__dim_date') }}
    ),
    last_week as (
        select max(last_day) as week_end from (
            select max(calendar_date) as last_day from {{ ref('int_dq__dim_date') }}
            group by retail_year, retail_week having count(*) = 7)
    ),
    pos as (
        select s.store_id, s.product_id, cast(c.week_end as date) as week_end, sum(s.quantity) as pos
        from {{ ref('int_dq__sales_curated') }} as s
        join calendar as c on c.calendar_date = s.transaction_date
        where s.stage = 'kept' and c.week_end <= (select week_end from last_week)
        group by 1, 2, 3
    ),
    stock as (
        select store_id, product_id, snapshot_date as week_end, arg_min(sold_qty, source_row) as stock
        from {{ ref('int_dq__inventory') }}
        where snapshot_date <= (select week_end from last_week)
        group by 1, 2, 3
    )
    select coalesce(p.store_id, k.store_id) as store_id, coalesce(p.product_id, k.product_id) as product_id,
           coalesce(p.week_end, k.week_end) as week_end, coalesce(p.pos, 0) as pos, coalesce(k.stock, 0) as stock
    from pos as p
    full join stock as k on k.store_id = p.store_id and k.product_id = p.product_id and k.week_end = p.week_end
    where coalesce(p.pos, 0) <> 0 or coalesce(k.stock, 0) <> 0
{% endset %}
{% set failing %}
    select store_id || '|' || product_id || '|' || cast(week_end as varchar) as row_key from population where pos <> stock
{% endset %}
{{ dq_result('TC-07', 2610, 492005, population, failing) }}
