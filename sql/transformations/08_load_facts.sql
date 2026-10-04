/* =====================================================================
   08  Load facts from staging
   ---------------------------------------------------------------------
   Source: stg.* only. Quarantined rows are not in the curated files, so
   they cannot reach a fact; every curated row is loaded exactly once
   (proved by the row-count reconciliation in 09).

   Dimension lookups use LEFT JOIN + COALESCE(key, -1): a row whose
   natural key has no dimension member is kept under UNKNOWN rather than
   silently dropped, and the reconciliation counts those rows.
   Business values are loaded as delivered by Phase 3; only derived
   columns (gross_amount, keys, flags) are computed here.
   ===================================================================== */

SET NOCOUNT ON;
TRUNCATE TABLE dw.fact_sales;
TRUNCATE TABLE dw.fact_returns;
TRUNCATE TABLE dw.fact_inventory;
TRUNCATE TABLE dw.fact_targets;
TRUNCATE TABLE dw.fact_promotion_coverage;
GO

/* ---------------------------------------------------------------- fact_sales */
SET NOCOUNT ON;
INSERT INTO dw.fact_sales (sales_line_id, date_key, store_key, product_key, promotion_key, transaction_id, line_number,
                           transaction_time, quantity, unit_price, gross_amount, discount_amount, sales_revenue, unit_cost,
                           cost_amount, margin_amount, is_promoted, is_late_arriving, is_imputed, extract_batch_id,
                           extract_timestamp, extract_lag_days, dq_status, dq_rules, source_file, source_row)
SELECT ROW_NUMBER() OVER (ORDER BY s.transaction_id, s.line_number_i),
       COALESCE(dd.date_key, -1),
       COALESCE(ds.store_key, -1),
       COALESCE(dp.product_key, -1),
       CASE WHEN s.promotion_id IS NULL THEN 0 ELSE COALESCE(pr.promotion_key, -1) END,
       s.transaction_id,
       s.line_number_i,
       TRY_CONVERT(TIME(0), s.transaction_time),
       TRY_CONVERT(SMALLINT, s.quantity),
       TRY_CONVERT(DECIMAL(10,2), s.unit_price),
       CAST(TRY_CONVERT(SMALLINT, s.quantity) * TRY_CONVERT(DECIMAL(10,2), s.unit_price) AS DECIMAL(12,2)),
       TRY_CONVERT(DECIMAL(12,2), s.discount),
       TRY_CONVERT(DECIMAL(12,2), s.revenue),
       TRY_CONVERT(DECIMAL(10,2), s.unit_cost),
       TRY_CONVERT(DECIMAL(12,2), s.cost),
       TRY_CONVERT(DECIMAL(12,2), s.margin),
       CASE WHEN s.promotion_id IS NULL THEN 0 ELSE 1 END,
       CASE WHEN s.is_late_arriving = N'True' THEN 1 ELSE 0 END,
       CASE WHEN s.is_imputed = N'True' THEN 1 ELSE 0 END,
       s.extract_batch_id,
       TRY_CONVERT(DATETIME2(0), s.extract_timestamp),
       TRY_CONVERT(SMALLINT, s.extract_lag_days),
       s.dq_status,
       s.dq_rules,
       s.source_file,
       TRY_CONVERT(INT, s.source_row)
FROM (
    SELECT x.*, TRY_CONVERT(SMALLINT, x.line_number) AS line_number_i,
           TRY_CONVERT(INT, REPLACE(x.transaction_date, N'-', N'')) AS date_key_i
    FROM stg.fact_sales AS x
) AS s
LEFT JOIN dw.dim_date      AS dd ON dd.date_key = s.date_key_i
LEFT JOIN dw.dim_store     AS ds ON ds.store_id = s.store_id
LEFT JOIN dw.dim_product   AS dp ON dp.product_id = s.product_id
LEFT JOIN dw.dim_promotion AS pr ON pr.promotion_id = s.promotion_id;
GO

-- @tsql-only
-- Compress the columnstore delta rowgroups created by the INSERT.
ALTER INDEX cci_fact_sales ON dw.fact_sales REORGANIZE WITH (COMPRESS_ALL_ROW_GROUPS = ON);
GO

/* ---------------------------------------------------------------- fact_returns */
-- restock_cost_credit implements the BRD COGS rule ("cost of returned-to-stock
-- items") exactly as Phase 3 reconciled it: restockable returned units valued
-- at the product's median till unit cost over all its sales lines.
SET NOCOUNT ON;
INSERT INTO dw.fact_returns (return_id, return_date_key, store_key, product_key, original_sale_date_key,
                             original_sale_store_key, original_transaction_id, original_line_number, original_sales_line_id,
                             return_quantity, refund_value, return_reason, is_restockable, restock_cost_credit, has_receipt,
                             is_linked_to_sale, dq_status, dq_rules, source_file, source_row)
SELECT r.return_id,
       COALESCE(dd.date_key, -1),
       COALESCE(ds.store_key, -1),
       COALESCE(dp.product_key, -1),
       COALESCE(fs.date_key, -1),
       COALESCE(fs.store_key, -1),
       r.original_transaction_id,
       r.original_line_number_i,
       fs.sales_line_id,
       TRY_CONVERT(SMALLINT, r.return_quantity),
       TRY_CONVERT(DECIMAL(12,2), r.refund_value),
       r.return_reason,
       CASE WHEN r.restockable_flag = N'True' THEN 1 ELSE 0 END,
       CASE WHEN r.restockable_flag = N'True'
            THEN CAST(TRY_CONVERT(SMALLINT, r.return_quantity) * COALESCE(m.median_unit_cost, 0) AS DECIMAL(14,4))
            ELSE 0 END,
       CASE WHEN r.original_transaction_id IS NULL THEN 0 ELSE 1 END,
       CASE WHEN r.is_linked = N'True' THEN 1 ELSE 0 END,
       r.dq_status,
       r.dq_rules,
       r.source_file,
       TRY_CONVERT(INT, r.source_row)
FROM (
    SELECT x.*, TRY_CONVERT(SMALLINT, x.original_line_number) AS original_line_number_i,
           TRY_CONVERT(INT, REPLACE(x.return_date, N'-', N'')) AS return_date_key_i
    FROM stg.fact_returns AS x
) AS r
LEFT JOIN dw.dim_date    AS dd ON dd.date_key = r.return_date_key_i
LEFT JOIN dw.dim_store   AS ds ON ds.store_id = r.store_id
LEFT JOIN dw.dim_product AS dp ON dp.product_id = r.product_id
LEFT JOIN dw.fact_sales  AS fs ON fs.transaction_id = r.original_transaction_id
                              AND fs.line_number = r.original_line_number_i
LEFT JOIN (
    SELECT q.product_key, MAX(q.median_unit_cost) AS median_unit_cost
    FROM (
        SELECT product_key,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CAST(unit_cost AS FLOAT)) OVER (PARTITION BY product_key) AS median_unit_cost
        FROM dw.fact_sales
    ) AS q
    GROUP BY q.product_key
) AS m ON m.product_key = dp.product_key;
GO

/* ---------------------------------------------------------------- fact_inventory */
SET NOCOUNT ON;
INSERT INTO dw.fact_inventory (snapshot_date_key, retail_week_key, store_key, product_key, opening_stock, received_qty,
                               sold_qty, adjustment_qty, closing_stock, is_in_stock, dq_status, dq_rules, source_file,
                               source_row)
SELECT COALESCE(dd.date_key, -1),
       COALESCE(dd.retail_week_key, -1),
       COALESCE(ds.store_key, -1),
       COALESCE(dp.product_key, -1),
       TRY_CONVERT(INT, i.opening_stock),
       TRY_CONVERT(INT, i.received_qty),
       TRY_CONVERT(INT, i.sold_qty),
       TRY_CONVERT(INT, i.adjustment_qty),
       TRY_CONVERT(INT, i.closing_stock),
       CASE WHEN TRY_CONVERT(INT, i.closing_stock) > 0 THEN 1 ELSE 0 END,
       i.dq_status,
       i.dq_rules,
       i.source_file,
       TRY_CONVERT(INT, i.source_row)
FROM (
    SELECT x.*, TRY_CONVERT(INT, REPLACE(x.snapshot_date, N'-', N'')) AS snapshot_date_key_i
    FROM stg.fact_inventory AS x
) AS i
LEFT JOIN dw.dim_date    AS dd ON dd.date_key = i.snapshot_date_key_i
LEFT JOIN dw.dim_store   AS ds ON ds.store_id = i.store_id
LEFT JOIN dw.dim_product AS dp ON dp.product_id = i.product_id;
GO

-- @tsql-only
ALTER INDEX cci_fact_inventory ON dw.fact_inventory REORGANIZE WITH (COMPRESS_ALL_ROW_GROUPS = ON);
GO

/* ---------------------------------------------------------------- fact_targets */
SET NOCOUNT ON;
INSERT INTO dw.fact_targets (retail_week_key, store_key, target_net_revenue, target_version, target_set_date, source_file,
                             source_row)
SELECT COALESCE(w.retail_week_key, -1),
       COALESCE(ds.store_key, -1),
       TRY_CONVERT(DECIMAL(14,2), t.target_net_revenue),
       t.target_version,
       TRY_CONVERT(DATE, t.target_set_date),
       t.source_file,
       TRY_CONVERT(INT, t.source_row)
FROM (
    SELECT x.*, TRY_CONVERT(INT, x.retail_year) * 100 + TRY_CONVERT(INT, x.retail_week) AS retail_week_key_i
    FROM stg.fact_targets AS x
) AS t
LEFT JOIN dw.dim_retail_week AS w  ON w.retail_week_key = t.retail_week_key_i
LEFT JOIN dw.dim_store       AS ds ON ds.store_id = t.store_id;
GO

/* ---------------------------------------------------------------- fact_promotion_coverage */
SET NOCOUNT ON;
INSERT INTO dw.fact_promotion_coverage (promotion_key, store_key, product_key, start_date, end_date, discount_pct,
                                        source_file, source_row)
SELECT COALESCE(pr.promotion_key, -1),
       COALESCE(ds.store_key, -1),
       COALESCE(dp.product_key, -1),
       TRY_CONVERT(DATE, p.start_date),
       TRY_CONVERT(DATE, p.end_date),
       TRY_CONVERT(DECIMAL(5,4), p.discount_pct),
       p.source_file,
       TRY_CONVERT(INT, p.source_row)
FROM stg.fact_promotions AS p
LEFT JOIN dw.dim_promotion AS pr ON pr.promotion_id = p.promotion_id
LEFT JOIN dw.dim_store     AS ds ON ds.store_id = p.store_id
LEFT JOIN dw.dim_product   AS dp ON dp.product_id = p.product_id;
GO
