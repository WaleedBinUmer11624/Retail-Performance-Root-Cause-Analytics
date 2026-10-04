/* =====================================================================
   Build the whole Phase 4 model from SSMS or sqlcmd (SQLCMD mode)
   ---------------------------------------------------------------------
   Equivalent to: python -m src.sql_model.run_model
   (the runner is the tested path and also writes reports/phase4/).

   sqlcmd -S localhost -E -I -i sql\run_all_sqlcmd.sql ^
          -v ProjectRoot="C:\...\Retail_Performance_Root_Cause_Analytics" ^
             CuratedPath="C:\...\Retail_Performance_Root_Cause_Analytics\data\processed\curated" ^
             RowTerminator="0x0a"

   -I (QUOTED_IDENTIFIER ON) is required by the filtered index in 06; the SET
   batch below also sets it for SSMS. In SSMS (Query > SQLCMD Mode) define the
   three variables with :setvar before running.

   reports/phase4/generated/recon_expected_values.sql is written by the runner from
   Phase 3's trusted outputs; it loads recon.expected. Any reconciliation or KPI
   validation failure raises an error (THROW) and stops the script.
   ===================================================================== */
:on error exit
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
GO
:r "$(ProjectRoot)\sql\schema\01_create_database_and_schemas.sql"
:r "$(ProjectRoot)\sql\staging\02_create_staging_tables.sql"
:r "$(ProjectRoot)\sql\staging\bulk_insert_staging.sql"
:r "$(ProjectRoot)\reports\phase4\generated\recon_expected_values.sql"
:r "$(ProjectRoot)\sql\schema\03_create_dimension_tables.sql"
:r "$(ProjectRoot)\sql\schema\04_create_fact_tables.sql"
:r "$(ProjectRoot)\sql\schema\05_create_keys_and_constraints.sql"
:r "$(ProjectRoot)\sql\schema\06_create_indexes.sql"
:r "$(ProjectRoot)\sql\transformations\07_load_dimensions.sql"
:r "$(ProjectRoot)\sql\transformations\08_load_facts.sql"
:r "$(ProjectRoot)\sql\validation\09_reconciliation.sql"
:r "$(ProjectRoot)\sql\analysis\10_analytical_views.sql"
:r "$(ProjectRoot)\sql\validation\11_kpi_validation.sql"
