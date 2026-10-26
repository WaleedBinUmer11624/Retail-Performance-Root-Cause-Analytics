-- fact_promotions through the FP treatments (promotions_targets.clean_promotions), one row per raw record:
--   FP-01 exact duplicates dropped, FP-02 window restored from the promotion's modal window,
--   FP-04 rows whose product or store is not in the dimensions quarantined.
-- stage: 'fp_01' duplicate, 'fp_02' unrestorable window, 'fp_04' orphan, 'kept' curated promotion row.
with raw as (
    select *,
           row_number() over (partition by promotion_id, promotion_name, promotion_type, product_id, store_id,
                                           start_date, end_date, discount_pct order by source_row) > 1 as fp_01_fail
    from {{ ref('stg_raw__fact_promotions') }}
),
typed as (
    select *, {{ parse_iso('start_date') }} as start_dt, {{ parse_iso('end_date') }} as end_dt,
           {{ to_num('discount_pct') }} as discount_pct_n
    from raw where not fp_01_fail
),
flagged as (
    select *, coalesce(end_dt < start_dt, false) or start_dt is null or end_dt is null as fp_02_fail from typed
),
start_mode as (
    select promotion_id, start_dt as s,
           row_number() over (partition by promotion_id order by count(*) desc, start_dt) as rk
    from flagged where not fp_02_fail group by promotion_id, start_dt
),
end_mode as (
    select promotion_id, end_dt as e,
           row_number() over (partition by promotion_id order by count(*) desc, end_dt) as rk
    from flagged where not fp_02_fail group by promotion_id, end_dt
),
modal as (
    select promotion_id, s, e
    from start_mode join end_mode using (promotion_id)
    where start_mode.rk = 1 and end_mode.rk = 1
),
restored as (
    select f.*,
           case when f.fp_02_fail then m.s else f.start_dt end as start_fixed,
           case when f.fp_02_fail then m.e else f.end_dt end as end_fixed,
           f.fp_02_fail and m.promotion_id is null as fp_02_unrestorable
    from flagged as f left join modal as m using (promotion_id)
),
checked as (
    select r.*,
           p.product_id is null or s.store_id is null as fp_04_fail
    from restored as r
    left join (select product_id from {{ ref('int_dq__dim_product') }} where is_kept) as p using (product_id)
    left join (select store_id from {{ ref('int_dq__dim_store') }}) as s using (store_id)
    where not r.fp_02_unrestorable
)
select source_row,
       promotion_id || '|' || coalesce(product_id, '') || '|' || coalesce(store_id, '') as row_key,
       promotion_id, promotion_name, promotion_type, product_id, store_id,
       start_fixed as start_date, end_fixed as end_date, discount_pct_n as discount_pct,
       fp_02_fail, fp_04_fail,
       case when fp_04_fail then 'fp_04' else 'kept' end as stage
from checked
union all
select source_row, promotion_id || '|' || coalesce(product_id, '') || '|' || coalesce(store_id, ''),
       promotion_id, promotion_name, promotion_type, product_id, store_id, start_dt, end_dt, discount_pct_n,
       fp_02_fail, cast(null as boolean), 'fp_02'
from restored where fp_02_unrestorable
union all
select source_row, promotion_id || '|' || coalesce(product_id, '') || '|' || coalesce(store_id, ''),
       promotion_id, promotion_name, promotion_type, product_id, store_id, cast(null as date), cast(null as date),
       {{ to_num('discount_pct') }}, cast(null as boolean), cast(null as boolean), 'fp_01'
from raw where fp_01_fail
