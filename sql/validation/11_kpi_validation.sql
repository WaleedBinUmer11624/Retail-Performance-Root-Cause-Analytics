/* =====================================================================
   11  KPI layer validation
   ---------------------------------------------------------------------
   Proves that the governed views in mart agree with
     (a) the independent totals in recon.actual (which 09 reconciled to
         Phase 3), and
     (b) each other at every level: store, region, format, category,
         week, product and promotion roll-ups all sum to the estate;
   and that the BRD identities hold on every estate period row.

   The heavier views are materialised once into recon.kv_* snapshot tables
   so each is computed a single time; the result is persisted in
   recon.kpi_validation_result, which the THROW check and the runner read.
   Any FAIL stops the build.
   ===================================================================== */

SET NOCOUNT ON;
DROP TABLE IF EXISTS recon.kv_base;
SELECT CAST(SUM(gross_sales) AS DECIMAL(19,2))         AS gross_sales,
       CAST(SUM(discount_value) AS DECIMAL(19,2))      AS discount_value,
       CAST(SUM(sales_revenue) AS DECIMAL(19,2))       AS sales_revenue,
       CAST(SUM(returns_value) AS DECIMAL(19,2))       AS returns_value,
       CAST(SUM(net_revenue) AS DECIMAL(19,2))         AS net_revenue,
       CAST(SUM(cogs) AS DECIMAL(19,4))                AS cogs,
       CAST(SUM(gross_margin) AS DECIMAL(19,4))        AS gross_margin,
       SUM(transactions)                               AS transactions,
       SUM(units_sold)                                 AS units_sold,
       SUM(sales_lines)                                AS sales_lines,
       CAST(SUM(promo_sales_revenue) AS DECIMAL(19,2)) AS promo_sales_revenue
INTO recon.kv_base
FROM mart.v_performance_store_day;

DROP TABLE IF EXISTS recon.kv_estate;
SELECT * INTO recon.kv_estate FROM mart.v_kpi_estate_period;

DROP TABLE IF EXISTS recon.kv_segment;
SELECT segment_type, retail_year, period,
       CAST(SUM(net_revenue) AS DECIMAL(19,2)) AS net_revenue,
       SUM(transactions)                       AS transactions
INTO recon.kv_segment
FROM mart.v_kpi_segment_period
GROUP BY segment_type, retail_year, period;

DROP TABLE IF EXISTS recon.kv_category;
SELECT retail_year, period,
       CAST(SUM(net_revenue) AS DECIMAL(19,2))   AS net_revenue,
       CAST(SUM(sales_revenue) AS DECIMAL(19,2)) AS sales_revenue
INTO recon.kv_category
FROM mart.v_kpi_category_period
GROUP BY retail_year, period;

DROP TABLE IF EXISTS recon.kv_yoy_estate;
SELECT * INTO recon.kv_yoy_estate FROM mart.v_yoy_segment_period WHERE segment_type = N'Estate';
GO

CREATE OR ALTER VIEW recon.v_kpi_validation AS
WITH act AS (
    SELECT metric_name, actual_value FROM recon.actual
),
checks AS (
    /* (a) governed atomic base = independent reconciled totals */
    SELECT N'base: gross_sales'    AS check_name, (SELECT actual_value FROM act WHERE metric_name = N'gross_sales')    AS expected_value, CAST(gross_sales AS FLOAT)    AS actual_value, 0.01 AS tolerance FROM recon.kv_base UNION ALL
    SELECT N'base: discount_value',  (SELECT actual_value FROM act WHERE metric_name = N'discount_value'),  CAST(discount_value AS FLOAT),  0.01 FROM recon.kv_base UNION ALL
    SELECT N'base: sales_revenue',   (SELECT actual_value FROM act WHERE metric_name = N'sales_revenue'),   CAST(sales_revenue AS FLOAT),   0.01 FROM recon.kv_base UNION ALL
    SELECT N'base: returns_value',   (SELECT actual_value FROM act WHERE metric_name = N'returns_value'),   CAST(returns_value AS FLOAT),   0.01 FROM recon.kv_base UNION ALL
    SELECT N'base: net_revenue',     (SELECT actual_value FROM act WHERE metric_name = N'net_revenue'),     CAST(net_revenue AS FLOAT),     0.01 FROM recon.kv_base UNION ALL
    SELECT N'base: cogs',            (SELECT actual_value FROM act WHERE metric_name = N'cogs'),            CAST(cogs AS FLOAT),            0.01 FROM recon.kv_base UNION ALL
    SELECT N'base: gross_margin',    (SELECT actual_value FROM act WHERE metric_name = N'gross_margin'),    CAST(gross_margin AS FLOAT),    0.01 FROM recon.kv_base UNION ALL
    SELECT N'base: transactions',    (SELECT actual_value FROM act WHERE metric_name = N'transactions'),    CAST(transactions AS FLOAT),    0    FROM recon.kv_base UNION ALL
    SELECT N'base: units',           (SELECT actual_value FROM act WHERE metric_name = N'units'),           CAST(units_sold AS FLOAT),      0    FROM recon.kv_base UNION ALL
    SELECT N'base: sales_lines',     (SELECT actual_value FROM act WHERE metric_name = N'sales_lines'),     CAST(sales_lines AS FLOAT),     0    FROM recon.kv_base UNION ALL
    SELECT N'base: promo_revenue_share', (SELECT actual_value FROM act WHERE metric_name = N'promo_revenue_share'),
           CAST(promo_sales_revenue AS FLOAT) / NULLIF(CAST(sales_revenue AS FLOAT), 0), 0.000001 FROM recon.kv_base UNION ALL
    /* (a) governed headline views = reconciled headline */
    SELECT N'estate H2 2024 net revenue', (SELECT actual_value FROM act WHERE metric_name = N'h2_2024_net_revenue'),
           CAST(net_revenue AS FLOAT), 0.01 FROM recon.kv_estate WHERE retail_year = 2024 AND period = N'H2' UNION ALL
    SELECT N'estate H2 2025 net revenue', (SELECT actual_value FROM act WHERE metric_name = N'h2_2025_net_revenue'),
           CAST(net_revenue AS FLOAT), 0.01 FROM recon.kv_estate WHERE retail_year = 2025 AND period = N'H2' UNION ALL
    SELECT N'estate H2 YoY % (mart.v_yoy_segment_period)', (SELECT actual_value FROM act WHERE metric_name = N'h2_yoy_pct'),
           net_revenue_yoy_pct, 0.0001 FROM recon.kv_yoy_estate WHERE retail_year = 2025 AND period = N'H2' UNION ALL
    SELECT N'estate stock availability 2024', (SELECT actual_value FROM act WHERE metric_name = N'stock_availability_2024'),
           stock_availability, 0.000001 FROM recon.kv_estate WHERE retail_year = 2024 AND period = N'FY' UNION ALL
    SELECT N'estate FY rows sum to base net revenue', (SELECT CAST(net_revenue AS FLOAT) FROM recon.kv_base),
           (SELECT CAST(SUM(net_revenue) AS FLOAT) FROM recon.kv_estate WHERE period = N'FY'), 0.01 UNION ALL
    SELECT N'estate FY rows sum to base transactions', (SELECT CAST(transactions AS FLOAT) FROM recon.kv_base),
           (SELECT CAST(SUM(transactions) AS FLOAT) FROM recon.kv_estate WHERE period = N'FY'), 0 UNION ALL
    /* (b) roll-ups agree with the estate for every year and period */
    SELECT CONCAT(N'segment roll-up = estate: ', s.segment_type), 0,
           CAST(SUM(CASE WHEN ABS(CAST(s.net_revenue AS FLOAT) - CAST(e.net_revenue AS FLOAT)) > 0.01
                          OR s.transactions <> e.transactions THEN 1 ELSE 0 END) AS FLOAT), 0
    FROM recon.kv_segment AS s JOIN recon.kv_estate AS e ON e.retail_year = s.retail_year AND e.period = s.period
    GROUP BY s.segment_type UNION ALL
    SELECT N'category roll-up = estate (net and sales revenue)', 0,
           CAST(SUM(CASE WHEN ABS(CAST(c.net_revenue AS FLOAT) - CAST(e.net_revenue AS FLOAT)) > 0.01
                          OR ABS(CAST(c.sales_revenue AS FLOAT) - CAST(e.sales_revenue AS FLOAT)) > 0.01 THEN 1 ELSE 0 END) AS FLOAT), 0
    FROM recon.kv_category AS c JOIN recon.kv_estate AS e ON e.retail_year = c.retail_year AND e.period = c.period UNION ALL
    SELECT N'store-week view sums to base net revenue', (SELECT CAST(net_revenue AS FLOAT) FROM recon.kv_base),
           (SELECT CAST(SUM(net_revenue) AS FLOAT) FROM mart.v_performance_store_week), 0.01 UNION ALL
    SELECT N'store-week targets = all targets loaded', (SELECT CAST(SUM(target_net_revenue) AS FLOAT) FROM dw.fact_targets),
           (SELECT CAST(SUM(target_net_revenue) AS FLOAT) FROM mart.v_performance_store_week), 0.01 UNION ALL
    SELECT N'product-store-week view sums to units', (SELECT actual_value FROM act WHERE metric_name = N'units'),
           (SELECT CAST(SUM(units_sold) AS FLOAT) FROM mart.v_product_store_week), 0 UNION ALL
    SELECT N'product-store-week view sums to sales revenue', (SELECT actual_value FROM act WHERE metric_name = N'sales_revenue'),
           (SELECT CAST(SUM(sales_revenue) AS FLOAT) FROM mart.v_product_store_week), 0.01 UNION ALL
    SELECT N'promotion view: promoted revenue = promo sales revenue', (SELECT CAST(promo_sales_revenue AS FLOAT) FROM recon.kv_base),
           (SELECT CAST(SUM(promoted_sales_revenue) AS FLOAT) FROM mart.v_promotion_performance WHERE promotion_key <> 0), 0.01 UNION ALL
    SELECT N'promotion view: all members sum to sales revenue', (SELECT actual_value FROM act WHERE metric_name = N'sales_revenue'),
           (SELECT CAST(SUM(promoted_sales_revenue) AS FLOAT) FROM mart.v_promotion_performance), 0.01 UNION ALL
    SELECT N'returns view sums to returns value', (SELECT actual_value FROM act WHERE metric_name = N'returns_value'),
           (SELECT CAST(SUM(returns_value) AS FLOAT) FROM mart.v_returns_analysis), 0.01 UNION ALL
    SELECT N'availability view 2024 = reconciled availability', (SELECT actual_value FROM act WHERE metric_name = N'stock_availability_2024'),
           (SELECT CAST(SUM(in_stock_cells) AS FLOAT) / NULLIF(CAST(SUM(ranged_cells) AS FLOAT), 0)
            FROM mart.v_availability_store_week WHERE retail_year = 2024), 0.000001 UNION ALL
    SELECT N'category availability view = store availability view (cells)',
           (SELECT CAST(SUM(ranged_cells) AS FLOAT) FROM mart.v_availability_store_week),
           (SELECT CAST(SUM(ranged_cells) AS FLOAT) FROM mart.v_availability_category_week), 0 UNION ALL
    SELECT N'line-level view row count = fact_sales', (SELECT actual_value FROM act WHERE metric_name = N'sales_lines'),
           (SELECT CAST(COUNT(*) AS FLOAT) FROM mart.v_sales_line), 0 UNION ALL
    /* (c) BRD identities on every estate period row (count of violating rows), in FLOAT to avoid decimal rescaling */
    SELECT N'identity: Sales Revenue = Gross Sales - Discount Value', 0,
           CAST(SUM(CASE WHEN ABS(CAST(sales_revenue AS FLOAT) - (CAST(gross_sales AS FLOAT) - CAST(discount_value AS FLOAT))) > 0.01
                         THEN 1 ELSE 0 END) AS FLOAT), 0 FROM recon.kv_estate UNION ALL
    SELECT N'identity: Net Revenue = Sales Revenue - Returns Value', 0,
           CAST(SUM(CASE WHEN ABS(CAST(net_revenue AS FLOAT) - (CAST(sales_revenue AS FLOAT) - CAST(returns_value AS FLOAT))) > 0.01
                         THEN 1 ELSE 0 END) AS FLOAT), 0 FROM recon.kv_estate UNION ALL
    SELECT N'identity: Gross Margin = Net Revenue - COGS', 0,
           CAST(SUM(CASE WHEN ABS(CAST(gross_margin AS FLOAT) - (CAST(net_revenue AS FLOAT) - CAST(cogs AS FLOAT))) > 0.01
                         THEN 1 ELSE 0 END) AS FLOAT), 0 FROM recon.kv_estate UNION ALL
    SELECT N'identity: Sales Revenue = Transactions x UPT x ASP', 0,
           CAST(SUM(CASE WHEN ABS(CAST(sales_revenue AS FLOAT) - transactions * upt * asp) > 0.01 THEN 1 ELSE 0 END) AS FLOAT), 0
    FROM recon.kv_estate UNION ALL
    SELECT N'identity: AOV = UPT x ASP', 0,
           CAST(SUM(CASE WHEN ABS(aov - upt * asp) > 0.000001 THEN 1 ELSE 0 END) AS FLOAT), 0 FROM recon.kv_estate UNION ALL
    SELECT N'identity: Gross Margin % x Net Revenue = Gross Margin', 0,
           CAST(SUM(CASE WHEN ABS(gross_margin_pct * CAST(net_revenue AS FLOAT) - CAST(gross_margin AS FLOAT)) > 0.01
                         THEN 1 ELSE 0 END) AS FLOAT), 0 FROM recon.kv_estate
)
SELECT check_name, expected_value, actual_value, ABS(actual_value - expected_value) AS abs_difference, tolerance,
       CASE WHEN expected_value IS NULL OR actual_value IS NULL THEN N'FAIL'
            WHEN ABS(actual_value - expected_value) <= tolerance THEN N'PASS'
            ELSE N'FAIL' END AS status
FROM checks;
GO

SET NOCOUNT ON;
DROP TABLE IF EXISTS recon.kpi_validation_result;
SELECT * INTO recon.kpi_validation_result FROM recon.v_kpi_validation;
GO

-- @tsql-only
IF EXISTS (SELECT 1 FROM recon.kpi_validation_result WHERE status <> N'PASS')
BEGIN
    THROW 50002, N'KPI validation failed: see recon.kpi_validation_result', 1;
END;
GO
