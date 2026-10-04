# Phase 9 independent review: findings and changes

**Reviewer:** an independent agent that had not produced the work. It was briefed to be adversarial and did not
edit any file.

**Scope:** the brief's section 24 list: data leakage, overfitting, arbitrary thresholds, causal overstatement,
duplicate alerts, double-counted exposure, retail-week alignment, look-ahead bias, prior-year comparison, unstable
baselines, excessive false alarms, alerts caused by DQ problems, unreadable charts and unnecessary ML complexity.

**How the review worked:**
- It re-ran Phase 9 into a separate folder. The outputs were byte-identical to the committed files.
- It ran the Phase 9 tests.
- It wrote its own probe scripts.

**Result:** 4 material findings, 7 minor findings and 3 notes. Every material finding was fixed before delivery.
The minor findings were fixed or disclosed. The numbers below are after the fixes.

## Checked and found sound

- **Freeze:** 324 Phase 1-8 files are unchanged, and reconciliation passes 21/21, including the H2 headline.
- **Evaluation assets:** no answer-key, planted-issue or evaluation-only file is referenced or opened. The file-open audit hook and the refused-path rule both work.
- **No leakage:** every baseline, rolling z, CUSUM and change-point statistic uses weeks before t only. The top-seller ranking and the exposure rates use the previous weeks. The DQ row-count median uses the counts each earlier week showed at its own run.
- **Weeks and prior year:** 52 weeks are compared, each prior-year week is exactly 364 days earlier, runs are at Monday 06:00, and the partial week is excluded.
- **Alert table:** alert IDs are unique and there are no duplicate entity-weeks. No exposure is totalled across signals.
- **Wording:** EW01 and EW05 carry the required wording on every alert. There is no causal, defect or supplier-blame wording, no invented management response and no claim of production deployment.
- **Complexity:** no machine learning.

## Material findings

**M1. The early-2025 returns alerts were caused by gaps in the data, not by trading, and nothing gated them.**
- **Found:** returns history starts with the extract, so returns of Christmas 2023 sales are missing from early 2024. For E&T, 9 units were returned in 2024-W01 against 100 in 2025-W01. This produced six unconfirmed EW05 WARNINGs in 2025-W05 to W07, and those WARNINGs also counted against the selection budget.
- **Changed:**
  - A new check, C12 "prior-year returns history incomplete", holds any returns-based comparison (EW05, EW06) whose prior-year window touches the first 5 retail weeks of history. The limit comes from the longest sale-to-return lag, 30 days (Phase 6).
  - 31 early-2025 alert-weeks are now held at WATCH with a C12 note.
  - Selection was re-run: EW05 category moved from p < 0.01 to p < 0.05, and EW06 from 2pp to 1pp over 4 weeks.
  - The first E&T faulty-return WARNING is now 2025-W37.
  - Test: `test_returns_warmup_holds_early_2025_return_comparisons`.

**M2. The EW03 availability baseline followed the shortage down, so the alert went quiet mid-episode.**
- **Found:** E&T availability sat 8-11pp below last year in 2025-W42 to W47 while severity was NORMAL or WATCH. The trailing 8-week mean had fallen with it, and DQ-failed weeks were not dropped from that mean.
- **Changed:**
  - The trailing mean is now guarded. A week at least 1pp below its trailing mean (and below last year), or a week that failed the DQ gate, is kept out of later trailing means.
  - The E&T alert is now on in every week from 2025-W33 to W48.
  - Test: `test_availability_alert_stays_on_through_the_shortage`.

**M3. The S03-S05 headline rested on a change-point rule that had not gone through selection, and the signal dictionary described it wrongly.**
- **Found:**
  - The change-point delta was hard-coded.
  - The dictionary said the test only "held open" alerts, but the code raised WARNING from it.
  - Once a step was found it stayed found for ever, because the history keeps growing. This produced CRITICAL weeks with no current shortfall.
  - The EW01 baseline drifted down into the step (S04 from about -5% to -19%).
- **Changed:**
  - The change-point test is now a secondary EW01 rule chosen by the same budget rule (`select_secondary`; delta 6 at 0%). The rule as operated, threshold and change point together, is checked against the budget again (EW01 1.99%, check V11).
  - The alarm now switches off once the current week is back within half the estimated step.
  - The robust baseline is frozen after an adverse anomaly until 4 consecutive weeks are back above z = -1.
  - CRITICAL from the change point now needs the threshold to be breached in the same week.
  - The dictionary text was corrected.
  - `s03_s05_detection.csv` reports the threshold rule on its own beside the operational rule.
  - After the fix, S04 is no longer in alert in the final week; this is reported rather than hidden.
  - Tests: `test_changepoint_switches_off_after_recovery`, `test_baseline_freezes_while_a_step_persists` and `test_changepoint_rule_is_selected_and_operated_within_budget`.
- **Not changed:** the reviewer also suggested that the breadth rule should not count members of the same episode. Severity never reads the known episodes, by design, so it cannot tell cluster members apart. Three stores at WARNING in one week is itself a systemic signal. The effect of the breadth rule is now shown in `severity_sensitivity.csv` (212 CRITICAL without it, against 246 as configured).

**M4. "No episode information is used" overstated the independence of the selection.**
- **Found:** the budget counts noise only on weeks outside the known episodes, so the episodes shape the selection through that mask. The test that scrambled detection metrics showed only that `select()` does not read them.
- **Changed:**
  - The wording is corrected in the config, docs/09, the executive summary, the validation report and the figure 8 subtitle.
  - A new output, `selection_mask_sensitivity.csv`, re-runs the selection with no mask. 8 of the 12 grains would get a stricter rule, and some would then miss or badly delay the known issues.
  - The EW02 estate budget is flagged as not measurable, because 20 non-episode weeks means one alert is already 5%.
  - Check V12 and its test were renamed to say what they actually prove.
  - Test: `test_episode_mask_effect_is_reported`.

## Minor findings

- **m1. The as-at replay was incomplete.**
  - **Found:** product-week sales used final values.
  - **Changed:** `mon.kpi_product_week` now carries on-time sales and units, and EW03/EW04 use them.
  - **Disclosed:** returns and stock snapshots have no arrival time in the source, so they stay at final values. This is stated in docs/09, the executive summary and the validation report.
- **m2. The baseline comparison was not like for like and had a bug.**
  - **Found:** B1 applied `log1p` to a value that was already a log ratio.
  - **Changed:** the bug is fixed. All six options are now tested on the same 878 store-weeks with the same rule (15% below baseline for 2 weeks), and a trailing 4-week option was added. B4 stays the choice: 1.4% burden and active 60% of the S03-S05 episode, while the quieter unguarded mean is active only 10%.
- **m3. The estate stock caveat appeared on almost everything.**
  - **Found:** it was raised when any store had a snapshot gap.
  - **Changed:** it is now raised only when more than 1% of the estate's snapshot cells are missing. Test: `test_estate_inventory_caveat_is_material_only`.
- **m4. The severity parameters were untested and hard-coded, and CRITICAL dominated.**
  - **Changed:** `record_min_history` moved to the config, and `severity_sensitivity.csv` shows WARNING+ and CRITICAL counts under the configured setting and eight alternatives.
  - **Disclosed:** CRITICAL is about 70% of WARNING+ because the 2025 issues were long.
- **m5. EW04 coverage and the 0% unconfirmed rate.**
  - **Disclosed:** the top 10% of SKUs carried 261 of the 786 E&T full-week stock-out cells in H2 2025, and 10 of the 19 SKUs Phase 6 found out of stock were never top sellers. The 0% unconfirmed rate is partly a result of how the episode is defined.
- **m6. The executive summary and figure 5 left out the early returns alerts.**
  - **Changed:** the first-alert weeks now come from all alerts, and the early held alerts are explained (C12).
- **m7. The review document was missing.**
  - **Changed:** this file.

## Notes

- **Literal em dash in a test:** the character is now written as its Unicode escape (U+2014).
- **WATCH volume:** 593 WATCH entity-weeks (about 11 a week, 466 outside the known episodes) are now quoted beside the 2% budget in docs/09.
- **Delays are in-sample:** they are measured from change points dated with hindsight. This was already disclosed and remains so.

## Effect of the fixes on the headline results

| Item | Before review | After review |
|---|---|---|
| S03 / S04 / S05 first WARNING | W31 / W33 / W33 | W31 / W33 / W33 (unchanged) |
| Cluster stores in alert in 2025-W52 | 3 (guaranteed by the never-ending change-point alarm) | 2 (S04 had recovered below half the step) |
| E&T availability alert, W42-W47 | quiet | on every week |
| First E&T faulty-return WARNING | W05 (data gap) | W37 (the early weeks are held by C12) |
| WARNING+ entity-weeks (unconfirmed) | 312 (31) | 356 (45) |
| Held alert-weeks | 8 | 41 (10 by the gate, 31 by C12) |
| Validation checks | 21/21 | 21/21 |

The rise in unconfirmed alerts is the cost of the fixes to M2 and M3. A baseline that no longer follows a
deterioration down also keeps flagging milder unexplained dips for longer:
- EW01 now has 16 unconfirmed alerts (previously 10).
- EW03 suppliers now have 13 (previously 7).

Every selected rule, and every rule as it is operated, stays inside the 2% budget (check V11).

## Verification pass

The same reviewer checked the fixes against a fresh re-run.

**What it confirmed:**
- The re-run was byte-identical to the committed outputs, and the 49 Phase 9 tests passed.
- M1, M2, M3 and six of the seven minor findings are fixed.
- An end-to-end truncation test found no look-ahead in the new logic. It rebuilt every signal from data cut off at 2025-W40, and every baseline, deviation, z-score, change-point statistic, exposure, DQ flag and breach up to W40 matched the full run.
- No em dash appears in any Phase 9 file.

**What it raised, and what changed:**

- **N1. Two leftover "no episode information" statements.**
  - **Fixed:** the validation-report text on the known episodes and a code comment in `backtest.select` are reworded.
- **N2. The baseline settings added after the review had no sensitivity check.**
  - **Fixed:** a new output, `baseline_setting_sensitivity.csv`, re-runs EW01-EW03 and their selection under the configured setting and eight alternatives; docs/09 section 14 summarises it.
  - EW01 detects all three cluster stores under every setting (detection is robust). Its selected rule moves to the 15%, 2-week neighbour under two settings (the rule choice is sensitive).
  - EW02 format is the fragile grain: it misses the Standard-format movement under three settings.
- **N3. Four S04 weeks were CRITICAL with no current threshold breach.**
  - **Fixed:** CRITICAL now also needs a breach of the selected threshold in the same week, so a week kept at WARNING only by the change-point rule stays WARNING.
  - As a result, CRITICAL went from 250 to 246 and WARNING from 106 to 110.
- **N4. Choosing baseline B4 over B5 used detection on the known episode.**
  - **Fixed:** docs/09 section 5 now says so, with the reasoning.
- **N5. Some tests pin known-episode results.**
  - **Fixed:** the test module now labels them as regression checks, not targets for recalibration.
- **N6. The unconfirmed Seasonal & Gifts returns alerts were not named.**
  - **Fixed:** docs/09 section 13 now names them (W45, W51, W52).
