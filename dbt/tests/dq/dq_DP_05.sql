-- DP-05: list_price and unit_cost positive (dimensions.clean_dim_product). Phase 3 counts the non-positive
-- prices and the non-positive costs separately, so a product with both counts twice.
{% set population %}select * from {{ ref('int_dq__dim_product') }} where is_kept{% endset %}
{% set failing %}
    select product_id || '|list_price' as row_key from population where price_not_positive
    union all
    select product_id || '|unit_cost' from population where cost_not_positive
{% endset %}
{{ dq_result('DP-05', 1, 600, population, failing) }}
