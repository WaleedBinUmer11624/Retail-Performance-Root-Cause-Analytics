/* =====================================================================
   Phase 5 diagnostics 01: headline and weekly trend
   ---------------------------------------------------------------------
   Schema diag holds the Phase 5 diagnostic views. They read ONLY the
   Phase 4 governed layer (mart.*) and the dw star schema, never staging,
   raw files or any evaluation asset.

   Comparison basis (BRD 3, sign-off item 2): H2 = retail weeks 27 to 52,
   week-aligned, so each current-year week is compared with the retail
   week that has the same number one year earlier (same weekdays).
   The views are written for every retail year; the Python layer selects
   the current and prior year from config/project_config.yaml.

   Money columns are summed from the DECIMAL columns of the governed base;
   ratios are computed after summing (never averaged) and cast to FLOAT.
   Script order matters: 02 to 09 build on views created here.
   ===================================================================== */

-- @tsql-only
IF SCHEMA_ID(N'diag') IS NULL EXEC(N'CREATE SCHEMA diag');
GO

-- Estate x retail week: every additive component of the governed store-day base
CREATE OR ALTER VIEW diag.v_estate_week AS
SELECT w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half,
       w.week_start_date, w.week_end_date, w.days_in_week, w.is_comparable_week, w.prior_year_week_key,
       a.trading_store_days, a.sales_lines, a.units_sold, a.transactions, a.gross_sales, a.discount_value,
       a.sales_revenue, a.returns_value, a.net_revenue, a.cogs, a.gross_margin, a.promo_sales_revenue,
       a.promo_discount_value, a.promo_units_sold, a.returned_units, a.return_lines
FROM (
    SELECT d.retail_week_key,
           SUM(CASE WHEN p.sales_lines > 0 THEN 1 ELSE 0 END) AS trading_store_days,
           SUM(p.sales_lines) AS sales_lines, SUM(p.units_sold) AS units_sold, SUM(p.transactions) AS transactions,
           SUM(p.gross_sales) AS gross_sales, SUM(p.discount_value) AS discount_value,
           SUM(p.sales_revenue) AS sales_revenue, SUM(p.returns_value) AS returns_value,
           SUM(p.net_revenue) AS net_revenue, SUM(p.cogs) AS cogs, SUM(p.gross_margin) AS gross_margin,
           SUM(p.promo_sales_revenue) AS promo_sales_revenue, SUM(p.promo_discount_value) AS promo_discount_value,
           SUM(p.promo_units_sold) AS promo_units_sold, SUM(p.returned_units) AS returned_units,
           SUM(p.return_lines) AS return_lines
    FROM mart.v_performance_store_day AS p
    JOIN dw.dim_date AS d ON d.date_key = p.date_key
    GROUP BY d.retail_week_key
) AS a
JOIN dw.dim_retail_week AS w ON w.retail_week_key = a.retail_week_key;
GO

-- H2 week-aligned comparison: each H2 week of a retail year against the same retail week one year earlier
CREATE OR ALTER VIEW diag.v_h2_week_comparison AS
SELECT c.retail_year, c.retail_week, c.retail_week - 26 AS h2_week_index,
       c.retail_week_key AS week_key_cy, p.retail_week_key AS week_key_py,
       c.week_start_date AS week_start_cy, p.week_start_date AS week_start_py,
       c.days_in_week AS days_cy, p.days_in_week AS days_py,
       c.trading_store_days AS trading_store_days_cy, p.trading_store_days AS trading_store_days_py,
       c.sales_revenue AS sales_revenue_cy, p.sales_revenue AS sales_revenue_py,
       c.returns_value AS returns_value_cy, p.returns_value AS returns_value_py,
       c.net_revenue AS net_revenue_cy, p.net_revenue AS net_revenue_py,
       c.gross_margin AS gross_margin_cy, p.gross_margin AS gross_margin_py,
       c.transactions AS transactions_cy, p.transactions AS transactions_py,
       c.units_sold AS units_sold_cy, p.units_sold AS units_sold_py,
       c.returned_units AS returned_units_cy, p.returned_units AS returned_units_py,
       c.promo_sales_revenue AS promo_sales_revenue_cy, p.promo_sales_revenue AS promo_sales_revenue_py,
       c.net_revenue - p.net_revenue AS net_revenue_change,
       100.0 * (CAST(c.net_revenue AS FLOAT) / NULLIF(CAST(p.net_revenue AS FLOAT), 0) - 1) AS net_revenue_yoy_pct
FROM diag.v_estate_week AS c
JOIN diag.v_estate_week AS p ON p.retail_week_key = c.prior_year_week_key
WHERE c.retail_half = N'H2' AND c.retail_week BETWEEN 27 AND 52 AND c.is_comparable_week = 1;
GO

-- H2 totals per retail year from the governed layer, with BRD 5.1 ratios
CREATE OR ALTER VIEW diag.v_h2_headline AS
SELECT h.retail_year, h.weeks, h.days, h.trading_store_days, h.sales_lines, h.gross_sales, h.discount_value,
       h.sales_revenue, h.returns_value, h.net_revenue, h.cogs, h.gross_margin, h.transactions, h.units_sold,
       h.returned_units, h.promo_sales_revenue, h.promo_discount_value, h.promo_units_sold,
       CAST(h.gross_margin AS FLOAT) / NULLIF(CAST(h.net_revenue AS FLOAT), 0)          AS gross_margin_pct,
       CAST(h.sales_revenue AS FLOAT) / NULLIF(CAST(h.transactions AS FLOAT), 0)        AS aov,
       CAST(h.units_sold AS FLOAT) / NULLIF(CAST(h.transactions AS FLOAT), 0)           AS upt,
       CAST(h.sales_revenue AS FLOAT) / NULLIF(CAST(h.units_sold AS FLOAT), 0)          AS asp,
       CAST(h.returns_value AS FLOAT) / NULLIF(CAST(h.sales_revenue AS FLOAT), 0)       AS return_rate_value,
       CAST(h.returned_units AS FLOAT) / NULLIF(CAST(h.units_sold AS FLOAT), 0)         AS return_rate_units,
       CAST(h.promo_sales_revenue AS FLOAT) / NULLIF(CAST(h.sales_revenue AS FLOAT), 0) AS promo_revenue_share
FROM (
    SELECT retail_year, COUNT(*) AS weeks, SUM(days_in_week) AS days, SUM(trading_store_days) AS trading_store_days,
           SUM(sales_lines) AS sales_lines, SUM(gross_sales) AS gross_sales, SUM(discount_value) AS discount_value,
           SUM(sales_revenue) AS sales_revenue, SUM(returns_value) AS returns_value, SUM(net_revenue) AS net_revenue,
           SUM(cogs) AS cogs, SUM(gross_margin) AS gross_margin, SUM(transactions) AS transactions,
           SUM(units_sold) AS units_sold, SUM(returned_units) AS returned_units,
           SUM(promo_sales_revenue) AS promo_sales_revenue, SUM(promo_discount_value) AS promo_discount_value,
           SUM(promo_units_sold) AS promo_units_sold
    FROM diag.v_estate_week
    WHERE retail_half = N'H2' AND retail_week BETWEEN 27 AND 52
    GROUP BY retail_year
) AS h;
GO

-- Independent path for the headline check: straight from the facts, bypassing every mart view
CREATE OR ALTER VIEW diag.v_h2_headline_from_facts AS
SELECT s.retail_year, s.sales_revenue, COALESCE(r.returns_value, 0) AS returns_value,
       s.sales_revenue - COALESCE(r.returns_value, 0) AS net_revenue, s.transactions, s.units_sold
FROM (
    SELECT d.retail_year, CAST(SUM(f.sales_revenue) AS DECIMAL(19,2)) AS sales_revenue,
           COUNT(DISTINCT f.transaction_id) AS transactions, SUM(CAST(f.quantity AS INT)) AS units_sold
    FROM dw.fact_sales AS f JOIN dw.dim_date AS d ON d.date_key = f.date_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY d.retail_year
) AS s
LEFT JOIN (
    SELECT d.retail_year, CAST(SUM(r.refund_value) AS DECIMAL(19,2)) AS returns_value
    FROM dw.fact_returns AS r JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY d.retail_year
) AS r ON r.retail_year = s.retail_year;
GO

-- Store x day completeness: trading days per store and retail week (data-coverage check for comparisons)
CREATE OR ALTER VIEW diag.v_store_week_coverage AS
SELECT d.retail_week_key, w.retail_year, w.retail_week, w.retail_half, w.days_in_week, p.store_key,
       SUM(CASE WHEN p.sales_lines > 0 THEN 1 ELSE 0 END) AS trading_days
FROM mart.v_performance_store_day AS p
JOIN dw.dim_date AS d ON d.date_key = p.date_key
JOIN dw.dim_retail_week AS w ON w.retail_week_key = d.retail_week_key
GROUP BY d.retail_week_key, w.retail_year, w.retail_week, w.retail_half, w.days_in_week, p.store_key;
GO
