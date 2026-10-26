{#- Shared body of every data-quality test (the generic tests in tests/generic/dq_tests.sql and the singular
    tests in tests/dq): the failing rows of a rule, plus one extra row when the checked population differs
    from Phase 3's rows_checked, so the failure count can only equal Phase 3's rows_failed when both agree.
    dq_failed_offset (default 0) exists so tests/test_dbt_project.py can prove a wrong expectation fails. -#}
{% macro dq_result(rule_id, failed, checked, population_sql, failing_sql) %}
{%- set expected = failed | int + var('dq_failed_offset', 0) | int -%}
{{ config(error_if='!=' ~ expected, warn_if='!=' ~ expected, tags=['dq', 'dq_rule', rule_id], meta={'rule_id': rule_id}) }}
with population as (
    {{ population_sql }}
),
failing as (
    {{ failing_sql }}
)
select '{{ rule_id }}' as rule_id, cast(row_key as varchar) as row_key from failing
union all
select '{{ rule_id }}', 'rows_checked ' || count(*) || ', Phase 3 checked {{ checked }}'
from population having count(*) <> {{ checked }}
{% endmacro %}
