-- SKU reference price and cost per product and year (dimensions.till_reference): the modal unit price
-- and unit cost on POS lines with a positive price and cost, from the main and late extracts as received.
-- Ties take the lowest value, as pandas Series.mode().iloc[0] does.
with lines as (
    select product_id, substr(transaction_id, 5, 4) as year,
           {{ to_num('unit_price') }} as p, {{ to_num('unit_cost') }} as c
    from {{ ref('stg_raw__fact_sales') }}
    union all
    select product_id, substr(transaction_id, 5, 4), {{ to_num('unit_price') }}, {{ to_num('unit_cost') }}
    from {{ ref('stg_raw__fact_sales_late_batch') }}
),
kept as (
    select * from lines where p > 0 and c > 0 and product_id is not null
),
price_mode as (
    select product_id, year, p as ref_price,
           row_number() over (partition by product_id, year order by count(*) desc, p) as rk
    from kept group by product_id, year, p
),
cost_mode as (
    select product_id, year, c as ref_cost,
           row_number() over (partition by product_id, year order by count(*) desc, c) as rk
    from kept group by product_id, year, c
)
select p.product_id, p.year, p.ref_price, c.ref_cost
from price_mode as p
join cost_mode as c on c.product_id = p.product_id and c.year = p.year and c.rk = 1
where p.rk = 1
