# Phase 8 independent review: findings and fixes

**Reviewer:** a separate agent that had not seen the work being produced, instructed to be adversarial and not to modify any file or open evaluation-only files.
**Scope:** every Phase 8 output, `docs/08`, `config/action_config.yaml` and `src/actions/`, checked against the frozen Phase 6 and Phase 7 files.
**Result:** 30 findings: 1 Critical, 12 Major, 17 Minor. All 30 were addressed. Phase 8 was then rerun and the full validation and test suite repeated (see `phase8_validation_report.md`).

Nothing was found in these categories: summing the four Home & Kitchen methods, invented ROI, claiming supplier failure, product defect or footfall decline as fact, hiding the residual, fabricated values for unavailable KPIs, starting forecasting or ML, and owners not labelled PROPOSED. The reviewer checked about 45 numbers against the source files and found all of them correct, including the headline, all attribution components and shares, the four promotion methods, the sensitivity ranges, the residual parts, and the cluster, stock-out, returns and promotion figures. The counts (actions, KPIs, data items, signals) were also correct.

## Findings and fixes

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | The Upper stock-out scenario did not net out deferred demand. Demand that came back after restock is already in H2 2025 revenue, so calling it avoidable counts it twice. | Upper removed. Its row now says "not provided" and explains why: the gross estimate and the sensitivity high include recovered demand, and the partial-week bound is not evidence. A check and a test fail if any of these figures reappears as avoidable value. |
| 2 | Major | The Base scenario was a best case, and "per half-year on the H2 2025 pattern" read as a forecast. The euro-exact values were false precision. | Scenarios now restate the H2 2025 estimate only; the future framing is gone. Base is renamed "Full elimination (best case)". Values are rounded (about €24k). E13 wording is aligned. |
| 3 | Major | A07 used "top 10% by prior-year sales" yet named P00151, a new SKU with no prior-year sales. New SKUs were excluded entirely. | A07 now selects the fastest sellers on the current sales rate (last 8 weeks) and includes new launches. It starts with the three largest lost-sales SKUs. The Phase 6 definition is named where it is quoted. |
| 4 | Major | A04 could not split the July gap using counters installed now. | Where counters with history exist, the July gap is split. Otherwise proxies (car park, transport, mobile location, card spend) cover the past, and new counters measure only the present. Cluster step 3 is changed to match. |
| 5 | Major | "Cause: Established" for I2 overstated D03. | The I2 cause note now reads: established only for lost sales during full-week stock-outs; why stock ran out is not established (see I3). |
| 6 | Major | The ACT NOW criteria differed between the plan, the figure and docs/08. Action-level categories did not follow the issue rule. | One action-level rule (`action_rule_text`) is stated identically in the plan and docs/08, and the figure subtitle is aligned. The docs explain that issue categories and action categories are different things. The test enforces the rule. |
| 7 | Major | Categories depend mostly on judgement ratings. Reversibility never separates issues. Rule 3 uses size while the text said size never decides. | The plan and docs now say plainly that categories depend on PROPOSED ratings and that reversibility does not separate issues. A new `pivotal_judgements` column shows which single rating would change each category. The claim is reworded: size can make an issue worth investigating, and only evidence can make it ACT NOW. The treatment of I6 as "Not quantified" is disclosed. |
| 8 | Major | The promotion test cannot report by the day-90 gate. | Day 90 now reviews only the governance control and the hold. The depth decision moves to a post-test gate, planned around day 150 to 180. DL-006, the plan rows and DR32/DR33 ("90+") are updated. |
| 9 | Major | An inconclusive test would have led to a cut, which amounts to acting on M1/M4. | An inconclusive result now keeps the current depth under the governance control (A18), and the test is extended or repeated. Depth moves towards the prior-year level only where the test shows margin is lost. |
| 10 | Major | The holdout test was unrealistic: national advertising, cross-shopping, few pairs, and a "holdout" that still promotes. | Only unadvertised in-store mechanics vary. Marketing and legal (price display, consumer protection) sign off. Stores that share customers are randomised as clusters. A time switchback is the fallback. The comparison arm is named as a lower-depth arm, not a holdout. |
| 11 | Major | K13 set Nov 2025 next to Sep 2024 only, which exaggerates the rise. | Same months are now paired: Sep 2025 with Sep 2024, and Nov 2025 with Nov 2024. |
| 12 | Major | A13 held returns only in the five flagged stores, so there was no no-fault-found baseline. | A comparison sample from three stores without an increase is added. The classification framework now judges the defect rate against those stores. |
| 13 | Major | docs/08 cited a review file that did not exist. | This file. |
| 14 | Minor | The promotion range was mislabelled: -€380,272 is an interval bound, not a point estimate. | Point estimates now run from -€265,003 (M4) to +€97,505 (M2), and from -€380,272 to +€161,234 including intervals. §5.4 is corrected. |
| 15 | Minor | Cannibalisation was shown as "not measured", but Phase 6 reported none measurable (ESTIMATE). | Phase 6's figure is cited, with the caveat that its baselines are contaminated. |
| 16 | Minor | The elasticity row used the raw units change. | Uses M1's units change against control categories, with its confidence interval (not significant). |
| 17 | Minor | The supplier-issue row quoted only the evidence against it. | Both sides are now quoted: the largest supplier holds 68% of the increase, and all four suppliers rose. |
| 18 | Minor | "Other return reasons did not rise" was not exact ('Damaged' rose €484). | Now reads "did not rise materially (largest change 'Damaged' +€484)". |
| 19 | Minor | I3's share sat among additive shares; the rounded shares add to 99%. | I3 is shown "(within I2)" in the table and the figure, and a rounding note is added. |
| 20 | Minor | Owners of DL-004, A11 and I3 differed without explanation. | I3 supporting teams now name Buying (supplier relationship) and Commercial (supplier sanction decisions). |
| 21 | Minor | A plan row listed the wrong decision-log IDs. | Now lists DL-001, DL-004 and DL-006. |
| 22 | Minor | DR33 was cited for loyalty data. | Replaced with DR10 and DR35. |
| 23 | Minor | Effort ratings were inconsistent (I1). | I1 effort changed to Medium, with the reason. I2 effort refers to its immediate controls; the Medium-effort data request (A09) is rated separately. |
| 24 | Minor | A08 was ambiguous about whether it changes parameters. | Parameters are adjusted only as temporary, recorded changes; permanent changes wait for I3. The I2 decision text matches. |
| 25 | Minor | The Phase 6 caveats on the cluster were dropped. | I1 now states them: no Dublin matched control, and the placebo overstates significance because of selection. The Dublin-control excess is added. |
| 26 | Minor | The K03 definition said "minus" but showed two values. | The definition now matches, and the D01 difference-in-differences gap is added. |
| 27 | Minor | A18's trigger ("deeper than prior-year depth") was undefined. | Now defined against the same SKU's depth in the equivalent prior-year promotion, or a depth band per mechanic set by Commercial. |
| 28 | Minor | "Every number is validated" was too broad; -7.177251% appeared in executive prose; "about" was paired with an exact figure. | The status line now separates analytical figures from planning proposals. Prose shows -7.18%, with 6 decimals kept only in the reconciliation. The margin is shown as "about €8k". |
| 29 | Minor | The I3 title "(who is responsible)" presumed blame. | Renamed "(supply vs ordering)". |
| 30 | Minor | The em dash character appeared literally in code, as the constant used to detect it. | Replaced with its Unicode escape sequence, so the character itself no longer appears in any Phase 8 file. |
