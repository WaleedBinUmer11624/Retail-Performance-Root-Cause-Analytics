-- dim_date typed to its contract (dimensions.clean_dim_date). Carries the DD-02 flag.
with typed as (
    select source_row,
           date_key as date_key_raw,
           try_cast({{ to_num('date_key') }} as bigint)        as date_key,
           {{ parse_iso('"date"') }}                           as calendar_date,
           try_cast({{ to_num('day_of_week') }} as integer)    as day_of_week,
           case is_weekend when 'True' then true when 'False' then false end         as is_weekend,
           try_cast({{ to_num('retail_year') }} as integer)    as retail_year,
           try_cast({{ to_num('retail_week') }} as integer)    as retail_week,
           {{ parse_iso('retail_week_start') }}                as retail_week_start,
           case is_trading_day when 'True' then true when 'False' then false end     as is_trading_day
    from {{ ref('stg_raw__dim_date') }}
)
select *,
       cast(date_key as varchar) as row_key,
       -- DD-02: weekday, weekend flag, date key and retail week start agree with the date
       coalesce(day_of_week <> isodow(calendar_date), true)
         or coalesce(is_weekend <> (isodow(calendar_date) >= 6), true)
         or coalesce(date_key <> cast(strftime(calendar_date, '%Y%m%d') as bigint), true)
         or coalesce(not (date_diff('day', retail_week_start, calendar_date) between 0 and 6), true) as dd_02_fail
from typed
