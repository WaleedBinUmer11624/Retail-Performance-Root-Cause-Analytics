# Phase 9: Operational Monitoring, Early Warning and Anomaly Detection

Phase 9 of the Retail Performance & Root-Cause Analytics System (Brightwater Retail Ltd, fictional).

Historical diagnosis → Evidence testing → Decision support → Management action planning → Operational early warning

Phases 5 to 8 explained the H2 2025 decline in Net Revenue (EUR 10,188,727.55 to EUR 9,457,457.05, -7.18%) after the
event. Phase 9 answers a forward-looking management question with the same data: **if a similar deterioration started
again, how would management see it early enough to investigate or act?** It turns the eight Phase 8 early-warning
requirements (EW01 to EW08) into governed, back-tested weekly rules, and replays them through 2025 exactly as a Monday
morning run would have seen the data.

This is a design and a back-test. Nothing is deployed to production. No alert was sent to anyone, no management
response is recorded, and owners are proposed roles. There is no forecasting in this phase.

## 1. Business objective

A weekly monitor must answer, for every alert:

| Question | Where the answer is |
|---|---|
| Is trading deteriorating abnormally? | `severity` (WATCH, WARNING, CRITICAL) against a leakage-free baseline |
| Which store, category, product or supplier? | `entity_type`, `entity_id` |
| How large is the deviation? | `actual_value`, `baseline_value`, `variance`, `variance_pct`, `estimated_exposure` |
| How long has it persisted? | `persistence_weeks`, `alert_episode_id` |
| Isolated fluctuation or sustained signal? | persistence rule; WATCH vs WARNING; `false_positive_analysis.csv` |
| Which KPI triggered it? | `signal`, `metric`, `rule` |
| How severe is it and why? | `severity`, `severity_reason` (plain text, rule based) |
| What evidence is available? | `evidence_level` (always "Observed change (monitoring alert)"), `cause_status` ("Not established"), context tables |
| Who should investigate? | `proposed_owner` (PROPOSED role) |
| What extra data is needed? | `data_required` (Phase 8 data requirements) |
| Actionable or investigative only? | `alert_class` in `signal_dictionary.csv` |
| How many false alarms would the rule produce? | `alert_backtest_results.csv`, `threshold_sensitivity.csv`, `false_positive_summary.csv` |

## 2. Architecture

```
Phase 4 star schema (dw, frozen)
   │  sql/monitoring/01_monitoring_views.sql   mon.* weekly views: additive components only, final AND on-time values
   │  sql/monitoring/02_alert_store.sql        mon.signal_rule, mon.alert, mon.alert_status_history (design, empty)
   ▼
src/monitoring/kpis.py        governed weekly KPIs, as-at replay (asat), reconciliation to Phases 4-7 (21 checks)
src/monitoring/dq.py          EW08 DQ gate per store-week (C1-C11, plus C12 for returns history) using dw row flags and the Phase 3 issue log
src/monitoring/baselines.py   walk-forward baselines (robust median/MAD, rolling mean/SD, trailing level, runs)
src/monitoring/signals.py     EW01-EW08 evaluation frames, one boolean column per candidate rule, CUSUM, change point
src/monitoring/backtest.py    back-test of every candidate, noise-budget selection, S03-S05 timing, baseline comparison
src/monitoring/alerts.py      severity, DQ gate, alert table, alert summary, lifecycle
src/monitoring/evaluate.py    operational detection, unconfirmed/isolated/uncorroborated analysis, change-point estimates
src/monitoring/context.py     investigation context: SKU/supplier stock-outs, return concentration, margin, promotions
src/monitoring/figures.py     ten figures;  report.py  executive summary and validation report
src/monitoring/run_phase9.py  one command: freeze check → views → KPIs → DQ → signals → back-test → alerts → outputs
   ▼
reports/phase9/*.csv, figures/, data/ (Power BI-ready extracts), phase9_*.md
```

Run: `python -m src.monitoring.run_phase9 --engine duckdb` (rebuilds the Phase 4 model locally; about 50 seconds) or
without `--engine` against the SQL Server model. The run stops if any Phase 1-8 file changed (324 files in
`reports/phase9/phase1_8_dependency_manifest.csv`) or if the monitoring layer does not reconcile.

**As-at replay.** The weekly run is scheduled for 06:00 on the Monday after each retail week closes. The views keep,
beside every final total, the on-time total built only from lines whose extract timestamp is at or before that run
time. A week is evaluated with its on-time values whenever any of its lines arrived later. This is how the S16 sales
for 2025-W51 and W52, delivered on 2026-01-09, show up in the back-test: as missing on the Monday they would have been
read, which the DQ gate catches. Sales and product-week sales are replayed this way; returns and stock snapshots carry
no arrival time in the source, so they are taken at their final values (a limitation, section 17).

**Reconciliation.** The monitoring layer reuses the governed definitions (Net Revenue = sales revenue - refunds;
COGS = cost - restock credit; Gross Margin = Net Revenue - COGS; transactions = distinct receipts; availability =
in-stock / ranged store-SKU-weeks; full-week stock-out = no opening stock, nothing received, out at the snapshot) and
reproduces the frozen figures exactly: the H2 headline, weekly estate revenue and transactions (Phase 5), category
revenue, availability and margin (Phase 5), E&T full-week stock-outs 0 to 786 and Voltix 0 to 674 (Phase 6), faulty
refunds (Phase 6), the Home & Kitchen discount rate (Phase 5 register) and the S03-S05 transaction change (Phase 6).

## 3. Monitoring KPI layer

`reports/phase9/monitoring_kpi_dictionary.csv` lists 15 KPIs with definition, numerator, denominator, grain,
comparison baseline, required dimensions, data source, refresh expectation and known limitations:
weekly net revenue, transactions, units, UPT, ASP, gross margin EUR, gross margin %, return rate, 'Faulty' rate,
availability, stock-out rate, full-week stock-outs, promotion share, discount rate and data completeness. The SQL views
store only additive sums; every ratio is a ratio of sums computed in Python, never an average of ratios.

## 4. Signals, grains and Phase 8 traceability

The eight Phase 8 signals are all implemented and none is replaced. `signal_dictionary.csv` puts the Phase 8 metric,
grain, baseline and threshold concept beside what was built and states every adaptation.

| Signal | Grain (why) | Metric | Baseline | Phase 8 status |
|---|---|---|---|---|
| EW01 Store transactions | Store-week (stores are the unit a manager can visit; the S03-S05 issue was store level) | Peer gap: log store transactions YoY minus log YoY of all other stores | Store's own trailing 13-week median of valid weeks, pooled MAD scale | Adapted: peers = all other stores (Phase 8 did not define "matched peers"); change-point test as specified |
| EW02 Estate transactions | Estate, region, format week (management totals; store detail is EW01) | log transactions YoY | Own trailing 13-week median, own MAD | Adapted: robust statistic; region and format added |
| EW03 Availability | Category and supplier week (store x SKU is too noisy; buyers act by category and supplier) | in-stock / ranged cells | BOTH same week last year and trailing 8-week mean | As Phase 8; persistence set by back-test (2 weeks) |
| EW04 Top-seller stock-outs | Product week, top 10% of SKUs by trailing 13-week sales (high-value SKUs first) | stores with a full-week stock-out | zero (any full-week stock-out on a top seller) | As Phase 8 concept; weeks of cover needs daily demand (not available) |
| EW05 'Faulty' returns | Store (E&T) and category, trailing 4 weeks (store-month in Phase 8; the brief requires the week) | 'Faulty' units per 100 sold | same 4 weeks last year, conditional binomial test | Adapted grain; supplier, product and store concentration as context |
| EW06 Gross margin | Category, trailing 4 weeks (promotion pulses make single weeks noisy) | GM % (GM EUR beside it) | same 4 weeks last year | As Phase 8 |
| EW07 Promotions | Category, trailing 4 weeks | discount / gross sales | same 4 weeks last year (no approved plan exists) | Adapted as Phase 8 allows until DR29 |
| EW08 Data quality | Store-week gate; C1 checks each trading day | checks C1-C11 | fixed tolerances, trailing 13-week line median, same week last year | Adapted: weekly gate with a day-level check |

Why the 4-week windows for EW05-EW07: Home & Kitchen promotions run in pulses of about three weeks, so a single week
against the same week last year swings with the pulse calendar rather than the underlying behaviour. A 4-week window
compared with the same 4 weeks last year smooths the pulse while still moving within a month.

Where a grain was dropped: store x category margin and store x SKU availability were not given alerts, because at
that grain almost every week is unusual somewhere (noise), and the managers who act on margin and availability work by
category and supplier. Those grains remain visible as drill-through in the dashboard design.

## 5. Baseline methodology

A baseline for week t is built from weeks before t only. A week that failed the DQ gate never enters a baseline. The
baseline options were compared on the same question, EW01 store transactions, like for like: the same 878 store-weeks
(the 2025 weeks where every option exists) and the same rule, at least 15% below the baseline for 2 consecutive weeks
(`baseline_comparison.csv`):

| Baseline | Unconfirmed rate | Active during S03-S05 episode | Stability (SD) | Reading |
|---|---|---|---|---|
| B1 same retail week last year | 2.4% | 82% | 0.15 | Seasonality handled; an estate-wide move hits every store at once (EW02 covers that) |
| B2 trailing 4-week mean of the level | 2.1% | 11% | 0.20 | Blind to seasonality; follows the fall within a month |
| B2 trailing 8-week mean of the level | 1.9% | 14% | 0.23 | Same problem, slower |
| B3 trailing 8-week median of the level | 3.4% | 15% | 0.24 | Robust to one bad week, still blind to seasonality |
| **B4 peer gap vs trailing 13-week median (selected)** | **1.4%** | **60%** | **0.13** | The store against the rest of the estate, against its own normal; guarded and frozen while anomalous |
| B5 peer gap vs trailing 13-week mean, unguarded | 1.0% | 10% | 0.13 | Quiet because the mean absorbs the anomaly: it stops seeing the step |

B4 has the lowest burden among the options that keep seeing a sustained step. B5 looks quieter only because it adopts
the new level, which is exactly what a monitor must not do. Note that this choice of baseline, unlike the threshold
selection, does use detection on a known episode (the "active" column): the reason for preferring B4 is a property
of the method (a mean over a window that includes the anomaly moves towards it), and the episode is the evidence
that this matters in practice.

**How B4 works.** The median of the last 13 valid weeks (at least 8, within 26 weeks); the scale is the median of all
stores' MADs times 1.4826. **Guard:** a week at z -2 or lower (adverse) or +3 or higher is kept out of later
baselines. **Freeze while anomalous** (added after the independent review, finding M3): once a week is at z -2 or
lower, the store's baseline is frozen until 4 consecutive weeks are back above z -1. Without the freeze, the milder
weeks of a long deterioration re-entered the baseline and dragged it down (S04's baseline slid from about -5% to -19%),
so a real step slowly looked normal. If a long anomaly pushes every valid week outside the 26-week lookback, the last
valid baseline is kept and flagged (`baseline_frozen`). In a live system, RESOLVED re-admits the new level.

**EW03 trailing mean.** The same idea applies to the 8-week availability baseline (review finding M2): a week that is
1pp or more below its trailing mean (and below last year) or failed the DQ gate is kept out of later trailing means,
so a shortage cannot become the baseline it is judged against. Before this fix the E&T alert went quiet in
2025-W42 to W47 while availability was still 8-11pp below last year; it now stays on from 2025-W33 to W48.

The trailing 4-week and 8-week options appear where they suit the signal: EW03 uses the guarded 8-week mean as its
second baseline and EW05-EW07 use 4-week windows. The seasonally aligned option is the same-weeks-last-year comparison
used by EW02, EW03 and EW05-EW07. Only 2025 has a prior year, so every YoY signal covers 52 weeks.

## 6. Threshold methodology and back-test

Every candidate threshold from the config (for example EW01 peer gap 5, 10, 15, 20% with persistence 1, 2, 3 weeks;
robust z 2.5 to 4; CUSUM h 3 to 6; change-point delta 6 and 10) is back-tested on every entity-week
(`alert_backtest_results.csv`, 155 candidates). For each: weeks tested, alerts, alert rate, entities affected, alert
episodes, isolated alerts, persistent (4+ week) episodes, repeat-alert entities, median alert duration, unconfirmed
alerts and rate, DQ-held breaches, known-episode detection, detection delay, active share and exposure covered.

**Selection rule.** For each signal and grain, take the rule families in order of interpretability; the first family
with a candidate whose unconfirmed WARNING rate is at most **2% of non-episode entity-weeks** wins; within it the
smallest threshold (it can see the smallest sustained shift) and then the shortest persistence, with at least 2 weeks
for a WARNING unless the rule is an alarm-type rule (change point, DQ gate). For EW01 the Phase 8 change-point test is
a second rule, selected the same way (most sensitive delta inside the budget; delta 6 at 0%), and the rule as
operated, both together, is checked against the budget again (EW01 1.99%, check V11).

**What the selection does and does not see.** Detection delay, coverage and exposure on the known episodes are never
read (check V12 scrambles them and gets the same rules). The known episodes DO shape the selection, because their
weeks are not counted as noise. `selection_mask_sensitivity.csv` re-runs the selection counting every alert as noise:
8 of the 12 grains would get a stricter rule, and several would then miss or badly delay the known issues (EW01 robust
z 4 for 2 weeks: 2 of 3 cluster stores, 8.5 weeks; EW06 5pp for 2 weeks: 23.5 weeks; EW02 estate and format: not
detected). The estate budget cannot really be measured: EW02 estate has only 20 non-episode weeks, so one alert is
already 5%. This dependence is why every detection result here is called in-sample (the independent review found an
earlier version of this document overstated the point; finding M4).

**Known episodes** are the issues Phases 5 and 6 established, read from the frozen outputs and listed in
`config/monitoring_config.yaml` (`episodes`): the S03-S05 cluster from its change points; E&T availability and the
top-selling SKUs Phase 6 found out of stock; E&T 'Faulty' returns in S07, S13-S16; H&K promotions; H&K and E&T margin;
and the two DQ incidents. No evaluation-only or answer-key file is read (the audit hook records every file opened;
check V19).

Selected rules (`selected_rules.csv`):

| Signal | Rule | Alerts | Unconfirmed rate | Known entities detected | Median delay |
|---|---|---|---|---|---|
| EW01 store | peer gap 10% below baseline, 3 weeks, OR online change point (delta 6) | 64 (+ change point) | 1.99% (as operated 1.99%) | 3/3 | 3 weeks (operational) |
| EW02 estate | YoY 3% below its trend, 2 weeks | 8 | 0% (not measurable) | 1/1 | 0 |
| EW02 region | 10%, 3 weeks | 9 | 1.04% (as operated 1.55%) | 1/1 | 7 |
| EW02 format | 5%, 3 weeks | 9 | 0.93% | 1/1 | 4 |
| EW03 category / supplier | 1pp below both baselines, 2 weeks | 20 / 31 | 0.87% / 1.71% | 1/1, 1/1 | 1 |
| EW04 product | 1+ store with a full-week stock-out, 2 weeks | 71 | 0% | 7/9 | 3 |
| EW05 category | p < 0.05 and 3+ excess units, 2 weeks | 19 | 1.03% | 1/1 | 1 |
| EW05 store (E&T) | p < 0.05 and 3+ excess units, 2 weeks | 59 | 0.13% | 5/5 | 2 |
| EW06 category | GM % 1pp below last year, 4 weeks | 36 | 1.17% | 2/2 | 5.5 |
| EW07 category | discount rate 5pp above last year, 3 weeks | 15 | 0.63% | 1/1 | 5 |
| EW08 store | DQ gate FAIL | 3 | 0% | 2/2 incidents | 0 |

"As operated" includes the record rule and, for EW01, the change-point rule. EW04's 0% is partly by construction: the
known episode is "E&T SKUs that had full-week stock-outs", and no top seller outside it had a 2-week full stock-out.

## 7. S03-S05 detection

`s03_s05_detection.csv` compares every method family (its best in-budget candidate, or its lowest-burden one if none
is in budget) on the three stores, then reports the operational EW01 rule:

| Method | S03 | S04 | S05 | Unconfirmed rate | Verdict |
|---|---|---|---|---|---|
| Peer-gap threshold 10%, 3 weeks | W31 (+2) | W33 (+5) | W35 (+5) | 1.99% | Selected threshold rule; S04 active only 32% of its episode |
| YoY threshold 10%, 3 weeks | W31 (+2) | W33 (+5) | W30 (+0) | 0.99% | Fast, but fires on every store in an estate-wide fall (EW02 covers that); not the Phase 8 peer concept |
| Robust z 2.5, 2 weeks | W30 (+1) | W32 (+4) | W34 (+4) | 0.37% | Low burden but flickers (S04 active 8% of its episode) |
| Rolling mean/SD z 2.5 | not detected | not detected | not detected | 0% | Rejected: the anomaly inflates its own SD |
| CUSUM h = 6 | W30 (+1) | W32 (+4) | W30 (+0) | 9.6% | Rejected: outside the budget at every h (drift accumulates) |
| Online change point, delta 6 | W31 (+2) | W33 (+5) | W33 (+3) | 0% | Selected as the second EW01 rule (same budget) |
| **Operational EW01** (threshold OR change point) | **W31 (+2)** | **W33 (+5)** | **W33 (+3)** | **1.99%** | CRITICAL at first WARNING (threshold and change point agree) |

Delays are weeks after each store's change point (2025-W29, W28, W30; mid-July 2025), as Phase 6 dated them with
hindsight. Before the first cluster detection the estate had 9 unconfirmed EW01 WARNING alerts in 2025 (other stores,
mostly in H1). S03 had one early WARNING in 2025-W22, before its change point, labelled unconfirmed. After the change
point the operational rule was in alert 92% (S03), 68% (S04) and 87% (S05) of the weeks; S03 and S05 were still in
alert in 2025-W52, S04 had dropped back just before the year end. Cause not established from available internal data.

## 8. Advanced method: online change-point test

**What it detects.** A single sustained step in a store's peer gap. At every week t, using only weeks up to t, it
fits the best one-step split (least squares) and compares it with a flat line: stat = n ln(SSE0/SSE1) - 2 ln n (a BIC
style penalty). It alarms when stat >= 6, the step is downward, at least 3 weeks follow the step, and the current week is still at
least half the step below the pre-step level; the last condition switches the alarm off once a store recovers (added
after review finding M3: without it, a step found once stayed found for ever, because the history keeps growing). It also dates the
step (`changepoint_estimates.csv`): S03 from 2025-W29, step -32% in the peer gap; S04 from W29, -21%; S05 from W25, -17%.
No other store triggered it in 2025 (0 unconfirmed alarms).

**Why it is useful.** Threshold rules ask "is this week far from normal?"; the change-point test asks "has normal
moved?". A store that drifts down by 15-20% can sit just above a 10% threshold in some weeks and below it in others
(S04 and S05), so a threshold alert flickers while the change-point statistic keeps growing. It is also directly the
Phase 8 EW01 threshold concept ("a step change in the gap that persists, change-point test as in Phase 6").

**Assumptions.** One step per series at a time; roughly constant level and noise either side; weekly values
independent enough for the penalty to be sensible.

**Limitations.** Needs about 8 weeks of data before it can speak and 3 weeks after a step, so it is never the fastest
signal; a gradual trend is fitted as a step; after RESOLVED the history should be restarted from the new level. The
penalty (delta 6) was chosen by the same budget rule as every other threshold, not tuned to the cluster.

**How it differs from thresholds.** No fixed percentage: it adapts to each store's noise and looks at the whole run
of weeks, not the latest one. It is transparent (the step week and size are reported) and needs no training data or
machine learning. CUSUM was also tried and rejected on noise (above); EWMA would behave like CUSUM here.
Deep learning was not considered: 20 stores x 52 weeks is far too little data, and the result would not be
explainable to a store manager.

## 9. Severity framework

Rule based, per alert, fully written out in `severity_reason`:

| Level | Condition |
|---|---|
| NORMAL | no breach |
| WATCH | the selected threshold is breached this week but the persistence rule has not fired; or any breach in a week that failed the DQ gate |
| WARNING | the persistence rule fired; or the most extreme deviation of the signal so far (historical rarity, at least 200 earlier entity-weeks, `record_min_history`); or for EW01 the selected change-point rule is on |
| CRITICAL | a WARNING whose threshold is also breached this week, and that has lasted 4+ consecutive weeks (persistence); or 3+ entities of the same signal at WARNING in the same week with this one at WARNING for 2+ weeks (breadth); or episode exposure to date of at least one normal week of the entity's revenue (financial exposure); or for EW01 the threshold is breached AND the change-point test agrees (evidence from two methods) |
| DQ cap | a failed DQ gate (or C12) caps the alert at WATCH and marks it `dq_hold` |

Magnitude enters through the threshold, persistence through the run length, exposure through the cumulative monitoring
estimate, breadth through the count of entities, rarity through the record rule, data quality through the cap, and
evidence through the two-method agreement. All parameters sit in `config/monitoring_config.yaml` (`severity`).

**How the CRITICAL settings behave** (`severity_sensitivity.csv`, 356 WARNING-or-above entity-weeks in 2025): as
configured 246 are CRITICAL (4 of them unconfirmed). Persistence of 3 or 6 weeks gives 256 or 231; switching the
breadth rule off gives 212; the exposure rule matters little at 1 or 2 weeks of revenue but at half a week adds 25
CRITICALs, 11 of them unconfirmed. A week kept at WARNING only by the change-point rule, with no shortfall beyond the
threshold that week, stays WARNING (review follow-up N3). About 70% of WARNING+ weeks are CRITICAL because the 2025 issues were long: a
WARNING that lasts 4 weeks is CRITICAL by design. The breadth rule counts the cluster stores together (three stores
at WARNING in one week is itself a systemic signal); severity never reads the known episodes.

Every alert's evidence level stays "Observed change (monitoring alert)"
whatever its severity: severity says how urgently to look, not how sure we are of the cause.

**Exposure.** A monitoring ESTIMATE per signal (basis in `exposure_basis`): for EW01 the revenue equivalent of the
transaction shortfall; for EW03 the availability gap x ranged cells x recent sales per in-stock cell; for EW04 stores
out x the SKU's recent sales per in-stock store-week; for EW05 excess faulty units x average refund; for EW06 the margin
gap x revenue; for EW07 extra discount vs last year's depth. Exposures overlap (a store and its region, a category and
its SKUs), so they are never added across signals and no output carries an all-signal total (check V16).

## 10. DQ gating

The gate runs first, per store-week, on the data the run could see:

| Check | Level | Detects |
|---|---|---|
| C1 missing trading days | FAIL | a trading day with no sales lines at run time |
| C2 late-arriving lines | retrospective | share of final lines that arrived by the run |
| C3 row-count drop | FAIL | lines below half the trailing 13-week median AND below half the same week last year |
| C4 duplicates removed | WARN | re-sent receipts removed at load (Phase 3 FS-01) |
| C5 invalid prices | WARN | zero, negative or 100x prices repaired |
| C6 invalid discounts | WARN | missing discounts or broken promotion references |
| C7 missing product references | WARN | lines on the UNKNOWN product member (broken foreign key) |
| C8 stale or missing snapshots | FAIL/WARN | no stock snapshot (FAIL) or gaps in store-SKU series |
| C9 null or corrected fields | WARN | lines corrected or imputed at load |
| C10 quarantined lines | WARN | implausible quantities quarantined |
| C11 unlinked returns | WARN | returns without a received sale line |
| C12 prior-year returns history incomplete | HOLD | returns-based comparisons (EW05, EW06) whose prior-year window touches the first 5 weeks of history |

Nulls in key fields cannot reach the model (Phase 4 NOT NULL constraints); they surface as repaired rows (C9) or
unknown members (C7, C11).

**C12, added after the independent review (finding M1).** The returns history starts with the extract, so returns of
sales made before it (Christmas 2023) are missing from the first weeks of 2024: E&T returned 9 units in 2024-W01
against 100 in 2025-W01. Comparing early 2025 with those weeks overstated the increase and produced six unconfirmed
EW05 WARNINGs in 2025-W05 to W07. The longest sale-to-return lag is 30 days (Phase 6), so any returns-based
comparison whose prior-year window touches the first 5 retail weeks is now held.

Result: FAIL on exactly three store-weeks, S13 2024-W42 (two trading days missing) and S16 2025-W51 and W52 (sales
not yet arrived at the run). 791 store-weeks carry a WARN note. A FAIL holds the store's own alerts, any estate,
region or format total that includes it, and any window signal where the failed weeks are material (missing more than
5% of the window's expected lines, this year or last); an immaterial failed week in a window becomes a WARN note. The
estate stock caveat is raised only when more than 1% of the estate's snapshot cells are missing (finding m3: before,
a single store-SKU gap put a caveat on almost every inventory alert). In the back-test 41 alert-weeks were held: 10
by the gate (the Estate, Standard and Munster totals in 2025-W51/W52, S16's faulty-return window, S13's faulty-return
window in 2025-W42 to W45 whose prior-year window contains the failed 2024-W42) and 31 by C12 (EW05 and EW06 in
2025-W04 to W08).

## 11. Alert lifecycle

`alert_lifecycle.csv` and `sql/monitoring/02_alert_store.sql`:

| Status | Meaning | Allowed next |
|---|---|---|
| NEW | created by the weekly run | ACKNOWLEDGED, FALSE POSITIVE |
| ACKNOWLEDGED | an owner accepted it | INVESTIGATING, MONITORING, FALSE POSITIVE |
| INVESTIGATING | data being gathered (Phase 8 data requests) | ACTIONED, MONITORING, RESOLVED, FALSE POSITIVE |
| ACTIONED | a decision logged in the Phase 8 decision log | MONITORING, RESOLVED |
| MONITORING | watching whether it persists | INVESTIGATING, RESOLVED |
| RESOLVED | deviation ended or explained; baseline may reset | (end) |
| FALSE POSITIVE | investigated, not a real change (reason required) | (end) |

Every back-test alert is NEW with empty owner, acknowledged, resolved and resolution fields; the note says it is a
replay with no management response recorded. `alert_id` = signal-entitytype-entity-week (unique; check V03) and
`alert_episode_id` groups consecutive weeks of the same alert.

## 12. False and unconfirmed alert burden

No ground truth exists outside the known episodes, so nothing is called a confirmed false positive.
`false_positive_analysis.csv` classifies each WARNING+ alert outside the known episodes as an **unconfirmed alert**,
flags **isolated alerts** (alert episodes of one week) and **alerts without corroborating evidence** (no WARNING+ alert
on a different signal for the same or a directly linked entity within two weeks):

* 2025: 356 WARNING or CRITICAL entity-weeks; 311 in known episodes; 45 unconfirmed (about 0.9 a week across all
  signals); 33 of those have no corroborating alert; none is isolated (a WARNING needs 2+ weeks by design).
* Largest unconfirmed sources: EW01 stores (16, most in H1 2025) and EW03 suppliers (13).
* 593 WATCH entity-weeks (about 11 a week), 466 of them outside the known episodes (41 more are DQ-held), including 95 one-week EW01 WATCH
  blips. WATCH is not limited by the budget; it is context on the investigation page and is never pushed.

## 13. Monitoring results by area

* **Transactions.** Estate WARNING first in 2025-W29 and repeatedly from W35; Standard format from W33; Dublin region (where the cluster stores are) from W36; S03-S05 as in section 7.
* **Stock-outs.** E&T availability WARNING from 2025-W33 and continuously to W48 (H2 95.4% to 89.3%); two short
  unconfirmed alerts earlier in 2025 (W13, W19). Coverage: the top-seller rule watches the top 10% of SKUs by recent
  sales, which carried 261 of the 786 E&T full-week stock-out cells in H2 2025; 10 of the 19 SKUs Phase 6 found out
  of stock were never top sellers and are covered only through EW03 (finding m5). Nine top-selling E&T SKUs alerted; 7 of
  the 9 top-selling SKUs Phase 6 found out of stock were flagged, median 3 weeks after the start of the availability episode (2025-W32).
  Supplier concentration (`ew04_supplier_concentration.csv`): 674 of 786 E&T full-week stock-out cells (86%) are on
  SKUs supplied by Voltix Distribution Ltd, 0 the year before. This is an observation; the data does not establish
  that the supplier caused the shortage.
* **Returns.** Faulty-return activity exceeds expected range and requires investigation: E&T category from
  2025-W37; stores S07, S13, S14, S15, S16 all flagged between W37 and W41 (S13 held in W42 to W45 by the gate). The
  early-2025 comparisons are held by C12 (section 10). Unconfirmed returns alerts that remain: store S01 (W44) and the
  Seasonal & Gifts category (W45, W51, W52). `ew05_return_context.csv` shows the
  increase concentrated in those five stores and in a handful of products. 'Faulty' is the recorded return reason; it
  does not prove a defect.
* **Margin.** H&K gross margin % WARNING from 2025-W30, E&T from W35; GM EUR fell alongside (`ew06_margin_context.csv`).
* **Promotions.** H&K discount depth WARNING from 2025-W32, with promotion lines at a median 1.8 times last year's (up to 5 times) in the same 4-week windows
  (`ew07_promotion_context.csv`). Two early-2025 alerts (Garden & Outdoor, Stationery & Crafts) are unconfirmed.
* **Data quality.** Three FAIL store-weeks; 10 alert-weeks held by the gate and 31 by C12, none escalated.

## 14. Threshold sensitivity

`threshold_sensitivity.csv` and figure 8. For EW01 the burden falls fastest with persistence: at 10% it is 22.7%
(1 week), 6.5% (2 weeks), 2.0% (3 weeks). Raising the threshold also cuts burden but slows detection sharply at 3
weeks (15%: median delay 11 weeks; 20%: 14). Exposure covered falls from 99.6% (5%, 1 week) to 81% (selected) to 47%
(20%, 3 weeks). The selected EW01 rule sits just inside the budget (1.99%); the nearest alternative, 15% for 2 weeks,
has 1.4% and a median delay of 4 weeks, so the choice is not fragile in detection terms. For EW06 the 1pp 4-week rule
(1.2%, delay 5.5 weeks) replaced the earlier 2pp rule once the C12 hold removed the understated early-2025
comparisons from the noise count. Neighbouring candidates change counts by a few alerts, not an order of magnitude.

**Baseline settings** (`baseline_setting_sensitivity.csv`, review follow-up N2). The freeze (release after 4 weeks
above z -1) and the EW03 guard (1pp) were added in response to the independent review, so they were varied too: the
configured setting plus eight alternatives, each re-running the signals and the selection from the code. Read it in two
parts. Detection of the known issues is **robust** (it survives every setting except for EW02 format). The choice of
rule is **sensitive** (it moves for EW01, EW02 format and EW03 supplier):

* EW01 detects all three cluster stores under every freeze setting, and with no freeze. The selected rule is
  10% for 3 weeks in most settings; with a 6-week release or release at z -0.5 it becomes 15% for 2 weeks (median
  delay 4 weeks instead of 5). The configured rule sits right at the budget (1.99%), so one more unexplained
  alert-week would move it to that neighbour; both detect the cluster.
* EW02 format is the fragile grain: with a 2-week release, release at z -0.5 or no freeze, its compliant rule becomes
  10% for 3 weeks and misses the Standard-format movement.
* EW03: with a 0.5pp guard the supplier rule needs 4 weeks (delay 3 weeks instead of 1); without any guard the E&T
  alert is active only 53% of the shortage (the M2 problem).

## 15. Dashboard design (Phase 9 monitoring, Power BI-ready)

The dashboard answers "what needs attention this week?". Every page has the same filter row (retail week, signal,
entity type, severity, region, category) and defaults to the latest complete week. Data: `weekly_alerts.csv`,
`data/monitoring_signal_week.csv` (value, baseline, severity per signal x entity x week), `dq_store_week_health.csv`,
the context tables and `data/week_calendar.csv`.

| Page | Purpose | Visuals |
|---|---|---|
| 1 Operational Health | This week at a glance | DQ gate banner first (FAIL stores, held alerts); count tiles NEW WARNING / CRITICAL by signal; estate EW02 line with baseline and threshold; top 10 open alerts by severity then exposure |
| 2 Store Alerts | Which stores need an area-manager call | EW01 heatmap store x week (figure 9 design); store peer-gap line with baseline, threshold and change-point step; alert list with persistence and cause status |
| 3 Inventory Alerts | Replenishment check list | E&T and supplier availability vs both baselines; top-seller SKUs in alert with stores out, weeks persisting, exposure; supplier concentration table with its not-a-cause note |
| 4 Returns & Quality Alerts | Where faulty returns are above expected | category and store faulty rate vs expected; concentration by store, product, supplier; reason mix; wording "Faulty-return activity exceeds expected range and requires investigation." |
| 5 Margin & Promotion Alerts | Profitability separate from revenue | GM % and GM EUR vs last year beside net revenue change; discount rate, promotion share and promotion lines vs last year; "driver not established" note |
| 6 Data Quality Health | Can this week's numbers be trusted? | store x week gate matrix (figure 10 design); checks C1-C12 with tolerances; late-line share; held alerts list |
| 7 Alert Investigation | One alert in full | drill-through by alert_id: why it fired (rule, value, baseline, variance, severity_reason), its episode history, related alerts (corroboration), data required, proposed owner, lifecycle status and notes |

Design rules carried from Phase 7: one y-axis per chart; severity colours are reserved status colours and always carry
a text label; alerts are never shown without their cause status.

## 16. Operational interpretation

1. Monday 06:00: the run executes; Data/BI reads page 6 first. A FAIL routes to the data feed before anyone reads
   the business pages.
2. Monday morning: owners receive NEW WARNING and CRITICAL alerts (WATCH is visible, not pushed).
3. Within a week: the owner acknowledges, opens page 7, checks corroboration and the Phase 8 investigation framework,
   and requests the data listed in `data_required`.
4. The outcome is logged (Phase 8 decision log); RESOLVED or FALSE POSITIVE needs a reason. Resolved alerts reset the
   baseline; FALSE POSITIVE outcomes feed the next recalibration.
5. Recalibrate the thresholds quarterly on the logged outcomes, not on one known event.

## 17. Limitations

* **In-sample.** Detection was measured on the same 2024-2025 data used for calibration, and the known episodes
  decided which weeks count as noise (section 6). A true test needs 2026 data.
* **One prior year.** YoY signals start in 2025; the robust baselines need 8 valid weeks, so EW01 and EW02 speak from
  2025-W09.
* **Causes are not observable.** No footfall, competitor, supplier order or delivery, store operations or product
  inspection data. Every alert is an observed change; cause not established.
* **Peer definition.** EW01 peers are all other stores, not matched peers; a region-wide event would shrink the gap
  (EW02 region covers it).
* **Baseline drift.** Handled by the freeze-while-anomalous rule and the guarded EW03 mean; a slow decline that never
  crosses z -2 is still absorbed, which the change-point test partly covers.
* **As-at replay is partial.** Returns and stock snapshots have no arrival time, so they are taken at final values;
  at 2025-W51/W52 the E&T 'Faulty' rate divides final returns by on-time sales (S16 is held separately).
* **Weekly grain.** Partial-week stock-outs, weeks of cover, and daily data gaps below a whole trading day are not
  visible. EW05 uses return-date windows, not sale cohorts.
* **Exposure** is a monitoring estimate, overlapping between signals, never a loss or recovery figure.
* **Post-promotion performance** is not monitored weekly; Phase 6 covered it retrospectively.
* **EW04 coverage** is the top 10% of SKUs only (section 13).

## 18. Files

Code: `src/monitoring/*.py`, `sql/monitoring/01_monitoring_views.sql`, `sql/monitoring/02_alert_store.sql`,
`config/monitoring_config.yaml`, `tests/test_phase9_monitoring.py`.
Outputs in `reports/phase9/`: `weekly_alerts.csv`, `alert_summary.csv`, `alert_backtest_results.csv`,
`threshold_sensitivity.csv`, `signal_dictionary.csv`, `selected_rules.csv`, `s03_s05_detection.csv`,
`baseline_comparison.csv`, `selection_mask_sensitivity.csv`, `severity_sensitivity.csv`,
`baseline_setting_sensitivity.csv`,
`false_positive_analysis.csv`, `false_positive_summary.csv`, `changepoint_estimates.csv`,
`monitoring_kpi_dictionary.csv`, `dq_check_catalogue.csv`, `dq_store_week_health.csv`, `alert_lifecycle.csv`,
`ew04_sku_alert_context.csv`, `ew04_supplier_concentration.csv`, `ew05_return_context.csv`, `ew06_margin_context.csv`,
`ew07_promotion_context.csv`, `reconciliation_checks.csv`, `input_verification.csv`,
`phase1_8_dependency_manifest.csv`, `phase9_validation_checks.csv`, `data/`, `figures/` (10 PNG),
`phase9_executive_summary.md`, `phase9_validation_report.md`, `phase9_independent_review.md`.
