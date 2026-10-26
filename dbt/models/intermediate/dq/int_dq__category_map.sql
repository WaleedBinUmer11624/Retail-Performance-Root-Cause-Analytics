-- Canonical category for every category label in the product master and on POS lines
-- (dimensions.canonical_category): exact match after normalising, else a unique first-word match,
-- else one close fuzzy match. Phase 3 scores fuzzy matches with difflib (ratio >= 0.85); SQL has no
-- difflib, so the score here is 1 - 2 x Levenshtein distance / combined length, which never exceeds
-- the difflib ratio for these short labels. tests/dq/dq_category_map_matches_phase3.sql checks the
-- product-master mapping against reports/phase3/category_mapping.csv.
with labels as (
    select distinct trim(category) as raw_label from {{ ref('stg_raw__dim_product') }}
    union
    select distinct category from {{ ref('stg_raw__fact_sales') }}
    union
    select distinct category from {{ ref('stg_raw__fact_sales_late_batch') }}
),
lbl as (
    select raw_label, {{ norm_label('raw_label') }} as n
    from labels where raw_label is not null and trim(raw_label) <> ''
),
canon as (
    select c, {{ norm_label('c') }} as n, {{ norm_label("split_part(c, ' ', 1)") }} as first_word
    from unnest({{ var('categories') }}) as t(c)
),
exact as (
    select l.raw_label, min(k.c) as c from lbl as l join canon as k on k.n = l.n group by l.raw_label
),
first_word as (
    select l.raw_label, min(k.c) as c from lbl as l join canon as k on k.first_word = l.n
    group by l.raw_label having count(*) = 1
),
scored as (
    select l.raw_label, k.c,
           1 - 2.0 * levenshtein(l.n, k.n) / nullif(length(l.n) + length(k.n), 0) as score
    from lbl as l cross join canon as k
),
close as (
    select raw_label, c, score, row_number() over (partition by raw_label order by score desc, c) as rk,
           lead(score) over (partition by raw_label order by score desc, c) as next_score
    from scored where score >= 0.85
),
fuzzy as (
    select raw_label, c from close where rk = 1 and (next_score is null or score - next_score > 0.1)
)
select l.raw_label, coalesce(e.c, f.c, z.c) as canonical
from lbl as l
left join exact as e using (raw_label)
left join first_word as f using (raw_label)
left join fuzzy as z using (raw_label)
