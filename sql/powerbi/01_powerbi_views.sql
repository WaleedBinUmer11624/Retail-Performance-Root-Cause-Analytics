/* =====================================================================
   Phase 7 Power BI source layer (schema pbi)
   ---------------------------------------------------------------------
   One view per table of the Power BI semantic model. The views read only
   the Phase 4 dw star schema; they add no business rule of their own
   beyond three documented conveniences:
     * transaction_key: an integer surrogate of the receipt id, so the
       Transactions measure is a DISTINCTCOUNT over integers (smaller and
       faster in VertiPaq than text). Same count, by construction.
     * period_label / period_sort / retail_week_label: display labels and their sort order.
     * is_full_week_stockout: the Phase 5/6 definition of a full-week
       stock-out (no opening stock, nothing received, out of stock at the
       weekly snapshot), so DAX does not re-implement it.
   All KPI arithmetic (Net Revenue, COGS, Gross Margin, ratios) is done by
   the DAX measure layer from these additive columns, exactly as the
   governed mart.v_performance_store_day defines it (docs/04, BRD 5).
   Power BI imports these views (Import mode). Nothing here is filtered:
   unknown members (key -1) are kept so totals reconcile to Phase 4.
   ===================================================================== */

-- @tsql-only
IF SCHEMA_ID(N'pbi') IS NULL EXEC(N'CREATE SCHEMA pbi');
GO

-- Calendar (day grain) with retail-week and retail-half attributes; the same-day-last-year key drives PY measures
CREATE OR ALTER VIEW pbi.dim_date AS
SELECT d.date_key, d.calendar_date, d.day_of_week, d.day_name, d.is_weekend, d.calendar_month, d.month_name,
       d.year_month, d.calendar_year, d.retail_year, d.retail_week, d.retail_week_key,
       w.retail_week_label, d.retail_week_start, d.retail_half,
       CASE WHEN d.retail_half IS NULL THEN N'Unknown'
            ELSE CONCAT(d.retail_half, N' ', CAST(d.retail_year AS NVARCHAR(4))) END AS period_label,
       CASE WHEN d.retail_half IS NULL THEN 0
            ELSE d.retail_year * 10 + CASE WHEN d.retail_half = N'H1' THEN 1 ELSE 2 END END AS period_sort,
       d.is_bank_holiday, d.is_trading_day, d.same_day_last_year_key, d.is_unknown
FROM dw.dim_date AS d
LEFT JOIN dw.dim_retail_week AS w ON w.retail_week_key = d.retail_week_key;
GO

CREATE OR ALTER VIEW pbi.dim_store AS
SELECT s.store_key, s.store_id, s.store_name, CONCAT(s.store_id, N' ', s.store_name) AS store_label,
       s.town, s.county, s.region, s.store_format, s.floor_area_m2, s.open_date, s.weekly_trading_hours, s.is_unknown
FROM dw.dim_store AS s;
GO

CREATE OR ALTER VIEW pbi.dim_product AS
SELECT p.product_key, p.product_id, p.product_name, CONCAT(p.product_id, N' ', p.product_name) AS product_label,
       p.category, p.subcategory, p.brand, p.supplier_id, p.supplier_name, p.list_price, p.product_status, p.is_unknown
FROM dw.dim_product AS p;
GO

CREATE OR ALTER VIEW pbi.dim_promotion AS
SELECT pr.promotion_key, pr.promotion_id, pr.promotion_name, pr.promotion_type, pr.promotion_category,
       pr.start_date, pr.end_date, pr.duration_days, pr.min_discount_pct, pr.max_discount_pct, pr.member_type,
       pr.is_unknown
FROM dw.dim_promotion AS pr;
GO

-- Sales lines (grain: receipt line). Additive money columns only; ratios live in DAX.
CREATE OR ALTER VIEW pbi.fact_sales AS
SELECT f.sales_line_id, f.date_key, f.store_key, f.product_key, f.promotion_key,
       DENSE_RANK() OVER (ORDER BY f.transaction_id) AS transaction_key,
       CAST(f.quantity AS INT) AS quantity, f.gross_amount, f.discount_amount, f.sales_revenue, f.cost_amount,
       CAST(f.is_promoted AS INT) AS is_promoted
FROM dw.fact_sales AS f;
GO

-- Return lines (grain: return line), counted on the return date at the returning store (BRD assumption 2).
-- original_sale_date_key supports the inactive cohort relationship; sale_was_promoted comes from the linked sale line.
CREATE OR ALTER VIEW pbi.fact_returns AS
SELECT r.return_id, r.return_date_key, r.store_key, r.product_key, r.original_sale_date_key,
       CAST(r.return_quantity AS INT) AS return_quantity, r.refund_value, r.restock_cost_credit, r.return_reason,
       CAST(r.is_restockable AS INT) AS is_restockable, CAST(r.is_linked_to_sale AS INT) AS is_linked_to_sale,
       CASE WHEN s.sales_line_id IS NULL THEN N'Unknown'
            WHEN s.is_promoted = 1 THEN N'Promoted sale' ELSE N'Full-price sale' END AS sale_promotion_status
FROM dw.fact_returns AS r
LEFT JOIN dw.fact_sales AS s ON s.sales_line_id = r.original_sales_line_id;
GO

-- Weekly stock snapshot (grain: store x product x retail week). Semi-additive: never sum stock across weeks.
CREATE OR ALTER VIEW pbi.fact_inventory AS
SELECT i.snapshot_date_key, i.retail_week_key, i.store_key, i.product_key, i.opening_stock, i.received_qty,
       i.closing_stock, CAST(i.is_in_stock AS INT) AS is_in_stock,
       CASE WHEN i.opening_stock <= 0 AND i.received_qty <= 0 AND i.is_in_stock = 0 THEN 1 ELSE 0 END
           AS is_full_week_stockout
FROM dw.fact_inventory AS i;
GO

-- Finance targets (grain: store x retail week). Not related to the day-grain calendar; DAX maps weeks.
CREATE OR ALTER VIEW pbi.fact_targets AS
SELECT t.retail_week_key, t.store_key, t.target_net_revenue
FROM dw.fact_targets AS t;
GO
