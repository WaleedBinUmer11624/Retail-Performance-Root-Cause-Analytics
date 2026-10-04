# Phase 9 executive summary: operational monitoring and early warning

Brightwater Retail Ltd | Retail Performance & Root-Cause Analytics | Phase 9

## What this phase adds

Phases 5 to 8 explained the 2025 decline after the event. Phase 9 asks a different question: **if a weekly monitor had been running, when would it have raised the alarm?** It turns the eight early-warning signals proposed in Phase 8 (EW01 to EW08) into tested rules and replays them week by week through 2025, each week using only the data that would have been available at 06:00 on the Monday after the week closed.

Historical diagnosis → Evidence testing → Decision support → Management action planning → Operational early warning

This is a back-test and a design. Nothing has been deployed to production, and no alert here was ever sent to anyone.

## The headline

* **The store cluster would have been flagged within weeks, not at half-year.** Stores S03, S04 and S05 reached WARNING in 2025-W31, 2025-W33 and 2025-W33: 2, 5 and 3 weeks after each store's change point. S03 and S05 were still in alert in the last week of the year. Cause not established from available internal data.
* **Electronics & Tech availability** would have been flagged in 2025-W33 (after short, unconfirmed alerts earlier in the year, the first in 2025-W13) and stayed in alert through the shortage. Top-selling SKUs with full-week stock-outs were flagged in the weeks that followed: 7 of the 9 top-selling Electronics & Tech SKUs that Phase 6 found out of stock. The monitor produces a replenishment check list; it does not say why stock ran out, and it does not attribute the gap to any supplier. By design it watches only the top-selling 10% of SKUs: they carried 261 of the 786 Electronics & Tech full-week stock-out cells in H2 2025, and 10 of the 19 SKUs Phase 6 found out of stock were never top sellers, so they are left to the availability signal (EW03).
* **Faulty returns**: faulty-return activity exceeds expected range and requires investigation. For Electronics & Tech this was flagged in 2025-W37, and 5 of the 5 stores Phase 6 identified were flagged within weeks of each other. Earlier 2025 comparisons (31 returns and margin alert-weeks in January and February) were held, not escalated: last year's returns in those weeks are understated because returns of sales made before the data starts are missing (check C12).
* **Margin and promotions**: Home & Kitchen gross margin % reached WARNING in 2025-W30 and its discount depth in 2025-W32. The alerts show that margin fell and that promotions were deeper than last year; they do not show that one caused the other.
* **Data problems are caught before they mislead.** The data-quality gate failed on exactly 3 store-weeks (S13 2024-W42 with two trading days missing, and S16 2025-W51 and W52, whose sales arrived after the Monday run). The 10 alert-weeks that depend on those weeks were held at WATCH instead of being escalated (41 held in all, including the C12 returns holds above).

## How much noise would managers have received?

Across 2025 the monitor raised 356 WARNING or CRITICAL entity-weeks. 311 fall inside the issues Phases 5 and 6 established; 45 (about 0.9 a week across all signals) are **unconfirmed alerts**: outside every known issue, unexplained, but not proven false. An analyst would check each one; only a closed investigation could mark an alert FALSE POSITIVE. Each rule was chosen to keep unconfirmed WARNINGs under 2% of the weeks it watches outside the known issues. The selection never looked at how quickly a rule caught those issues, but it did depend on them: their weeks are left out of the noise count. Counting every alert as noise would have chosen stricter rules for 8 of the 12 signal grains (`selection_mask_sensitivity.csv`).

About 69% of WARNING-or-above entity-weeks are CRITICAL. That is expected here: the 2025 issues each lasted many weeks, and a WARNING that persists for 4 weeks becomes CRITICAL. `severity_sensitivity.csv` shows how the count moves with each CRITICAL setting.

A further 593 entity-weeks were at WATCH (a threshold breached once, not yet persistent). WATCH is shown on the investigation page for context and is not pushed to anyone.

## What each signal is for

| Signal | Watches | Rule chosen | Alert means | Proposed owner |
|---|---|---|---|---|
| EW01 store | Store transaction deterioration | 10 (peer gap threshold), 3 week(s), or the change-point test | INVESTIGATIVE | Retail Operations (area manager) (PROPOSED) |
| EW02 estate | Estate transaction deterioration | 3 (yoy vs trend threshold), 2 week(s) | INVESTIGATIVE | Head of Retail (PROPOSED) |
| EW02 format | Estate transaction deterioration | 5 (yoy vs trend threshold), 3 week(s) | INVESTIGATIVE | Head of Retail (PROPOSED) |
| EW02 region | Estate transaction deterioration | 10 (yoy vs trend threshold), 3 week(s) | INVESTIGATIVE | Head of Retail (PROPOSED) |
| EW03 category | Availability deterioration | 1 (availability gap pp), 2 week(s) | INVESTIGATIVE | Supply Chain (replenishment) (PROPOSED) |
| EW03 supplier | Availability deterioration | 1 (availability gap pp), 2 week(s) | INVESTIGATIVE | Supply Chain (replenishment) (PROPOSED) |
| EW04 product | Top-seller full-week stock-outs | 1 (stores out count), 2 week(s) | ACTIONABLE (replenishment check) | Supply Chain (replenishment) (PROPOSED) |
| EW05 category | Faulty-return deterioration | p<0.05, excess>=3 (binomial excess), 2 week(s) | INVESTIGATIVE | Quality / Buying (Electronics & Tech) (PROPOSED) |
| EW05 store | Faulty-return deterioration | p<0.05, excess>=3 (binomial excess), 2 week(s) | INVESTIGATIVE | Quality / Buying (Electronics & Tech) (PROPOSED) |
| EW06 category | Gross-margin deterioration | 1 (margin gap pp), 4 week(s) | INVESTIGATIVE | Finance / Category manager (PROPOSED) |
| EW07 category | Unusual promotion behaviour | 5 (discount gap pp), 3 week(s) | INVESTIGATIVE | Commercial / Trading (PROPOSED) |
| EW08 store | Data completeness and quality | gate FAIL (dq gate fail), 1 week(s) | ACTIONABLE (data feed check) | Data/BI (PROPOSED) |

Every alert carries the same two statements: evidence level *Observed change (monitoring alert)* and cause status *Not established*. An alert starts an investigation (the Phase 8 investigation frameworks); it is never the conclusion.

## What managers should take from this

1. A weekly monitor on data Brightwater already holds would have surfaced each 2025 issue months before the half-year review, with a small number of unexplained alerts to check each week.
2. The alerts are only as good as the feed: the DQ gate must run first each Monday, and its failures go to Data/BI before anyone reads the dashboard.
3. The thresholds were calibrated on 2024 and 2025 and tested on the same period. They are a starting point: the first quarter of live running should be treated as a calibration period, with each alert's outcome logged in the Phase 8 decision log.
4. Owners and responses are proposals. No management response is recorded here and none has been invented.

## Limits to keep in mind

* In-sample: the known issues used to judge detection come from the same two years the rules were tuned on, and their weeks were left out of the noise count, so the test is not out-of-sample.
* The replay is as-at for sales but not for returns and stock snapshots, which carry no arrival time; they are taken at their final values.
* Alerts are observed changes, not causes. Footfall, supplier, purchase-order, local-event and store-operations data are not available, so no alert can say why.
* Exposure figures are monitoring estimates of the size of each deviation. They overlap between signals and are never added together.
* Only one year (2025) has a prior year, so year-on-year signals cover 52 weeks.

Detail: `docs/09_monitoring_early_warning.md`; validation: `phase9_validation_report.md`; figures in `reports/phase9/figures/`.
