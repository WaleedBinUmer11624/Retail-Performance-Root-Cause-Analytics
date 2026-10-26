-- DD-03: retail weeks have 7 days (dimensions.clean_dim_date). Checked per retail week.
{% set population %}
    select retail_year, retail_week, count(*) as days from {{ ref('int_dq__dim_date') }}
    where retail_year is not null and retail_week is not null group by retail_year, retail_week
{% endset %}
{% set failing %}select retail_year || '|' || retail_week as row_key from population where days <> 7{% endset %}
{{ dq_result('DD-03', 1, 105, population, failing) }}
