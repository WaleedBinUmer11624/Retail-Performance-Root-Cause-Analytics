-- The dbt build lands on the same figures as the governed DuckDB build: every reconciliation metric and
-- every KPI validation check equals the governed result in reports/phase4 (same status, actual values equal
-- to 1e-6). Counts and money totals in the reconciliation are exact to the cent. One row per difference.
select 'reconciliation' as result_set, coalesce(g.metric_name, d.metric_name) as name, g.actual_value as governed,
       d.actual_value as dbt
from {{ source('phase4_reports', 'reconciliation_results_duckdb') }} as g
full join {{ ref('v_reconciliation') }} as d on d.metric_name = g.metric_name
where g.metric_name is null or d.metric_name is null or g.status <> d.status
   or abs(cast(g.actual_value as double) - d.actual_value) > 1e-6
union all
select 'kpi_validation', coalesce(g.check_name, d.check_name), g.actual_value, d.actual_value
from {{ source('phase4_reports', 'kpi_validation_duckdb') }} as g
full join {{ ref('kpi_validation_result') }} as d on d.check_name = g.check_name
where g.check_name is null or d.check_name is null or g.status <> d.status
   or abs(cast(g.actual_value as double) - d.actual_value) > 1e-6
