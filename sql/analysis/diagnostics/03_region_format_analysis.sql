/* =====================================================================
   Phase 5 diagnostics 03: region and format roll-ups
   ---------------------------------------------------------------------
   Region and format contributions come from diag.v_segment_h2_contribution
   (script 02), which sums the same store components, so region, format and
   store contributions all add up to the same estate change.

   This script adds what a roll-up alone hides:
     * how many stores in each region / format declined, and the spread
       between the best and worst store (is the region's change broad-based
       or driven by one store?)
     * the region x format matrix (is a "regional" pattern really a format mix effect?)
   ===================================================================== */

-- Breadth of the change inside each region and format
CREATE OR ALTER VIEW diag.v_segment_h2_breadth AS
SELECT g.segment_type, g.segment_name, s.retail_year,
       COUNT(*)                                                   AS stores,
       SUM(CASE WHEN s.net_revenue_change < 0 THEN 1 ELSE 0 END)  AS stores_declining,
       MIN(s.net_revenue_yoy_pct)                                 AS worst_store_yoy_pct,
       MAX(s.net_revenue_yoy_pct)                                 AS best_store_yoy_pct,
       MIN(s.net_revenue_change)                                  AS worst_store_change,
       MAX(s.net_revenue_change)                                  AS best_store_change
FROM (
    SELECT N'Region' AS segment_type, st.region AS segment_name, st.store_id FROM dw.dim_store AS st WHERE st.store_key > 0
    UNION ALL
    SELECT N'Format', st.store_format, st.store_id FROM dw.dim_store AS st WHERE st.store_key > 0
) AS g
JOIN diag.v_segment_h2_contribution AS s ON s.segment_type = N'Store' AND s.segment_name = g.store_id
GROUP BY g.segment_type, g.segment_name, s.retail_year;
GO

-- Region x format matrix of the H2 change
CREATE OR ALTER VIEW diag.v_region_format_h2 AS
SELECT c.retail_year, c.region, c.store_format, COUNT(*) AS stores,
       SUM(p.net_revenue) AS net_revenue_py, SUM(c.net_revenue) AS net_revenue_cy,
       SUM(c.net_revenue) - SUM(p.net_revenue) AS net_revenue_change,
       100.0 * (CAST(SUM(c.net_revenue) AS FLOAT) / NULLIF(CAST(SUM(p.net_revenue) AS FLOAT), 0) - 1) AS net_revenue_yoy_pct
FROM diag.v_store_h2_components AS c
JOIN diag.v_store_h2_components AS p ON p.store_key = c.store_key AND p.retail_year = c.retail_year - 1
GROUP BY c.retail_year, c.region, c.store_format;
GO
