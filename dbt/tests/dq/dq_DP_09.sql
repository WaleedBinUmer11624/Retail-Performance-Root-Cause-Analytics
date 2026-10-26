-- DP-09: each subcategory belongs to one category (after DP-02 standardisation). Checked per subcategory.
{% set population %}
    select subcategory, count(distinct category) as categories from {{ ref('int_dq__dim_product') }}
    where is_kept and subcategory is not null group by subcategory
{% endset %}
{% set failing %}select subcategory as row_key from population where categories > 1{% endset %}
{{ dq_result('DP-09', 0, 39, population, failing) }}
