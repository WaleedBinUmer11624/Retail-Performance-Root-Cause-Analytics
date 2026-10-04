/* =====================================================================
   Optional: load staging with BULK INSERT from SSMS (SQLCMD mode)
   ---------------------------------------------------------------------
   The primary, tested path is the Python runner (python -m src.sql_model.run_model),
   which loads staging through pyodbc and verifies the curated files' SHA-256
   first. Use this script only to build the model entirely from SSMS.

   * Enable Query > SQLCMD Mode in SSMS and define the folder first with the
     SQLCMD command setvar CuratedPath "C:\...\data\processed\curated"
     (preceded by a colon), or pass it to sqlcmd: -v CuratedPath="...".
   * The SQL Server service account must be able to read that folder.
   * Curated CSVs are UTF-8, comma separated, header on line 1. Line endings
     depend on where Phase 3 ran: LF on Linux/macOS, CRLF when pandas wrote
     them on Windows. Set the variable RowTerminator to 0x0a for LF files, or
     to \n for CRLF files (in BULK INSERT the literal \n means CR+LF).
     A wrong terminator leaves a carriage return in the last column; the Python
     runner reads either format correctly.
   * Empty fields load as NULL (KEEPNULLS), exactly as the runner loads them.
   Run after 02_create_staging_tables.sql.
   ===================================================================== */
-- @tsql-only
TRUNCATE TABLE stg.dim_date;
TRUNCATE TABLE stg.dim_store;
TRUNCATE TABLE stg.dim_product;
TRUNCATE TABLE stg.fact_sales;
TRUNCATE TABLE stg.fact_returns;
TRUNCATE TABLE stg.fact_inventory;
TRUNCATE TABLE stg.fact_promotions;
TRUNCATE TABLE stg.fact_targets;
BULK INSERT stg.dim_date        FROM '$(CuratedPath)\dim_date.csv'        WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '$(RowTerminator)', CODEPAGE = '65001', KEEPNULLS, TABLOCK);
BULK INSERT stg.dim_store       FROM '$(CuratedPath)\dim_store.csv'       WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '$(RowTerminator)', CODEPAGE = '65001', KEEPNULLS, TABLOCK);
BULK INSERT stg.dim_product     FROM '$(CuratedPath)\dim_product.csv'     WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '$(RowTerminator)', CODEPAGE = '65001', KEEPNULLS, TABLOCK);
BULK INSERT stg.fact_sales      FROM '$(CuratedPath)\fact_sales.csv'      WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '$(RowTerminator)', CODEPAGE = '65001', KEEPNULLS, TABLOCK);
BULK INSERT stg.fact_returns    FROM '$(CuratedPath)\fact_returns.csv'    WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '$(RowTerminator)', CODEPAGE = '65001', KEEPNULLS, TABLOCK);
BULK INSERT stg.fact_inventory  FROM '$(CuratedPath)\fact_inventory.csv'  WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '$(RowTerminator)', CODEPAGE = '65001', KEEPNULLS, TABLOCK);
BULK INSERT stg.fact_promotions FROM '$(CuratedPath)\fact_promotions.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '$(RowTerminator)', CODEPAGE = '65001', KEEPNULLS, TABLOCK);
BULK INSERT stg.fact_targets    FROM '$(CuratedPath)\fact_targets.csv'    WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '$(RowTerminator)', CODEPAGE = '65001', KEEPNULLS, TABLOCK);
GO
