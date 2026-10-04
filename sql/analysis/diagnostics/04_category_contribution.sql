/* =====================================================================
   Phase 5 diagnostics 04: category and product contribution
   ---------------------------------------------------------------------
   * Category components come from the governed category view
     mart.v_performance_category_week (returns attributed to the returned
     product's category on the return date, as in Phase 4).
   * transactions_with_category counts receipts containing the category.
     It is NOT additive across categories (one receipt can hold several),
     so category "transactions" are expressed as incidence: the share of
     all estate receipts that contain the category.
   * Product components feed the drill-down, which the Python layer only
     opens for categories that carry a material share of the decline.
   ===================================================================== */

-- Category x retail year: H2 components, availability and estate receipts (for incidence)
CREATE OR ALTER VIEW diag.v_category_h2_components AS
SELECT k.category, k.retail_year,
       k.sales_revenue, k.returns_value, k.net_revenue, k.cogs, k.gross_margin, k.units_sold,
       k.transactions_with_category, k.returned_units, k.promo_sales_revenue, k.discount_value, k.gross_sales,
       av.ranged_cells, av.in_stock_cells,
       e.transactions AS estate_transactions
FROM (
    SELECT category, retail_year,
           SUM(sales_revenue) AS sales_revenue, SUM(returns_value) AS returns_value, SUM(net_revenue) AS net_revenue,
           SUM(cogs) AS cogs, SUM(gross_margin) AS gross_margin, SUM(units_sold) AS units_sold,
           SUM(transactions_with_category) AS transactions_with_category, SUM(returned_units) AS returned_units,
           SUM(promo_sales_revenue) AS promo_sales_revenue, SUM(discount_value) AS discount_value,
           SUM(gross_sales) AS gross_sales
    FROM mart.v_performance_category_week
    WHERE retail_half = N'H2' AND retail_week BETWEEN 27 AND 52
    GROUP BY category, retail_year
) AS k
LEFT JOIN (
    SELECT category, retail_year, SUM(ranged_cells) AS ranged_cells, SUM(in_stock_cells) AS in_stock_cells
    FROM mart.v_availability_category_week
    WHERE retail_half = N'H2' AND retail_week BETWEEN 27 AND 52
    GROUP BY category, retail_year
) AS av ON av.category = k.category AND av.retail_year = k.retail_year
JOIN (
    SELECT retail_year, SUM(transactions) AS transactions
    FROM diag.v_estate_week WHERE retail_half = N'H2' AND retail_week BETWEEN 27 AND 52
    GROUP BY retail_year
) AS e ON e.retail_year = k.retail_year;
GO

-- Category current vs prior year with contribution to the estate net revenue change
CREATE OR ALTER VIEW diag.v_category_h2_contribution AS
SELECT x.*,
       100.0 * CAST(x.net_revenue_change AS FLOAT) / NULLIF(SUM(CAST(x.net_revenue_py AS FLOAT)) OVER (PARTITION BY x.retail_year), 0) AS contribution_pp,
       CAST(x.net_revenue_change AS FLOAT) / NULLIF(SUM(CAST(x.net_revenue_change AS FLOAT)) OVER (PARTITION BY x.retail_year), 0)      AS share_of_change,
       ROW_NUMBER() OVER (PARTITION BY x.retail_year ORDER BY x.net_revenue_change ASC, x.category ASC)                                 AS contribution_rank
FROM (
    SELECT c.category, c.retail_year,
           p.net_revenue AS net_revenue_py, c.net_revenue AS net_revenue_cy, c.net_revenue - p.net_revenue AS net_revenue_change,
           100.0 * (CAST(c.net_revenue AS FLOAT) / NULLIF(CAST(p.net_revenue AS FLOAT), 0) - 1)                  AS net_revenue_yoy_pct,
           p.sales_revenue AS sales_revenue_py, c.sales_revenue AS sales_revenue_cy,
           p.returns_value AS returns_value_py, c.returns_value AS returns_value_cy,
           p.gross_margin AS gross_margin_py, c.gross_margin AS gross_margin_cy,
           CAST(p.gross_margin AS FLOAT) / NULLIF(CAST(p.net_revenue AS FLOAT), 0)                               AS gross_margin_pct_py,
           CAST(c.gross_margin AS FLOAT) / NULLIF(CAST(c.net_revenue AS FLOAT), 0)                               AS gross_margin_pct_cy,
           p.units_sold AS units_sold_py, c.units_sold AS units_sold_cy,
           p.transactions_with_category AS transactions_with_category_py, c.transactions_with_category AS transactions_with_category_cy,
           CAST(p.transactions_with_category AS FLOAT) / NULLIF(CAST(p.estate_transactions AS FLOAT), 0)        AS incidence_py,
           CAST(c.transactions_with_category AS FLOAT) / NULLIF(CAST(c.estate_transactions AS FLOAT), 0)        AS incidence_cy,
           CAST(p.sales_revenue AS FLOAT) / NULLIF(CAST(p.units_sold AS FLOAT), 0)                               AS asp_py,
           CAST(c.sales_revenue AS FLOAT) / NULLIF(CAST(c.units_sold AS FLOAT), 0)                               AS asp_cy,
           CAST(p.returns_value AS FLOAT) / NULLIF(CAST(p.sales_revenue AS FLOAT), 0)                            AS return_rate_value_py,
           CAST(c.returns_value AS FLOAT) / NULLIF(CAST(c.sales_revenue AS FLOAT), 0)                            AS return_rate_value_cy,
           p.returned_units AS returned_units_py, c.returned_units AS returned_units_cy,
           CAST(p.in_stock_cells AS FLOAT) / NULLIF(CAST(p.ranged_cells AS FLOAT), 0)                            AS availability_py,
           CAST(c.in_stock_cells AS FLOAT) / NULLIF(CAST(c.ranged_cells AS FLOAT), 0)                            AS availability_cy,
           CAST(p.promo_sales_revenue AS FLOAT) / NULLIF(CAST(p.sales_revenue AS FLOAT), 0)                      AS promo_revenue_share_py,
           CAST(c.promo_sales_revenue AS FLOAT) / NULLIF(CAST(c.sales_revenue AS FLOAT), 0)                      AS promo_revenue_share_cy,
           p.discount_value AS discount_value_py, c.discount_value AS discount_value_cy,
           p.estate_transactions AS estate_transactions_py, c.estate_transactions AS estate_transactions_cy
    FROM diag.v_category_h2_components AS c
    JOIN diag.v_category_h2_components AS p ON p.category = c.category AND p.retail_year = c.retail_year - 1
) AS x;
GO

-- Product x retail year: H2 sales, returns and stock components (drill-down input)
CREATE OR ALTER VIEW diag.v_product_h2_components AS
SELECT u.product_key, pr.product_id, pr.product_name, pr.category, pr.subcategory, pr.supplier_name, pr.list_price,
       u.retail_year,
       SUM(u.sales_revenue) AS sales_revenue, SUM(u.units_sold) AS units_sold, SUM(u.cost_of_sales) AS cost_of_sales,
       SUM(u.promo_sales_revenue) AS promo_sales_revenue, SUM(u.promo_units_sold) AS promo_units_sold,
       SUM(u.discount_value) AS discount_value, SUM(u.transactions) AS transactions,
       SUM(u.returns_value) AS returns_value, SUM(u.returned_units) AS returned_units,
       SUM(u.ranged_cells) AS ranged_cells, SUM(u.in_stock_cells) AS in_stock_cells, SUM(u.stores_ranged) AS stores_ranged
FROM (
    SELECT f.product_key, d.retail_year,
           CAST(SUM(f.sales_revenue) AS DECIMAL(19,2)) AS sales_revenue, SUM(CAST(f.quantity AS INT)) AS units_sold,
           CAST(SUM(f.cost_amount) AS DECIMAL(19,2)) AS cost_of_sales,
           CAST(SUM(CASE WHEN f.is_promoted = 1 THEN f.sales_revenue ELSE 0 END) AS DECIMAL(19,2)) AS promo_sales_revenue,
           SUM(CASE WHEN f.is_promoted = 1 THEN CAST(f.quantity AS INT) ELSE 0 END) AS promo_units_sold,
           CAST(SUM(f.discount_amount) AS DECIMAL(19,2)) AS discount_value,
           COUNT(DISTINCT f.transaction_id) AS transactions,
           CAST(0 AS DECIMAL(19,2)) AS returns_value, 0 AS returned_units, 0 AS ranged_cells, 0 AS in_stock_cells, 0 AS stores_ranged
    FROM dw.fact_sales AS f JOIN dw.dim_date AS d ON d.date_key = f.date_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY f.product_key, d.retail_year
    UNION ALL
    SELECT r.product_key, d.retail_year, 0, 0, 0, 0, 0, 0, 0,
           CAST(SUM(r.refund_value) AS DECIMAL(19,2)), SUM(CAST(r.return_quantity AS INT)), 0, 0, 0
    FROM dw.fact_returns AS r JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY r.product_key, d.retail_year
    UNION ALL
    SELECT i.product_key, w.retail_year, 0, 0, 0, 0, 0, 0, 0, 0, 0,
           COUNT(*), SUM(CAST(i.is_in_stock AS INT)), COUNT(DISTINCT i.store_key)
    FROM dw.fact_inventory AS i JOIN dw.dim_retail_week AS w ON w.retail_week_key = i.retail_week_key
    WHERE w.retail_week BETWEEN 27 AND 52
    GROUP BY i.product_key, w.retail_year
) AS u
JOIN dw.dim_product AS pr ON pr.product_key = u.product_key
GROUP BY u.product_key, pr.product_id, pr.product_name, pr.category, pr.subcategory, pr.supplier_name, pr.list_price,
         u.retail_year;
GO
