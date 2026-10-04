/* =====================================================================
   02  Staging tables
   ---------------------------------------------------------------------
   One landing table per approved Phase 3 curated file, columns in the
   exact order of the CSV header (required by BULK INSERT). Every column
   is text: staging holds the file as delivered, and typing happens in
   the dimensional load (07, 08), where conversion failures are counted.
   Also creates the reconciliation tables in schema recon.
   Re-runnable: drops and recreates.
   ===================================================================== */

SET NOCOUNT ON;
DROP TABLE IF EXISTS stg.dim_date;
CREATE TABLE stg.dim_date (
    source_file              NVARCHAR(50) NULL,
    source_row               NVARCHAR(50) NULL,
    date_key                 NVARCHAR(50) NULL,
    [date]                   NVARCHAR(50) NULL,
    day_of_week              NVARCHAR(50) NULL,
    day_name                 NVARCHAR(50) NULL,
    is_weekend               NVARCHAR(50) NULL,
    calendar_month           NVARCHAR(50) NULL,
    month_name               NVARCHAR(50) NULL,
    calendar_quarter         NVARCHAR(50) NULL,
    calendar_year            NVARCHAR(50) NULL,
    retail_year              NVARCHAR(50) NULL,
    retail_week              NVARCHAR(50) NULL,
    retail_week_start        NVARCHAR(50) NULL,
    retail_half              NVARCHAR(50) NULL,
    is_bank_holiday          NVARCHAR(50) NULL,
    holiday_name             NVARCHAR(80) NULL,
    is_trading_day           NVARCHAR(50) NULL,
    same_day_last_year       NVARCHAR(50) NULL
);
GO

SET NOCOUNT ON;
DROP TABLE IF EXISTS stg.dim_store;
CREATE TABLE stg.dim_store (
    source_file              NVARCHAR(50) NULL,
    source_row               NVARCHAR(50) NULL,
    store_id                 NVARCHAR(50) NULL,
    store_name               NVARCHAR(100) NULL,
    town                     NVARCHAR(50) NULL,
    county                   NVARCHAR(50) NULL,
    region                   NVARCHAR(50) NULL,
    store_format             NVARCHAR(50) NULL,
    floor_area_m2            NVARCHAR(50) NULL,
    open_date                NVARCHAR(50) NULL,
    manager_name             NVARCHAR(100) NULL,
    headcount_fte            NVARCHAR(50) NULL,
    weekly_trading_hours     NVARCHAR(50) NULL,
    latitude                 NVARCHAR(50) NULL,
    longitude                NVARCHAR(50) NULL
);
GO

SET NOCOUNT ON;
DROP TABLE IF EXISTS stg.dim_product;
CREATE TABLE stg.dim_product (
    source_file              NVARCHAR(50) NULL,
    source_row               NVARCHAR(50) NULL,
    product_id               NVARCHAR(50) NULL,
    product_name             NVARCHAR(150) NULL,
    category                 NVARCHAR(50) NULL,
    subcategory              NVARCHAR(50) NULL,
    brand                    NVARCHAR(50) NULL,
    supplier_id              NVARCHAR(50) NULL,
    supplier_name            NVARCHAR(100) NULL,
    list_price               NVARCHAR(50) NULL,
    unit_cost                NVARCHAR(50) NULL,
    launch_date              NVARCHAR(50) NULL,
    discontinued_date        NVARCHAR(50) NULL,
    status                   NVARCHAR(50) NULL
);
GO

SET NOCOUNT ON;
DROP TABLE IF EXISTS stg.fact_sales;
CREATE TABLE stg.fact_sales (
    transaction_id           NVARCHAR(50) NULL,
    line_number              NVARCHAR(50) NULL,
    transaction_date         NVARCHAR(50) NULL,
    transaction_time         NVARCHAR(50) NULL,
    store_id                 NVARCHAR(50) NULL,
    product_id               NVARCHAR(50) NULL,
    category                 NVARCHAR(50) NULL,
    quantity                 NVARCHAR(50) NULL,
    unit_price               NVARCHAR(50) NULL,
    discount                 NVARCHAR(50) NULL,
    revenue                  NVARCHAR(50) NULL,
    unit_cost                NVARCHAR(50) NULL,
    cost                     NVARCHAR(50) NULL,
    margin                   NVARCHAR(50) NULL,
    promotion_id             NVARCHAR(50) NULL,
    extract_batch_id         NVARCHAR(50) NULL,
    extract_timestamp        NVARCHAR(50) NULL,
    extract_lag_days         NVARCHAR(50) NULL,
    is_late_arriving         NVARCHAR(50) NULL,
    is_imputed               NVARCHAR(50) NULL,
    dq_status                NVARCHAR(50) NULL,
    dq_rules                 NVARCHAR(400) NULL,
    source_file              NVARCHAR(50) NULL,
    source_row               NVARCHAR(50) NULL
);
GO

SET NOCOUNT ON;
DROP TABLE IF EXISTS stg.fact_returns;
CREATE TABLE stg.fact_returns (
    source_file              NVARCHAR(50) NULL,
    source_row               NVARCHAR(50) NULL,
    return_id                NVARCHAR(50) NULL,
    return_date              NVARCHAR(50) NULL,
    store_id                 NVARCHAR(50) NULL,
    original_transaction_id  NVARCHAR(50) NULL,
    original_line_number     NVARCHAR(50) NULL,
    product_id               NVARCHAR(50) NULL,
    return_quantity          NVARCHAR(50) NULL,
    refund_value             NVARCHAR(50) NULL,
    return_reason            NVARCHAR(50) NULL,
    restockable_flag         NVARCHAR(50) NULL,
    is_linked                NVARCHAR(50) NULL,
    dq_rules                 NVARCHAR(400) NULL,
    dq_status                NVARCHAR(50) NULL
);
GO

SET NOCOUNT ON;
DROP TABLE IF EXISTS stg.fact_inventory;
CREATE TABLE stg.fact_inventory (
    source_file              NVARCHAR(50) NULL,
    source_row               NVARCHAR(50) NULL,
    snapshot_date            NVARCHAR(50) NULL,
    retail_year              NVARCHAR(50) NULL,
    retail_week              NVARCHAR(50) NULL,
    store_id                 NVARCHAR(50) NULL,
    product_id               NVARCHAR(50) NULL,
    opening_stock            NVARCHAR(50) NULL,
    received_qty             NVARCHAR(50) NULL,
    sold_qty                 NVARCHAR(50) NULL,
    adjustment_qty           NVARCHAR(50) NULL,
    closing_stock            NVARCHAR(50) NULL,
    dq_rules                 NVARCHAR(400) NULL,
    dq_status                NVARCHAR(50) NULL
);
GO

SET NOCOUNT ON;
DROP TABLE IF EXISTS stg.fact_promotions;
CREATE TABLE stg.fact_promotions (
    source_file              NVARCHAR(50) NULL,
    source_row               NVARCHAR(50) NULL,
    promotion_id             NVARCHAR(50) NULL,
    promotion_name           NVARCHAR(120) NULL,
    promotion_type           NVARCHAR(50) NULL,
    product_id               NVARCHAR(50) NULL,
    store_id                 NVARCHAR(50) NULL,
    start_date               NVARCHAR(50) NULL,
    end_date                 NVARCHAR(50) NULL,
    discount_pct             NVARCHAR(50) NULL
);
GO

SET NOCOUNT ON;
DROP TABLE IF EXISTS stg.fact_targets;
CREATE TABLE stg.fact_targets (
    source_file              NVARCHAR(50) NULL,
    source_row               NVARCHAR(50) NULL,
    store_id                 NVARCHAR(50) NULL,
    retail_year              NVARCHAR(50) NULL,
    retail_week              NVARCHAR(50) NULL,
    week_start_date          NVARCHAR(50) NULL,
    week_end_date            NVARCHAR(50) NULL,
    target_net_revenue       NVARCHAR(50) NULL,
    target_version           NVARCHAR(50) NULL,
    target_set_date          NVARCHAR(50) NULL
);
GO

SET NOCOUNT ON;
-- results of any previous run are removed so a failed run can never report stale checks
DROP TABLE IF EXISTS recon.dw_totals;
DROP TABLE IF EXISTS recon.kpi_validation_result;
DROP TABLE IF EXISTS recon.kv_base;
DROP TABLE IF EXISTS recon.kv_estate;
DROP TABLE IF EXISTS recon.kv_segment;
DROP TABLE IF EXISTS recon.kv_category;
DROP TABLE IF EXISTS recon.kv_yoy_estate;
DROP TABLE IF EXISTS recon.expected;
CREATE TABLE recon.expected (
    metric_name              NVARCHAR(100) NOT NULL,
    metric_group             NVARCHAR(30)  NOT NULL,
    expected_value           FLOAT         NOT NULL,
    tolerance_abs            FLOAT         NOT NULL,
    expected_source          NVARCHAR(200) NOT NULL,
    CONSTRAINT pk_recon_expected PRIMARY KEY (metric_name)
);
DROP TABLE IF EXISTS recon.actual;
CREATE TABLE recon.actual (
    metric_name              NVARCHAR(100) NOT NULL,
    actual_value             FLOAT         NULL,
    computed_from            NVARCHAR(200) NOT NULL,
    CONSTRAINT pk_recon_actual PRIMARY KEY (metric_name)
);
GO
