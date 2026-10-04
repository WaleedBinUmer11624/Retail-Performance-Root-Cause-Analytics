/* =====================================================================
   Phase 9 monitoring layer (schema mon)
   ---------------------------------------------------------------------
   Weekly KPI views for the early-warning framework. They read only the
   Phase 4 dw star schema and reuse its governed definitions:
     * Net Revenue   = sales_revenue - refund_value          (BRD 5.1)
     * COGS          = cost_amount - restock_cost_credit     (docs/04 7.1)
     * Gross Margin  = Net Revenue - COGS
     * Transactions  = distinct receipts (transaction_id); at category
       grain, receipts containing the category (Phase 4/5 definition)
     * Availability  = in-stock store-SKU-weeks / ranged store-SKU-weeks
     * Full-week stock-out = no opening stock, nothing received, out of
       stock at the weekly snapshot (Phase 5/6/7 definition)
   Only additive components are stored; every ratio is computed in Python
   (src/monitoring/kpis.py) from these sums, never averaged.

   Two views of each week are kept:
     * final values (all lines, as the governed model holds them);
     * on-time values: only lines whose extract_timestamp is at or before
       the weekly run (06:00 on the Monday after the retail week closes).
       This is what a Monday-morning monitoring run would actually have
       seen, so late-arriving batches can be replayed honestly.
   The partial retail week at the extract end (3 days) is excluded.
   ===================================================================== */

-- @tsql-only
IF SCHEMA_ID(N'mon') IS NULL EXEC(N'CREATE SCHEMA mon');
GO

-- One row per complete retail week, with the prior-year week (same retail week, 364 days earlier) and the run time.
CREATE OR ALTER VIEW mon.week_calendar AS
WITH w AS (
    SELECT d.retail_week_key, MIN(d.retail_year) AS retail_year, MIN(d.retail_week) AS retail_week,
           MIN(d.calendar_date) AS week_start, MAX(d.calendar_date) AS week_end, COUNT(*) AS days_in_week,
           SUM(CAST(d.is_trading_day AS INT)) AS trading_days
    FROM dw.dim_date AS d
    WHERE d.is_unknown = 0
    GROUP BY d.retail_week_key
)
SELECT w.retail_week_key, w.retail_year, w.retail_week, w.week_start, w.week_end, w.days_in_week, w.trading_days,
       ly.retail_week_key AS py_week_key,
       -- Sunday 00:00 plus 30 hours = Monday 06:00, the weekly run time.
       DATEADD(HOUR, 30, CAST(w.week_end AS DATETIME2(0))) AS run_time
FROM w
JOIN dw.dim_date AS s ON s.calendar_date = w.week_start
LEFT JOIN dw.dim_date AS ly ON ly.date_key = s.same_day_last_year_key
WHERE w.days_in_week = 7;
GO

-- Sales lines with their week and run time (helper; one row per sales line).
CREATE OR ALTER VIEW mon.sales_line_week AS
SELECT f.store_key, f.product_key, f.date_key, c.retail_week_key, f.transaction_id, f.quantity, f.gross_amount,
       f.discount_amount, f.sales_revenue, f.cost_amount, f.is_promoted, f.is_late_arriving, f.is_imputed,
       f.dq_status, f.promotion_key, f.extract_timestamp,
       CASE WHEN f.extract_timestamp <= c.run_time THEN 1 ELSE 0 END AS is_on_time
FROM dw.fact_sales AS f
JOIN dw.dim_date AS d ON d.date_key = f.date_key
JOIN mon.week_calendar AS c ON c.retail_week_key = d.retail_week_key;
GO

-- Store x week: sales side (final and on-time) plus row-level data-quality counts.
CREATE OR ALTER VIEW mon.sales_store_week AS
SELECT s.store_key, s.retail_week_key,
       SUM(s.sales_revenue) AS sales_revenue, SUM(s.gross_amount) AS gross_amount,
       SUM(s.discount_amount) AS discount_amount, SUM(s.cost_amount) AS cost_amount,
       SUM(CAST(s.quantity AS INT)) AS units, COUNT(DISTINCT s.transaction_id) AS transactions,
       SUM(CASE WHEN s.is_promoted = 1 THEN s.sales_revenue ELSE 0 END) AS promo_revenue,
       COUNT(*) AS lines, COUNT(DISTINCT s.date_key) AS days_with_sales,
       SUM(CASE WHEN s.is_on_time = 1 THEN s.sales_revenue ELSE 0 END) AS sales_revenue_ontime,
       COUNT(DISTINCT CASE WHEN s.is_on_time = 1 THEN s.transaction_id END) AS transactions_ontime,
       SUM(CASE WHEN s.is_on_time = 1 THEN 1 ELSE 0 END) AS lines_ontime,
       COUNT(DISTINCT CASE WHEN s.is_on_time = 1 THEN s.date_key END) AS days_with_sales_ontime,
       MAX(s.extract_timestamp) AS last_extract_timestamp,
       SUM(CAST(s.is_late_arriving AS INT)) AS lines_late,
       SUM(CAST(s.is_imputed AS INT)) AS lines_imputed,
       SUM(CASE WHEN s.dq_status IN (N'corrected', N'imputed') THEN 1 ELSE 0 END) AS lines_dq_flagged,
       SUM(CASE WHEN s.product_key = -1 THEN 1 ELSE 0 END) AS lines_unknown_product,
       SUM(CASE WHEN s.promotion_key = -1 THEN 1 ELSE 0 END) AS lines_unknown_promotion
FROM mon.sales_line_week AS s
GROUP BY s.store_key, s.retail_week_key;
GO

-- Store x week: returns side (return-date basis, as the governed Net Revenue counts them).
CREATE OR ALTER VIEW mon.returns_store_week AS
SELECT r.store_key, d.retail_week_key, SUM(r.refund_value) AS returns_value,
       SUM(CAST(r.return_quantity AS INT)) AS returned_units, SUM(r.restock_cost_credit) AS restock_cost_credit,
       SUM(CASE WHEN r.is_linked_to_sale = 0 THEN 1 ELSE 0 END) AS returns_unlinked,
       SUM(CASE WHEN r.dq_status <> N'clean' THEN 1 ELSE 0 END) AS returns_dq_flagged
FROM dw.fact_returns AS r
JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
GROUP BY r.store_key, d.retail_week_key;
GO

-- Store x week KPI components (grain: store x complete retail week).
CREATE OR ALTER VIEW mon.kpi_store_week AS
SELECT c.retail_week_key, st.store_key, st.store_id, st.region, st.store_format,
       COALESCE(s.sales_revenue, 0) AS sales_revenue, COALESCE(s.gross_amount, 0) AS gross_amount,
       COALESCE(s.discount_amount, 0) AS discount_amount, COALESCE(s.cost_amount, 0) AS cost_amount,
       COALESCE(s.units, 0) AS units, COALESCE(s.transactions, 0) AS transactions,
       COALESCE(s.promo_revenue, 0) AS promo_revenue,
       COALESCE(r.returns_value, 0) AS returns_value, COALESCE(r.returned_units, 0) AS returned_units,
       COALESCE(r.restock_cost_credit, 0) AS restock_cost_credit,
       COALESCE(s.sales_revenue_ontime, 0) AS sales_revenue_ontime,
       COALESCE(s.transactions_ontime, 0) AS transactions_ontime,
       COALESCE(s.lines, 0) AS lines, COALESCE(s.lines_ontime, 0) AS lines_ontime,
       COALESCE(s.days_with_sales, 0) AS days_with_sales, COALESCE(s.days_with_sales_ontime, 0) AS days_with_sales_ontime,
       c.trading_days, s.last_extract_timestamp, c.run_time,
       COALESCE(s.lines_late, 0) AS lines_late, COALESCE(s.lines_imputed, 0) AS lines_imputed,
       COALESCE(s.lines_dq_flagged, 0) AS lines_dq_flagged,
       COALESCE(s.lines_unknown_product, 0) AS lines_unknown_product,
       COALESCE(s.lines_unknown_promotion, 0) AS lines_unknown_promotion,
       COALESCE(r.returns_unlinked, 0) AS returns_unlinked, COALESCE(r.returns_dq_flagged, 0) AS returns_dq_flagged
FROM mon.week_calendar AS c
CROSS JOIN dw.dim_store AS st
LEFT JOIN mon.sales_store_week AS s ON s.store_key = st.store_key AND s.retail_week_key = c.retail_week_key
LEFT JOIN mon.returns_store_week AS r ON r.store_key = st.store_key AND r.retail_week_key = c.retail_week_key
WHERE st.is_unknown = 0;
GO

-- Estate category x week: sales, returns (incl. 'Faulty' reason), receipts containing the category.
CREATE OR ALTER VIEW mon.sales_category_week AS
SELECT p.category, s.retail_week_key, SUM(s.sales_revenue) AS sales_revenue, SUM(s.gross_amount) AS gross_amount,
       SUM(s.discount_amount) AS discount_amount, SUM(s.cost_amount) AS cost_amount,
       SUM(CAST(s.quantity AS INT)) AS units, COUNT(DISTINCT s.transaction_id) AS transactions,
       SUM(CASE WHEN s.is_promoted = 1 THEN s.sales_revenue ELSE 0 END) AS promo_revenue,
       SUM(CASE WHEN s.is_promoted = 1 THEN 1 ELSE 0 END) AS promo_lines,
       SUM(CASE WHEN s.is_on_time = 1 THEN s.sales_revenue ELSE 0 END) AS sales_revenue_ontime,
       SUM(CASE WHEN s.is_on_time = 1 THEN s.gross_amount ELSE 0 END) AS gross_amount_ontime,
       SUM(CASE WHEN s.is_on_time = 1 THEN s.discount_amount ELSE 0 END) AS discount_amount_ontime,
       SUM(CASE WHEN s.is_on_time = 1 THEN s.cost_amount ELSE 0 END) AS cost_amount_ontime,
       SUM(CASE WHEN s.is_on_time = 1 THEN CAST(s.quantity AS INT) ELSE 0 END) AS units_ontime,
       COUNT(DISTINCT CASE WHEN s.is_on_time = 1 THEN s.transaction_id END) AS transactions_ontime,
       SUM(CASE WHEN s.is_on_time = 1 AND s.is_promoted = 1 THEN s.sales_revenue ELSE 0 END) AS promo_revenue_ontime,
       SUM(CASE WHEN s.is_on_time = 1 AND s.is_promoted = 1 THEN 1 ELSE 0 END) AS promo_lines_ontime,
       MAX(s.extract_timestamp) AS last_extract_timestamp
FROM mon.sales_line_week AS s
JOIN dw.dim_product AS p ON p.product_key = s.product_key
GROUP BY p.category, s.retail_week_key;
GO

-- Estate category x week returns on return-date basis, with the 'Faulty' reason split out.
CREATE OR ALTER VIEW mon.returns_category_week AS
SELECT p.category, d.retail_week_key, SUM(r.refund_value) AS returns_value,
       SUM(CAST(r.return_quantity AS INT)) AS returned_units, SUM(r.restock_cost_credit) AS restock_cost_credit,
       SUM(CASE WHEN r.return_reason = N'Faulty' THEN CAST(r.return_quantity AS INT) ELSE 0 END) AS faulty_units,
       SUM(CASE WHEN r.return_reason = N'Faulty' THEN r.refund_value ELSE 0 END) AS faulty_value
FROM dw.fact_returns AS r
JOIN dw.dim_product AS p ON p.product_key = r.product_key
JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
GROUP BY p.category, d.retail_week_key;
GO

-- Inventory at product x week (store cells aggregated): ranged, in-stock and full-week stock-out cells.
CREATE OR ALTER VIEW mon.inventory_product_week AS
SELECT i.product_key, i.retail_week_key, COUNT(*) AS ranged_cells, SUM(CAST(i.is_in_stock AS INT)) AS in_stock_cells,
       SUM(CASE WHEN i.opening_stock <= 0 AND i.received_qty <= 0 AND i.is_in_stock = 0 THEN 1 ELSE 0 END)
           AS full_week_stockout_cells,
       SUM(i.closing_stock) AS closing_stock, SUM(i.received_qty) AS received_qty,
       SUM(CASE WHEN i.dq_status <> N'clean' THEN 1 ELSE 0 END) AS cells_dq_flagged
FROM dw.fact_inventory AS i
GROUP BY i.product_key, i.retail_week_key;
GO

-- Category x week KPI components; the calendar cross join keeps zero-sales weeks as explicit rows.
CREATE OR ALTER VIEW mon.kpi_category_week AS
SELECT c.retail_week_key, cat.category,
       COALESCE(s.sales_revenue, 0) AS sales_revenue, COALESCE(s.gross_amount, 0) AS gross_amount,
       COALESCE(s.discount_amount, 0) AS discount_amount, COALESCE(s.cost_amount, 0) AS cost_amount,
       COALESCE(s.units, 0) AS units, COALESCE(s.transactions, 0) AS transactions,
       COALESCE(s.promo_revenue, 0) AS promo_revenue, COALESCE(s.promo_lines, 0) AS promo_lines,
       COALESCE(s.sales_revenue_ontime, 0) AS sales_revenue_ontime, COALESCE(s.gross_amount_ontime, 0) AS gross_amount_ontime,
       COALESCE(s.discount_amount_ontime, 0) AS discount_amount_ontime, COALESCE(s.cost_amount_ontime, 0) AS cost_amount_ontime,
       COALESCE(s.units_ontime, 0) AS units_ontime, COALESCE(s.transactions_ontime, 0) AS transactions_ontime,
       COALESCE(s.promo_revenue_ontime, 0) AS promo_revenue_ontime, COALESCE(s.promo_lines_ontime, 0) AS promo_lines_ontime,
       s.last_extract_timestamp, c.run_time,
       COALESCE(r.returns_value, 0) AS returns_value, COALESCE(r.returned_units, 0) AS returned_units,
       COALESCE(r.restock_cost_credit, 0) AS restock_cost_credit,
       COALESCE(r.faulty_units, 0) AS faulty_units, COALESCE(r.faulty_value, 0) AS faulty_value,
       COALESCE(i.ranged_cells, 0) AS ranged_cells, COALESCE(i.in_stock_cells, 0) AS in_stock_cells,
       COALESCE(i.full_week_stockout_cells, 0) AS full_week_stockout_cells
FROM mon.week_calendar AS c
CROSS JOIN (SELECT DISTINCT category FROM dw.dim_product) AS cat
LEFT JOIN mon.sales_category_week AS s ON s.category = cat.category AND s.retail_week_key = c.retail_week_key
LEFT JOIN mon.returns_category_week AS r ON r.category = cat.category AND r.retail_week_key = c.retail_week_key
LEFT JOIN (SELECT p.category, ip.retail_week_key, SUM(ip.ranged_cells) AS ranged_cells,
                  SUM(ip.in_stock_cells) AS in_stock_cells, SUM(ip.full_week_stockout_cells) AS full_week_stockout_cells
           FROM mon.inventory_product_week AS ip JOIN dw.dim_product AS p ON p.product_key = ip.product_key
           GROUP BY p.category, ip.retail_week_key) AS i
       ON i.category = cat.category AND i.retail_week_key = c.retail_week_key;
GO

-- Product x week: sales and stock (for top-seller stock-out monitoring and supplier roll-ups).
CREATE OR ALTER VIEW mon.kpi_product_week AS
SELECT c.retail_week_key, p.product_key, p.product_id, p.category, p.supplier_name,
       COALESCE(s.sales_revenue, 0) AS sales_revenue, COALESCE(s.units, 0) AS units,
       COALESCE(s.sales_revenue_ontime, 0) AS sales_revenue_ontime, COALESCE(s.units_ontime, 0) AS units_ontime,
       s.last_extract_timestamp, c.run_time,
       COALESCE(i.ranged_cells, 0) AS ranged_cells, COALESCE(i.in_stock_cells, 0) AS in_stock_cells,
       COALESCE(i.full_week_stockout_cells, 0) AS full_week_stockout_cells,
       COALESCE(i.closing_stock, 0) AS closing_stock, COALESCE(i.received_qty, 0) AS received_qty
FROM mon.week_calendar AS c
CROSS JOIN dw.dim_product AS p
LEFT JOIN (SELECT product_key, retail_week_key, SUM(sales_revenue) AS sales_revenue, SUM(CAST(quantity AS INT)) AS units,
                  SUM(CASE WHEN is_on_time = 1 THEN sales_revenue ELSE 0 END) AS sales_revenue_ontime,
                  SUM(CASE WHEN is_on_time = 1 THEN CAST(quantity AS INT) ELSE 0 END) AS units_ontime,
                  MAX(extract_timestamp) AS last_extract_timestamp
           FROM mon.sales_line_week GROUP BY product_key, retail_week_key) AS s
       ON s.product_key = p.product_key AND s.retail_week_key = c.retail_week_key
LEFT JOIN mon.inventory_product_week AS i ON i.product_key = p.product_key AND i.retail_week_key = c.retail_week_key
WHERE p.is_unknown = 0;
GO

-- Store x category x week: units sold and returns by reason (store-level 'Faulty' monitoring).
CREATE OR ALTER VIEW mon.kpi_store_category_week AS
SELECT c.retail_week_key, st.store_id, cat.category,
       COALESCE(s.units, 0) AS units, COALESCE(s.sales_revenue, 0) AS sales_revenue,
       COALESCE(s.units_ontime, 0) AS units_ontime, s.last_extract_timestamp, c.run_time,
       COALESCE(r.returned_units, 0) AS returned_units, COALESCE(r.faulty_units, 0) AS faulty_units,
       COALESCE(r.faulty_value, 0) AS faulty_value
FROM mon.week_calendar AS c
CROSS JOIN dw.dim_store AS st
CROSS JOIN (SELECT DISTINCT category FROM dw.dim_product) AS cat
LEFT JOIN (SELECT sl.store_key, p.category, sl.retail_week_key, SUM(CAST(sl.quantity AS INT)) AS units,
                  SUM(sl.sales_revenue) AS sales_revenue,
                  SUM(CASE WHEN sl.is_on_time = 1 THEN CAST(sl.quantity AS INT) ELSE 0 END) AS units_ontime,
                  MAX(sl.extract_timestamp) AS last_extract_timestamp
           FROM mon.sales_line_week AS sl JOIN dw.dim_product AS p ON p.product_key = sl.product_key
           GROUP BY sl.store_key, p.category, sl.retail_week_key) AS s
       ON s.store_key = st.store_key AND s.category = cat.category AND s.retail_week_key = c.retail_week_key
LEFT JOIN (SELECT r.store_key, p.category, d.retail_week_key, SUM(CAST(r.return_quantity AS INT)) AS returned_units,
                  SUM(CASE WHEN r.return_reason = N'Faulty' THEN CAST(r.return_quantity AS INT) ELSE 0 END) AS faulty_units,
                  SUM(CASE WHEN r.return_reason = N'Faulty' THEN r.refund_value ELSE 0 END) AS faulty_value
           FROM dw.fact_returns AS r JOIN dw.dim_product AS p ON p.product_key = r.product_key
           JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
           GROUP BY r.store_key, p.category, d.retail_week_key) AS r
       ON r.store_key = st.store_key AND r.category = cat.category AND r.retail_week_key = c.retail_week_key
WHERE st.is_unknown = 0;
GO

-- Store x week inventory snapshot coverage (stale or missing snapshots feed the DQ gate).
CREATE OR ALTER VIEW mon.inventory_store_week AS
SELECT c.retail_week_key, st.store_id, COALESCE(i.snapshot_rows, 0) AS snapshot_rows,
       COALESCE(i.cells_dq_flagged, 0) AS inventory_cells_dq_flagged
FROM mon.week_calendar AS c
CROSS JOIN dw.dim_store AS st
LEFT JOIN (SELECT store_key, retail_week_key, COUNT(*) AS snapshot_rows,
                  SUM(CASE WHEN dq_status <> N'clean' THEN 1 ELSE 0 END) AS cells_dq_flagged
           FROM dw.fact_inventory GROUP BY store_key, retail_week_key) AS i
       ON i.store_key = st.store_key AND i.retail_week_key = c.retail_week_key
WHERE st.is_unknown = 0;
GO

-- Product x week returns by reason (context for 'Faulty' alerts: which products and suppliers carry the increase).
CREATE OR ALTER VIEW mon.returns_product_week AS
SELECT p.product_id, p.category, p.supplier_name, d.retail_week_key, st.store_id,
       SUM(CAST(r.return_quantity AS INT)) AS returned_units,
       SUM(CASE WHEN r.return_reason = N'Faulty' THEN CAST(r.return_quantity AS INT) ELSE 0 END) AS faulty_units,
       SUM(CASE WHEN r.return_reason = N'Faulty' THEN r.refund_value ELSE 0 END) AS faulty_value
FROM dw.fact_returns AS r
JOIN dw.dim_product AS p ON p.product_key = r.product_key
JOIN dw.dim_store AS st ON st.store_key = r.store_key
JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
GROUP BY p.product_id, p.category, p.supplier_name, d.retail_week_key, st.store_id;
GO
