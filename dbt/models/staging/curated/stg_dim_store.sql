{{ config(alias='dim_store') }}
-- Governed stg.dim_store: the Phase 3 curated file as text, blanks as NULL (sql/staging/02, runner @load_staging).
select * from {{ source('curated', 'dim_store') }}
