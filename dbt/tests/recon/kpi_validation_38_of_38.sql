-- The governed KPI layer validation (sql/validation/11): all 38 checks PASS. Replaces the T-SQL THROW 50002.
-- One row per failing check, plus one row if the number of checks is not 38.
select check_name, status from {{ ref('kpi_validation_result') }} where status <> 'PASS'
union all
select 'checks: ' || count(*) || ' (expected 38)', 'FAIL' from {{ ref('kpi_validation_result') }} having count(*) <> 38
