{{ config(alias='dim_date') }}
-- Governed stg.dim_date: the Phase 3 curated file as text, blanks as NULL (sql/staging/02, runner @load_staging).
select * from {{ source('curated', 'dim_date') }}
