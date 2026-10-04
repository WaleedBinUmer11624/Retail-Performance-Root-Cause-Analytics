/* =====================================================================
   09  Reconciliation against the Phase 3 trusted outputs
   ---------------------------------------------------------------------
   recon.expected  is loaded by the runner (src/sql_model) before this
                   script, from Phase 3's own outputs:
                     reports/phase3/lineage.json          curated row counts
                     reports/phase3/kpi_reconciliation.csv  "clean_complete" KPIs
                     data/processed/curated/*.csv         UNKNOWN-member counts
                   Each metric carries an explicit absolute tolerance.
   recon.actual    is computed here, independently, from stg and dw tables.
   recon.v_reconciliation compares the two; any FAIL (difference above
   tolerance, or a metric missing on either side) stops the build.
   ===================================================================== */

/* Totals of the loaded star schema, one row. Definitions follow BRD 5.1.
   Sums are cast to DECIMAL(19,2) / DECIMAL(19,4) so that later subtractions
   stay within 38 digits and are never rounded by SQL Server. */
CREATE OR ALTER VIEW recon.v_dw_totals AS
SELECT s.sales_lines, s.gross_sales, s.discount_value, s.sales_revenue, s.cost_of_sales, s.units_sold, s.transactions,
       s.promo_sales_revenue,
       r.returns_rows, r.returns_value, r.restock_cost_credit,
       i.inventory_cells_2024, i.in_stock_cells_2024,
       h.h2_2024_sales_revenue, h.h2_2025_sales_revenue,
       hr.h2_2024_returns_value, hr.h2_2025_returns_value
FROM (
    SELECT COUNT(*)                                                                         AS sales_lines,
           CAST(SUM(gross_amount) AS DECIMAL(19,2))                                         AS gross_sales,
           CAST(SUM(discount_amount) AS DECIMAL(19,2))                                      AS discount_value,
           CAST(SUM(sales_revenue) AS DECIMAL(19,2))                                        AS sales_revenue,
           CAST(SUM(cost_amount) AS DECIMAL(19,2))                                          AS cost_of_sales,
           SUM(CAST(quantity AS INT))                                                       AS units_sold,
           COUNT(DISTINCT transaction_id)                                                   AS transactions,
           CAST(SUM(CASE WHEN is_promoted = 1 THEN sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS promo_sales_revenue
    FROM dw.fact_sales
) AS s
CROSS JOIN (
    SELECT COUNT(*)                                          AS returns_rows,
           CAST(SUM(refund_value) AS DECIMAL(19,2))          AS returns_value,
           CAST(SUM(restock_cost_credit) AS DECIMAL(19,4))   AS restock_cost_credit
    FROM dw.fact_returns
) AS r
CROSS JOIN (
    SELECT COUNT(*)                         AS inventory_cells_2024,
           SUM(CAST(f.is_in_stock AS INT))  AS in_stock_cells_2024
    FROM dw.fact_inventory AS f
    JOIN dw.dim_date AS d ON d.date_key = f.snapshot_date_key
    WHERE d.retail_year = 2024
) AS i
CROSS JOIN (
    SELECT CAST(SUM(CASE WHEN d.retail_year = 2024 THEN f.sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS h2_2024_sales_revenue,
           CAST(SUM(CASE WHEN d.retail_year = 2025 THEN f.sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS h2_2025_sales_revenue
    FROM dw.fact_sales AS f
    JOIN dw.dim_date AS d ON d.date_key = f.date_key
    WHERE d.retail_week BETWEEN 27 AND 52
) AS h
CROSS JOIN (
    SELECT CAST(SUM(CASE WHEN d.retail_year = 2024 THEN f.refund_value ELSE 0 END) AS DECIMAL(19,2)) AS h2_2024_returns_value,
           CAST(SUM(CASE WHEN d.retail_year = 2025 THEN f.refund_value ELSE 0 END) AS DECIMAL(19,2)) AS h2_2025_returns_value
    FROM dw.fact_returns AS f
    JOIN dw.dim_date AS d ON d.date_key = f.return_date_key
    WHERE d.retail_week BETWEEN 27 AND 52
) AS hr;
GO

-- Materialise the totals once: every metric below reads this one-row table,
-- so fact_sales is aggregated once rather than once per metric.
SET NOCOUNT ON;
DROP TABLE IF EXISTS recon.dw_totals;
SELECT * INTO recon.dw_totals FROM recon.v_dw_totals;
DELETE FROM recon.actual;
INSERT INTO recon.actual (metric_name, actual_value, computed_from)
/* row counts: staging = curated files */
SELECT N'rows_stg_dim_date',        CAST(COUNT(*) AS FLOAT), N'stg.dim_date'        FROM stg.dim_date        UNION ALL
SELECT N'rows_stg_dim_store',       CAST(COUNT(*) AS FLOAT), N'stg.dim_store'       FROM stg.dim_store       UNION ALL
SELECT N'rows_stg_dim_product',     CAST(COUNT(*) AS FLOAT), N'stg.dim_product'     FROM stg.dim_product     UNION ALL
SELECT N'rows_stg_fact_sales',      CAST(COUNT(*) AS FLOAT), N'stg.fact_sales'      FROM stg.fact_sales      UNION ALL
SELECT N'rows_stg_fact_returns',    CAST(COUNT(*) AS FLOAT), N'stg.fact_returns'    FROM stg.fact_returns    UNION ALL
SELECT N'rows_stg_fact_inventory',  CAST(COUNT(*) AS FLOAT), N'stg.fact_inventory'  FROM stg.fact_inventory  UNION ALL
SELECT N'rows_stg_fact_promotions', CAST(COUNT(*) AS FLOAT), N'stg.fact_promotions' FROM stg.fact_promotions UNION ALL
SELECT N'rows_stg_fact_targets',    CAST(COUNT(*) AS FLOAT), N'stg.fact_targets'    FROM stg.fact_targets    UNION ALL
/* row counts: star schema = curated files (UNKNOWN members added by the model are excluded) */
SELECT N'rows_dw_dim_date',       CAST(COUNT(*) AS FLOAT), N'dw.dim_date (excl. -1)'      FROM dw.dim_date    WHERE date_key <> -1  UNION ALL
SELECT N'rows_dw_dim_store',      CAST(COUNT(*) AS FLOAT), N'dw.dim_store (excl. -1)'     FROM dw.dim_store   WHERE store_key <> -1 UNION ALL
SELECT N'rows_dw_dim_product',    CAST(COUNT(*) AS FLOAT), N'dw.dim_product (incl. curated UNKNOWN)' FROM dw.dim_product              UNION ALL
SELECT N'rows_dw_dim_promotion',  CAST(COUNT(*) AS FLOAT), N'dw.dim_promotion (excl. 0, -1)' FROM dw.dim_promotion WHERE promotion_key > 0 UNION ALL
SELECT N'rows_dw_fact_sales',     CAST(COUNT(*) AS FLOAT), N'dw.fact_sales'               FROM dw.fact_sales                         UNION ALL
SELECT N'rows_dw_fact_returns',   CAST(COUNT(*) AS FLOAT), N'dw.fact_returns'             FROM dw.fact_returns                       UNION ALL
SELECT N'rows_dw_fact_inventory', CAST(COUNT(*) AS FLOAT), N'dw.fact_inventory'           FROM dw.fact_inventory                     UNION ALL
SELECT N'rows_dw_fact_targets',   CAST(COUNT(*) AS FLOAT), N'dw.fact_targets'             FROM dw.fact_targets                       UNION ALL
SELECT N'rows_dw_fact_promotion_coverage', CAST(COUNT(*) AS FLOAT), N'dw.fact_promotion_coverage' FROM dw.fact_promotion_coverage    UNION ALL
/* UNKNOWN-member usage: must match the curated data exactly */
SELECT N'unknown_product_sales_lines',   CAST(COUNT(*) AS FLOAT), N'dw.fact_sales product_key = -1'   FROM dw.fact_sales WHERE product_key = -1   UNION ALL
SELECT N'unknown_promotion_sales_lines', CAST(COUNT(*) AS FLOAT), N'dw.fact_sales promotion_key = -1' FROM dw.fact_sales WHERE promotion_key = -1 UNION ALL
SELECT N'not_promoted_sales_lines',      CAST(COUNT(*) AS FLOAT), N'dw.fact_sales promotion_key = 0'  FROM dw.fact_sales WHERE promotion_key = 0  UNION ALL
SELECT N'unknown_store_fact_rows',       CAST(SUM(n) AS FLOAT),   N'store_key = -1 in all facts'
FROM (SELECT COUNT(*) AS n FROM dw.fact_sales WHERE store_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_returns WHERE store_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_inventory WHERE store_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_targets WHERE store_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_promotion_coverage WHERE store_key = -1) AS u      UNION ALL
SELECT N'unknown_date_fact_rows',        CAST(SUM(n) AS FLOAT),   N'date/week key = -1 in all facts'
FROM (SELECT COUNT(*) AS n FROM dw.fact_sales WHERE date_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_returns WHERE return_date_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_inventory WHERE snapshot_date_key = -1 OR retail_week_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_targets WHERE retail_week_key = -1) AS u            UNION ALL
SELECT N'unknown_product_other_fact_rows', CAST(SUM(n) AS FLOAT), N'product_key = -1 outside fact_sales'
FROM (SELECT COUNT(*) AS n FROM dw.fact_returns WHERE product_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_inventory WHERE product_key = -1
      UNION ALL SELECT COUNT(*) FROM dw.fact_promotion_coverage WHERE product_key = -1 OR promotion_key = -1) AS u UNION ALL
/* silent conversion failures on nullable typed columns (NOT NULL columns fail the load instead) */
SELECT N'conversion_failures', CAST(COUNT(*) AS FLOAT), N'stg value present but typed value NULL'
FROM stg.fact_sales AS s
JOIN dw.fact_sales AS f ON f.transaction_id = s.transaction_id AND f.line_number = TRY_CONVERT(SMALLINT, s.line_number)
WHERE (s.transaction_time IS NOT NULL AND f.transaction_time IS NULL)
   OR (s.extract_lag_days IS NOT NULL AND f.extract_lag_days IS NULL)                                                UNION ALL
/* financial and operational KPIs (BRD 5.1, 5.3, 5.4) */
SELECT N'sales_lines',        CAST(sales_lines AS FLOAT),    N'COUNT(*) dw.fact_sales'                FROM recon.dw_totals UNION ALL
SELECT N'gross_sales',        CAST(gross_sales AS FLOAT),    N'SUM(quantity x unit_price)'            FROM recon.dw_totals UNION ALL
SELECT N'discount_value',     CAST(discount_value AS FLOAT), N'SUM(discount)'                         FROM recon.dw_totals UNION ALL
SELECT N'sales_revenue',      CAST(sales_revenue AS FLOAT),  N'Gross Sales - Discount Value'          FROM recon.dw_totals UNION ALL
SELECT N'returns_value',      CAST(returns_value AS FLOAT),  N'SUM(refund_value)'                     FROM recon.dw_totals UNION ALL
SELECT N'returns_rows',       CAST(returns_rows AS FLOAT),   N'COUNT(*) dw.fact_returns'              FROM recon.dw_totals UNION ALL
SELECT N'net_revenue',        CAST(sales_revenue - returns_value AS FLOAT), N'Sales Revenue - Returns Value' FROM recon.dw_totals UNION ALL
SELECT N'cogs',               CAST(cost_of_sales - restock_cost_credit AS FLOAT), N'SUM(cost) - returned-to-stock cost' FROM recon.dw_totals UNION ALL
SELECT N'gross_margin',       CAST((sales_revenue - returns_value) - (cost_of_sales - restock_cost_credit) AS FLOAT),
                              N'Net Revenue - COGS'                                                   FROM recon.dw_totals UNION ALL
SELECT N'gross_margin_pct',   CAST((sales_revenue - returns_value) - (cost_of_sales - restock_cost_credit) AS FLOAT)
                              / NULLIF(CAST(sales_revenue - returns_value AS FLOAT), 0), N'Gross Margin / Net Revenue' FROM recon.dw_totals UNION ALL
SELECT N'transactions',       CAST(transactions AS FLOAT),   N'COUNT(DISTINCT transaction_id)'        FROM recon.dw_totals UNION ALL
SELECT N'units',              CAST(units_sold AS FLOAT),     N'SUM(quantity)'                         FROM recon.dw_totals UNION ALL
SELECT N'aov',                CAST(sales_revenue AS FLOAT) / NULLIF(CAST(transactions AS FLOAT), 0), N'Sales Revenue / Transactions' FROM recon.dw_totals UNION ALL
SELECT N'upt',                CAST(units_sold AS FLOAT) / NULLIF(CAST(transactions AS FLOAT), 0),    N'Units / Transactions'         FROM recon.dw_totals UNION ALL
SELECT N'asp',                CAST(sales_revenue AS FLOAT) / NULLIF(CAST(units_sold AS FLOAT), 0),   N'Sales Revenue / Units'        FROM recon.dw_totals UNION ALL
SELECT N'return_rate_value',  CAST(returns_value AS FLOAT) / NULLIF(CAST(sales_revenue AS FLOAT), 0), N'Returns Value / Sales Revenue' FROM recon.dw_totals UNION ALL
SELECT N'promo_revenue_share', CAST(promo_sales_revenue AS FLOAT) / NULLIF(CAST(sales_revenue AS FLOAT), 0), N'Promoted Sales Revenue / Sales Revenue' FROM recon.dw_totals UNION ALL
SELECT N'stock_availability_2024', CAST(in_stock_cells_2024 AS FLOAT) / NULLIF(CAST(inventory_cells_2024 AS FLOAT), 0),
                              N'In-stock store-SKU-weeks / ranged store-SKU-weeks, retail 2024'        FROM recon.dw_totals UNION ALL
SELECT N'h2_2024_net_revenue', CAST(h2_2024_sales_revenue - h2_2024_returns_value AS FLOAT), N'Retail 2024 weeks 27-52' FROM recon.dw_totals UNION ALL
SELECT N'h2_2025_net_revenue', CAST(h2_2025_sales_revenue - h2_2025_returns_value AS FLOAT), N'Retail 2025 weeks 27-52' FROM recon.dw_totals UNION ALL
SELECT N'h2_yoy_pct',         100.0 * (CAST(h2_2025_sales_revenue - h2_2025_returns_value AS FLOAT)
                              / NULLIF(CAST(h2_2024_sales_revenue - h2_2024_returns_value AS FLOAT), 0) - 1),
                              N'(H2 2025 / H2 2024 - 1) x 100, week-aligned'                            FROM recon.dw_totals;
GO

CREATE OR ALTER VIEW recon.v_reconciliation AS
SELECT COALESCE(e.metric_name, a.metric_name)                       AS metric_name,
       e.metric_group,
       e.expected_value,
       a.actual_value,
       ABS(a.actual_value - e.expected_value)                        AS abs_difference,
       e.tolerance_abs,
       CASE WHEN e.metric_name IS NULL THEN N'FAIL'                  -- computed but no expectation
            WHEN a.metric_name IS NULL OR a.actual_value IS NULL THEN N'FAIL'
            WHEN ABS(a.actual_value - e.expected_value) <= e.tolerance_abs THEN N'PASS'
            ELSE N'FAIL' END                                         AS status,
       e.expected_source,
       a.computed_from
FROM recon.expected AS e
FULL OUTER JOIN recon.actual AS a ON a.metric_name = e.metric_name;
GO

-- @tsql-only
-- Stop the build when any metric is outside tolerance.
IF EXISTS (SELECT 1 FROM recon.v_reconciliation WHERE status <> N'PASS')
BEGIN
    THROW 50001, N'Reconciliation failed: see recon.v_reconciliation', 1;
END;
GO
