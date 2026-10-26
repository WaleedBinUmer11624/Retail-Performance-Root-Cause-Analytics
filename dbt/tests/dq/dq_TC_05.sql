-- TC-05: no missing week inside a store-SKU stock series (returns_inventory.clean_inventory). Checked on the
-- snapshots plus the missing weeks; failing rows are the missing weeks.
{% set missing %}
    select g.store_id || '|' || g.product_id || '|' || strftime(cast(t.w as date), '%Y-%m-%d') as row_key
    from (
        select store_id, product_id, snapshot_date, prev_date from {{ ref('int_dq__inventory') }}
        where prev_date is not null and date_diff('day', prev_date, snapshot_date) > 7
    ) as g
    cross join unnest(generate_series(cast(g.prev_date + interval 7 day as timestamp),
                                      cast(g.snapshot_date - interval 7 day as timestamp), interval 7 day)) as t(w)
{% endset %}
{% set population %}
    select row_key from {{ ref('int_dq__inventory') }}
    union all
    {{ missing }}
{% endset %}
{{ dq_result('TC-05', 462, 939711, population, missing) }}
