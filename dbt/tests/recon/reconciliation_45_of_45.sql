-- The governed reconciliation (sql/validation/09): all 45 metrics PASS against the Phase 3 expected values,
-- within each metric's tolerance. Replaces the T-SQL THROW 50001. One row per failing metric, plus one row
-- if the number of metrics is not 45.
select metric_name, status from {{ ref('v_reconciliation') }} where status <> 'PASS'
union all
select 'metrics: ' || count(*) || ' (expected 45)', 'FAIL' from {{ ref('v_reconciliation') }} having count(*) <> 45
