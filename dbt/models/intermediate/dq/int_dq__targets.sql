-- fact_targets through the FT rules (promotions_targets.clean_targets), one row per raw record:
--   FT-01 superseded versions dropped (latest version, then latest set date, then last row kept)
--   FT-02 targets over 10x the store median divided by 100 when that lands in the normal range.
-- stage: 'ft_01' superseded, 'ft_02' extreme outlier quarantined, 'kept' curated target.
with typed as (
    select source_row, store_id, target_version,
           try_cast({{ to_num('retail_year') }} as bigint) as retail_year,
           try_cast({{ to_num('retail_week') }} as bigint) as retail_week,
           {{ to_num('target_net_revenue') }} as target_net_revenue,
           {{ parse_iso('week_start_date') }} as week_start_date,
           {{ parse_iso('week_end_date') }} as week_end_date,
           {{ parse_iso('target_set_date') }} as target_set_date,
           try_cast(regexp_extract(target_version, '(\d+)', 1) as double) as version_no
    from {{ ref('stg_raw__fact_targets') }}
),
versioned as (
    select *,
           row_number() over (partition by store_id, retail_year, retail_week
                              order by version_no desc nulls last, target_set_date desc nulls last, source_row desc) > 1
               as ft_01_fail
    from typed
),
current_targets as (
    select *, median(target_net_revenue) over (partition by store_id) as store_median
    from versioned where not ft_01_fail
),
outliers as (
    select *,
           coalesce(target_net_revenue / store_median > {{ var('target_outlier_ratio') }}, false) as ft_02_fail,
           coalesce(target_net_revenue / store_median > {{ var('target_outlier_ratio') }}
                    and target_net_revenue / store_median / 100 between {{ var('target_decimal_shift_band')[0] }}
                                                                    and {{ var('target_decimal_shift_band')[1] }}, false)
               as ft_02_shift
    from current_targets
),
weeks as (
    select retail_year, retail_week, min(calendar_date) as first_day, max(calendar_date) as last_day
    from {{ ref('int_dq__dim_date') }} group by retail_year, retail_week
)
select o.source_row,
       o.store_id || '|' || coalesce(cast(o.retail_year as varchar), '<NA>') || '|' || coalesce(cast(o.retail_week as varchar), '<NA>')
           as row_key,
       o.store_id, o.retail_year, o.retail_week, o.week_start_date, o.week_end_date, o.target_version, o.target_set_date,
       case when o.ft_02_shift then {{ np_round('o.target_net_revenue / 100') }} else o.target_net_revenue end as target_net_revenue,
       o.ft_01_fail, o.ft_02_fail, o.ft_02_shift,
       coalesce(w.first_day <> o.week_start_date, true) or coalesce(w.last_day <> o.week_end_date, true) as ft_03_fail,
       coalesce(o.target_net_revenue <= 0, false) or o.target_net_revenue is null
         or o.store_id not in (select store_id from {{ ref('int_dq__dim_store') }}) or o.store_id is null as ft_04_fail,
       case when o.ft_02_fail and not o.ft_02_shift then 'ft_02' else 'kept' end as stage
from outliers as o
left join weeks as w on w.retail_year = o.retail_year and w.retail_week = o.retail_week
union all
select source_row,
       store_id || '|' || coalesce(cast(retail_year as varchar), '<NA>') || '|' || coalesce(cast(retail_week as varchar), '<NA>'),
       store_id, retail_year, retail_week, week_start_date, week_end_date, target_version, target_set_date,
       target_net_revenue, ft_01_fail, cast(null as boolean), cast(null as boolean), cast(null as boolean),
       cast(null as boolean), 'ft_01'
from versioned where ft_01_fail
