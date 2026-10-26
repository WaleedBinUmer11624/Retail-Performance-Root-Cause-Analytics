{{ config(alias='fact_inventory') }}
-- Governed stg.fact_inventory: the Phase 3 curated file as text, blanks as NULL (sql/staging/02, runner @load_staging).
select * from {{ source('curated', 'fact_inventory') }}
