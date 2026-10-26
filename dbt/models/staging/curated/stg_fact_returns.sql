{{ config(alias='fact_returns') }}
-- Governed stg.fact_returns: the Phase 3 curated file as text, blanks as NULL (sql/staging/02, runner @load_staging).
select * from {{ source('curated', 'fact_returns') }}
