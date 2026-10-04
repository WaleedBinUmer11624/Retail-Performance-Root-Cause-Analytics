/* =====================================================================
   Phase 6 root-cause views 01: store-cluster investigation
   ---------------------------------------------------------------------
   Schema rca holds the Phase 6 views. Like Phase 5 (schema diag) they read
   only the Phase 4 governed layer (mart.*) and the dw star schema.
   The views are generic (every store, every date); the Python layer picks
   the investigated stores and the control groups from configuration.
   ===================================================================== */

-- @tsql-only
IF SCHEMA_ID(N'rca') IS NULL EXEC(N'CREATE SCHEMA rca');
GO

-- Store x calendar day with the calendar attributes needed for timing and weekday analysis
CREATE OR ALTER VIEW rca.v_store_day AS
SELECT p.date_key, d.calendar_date, d.day_of_week, d.day_name, d.is_weekend, d.is_bank_holiday,
       d.retail_year, d.retail_week, d.retail_half, d.same_day_last_year_key,
       st.store_key, st.store_id, st.region, st.store_format,
       p.transactions, p.units_sold, p.sales_revenue, p.returns_value, p.net_revenue, p.gross_margin,
       p.promo_sales_revenue, p.discount_value
FROM mart.v_performance_store_day AS p
JOIN dw.dim_date  AS d  ON d.date_key = p.date_key
JOIN dw.dim_store AS st ON st.store_key = p.store_key;
GO

-- One row per receipt: basket value, basket size, promotion content and hour of day
CREATE OR ALTER VIEW rca.v_receipt AS
SELECT f.transaction_id, f.store_key, f.date_key, d.retail_year, d.retail_week, d.retail_half, d.is_weekend,
       MIN(DATEPART(hour, f.transaction_time))                        AS hour_of_day,
       COUNT(*)                                                       AS lines,
       SUM(CAST(f.quantity AS INT))                                   AS units,
       CAST(SUM(f.sales_revenue) AS DECIMAL(19,2))                    AS basket_value,
       MAX(CAST(f.is_promoted AS INT))                                AS has_promoted_line
FROM dw.fact_sales AS f
JOIN dw.dim_date AS d ON d.date_key = f.date_key
GROUP BY f.transaction_id, f.store_key, f.date_key, d.retail_year, d.retail_week, d.retail_half, d.is_weekend;
GO

-- Store x category x retail week: sales, promotion content, units and receipts containing the category
CREATE OR ALTER VIEW rca.v_store_category_week AS
SELECT f.store_key, p.category, d.retail_year, d.retail_week, d.retail_week_key,
       COUNT(DISTINCT f.transaction_id)                                            AS transactions_with_category,
       SUM(CAST(f.quantity AS INT))                                                AS units_sold,
       CAST(SUM(f.gross_amount) AS DECIMAL(19,2))                                  AS gross_sales,
       CAST(SUM(f.discount_amount) AS DECIMAL(19,2))                               AS discount_value,
       CAST(SUM(f.sales_revenue) AS DECIMAL(19,2))                                 AS sales_revenue,
       CAST(SUM(f.cost_amount) AS DECIMAL(19,2))                                   AS cost_of_sales,
       CAST(SUM(CASE WHEN f.is_promoted = 1 THEN f.sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS promo_sales_revenue,
       SUM(CASE WHEN f.is_promoted = 1 THEN CAST(f.quantity AS INT) ELSE 0 END)    AS promo_units_sold
FROM dw.fact_sales AS f
JOIN dw.dim_date    AS d ON d.date_key = f.date_key
JOIN dw.dim_product AS p ON p.product_key = f.product_key
GROUP BY f.store_key, p.category, d.retail_year, d.retail_week, d.retail_week_key;
GO
