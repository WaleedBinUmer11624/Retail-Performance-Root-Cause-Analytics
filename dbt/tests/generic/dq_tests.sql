{#- Generic data-quality tests. Each returns one row per record that fails the rule, so dbt's failure
    count is the rule's rows_failed. Phase 3 recorded an exact rows_failed and rows_checked for every rule
    (reports/phase3/dq_rule_results.csv); the test passes only when dbt finds exactly that many failing
    rows (error_if / warn_if "!= failed") among exactly that many checked rows (a population of any
    other size adds one extra row, so the count can no longer match). The shared body is the macro
    dq_result in macros/dq_result.sql. -#}


{#- Any row-level rule: rows of the population where the condition holds. -#}
{% test dq_rule(model, rule_id, failed, checked, condition, population='true', key='row_key') %}
{{ dq_result(rule_id, failed, checked,
             'select *, ' ~ key ~ ' as dq_key from ' ~ model ~ ' where ' ~ population,
             'select dq_key as row_key from population where ' ~ condition) }}
{% endtest %}

{#- Exact duplicate rows: every repeat of an earlier identical row (pandas duplicated(keep="first")). -#}
{% test dq_exact_duplicates(model, rule_id, failed, checked, columns, key) %}
{{ dq_result(rule_id, failed, checked,
             'select * from ' ~ model,
             'select ' ~ key ~ ' as row_key from (select *, row_number() over (partition by ' ~ columns | join(', ')
             ~ ' order by source_row) as copy_no from population) where copy_no > 1') }}
{% endtest %}

{#- Text with leading or trailing whitespace in any of the columns. -#}
{% test dq_padded(model, rule_id, failed, checked, columns, key) %}
{%- set cond -%}{% for c in columns %}{{ is_padded(c) }}{{ ' or ' if not loop.last }}{% endfor %}{%- endset -%}
{{ dq_result(rule_id, failed, checked,
             'select * from ' ~ model,
             'select ' ~ key ~ ' as row_key from population where ' ~ cond) }}
{% endtest %}

{#- Key that is not unique or not well formed: every row of a duplicated key (keep=False) and every
    row whose key does not match the pattern. -#}
{% test dq_unique_well_formed(model, rule_id, failed, checked, column, pattern) %}
{{ dq_result(rule_id, failed, checked,
             'select * from ' ~ model,
             'select ' ~ column ~ ' as row_key from (select *, count(*) over (partition by ' ~ column ~ ') as copies from population) '
             ~ 'where copies > 1 or not ' ~ matches(column, pattern)) }}
{% endtest %}
