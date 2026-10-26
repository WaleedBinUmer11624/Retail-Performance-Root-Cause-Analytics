-- TC-04: one extract batch per business day, loaded next morning (completeness.batch_structure), on the main
-- extract as received. Phase 3 adds the batches covering more than one business day to the batches
-- extracted at more than one hour (re-sends), so a batch with both counts twice.
{% set population %}
    select extract_batch_id,
           count(distinct {{ id_date('transaction_id') }}) as business_days,
           count(distinct hour({{ parse_datetime('extract_timestamp') }}))
             + max(case when {{ parse_datetime('extract_timestamp') }} is null then 1 else 0 end) as extract_hours
    from {{ ref('stg_raw__fact_sales') }} group by extract_batch_id
{% endset %}
{% set failing %}
    select coalesce(extract_batch_id, '') || '|business_days' as row_key from population where business_days > 1
    union all
    select coalesce(extract_batch_id, '') || '|extract_hours' from population where extract_hours > 1
{% endset %}
{{ dq_result('TC-04', 571, 729, population, failing) }}
