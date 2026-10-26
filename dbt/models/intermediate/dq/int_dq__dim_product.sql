-- dim_product after the DP treatments (dimensions.clean_dim_product), one row per raw record:
--   DP-01 duplicate product IDs: the copy whose list price is nearest the latest till price is kept
--   DP-03 trim, DP-02 canonical category, DP-04 UNKNOWN supplier, DP-05 sign confirmed by the till
-- is_kept marks the curated rows; the rule flags are evaluated on the rows Phase 3 evaluates them on.
{%- set text_cols = ['product_name', 'category', 'subcategory', 'brand', 'supplier_id', 'supplier_name', 'status'] %}
with latest as (
    select product_id, arg_max(ref_price, year) as ref_price, arg_max(ref_cost, year) as ref_cost
    from {{ ref('int_dq__till_reference') }} group by product_id
),
raw as (
    select r.*, {{ to_num('r.list_price') }} as list_price_num, {{ to_num('r.unit_cost') }} as unit_cost_num,
           count(*) over (partition by r.product_id) as id_copies,
           l.ref_price, l.ref_cost
    from {{ ref('stg_raw__dim_product') }} as r
    left join latest as l using (product_id)
),
ranked as (
    select *,
           row_number() over (partition by product_id
                              order by coalesce(abs(list_price_num - ref_price), 'inf'::double), source_row) as copy_rank
    from raw
),
kept as (
    select source_row, product_id, id_copies, copy_rank, list_price_num, unit_cost_num, ref_price, ref_cost,
           launch_date, discontinued_date,
           ({% for c in text_cols %}{{ is_padded(c) }}{{ ' or ' if not loop.last }}{% endfor %}) as dp_03_fail,
           {% for c in text_cols %}trim({{ c }}) as {{ c }}{{ ',' if not loop.last }}
           {% endfor %}
    from ranked
),
categorised as (
    select k.*, m.canonical as category_canonical
    from kept as k left join {{ ref('int_dq__category_map') }} as m on m.raw_label = k.category
),
treated as (
    select *,
           {{ is_blank('supplier_id') }} or {{ is_blank('supplier_name') }} as dp_04_fail,
           coalesce(list_price_num <= 0, false) as price_not_positive,
           coalesce(unit_cost_num <= 0, false) as cost_not_positive,
           case when list_price_num <= 0 and abs(abs(list_price_num) - ref_price) <= 0.05 * ref_price
                then abs(list_price_num) else list_price_num end as list_price_fixed,
           case when unit_cost_num <= 0 and abs(abs(unit_cost_num) - ref_cost) <= 0.05 * ref_cost
                then abs(unit_cost_num) else unit_cost_num end as unit_cost_fixed,
           try_cast(launch_date as date) as launch,
           case when {{ is_blank('discontinued_date') }} then null else try_cast(discontinued_date as date) end as disc
    from categorised
)
select source_row,
       product_id as row_key,
       product_id,
       copy_rank = 1 as is_kept,
       id_copies > 1 and copy_rank > 1 as dp_01_fail,
       product_name,
       coalesce(category_canonical, category) as category,
       subcategory, brand,
       case when dp_04_fail then 'UNKNOWN' else supplier_id end as supplier_id,
       case when dp_04_fail then 'Unknown supplier' else supplier_name end as supplier_name,
       list_price_fixed as list_price,
       unit_cost_fixed as unit_cost,
       launch as launch_date,
       disc as discontinued_date,
       status,
       dp_03_fail,
       (category_canonical is null or category_canonical <> category) as dp_02_fail,
       dp_04_fail,
       price_not_positive, cost_not_positive,
       coalesce(unit_cost_fixed >= list_price_fixed, false) as dp_06_fail,
       (launch is null or coalesce(disc <= launch, false)
        or coalesce(status not in {{ in_list(var('product_status')) }}, true)
        or (status = 'Discontinued' and disc is null)) as dp_07_fail,
       count(*) over (partition by lower(product_name), copy_rank = 1) > 1 as dp_08_fail
from treated
