/* =====================================================================
   04  Fact tables
   ---------------------------------------------------------------------
   Grain of every fact is stated above its table. Money is DECIMAL (exact),
   never FLOAT. Primary keys, foreign keys and indexes are added in 05 and
   06 so each concern lives in one script.

   Traceability: every fact row keeps the curated natural key (degenerate
   dimension columns) plus source_file / source_row, which point to the
   exact line in the raw extract (Phase 3 lineage). dq_status / dq_rules
   carry the Phase 3 data-quality history of the row.
   ===================================================================== */

SET NOCOUNT ON;
DROP TABLE IF EXISTS dw.fact_sales;
DROP TABLE IF EXISTS dw.fact_returns;
DROP TABLE IF EXISTS dw.fact_inventory;
DROP TABLE IF EXISTS dw.fact_targets;
DROP TABLE IF EXISTS dw.fact_promotion_coverage;
GO

-- GRAIN: one row per POS receipt line (transaction_id, line_number).
-- Transaction-level facts (visits) are derived with COUNT(DISTINCT transaction_id).
CREATE TABLE dw.fact_sales (
    sales_line_id            BIGINT        NOT NULL,   -- compact row id, used by fact_returns
    date_key                 INT           NOT NULL,
    store_key                INT           NOT NULL,
    product_key              INT           NOT NULL,
    promotion_key            INT           NOT NULL,   -- 0 = not promoted, -1 = unknown promotion
    transaction_id           NVARCHAR(20)  NOT NULL,   -- degenerate dimension (receipt)
    line_number              SMALLINT      NOT NULL,
    transaction_time         TIME(0)       NULL,
    quantity                 SMALLINT      NOT NULL,
    unit_price               DECIMAL(10,2) NOT NULL,
    gross_amount             DECIMAL(12,2) NOT NULL,   -- quantity x unit_price
    discount_amount          DECIMAL(12,2) NOT NULL,
    sales_revenue            DECIMAL(12,2) NOT NULL,   -- gross_amount - discount_amount (line revenue)
    unit_cost                DECIMAL(10,2) NOT NULL,   -- standard cost on the day
    cost_amount              DECIMAL(12,2) NOT NULL,   -- quantity x unit_cost
    margin_amount            DECIMAL(12,2) NOT NULL,   -- sales_revenue - cost_amount
    is_promoted              TINYINT       NOT NULL,
    is_late_arriving         TINYINT       NOT NULL,
    is_imputed               TINYINT       NOT NULL,
    extract_batch_id         NVARCHAR(20)  NOT NULL,
    extract_timestamp        DATETIME2(0)  NOT NULL,
    extract_lag_days         SMALLINT      NULL,
    dq_status                NVARCHAR(12)  NOT NULL,
    dq_rules                 NVARCHAR(200) NULL,
    source_file              NVARCHAR(50)  NOT NULL,
    source_row               INT           NOT NULL
);
GO

-- GRAIN: one row per returned line (return_id). Counted on the return
-- date at the returning store (BRD assumption 2). Role-playing dates:
-- return_date_key and original_sale_date_key both reference dim_date.
CREATE TABLE dw.fact_returns (
    return_id                NVARCHAR(10)  NOT NULL,   -- degenerate dimension
    return_date_key          INT           NOT NULL,
    store_key                INT           NOT NULL,   -- store where the return was made
    product_key              INT           NOT NULL,
    original_sale_date_key   INT           NOT NULL,   -- -1 when the sale line is not in fact_sales
    original_sale_store_key  INT           NOT NULL,   -- -1 when the sale line is not in fact_sales
    original_transaction_id  NVARCHAR(20)  NULL,
    original_line_number     SMALLINT      NULL,
    original_sales_line_id   BIGINT        NULL,       -- link to fact_sales when the sale line is present
    return_quantity          SMALLINT      NOT NULL,
    refund_value             DECIMAL(12,2) NOT NULL,
    return_reason            NVARCHAR(30)  NOT NULL,
    is_restockable           TINYINT       NOT NULL,
    restock_cost_credit      DECIMAL(14,4) NOT NULL,   -- COGS credit for returned-to-stock units (docs/04 7.1)
    has_receipt              TINYINT       NOT NULL,   -- original transaction recorded on the return
    is_linked_to_sale        TINYINT       NOT NULL,   -- Phase 3: referenced sale line was received
    dq_status                NVARCHAR(12)  NOT NULL,
    dq_rules                 NVARCHAR(200) NULL,
    source_file              NVARCHAR(50)  NOT NULL,
    source_row               INT           NOT NULL
);
GO

-- GRAIN: one row per store x product x retail week (Sunday closing snapshot),
-- for products ranged in the store. Periodic snapshot: stock levels are
-- semi-additive (do not sum closing stock across weeks).
CREATE TABLE dw.fact_inventory (
    snapshot_date_key        INT           NOT NULL,
    retail_week_key          INT           NOT NULL,
    store_key                INT           NOT NULL,
    product_key              INT           NOT NULL,
    opening_stock            INT           NOT NULL,
    received_qty             INT           NOT NULL,
    sold_qty                 INT           NOT NULL,
    adjustment_qty           INT           NOT NULL,
    closing_stock            INT           NOT NULL,
    is_in_stock              TINYINT       NOT NULL,   -- closing_stock > 0 (BRD 5.3 availability)
    dq_status                NVARCHAR(12)  NOT NULL,
    dq_rules                 NVARCHAR(200) NULL,
    source_file              NVARCHAR(50)  NOT NULL,
    source_row               INT           NOT NULL
);
GO

-- GRAIN: one row per store x retail week (Finance net revenue target).
CREATE TABLE dw.fact_targets (
    retail_week_key          INT           NOT NULL,
    store_key                INT           NOT NULL,
    target_net_revenue       DECIMAL(14,2) NOT NULL,
    target_version           NVARCHAR(10)  NOT NULL,
    target_set_date          DATE          NULL,
    source_file              NVARCHAR(50)  NOT NULL,
    source_row               INT           NOT NULL
);
GO

-- GRAIN: one row per promotion x product x store (factless coverage fact).
-- Records which SKUs were on promotion where, whether or not they sold.
-- start/end dates are attributes, not date keys: some promotions end after
-- the last calendar day in dim_date (they straddle the extract end).
CREATE TABLE dw.fact_promotion_coverage (
    promotion_key            INT           NOT NULL,
    store_key                INT           NOT NULL,
    product_key              INT           NOT NULL,
    start_date               DATE          NOT NULL,
    end_date                 DATE          NOT NULL,
    discount_pct             DECIMAL(5,4)  NOT NULL,
    source_file              NVARCHAR(50)  NOT NULL,
    source_row               INT           NOT NULL
);
GO
