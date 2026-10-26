-- POS lines in scope (FS-09 bulk lines and lines with a malformed ID removed), with the product and
-- price treatments in Phase 3 order:
--   FS-05 / FS-06 product restored from the linked return, else UNKNOWN
--   FS-10 price from (revenue + discount) / quantity, FS-15 discount from quantity x price - revenue
--   FS-13 price about 100x the SKU-year reference divided by 100, FS-11 zero price imputed from the
--   reference less the promotion depth; FS-14 and FS-28 test the result against the reference.
with s as (
    select * from {{ ref('int_dq__sales_deduplicated') }} where tid_ok and not fs_09_fail
),
products as (
    select product_id from {{ ref('int_dq__dim_product') }} where is_kept
),
return_links as (
    -- sale line -> product named on its returns, when every return of that line names the same product
    select original_transaction_id || '|' || coalesce(original_line_number, '') as row_key, min(product_id) as product_id
    from {{ ref('stg_raw__fact_returns') }}
    where not {{ is_blank('original_transaction_id') }} and not {{ is_blank('product_id') }}
    group by 1 having count(distinct product_id) = 1
),
keyed as (
    select s.*,
           {{ is_blank('s.product_id_raw') }} as fs_05_fail,
           lp.product_id as linked_product,
           p.product_id is not null as product_known
    from s
    left join return_links as l on l.row_key = s.row_key
    left join products as lp on lp.product_id = l.product_id
    left join products as p on p.product_id = s.product_id_raw
),
product_fixed as (
    select *,
           not fs_05_fail and not product_known and product_id_raw <> 'UNKNOWN' as fs_06_fail,
           case when fs_05_fail or (not product_known and product_id_raw <> 'UNKNOWN')
                then coalesce(linked_product, 'UNKNOWN') else product_id_raw end as product_id
    from keyed
),
imputed as (
    select *,
           unit_price is null as fs_10_fail,
           discount is null as fs_15_fail,
           case when unit_price is null and revenue is not null and discount is not null and quantity > 0
                then {{ np_round('(revenue + discount) / quantity') }} else unit_price end as price1
    from product_fixed
),
imputed2 as (
    select *,
           case when discount is null and revenue is not null and price1 is not null
                then greatest({{ np_round('quantity * price1 - revenue') }}, 0) else discount end as disc1
    from imputed
),
referenced as (
    select i.*, t.ref_price,
           coalesce(i.price1 / t.ref_price between {{ var('decimal_shift_ratio')[0] }} and {{ var('decimal_shift_ratio')[1] }}, false)
               as fs_13_fail
    from imputed2 as i
    left join {{ ref('int_dq__till_reference') }} as t
           on t.product_id = i.product_id and t.year = substr(i.transaction_id, 5, 4)
),
shifted as (
    select *,
           case when fs_13_fail then {{ np_round('price1 / 100') }} else price1 end as price2
    from referenced
),
shifted2 as (
    select *,
           case when fs_13_fail and disc1 > {{ var('max_discount_share') }} * quantity * price2
                then {{ np_round('disc1 / 100') }} else disc1 end as disc2
    from shifted
),
shifted3 as (
    select *,
           case when fs_13_fail then {{ np_round('quantity * price2 - disc2') }} else revenue end as rev2
    from shifted2
),
promo_depth as (
    select promotion_id, store_id, product_id, arg_min(discount_pct, source_row) as discount_pct
    from {{ ref('int_dq__promotions') }} where stage = 'kept'
    group by promotion_id, store_id, product_id
),
priced as (
    select h.*,
           coalesce(h.price2 = 0, false) as fs_11_fail,
           coalesce(h.price2 = 0, false) and h.ref_price is not null as fs_11_imputed,
           coalesce(d.discount_pct, 0.0) as promo_depth
    from shifted3 as h
    left join promo_depth as d
           on d.promotion_id = h.promotion_id_raw and d.store_id = h.store_id and d.product_id = h.product_id
),
priced2 as (
    select *,
           case when fs_11_imputed then ref_price else price2 end as price3,
           case when fs_11_imputed then {{ np_round('quantity * ref_price * promo_depth') }} else disc2 end as disc3
    from priced
),
priced3 as (
    select *,
           case when fs_11_imputed then {{ np_round('quantity * price3 - disc3') }} else rev2 end as rev3
    from priced2
)
select source_file, source_row, received_order, row_key, transaction_id, line_no, transaction_date, transaction_time,
       store_id, product_id, product_id_raw, category_raw, promotion_id_raw,
       extract_batch_id, extract_timestamp, extract_ts, extract_lag_days, tc_01_fail,
       fs_02_fail, fs_03_fail, fs_04_fail, fs_08_fail, fs_12_fail,
       fs_05_fail, fs_06_fail, fs_10_fail, fs_15_fail, fs_13_fail, fs_11_fail, fs_11_imputed,
       fs_10_fail and price1 is not null as fs_10_imputed,
       fs_15_fail and disc1 is not null as fs_15_imputed,
       quantity, price3 as unit_price, disc3 as discount, rev3 as revenue, unit_cost, cost,
       case when fs_13_fail or fs_11_imputed then {{ np_round('rev3 - cost') }} else margin end as margin,
       ref_price,
       ref_price is not null and abs(price3 / ref_price - 1) > {{ var('price_reference_tolerance') }} as fs_14_fail,
       ref_price is null as fs_28_fail,
       fs_11_fail and not fs_11_imputed as fs_11_quarantined
from priced3
