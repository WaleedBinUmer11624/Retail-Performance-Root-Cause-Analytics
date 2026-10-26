-- The governed headline figures, read from the governed views (mart.v_kpi_estate_period and
-- mart.v_yoy_segment_period): estate net revenue for retail H2 2025 is EUR 9,457,457.05, -7.18% on H2 2024,
-- and for retail H1 2025 EUR 8,629,984.78, +1.438% on H1 2024. One row per figure that differs.
with figures as (
    select e.period, e.net_revenue, y.net_revenue_yoy_pct
    from {{ ref('v_kpi_estate_period') }} as e
    join {{ ref('v_yoy_segment_period') }} as y
      on y.segment_type = 'Estate' and y.retail_year = e.retail_year and y.period = e.period
    where e.retail_year = 2025 and e.period in ('H1', 'H2')
),
expected as (
    select * from (values ('H2', 9457457.05, -7.18, 2), ('H1', 8629984.78, 1.438, 3)) as t(period, net_revenue, yoy_pct, decimals)
)
select x.period, f.net_revenue, f.net_revenue_yoy_pct
from expected as x
left join figures as f using (period)
where f.period is null
   or abs(cast(f.net_revenue as double) - x.net_revenue) > 0.005
   or round(f.net_revenue_yoy_pct, x.decimals) <> x.yoy_pct
