/* =====================================================================
   06  Indexes
   ---------------------------------------------------------------------
   Workload: Power BI import refreshes and analytical SQL (large scans,
   aggregations by date/store/product), plus key lookups during the load.

   * fact_sales (1.34M rows) and fact_inventory (0.94M rows): CLUSTERED
     COLUMNSTORE. Aggregations read only the columns they need, compressed
     roughly 5-10x; rowgroups of ~1M rows are a good fit for these sizes.
     The grain is still enforced by the nonclustered PK from 05.
   * fact_returns (35k), fact_targets (2k), fact_promotion_coverage (49k):
     rowstore with a clustered PK; a columnstore brings nothing at this size.
     Nonclustered indexes support the joins actually used by the views.
   * Dimensions: clustered PK on the surrogate key (03), unique index on the
     natural key (03) for the load lookups. Dimensions are tiny.
   * Foreign-key columns on the columnstore facts are not indexed
     separately: columnstore segment elimination covers those scans.
   ===================================================================== */

-- @tsql-only
CREATE CLUSTERED COLUMNSTORE INDEX cci_fact_sales     ON dw.fact_sales;
CREATE CLUSTERED COLUMNSTORE INDEX cci_fact_inventory ON dw.fact_inventory;
GO

-- @tsql-only
CREATE NONCLUSTERED INDEX ix_fact_returns_return_date ON dw.fact_returns (return_date_key, store_key) INCLUDE (refund_value, return_quantity, restock_cost_credit);
CREATE NONCLUSTERED INDEX ix_fact_returns_product     ON dw.fact_returns (product_key) INCLUDE (refund_value, return_quantity);
CREATE NONCLUSTERED INDEX ix_fact_returns_sales_line  ON dw.fact_returns (original_sales_line_id) WHERE original_sales_line_id IS NOT NULL;
CREATE NONCLUSTERED INDEX ix_fact_promo_cov_store_product ON dw.fact_promotion_coverage (store_key, product_key) INCLUDE (start_date, end_date, discount_pct);
CREATE NONCLUSTERED INDEX ix_dim_date_retail_week     ON dw.dim_date (retail_week_key);
GO
