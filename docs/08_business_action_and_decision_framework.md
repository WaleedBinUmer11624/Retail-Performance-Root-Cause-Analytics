# Phase 8: Business Action Plan, Decision Support and Impact Framework

| Item | Detail |
|---|---|
| Project | Retail Performance & Root-Cause Analytics System |
| Company | Brightwater Retail Ltd (fictional, synthetic data) |
| Author | Waleed Bin Umer |
| Version | 1.0 (awaiting Phase 8 sign-off) |
| Date | 28 September 2026 |
| Inputs | Frozen Phase 1 to 7 outputs (289 files under checksum) |
| Code | `src/actions/`, `config/action_config.yaml`, `tests/test_phase8_actions.py` |
| Outputs | `reports/phase8/` (executive action plan, 12 management tables, fact register, validation report, one figure) |

---

## 0. What this phase is and is not

Phase 8 turns the validated root-cause investigation into a management decision process: what we know, what is uncertain, what can safely be done now, what must be investigated first, who owns it, how progress is measured and when it is reviewed.

It is **not** a new analysis. No figure is recomputed and no evidence level is changed. Every number in the outputs is read from a frozen Phase 5, 6 or 7 file, and the configuration that holds the wording contains no typed figure (a check scans it). It does not depend on the Power BI Desktop build (Phase 7A), which is being validated separately: it uses only the Phase 7 results that were reconciled in Phase 7 (the number register and validation checks), never a PBIX result.

The movement the phase completes is DATA → INSIGHT → EVIDENCE → **DECISION → ACTION → MEASUREMENT**.

## 1. Audience and deliverables

Written for the Head of Retail, Commercial Director, Finance Director, Supply Chain Manager, Trading Manager, Operations Manager and Data/BI Lead. Every recommendation answers: what happened, what evidence supports it, why it matters, what we can safely do, what we must investigate, who owns it, how we measure it and when we review it.

| File (`reports/phase8/`) | What it is |
|---|---|
| `phase8_executive_action_plan.md` | The management document: one-page position, priorities, issue-by-issue framework, investigation frameworks, 30/60/90 plan, KPIs, early warning, impact treatment, evidence controls, decision log, data needs, limitations |
| `phase8_action_register.csv` | 25 actions: category, type, evidence basis, proposed owner, KPI, trigger, timing, effort, reversibility |
| `phase8_30_60_90_plan.csv` | 22 dated activities with deliverables and decision gates at days 60 and 90 |
| `phase8_kpi_monitoring_framework.csv` | 20 KPIs: definition, purpose, owner, frequency, threshold concept, source, availability, whether it exists in the project, current values where they exist |
| `phase8_evidence_to_action_matrix.csv` | 13 findings: evidence level, interpretation, permitted and not-permitted conclusions, next step |
| `phase8_decision_log_template.csv` | The decision log with its 13 fields and the first 8 proposed decisions (dates and results left empty) |
| `phase8_data_requirements.csv` | 36 data items, the question each answers, the issue it serves, proposed owner, availability, when it is needed |
| `phase8_early_warning_requirements.csv` | 8 signals specified for a later monitoring phase (concepts, not calibrated thresholds) |
| `phase8_decision_framework.csv` | The 16-field decision framework for each of the 7 issues |
| `phase8_prioritisation_matrix.csv` | Ratings, their reasons and the rule that gives each issue its category |
| `phase8_impact_framework.csv`, `phase8_impact_scenarios.csv` | Observed vs estimated vs recoverable, and the only scenarios (stock-outs) with their assumptions |
| `phase8_investigation_frameworks.csv` | Cluster investigation sequence, inventory checks, returns classification, promotion framework and test design, residual dimensions |
| `phase8_fact_register.csv` | Every fact used: value, file, row and column, evidence tag |
| `phase8_validation_report.md`, `phase8_validation_checks.csv` | Freeze, headline and governance checks |
| `figures/phase8_prioritisation_grid.png` | One figure: evidence strength against financial relevance, with the decision category |

## 2. Inputs and freeze

At the start of the phase, `python -m src.actions.run_phase8 --record-freeze` recorded SHA-256 checksums of the 289 Phase 1 to 7 files (`reports/phase8/phase1_7_input_manifest.csv`): the 170 files frozen for Phase 7 plus the Phase 7 code, SQL views, configuration, design document, tests, CSV outputs, mockups and the `powerbi/` build kit. The Phase 7 validation report and run log are excluded because they record run times, as the earlier phases excluded theirs.

Every run verifies the manifest, then the Phase 7 manifest (Phase 1 to 6) and through it the Phase 6 manifest (Phase 1 to 5). Any change stops the run. The run then recomputes the headline from the Phase 4 model with a plain SQL sum over the Power BI source views: H2 2024 €10,188,727.55, H2 2025 €9,457,457.05, change -€731,270.50, YoY -7.177251%. It matches the brief, Phase 4, 5, 6 and the Phase 7 register exactly.

Phase 8 opens files only through a whitelist (`src/actions/access.py`), and an audit hook records every file opened; no evaluation-only or answer-key file is opened.

## 3. How numbers enter the outputs

`src/actions/facts.py` builds a fact base of 161 facts. Most are entries of the Phase 7 dashboard number register (which itself traces each number to a DAX measure or a frozen Phase 5/6 cell); the rest are named cells of frozen Phase 6 and Phase 5 files. A handful are derived by simple arithmetic and say so (for example the demand that came back after restock is the gross lost-sales estimate minus the net estimate).

The wording lives in `config/action_config.yaml` and refers to facts with placeholders such as `{d01_eur|eur}`. Rendering replaces each placeholder with the formatted fact and records which facts each table used. Three checks keep this honest: the configuration holds no typed euro amount, percentage or large count; every euro amount in any output is a formatted fact; no placeholder is left unresolved.

## 4. The decision framework

### 4.1 Issues

The seven issues follow the Phase 6 drivers, grouped as management would ask about them:

| Issue | Phase 6 drivers | Evidence (Phase 6, unchanged) |
|---|---|---|
| I1 Store-cluster transaction loss (S03, S04, S05) | D01, D02 | Observed change; Hypothesis. Cause UNRESOLVED |
| I2 Electronics & Tech full-week stock-outs | D03 | Root-cause evidence for lost sales during full-week stock-outs only; why stock ran out is not established (I3) |
| I3 Voltix stock-out concentration (supply vs ordering) | D04 | Statistical association; supplier responsibility not established |
| I4 Electronics & Tech 'Faulty' returns | D05, D06 | Observed change (FACT); product defect is a Hypothesis |
| I5 Home & Kitchen promotions | D07 | Statistical association; the four methods disagree in sign |
| I6 Electronics & Tech range and continuing-SKU sales | D08 | Observed change (a partition); SKU switching is a Hypothesis |
| I7 Residual | D09 | UNEXPLAINED / NOT ATTRIBUTED |

Each issue carries the 16 fields the brief asks for: issue, observed evidence, financial relevance, evidence level, what we know, what we do not know, business risk, immediate safe action, investigation required, additional data required, proposed owner, supporting teams, KPI to monitor, trigger/escalation, review frequency, decision after investigation.

### 4.2 Ratings

Eight dimensions, each High / Medium / Low with a written definition. No score is calculated: the ratings are never added or multiplied, which would create false precision.

- **Computed from frozen results:** financial relevance (share of the H2 change in the Phase 6 attribution: High from 20%, Medium from 5%) and evidence strength (the Phase 7 causal-evidence scale: root-cause evidence High, statistical association Medium, observed change or hypothesis Low).
- **Judgements, labelled PROPOSED, each with a reason:** business urgency, implementation effort, reversibility, data requirement, risk of acting now, time to validate.

A slice (I3 is part of I2) uses its own amount and is flagged as not additional; a partition (I6) is "Not quantified" and the rule treats it like Low.

Because six of the eight ratings are judgements, the categories depend on them. Reversibility is High for every issue (every immediate action can be stopped at no cost), so it does not separate issues. The prioritisation matrix therefore shows, for each issue, which single judgement would change its category (column `pivotal_judgements`): for example I6 would become INVESTIGATE FIRST if its urgency or risk of acting were rated High, and I4 would drop to MONITOR if its urgency were not High. Management can challenge exactly those ratings.

### 4.3 The decision rule

Applied in `src/actions/framework.py`, repeated in the outputs and tested:

1. No identified driver (the amount is not attributed): **NO ACTION YET** beyond analysis.
2. High causal evidence, reversible immediate actions and low risk of acting: **ACT NOW**.
3. Financial relevance High or Medium, or urgency High, or high risk of acting on the wrong cause: **INVESTIGATE FIRST**.
4. Otherwise: **MONITOR**.

The result: I2 is ACT NOW; I1, I3, I4 and I5 are INVESTIGATE FIRST; I6 is MONITOR; I7 is NO ACTION YET. Financial relevance appears in rule 3, so size can make an issue worth investigating; it can never make an issue ACT NOW, which needs root-cause evidence. The largest amount (I1, 54% of the decline) is therefore investigated, not acted on, because its cause is unknown (a test checks this).

### 4.4 Actions

Every action has a category, a type and an evidence basis (the Phase 6 driver and level). The types keep the categories honest:

- **Control** (operational): only where the evidence is root-cause evidence (I2: the zero-stock exception list and the reorder-point review).
- **Governance control:** sensible whatever the cause (the Home & Kitchen promotion objective-and-review rule; the decision log itself).
- **Evidence capture:** preserves evidence that would otherwise be lost (holding 'Faulty' returns for inspection with batch capture).
- **Investigation, Monitoring, Analysis.**
- **Hold:** a deliberate decision not to act yet, recorded in the decision log: no price or marketing response aimed at S03 to S05 until a cause is known; no sanction against Voltix before the order and delivery review; no blanket change to Home & Kitchen promotion depth on the strength of any one method.

The issue category is what management decides about the problem; each action inside an issue has its own category. One rule governs action-level ACT NOW, stated identically in the plan: an action can be ACT NOW, even inside an INVESTIGATE FIRST issue, only if it is reversible, low effort and low risk, and it is an operational control resting on root-cause evidence (only I2 qualifies), evidence capture that would otherwise be lost, or a governance control that changes no commercial lever (tested). So I4's evidence capture (A13) and I5's governance control (A18) are ACT NOW while I4 and I5 themselves are INVESTIGATE FIRST.

## 5. Investigation frameworks

- **Store cluster (I1):** a six-step sequence, cheapest first: is the receipt loss real (POS completeness against payment settlement); did the stores change (hours, closures, staffing, works); fewer visitors or fewer buyers (footfall and conversion, which can only be split for the July step where counters with history exist; otherwise proxies are used for the past and new counters measure only the present); did the local environment change (competitors, access, events); where did customers go (feedback, loyalty, online); then a day-60 decision that either names a cause with its evidence level or keeps it UNRESOLVED. No cause is assumed at any step.
- **Electronics inventory (I2, I3):** eleven checks (purchase orders, confirmations and ASNs, fill rate, OTIF, lead times and late deliveries, order quantity against parameters, forecast accuracy, reorder points and safety stock, DC availability, store replenishment and allocation, supplier service levels), each stating what would point to supply and what would point to Brightwater's ordering.
- **'Faulty' returns (I4):** a classification framework for product quality, specific batch, supplier issue, classification behaviour, store process, customer behaviour and another cause, with the evidence that would support or count against each. None is selected without that evidence. Returns are held for inspection in the five stores and in three comparison stores, so the defect rate is judged against a normal no-fault-found rate.
- **Home & Kitchen promotions (I5):** incrementality, cannibalisation, pull-forward, baseline selection, margin impact, basket attachment, customer segment, promotion objective, control groups, elasticity and post-promotion behaviour, each with what we have now and how to measure it; and a controlled test design. Only unadvertised in-store mechanics vary (nationally advertised prices stay the same everywhere), with marketing and legal sign-off; stores that share customers go to the same arm; S03 to S05 are excluded; the comparison arm runs the prior-year depth rather than no promotions; a time switchback is the fallback if store numbers are too small; one promotion cycle plus a post-period; analysis plan written before launch; guardrails; a power check. The result arrives after day 90, so the depth decision is taken at a post-test gate (planned around day 150 to 180), and an inconclusive result keeps the current depth under the governance control rather than triggering a cut.
- **Residual (I7):** ten dimensions (store, category, product, week, price, mix, returns, availability, customer behaviour, data quality). The residual stays UNEXPLAINED / NOT ATTRIBUTED unless a new driver meets the Phase 6 evidence standard.

## 6. Measurement

**KPIs.** Twenty KPIs, each with definition, business purpose, proposed owner, frequency, threshold concept, data source, availability and whether it already exists in the project (most are Phase 7 DAX measures). Current values are shown only where the project holds them. Footfall, conversion rate, confirmed-defect rate, promotion incrementality, supplier OTIF, supplier fill rate and forecast accuracy are marked Not available and carry no value. The lost-sales estimate is shown as an analysis ESTIMATE, not a routine KPI.

**Early warning.** Eight signals (store and estate transaction deterioration, availability deterioration, stock-out spikes on top sellers, return-rate increases by reason, margin deterioration, unusual promotion behaviour, data completeness), each with metric, grain, baseline concept, threshold concept, frequency, proposed owner, alert recipient and required response. No threshold is set: each must be back-tested for false alarms and detection delay in the monitoring phase. This is the specification for that phase; no forecasting is built here.

## 7. Business impact

Three columns are kept apart for every issue: **observed historical impact** (FACT), **estimated historical impact** (ESTIMATE, with its range) and **potential recoverable value**. The third is "Not estimated" for every issue except I2, the only one with a known mechanism, which has "Scenario only".

The I2 scenarios restate the H2 2025 estimate under stated assumptions (how much of that half-year's loss would have been avoided). They describe the past only, are rounded, and are in sales before the cost of holding more stock:

| Scenario | Illustrative value (H2 2025) | Main assumption |
|---|---|---|
| Conservative | €0 | Nothing is treated as avoidable until the order data shows the cause was within Brightwater's control and the controls show a measured effect |
| Full elimination (best case) | about €24k | Every full-week stock-out removed; only demand that did not come back after restock counts (€13k came back and is already in H2 2025 revenue) |
| Upper: not provided | n/a | The gross estimate and the sensitivity high include demand that came back after restock, and the partial-week upper bound is not evidence, so none of them is avoidable value |

They are labelled SCENARIO, not a forecast and not a target. A €37,235 historical lost-sales estimate does not mean an intervention will produce €37,235. For the other issues the reason is stated: the cause is unknown (I1), the methods disagree in sign (I5), a verified defect would at most support supplier cost claims, not revenue (I4), or there is no driver (I6, I7).

## 8. Governance

- **Evidence-to-action matrix:** for each finding, the permitted conclusion and the conclusion that is not permitted. Examples: full-week stock-outs caused lost sales (permitted), the supplier failed (not permitted without purchase order and ASN evidence); promotion activity is associated with the Home & Kitchen decline (permitted), promotions caused it or the four methods summed (not permitted).
- **Decision log:** decision ID, date, issue, evidence reviewed, evidence level, decision, owner, expected outcome, KPI, review date, status, result, learning. The first eight entries are proposed decisions; dates, results and learning are left empty for management.
- **Monthly evidence review** chaired by the Data/BI Lead; decision gates at day 60 (cluster cause, supply vs ordering, defect vs recording), day 90 (the Home & Kitchen governance control and promotion hold, next period's investigation list) and a post-test gate planned around day 150 to 180 (promotion depth).
- **Owners** are labelled PROPOSED everywhere: they are not findings of the analysis.

## 9. Validation

`python -m src.actions.run_phase8 --engine duckdb` verifies the freeze, recomputes the headline, builds the outputs and runs the checks (`phase8_validation_report.md`). The groups:

- **Freeze and headline:** 289 files unchanged; headline recomputed from the model and read from the Phase 7 register, both equal to the brief.
- **Attribution:** components sum to -€731,270.50, shares to 100%; each component rounds to the brief's figure; the residual keeps its size.
- **Evidence:** every driver's evidence level and cause status unchanged from Phase 6; every level shown in the outputs equals the matrix; a claim scan finds no sentence stating a hypothesis or association as a finding; the required promotion wording is present.
- **Promotions:** no sum or average of any combination of the four methods appears anywhere.
- **Residual:** NO ACTION YET, labelled NOT ATTRIBUTED, no recoverable value.
- **KPIs:** unavailable KPIs carry no value; no threshold is calibrated.
- **Impact:** recoverable value is never a historical figure; scenarios only for I2, with assumptions, not forecasts; the conservative scenario is zero; no scenario counts demand that came back after restock, and the gross, sensitivity-high and upper-bound figures are never offered as avoidable value.
- **Actions and rule:** every action has an evidence basis; ACT NOW actions meet their conditions; every issue's category follows the rule; the largest amount is not ACT NOW.
- **Data, owners, early warning, traceability, style:** every unresolved issue names data; every owner is PROPOSED; every signal is fully specified and uncalibrated; every euro amount traces to a fact; no em dash.

`tests/test_phase8_actions.py` runs the same checks and adds independent ones (see section 10).

## 10. Independent review

An adversarial review by a separate agent that had not seen the work being produced looked for causal overstatement, unsupported recommendations, invented financial benefits, double counting, fake precision, unrealistic retail actions, confusion between historical loss and recoverable value, and hypotheses written as findings. It reported 30 findings (1 Critical, 12 Major, 17 Minor). All were addressed and the checks rerun; the findings, the fixes and what was verified as correct are in `reports/phase8/phase8_independent_review.md`.

## 11. Limitations

- Every number describes H2 2025 against H2 2024 in synthetic data. Nothing is a forecast.
- Owners, judgement ratings, timings and threshold concepts are proposals for management.
- Seven KPIs and most of the 36 data items do not exist in the project; the plan names them and does not estimate them.
- The promotion test has few stores to work with and can detect only large effects, and its result arrives after day 90; the design says how to handle both.
- The claim scan is a guard against wording drift, not a proof: the evidence-to-action matrix and the review are the main controls.

## 12. Reproducibility

```
python -m src.actions.run_phase8 --engine duckdb    # about 25 s: freeze, headline from the model, outputs, checks
python -m src.actions.run_phase8                    # headline from the SQL Server model
python -m pytest tests/test_phase8_actions.py
```

## 13. Interview readiness

**What did Phase 8 add?** It turned a root-cause analysis into decisions: what to do now, what to investigate, what to hold, who owns it and how it is measured, with the evidence level carried into every decision.

**How did you decide priorities?** With a documented rule in which size can make an issue worth investigating but only root-cause evidence can make it ACT NOW; the judgement ratings behind each category, and which one would change it, are shown so management can challenge them. The largest component (the store cluster, 54% of the decline) is investigated first, not acted on, because its cause is unknown. Only the stock-out mechanism, which has root-cause evidence, gets immediate operational controls.

**How did you avoid inventing benefits?** Historical impact, estimated impact and recoverable value are separate columns. Recoverable value is not estimated unless the mechanism is known, and the one set of scenarios starts at zero, never counts demand that came back after restock, and restates the past rather than forecasting.

**What would you do on day one?** Confirm the S03 to S05 receipt loss is real, start the zero-stock exception list for the fastest-selling Electronics SKUs, hold 'Faulty' returns for inspection (with comparison stores), and request the order, delivery and footfall data. Then hold anything that would spend money on a guessed cause.
