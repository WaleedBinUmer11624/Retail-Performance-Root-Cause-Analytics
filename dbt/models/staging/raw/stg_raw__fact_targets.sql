{{ config(alias='fact_targets') }}
-- Raw extract as delivered, every column text. source_row is the CSV line number (header = line 1),
-- as in Phase 3 (src/data_quality/core.py load_raw).
select 'fact_targets.csv' as source_file, cast(row_number() over () + 1 as bigint) as source_row, *
from {{ source('raw', 'fact_targets') }}
