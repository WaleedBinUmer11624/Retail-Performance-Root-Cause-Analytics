/* =====================================================================
   03  Dimension tables
   ---------------------------------------------------------------------
   Full-refresh model: every run drops and recreates the star schema.
   Facts are dropped first because they reference the dimensions.

   Key strategy (see docs/04 section 6)
     * dim_date uses the smart key yyyymmdd (INT); -1 = unknown date.
     * dim_retail_week uses yyyyww (INT); -1 = unknown week.
     * dim_store, dim_product, dim_promotion use INT surrogate keys assigned
       deterministically at load (ROW_NUMBER over the natural key), so a
       rebuild from the same curated files gives identical keys.
     * -1 = UNKNOWN member in every dimension; 0 = "No promotion" in
       dim_promotion (a sales line without a promotion is not unknown).
   Flags are TINYINT (0/1): SQL Server cannot SUM a BIT column, and flags
   are summed in the KPI views (for example in-stock cells).
   ===================================================================== */

SET NOCOUNT ON;
DROP TABLE IF EXISTS dw.fact_sales;
DROP TABLE IF EXISTS dw.fact_returns;
DROP TABLE IF EXISTS dw.fact_inventory;
DROP TABLE IF EXISTS dw.fact_targets;
DROP TABLE IF EXISTS dw.fact_promotion_coverage;
DROP TABLE IF EXISTS dw.dim_date;
DROP TABLE IF EXISTS dw.dim_retail_week;
DROP TABLE IF EXISTS dw.dim_store;
DROP TABLE IF EXISTS dw.dim_product;
DROP TABLE IF EXISTS dw.dim_promotion;
GO

-- Retail week: shrunken roll-up of dim_date, used by the weekly facts
-- (targets, inventory) so they never relate to individual days.
CREATE TABLE dw.dim_retail_week (
    retail_week_key          INT           NOT NULL,   -- yyyyww, -1 unknown
    retail_year              SMALLINT      NULL,
    retail_week              TINYINT       NULL,
    retail_week_label        NVARCHAR(10)  NOT NULL,   -- e.g. 2025-W27
    week_start_date          DATE          NULL,
    week_end_date            DATE          NULL,
    days_in_week             TINYINT       NULL,
    retail_half              NVARCHAR(2)   NULL,
    is_comparable_week       TINYINT       NOT NULL,   -- full 7-day week inside retail years 2024-2025
    prior_year_week_key      INT           NULL,       -- same retail week one year earlier (week-aligned YoY)
    is_unknown               TINYINT       NOT NULL,
    CONSTRAINT pk_dim_retail_week PRIMARY KEY (retail_week_key)
);
GO

CREATE TABLE dw.dim_date (
    date_key                 INT           NOT NULL,   -- yyyymmdd, -1 unknown
    calendar_date            DATE          NULL,
    day_of_week              TINYINT       NULL,       -- 1 = Monday
    day_name                 NVARCHAR(10)  NULL,
    is_weekend               TINYINT       NULL,
    calendar_month           TINYINT       NULL,
    month_name               NVARCHAR(10)  NULL,
    year_month               INT           NULL,       -- yyyymm
    calendar_quarter         TINYINT       NULL,
    calendar_year            SMALLINT      NULL,
    retail_year              SMALLINT      NULL,
    retail_week              TINYINT       NULL,
    retail_week_key          INT           NOT NULL,
    retail_week_start        DATE          NULL,
    retail_half              NVARCHAR(2)   NULL,
    is_bank_holiday          TINYINT       NULL,
    holiday_name             NVARCHAR(80)  NULL,
    is_trading_day           TINYINT       NULL,
    same_day_last_year       DATE          NULL,
    same_day_last_year_key   INT           NULL,       -- date minus 364 days (same weekday)
    is_unknown               TINYINT       NOT NULL,
    CONSTRAINT pk_dim_date PRIMARY KEY (date_key)
);
GO

CREATE TABLE dw.dim_store (
    store_key                INT           NOT NULL,
    store_id                 NVARCHAR(10)  NOT NULL,   -- natural key
    store_name               NVARCHAR(100) NOT NULL,
    town                     NVARCHAR(50)  NULL,
    county                   NVARCHAR(50)  NULL,
    region                   NVARCHAR(30)  NOT NULL,
    store_format             NVARCHAR(20)  NOT NULL,
    floor_area_m2            INT           NULL,
    open_date                DATE          NULL,
    manager_name             NVARCHAR(100) NULL,
    headcount_fte            DECIMAL(6,1)  NULL,
    weekly_trading_hours     SMALLINT      NULL,
    latitude                 DECIMAL(9,4)  NULL,
    longitude                DECIMAL(9,4)  NULL,
    is_unknown               TINYINT       NOT NULL,
    source_row               INT           NULL,       -- line in the raw extract (lineage)
    CONSTRAINT pk_dim_store PRIMARY KEY (store_key),
    CONSTRAINT uq_dim_store_store_id UNIQUE (store_id)
);
GO

CREATE TABLE dw.dim_product (
    product_key              INT           NOT NULL,
    product_id               NVARCHAR(10)  NOT NULL,   -- natural key
    product_name             NVARCHAR(150) NOT NULL,
    category                 NVARCHAR(40)  NOT NULL,
    subcategory              NVARCHAR(40)  NOT NULL,
    brand                    NVARCHAR(40)  NOT NULL,
    supplier_id              NVARCHAR(10)  NOT NULL,
    supplier_name            NVARCHAR(100) NOT NULL,
    list_price               DECIMAL(10,2) NULL,       -- current (2025) price, excl. VAT
    unit_cost                DECIMAL(10,2) NULL,       -- current standard cost
    launch_date              DATE          NULL,
    discontinued_date        DATE          NULL,
    product_status           NVARCHAR(20)  NOT NULL,
    is_unknown               TINYINT       NOT NULL,
    source_row               INT           NULL,
    CONSTRAINT pk_dim_product PRIMARY KEY (product_key),
    CONSTRAINT uq_dim_product_product_id UNIQUE (product_id)
);
GO

-- One row per promotion event (header). The promotion x product x store
-- scope is the factless fact dw.fact_promotion_coverage.
CREATE TABLE dw.dim_promotion (
    promotion_key            INT           NOT NULL,
    promotion_id             NVARCHAR(12)  NOT NULL,   -- natural key; NONE / UNKNOWN for special members
    promotion_name           NVARCHAR(120) NOT NULL,
    promotion_type           NVARCHAR(20)  NOT NULL,
    promotion_category       NVARCHAR(40)  NOT NULL,   -- category of the covered products, or Mixed
    start_date               DATE          NULL,
    end_date                 DATE          NULL,
    duration_days            SMALLINT      NULL,
    min_discount_pct         DECIMAL(5,4)  NULL,
    max_discount_pct         DECIMAL(5,4)  NULL,
    stores_covered           SMALLINT      NULL,
    products_covered         SMALLINT      NULL,
    member_type              NVARCHAR(20)  NOT NULL,   -- Promotion / No promotion / Unknown
    is_unknown               TINYINT       NOT NULL,
    CONSTRAINT pk_dim_promotion PRIMARY KEY (promotion_key),
    CONSTRAINT uq_dim_promotion_promotion_id UNIQUE (promotion_id)
);
GO
