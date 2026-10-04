/* =====================================================================
   Phase 5 diagnostics 08: promotions
   ---------------------------------------------------------------------
   BRD 5.4:
     Promo Revenue Share %    = Sales Revenue on promoted lines / Sales Revenue
                                (promoted lines include the UNKNOWN promotion)
     Promo Discount Cost      = Discount Value on promoted lines
     Promo Uplift %           = (Units during promotion - Baseline units) / Baseline units,
                                baseline = same SKU and store, comparable non-promoted weeks
     Incremental Promo Margin = incremental gross margin from uplift - Promo Discount Cost
   Uplift, baseline and the post-promotion (pull-forward) check are computed
   in Python from diag.v_promo_event_week joined to diag.v_stock_cell_week
   (script 07). This script supplies the promotion scope and the line-level
   summaries.
   ===================================================================== */

-- Promoted vs non-promoted sales by retail year (H2), category and promotion type
CREATE OR ALTER VIEW diag.v_promo_h2_lines AS
SELECT d.retail_year, p.category,
       CASE WHEN f.is_promoted = 1 THEN pr.promotion_type ELSE N'Not promoted' END AS promotion_type,
       f.is_promoted,
       COUNT(*)                                        AS sales_lines,
       SUM(CAST(f.quantity AS INT))                    AS units_sold,
       CAST(SUM(f.gross_amount) AS DECIMAL(19,2))      AS gross_sales,
       CAST(SUM(f.discount_amount) AS DECIMAL(19,2))   AS discount_value,
       CAST(SUM(f.sales_revenue) AS DECIMAL(19,2))     AS sales_revenue,
       CAST(SUM(f.cost_amount) AS DECIMAL(19,2))       AS cost_of_sales,
       COUNT(DISTINCT f.promotion_key)                 AS promotions
FROM dw.fact_sales AS f
JOIN dw.dim_date AS d ON d.date_key = f.date_key
JOIN dw.dim_product AS p ON p.product_key = f.product_key
JOIN dw.dim_promotion AS pr ON pr.promotion_key = f.promotion_key
WHERE d.retail_week BETWEEN 27 AND 52
GROUP BY d.retail_year, p.category, CASE WHEN f.is_promoted = 1 THEN pr.promotion_type ELSE N'Not promoted' END, f.is_promoted;
GO

-- Promotion scope planned in each H2: promotions starting in the half, store-SKU coverage and depth
CREATE OR ALTER VIEW diag.v_promo_h2_scope AS
SELECT d.retail_year, pr.promotion_type, pr.promotion_category,
       COUNT(DISTINCT c.promotion_key)                                     AS promotions,
       COUNT(*)                                                            AS store_sku_events,
       SUM(DATEDIFF(day, c.start_date, c.end_date) + 1)                    AS store_sku_promo_days,
       AVG(CAST(c.discount_pct AS FLOAT))                                  AS avg_discount_pct
FROM dw.fact_promotion_coverage AS c
JOIN dw.dim_promotion AS pr ON pr.promotion_key = c.promotion_key
JOIN dw.dim_date AS d ON d.calendar_date = c.start_date
WHERE d.retail_week BETWEEN 27 AND 52
GROUP BY d.retail_year, pr.promotion_type, pr.promotion_category;
GO

-- Store-SKU promotion events by retail week (input to the uplift and pull-forward analysis)
CREATE OR ALTER VIEW diag.v_promo_event_week AS
SELECT c.promotion_key, pr.promotion_type, c.store_key, c.product_key, c.start_date, c.end_date,
       CAST(c.discount_pct AS FLOAT) AS discount_pct,
       d.retail_week_key, COUNT(*) AS promo_days_in_week
FROM dw.fact_promotion_coverage AS c
JOIN dw.dim_promotion AS pr ON pr.promotion_key = c.promotion_key
JOIN dw.dim_date AS d ON d.calendar_date BETWEEN c.start_date AND c.end_date AND d.date_key <> -1
GROUP BY c.promotion_key, pr.promotion_type, c.store_key, c.product_key, c.start_date, c.end_date, c.discount_pct,
         d.retail_week_key;
GO
