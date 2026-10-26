-- TC-06: a target for every store and retail week (promotions_targets.target_gaps). Checked on the grid of
-- trading stores x full retail weeks of the target years; failing rows are store-weeks without a target.
{% set population %}
    select s.store_id, w.retail_year, w.retail_week
    from (select distinct store_id from {{ ref('int_dq__sales_curated') }} where stage = 'kept') as s
    cross join (
        select retail_year, retail_week from {{ ref('int_dq__dim_date') }}
        where retail_year in (select distinct retail_year from {{ ref('int_dq__targets') }} where stage = 'kept')
        group by retail_year, retail_week having count(*) = 7
    ) as w
{% endset %}
{% set failing %}
    select p.store_id || '|' || p.retail_year || '|' || p.retail_week as row_key
    from population as p
    left join (select * from {{ ref('int_dq__targets') }} where stage = 'kept') as t
           on t.store_id = p.store_id and t.retail_year = p.retail_year and t.retail_week = p.retail_week
    where t.store_id is null
{% endset %}
{{ dq_result('TC-06', 3, 2080, population, failing) }}
