-- DD-01: one row per calendar day for the whole period, keys unique (dimensions.clean_dim_date).
-- Failing rows: period days missing from dim_date, rows outside the period or unparseable, repeated dates
-- and repeated date keys.
{% set population %}select * from {{ ref('int_dq__dim_date') }}{% endset %}
{% set failing %}
    select cast(cast(d as date) as varchar) as row_key
    from generate_series(timestamp '{{ var("period_start") }}', timestamp '{{ var("period_end") }}', interval 1 day) as t(d)
    where cast(d as date) not in (select calendar_date from population where calendar_date is not null)
    union all
    select coalesce(cast(calendar_date as varchar), date_key_raw) from population
    where calendar_date is null or calendar_date not between date '{{ var("period_start") }}' and date '{{ var("period_end") }}'
    union all
    select cast(calendar_date as varchar) from population group by calendar_date having count(*) > 1
    union all
    select cast(date_key as varchar) from population group by date_key having count(*) > 1
{% endset %}
{{ dq_result('DD-01', 0, 731, population, failing) }}
