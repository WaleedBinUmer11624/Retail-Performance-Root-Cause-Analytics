/* =====================================================================
   Paginated report source layer (schema rpt)
   ---------------------------------------------------------------------
   Read-only views for powerbi/paginated/Executive_KPI_Summary.rdl.
   Each view selects existing columns from the governed mart and recon
   views and filters rows; none computes a KPI. Revenue, change and YoY %
   come from mart.v_yoy_segment_period exactly as Phase 4 defines them.
   Two views add counts, neither of them a KPI. The validation gate counts
   the PASS rows of recon.v_reconciliation (45) and recon.v_kpi_validation
   (38): the report must show PASS on both before it is exported. The half
   parameter view counts the retail weeks with data in each half, so the
   report can flag a half that is shorter than its prior-year comparison.

   Not part of the governed build: this script is not listed in
   config/sql_model_config.yaml and the Phase 4 runner never runs it.
   Run it separately after each SQL Server build (the build recreates the
   database, which removes this schema):
     sqlcmd -S localhost -d BrightwaterRetail -E -C -b -i sql\reporting\01_rpt_views.sql
   ===================================================================== */

-- @tsql-only
IF SCHEMA_ID(N'rpt') IS NULL EXEC(N'CREATE SCHEMA rpt');
GO

-- Estate year on year by retail half (H1, H2); one row per year and half
CREATE OR ALTER VIEW rpt.v_estate_yoy AS
SELECT y.retail_year, y.period, y.segment_name,
       y.net_revenue_cy, y.net_revenue_py, y.net_revenue_change, y.net_revenue_yoy_pct,
       y.sales_revenue_cy, y.sales_revenue_py, y.returns_value_cy, y.returns_value_py,
       y.transactions_cy, y.transactions_py, y.transactions_yoy_pct,
       y.aov_cy, y.aov_py, y.gross_margin_pct_cy, y.gross_margin_pct_py
FROM mart.v_yoy_segment_period AS y
WHERE y.segment_type = N'Estate' AND y.period IN (N'H1', N'H2');
GO

-- Store year on year by retail half; store_label is the governed segment name, for example "S03 Dublin Blanchardstown"
CREATE OR ALTER VIEW rpt.v_store_yoy AS
SELECT y.retail_year, y.period, y.segment_name AS store_label,
       y.net_revenue_cy, y.net_revenue_py, y.net_revenue_change, y.net_revenue_yoy_pct,
       y.transactions_cy, y.transactions_py, y.transactions_yoy_pct,
       y.aov_cy, y.aov_py, y.gross_margin_pct_cy, y.gross_margin_pct_py
FROM mart.v_yoy_segment_period AS y
WHERE y.segment_type = N'Store' AND y.period IN (N'H1', N'H2');
GO

-- Available values for the Year and Half parameters
CREATE OR ALTER VIEW rpt.v_period_parameter AS
SELECT DISTINCT y.retail_year, y.period
FROM mart.v_yoy_segment_period AS y
WHERE y.period IN (N'H1', N'H2');
GO

-- Halves with year on year data, for the cascading Half parameter. A half is partial when it has
-- fewer retail weeks with data than the same half a year earlier (for example 2026 H1, where the
-- data ends in its first week), so its change is not comparable.
CREATE OR ALTER VIEW rpt.v_half_parameter AS
SELECT p.retail_year, p.period, cy.weeks_with_data, py.weeks_with_data AS prior_year_weeks_with_data,
       CASE WHEN cy.weeks_with_data < py.weeks_with_data THEN 1 ELSE 0 END AS is_partial
FROM (
    SELECT DISTINCT y.retail_year, y.period
    FROM mart.v_yoy_segment_period AS y
    WHERE y.period IN (N'H1', N'H2')
) AS p
JOIN (
    SELECT w.retail_year, w.retail_half, COUNT(DISTINCT w.retail_week) AS weeks_with_data
    FROM mart.v_performance_store_week AS w
    GROUP BY w.retail_year, w.retail_half
) AS cy ON cy.retail_year = p.retail_year AND cy.retail_half = p.period
LEFT JOIN (
    SELECT w.retail_year, w.retail_half, COUNT(DISTINCT w.retail_week) AS weeks_with_data
    FROM mart.v_performance_store_week AS w
    GROUP BY w.retail_year, w.retail_half
) AS py ON py.retail_year = p.retail_year - 1 AND py.retail_half = p.period;
GO

-- Available values for the Store parameter
CREATE OR ALTER VIEW rpt.v_store_parameter AS
SELECT DISTINCT y.segment_name AS store_label
FROM mart.v_yoy_segment_period AS y
WHERE y.segment_type = N'Store';
GO

-- Validation gate: both check sets must be complete and all PASS before any export
CREATE OR ALTER VIEW rpt.v_validation_gate AS
SELECT g.check_set, g.checks, g.passed, g.expected_checks,
       CASE WHEN g.checks = g.expected_checks AND g.passed = g.expected_checks THEN N'PASS' ELSE N'FAIL' END AS gate_status
FROM (
    SELECT N'Reconciliation' AS check_set, COUNT(*) AS checks,
           SUM(CASE WHEN r.status = N'PASS' THEN 1 ELSE 0 END) AS passed, 45 AS expected_checks
    FROM recon.v_reconciliation AS r
    UNION ALL
    SELECT N'KPI validation', COUNT(*), SUM(CASE WHEN k.status = N'PASS' THEN 1 ELSE 0 END), 38
    FROM recon.v_kpi_validation AS k
) AS g;
GO
