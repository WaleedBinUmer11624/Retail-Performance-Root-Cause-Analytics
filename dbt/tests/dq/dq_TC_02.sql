-- TC-02: every store has POS data for every trading day (completeness.store_day_coverage). Checked on the
-- grid of trading stores x trading days; a gap is a store-day with no line from the main extract (Phase 3
-- then reports whether the late file filled it).
{% set population %}
    select s.store_id, d.calendar_date
    from (select distinct store_id from {{ ref('int_dq__sales_curated') }} where stage = 'kept') as s
    cross join (select calendar_date from {{ ref('int_dq__dim_date') }} where is_trading_day) as d
{% endset %}
{% set failing %}
    select p.store_id || '|' || cast(p.calendar_date as varchar) as row_key
    from population as p
    left join (select distinct store_id, transaction_date from {{ ref('int_dq__sales_curated') }}
               where stage = 'kept' and source_file = 'fact_sales.csv') as m
           on m.store_id = p.store_id and m.transaction_date = p.calendar_date
    where m.store_id is null
{% endset %}
{{ dq_result('TC-02', 15, 14580, population, failing) }}
