-- The dbt data-quality port reproduces the Phase 3 curated files it ports: every key and every value of
-- fact_sales (all 24 columns), fact_returns, fact_inventory and fact_targets, and the keys of fact_promotions
-- (kept rows plus the FP-04 rows restored from POS lines). One row per difference.
with sales as (
    select coalesce(c.transaction_id, d.transaction_id) || '|' || coalesce(c.line_number, cast(d.line_no as varchar)) as row_key
    from {{ ref('stg_fact_sales') }} as c
    full join (select * from {{ ref('int_dq__sales_curated') }} where stage = 'kept') as d
      on d.transaction_id = c.transaction_id and d.line_no = cast(c.line_number as bigint)
    where c.transaction_id is null or d.transaction_id is null
       or c.transaction_date <> strftime(d.transaction_date, '%Y-%m-%d')
       or c.transaction_time is distinct from d.transaction_time
       or c.store_id is distinct from d.store_id or c.product_id is distinct from d.product_id
       or c.category is distinct from d.category
       or cast(c.quantity as double) is distinct from d.quantity
       or abs(cast(c.unit_price as double) - d.unit_price) > 1e-9 or abs(cast(c.discount as double) - d.discount) > 1e-9
       or abs(cast(c.revenue as double) - d.revenue) > 1e-9 or abs(cast(c.unit_cost as double) - d.unit_cost) > 1e-9
       or abs(cast(c.cost as double) - d.cost) > 1e-9 or abs(cast(c.margin as double) - d.margin) > 1e-9
       or c.promotion_id is distinct from d.promotion_id
       or c.extract_batch_id is distinct from d.extract_batch_id or c.extract_timestamp is distinct from d.extract_timestamp
       or cast(c.extract_lag_days as integer) is distinct from d.extract_lag_days
       or (c.is_late_arriving = 'True') is distinct from d.tc_01_fail
       or (c.is_imputed = 'True') is distinct from d.fs_11_imputed
       or c.dq_status is distinct from d.dq_status or coalesce(c.dq_rules, '') is distinct from d.dq_rules
       or c.source_file is distinct from d.source_file or cast(c.source_row as bigint) is distinct from d.source_row
),
returns as (
    select coalesce(c.return_id, d.return_id) as row_key
    from {{ ref('stg_fact_returns') }} as c
    full join (select * from {{ ref('int_dq__returns') }} where stage = 'kept') as d using (return_id)
    where c.return_id is null or d.return_id is null
       or abs(cast(c.refund_value as double) - d.refund_value) > 1e-9
       or cast(c.return_quantity as double) is distinct from d.return_quantity
       or c.store_id is distinct from d.store_id or c.product_id is distinct from d.product_id
       or c.return_date <> strftime(d.return_date, '%Y-%m-%d')
),
inventory as (
    select coalesce(d.row_key, c.store_id || '|' || c.product_id || '|' || c.snapshot_date) as row_key
    from {{ ref('stg_fact_inventory') }} as c
    full join {{ ref('int_dq__inventory') }} as d on d.row_key = c.store_id || '|' || c.product_id || '|' || c.snapshot_date
    where c.store_id is null or d.row_key is null
       {%- for col in ['retail_year', 'retail_week', 'opening_stock', 'received_qty', 'sold_qty', 'adjustment_qty', 'closing_stock'] %}
       or cast(c.{{ col }} as double) is distinct from d.{{ col }}
       {%- endfor %}
),
targets as (
    select coalesce(d.row_key, c.store_id || '|' || c.retail_year || '|' || c.retail_week) as row_key
    from {{ ref('stg_fact_targets') }} as c
    full join (select * from {{ ref('int_dq__targets') }} where stage = 'kept') as d
      on d.row_key = c.store_id || '|' || c.retail_year || '|' || c.retail_week
    where c.store_id is null or d.row_key is null
       or abs(cast(c.target_net_revenue as double) - d.target_net_revenue) > 1e-9
       or c.target_version is distinct from d.target_version
),
promotions as (
    select coalesce(c.k, d.k) as row_key
    from (select promotion_id || '|' || product_id || '|' || store_id || '|' || start_date || '|' || end_date as k,
                 count(*) as n
          from {{ ref('stg_fact_promotions') }} group by 1) as c
    full join (
        select promotion_id || '|' || product_id || '|' || store_id || '|' || strftime(start_date, '%Y-%m-%d') || '|'
               || strftime(end_date, '%Y-%m-%d') as k, count(*) as n
        from (select promotion_id, product_id, store_id, start_date, end_date
              from {{ ref('int_dq__promotions') }} where stage = 'kept'
              union all
              select promotion_id, product_id, store_id, start_date, end_date from {{ ref('int_dq__promotions_restored') }})
        group by 1) as d on d.k = c.k
    where c.k is null or d.k is null or c.n <> d.n
)
select 'fact_sales' as curated_file, row_key from sales
union all select 'fact_returns', row_key from returns
union all select 'fact_inventory', row_key from inventory
union all select 'fact_targets', row_key from targets
union all select 'fact_promotions', row_key from promotions
