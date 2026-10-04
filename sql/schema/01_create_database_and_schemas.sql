/* =====================================================================
   01  Database and schemas
   ---------------------------------------------------------------------
   Target: SQL Server 2022 (Developer), Windows authentication.
   Run against master; the USE switches the session to the new database.

   Schemas
     stg    landing copies of the approved Phase 3 curated files (text)
     dw     star schema: dimensions and facts (typed, keyed, constrained)
     mart   governed KPI and analytical views for Power BI and SQL analysis
     recon  reconciliation against the Phase 3 trusted outputs

   Batches marked "@tsql-only" run only on SQL Server (the local DuckDB
   verification engine creates the same four schemas itself).
   Re-runnable: every statement checks for existence first.
   ===================================================================== */

-- @tsql-only
IF DB_ID(N'BrightwaterRetail') IS NULL
    CREATE DATABASE BrightwaterRetail;
GO

-- @tsql-only
-- Development database rebuilt by full reload: simple recovery keeps the log small.
ALTER DATABASE BrightwaterRetail SET RECOVERY SIMPLE;
GO

-- @tsql-only
USE BrightwaterRetail;
GO

-- @tsql-only
IF SCHEMA_ID(N'stg')   IS NULL EXEC (N'CREATE SCHEMA stg');
IF SCHEMA_ID(N'dw')    IS NULL EXEC (N'CREATE SCHEMA dw');
IF SCHEMA_ID(N'mart')  IS NULL EXEC (N'CREATE SCHEMA mart');
IF SCHEMA_ID(N'recon') IS NULL EXEC (N'CREATE SCHEMA recon');
GO
