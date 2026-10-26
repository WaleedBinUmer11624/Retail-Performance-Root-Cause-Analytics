-- dim_store after DS-02 (trim) and DS-03 (canonical region and format), with the DS rule flags
-- (dimensions.clean_dim_store).
{%- set text_cols = ['store_id', 'store_name', 'town', 'county', 'region', 'store_format', 'manager_name'] %}
with raw as (
    select *, count(*) over (partition by store_id) as id_copies
    from {{ ref('stg_raw__dim_store') }}
),
trimmed as (
    select source_row, id_copies,
           {{ matches('store_id', '^S\\d{2}$') }} as id_well_formed,
           ({% for c in text_cols %}{{ is_padded(c) }}{{ ' or ' if not loop.last }}{% endfor %}) as ds_02_fail,
           {% for c in text_cols %}trim({{ c }}) as {{ c }},
           {% endfor %}
           {{ to_num('floor_area_m2') }} as floor_area_m2,
           {{ to_num('headcount_fte') }} as headcount_fte,
           {{ to_num('weekly_trading_hours') }} as weekly_trading_hours,
           {{ to_num('latitude') }} as latitude,
           {{ to_num('longitude') }} as longitude,
           open_date
    from raw
),
domains as (
    select r.*,
           (select max(d) from unnest({{ var('regions') }}) as t(d) where lower(d) = lower(r.region)) as region_canonical,
           (select max(d) from unnest({{ var('store_formats') }}) as t(d) where lower(d) = lower(r.store_format)) as format_canonical
    from trimmed as r
)
select source_row,
       store_id as row_key,
       store_id,
       store_name, town, county,
       coalesce(region_canonical, region) as region,
       coalesce(format_canonical, store_format) as store_format,
       floor_area_m2, headcount_fte, weekly_trading_hours, latitude, longitude, open_date, manager_name,
       (not id_well_formed or id_copies > 1) as ds_01_fail,
       ds_02_fail,
       (region_canonical is null or region_canonical <> region or format_canonical is null
        or format_canonical <> store_format) as ds_03_fail,
       coalesce(floor_area_m2 <= 0, false) or coalesce(headcount_fte <= 0, false)
         or coalesce(not (weekly_trading_hours between 40 and 168), true)
         or coalesce(not (latitude between 51.3 and 55.5), true)
         or coalesce(not (longitude between -10.7 and -5.9), true) as ds_04_fail
from domains
