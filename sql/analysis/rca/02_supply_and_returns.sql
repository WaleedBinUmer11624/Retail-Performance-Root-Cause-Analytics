/* =====================================================================
   Phase 6 root-cause views 02: supply (stock-out episodes) and returns
   ---------------------------------------------------------------------
   * rca.v_stockout_episode groups consecutive stock-out weeks of the same
     store-SKU into episodes (gaps and islands on the retail-week sequence),
     with receipts during the episode.
   * rca.v_return_detail links each return to its original sale line where the
     link exists (product, supplier, promotion status of the sale, sale-to-
     return lag). return_reason is the reason recorded at the till; it is not
     a verified fault.
   ===================================================================== */

-- Store x SKU x retail week with supplier, stock and receipts (ranged cells only)
CREATE OR ALTER VIEW rca.v_sku_week_supply AS
SELECT c.retail_week_key, c.retail_year, c.retail_week, c.store_key, c.product_key, c.category,
       p.product_id, p.supplier_name, p.list_price,
       c.opening_stock, c.received_qty, c.closing_stock, c.is_in_stock, c.units_sold, c.sales_revenue, c.promo_days,
       DENSE_RANK() OVER (ORDER BY c.retail_week_key) AS week_seq
FROM diag.v_stock_cell_week AS c
JOIN dw.dim_product AS p ON p.product_key = c.product_key;
GO

-- Consecutive stock-out weeks of one store-SKU form an episode
CREATE OR ALTER VIEW rca.v_stockout_episode AS
SELECT e.store_key, e.product_key, e.product_id, e.category, e.supplier_name, e.episode_group,
       MIN(e.retail_week_key) AS first_week_key, MAX(e.retail_week_key) AS last_week_key,
       COUNT(*) AS weeks_out,
       SUM(CASE WHEN e.opening_stock <= 0 AND e.received_qty <= 0 THEN 1 ELSE 0 END) AS full_weeks_out,
       SUM(e.received_qty) AS received_during_episode,
       SUM(e.units_sold) AS units_sold_during_episode
FROM (
    SELECT s.*, s.week_seq - ROW_NUMBER() OVER (PARTITION BY s.store_key, s.product_key ORDER BY s.week_seq) AS episode_group
    FROM rca.v_sku_week_supply AS s
    WHERE s.is_in_stock = 0
) AS e
GROUP BY e.store_key, e.product_key, e.product_id, e.category, e.supplier_name, e.episode_group;
GO

-- Returns with the original sale where linked
CREATE OR ALTER VIEW rca.v_return_detail AS
SELECT r.return_id, r.return_date_key, d.calendar_date AS return_date, d.retail_year AS return_retail_year,
       d.retail_week AS return_retail_week, r.store_key, st.store_id,
       r.product_key, p.product_id, p.product_name, p.category, p.supplier_name,
       r.return_reason, r.return_quantity, r.refund_value, r.is_restockable, r.restock_cost_credit, r.has_receipt,
       r.original_sale_store_key,
       od.calendar_date AS original_sale_date, od.retail_year AS sale_retail_year, od.retail_week AS sale_retail_week,
       od.year_month AS sale_year_month,
       CASE WHEN od.calendar_date IS NULL THEN NULL ELSE DATEDIFF(day, od.calendar_date, d.calendar_date) END AS days_sale_to_return,
       f.is_promoted AS sale_was_promoted, f.unit_price AS sale_unit_price,
       CASE WHEN r.original_sales_line_id IS NULL THEN 0 ELSE 1 END AS is_linked_line
FROM dw.fact_returns AS r
JOIN dw.dim_date    AS d  ON d.date_key = r.return_date_key
JOIN dw.dim_store   AS st ON st.store_key = r.store_key
JOIN dw.dim_product AS p  ON p.product_key = r.product_key
LEFT JOIN dw.dim_date   AS od ON od.date_key = r.original_sale_date_key AND od.date_key <> -1
LEFT JOIN dw.fact_sales AS f  ON f.sales_line_id = r.original_sales_line_id;
GO

-- Product x sale month: units sold (denominator for return rates by sale cohort)
CREATE OR ALTER VIEW rca.v_product_sale_month AS
SELECT f.product_key, d.year_month AS sale_year_month, d.retail_year,
       SUM(CAST(f.quantity AS INT)) AS units_sold, CAST(SUM(f.sales_revenue) AS DECIMAL(19,2)) AS sales_revenue
FROM dw.fact_sales AS f
JOIN dw.dim_date AS d ON d.date_key = f.date_key
GROUP BY f.product_key, d.year_month, d.retail_year;
GO

-- Store x category x retail year (H2): exact net revenue and margin intersections for the overlap analysis
CREATE OR ALTER VIEW rca.v_store_category_h2 AS
SELECT u.store_key, u.category, u.retail_year,
       SUM(u.sales_revenue) AS sales_revenue, SUM(u.returns_value) AS returns_value,
       CAST(SUM(u.sales_revenue) AS DECIMAL(19,2)) - CAST(SUM(u.returns_value) AS DECIMAL(19,2)) AS net_revenue,
       CAST(SUM(u.cost_of_sales) AS DECIMAL(19,2)) - CAST(SUM(u.restock_cost_credit) AS DECIMAL(19,4)) AS cogs
FROM (
    SELECT f.store_key, p.category, d.retail_year,
           CAST(SUM(f.sales_revenue) AS DECIMAL(19,2)) AS sales_revenue, CAST(0 AS DECIMAL(19,2)) AS returns_value,
           CAST(SUM(f.cost_amount) AS DECIMAL(19,2)) AS cost_of_sales, CAST(0 AS DECIMAL(19,4)) AS restock_cost_credit
    FROM dw.fact_sales AS f
    JOIN dw.dim_date AS d ON d.date_key = f.date_key
    JOIN dw.dim_product AS p ON p.product_key = f.product_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY f.store_key, p.category, d.retail_year
    UNION ALL
    SELECT r.store_key, p.category, d.retail_year, 0, CAST(SUM(r.refund_value) AS DECIMAL(19,2)), 0,
           CAST(SUM(r.restock_cost_credit) AS DECIMAL(19,4))
    FROM dw.fact_returns AS r
    JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
    JOIN dw.dim_product AS p ON p.product_key = r.product_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY r.store_key, p.category, d.retail_year
) AS u
GROUP BY u.store_key, u.category, u.retail_year;
GO
