-- FS-26: one store, date and time per transaction; line numbers 1..n (sales.clean_sales). Checked per
-- curated transaction. Line-number gaps are tested on every distinct line received, because a gap is
-- expected where a line was quarantined.
{% set population %}
    select distinct transaction_id from {{ ref('int_dq__sales_curated') }} where stage = 'kept'
{% endset %}
{% set failing %}
    select transaction_id as row_key from {{ ref('int_dq__sales_curated') }} where stage = 'kept'
    group by transaction_id
    having count(distinct store_id) > 1 or count(distinct transaction_date) > 1 or count(distinct transaction_time) > 1
    union
    select transaction_id from {{ ref('int_dq__sales_deduplicated') }}
    group by transaction_id having min(line_no) <> 1 or max(line_no) <> count(*)
{% endset %}
{{ dq_result('FS-26', 0, 835568, population, failing) }}
