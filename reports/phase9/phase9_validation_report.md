# Phase 9 validation report: monitoring, early warning and anomaly detection

Run: 2026-09-29T04:57:15 | engine: duckdb | runtime 47.8 s | overall: **PASS** (21 of 21 checks)

## 1. Freeze

324 Phase 1-8 files (and the four Phase 3 DQ audit files Phase 9 reads) match the dependency manifest recorded at the start of Phase 9 (`phase1_8_dependency_manifest.csv`). The Phase 8, 7 and 6 manifests were re-verified in the same run. Per-file result: `input_verification.csv`.

| Phase | Files | Status |
|---|---|---|
| Phase 1-4 | 34 | all UNCHANGED |
| Phase 3 DQ audit | 4 | all UNCHANGED |
| Phase 5 | 50 | all UNCHANGED |
| Phase 6 | 86 | all UNCHANGED |
| Phase 7 | 119 | all UNCHANGED |
| Phase 8 | 31 | all UNCHANGED |

## 2. Reconciliation of the monitoring layer to Phases 4-7

21 of 21 checks pass (`reconciliation_checks.csv`). The monitoring views (`sql/monitoring/01_monitoring_views.sql`) read only the Phase 4 star schema and reproduce the governed totals exactly:

| Check | Status |
|---|---|
| H2 2024 net revenue (monitoring layer) = approved headline | PASS |
| H2 2025 net revenue (monitoring layer) = approved headline | PASS |
| H2 change = approved headline | PASS |
| Weekly estate net revenue 2025, all 52 weeks: max difference to Phase 5 | PASS |
| Weekly estate transactions 2025, all 52 weeks: max difference to Phase 5 | PASS |
| Weekly estate net revenue 2024 (PY weeks): max difference to Phase 5 | PASS |
| Electronics & Tech H2 2025 net revenue = Phase 5 | PASS |
| Electronics & Tech H2 2025 availability = Phase 5 | PASS |
| Electronics & Tech H2 2024 availability = Phase 5 | PASS |
| Electronics & Tech H2 2025 gross margin = Phase 5 | PASS |
| Home & Kitchen H2 2025 net revenue = Phase 5 | PASS |
| Home & Kitchen H2 2025 availability = Phase 5 | PASS |
| Home & Kitchen H2 2024 availability = Phase 5 | PASS |
| Home & Kitchen H2 2025 gross margin = Phase 5 | PASS |
| E&T full-week stock-outs H2 2025 = Phase 6 (all suppliers) | PASS |
| E&T full-week stock-outs H2 2024 = Phase 6 | PASS |
| E&T 'Faulty' refunds H2 2025 = Phase 6 | PASS |
| E&T 'Faulty' refunds H2 2024 = Phase 6 | PASS |
| Home & Kitchen H2 2024 discount rate = Phase 7 register (P5-09) | PASS |
| Home & Kitchen H2 2025 discount rate = Phase 7 register (P5-10) | PASS |
| S03-S05 transactions YoY H2 = Phase 7 register (P2-01) | PASS |

## 3. Validation checks

| ID | Check | Status | Detail |
|---|---|---|---|
| V01 | Phase 1-8 files unchanged since the Phase 9 freeze | PASS | 324 files |
| V02 | Monitoring KPIs reconcile to Phases 4-7 | PASS | 21/21 |
| V03 | alert_id is unique | PASS | 949 alerts |
| V04 | Every alert has a valid severity and lifecycle status NEW | PASS |  |
| V05 | DQ gate: held alerts are capped at WATCH and no store alert above WATCH in a failed store-week | PASS | 41 held |
| V06 | EW08 alerts are exactly the failed store-weeks | PASS | S13 202442, S16 202551, S16 202552 |
| V07 | Required wordings used (EW01 cause wording, EW05 faulty-return wording) | PASS |  |
| V08 | No causal, defect or supplier-blame wording and no em dash in alerts and reports | PASS |  |
| V09 | No fabricated management responses (owner, acknowledged, resolved all empty) | PASS |  |
| V10 | Owners are proposed roles | PASS |  |
| V11 | Every selected rule, the secondary change-point rule and each rule as operated stay inside the budget | PASS | EW01/store 1.99% (operated 1.99%); EW02/estate 0.00% (operated 0.00%); EW02/format 0.93% (operated 0.93%); EW02/region 1.04% (operated 1.55%); EW03/category 0.8 |
| V12 | Selection reads only the noise budget: scrambling every detection metric (delay, coverage, exposure) gives the same rules (the episode mask's own effect is reported in selection_mask_sensitivity.csv) | PASS |  |
| V13 | No leakage: perturbing later weeks leaves earlier baselines, z-scores and change-point statistics unchanged | PASS |  |
| V14 | Week alignment: every alert is on a complete retail week; business alerts in 2025 (the year with a prior year) | PASS |  |
| V15 | Prior-year logic: each 2025 week maps to the same retail week of 2024 | PASS |  |
| V16 | Exposure is never totalled across signals (no all-signal total in any output) | PASS |  |
| V17 | S03, S04 and S05 each detected by the operational EW01 rule | PASS | S03 2025-W31; S04 2025-W33; S05 2025-W33 |
| V18 | Ten figures written | PASS |  |
| V19 | No evaluation-only or refused path opened | PASS |  |
| V21 | Stock-out context reproduces Phase 6 supplier figures (Voltix full-week stock-outs and availability) | PASS | Voltix full-week stock-out cells H2: 0 -> 674 |
| V20 | Lifecycle has the seven required statuses | PASS |  |

## 4. Back-test design

* **As-at replay.** Each retail week is evaluated as the Monday 06:00 run would have seen it: lines whose extract timestamp is later than the run are excluded (`*_ontime` columns). S16's 2025-W51/W52 sales, delivered on 2026-01-09, therefore appear as missing and fail the gate. Returns and stock snapshots carry no arrival time and are taken at final values.
* **Walk-forward baselines.** Every baseline for week t uses weeks before t only; test V13 perturbs all later weeks and confirms the earlier baselines, z-scores and change-point statistics do not move.
* **Selection.** One rule per signal and grain: the first family in interpretability order with a candidate whose unconfirmed WARNING rate is within 2% of non-episode entity-weeks; the smallest compliant threshold, then the shortest persistence (2 weeks minimum for WARNING). Detection delay, coverage and exposure on the known episodes are never read (test V12 scrambles them and gets the same rules). The known episodes DO shape the selection through the noise mask: their weeks are not counted as noise. `selection_mask_sensitivity.csv` re-runs the selection with no mask; 8 of the 12 grains would get a stricter rule. The EW02 estate budget cannot be measured (20 non-episode weeks: one alert is 5%).
* **Secondary rule (EW01).** The Phase 8 change-point test is selected the same way (the most sensitive candidate inside the budget) and raises WARNING on its own; the rule as operated, both together, is checked against the budget again (V11).
* **Known episodes** are the issues Phases 5 and 6 established (config `episodes`). They label alerts, measure detection after selection and, through the noise mask, decide which weeks count as noise. They come from the same period, so detection results are in-sample.

## 5. Selected rules and their back-test

| Signal | Grain | Rule | Alerts | Unconfirmed | Rate | Known entities detected | Median delay (weeks) |
|---|---|---|---|---|---|---|---|
| EW01 | store | peer_gap_threshold: 10, 3 wk | 64 | 16 | 1.99% | 3/3 | 5 |
| EW02 | estate | yoy_vs_trend_threshold: 3, 2 wk | 8 | 0 | 0.00% | 1/1 | 0 |
| EW02 | format | yoy_vs_trend_threshold: 5, 3 wk | 9 | 1 | 0.93% | 1/1 | 4 |
| EW02 | region | yoy_vs_trend_threshold: 10, 3 wk | 9 | 2 | 1.04% | 1/1 | 7 |
| EW03 | category | availability_gap_pp: 1, 2 wk | 20 | 3 | 0.87% | 1/1 | 1 |
| EW03 | supplier | availability_gap_pp: 1, 2 wk | 31 | 13 | 1.71% | 1/1 | 1 |
| EW04 | product | stores_out_count: 1, 2 wk | 71 | 0 | 0.00% | 7/9 | 3 |
| EW05 | category | binomial_excess: p<0.05, excess>=3, 2 wk | 19 | 3 | 1.03% | 1/1 | 1 |
| EW05 | store | binomial_excess: p<0.05, excess>=3, 2 wk | 59 | 1 | 0.13% | 5/5 | 2 |
| EW06 | category | margin_gap_pp: 1, 4 wk | 36 | 3 | 1.17% | 2/2 | 5.5 |
| EW07 | category | discount_gap_pp: 5, 3 wk | 15 | 2 | 0.63% | 1/1 | 5 |
| EW08 | store | dq_gate_fail: gate FAIL, 1 wk | 3 | 0 | 0.00% | 2/2 | 0 |

Grains that missed part of a known episode at the selected rule: EW04 product. This is reported, not tuned away.

Baseline settings (`baseline_setting_sensitivity.csv`, 8 alternatives to the configured one): EW01 detects the cluster under 8 of 8; EW02 format misses the Standard-format movement under 3 (hold release 2 weeks, release z -0.5, no freeze).

## 6. S03-S05 detection

| Store | Change point | First WARNING | Delay | Severity then | First CRITICAL | Active after onset | Active in final week |
|---|---|---|---|---|---|---|---|
| S03 | 2025-W29 | 2025-W31 | 2 | CRITICAL | 2025-W31 | 92% | yes |
| S04 | 2025-W28 | 2025-W33 | 5 | CRITICAL | 2025-W33 | 68% | no |
| S05 | 2025-W30 | 2025-W33 | 3 | CRITICAL | 2025-W33 | 87% | yes |

Cause not established from available internal data.

## 7. Outputs

Hashes of the main outputs (a second run with the same inputs gives identical files; see the determinism test):

* `weekly_alerts.csv`: `1249cfa3377ebe8f...`
* `alert_summary.csv`: `2d48f71f221866fb...`
* `alert_backtest_results.csv`: `87a984fdf60a9b0b...`

## 8. Files opened

155 project files were read during the run; none is an evaluation-only file (refused paths opened: 0).
