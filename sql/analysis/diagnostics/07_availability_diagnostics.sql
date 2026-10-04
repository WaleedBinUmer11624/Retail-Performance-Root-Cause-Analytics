/* =====================================================================
   Phase 5 diagnostics 07: availability and stock-outs
   ---------------------------------------------------------------------
   BRD 5.3: Stock Availability % = ranged store-SKU-weeks with closing stock > 0
                                   / all ranged store-SKU-weeks
            Stock-out Rate %     = 1 - Stock Availability %
   A store-SKU is "ranged" in a week when the weekly stock snapshot has a row
   for it (dw.fact_inventory holds ranged SKUs only).

   Estimated Lost Sales (BR-05) needs a baseline built from each store-SKU's
   own in-stock, non-promoted weeks. The baseline is computed in Python
   (src/analytics/diagnostics.py) from diag.v_stock_cell_week, which gives one
   row per ranged store-SKU-week with sales, stock and promotion coverage.
   The method is documented in docs/05_exploratory_analysis.md.
   ===================================================================== */

-- Promotion coverage expanded to store x SKU x retail week (days covered by any promotion)
CREATE OR ALTER VIEW diag.v_promo_cover_week AS
SELECT d.retail_week_key, c.store_key, c.product_key,
       COUNT(DISTINCT d.calendar_date) AS promo_days,
       MAX(c.discount_pct)             AS max_discount_pct
FROM dw.fact_promotion_coverage AS c
JOIN dw.dim_date AS d ON d.calendar_date BETWEEN c.start_date AND c.end_date AND d.date_key <> -1
GROUP BY d.retail_week_key, c.store_key, c.product_key;
GO

-- One row per ranged store-SKU-week: stock state, till sales, promotion coverage
CREATE OR ALTER VIEW diag.v_stock_cell_week AS
SELECT i.retail_week_key, w.retail_year, w.retail_week, w.retail_half,
       i.store_key, i.product_key, p.category,
       i.opening_stock, i.received_qty, i.closing_stock, CAST(i.is_in_stock AS INT) AS is_in_stock,
       COALESCE(s.units_sold, 0)        AS units_sold,
       COALESCE(s.sales_revenue, 0)     AS sales_revenue,
       COALESCE(s.promo_units_sold, 0)  AS promo_units_sold,
       COALESCE(s.discount_value, 0)    AS discount_value,
       COALESCE(s.cost_of_sales, 0)     AS cost_of_sales,
       COALESCE(pc.promo_days, 0)       AS promo_days
FROM dw.fact_inventory AS i
JOIN dw.dim_retail_week AS w ON w.retail_week_key = i.retail_week_key
JOIN dw.dim_product AS p ON p.product_key = i.product_key
LEFT JOIN (
    SELECT d.retail_week_key, f.store_key, f.product_key,
           SUM(CAST(f.quantity AS INT)) AS units_sold,
           CAST(SUM(f.sales_revenue) AS DECIMAL(19,2)) AS sales_revenue,
           SUM(CASE WHEN f.is_promoted = 1 THEN CAST(f.quantity AS INT) ELSE 0 END) AS promo_units_sold,
           CAST(SUM(f.discount_amount) AS DECIMAL(19,2)) AS discount_value,
           CAST(SUM(f.cost_amount) AS DECIMAL(19,2)) AS cost_of_sales
    FROM dw.fact_sales AS f JOIN dw.dim_date AS d ON d.date_key = f.date_key
    GROUP BY d.retail_week_key, f.store_key, f.product_key
) AS s ON s.retail_week_key = i.retail_week_key AND s.store_key = i.store_key AND s.product_key = i.product_key
LEFT JOIN diag.v_promo_cover_week AS pc
       ON pc.retail_week_key = i.retail_week_key AND pc.store_key = i.store_key AND pc.product_key = i.product_key;
GO

-- Availability by store x category x retail year (H2)
CREATE OR ALTER VIEW diag.v_availability_h2_store_category AS
SELECT i.store_key, st.store_id, st.region, st.store_format, p.category, w.retail_year,
       COUNT(*) AS ranged_cells, SUM(CAST(i.is_in_stock AS INT)) AS in_stock_cells
FROM dw.fact_inventory AS i
JOIN dw.dim_retail_week AS w ON w.retail_week_key = i.retail_week_key
JOIN dw.dim_product AS p ON p.product_key = i.product_key
JOIN dw.dim_store AS st ON st.store_key = i.store_key
WHERE w.retail_week BETWEEN 27 AND 52
GROUP BY i.store_key, st.store_id, st.region, st.store_format, p.category, w.retail_year;
GO

-- Estate availability per retail week (all weeks, for the trend)
CREATE OR ALTER VIEW diag.v_availability_week AS
SELECT w.retail_week_key, w.retail_year, w.retail_week, w.retail_half,
       COUNT(*) AS ranged_cells, SUM(CAST(i.is_in_stock AS INT)) AS in_stock_cells,
       CAST(SUM(CAST(i.is_in_stock AS INT)) AS FLOAT) / NULLIF(CAST(COUNT(*) AS FLOAT), 0) AS stock_availability
FROM dw.fact_inventory AS i
JOIN dw.dim_retail_week AS w ON w.retail_week_key = i.retail_week_key
GROUP BY w.retail_week_key, w.retail_year, w.retail_week, w.retail_half;
GO

-- Availability by supplier and category x retail year (H2): is a stock-out pattern tied to a supply source?
CREATE OR ALTER VIEW diag.v_availability_h2_supplier AS
SELECT a.supplier_id, a.supplier_name, a.category, a.retail_year,
       SUM(a.ranged_cells) AS ranged_cells, SUM(a.in_stock_cells) AS in_stock_cells
FROM mart.v_availability_category_week AS a
WHERE a.retail_week BETWEEN 27 AND 52
GROUP BY a.supplier_id, a.supplier_name, a.category, a.retail_year;
GO
