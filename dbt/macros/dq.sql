{#- SQL versions of the Phase 3 parsing helpers (src/data_quality/core.py). Raw extracts are read
    as text; each rule parses what it checks, and a blank is never a parse failure. -#}

{%- macro null_tokens() -%}('', 'NULL', 'null', 'None', 'NaN', 'nan', 'N/A', 'n/a', '#N/A'){%- endmacro -%}

{#- core.is_blank: empty or a null token; short values (4 characters or fewer) are also tested trimmed. -#}
{%- macro is_blank(col) -%}
({{ col }} is null or {{ col }} in {{ null_tokens() }} or (length({{ col }}) <= 4 and trim({{ col }}) in {{ null_tokens() }}))
{%- endmacro -%}

{#- core.to_num: numeric value, NULL for blanks and unparseable text. -#}
{%- macro to_num(col) -%}
(case when not {{ is_blank(col) }} then try_cast(trim({{ col }}) as double) end)
{%- endmacro -%}

{#- core.parse_date_iso / parse_date_dmy: strict yyyy-mm-dd or dd/mm/yyyy, NULL otherwise. -#}
{%- macro parse_iso(col) -%}
(case when not {{ is_blank(col) }} then cast(try_strptime({{ col }}, '%Y-%m-%d') as date) end)
{%- endmacro -%}

{%- macro parse_dmy(col) -%}
(case when not {{ is_blank(col) }} then cast(try_strptime({{ col }}, '%d/%m/%Y') as date) end)
{%- endmacro -%}

{%- macro parse_datetime(col) -%}
(case when not {{ is_blank(col) }} then try_strptime({{ col }}, '%Y-%m-%d %H:%M:%S') end)
{%- endmacro -%}

{#- core.id_date / id_store: business date and store encoded in the transaction ID (Sxx-yyyymmdd-nnnnn). -#}
{%- macro id_date(col) -%}
cast(try_strptime(substr({{ col }}, 5, 8), '%Y%m%d') as date)
{%- endmacro -%}

{%- macro id_store(col) -%}
substr({{ col }}, 1, 3)
{%- endmacro -%}

{#- core.matches: full-string regex match; missing values do not match. -#}
{%- macro matches(col, pattern) -%}
coalesce(regexp_full_match({{ col }}, '{{ pattern }}'), false)
{%- endmacro -%}

{#- pandas str != str.strip(): a value with leading or trailing whitespace. -#}
{%- macro is_padded(col) -%}
coalesce({{ col }} <> trim({{ col }}, ' ' || chr(9) || chr(10) || chr(13)), false)
{%- endmacro -%}

{#- core.parse_type failure for a contract type: a non-blank value that does not parse. -#}
{%- macro type_failure(col, kind) -%}
{%- if kind == 'str' -%} false
{%- elif kind == 'decimal' -%} (not {{ is_blank(col) }} and {{ to_num(col) }} is null)
{%- elif kind == 'int' -%} (not {{ is_blank(col) }} and ({{ to_num(col) }} is null or {{ to_num(col) }} <> round({{ to_num(col) }})))
{%- elif kind == 'date' -%} (not {{ is_blank(col) }} and {{ parse_iso(col) }} is null)
{%- elif kind == 'datetime' -%} (not {{ is_blank(col) }} and {{ parse_datetime(col) }} is null)
{%- elif kind == 'time' -%} (not {{ is_blank(col) }} and try_strptime({{ col }}, '%H:%M') is null)
{%- elif kind == 'bool' -%} (not {{ is_blank(col) }} and coalesce({{ col }} not in ('True', 'False'), true))
{%- endif -%}
{%- endmacro -%}

{#- dimensions._norm: lower case, the word "and" removed, letters only. -#}
{%- macro norm_label(col) -%}
regexp_replace(regexp_replace(lower(trim({{ col }})), '\band\b', '', 'g'), '[^a-z]', '', 'g')
{%- endmacro -%}

{#- Revenue sum as Phase 3 _rev rounds it. -#}
{%- macro money(expr) -%}round({{ expr }}, 2){%- endmacro -%}

{#- numpy round, as pandas Series.round applies it: scale, round half to even, unscale. -#}
{%- macro np_round(expr, digits=2) -%}(round_even(({{ expr }}) * {{ 10 ** digits }}, 0) / {{ 10 ** digits }}){%- endmacro -%}

{#- A list of strings as an SQL IN list: ('a', 'b'). -#}
{%- macro in_list(values) -%}({% for v in values %}'{{ v | replace("'", "''") }}'{{ ', ' if not loop.last }}{% endfor %}){%- endmacro -%}
