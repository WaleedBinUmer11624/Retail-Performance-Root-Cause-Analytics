# Phase 8 validation report: business action plan and decision framework

Run: 2026-09-28T17:19:55 | headline engine: duckdb | runtime 17.8 s | overall: **PASS** (114 of 114 checks)

## Freeze

289 Phase 1-7 files match the manifest recorded at the start of Phase 8 (`phase1_7_input_manifest.csv`); the Phase 7 manifest (Phase 1-6) and the Phase 6 manifest (Phase 1-5) were re-verified in the same run. Per-file result: `input_verification.csv`.

## Headline

Recomputed from the Phase 4 model with a plain SQL sum over the Power BI source views:

| Period | Sales revenue | Returns | Net revenue |
|---|---:|---:|---:|
| H2 2024 | 10,557,440.91 | 368,713.36 | 10,188,727.55 |
| H2 2025 | 9,840,827.88 | 383,370.83 | 9,457,457.05 |

Change -731,270.50; YoY -7.177251%. Required: H2 2024 10,188,727.55; H2 2025 9,457,457.05; change -731,270.50; YoY -7.177251%.

## Checks by group

| Group | Checks | Passed |
|---|---:|---:|
| Freeze | 1 | 1 |
| Headline | 9 | 9 |
| Attribution | 14 | 14 |
| Brief figures | 13 | 13 |
| Evidence | 22 | 22 |
| Promotions | 2 | 2 |
| Residual | 3 | 3 |
| KPIs | 9 | 9 |
| Impact | 10 | 10 |
| Actions | 14 | 14 |
| Decision rule | 3 | 3 |
| Data | 5 | 5 |
| Owners | 1 | 1 |
| Early warning | 3 | 3 |
| Traceability | 4 | 4 |
| Style | 1 | 1 |

Failures: none.

Full list: `phase8_validation_checks.csv`.

## Traceability

117 facts are used in the outputs, each read from a frozen Phase 5, 6 or 7 file (`phase8_fact_register.csv`: file, row and column, evidence tag). The configuration holds no typed figure; a check scans it.

## Outputs

- `phase8_action_register.csv`: 25 rows
- `phase8_30_60_90_plan.csv`: 22 rows
- `phase8_kpi_monitoring_framework.csv`: 20 rows
- `phase8_evidence_to_action_matrix.csv`: 13 rows
- `phase8_decision_log_template.csv`: 8 rows
- `phase8_data_requirements.csv`: 36 rows
- `phase8_early_warning_requirements.csv`: 8 rows
- `phase8_decision_framework.csv`: 7 rows
- `phase8_prioritisation_matrix.csv`: 7 rows
- `phase8_impact_framework.csv`: 7 rows
- `phase8_impact_scenarios.csv`: 3 rows
- `phase8_investigation_frameworks.csv`: 55 rows
- `phase8_executive_action_plan.md`
- `figures/phase8_prioritisation_grid.png`

## Independence

Files opened during the run: 130 project files; refused: 0. No evaluation-only or answer-key file was opened (audit hook).
