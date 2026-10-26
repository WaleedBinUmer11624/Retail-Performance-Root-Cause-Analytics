-- Final POS stage (sales.clean_sales from FS-17 on): line arithmetic, category, promotions, receipt
-- integrity and life cycle, then the curated sales columns with each line's DQ history.
-- stage: 'kept' (curated line) or the rule that quarantined it.
with s as (
    select * from {{ ref('int_dq__sales_scoped') }} where not fs_11_quarantined
),
arith as (
    select *,
           {{ np_round('quantity * unit_price - discount') }} as calc_rev
    from s
),
arith2 as (
    select *,
           coalesce(abs(calc_rev - revenue) > {{ var('money_tolerance') }}, false) as fs_17_fail,
           coalesce(abs(calc_rev - revenue) > {{ var('money_tolerance') }}, false)
             and coalesce(abs(calc_rev - (cost + margin)) <= {{ var('money_tolerance') }}, false) as fs_17_confirmed
    from arith
),
arith3 as (
    select * exclude (revenue),
           case when fs_17_confirmed then calc_rev else revenue end as revenue,
           fs_17_fail and not fs_17_confirmed as fs_17_unconfirmed
    from arith2
),
kept as (
    select * from arith3 where not fs_17_unconfirmed
),
margined as (
    select *,
           coalesce(abs({{ np_round('revenue - cost') }} - margin) > {{ var('money_tolerance') }}, false) as fs_18_margin,
           coalesce(abs({{ np_round('quantity * unit_cost') }} - cost) > {{ var('money_tolerance') }}, false) as fs_18_cost
    from kept
),
margined2 as (
    select * exclude (margin),
           case when fs_18_margin then {{ np_round('revenue - cost') }} else margin end as margin,
           fs_18_margin or fs_18_cost as fs_18_fail,
           coalesce(discount < -{{ var('money_tolerance') }}
                    or discount > {{ var('max_discount_share') }} * quantity * unit_price + {{ var('money_tolerance') }}, false)
               as fs_16_fail
    from margined
),
products as (
    select product_id, category, unit_cost as master_cost, launch_date, discontinued_date
    from {{ ref('int_dq__dim_product') }} where is_kept
),
categorised as (
    select m.*,
           case when m.product_id = 'UNKNOWN' then coalesce(c.canonical, 'Unknown') else p.category end as category,
           p.master_cost, p.launch_date, p.discontinued_date
    from margined2 as m
    left join products as p on p.product_id = m.product_id
    left join {{ ref('int_dq__category_map') }} as c on c.raw_label = m.category_raw
),
categorised2 as (
    select *, coalesce(coalesce(category_raw, '') <> category, true) as fs_07_fail from categorised
),
promos as (
    select * from {{ ref('int_dq__promotions') }} where stage = 'kept'
),
promo_ids as (
    select distinct promotion_id from promos
),
promo_flagged as (
    select c.*,
           not {{ is_blank('c.promotion_id_raw') }} as promo_present,
           not {{ is_blank('c.promotion_id_raw') }} and i.promotion_id is null as fs_19_fail
    from categorised2 as c left join promo_ids as i on i.promotion_id = c.promotion_id_raw
),
promo_candidates as (
    -- an unknown code is restored from the one active promotion for the store and product whose depth matches
    select f.row_key, min(p.promotion_id) as promotion_id, count(*) as candidates
    from promo_flagged as f
    join promos as p on p.store_id = f.store_id and p.product_id = f.product_id
    where f.fs_19_fail and f.transaction_date between p.start_date and p.end_date
      and abs(f.discount / (f.quantity * f.unit_price) - p.discount_pct) <= 0.011
    group by f.row_key
),
promo_fixed as (
    select f.*,
           case when not f.fs_19_fail then f.promotion_id_raw
                when pc.candidates = 1 then pc.promotion_id
                when f.discount <= 0 then null
                else 'UNKNOWN' end as promotion_id
    from promo_flagged as f
    left join promo_candidates as pc on pc.row_key = f.row_key and f.fs_19_fail
),
promo_known as (
    select f.*,
           f.promotion_id is not null and not {{ is_blank('f.promotion_id') }} as promo_present_after,
           f.promotion_id is not null and not {{ is_blank('f.promotion_id') }} and f.promotion_id <> 'UNKNOWN' as promo_known,
           k.promotion_id is not null as in_promotion_scope
    from promo_fixed as f
    left join (select distinct promotion_id, store_id, product_id from promos) as k
           on k.promotion_id = f.promotion_id and k.store_id = f.store_id and k.product_id = f.product_id
),
not_in_scope as (
    select *, promo_known and product_id <> 'UNKNOWN' and not in_promotion_scope as notin from promo_known
),
restorable as (
    -- FP-04: a promotion row quarantined for an invalid product is restored when the POS lines of that
    -- promotion and store identify exactly one product missing from the promotion
    select n.promotion_id, n.store_id
    from not_in_scope as n
    join (select distinct promotion_id, store_id from {{ ref('int_dq__promotions') }} where stage = 'fp_04') as o
      on o.promotion_id = n.promotion_id and o.store_id = n.store_id
    where n.notin
    group by n.promotion_id, n.store_id having count(distinct n.product_id) = 1
),
windows as (
    select promotion_id, min(start_date) as s, max(end_date) as e from promos group by promotion_id
),
promo_rules as (
    select n.*,
           n.notin and r.promotion_id is null as fs_20_fail,
           n.promo_known and coalesce(n.discount <= 0, false) as fs_21_fail,
           n.promo_known and coalesce(n.transaction_date < w.s or n.transaction_date > w.e, false) as fs_22_fail,
           not n.promo_present_after and coalesce(n.discount > 0, false) as fs_23_fail
    from not_in_scope as n
    left join restorable as r on r.promotion_id = n.promotion_id and r.store_id = n.store_id
    left join windows as w on w.promotion_id = n.promotion_id
),
receipts as (
    select transaction_id
    from promo_rules group by transaction_id
    having count(distinct store_id) > 1 or count(distinct transaction_date) > 1 or count(distinct transaction_time) > 1
    union
    -- line-number gaps are tested on every distinct line received, as gaps are expected where a line was quarantined
    select transaction_id from {{ ref('int_dq__sales_deduplicated') }}
    group by transaction_id having min(line_no) <> 1 or max(line_no) <> count(*)
),
final as (
    select p.*,
           r.transaction_id is not null as fs_26_fail,
           coalesce(p.master_cost is not null and abs(p.unit_cost - p.master_cost) > {{ var('money_tolerance') }}, false) as fs_24_fail,
           coalesce(p.margin < 0, false) as fs_25_fail,
           coalesce(p.transaction_date < p.launch_date or p.transaction_date > p.discontinued_date + interval 7 day, false)
               as fs_27_fail,
           p.quantity is null or p.unit_price is null or p.discount is null or p.revenue is null or p.unit_cost is null
             or p.cost is null or p.margin is null as money_missing
    from promo_rules as p
    left join (select distinct transaction_id from receipts) as r using (transaction_id)
),
tagged as (
    select *,
           list_sort(list_filter([
               case when tc_01_fail then 'TC-01' end, case when fs_02_fail then 'FS-02' end,
               case when fs_03_fail then 'FS-03' end, case when fs_04_fail then 'FS-04' end,
               case when fs_08_fail then 'FS-08' end, case when fs_12_fail then 'FS-12' end,
               case when fs_05_fail then 'FS-05' end, case when fs_06_fail then 'FS-06' end,
               case when fs_10_imputed then 'FS-10' end, case when fs_15_imputed then 'FS-15' end,
               case when fs_13_fail then 'FS-13' end, case when fs_11_imputed then 'FS-11' end,
               case when fs_14_fail then 'FS-14' end, case when fs_17_confirmed then 'FS-17' end,
               case when fs_18_fail then 'FS-18' end, case when fs_16_fail then 'FS-16' end,
               case when fs_07_fail then 'FS-07' end, case when fs_19_fail then 'FS-19' end,
               case when fs_20_fail then 'FS-20' end, case when fs_21_fail then 'FS-21' end,
               case when fs_22_fail then 'FS-22' end, case when fs_26_fail then 'FS-26' end,
               case when fs_27_fail then 'FS-27' end], x -> x is not null)) as rule_list
    from final
),
treatments as (
    select rule_id, treatment from {{ source('phase3_reports', 'dq_rule_catalogue') }}
),
status as (
    select t.row_key,
           case when bool_or(c.treatment = 'IMPUTE') then 'imputed'
                when bool_or(c.treatment in ('CORRECT', 'UNKNOWN_MEMBER')) then 'corrected'
                when bool_or(c.treatment in ('FLAG', 'INCLUDE')) then 'flagged'
                else 'standardised' end as dq_status
    from tagged as t
    cross join unnest(t.rule_list) as u(rule_id)
    join treatments as c on c.rule_id = u.rule_id
    group by t.row_key
)
select t.*,
       array_to_string(t.rule_list, ';') as dq_rules,
       coalesce(st.dq_status, 'clean') as dq_status,
       case when t.money_missing then 'final_gate' else 'kept' end as stage
from tagged as t
left join status as st using (row_key)
