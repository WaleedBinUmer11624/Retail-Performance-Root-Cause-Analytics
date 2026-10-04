/* =====================================================================
   05  Primary keys, foreign keys and check constraints
   ---------------------------------------------------------------------
   Dimension primary keys and natural-key UNIQUE constraints are declared
   inline in 03 (they are portable). This script adds what depends on the
   physical design chosen in 06:

   * Fact primary keys enforce the declared grain. fact_sales and
     fact_inventory get NONCLUSTERED primary keys because their clustered
     index is a columnstore (06). The small facts use clustered PKs.
   * Foreign keys are created before the load (07, 08) so SQL Server
     rejects any row that does not join to a dimension: nothing can enter
     a fact without a valid (or explicitly UNKNOWN) member. Being enabled
     from the start, the constraints are trusted by the optimiser.
   * Check constraints guard the arithmetic identities the KPIs rely on.

   The local verification engine (DuckDB) cannot add constraints with
   ALTER TABLE; there the same rules are verified by tests
   (tests/test_phase4_sql_model.py parses every FOREIGN KEY below).
   ===================================================================== */

-- @tsql-only
-- Primary keys = declared grain
ALTER TABLE dw.fact_sales              ADD CONSTRAINT pk_fact_sales              PRIMARY KEY NONCLUSTERED (transaction_id, line_number);
ALTER TABLE dw.fact_sales              ADD CONSTRAINT uq_fact_sales_line_id      UNIQUE NONCLUSTERED (sales_line_id);
ALTER TABLE dw.fact_returns            ADD CONSTRAINT pk_fact_returns            PRIMARY KEY CLUSTERED (return_id);
ALTER TABLE dw.fact_inventory          ADD CONSTRAINT pk_fact_inventory          PRIMARY KEY NONCLUSTERED (store_key, product_key, snapshot_date_key);
ALTER TABLE dw.fact_targets            ADD CONSTRAINT pk_fact_targets            PRIMARY KEY CLUSTERED (store_key, retail_week_key);
ALTER TABLE dw.fact_promotion_coverage ADD CONSTRAINT pk_fact_promotion_coverage PRIMARY KEY CLUSTERED (promotion_key, store_key, product_key);
GO

-- @tsql-only
-- Foreign keys: dimension to dimension
ALTER TABLE dw.dim_date ADD CONSTRAINT fk_dim_date_retail_week FOREIGN KEY (retail_week_key) REFERENCES dw.dim_retail_week (retail_week_key);
GO

-- @tsql-only
-- Foreign keys: fact_sales
ALTER TABLE dw.fact_sales ADD CONSTRAINT fk_fact_sales_date      FOREIGN KEY (date_key)      REFERENCES dw.dim_date (date_key);
ALTER TABLE dw.fact_sales ADD CONSTRAINT fk_fact_sales_store     FOREIGN KEY (store_key)     REFERENCES dw.dim_store (store_key);
ALTER TABLE dw.fact_sales ADD CONSTRAINT fk_fact_sales_product   FOREIGN KEY (product_key)   REFERENCES dw.dim_product (product_key);
ALTER TABLE dw.fact_sales ADD CONSTRAINT fk_fact_sales_promotion FOREIGN KEY (promotion_key) REFERENCES dw.dim_promotion (promotion_key);
GO

-- @tsql-only
-- Foreign keys: fact_returns (two role-playing dates, two store roles)
ALTER TABLE dw.fact_returns ADD CONSTRAINT fk_fact_returns_return_date FOREIGN KEY (return_date_key)         REFERENCES dw.dim_date (date_key);
ALTER TABLE dw.fact_returns ADD CONSTRAINT fk_fact_returns_store       FOREIGN KEY (store_key)               REFERENCES dw.dim_store (store_key);
ALTER TABLE dw.fact_returns ADD CONSTRAINT fk_fact_returns_product     FOREIGN KEY (product_key)             REFERENCES dw.dim_product (product_key);
ALTER TABLE dw.fact_returns ADD CONSTRAINT fk_fact_returns_sale_date   FOREIGN KEY (original_sale_date_key)  REFERENCES dw.dim_date (date_key);
ALTER TABLE dw.fact_returns ADD CONSTRAINT fk_fact_returns_sale_store  FOREIGN KEY (original_sale_store_key) REFERENCES dw.dim_store (store_key);
GO

-- @tsql-only
-- Foreign keys: fact_inventory, fact_targets, fact_promotion_coverage
ALTER TABLE dw.fact_inventory ADD CONSTRAINT fk_fact_inventory_date    FOREIGN KEY (snapshot_date_key) REFERENCES dw.dim_date (date_key);
ALTER TABLE dw.fact_inventory ADD CONSTRAINT fk_fact_inventory_week    FOREIGN KEY (retail_week_key)   REFERENCES dw.dim_retail_week (retail_week_key);
ALTER TABLE dw.fact_inventory ADD CONSTRAINT fk_fact_inventory_store   FOREIGN KEY (store_key)         REFERENCES dw.dim_store (store_key);
ALTER TABLE dw.fact_inventory ADD CONSTRAINT fk_fact_inventory_product FOREIGN KEY (product_key)       REFERENCES dw.dim_product (product_key);
ALTER TABLE dw.fact_targets   ADD CONSTRAINT fk_fact_targets_week      FOREIGN KEY (retail_week_key)   REFERENCES dw.dim_retail_week (retail_week_key);
ALTER TABLE dw.fact_targets   ADD CONSTRAINT fk_fact_targets_store     FOREIGN KEY (store_key)         REFERENCES dw.dim_store (store_key);
ALTER TABLE dw.fact_promotion_coverage ADD CONSTRAINT fk_fact_promo_cov_promotion FOREIGN KEY (promotion_key) REFERENCES dw.dim_promotion (promotion_key);
ALTER TABLE dw.fact_promotion_coverage ADD CONSTRAINT fk_fact_promo_cov_store     FOREIGN KEY (store_key)     REFERENCES dw.dim_store (store_key);
ALTER TABLE dw.fact_promotion_coverage ADD CONSTRAINT fk_fact_promo_cov_product   FOREIGN KEY (product_key)   REFERENCES dw.dim_product (product_key);
GO

-- @tsql-only
-- Check constraints: line identities and value domains
ALTER TABLE dw.fact_sales ADD CONSTRAINT ck_fact_sales_quantity CHECK (quantity > 0);
ALTER TABLE dw.fact_sales ADD CONSTRAINT ck_fact_sales_gross    CHECK (gross_amount = quantity * unit_price);
ALTER TABLE dw.fact_sales ADD CONSTRAINT ck_fact_sales_revenue  CHECK (sales_revenue = gross_amount - discount_amount);
ALTER TABLE dw.fact_sales ADD CONSTRAINT ck_fact_sales_margin   CHECK (margin_amount = sales_revenue - cost_amount);
ALTER TABLE dw.fact_sales ADD CONSTRAINT ck_fact_sales_flags    CHECK (is_promoted IN (0, 1) AND is_late_arriving IN (0, 1) AND is_imputed IN (0, 1));
ALTER TABLE dw.fact_returns   ADD CONSTRAINT ck_fact_returns_values CHECK (return_quantity > 0 AND refund_value > 0);
ALTER TABLE dw.fact_inventory ADD CONSTRAINT ck_fact_inventory_flow CHECK (closing_stock >= 0 AND is_in_stock IN (0, 1));
ALTER TABLE dw.fact_targets   ADD CONSTRAINT ck_fact_targets_value  CHECK (target_net_revenue > 0);
GO
