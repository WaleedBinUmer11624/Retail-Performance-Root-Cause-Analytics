/* =====================================================================
   10  Governed KPI layer and analytical views (schema mart)
   ---------------------------------------------------------------------
   Rules that keep the KPIs governed (BRD 5, NFR-07):
   * One atomic base, mart.v_performance_store_day, holds every additive
     component at store x day. All period, store, region, format and
     estate KPIs aggregate that base, so they cannot drift apart.
   * Ratios (AOV, UPT, ASP, GM %, return rate, promo share, availability)
     are computed after summing numerators and denominators, never by
     averaging ratios.
   * Transactions are additive across stores and days (a receipt belongs to
     one store on one day) but NOT across products or categories: category
     views expose "transactions_with_category" and no AOV.
   * Returns are counted on the return date at the returning store
     (BRD assumption 2); category views attribute returns to the returned
     product's category.
   * Net Revenue = Sales Revenue - Returns Value; COGS = cost of sales minus
     cost of returned-to-stock units; Gross Margin = Net Revenue - COGS.
   * Precision: component sums are cast to DECIMAL(19,2) (money) and
     DECIMAL(19,4) (restock credit) before any subtraction. Subtracting two
     unbounded SUMs of different scale (38,2) - (38,4) would exceed 38 digits
     and SQL Server would round the result to 2 decimals.

   These views are the analytical foundation. They do not compute drivers
   of the revenue change (that is Phase 7).
   ===================================================================== */

/* ================================================================ base */

-- Additive sales components at store x day
CREATE OR ALTER VIEW mart.v_sales_store_day AS
SELECT f.date_key,
       f.store_key,
       COUNT(*)                                                             AS sales_lines,
       SUM(CAST(f.quantity AS INT))                                         AS units_sold,
       COUNT(DISTINCT f.transaction_id)                                     AS transactions,
       CAST(SUM(f.gross_amount) AS DECIMAL(19,2))                                              AS gross_sales,
       CAST(SUM(f.discount_amount) AS DECIMAL(19,2))                                           AS discount_value,
       CAST(SUM(f.sales_revenue) AS DECIMAL(19,2))                                             AS sales_revenue,
       CAST(SUM(f.cost_amount) AS DECIMAL(19,2))                                               AS cost_of_sales,
       CAST(SUM(CASE WHEN f.is_promoted = 1 THEN f.sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS promo_sales_revenue,
       CAST(SUM(CASE WHEN f.is_promoted = 1 THEN f.discount_amount ELSE 0 END) AS DECIMAL(19,2)) AS promo_discount_value,
       SUM(CASE WHEN f.is_promoted = 1 THEN CAST(f.quantity AS INT) ELSE 0 END)                AS promo_units_sold,
       CAST(SUM(CASE WHEN f.is_late_arriving = 1 THEN f.sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS late_arriving_sales_revenue,
       CAST(SUM(CASE WHEN f.product_key = -1 THEN f.sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS unknown_product_sales_revenue
FROM dw.fact_sales AS f
GROUP BY f.date_key, f.store_key;
GO

-- Additive returns components at returning store x return day
CREATE OR ALTER VIEW mart.v_returns_store_day AS
SELECT r.return_date_key                                   AS date_key,
       r.store_key,
       COUNT(*)                                            AS return_lines,
       SUM(CAST(r.return_quantity AS INT))                 AS returned_units,
       CAST(SUM(r.refund_value) AS DECIMAL(19,2))          AS returns_value,
       CAST(SUM(r.restock_cost_credit) AS DECIMAL(19,4))   AS restock_cost_credit,
       SUM(CAST(r.has_receipt AS INT))                     AS returns_with_receipt,
       SUM(CASE WHEN r.original_sales_line_id IS NULL THEN 0 ELSE 1 END) AS returns_linked_to_sales_line
FROM dw.fact_returns AS r
GROUP BY r.return_date_key, r.store_key;
GO

-- THE governed atomic base: every additive KPI component at store x day
CREATE OR ALTER VIEW mart.v_performance_store_day AS
SELECT COALESCE(s.date_key, r.date_key)                            AS date_key,
       COALESCE(s.store_key, r.store_key)                          AS store_key,
       COALESCE(s.sales_lines, 0)                                  AS sales_lines,
       COALESCE(s.units_sold, 0)                                   AS units_sold,
       COALESCE(s.transactions, 0)                                 AS transactions,
       COALESCE(s.gross_sales, 0)                                  AS gross_sales,
       COALESCE(s.discount_value, 0)                               AS discount_value,
       COALESCE(s.sales_revenue, 0)                                AS sales_revenue,
       COALESCE(r.returns_value, 0)                                AS returns_value,
       COALESCE(s.sales_revenue, 0) - COALESCE(r.returns_value, 0) AS net_revenue,
       COALESCE(s.cost_of_sales, 0)                                AS cost_of_sales,
       COALESCE(r.restock_cost_credit, 0)                          AS restock_cost_credit,
       COALESCE(s.cost_of_sales, 0) - COALESCE(r.restock_cost_credit, 0) AS cogs,
       (COALESCE(s.sales_revenue, 0) - COALESCE(r.returns_value, 0))
         - (COALESCE(s.cost_of_sales, 0) - COALESCE(r.restock_cost_credit, 0)) AS gross_margin,
       COALESCE(s.promo_sales_revenue, 0)                          AS promo_sales_revenue,
       COALESCE(s.promo_discount_value, 0)                         AS promo_discount_value,
       COALESCE(s.promo_units_sold, 0)                             AS promo_units_sold,
       COALESCE(s.late_arriving_sales_revenue, 0)                  AS late_arriving_sales_revenue,
       COALESCE(s.unknown_product_sales_revenue, 0)                AS unknown_product_sales_revenue,
       COALESCE(r.return_lines, 0)                                 AS return_lines,
       COALESCE(r.returned_units, 0)                               AS returned_units
FROM mart.v_sales_store_day AS s
FULL OUTER JOIN mart.v_returns_store_day AS r
       ON r.date_key = s.date_key AND r.store_key = s.store_key;
GO

/* ================================================================ time and store */

-- Store x retail week, with Finance targets (Target vs Actual, BRD 5.4)
CREATE OR ALTER VIEW mart.v_performance_store_week AS
SELECT w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half, w.is_comparable_week,
       st.store_key, st.store_id, st.store_name, st.region, st.store_format,
       a.sales_lines, a.units_sold, a.transactions, a.gross_sales, a.discount_value, a.sales_revenue, a.returns_value,
       a.net_revenue, a.cogs, a.gross_margin, a.promo_sales_revenue, a.late_arriving_sales_revenue,
       t.target_net_revenue,
       a.net_revenue - t.target_net_revenue                                                       AS variance_to_target,
       CAST(a.net_revenue AS FLOAT) / NULLIF(CAST(t.target_net_revenue AS FLOAT), 0)             AS target_achievement_pct,
       CAST(a.sales_revenue AS FLOAT) / NULLIF(CAST(a.transactions AS FLOAT), 0)                 AS aov,
       CAST(a.units_sold AS FLOAT) / NULLIF(CAST(a.transactions AS FLOAT), 0)                    AS upt,
       CAST(a.sales_revenue AS FLOAT) / NULLIF(CAST(a.units_sold AS FLOAT), 0)                   AS asp,
       CAST(a.gross_margin AS FLOAT) / NULLIF(CAST(a.net_revenue AS FLOAT), 0)                   AS gross_margin_pct
FROM (
    SELECT d.retail_week_key, p.store_key,
           SUM(p.sales_lines) AS sales_lines, SUM(p.units_sold) AS units_sold, SUM(p.transactions) AS transactions,
           SUM(p.gross_sales) AS gross_sales, SUM(p.discount_value) AS discount_value,
           SUM(p.sales_revenue) AS sales_revenue, SUM(p.returns_value) AS returns_value,
           SUM(p.net_revenue) AS net_revenue, SUM(p.cogs) AS cogs, SUM(p.gross_margin) AS gross_margin,
           SUM(p.promo_sales_revenue) AS promo_sales_revenue,
           SUM(p.late_arriving_sales_revenue) AS late_arriving_sales_revenue
    FROM mart.v_performance_store_day AS p
    JOIN dw.dim_date AS d ON d.date_key = p.date_key
    GROUP BY d.retail_week_key, p.store_key
) AS a
JOIN dw.dim_retail_week AS w ON w.retail_week_key = a.retail_week_key
JOIN dw.dim_store       AS st ON st.store_key = a.store_key
LEFT JOIN dw.fact_targets AS t ON t.retail_week_key = a.retail_week_key AND t.store_key = a.store_key;
GO

-- Store x retail year x period (H1, H2, FY), with store attributes for region/format roll-ups
CREATE OR ALTER VIEW mart.v_kpi_store_period AS
SELECT b.retail_year, b.period, st.store_key, st.store_id, st.store_name, st.region, st.store_format,
       b.sales_lines, b.units_sold, b.transactions, b.gross_sales, b.discount_value, b.sales_revenue, b.returns_value,
       b.net_revenue, b.cogs, b.gross_margin, b.promo_sales_revenue, b.target_net_revenue,
       CAST(b.sales_revenue AS FLOAT) / NULLIF(CAST(b.transactions AS FLOAT), 0)        AS aov,
       CAST(b.units_sold AS FLOAT) / NULLIF(CAST(b.transactions AS FLOAT), 0)           AS upt,
       CAST(b.sales_revenue AS FLOAT) / NULLIF(CAST(b.units_sold AS FLOAT), 0)          AS asp,
       CAST(b.gross_margin AS FLOAT) / NULLIF(CAST(b.net_revenue AS FLOAT), 0)          AS gross_margin_pct,
       CAST(b.returns_value AS FLOAT) / NULLIF(CAST(b.sales_revenue AS FLOAT), 0)       AS return_rate_value,
       CAST(b.promo_sales_revenue AS FLOAT) / NULLIF(CAST(b.sales_revenue AS FLOAT), 0) AS promo_revenue_share,
       CAST(b.net_revenue AS FLOAT) / NULLIF(CAST(b.target_net_revenue AS FLOAT), 0)    AS target_achievement_pct
FROM (
    SELECT x.retail_year, x.period, x.store_key,
           SUM(x.sales_lines) AS sales_lines, SUM(x.units_sold) AS units_sold, SUM(x.transactions) AS transactions,
           SUM(x.gross_sales) AS gross_sales, SUM(x.discount_value) AS discount_value, SUM(x.sales_revenue) AS sales_revenue,
           SUM(x.returns_value) AS returns_value, SUM(x.net_revenue) AS net_revenue, SUM(x.cogs) AS cogs,
           SUM(x.gross_margin) AS gross_margin, SUM(x.promo_sales_revenue) AS promo_sales_revenue,
           SUM(x.target_net_revenue) AS target_net_revenue
    FROM (
        SELECT w.retail_year, w.retail_half AS period, w.store_key, w.sales_lines, w.units_sold, w.transactions,
               w.gross_sales, w.discount_value, w.sales_revenue, w.returns_value, w.net_revenue, w.cogs, w.gross_margin,
               w.promo_sales_revenue, w.target_net_revenue
        FROM mart.v_performance_store_week AS w
        UNION ALL
        SELECT w.retail_year, N'FY', w.store_key, w.sales_lines, w.units_sold, w.transactions,
               w.gross_sales, w.discount_value, w.sales_revenue, w.returns_value, w.net_revenue, w.cogs, w.gross_margin,
               w.promo_sales_revenue, w.target_net_revenue
        FROM mart.v_performance_store_week AS w
    ) AS x
    GROUP BY x.retail_year, x.period, x.store_key
) AS b
JOIN dw.dim_store AS st ON st.store_key = b.store_key;
GO

-- Segment x retail year x period: Estate, Region, Format, Store in one governed shape
CREATE OR ALTER VIEW mart.v_kpi_segment_period AS
SELECT g.segment_type, g.segment_name, g.retail_year, g.period,
       g.sales_lines, g.units_sold, g.transactions, g.gross_sales, g.discount_value, g.sales_revenue, g.returns_value,
       g.net_revenue, g.cogs, g.gross_margin, g.promo_sales_revenue, g.target_net_revenue,
       CAST(g.sales_revenue AS FLOAT) / NULLIF(CAST(g.transactions AS FLOAT), 0)        AS aov,
       CAST(g.units_sold AS FLOAT) / NULLIF(CAST(g.transactions AS FLOAT), 0)           AS upt,
       CAST(g.sales_revenue AS FLOAT) / NULLIF(CAST(g.units_sold AS FLOAT), 0)          AS asp,
       CAST(g.gross_margin AS FLOAT) / NULLIF(CAST(g.net_revenue AS FLOAT), 0)          AS gross_margin_pct,
       CAST(g.returns_value AS FLOAT) / NULLIF(CAST(g.sales_revenue AS FLOAT), 0)       AS return_rate_value,
       CAST(g.promo_sales_revenue AS FLOAT) / NULLIF(CAST(g.sales_revenue AS FLOAT), 0) AS promo_revenue_share,
       CAST(g.net_revenue AS FLOAT) / NULLIF(CAST(g.target_net_revenue AS FLOAT), 0)    AS target_achievement_pct
FROM (
    SELECT u.segment_type, u.segment_name, u.retail_year, u.period,
           SUM(u.sales_lines) AS sales_lines, SUM(u.units_sold) AS units_sold, SUM(u.transactions) AS transactions,
           SUM(u.gross_sales) AS gross_sales, SUM(u.discount_value) AS discount_value, SUM(u.sales_revenue) AS sales_revenue,
           SUM(u.returns_value) AS returns_value, SUM(u.net_revenue) AS net_revenue, SUM(u.cogs) AS cogs,
           SUM(u.gross_margin) AS gross_margin, SUM(u.promo_sales_revenue) AS promo_sales_revenue,
           SUM(u.target_net_revenue) AS target_net_revenue
    FROM (
        SELECT N'Estate' AS segment_type, N'Brightwater estate' AS segment_name, s.* FROM mart.v_kpi_store_period AS s
        UNION ALL SELECT N'Region', s.region, s.* FROM mart.v_kpi_store_period AS s
        UNION ALL SELECT N'Format', s.store_format, s.* FROM mart.v_kpi_store_period AS s
        UNION ALL SELECT N'Store', CONCAT(s.store_id, N' ', s.store_name), s.* FROM mart.v_kpi_store_period AS s
    ) AS u
    GROUP BY u.segment_type, u.segment_name, u.retail_year, u.period
) AS g;
GO

-- Estate KPIs by retail year and period (the governed headline view)
CREATE OR ALTER VIEW mart.v_kpi_estate_period AS
SELECT k.retail_year, k.period, k.sales_lines, k.units_sold, k.transactions, k.gross_sales, k.discount_value,
       k.sales_revenue, k.returns_value, k.net_revenue, k.cogs, k.gross_margin, k.promo_sales_revenue,
       k.target_net_revenue, k.aov, k.upt, k.asp, k.gross_margin_pct, k.return_rate_value, k.promo_revenue_share,
       k.target_achievement_pct,
       a.inventory_cells, a.in_stock_cells,
       CAST(a.in_stock_cells AS FLOAT) / NULLIF(CAST(a.inventory_cells AS FLOAT), 0) AS stock_availability
FROM mart.v_kpi_segment_period AS k
LEFT JOIN (
    SELECT x.retail_year, x.period, SUM(x.cells) AS inventory_cells, SUM(x.in_stock) AS in_stock_cells
    FROM (
        SELECT w.retail_year, w.retail_half AS period, COUNT(*) AS cells, SUM(CAST(f.is_in_stock AS INT)) AS in_stock
        FROM dw.fact_inventory AS f JOIN dw.dim_retail_week AS w ON w.retail_week_key = f.retail_week_key
        GROUP BY w.retail_year, w.retail_half
        UNION ALL
        SELECT w.retail_year, N'FY', COUNT(*), SUM(CAST(f.is_in_stock AS INT))
        FROM dw.fact_inventory AS f JOIN dw.dim_retail_week AS w ON w.retail_week_key = f.retail_week_key
        GROUP BY w.retail_year
    ) AS x
    GROUP BY x.retail_year, x.period
) AS a ON a.retail_year = k.retail_year AND a.period = k.period
WHERE k.segment_type = N'Estate';
GO

-- YoY growth (BRD 5.2): each segment, year and period against the same period one retail year earlier.
-- Week-aligned by construction (retail weeks), so no day-of-week distortion.
CREATE OR ALTER VIEW mart.v_yoy_segment_period AS
SELECT c.segment_type, c.segment_name, c.retail_year, c.period,
       c.net_revenue      AS net_revenue_cy,     p.net_revenue      AS net_revenue_py,
       c.net_revenue - p.net_revenue                                                        AS net_revenue_change,
       100.0 * (CAST(c.net_revenue AS FLOAT) / NULLIF(CAST(p.net_revenue AS FLOAT), 0) - 1) AS net_revenue_yoy_pct,
       c.sales_revenue    AS sales_revenue_cy,   p.sales_revenue    AS sales_revenue_py,
       100.0 * (CAST(c.sales_revenue AS FLOAT) / NULLIF(CAST(p.sales_revenue AS FLOAT), 0) - 1) AS sales_revenue_yoy_pct,
       c.returns_value    AS returns_value_cy,   p.returns_value    AS returns_value_py,
       c.transactions     AS transactions_cy,    p.transactions     AS transactions_py,
       100.0 * (CAST(c.transactions AS FLOAT) / NULLIF(CAST(p.transactions AS FLOAT), 0) - 1)   AS transactions_yoy_pct,
       c.aov AS aov_cy, p.aov AS aov_py, c.upt AS upt_cy, p.upt AS upt_py, c.asp AS asp_cy, p.asp AS asp_py,
       c.gross_margin     AS gross_margin_cy,    p.gross_margin     AS gross_margin_py,
       c.gross_margin_pct AS gross_margin_pct_cy, p.gross_margin_pct AS gross_margin_pct_py
FROM mart.v_kpi_segment_period AS c
JOIN mart.v_kpi_segment_period AS p
  ON p.segment_type = c.segment_type AND p.segment_name = c.segment_name
 AND p.period = c.period AND p.retail_year = c.retail_year - 1;
GO

-- Week-aligned YoY per store and retail week (time-series comparisons)
CREATE OR ALTER VIEW mart.v_yoy_store_week AS
SELECT c.retail_week_key, c.retail_year, c.retail_week, c.retail_week_label, c.store_key, c.store_id, c.store_name,
       c.region, c.store_format,
       c.net_revenue AS net_revenue_cy, p.net_revenue AS net_revenue_py,
       c.net_revenue - p.net_revenue AS net_revenue_change,
       c.sales_revenue AS sales_revenue_cy, p.sales_revenue AS sales_revenue_py,
       c.transactions AS transactions_cy, p.transactions AS transactions_py,
       c.units_sold AS units_sold_cy, p.units_sold AS units_sold_py,
       c.returns_value AS returns_value_cy, p.returns_value AS returns_value_py
FROM mart.v_performance_store_week AS c
JOIN dw.dim_retail_week AS w ON w.retail_week_key = c.retail_week_key
JOIN mart.v_performance_store_week AS p
  ON p.retail_week_key = w.prior_year_week_key AND p.store_key = c.store_key
WHERE c.is_comparable_week = 1;
GO

/* ================================================================ category and product */

-- Category x retail week. Returns attributed to the returned product's category and return week.
CREATE OR ALTER VIEW mart.v_performance_category_week AS
SELECT w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half, w.is_comparable_week,
       c.category,
       COALESCE(s.sales_lines, 0)                 AS sales_lines,
       COALESCE(s.units_sold, 0)                  AS units_sold,
       COALESCE(s.transactions_with_category, 0)  AS transactions_with_category,  -- not additive across categories
       COALESCE(s.gross_sales, 0)                 AS gross_sales,
       COALESCE(s.discount_value, 0)              AS discount_value,
       COALESCE(s.sales_revenue, 0)               AS sales_revenue,
       COALESCE(r.returns_value, 0)               AS returns_value,
       COALESCE(s.sales_revenue, 0) - COALESCE(r.returns_value, 0) AS net_revenue,
       COALESCE(s.cost_of_sales, 0) - COALESCE(r.restock_cost_credit, 0) AS cogs,
       (COALESCE(s.sales_revenue, 0) - COALESCE(r.returns_value, 0))
         - (COALESCE(s.cost_of_sales, 0) - COALESCE(r.restock_cost_credit, 0)) AS gross_margin,
       COALESCE(s.promo_sales_revenue, 0)         AS promo_sales_revenue,
       COALESCE(r.returned_units, 0)              AS returned_units,
       CAST(COALESCE(s.sales_revenue, 0) AS FLOAT) / NULLIF(CAST(s.units_sold AS FLOAT), 0) AS asp,
       CAST(COALESCE(s.promo_sales_revenue, 0) AS FLOAT) / NULLIF(CAST(s.sales_revenue AS FLOAT), 0) AS promo_revenue_share,
       CAST(COALESCE(r.returns_value, 0) AS FLOAT) / NULLIF(CAST(s.sales_revenue AS FLOAT), 0) AS return_rate_value
FROM (
    SELECT DISTINCT d.retail_week_key, p.category
    FROM dw.dim_date AS d CROSS JOIN dw.dim_product AS p
    WHERE d.date_key <> -1
) AS c
JOIN dw.dim_retail_week AS w ON w.retail_week_key = c.retail_week_key
LEFT JOIN (
    SELECT d.retail_week_key, p.category,
           COUNT(*) AS sales_lines, SUM(CAST(f.quantity AS INT)) AS units_sold,
           COUNT(DISTINCT f.transaction_id) AS transactions_with_category,
           CAST(SUM(f.gross_amount) AS DECIMAL(19,2)) AS gross_sales,
           CAST(SUM(f.discount_amount) AS DECIMAL(19,2)) AS discount_value,
           CAST(SUM(f.sales_revenue) AS DECIMAL(19,2)) AS sales_revenue,
           CAST(SUM(f.cost_amount) AS DECIMAL(19,2)) AS cost_of_sales,
           CAST(SUM(CASE WHEN f.is_promoted = 1 THEN f.sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS promo_sales_revenue
    FROM dw.fact_sales AS f
    JOIN dw.dim_date    AS d ON d.date_key = f.date_key
    JOIN dw.dim_product AS p ON p.product_key = f.product_key
    GROUP BY d.retail_week_key, p.category
) AS s ON s.retail_week_key = c.retail_week_key AND s.category = c.category
LEFT JOIN (
    SELECT d.retail_week_key, p.category, CAST(SUM(r.refund_value) AS DECIMAL(19,2)) AS returns_value,
           CAST(SUM(r.restock_cost_credit) AS DECIMAL(19,4)) AS restock_cost_credit,
           SUM(CAST(r.return_quantity AS INT)) AS returned_units
    FROM dw.fact_returns AS r
    JOIN dw.dim_date    AS d ON d.date_key = r.return_date_key
    JOIN dw.dim_product AS p ON p.product_key = r.product_key
    GROUP BY d.retail_week_key, p.category
) AS r ON r.retail_week_key = c.retail_week_key AND r.category = c.category
WHERE s.sales_lines IS NOT NULL OR r.returns_value IS NOT NULL;
GO

-- Category x retail year x period with YoY (same governed formulas as the segment view)
CREATE OR ALTER VIEW mart.v_kpi_category_period AS
SELECT b.category, b.retail_year, b.period, b.sales_lines, b.units_sold, b.gross_sales, b.discount_value, b.sales_revenue,
       b.returns_value, b.net_revenue, b.cogs, b.gross_margin, b.promo_sales_revenue,
       CAST(b.sales_revenue AS FLOAT) / NULLIF(CAST(b.units_sold AS FLOAT), 0)          AS asp,
       CAST(b.gross_margin AS FLOAT) / NULLIF(CAST(b.net_revenue AS FLOAT), 0)          AS gross_margin_pct,
       CAST(b.returns_value AS FLOAT) / NULLIF(CAST(b.sales_revenue AS FLOAT), 0)       AS return_rate_value,
       CAST(b.promo_sales_revenue AS FLOAT) / NULLIF(CAST(b.sales_revenue AS FLOAT), 0) AS promo_revenue_share,
       p.net_revenue AS net_revenue_py,
       100.0 * (CAST(b.net_revenue AS FLOAT) / NULLIF(CAST(p.net_revenue AS FLOAT), 0) - 1) AS net_revenue_yoy_pct
FROM (
    SELECT x.category, x.retail_year, x.period, SUM(x.sales_lines) AS sales_lines, SUM(x.units_sold) AS units_sold,
           SUM(x.gross_sales) AS gross_sales, SUM(x.discount_value) AS discount_value, SUM(x.sales_revenue) AS sales_revenue,
           SUM(x.returns_value) AS returns_value, SUM(x.net_revenue) AS net_revenue, SUM(x.cogs) AS cogs,
           SUM(x.gross_margin) AS gross_margin, SUM(x.promo_sales_revenue) AS promo_sales_revenue
    FROM (
        SELECT category, retail_year, retail_half AS period, sales_lines, units_sold, gross_sales, discount_value,
               sales_revenue, returns_value, net_revenue, cogs, gross_margin, promo_sales_revenue
        FROM mart.v_performance_category_week
        UNION ALL
        SELECT category, retail_year, N'FY', sales_lines, units_sold, gross_sales, discount_value,
               sales_revenue, returns_value, net_revenue, cogs, gross_margin, promo_sales_revenue
        FROM mart.v_performance_category_week
    ) AS x
    GROUP BY x.category, x.retail_year, x.period
) AS b
LEFT JOIN (
    SELECT category, retail_year, retail_half AS period, SUM(net_revenue) AS net_revenue
    FROM mart.v_performance_category_week GROUP BY category, retail_year, retail_half
    UNION ALL
    SELECT category, retail_year, N'FY', SUM(net_revenue)
    FROM mart.v_performance_category_week GROUP BY category, retail_year
) AS p ON p.category = b.category AND p.period = b.period AND p.retail_year = b.retail_year - 1;
GO

-- Product x store x retail week: sales joined to the stock snapshot (availability vs sales)
CREATE OR ALTER VIEW mart.v_product_store_week AS
SELECT COALESCE(i.retail_week_key, s.retail_week_key) AS retail_week_key,
       COALESCE(i.store_key, s.store_key)             AS store_key,
       COALESCE(i.product_key, s.product_key)         AS product_key,
       CASE WHEN i.product_key IS NULL THEN 0 ELSE 1 END AS is_ranged,
       i.opening_stock, i.received_qty, i.sold_qty AS stock_system_sold_qty, i.adjustment_qty, i.closing_stock,
       i.is_in_stock,
       COALESCE(s.sales_lines, 0)         AS sales_lines,
       COALESCE(s.units_sold, 0)          AS units_sold,
       COALESCE(s.sales_revenue, 0)       AS sales_revenue,
       COALESCE(s.discount_value, 0)      AS discount_value,
       COALESCE(s.promo_units_sold, 0)    AS promo_units_sold
FROM (
    SELECT retail_week_key, store_key, product_key, opening_stock, received_qty, sold_qty, adjustment_qty, closing_stock,
           is_in_stock
    FROM dw.fact_inventory
) AS i
FULL OUTER JOIN (
    SELECT d.retail_week_key, f.store_key, f.product_key, COUNT(*) AS sales_lines,
           SUM(CAST(f.quantity AS INT)) AS units_sold, SUM(f.sales_revenue) AS sales_revenue,
           SUM(f.discount_amount) AS discount_value,
           SUM(CASE WHEN f.is_promoted = 1 THEN CAST(f.quantity AS INT) ELSE 0 END) AS promo_units_sold
    FROM dw.fact_sales AS f JOIN dw.dim_date AS d ON d.date_key = f.date_key
    GROUP BY d.retail_week_key, f.store_key, f.product_key
) AS s ON s.retail_week_key = i.retail_week_key AND s.store_key = i.store_key AND s.product_key = i.product_key;
GO

/* ================================================================ inventory / availability */

-- Stock Availability % (BRD 5.3) by store and retail week
CREATE OR ALTER VIEW mart.v_availability_store_week AS
SELECT w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half,
       st.store_key, st.store_id, st.store_name, st.region, st.store_format,
       COUNT(*)                          AS ranged_cells,
       SUM(CAST(f.is_in_stock AS INT))   AS in_stock_cells,
       CAST(SUM(CAST(f.is_in_stock AS INT)) AS FLOAT) / NULLIF(CAST(COUNT(*) AS FLOAT), 0) AS stock_availability,
       SUM(CAST(f.closing_stock AS BIGINT)) AS closing_stock_units,
       SUM(CAST(f.sold_qty AS BIGINT))      AS stock_system_sold_units
FROM dw.fact_inventory AS f
JOIN dw.dim_retail_week AS w ON w.retail_week_key = f.retail_week_key
JOIN dw.dim_store       AS st ON st.store_key = f.store_key
GROUP BY w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half,
         st.store_key, st.store_id, st.store_name, st.region, st.store_format;
GO

-- Stock Availability % by category, subcategory, supplier and retail week
CREATE OR ALTER VIEW mart.v_availability_category_week AS
SELECT w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half,
       p.category, p.subcategory, p.supplier_id, p.supplier_name,
       COUNT(*)                          AS ranged_cells,
       SUM(CAST(f.is_in_stock AS INT))   AS in_stock_cells,
       CAST(SUM(CAST(f.is_in_stock AS INT)) AS FLOAT) / NULLIF(CAST(COUNT(*) AS FLOAT), 0) AS stock_availability
FROM dw.fact_inventory AS f
JOIN dw.dim_retail_week AS w ON w.retail_week_key = f.retail_week_key
JOIN dw.dim_product     AS p ON p.product_key = f.product_key
GROUP BY w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half,
         p.category, p.subcategory, p.supplier_id, p.supplier_name;
GO

/* ================================================================ promotion */

-- One row per promotion: scope (coverage) and what was sold on it
CREATE OR ALTER VIEW mart.v_promotion_performance AS
SELECT pr.promotion_key, pr.promotion_id, pr.promotion_name, pr.promotion_type, pr.promotion_category, pr.member_type,
       pr.start_date, pr.end_date, pr.duration_days, pr.min_discount_pct, pr.max_discount_pct,
       COALESCE(c.coverage_cells, 0)     AS coverage_cells,
       pr.stores_covered, pr.products_covered,
       COALESCE(s.sales_lines, 0)        AS promoted_sales_lines,
       COALESCE(s.units_sold, 0)         AS promoted_units_sold,
       COALESCE(s.gross_sales, 0)        AS promoted_gross_sales,
       COALESCE(s.discount_value, 0)     AS promo_discount_cost,         -- BRD 5.4 Promo Discount Cost
       COALESCE(s.sales_revenue, 0)      AS promoted_sales_revenue,
       COALESCE(s.cost_of_sales, 0)      AS promoted_cost_of_sales,
       COALESCE(s.sales_revenue, 0) - COALESCE(s.cost_of_sales, 0) AS promoted_line_margin
FROM dw.dim_promotion AS pr
LEFT JOIN (
    SELECT promotion_key, COUNT(*) AS coverage_cells FROM dw.fact_promotion_coverage GROUP BY promotion_key
) AS c ON c.promotion_key = pr.promotion_key
LEFT JOIN (
    SELECT promotion_key, COUNT(*) AS sales_lines, SUM(CAST(quantity AS INT)) AS units_sold, SUM(gross_amount) AS gross_sales,
           SUM(discount_amount) AS discount_value, SUM(sales_revenue) AS sales_revenue, SUM(cost_amount) AS cost_of_sales
    FROM dw.fact_sales GROUP BY promotion_key
) AS s ON s.promotion_key = pr.promotion_key;
GO

/* ================================================================ returns */

-- Returns by return week, returning store, category and reason
CREATE OR ALTER VIEW mart.v_returns_analysis AS
SELECT w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half,
       st.store_key, st.store_id, st.store_name, st.region, st.store_format,
       p.category, p.subcategory,
       r.return_reason, r.is_restockable,
       COUNT(*)                                     AS return_lines,
       SUM(CAST(r.return_quantity AS INT))          AS returned_units,
       SUM(r.refund_value)                          AS returns_value,
       SUM(r.restock_cost_credit)                   AS restock_cost_credit,
       SUM(CAST(r.has_receipt AS INT))              AS returns_with_receipt,
       SUM(CASE WHEN r.original_sales_line_id IS NULL THEN 0 ELSE 1 END) AS returns_linked_to_sales_line,
       SUM(CASE WHEN r.original_sale_store_key NOT IN (-1, r.store_key) THEN 1 ELSE 0 END) AS returned_at_other_store
FROM dw.fact_returns AS r
JOIN dw.dim_date        AS d  ON d.date_key = r.return_date_key
JOIN dw.dim_retail_week AS w  ON w.retail_week_key = d.retail_week_key
JOIN dw.dim_store       AS st ON st.store_key = r.store_key
JOIN dw.dim_product     AS p  ON p.product_key = r.product_key
GROUP BY w.retail_week_key, w.retail_year, w.retail_week, w.retail_week_label, w.retail_half,
         st.store_key, st.store_id, st.store_name, st.region, st.store_format,
         p.category, p.subcategory, r.return_reason, r.is_restockable;
GO

/* ================================================================ line-level drill-through */

CREATE OR ALTER VIEW mart.v_sales_line AS
SELECT f.sales_line_id, f.transaction_id, f.line_number, d.calendar_date AS transaction_date, f.transaction_time,
       d.retail_year, d.retail_week, d.retail_half, d.day_name,
       st.store_id, st.store_name, st.region, st.store_format,
       p.product_id, p.product_name, p.category, p.subcategory, p.brand, p.supplier_name,
       pr.promotion_id, pr.promotion_name, pr.member_type AS promotion_member_type,
       f.quantity, f.unit_price, f.gross_amount, f.discount_amount, f.sales_revenue, f.unit_cost, f.cost_amount,
       f.margin_amount, f.is_promoted, f.is_late_arriving, f.is_imputed, f.dq_status, f.dq_rules,
       f.source_file, f.source_row
FROM dw.fact_sales AS f
JOIN dw.dim_date      AS d  ON d.date_key = f.date_key
JOIN dw.dim_store     AS st ON st.store_key = f.store_key
JOIN dw.dim_product   AS p  ON p.product_key = f.product_key
JOIN dw.dim_promotion AS pr ON pr.promotion_key = f.promotion_key;
GO

/* ================================================================ KPI dictionary */

SET NOCOUNT ON;
DROP TABLE IF EXISTS mart.kpi_definition;
CREATE TABLE mart.kpi_definition (
    kpi_name        NVARCHAR(60)  NOT NULL,
    brd_reference   NVARCHAR(20)  NOT NULL,
    definition      NVARCHAR(300) NOT NULL,
    sql_expression  NVARCHAR(300) NOT NULL,
    governed_view   NVARCHAR(100) NOT NULL,
    additivity      NVARCHAR(120) NOT NULL,
    CONSTRAINT pk_kpi_definition PRIMARY KEY (kpi_name)
);
INSERT INTO mart.kpi_definition (kpi_name, brd_reference, definition, sql_expression, governed_view, additivity) VALUES
(N'Gross Sales',           N'BRD 5.1', N'Sum of quantity x unit price, before discount, excl. VAT', N'SUM(gross_amount)', N'mart.v_performance_store_day', N'Additive'),
(N'Discount Value',        N'BRD 5.1', N'Sum of line discounts', N'SUM(discount_amount)', N'mart.v_performance_store_day', N'Additive'),
(N'Sales Revenue',         N'BRD 5.1', N'Gross Sales - Discount Value (before returns)', N'SUM(sales_revenue)', N'mart.v_performance_store_day', N'Additive'),
(N'Returns Value',         N'BRD 5.1', N'Sum of refund values, on return date at the returning store', N'SUM(refund_value)', N'mart.v_performance_store_day', N'Additive'),
(N'Net Revenue',           N'BRD 5.1', N'Sales Revenue - Returns Value (headline metric)', N'SUM(sales_revenue) - SUM(returns_value)', N'mart.v_performance_store_day', N'Additive'),
(N'COGS',                  N'BRD 5.1', N'Cost of units sold minus cost of returned-to-stock units (median till cost of the product)', N'SUM(cost_amount) - SUM(restock_cost_credit)', N'mart.v_performance_store_day', N'Additive'),
(N'Gross Margin',          N'BRD 5.1', N'Net Revenue - COGS', N'net_revenue - cogs', N'mart.v_performance_store_day', N'Additive'),
(N'Gross Margin %',        N'BRD 5.1', N'Gross Margin / Net Revenue', N'SUM(gross_margin) / SUM(net_revenue)', N'mart.v_kpi_segment_period', N'Ratio: recompute from sums'),
(N'Transactions',          N'BRD 5.1', N'Count of distinct receipts (proxy for customer visits)', N'COUNT(DISTINCT transaction_id)', N'mart.v_performance_store_day', N'Additive across stores and days only'),
(N'Units Sold',            N'BRD 5.1', N'Sum of quantity', N'SUM(quantity)', N'mart.v_performance_store_day', N'Additive'),
(N'Average Order Value',   N'BRD 5.1', N'Sales Revenue / Transactions', N'SUM(sales_revenue) / SUM(transactions)', N'mart.v_kpi_segment_period', N'Ratio: recompute from sums'),
(N'Units per Transaction', N'BRD 5.1', N'Units Sold / Transactions', N'SUM(units_sold) / SUM(transactions)', N'mart.v_kpi_segment_period', N'Ratio: recompute from sums'),
(N'Average Selling Price', N'BRD 5.1', N'Sales Revenue / Units Sold', N'SUM(sales_revenue) / SUM(units_sold)', N'mart.v_kpi_segment_period', N'Ratio: recompute from sums'),
(N'Return Rate % (value)', N'BRD 5.4', N'Returns Value / Sales Revenue', N'SUM(returns_value) / SUM(sales_revenue)', N'mart.v_kpi_segment_period', N'Ratio: recompute from sums'),
(N'Promo Revenue Share %', N'BRD 5.4', N'Sales Revenue on promoted lines (including unknown promotion) / Sales Revenue', N'SUM(promo_sales_revenue) / SUM(sales_revenue)', N'mart.v_kpi_segment_period', N'Ratio: recompute from sums'),
(N'Promo Discount Cost',   N'BRD 5.4', N'Discount Value on promoted lines', N'SUM(promo_discount_value)', N'mart.v_promotion_performance', N'Additive'),
(N'Stock Availability %',  N'BRD 5.3', N'Ranged store-SKU-weeks with closing stock > 0 / all ranged store-SKU-weeks', N'SUM(is_in_stock) / COUNT(*)', N'mart.v_availability_store_week', N'Ratio: recompute from counts'),
(N'Target Revenue',        N'BRD 5.4', N'Finance weekly net revenue target', N'SUM(target_net_revenue)', N'mart.v_performance_store_week', N'Additive'),
(N'Target Achievement %',  N'BRD 5.4', N'Net Revenue / Target Revenue', N'SUM(net_revenue) / SUM(target_net_revenue)', N'mart.v_performance_store_week', N'Ratio: recompute from sums'),
(N'Revenue Variance to Target', N'BRD 5.4', N'Net Revenue - Target Revenue', N'SUM(net_revenue) - SUM(target_net_revenue)', N'mart.v_performance_store_week', N'Additive'),
(N'YoY Growth %',          N'BRD 5.2', N'(Current period / same retail period last year - 1) x 100, week-aligned', N'100 * (cy / py - 1)', N'mart.v_yoy_segment_period', N'Ratio: recompute from sums');
GO
