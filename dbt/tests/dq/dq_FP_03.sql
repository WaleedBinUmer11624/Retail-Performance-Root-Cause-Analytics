-- FP-03: one name, type and window per promotion_id (after the FP-02 window repair, before the FP-04
-- quarantine). Checked per promotion.
{% set population %}
    select promotion_id,
           count(distinct promotion_name) as names, count(distinct promotion_type) as types,
           count(distinct start_date) as starts, count(distinct end_date) as ends
    from {{ ref('int_dq__promotions') }} where stage in ('kept', 'fp_04') group by promotion_id
{% endset %}
{% set failing %}
    select promotion_id as row_key from population where names > 1 or types > 1 or starts > 1 or ends > 1
{% endset %}
{{ dq_result('FP-03', 0, 136, population, failing) }}
