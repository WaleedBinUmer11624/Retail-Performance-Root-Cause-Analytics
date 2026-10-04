/* =====================================================================
   Phase 5 diagnostics 06: returns
   ---------------------------------------------------------------------
   BRD 5.4: Return Rate % (value) = Returns Value / Sales Revenue
            Return Rate % (units) = Returned units / Units sold
   Returns are counted on the return date at the returning store (BRD
   assumption 2) and attributed to the returned product's category.
   A store x category rate therefore compares that store's refunds in the
   category with that store's own category sales in the same weeks.

   return_reason is the reason recorded at the till. It is a stated reason,
   not a verified cause, and the analysis reports it as such.
   ===================================================================== */

-- Store x category x retail year (H2): returns and the sales they are rated against
CREATE OR ALTER VIEW diag.v_returns_h2_store_category AS
SELECT u.store_key, st.store_id, st.store_name, st.region, st.store_format, u.category, u.retail_year,
       SUM(u.sales_revenue) AS sales_revenue, SUM(u.units_sold) AS units_sold,
       SUM(u.returns_value) AS returns_value, SUM(u.returned_units) AS returned_units, SUM(u.return_lines) AS return_lines
FROM (
    SELECT f.store_key, p.category, d.retail_year,
           CAST(SUM(f.sales_revenue) AS DECIMAL(19,2)) AS sales_revenue, SUM(CAST(f.quantity AS INT)) AS units_sold,
           CAST(0 AS DECIMAL(19,2)) AS returns_value, 0 AS returned_units, 0 AS return_lines
    FROM dw.fact_sales AS f
    JOIN dw.dim_date AS d ON d.date_key = f.date_key
    JOIN dw.dim_product AS p ON p.product_key = f.product_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY f.store_key, p.category, d.retail_year
    UNION ALL
    SELECT r.store_key, p.category, d.retail_year, 0, 0,
           CAST(SUM(r.refund_value) AS DECIMAL(19,2)), SUM(CAST(r.return_quantity AS INT)), COUNT(*)
    FROM dw.fact_returns AS r
    JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
    JOIN dw.dim_product AS p ON p.product_key = r.product_key
    WHERE d.retail_week BETWEEN 27 AND 52
    GROUP BY r.store_key, p.category, d.retail_year
) AS u
JOIN dw.dim_store AS st ON st.store_key = u.store_key
GROUP BY u.store_key, st.store_id, st.store_name, st.region, st.store_format, u.category, u.retail_year;
GO

-- Recorded return reason x category x retail year (H2)
CREATE OR ALTER VIEW diag.v_returns_h2_reason AS
SELECT d.retail_year, p.category, r.return_reason,
       COUNT(*) AS return_lines, SUM(CAST(r.return_quantity AS INT)) AS returned_units,
       CAST(SUM(r.refund_value) AS DECIMAL(19,2)) AS returns_value
FROM dw.fact_returns AS r
JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
JOIN dw.dim_product AS p ON p.product_key = r.product_key
WHERE d.retail_week BETWEEN 27 AND 52
GROUP BY d.retail_year, p.category, r.return_reason;
GO

-- Return attributes per retail year (H2): receipts, links to the sale, restocking, days from sale to return
CREATE OR ALTER VIEW diag.v_returns_h2_attributes AS
SELECT d.retail_year,
       COUNT(*)                                                            AS return_lines,
       CAST(SUM(r.refund_value) AS DECIMAL(19,2))                          AS returns_value,
       SUM(CAST(r.has_receipt AS INT))                                     AS with_receipt,
       SUM(CASE WHEN r.original_sales_line_id IS NULL THEN 0 ELSE 1 END)   AS linked_to_sale,
       SUM(CAST(r.is_restockable AS INT))                                  AS restockable,
       SUM(CASE WHEN r.original_sale_store_key NOT IN (-1, r.store_key) THEN 1 ELSE 0 END) AS returned_at_other_store,
       AVG(CASE WHEN od.calendar_date IS NULL THEN NULL
                ELSE CAST(DATEDIFF(day, od.calendar_date, d.calendar_date) AS FLOAT) END) AS avg_days_sale_to_return
FROM dw.fact_returns AS r
JOIN dw.dim_date AS d ON d.date_key = r.return_date_key
LEFT JOIN dw.dim_date AS od ON od.date_key = r.original_sale_date_key AND od.date_key <> -1
WHERE d.retail_week BETWEEN 27 AND 52
GROUP BY d.retail_year;
GO
