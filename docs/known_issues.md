# Known issues

Open findings recorded during the project. Nothing in this file is a fix: each entry states what
was observed, where it was observed, and what has or has not been done about it.

Governed and frozen artefacts are never edited to resolve an entry. Where a finding needs a
governed change it stays open until the owner decides.

---

## KI-01 Evidence-matrix impact columns: point estimates agree, schemas differ

**Status:** resolved for the AI layer, recorded here for traceability
**Found:** Phase 11 checkpoint 3 review, read-only comparison on 2026-10-04
**Files:** `reports/phase6/root_cause_evidence_matrix.csv`,
`powerbi/data/p6_evidence_matrix.csv` (both frozen, both unmodified)

### Side-by-side impact comparison

| Driver | `root_cause_evidence_matrix.estimated_impact_eur` | `p6_evidence_matrix.financial_impact_eur` | Difference |
| --- | ---: | ---: | ---: |
| D01 | -397778.209303 | -397778.209303 | 0 |
| D02 | -397778.209303 | -397778.209303 | 0 |
| D03 | -37235.346776 | -37235.346776 | 0 |
| D04 | -30996.272461 | -30996.272461 | 0 |
| D05 | -31588.73 | -31588.73 | 0 |
| D06 | -31588.73 | -31588.73 | 0 |
| D07 | -186146.420449 | -186146.420449 | 0 |
| D08 | (blank) | (blank) | n/a |
| D09 | -78521.793472 | -78521.793472 | 0 |

**The two point estimates are identical for every driver.** D08 is blank in both files, which is
deliberate on both sides: `docs/07_power_bi_dashboard_design.md` and the Phase 6 report both
present D08 as a partition of the Electronics and Tech change rather than an estimate, and the
dashboard renders `impact_range = "n/a (a partition, not an estimate)"`.

**Correction to an earlier checkpoint 3 report.** That report stated the two columns disagreed.
It did not: it inferred a disagreement from the `confidence` column of the dashboard extract,
which holds sensitivity ranges such as `-EUR 435,210 to -EUR 377,245`, without reading
`financial_impact_eur` itself. Reading the column shows exact agreement. No inconsistency
exists between the two impact columns.

### Do the definitions differ?

No definitional difference was found. The documentation does not define either column name
directly; `docs/07_power_bi_dashboard_design.md` describes the matrix impact as the
`[Driver Impact (single driver)]` measure, warns that the driver rows overlap (D02 repeats D01,
D04 is part of D03, D06 repeats D05) and that the measure is therefore blank at total level. The
Phase 6 report describes the same figures as estimated or root-caused amounts with ranges.

### The real differences are structural, not numeric

The two files serve different purposes and carry different columns:

| Concern | `reports/phase6/root_cause_evidence_matrix.csv` | `powerbi/data/p6_evidence_matrix.csv` |
| --- | --- | --- |
| Impact column | `estimated_impact_eur` | `financial_impact_eur` |
| Evidence strength | `evidence_level` text only | `evidence_level` **plus** numeric `evidence_strength` 0 to 3 and `evidence_colour` |
| Cause state | not present | `cause_status` |
| Sensitivity range | not present | `confidence` (variant ranges) and `impact_range` |
| Reasoning text | `mechanism`, `conclusion` | `what_we_know`, `what_we_do_not_know`, `method` |
| Data needed | `additional_data_required`, `double_counting_risk` | `additional_data_required`, `double_counting_risk` |
| Dashboard ordering | `sort_order` present | `sort_order` present |

The dashboard extract is a superset for strength and range purposes: it is the only one of the
two that carries the governed `evidence_strength` score, which is what the Phase 11 confidence
scale in `experimental/ai_layer/grounding.py` is derived from.

### Action taken

`config/phase11_config.yaml` now resolves `phase6.evidence_matrix` to
`powerbi/data/p6_evidence_matrix.csv`, so the AI layer and every dashboard page cite the same
impact and strength figures. No frozen file was edited; both CSV files are byte-identical to
their recorded hashes. `tests/test_phase11_cp3.py` asserts that every evidence-matrix claim names
the dashboard extract as its source and that each rendered impact equals the published
`financial_impact_eur` for that driver.

---

## KI-02 Residual wording differs between the attribution file and the matrix

**Status:** open, wording only, no action recommended without an owner decision
**Found:** Phase 11 checkpoint 3
**Files:** `reports/phase6/driver_attribution.csv` (frozen),
`reports/phase6/root_cause_evidence_matrix.csv` (frozen)

The residual component is described differently in the two frozen files:

- `driver_attribution.csv` row `Residual: not attributed` gives
  `basis = "Total minus the components above (closes the attribution exactly)"`.
- `root_cause_evidence_matrix.csv` D09 gives
  `conclusion = "Not attributed. Mostly E&T continuing-SKU sales outside the cluster (see D08)."`

Both describe the same EUR -78,521.79 residual and both close on the same total. The
attribution file says "components", the matrix says "drivers". This is a wording difference only;
no figure, sign or total differs.

Left open deliberately. Both files are frozen, and section 24 of the phase brief requires a
governed inconsistency to be reported rather than silently corrected. Resolving it needs an owner
decision on which wording is canonical.

---

## KI-03 measures_tmdl.tmdl drifted on regeneration; original recovered and restored

**Status:** resolved; frozen original restored and the protected baseline reverted
**Found:** Phase 11 checkpoint 5, 2026-10-04; corrected the same day
**Files:** `powerbi/dax/measures_tmdl.tmdl`, `src/powerbi/run_phase7.py`, `src/powerbi/assets.py`
(all Phase 7 frozen artefacts), `tmp/protected_hash_baseline.txt`

### What happened

Regenerating the Power BI report to repair a Desktop save that had dropped the registered theme and
the table-total settings re-ran `src/powerbi/run_phase7.py`, which rewrote its own outputs. That
overwrote two frozen artefacts that the report rebuild was never meant to touch:

| File | Frozen | Drifted | Restored |
| --- | ---: | ---: | --- |
| `powerbi/dax/measures_tmdl.tmdl` | 27,027 bytes | 26,863 bytes | yes |
| `reports/phase7/mockups/*.png` (7 files) | 230,181 to 366,326 bytes each | 204,520 to 287,445 bytes each | yes |

The seven mockup PNGs were recovered byte-for-byte from
`E:\Retail_Performance_Root_Cause_Analytics_backups\phase7_frozen_restore.zip`.

### The original TMDL was recoverable

An earlier version of this entry said the original 27,027-byte file was unrecoverable. That was
wrong. `E:\Retail_Performance_Root_Cause_Analytics_backups\pbip_all_pages_v4.zip` holds it at
`powerbi/dax/measures_tmdl.tmdl` with sha256 `a3733a36e4039172300d218c597237cd52ec38ed51b52a526858de21262be375`
and 27,027 bytes, matching both `reports/phase8/phase1_7_input_manifest.csv` and
`reports/phase9/phase1_8_dependency_manifest.csv`. It was verified on sha256 and size and restored.

### The drift was format-string quoting, not whitespace

An earlier version of this entry described the 164-byte difference as trailing whitespace inside
`///` comments. That was also wrong. A line diff of the two files shows the only change is the
quoting of `formatString` values, on every measure that has one:

| Frozen | Drifted |
| --- | --- |
| `formatString: "€#,0"` | `formatString: €#,0` |
| `formatString: "0.0%"` | `formatString: 0.0%` |

82 quote pairs account for the 164 bytes. No measure name, DAX expression, display folder or data
type differs; both files have LF line endings. `tmp/validate_pbip.py` check [7] (DAX expression
fidelity) reports 0 differences across 92 measures against the restored file, and check [8]
reports the euro sign intact.

### Baseline reverted

The re-baselining recorded earlier for this entry has been undone:

| Group | Drifted sha256 (removed) | Restored sha256 (original) |
| --- | --- | --- |
| `governed_measure_source` | `d2f7c76055d2d206df8d709a3b457e5a50223baf2fd97fdd78b3f7f172cfd2f1` | `edd3c897905c3a1cc3a1540dae1a333b23a70182f484d5739975734ec1f06319` |

`tmp/hash_check.py` passes 9/9 against the original values.

### LF fix reverted in the Phase 7 generator

After the drift, `src/powerbi/run_phase7.py` and `src/powerbi/assets.py` were edited to pass
`newline=""` to every `write_text` call, so their outputs would be LF on every platform. Both files
are frozen by the Phase 8 and Phase 9 manifests, so that edit broke the Phase 8, 9 and 10 freeze
checks. Both were restored to their frozen versions:

| File | sha256 | Bytes | Source |
| --- | --- | ---: | --- |
| `src/powerbi/run_phase7.py` | `4bec7cbe2710f4695dea04d0450885305ef3d640b2d8a86d4c36afcc44602a4d` | 13,593 | `tmp/run_phase7_restore.zip` |
| `src/powerbi/assets.py` | `67b0323cb228c3a0fc4ff309e8d3165ea6878c6618dc26689ef34b448f54661d` | 17,407 | rebuilt by removing the four `newline=""` arguments and one comment; byte-identical to the manifest |

Effect on the Phase 7 reproducibility test: `tests/test_phase7_powerbi.py::test_assets_and_reports_are_reproducible` now fails on Windows.
The frozen generator writes text with the platform line ending, so a fresh run produces CRLF
while the committed outputs are LF; the first mismatch reported is
`powerbi/brightwater_theme.json` (`b'{\n'` committed against `b'{\r\n'` regenerated). No
committed output changes. Restoring the LF fix needs an owner decision to re-freeze both
runner files in the Phase 8 and Phase 9 manifests.

### Root cause and the guard added against it

The report rebuild script `tmp/build_pbip.py` writes the PBIP report under
`powerbi/Brightwater_Executive_Dashboard/` only. The overwrite came from running the **Phase 7
generator** (`src/powerbi/run_phase7.py`) for its side effects, not from the report builder. That
runner writes `powerbi/dax/` and `reports/phase7/` by design.

Two guards prevent a repeat:

1. `tmp/build_pbip.py` refuses to write anything outside the PBIP report directory.
2. `tests/test_phase11_cp4.py::test_pbip_builder_writes_only_inside_the_report_directory` asserts
   that constraint from the script source.

Do not re-run `src/powerbi/run_phase7.py` against the repository root; it overwrites frozen outputs.

---

## KI-04 A virtual environment inside the project root fails the Phase 5 and Phase 7 open audits

**Status:** open; avoided by setup, governed code not changed
**Found:** test diagnosis, 2026-10-04
**Files:** `src/analytics/run_phase5.py` (`OpenRecorder`), `src/analytics/model_access.py`
(`_is_refused`), `src/powerbi/run_phase7.py` (all frozen, all unmodified)

### What happens

The Phase 5 and Phase 7 runners record every file opened under the project root through a Python
audit hook, then refuse any path with a segment that starts with a single underscore (the marker
for evaluation-only assets). When the virtual environment lives at `.venv/` inside the project,
library imports during the run are recorded too, for example
`.venv/Lib/site-packages/duckdb/__pycache__/_dbapi_type_object.cpython-314.pyc`. Those names start
with an underscore, so the run reports a refused read and sets `passed = False`.

| Test | Effect |
| --- | --- |
| `tests/test_phase5_analytics.py::test_all_validation_checks_pass` | fails on `phase5["passed"]` although all 64 checks PASS |
| `tests/test_phase5_analytics.py::test_run_never_opens_an_evaluation_asset` | lists the `.venv` reads as offenders |
| `tests/test_phase7_powerbi.py::test_all_checks_pass` | fails on the same refused list |
| `tests/test_phase7_powerbi.py::test_run_never_opens_an_evaluation_asset` | lists the `.venv` reads as offenders |

No evaluation-only asset is opened. The flagged reads are the interpreter's own library files.

### Why Phases 6, 8 and 9 are not affected

Their runners pass the recorder summary through `classify_opened` in `src/monitoring/access.py`,
which moves reads inside the active interpreter environment to `runtime_reads` and leaves every
project-data refusal in place. The Phase 5 and Phase 7 runners are frozen and call
`OpenRecorder.summary()` directly, so they never received that split.

### Resolution

Create the virtual environment outside the project folder (README section 8, Step 2), so no
library read falls under the project root. The frozen runners are not edited.

---

## KI-05 SQL Server rejected the reconciliation script: a path in its header opened a nested comment

**Status:** resolved; comment-only change to a frozen script, authorised by the project owner on
2026-10-18, with the hash re-baselined in every manifest that pins it
**Found:** read-only audit of `reports/phase4/run_summary_mssql.json`, 2026-10-18
**Files:** `sql/validation/09_reconciliation.sql` (frozen, line 8 comment only), the ten Phase 5 to
9 manifest and verification files listed below, `reports/phase4/*_mssql*`,
`tmp/protected_hash_baseline.txt`

This entry is the one recorded exception to the rule at the top of this file: a frozen script was
edited because the owner authorised it. The change touches comment text only.

### What happened

The governed SQL Server run (`python -m src.sql_model.run_model --engine mssql`, 2026-09-29) loaded
the schema, dimensions and facts, then stopped at script 09 with `Missing end comment mark` and
recorded `passed: false`. Line 8 of the script header read `data/processed/curated/*.csv`. SQL
Server nests block comments, so the `/*` inside that path opened a second comment level that the
header's single `*/` never closed (8 openers, 7 closers). The DuckDB path was not affected: its
runner strips comments with a non-nesting pattern before translation, which is why DuckDB passed.

### Change

Line 8 only, inside the header comment:

| | Text | File SHA-256 | Bytes |
| --- | --- | --- | --- |
| Before | `data/processed/curated/*.csv` | `bf98055918ec9635aa3ff5f499594e48523fd78f26fd30e9c0538d4650cee575` | 13,700 |
| After | `data/processed/curated (*.csv)` | `a0c7f3ed90d79d7db0a8e800491684c1ed668e1f5a1608755f8d11cffd3f1891` | 13,700 |

The padding after the path was shortened by two spaces, so the file size and column alignment are
unchanged. The file now has 7 openers and 7 closers. No statement, view or value changed.

### Manifests re-baselined

The new hash replaces the old one in all ten files that pin it. Each later manifest also records the
hash of the earlier manifests, so the change cascades from Phase 5 to Phase 9; only hash strings
were replaced, and every file keeps its size.

- `reports/phase5/phase1_4_input_manifest.csv`, `reports/phase5/input_verification.csv`
- `reports/phase6/phase1_5_input_manifest.csv`, `reports/phase6/input_verification.csv`
- `reports/phase7/phase1_6_input_manifest.csv`, `reports/phase7/input_verification.csv`
- `reports/phase8/phase1_7_input_manifest.csv`, `reports/phase8/input_verification.csv`
- `reports/phase9/phase1_8_dependency_manifest.csv`, `reports/phase9/input_verification.csv`

After the change every row of the five manifests matches the file on disk. The Phase 7, 8 and 9
verification files carry 6, 11 and 14 older snapshot rows that do not match current files; the
same rows mismatch in the committed state before this change, so they are historical and were
left as recorded.

`docs/appendix/phase9_archive_comparison.csv` is a dated record of the Phase 9 archive recovery
and still shows the old hashes; it was not edited.

### Proof that no output changed

1. **DuckDB:** the model was rebuilt with the edited script into a scratch folder. Reconciliation
   45/45 PASS and KPI validation 38/38 PASS; `object_inventory_duckdb.csv`, `generated/` and the
   summary (apart from timings) are byte-identical to `reports/phase4`. The two result CSVs differ
   from the committed copies only in line endings (CRLF written on Windows), the same cause as the
   Windows note in KI-03. `reports/phase4` was not overwritten by this check.
2. **SQL Server:** the governed run was repeated on 2026-10-18 on SQL Server 2025 (17.0.1145.4)
   and passed in 361.5 s: reconciliation 45/45 PASS, KPI validation 38/38 PASS, the eight curated
   inputs verified (`fact_sales` 1,339,510 rows). Its 45 reconciliation and 38 KPI results match the
   DuckDB results check by check: same checks, same statuses, zero numeric difference. This is
   the SQL Server run that `docs/04_data_model_design.md` section 2.3 names as the definitive proof.
3. **Protected hashes:** `tmp/hash_check.py` passes 9/9 groups. Seven groups are unchanged. Two
   changed, and only through the files named in this entry:

| Group | Before | After | Cause |
| --- | --- | --- | --- |
| `freeze_manifests` | 5 files, `344c51d1...` | 5 files, `0b759401...` | the five manifests above |
| `phase1_10_outputs` | 236 files, `41a89031...` | 238 files, `c84a045e...` | the ten manifest files, plus the SQL Server run outputs below |

SQL Server run outputs in `reports/phase4` (replaced by the passing run):
`run_summary_mssql.json` (`passed: false` to `passed: true`), `run_log_mssql.csv`,
`object_inventory_mssql.csv`, `phase4_build_report_mssql.md`, and two files the failed run never
reached: `reconciliation_results_mssql.csv` and `kpi_validation_mssql.csv` (236 to 238 files).
`generated/recon_expected_values.sql` was rewritten by the run with identical bytes.

4. **Tests:** the full suite was run on an isolated copy of the changed project (548 tests): 515 passed,
   4 failed, 29 skipped, 0 errors, the same result and the same four failures as the run before this
   change. The failures are unrelated: `test_assets_and_reports_are_reproducible` is the Windows
   line-ending failure listed in the README (KI-03), and three `tests/test_phase9_monitoring.py`
   tests expect the interpreter environment at `.venv/` under the project root, which the isolated
   copy did not have. The 29 skips need the generated sample or evaluation-only data.

---

## KI-06 Three Phase 9 tests fail when the environment is outside the project root

**Status:** open; no code changed, analysis unaffected
**Found:** full test run on an isolated copy, 2026-10-18
**Files:** `src/monitoring/access.py` (`is_environment_read`, line 74), `tests/test_phase9_monitoring.py`

### What happens

With the virtual environment outside the project folder, as README Step 2 recommends (see KI-04),
three tests fail on Windows:

| Test | Effect |
| --- | --- |
| `tests/test_phase9_monitoring.py::test_environment_import_reads_are_not_false_positives` | `.venv/Lib/site-packages/...` paths are not recognised as environment reads |
| `tests/test_phase9_monitoring.py::test_a_pyc_suffix_alone_never_grants_exemption` | same cause |
| `tests/test_phase9_monitoring.py::test_classify_opened_keeps_project_violations_and_splits_runtime_reads` | the `.venv` read stays in `refused` instead of moving to `runtime_reads` |

### Cause

`is_environment_read` resolves each path against the project root (`PROJECT_ROOT / rel`) and
accepts it only if it falls inside the active interpreter environment (`sys.prefix`,
`sys.base_prefix`, `sys.exec_prefix`). The tests use fixed paths such as
`.venv/Lib/site-packages/duckdb/__pycache__/_version.cpython-314.pyc`, so they pass only when the
active environment is `.venv/` inside the project. With the environment elsewhere, those paths are
not inside it and the function correctly returns False.

### Impact

None on the analysis. The function is used by the Phase 6, 8 and 9 runners to move interpreter
library reads out of the refused list. With the environment outside the project, no library read
falls under the project root, so there is nothing to move, and every project-data refusal is kept
as before. Only the tests' assumption about where the environment lives is affected. The
environment location therefore trades KI-04 (environment inside: Phase 5 and Phase 7 open audits
fail) against this entry (environment outside: these three tests fail).

### Resolution

None yet. A fix belongs in the tests (build the paths from the active `sys.prefix` instead of a
fixed `.venv/`), not in the frozen runners. Until then, the expected Windows result with the
environment outside the project is 515 passed, 29 skipped and 4 known failures (this entry and
KI-03).

---

## KI-07 BigQuery build: what differs from the SQL Server and DuckDB builds

**Status:** open, by design; the BigQuery build passes every check (45/45, 38/38, H1 and H2 2025)
**Found:** first BigQuery build, 2026-10-25
**Files:** `src/bigquery_model/` (new), `config/bigquery_config.yaml`, `docs/bigquery_engine.md`,
`reports/bigquery/` (no Phase 1 to 10 file, manifest or frozen script changed)

The optional BigQuery engine builds the same star schema from the same verified curated files and
reconciles it with the same criteria. Its results match the other two engines, with the differences
below.

### Values that are not bit-identical

Of 166 reconciliation and KPI validation values compared with the committed DuckDB and SQL Server
results, 160 are identical and 6 differ by floating-point rounding only: `asp` by 3.6e-15 and
`promo_revenue_share` (in the reconciliation and the KPI validation) by 2.8e-17, against each engine.
Both are ratios computed in FLOAT; the tolerance is 0.000001, so every check passes on every engine.
Every money total, row count, the H2 2025 figure EUR 9,457,457.05 (-7.18%) and the H1 2025 figure
EUR 8,629,984.78 (+1.438%) are identical across the three engines.

### SQL Server behaviour not reproduced

- Keys, constraints and columnstore indexes (scripts 05 and 06) and the `THROW` that stops a failed
  SQL Server build are not executed, as on DuckDB. BigQuery does not enforce keys; the runner applies
  the pass criteria from the same reconciliation views instead.
- No DML: the project is a BigQuery sandbox (no billing account), so every `INSERT` is rebuilt as
  `CREATE OR REPLACE TABLE ... AS SELECT` and data arrives by load jobs. Rules R5, R6 and R14 in
  `docs/bigquery_engine.md` keep the T-SQL meaning, including the UNKNOWN-member guard.
- Sandbox tables expire after 60 days; rebuild or tear down with `src.bigquery_model.run_bigquery`.

### Dialect difference found during the build (fixed in the translation, not in the scripts)

The curated `transaction_time` values are text in `HH:MM` form. SQL Server and DuckDB convert them to
`TIME`; BigQuery's cast requires seconds and returned NULL for every sales line, so the
`conversion_failures` check reported 1,339,510 on the first complete build. Rule R11 now reads `HH:MM`
explicitly, and the check returns 0. The Phase 4 scripts were not changed.