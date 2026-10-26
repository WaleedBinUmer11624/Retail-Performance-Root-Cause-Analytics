-- TC-03: store-day revenue not far below the store's usual level (completeness.low_volume_days): below
-- 30% of the median of the same weekday over a centred 9-week window, with at least 5 weeks present.
{% set population %}
    select store_id, transaction_date, sum(revenue) as rev
    from {{ ref('int_dq__sales_curated') }} where stage = 'kept' group by store_id, transaction_date
{% endset %}
{% set failing %}
    select store_id || '|' || cast(transaction_date as varchar) as row_key
    from (
        select *, median(rev) over w as typical, count(rev) over w as weeks
        from population
        window w as (partition by store_id, isodow(transaction_date) order by transaction_date
                     rows between 4 preceding and 4 following)
    )
    where weeks >= 5 and rev / typical < {{ var('low_volume_day_ratio') }}
{% endset %}
{{ dq_result('TC-03', 0, 14578, population, failing) }}
