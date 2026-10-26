-- Every raw stock snapshot with the two record-level flags: FI-01 exact duplicate (a repeat of an earlier
-- identical row) and FI-02 conflicting snapshots for one store, product and date (tested after FI-01).
with raw as (
    select *,
           row_number() over (partition by snapshot_date, retail_year, retail_week, store_id, product_id, opening_stock,
                                           received_qty, sold_qty, adjustment_qty, closing_stock order by source_row) > 1 as fi_01_fail
    from {{ ref('stg_raw__fact_inventory') }}
)
select *,
       store_id || '|' || product_id || '|' || snapshot_date as row_key,
       not fi_01_fail and count(*) filter (where not fi_01_fail)
           over (partition by store_id, product_id, snapshot_date) > 1 as fi_02_fail
from raw
