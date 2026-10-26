-- Promotion rows quarantined by FP-04 (product or store not in the dimensions) that Phase 3 moves back
-- into the curated table (run_dq.restore_promotions): the POS lines of that promotion and store that are
-- not covered by any promotion row name exactly one product, which replaces the invalid product_id.
with uncovered as (
    select promotion_id, store_id, product_id
    from {{ ref('int_dq__sales_curated') }} where notin
),
orphans as (
    -- Phase 3 restores orphans one at a time and clears the lines it used, so only the first orphan row of
    -- a promotion and store can be restored
    select * from {{ ref('int_dq__promotions') }} where stage = 'fp_04'
    qualify row_number() over (partition by promotion_id, store_id order by source_row) = 1
),
identified as (
    select o.source_row, min(u.product_id) as product_id
    from orphans as o
    join uncovered as u on u.promotion_id = o.promotion_id and u.store_id = o.store_id
    group by o.source_row
    having count(distinct u.product_id) = 1
)
select o.source_row, o.promotion_id, o.promotion_name, o.promotion_type,
       o.product_id as product_id_raw, i.product_id, o.store_id,
       r.start_date as start_date_raw, r.end_date as end_date_raw,
       try_cast(r.start_date as date) as start_date, try_cast(r.end_date as date) as end_date, o.discount_pct
from orphans as o
join identified as i using (source_row)
join {{ ref('stg_raw__fact_promotions') }} as r on r.source_row = o.source_row
