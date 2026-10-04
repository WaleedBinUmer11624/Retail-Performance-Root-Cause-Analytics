/* =====================================================================
   Phase 5 diagnostics 02: store contribution to the H2 change
   ---------------------------------------------------------------------
   BRD 5.2 definitions:
     Contribution to change (pp) = segment EUR change / estate prior-period net revenue x 100
     Share of decline            = segment EUR change / estate EUR change
   The contribution of all stores adds up exactly to the estate YoY %, which
   is why it, not the store's own YoY %, ranks the drivers: a small store can
   fall 20% and still move the estate less than a flagship falling 5%.

   Target achievement uses only the weeks that have a target, on both sides.
   Availability (BRD 5.3) = in-stock ranged store-SKU-weeks / ranged store-SKU-weeks.
   ===================================================================== */

-- Store x retail year: additive H2 components (one row per store and year)
CREATE OR ALTER VIEW diag.v_store_h2_components AS
SELECT st.store_key, st.store_id, st.store_name, st.region, st.store_format, st.floor_area_m2,
       k.retail_year,
       k.sales_revenue, k.returns_value, k.net_revenue, k.gross_margin, k.transactions, k.units_sold,
       k.promo_sales_revenue, k.discount_value,
       k.target_net_revenue, k.net_revenue_on_target_weeks, k.target_weeks,
       rt.returned_units,
       av.ranged_cells, av.in_stock_cells,
       cv.trading_days, cv.calendar_days
FROM (
    SELECT store_key, retail_year,
           SUM(sales_revenue) AS sales_revenue, SUM(returns_value) AS returns_value, SUM(net_revenue) AS net_revenue,
           SUM(gross_margin) AS gross_margin, SUM(transactions) AS transactions, SUM(units_sold) AS units_sold,
           SUM(promo_sales_revenue) AS promo_sales_revenue, SUM(discount_value) AS discount_value,
           SUM(target_net_revenue) AS target_net_revenue,
           SUM(CASE WHEN target_net_revenue IS NOT NULL THEN net_revenue ELSE 0 END) AS net_revenue_on_target_weeks,
           SUM(CASE WHEN target_net_revenue IS NOT NULL THEN 1 ELSE 0 END) AS target_weeks
    FROM mart.v_performance_store_week
    WHERE retail_half = N'H2' AND retail_week BETWEEN 27 AND 52
    GROUP BY store_key, retail_year
) AS k
JOIN dw.dim_store AS st ON st.store_key = k.store_key
LEFT JOIN (
    SELECT p.store_key, d.retail_year, SUM(p.returned_units) AS returned_units
    FROM mart.v_performance_store_day AS p JOIN dw.dim_date AS d ON d.date_key = p.date_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY p.store_key, d.retail_year
) AS rt ON rt.store_key = k.store_key AND rt.retail_year = k.retail_year
LEFT JOIN (
    SELECT store_key, retail_year, SUM(ranged_cells) AS ranged_cells, SUM(in_stock_cells) AS in_stock_cells
    FROM mart.v_availability_store_week
    WHERE retail_half = N'H2' AND retail_week BETWEEN 27 AND 52
    GROUP BY store_key, retail_year
) AS av ON av.store_key = k.store_key AND av.retail_year = k.retail_year
LEFT JOIN (
    SELECT store_key, retail_year, SUM(trading_days) AS trading_days, SUM(days_in_week) AS calendar_days
    FROM diag.v_store_week_coverage
    WHERE retail_half = N'H2' AND retail_week BETWEEN 27 AND 52
    GROUP BY store_key, retail_year
) AS cv ON cv.store_key = k.store_key AND cv.retail_year = k.retail_year;
GO

-- Estate / Region / Format / Store components in one shape (the roll-ups sum store components)
CREATE OR ALTER VIEW diag.v_segment_h2_components AS
SELECT u.segment_type, u.segment_name, u.retail_year, COUNT(*) AS stores,
       SUM(u.sales_revenue) AS sales_revenue, SUM(u.returns_value) AS returns_value, SUM(u.net_revenue) AS net_revenue,
       SUM(u.gross_margin) AS gross_margin, SUM(u.transactions) AS transactions, SUM(u.units_sold) AS units_sold,
       SUM(u.returned_units) AS returned_units, SUM(u.promo_sales_revenue) AS promo_sales_revenue,
       SUM(u.discount_value) AS discount_value, SUM(u.target_net_revenue) AS target_net_revenue,
       SUM(u.net_revenue_on_target_weeks) AS net_revenue_on_target_weeks, SUM(u.target_weeks) AS target_weeks,
       SUM(u.ranged_cells) AS ranged_cells, SUM(u.in_stock_cells) AS in_stock_cells,
       SUM(u.trading_days) AS trading_days, SUM(u.calendar_days) AS calendar_days
FROM (
    SELECT N'Estate' AS segment_type, N'Brightwater estate' AS segment_name, c.* FROM diag.v_store_h2_components AS c
    UNION ALL SELECT N'Region', c.region, c.* FROM diag.v_store_h2_components AS c
    UNION ALL SELECT N'Format', c.store_format, c.* FROM diag.v_store_h2_components AS c
    UNION ALL SELECT N'Store', c.store_id, c.* FROM diag.v_store_h2_components AS c
) AS u
GROUP BY u.segment_type, u.segment_name, u.retail_year;
GO

-- Current year vs prior year per segment, with contribution, share of decline and driver KPIs
CREATE OR ALTER VIEW diag.v_segment_h2_contribution AS
SELECT x.*,
       100.0 * CAST(x.net_revenue_change AS FLOAT) / NULLIF(SUM(CASE WHEN x.segment_type = N'Estate' THEN CAST(x.net_revenue_py AS FLOAT) END)
             OVER (PARTITION BY x.retail_year), 0)                                         AS contribution_pp,
       CAST(x.net_revenue_change AS FLOAT) / NULLIF(SUM(CASE WHEN x.segment_type = N'Estate' THEN CAST(x.net_revenue_change AS FLOAT) END)
             OVER (PARTITION BY x.retail_year), 0)                                         AS share_of_change
FROM (
    SELECT c.segment_type, c.segment_name, c.retail_year, c.stores,
           p.net_revenue AS net_revenue_py, c.net_revenue AS net_revenue_cy,
           c.net_revenue - p.net_revenue AS net_revenue_change,
           100.0 * (CAST(c.net_revenue AS FLOAT) / NULLIF(CAST(p.net_revenue AS FLOAT), 0) - 1)        AS net_revenue_yoy_pct,
           p.sales_revenue AS sales_revenue_py, c.sales_revenue AS sales_revenue_cy,
           p.returns_value AS returns_value_py, c.returns_value AS returns_value_cy,
           p.gross_margin AS gross_margin_py, c.gross_margin AS gross_margin_cy,
           p.transactions AS transactions_py, c.transactions AS transactions_cy,
           100.0 * (CAST(c.transactions AS FLOAT) / NULLIF(CAST(p.transactions AS FLOAT), 0) - 1)      AS transactions_yoy_pct,
           p.units_sold AS units_sold_py, c.units_sold AS units_sold_cy,
           CAST(p.sales_revenue AS FLOAT) / NULLIF(CAST(p.transactions AS FLOAT), 0)                  AS aov_py,
           CAST(c.sales_revenue AS FLOAT) / NULLIF(CAST(c.transactions AS FLOAT), 0)                  AS aov_cy,
           CAST(p.units_sold AS FLOAT) / NULLIF(CAST(p.transactions AS FLOAT), 0)                     AS upt_py,
           CAST(c.units_sold AS FLOAT) / NULLIF(CAST(c.transactions AS FLOAT), 0)                     AS upt_cy,
           CAST(p.sales_revenue AS FLOAT) / NULLIF(CAST(p.units_sold AS FLOAT), 0)                    AS asp_py,
           CAST(c.sales_revenue AS FLOAT) / NULLIF(CAST(c.units_sold AS FLOAT), 0)                    AS asp_cy,
           CAST(p.returns_value AS FLOAT) / NULLIF(CAST(p.sales_revenue AS FLOAT), 0)                 AS return_rate_value_py,
           CAST(c.returns_value AS FLOAT) / NULLIF(CAST(c.sales_revenue AS FLOAT), 0)                 AS return_rate_value_cy,
           p.returned_units AS returned_units_py, c.returned_units AS returned_units_cy,
           CAST(p.in_stock_cells AS FLOAT) / NULLIF(CAST(p.ranged_cells AS FLOAT), 0)                 AS availability_py,
           CAST(c.in_stock_cells AS FLOAT) / NULLIF(CAST(c.ranged_cells AS FLOAT), 0)                 AS availability_cy,
           p.ranged_cells AS ranged_cells_py, c.ranged_cells AS ranged_cells_cy,
           p.in_stock_cells AS in_stock_cells_py, c.in_stock_cells AS in_stock_cells_cy,
           CAST(p.promo_sales_revenue AS FLOAT) / NULLIF(CAST(p.sales_revenue AS FLOAT), 0)           AS promo_revenue_share_py,
           CAST(c.promo_sales_revenue AS FLOAT) / NULLIF(CAST(c.sales_revenue AS FLOAT), 0)           AS promo_revenue_share_cy,
           p.target_net_revenue AS target_net_revenue_py, c.target_net_revenue AS target_net_revenue_cy,
           CAST(p.net_revenue_on_target_weeks AS FLOAT) / NULLIF(CAST(p.target_net_revenue AS FLOAT), 0) AS target_achievement_py,
           CAST(c.net_revenue_on_target_weeks AS FLOAT) / NULLIF(CAST(c.target_net_revenue AS FLOAT), 0) AS target_achievement_cy,
           p.target_weeks AS target_weeks_py, c.target_weeks AS target_weeks_cy,
           p.trading_days AS trading_days_py, c.trading_days AS trading_days_cy,
           p.calendar_days AS calendar_days_py, c.calendar_days AS calendar_days_cy
    FROM diag.v_segment_h2_components AS c
    JOIN diag.v_segment_h2_components AS p
      ON p.segment_type = c.segment_type AND p.segment_name = c.segment_name AND p.retail_year = c.retail_year - 1
) AS x;
GO

-- Store view of the contribution, ranked by EUR contribution (most negative first; ties broken by store id)
CREATE OR ALTER VIEW diag.v_store_h2_contribution AS
SELECT s.store_key, s.store_name, s.floor_area_m2, c.*,
       ROW_NUMBER() OVER (PARTITION BY c.retail_year ORDER BY c.net_revenue_change ASC, c.segment_name ASC) AS contribution_rank,
       ROW_NUMBER() OVER (PARTITION BY c.retail_year ORDER BY c.net_revenue_yoy_pct ASC, c.segment_name ASC) AS yoy_pct_rank
FROM diag.v_segment_h2_contribution AS c
JOIN dw.dim_store AS s ON s.store_id = c.segment_name
WHERE c.segment_type = N'Store';
GO
