# Phase 6: Root-Cause Investigation and Causal Diagnostics

| Item | Detail |
|---|---|
| Project | Retail Performance & Root-Cause Analytics System |
| Company | Brightwater Retail Ltd (fictional, synthetic data) |
| Author | Waleed Bin Umer |
| Version | 1.0 (awaiting Phase 6 sign-off) |
| Date | 28 September 2026 |
| Inputs | Phase 4 governed model (rebuilt from the frozen Phase 3 curated data), frozen Phase 5 outputs |
| Code | `src/rca/`, `sql/analysis/rca/01-02`, `config/rca_config.yaml` |
| Outputs | `reports/phase6/` (report, evidence matrix, about 50 tables, 11 figures, validation report, run log) |

---

## 1. Objective

Phase 5 described what changed and where, and handed over a shortlist of candidate drivers. Phase 6 tests each candidate and asks, for each one, three questions:

1. How big is it once overlaps with the other drivers are removed?
2. Is there a visible mechanism, or only a correlation?
3. Which data would move it to a higher evidence level?

Phase 6 does not recommend actions, forecast, build Power BI or add machine learning. It diagnoses. The findings are in `reports/phase6/phase6_root_cause_report.md`; this document explains the methods.

## 2. Independence and freeze

- **Blind to the generator.** Phase 6 reads only the governed model and the frozen Phase 4 and Phase 5 outputs listed in `config/rca_config.yaml`. The input guard (`src/rca/access.py`) refuses raw, sample, quarantine and every evaluation-only asset. An audit hook and a traced `open` record every file the run touches, and the tests assert that none of them is an evaluation asset.
- **Freeze.** At the start of the phase, SHA-256 hashes of 84 Phase 1 to 5 files (code, SQL, configuration, docs, tests, Phase 5 tables and summary) were recorded in `reports/phase6/phase1_5_input_manifest.csv`. Every run re-hashes them and stops if any file changed, disappeared or appeared.
- **Independent recomputation.** Phase 6 recomputes the headline from the model and reconciles it three ways: to Phase 4's reconciliation results, to a direct fact-table query, and to Phase 5's `headline_kpis.csv`. It also recomputes the store cluster with the Phase 5 rule and stops if the result differs from Phase 5's hand-off. Its full-week lost-sales figure must equal Phase 5's to the cent.

## 3. Pipeline

```
verify freeze (84 files)  -> build the Phase 4 model (DuckDB) or open it (SQL Server)
  -> diag.* views (Phase 5, unchanged) -> rca.* views (sql/analysis/rca, T-SQL)
  -> load, and sort every result for reproducibility
  -> headline reconciliation (STOP on failure) -> cluster hand-off check (STOP on mismatch)
  -> store cluster | Electronics availability | 'Faulty' returns | Home & Kitchen promotions
  -> overlap and exclusive attribution -> sensitivity (83 variants) -> scenarios -> evidence matrix
  -> 36 validation checks -> tables, figures, report, validation report
```

The `rca` views (`v_store_day`, `v_receipt`, `v_store_category_week`, `v_sku_week_supply`, `v_stockout_episode`, `v_return_detail`, `v_product_sale_month`, `v_store_category_h2`) read only `dw.*`, `mart.*` and `diag.*`. They are written in T-SQL and translated for DuckDB by the Phase 4 engine layer. They read no files.

## 4. Store-cluster investigation (S03, S04, S05)

**Onset (an ESTIMATE, not a fact).** Daily transactions are compared with the same weekday last year, and the cluster's YoY is compared with the control stores' YoY. Three models are fitted to that daily gap: a single step (change point), a linear ramp of 0 to 56 days, and a straight line. They are compared by BIC. A best-fitting transition of 14 days or less counts as abrupt. Each store is also fitted on its own.

**Controls.** There are four control groups:
- *matched* (primary): the 5 nearest non-cluster stores on standardised pre-period revenue, transactions, basket, format, region and H1 trend;
- all non-cluster Standard-format stores;
- the Dublin non-cluster stores;
- all non-cluster stores.

A test asserts that no control group contains a cluster store.

**Difference-in-differences.** The outcome is the store-week YoY log ratio (transactions, net revenue, sales revenue). The pre-period is weeks 1 to 26 and the post-period is weeks 27 to 52. Parallel trends is checked by regressing the pre-period weekly gap on time. Inference is a permutation placebo: the same statistic is computed for all 680 three-store groups of non-cluster stores, each against the remaining non-cluster stores. Because Phase 5 selected the cluster as the stores that declined most, the placebo p-value overstates significance; the report treats the size of the gap, and its stability across control groups, as the evidence. The cluster stores are the only Standard-format stores in Dublin, so no matched control shares their region; this is disclosed in the report.

**EUR impact (ratio DiD).**

Counterfactual = cluster prior-year H2 × control-store YoY ratio × cluster pre-period gap ratio

Excess = actual minus counterfactual. The same calculation gives gross margin and transactions.

**Mechanism checks.** The cluster is compared with its controls on availability, promotional share, average selling price, units per transaction, ranged SKUs and return rate. The loss is broken down by weekday, hour, category and basket-value band. A uniform loss across all of them, with no internal lever moving, is what a drop in visits looks like. The data has receipts but no footfall, so the cause is classified as **unresolved**. The external explanation stays a **hypothesis** until footfall, competitor and local-event data are available.

## 5. Electronics & Tech availability

- **Lost sales.** The Phase 5 estimator is reused unchanged (`src/analytics/diagnostics.py`): expected units come from recent in-stock, non-promoted weeks with a seasonal index.
  - *Primary figure:* full-week stock-outs only (opening stock 0 and nothing received). No sale could have happened that week, so the estimate is conservative.
  - *Upper bound:* the literal BR-05 formula over every stock-out week. It counts partial-week stock-outs, where some sales did happen, and it is never used as evidence.
- **Supplier test.** The change in each SKU's stock-out rate is compared between the leading supplier's SKUs and all other suppliers' SKUs in the category. The test uses a bootstrap CI and a label-permutation p-value, repeated with the largest SKU removed. Because the supplier is picked as the worst before testing, a Bonferroni-adjusted p-value (times the number of suppliers) is also reported. This checks the hypothesis rather than assuming it.
- **Episodes, concentration, recovery.** Stock-out episodes are found with gaps-and-islands logic in SQL. Concentration is reported for high-selling SKUs (top 10% by prior-year revenue) and for the top SKUs. Recovery is actual versus expected sales in the two weeks after an episode ends. Sales above expected mean part of the demand was deferred rather than lost. Sales after restock normally run above expected (the prior year shows the same bounce), so the **recovery offset** is the current-year post-restock revenue above what the prior-year actual-to-expected ratio implies, measured after episodes that contain a full-week stock-out (the scope of the primary estimate). It is netted off the primary estimate as a sensitivity variant; the equivalent offset over all episodes is netted off the upper bound.
- **Replenishment.** Opening stock and units received per ranged store-SKU-week, by supplier and year. These separate "less stock arrived" from "stock arrived but sold out".
- **Range and distribution.** Outside the cluster, the category's sales change is split by supplier and SKU status: delisted (ranged in the prior H2 only), new (current H2 only) and continuing. For continuing SKUs, a distribution effect (change in ranged store-SKU-weeks at the prior-year sales per ranged week) is separated from a rate effect. This is a partition of measured sales (FACT), not an estimate.

## 6. 'Faulty' returns

'Faulty' is a reason code chosen at the till, not a verified defect. Rates are returned units per 100 units sold in the same scope, by product, supplier, store, store × supplier and sale-month cohort. Excess returns are measured against each scope's own prior-year rate. The increase is tested with a one-sided conditional binomial test (current-year returns out of both years' returns, against the current year's share of units sold), which treats both years' rates as uncertain. Store-level p-values are not adjusted for testing 20 stores and are read as a statistical association.

Other return reasons in the same stores act as a control. If they did not rise, a store-wide returns-policy change is less likely, but a change in how staff pick the reason code is not ruled out.

The lag from sale to return is compared with a KS test. The increase is split between promoted and full-price sales.

To confirm a product defect you would need QA inspection results, batch, lot or serial numbers, supplier defect and RMA reports, warranty claims, and a returns-handling audit in the stores concerned.

## 7. Home & Kitchen promotions

Four methods are used on purpose, because each has a different weakness.

| Method | What it measures | Main weakness |
|---|---|---|
| M1 category DiD | H&K YoY log change minus the control categories' in the same store-weeks, pre vs post. The margin effect is the revenue effect minus the cost of the M1 unit response, so it stays consistent with the volume change | Attributes every H&K-specific change in H2 to "the promotion period" |
| M2 dose-response | Store-week gap regressed on the change in promotion coverage (current and 2 lag weeks), depth and in-stock, with store fixed effects | Promoted weeks are chosen, not random |
| M3 event level | Phase 5's promotion uplift per event, net of post-promotion dips and cannibalisation | Baselines are contaminated when promotions run back to back |
| M4 discount accounting | Revenue given away by the higher discount rate with no net volume response; its range uses the M1 units CI bounds (a range, not a confidence interval) | Assumes the M1 volume response |

The M1 and M2 confidence intervals come from a store-level bootstrap with a fixed seed. M3 has no interval, and the M4 range is explained above.

Because M1 and M4 are negative while M2 and M3 are positive, the driver cannot be Root-cause evidence. Temporal association is never read as causation. A holdout-store test or SKU price elasticities would be needed.

## 8. Overlap and exclusive attribution

Phase 5's slices overlap. The cluster stores sell Electronics and Home & Kitchen, and adding the slices counts some of the decline twice.

The exclusive attribution works in three steps:

1. **Cluster excess.** The store-cluster excess (DiD against controls) comes first.
2. **Category drivers.** Each category driver is measured in all stores. The cluster excess already contains only the part of a driver by which the cluster exceeds the control-store rate (the cluster's amount minus what the control-store rate implies for the cluster's size). Only that part, when it has the same sign as the driver, is removed. When the cluster has less of a driver than the controls, nothing is removed, so a driver is never inflated above its measured total. In these data the cluster had less of every driver, so no overlap is removed.
3. **Residual.** A residual closes the total exactly. It is split by where it sits: outside the cluster, each category group's measured change minus the drivers measured there; the remainder is the cluster's change at the control-store rate net of its driver amounts.

Other overlaps:
- Stock-outs and 'Faulty' returns are different ledger lines (lost sales vs refunds), so they are additive. Their overlap on the same store-SKUs is still reported.
- Electronics and Home & Kitchen are disjoint.

The six-cell perimeter matrix (cluster vs other stores × E&T vs H&K vs other) shows the facts that the attribution divides.

## 9. Counterfactual scenarios

These are analytical counterfactuals, not forecasts.

| Scenario | What changes | How it is built |
|---|---|---|
| A | Cluster transactions follow the control stores | Negative of the cluster excess |
| A2 | Every store's H2 transactions follow its own H1 YoY trend | Simple extrapolation (Hypothesis) |
| B | Electronics availability at the prior-year baseline | Full-week lost-sales change; range from the sensitivity variants, including the estimate net of deferred demand (the BR-05 upper bound is not used) |
| C | Returns at the prior-year rate | Arithmetic on the return rate (no range); the 'Faulty' share is stated |
| D | Home & Kitchen promotional behaviour as in the prior year | M1; range across all methods |
| E | Combination | Sum of the mutually exclusive components only |

## 10. Sensitivity

There are 83 variants in total:
- **Lost-sales estimator:** baseline windows, minimum history, seasonality on and off, and the estimate net of deferred demand.
- **Store cluster:** the four control groups and three pre-period windows.
- **Promotions:** three control-category sets, event pre-periods of 2, 4 and 6 weeks, and all four methods.
- **Faulty returns:** four rate bases.

A central estimate is **robust** when every eligible variant has the same sign and lies within ±50% of it. Lost-sales variants whose baseline covers under 90% of the stock-out cells are shown but not counted in the robustness test: they drop cells rather than estimate them.

## 11. Evidence rules

Only the four BRD levels are used.

| Level | Rule in Phase 6 |
|---|---|
| Observed change | Measured directly; no causal mechanism claimed |
| Statistical association | Measured co-movement, or a mechanism that is not robust across methods |
| Root-cause evidence | Mechanism visible in the data, quantified, and robust in sensitivity |
| Hypothesis | Plausible, but the available data cannot test it |

Two checks enforce the rules: no fragile estimate can be labelled Root-cause evidence, and every driver has exactly one level. The report tags each statement FACT, ESTIMATE, STATISTICAL ASSOCIATION or HYPOTHESIS. Model fits (the onset date), DiD counterfactuals and statistical tests are ESTIMATES or associations, never FACT. It marks the store-cluster cause UNRESOLVED.

In this run, only the Electronics & Tech full-week stock-outs reach Root-cause evidence: the mechanism is visible, quantified, and robust across all eligible variants, including the one net of deferred demand. It explains a small share of the decline. Everything else is an Observed change, a Statistical association or a Hypothesis; the size and location of the decline are established, but its larger causes need the additional data listed in the report.

## 12. Validation and tests

- The runner performs 36 checks and stops on any failure. They cover:
  - headline reconciliation to Phase 4, the facts and Phase 5;
  - the perimeter, the attribution and the residual breakdown closing exactly;
  - no driver exceeding its measured total after the overlap step;
  - the H2 week window hard-coded in one rca view matching the configuration;
  - the ratio-DiD identity;
  - controls excluding the cluster;
  - the Phase 5 lost-sales figure matching;
  - supplier, store and product shares adding up;
  - bootstrap intervals containing their estimates;
  - scenario E equalling the exclusive sum;
  - valid evidence levels;
  - no infinite values.
- `tests/test_phase6_rca.py` adds unit tests (change point, ramp, DiD, placebo, robust rule, rate table, overlap, level rule), freeze and freeze-change detection, determinism (a fresh run must reproduce every committed table and the report), independence (code, SQL and runtime opens) and style tests.
- The whole project suite is run, not only the Phase 6 tests.

## 13. Limitations

- There is no footfall, competitor, local-event or store-operations data, so the largest driver's cause cannot be tested.
- Stock is weekly: stock-out duration inside a partial week is unknown, which is why the primary lost-sales figure uses full weeks only. SKU substitution during stock-outs is not measured.
- 'Faulty' is a reason code. There are no QA, batch or RMA data.
- The promotion counterfactual depends on the method. Promotions are not randomised.
- Control stores and categories are themselves exposed to estate-wide conditions. The DiD removes those conditions from the drivers and leaves them in the residual.
- New and continuing SKUs cannot be linked at customer level, so switching between models is a hypothesis.
- The results come from synthetic data and a single year pair.

## 14. Reproducibility

```
python -m src.rca.run_phase6 --engine duckdb      # about 40 seconds; rebuilds the Phase 4 model in memory
python -m src.rca.run_phase6                      # on the SQL Server model built by Phase 4
python -m pytest tests/test_phase6_rca.py
```

Every SQL result is sorted before analysis, and all resampling uses the fixed seed in `config/rca_config.yaml`. Two runs produce byte-identical tables and reports. Only the validation report and the run log differ, because they record run times.
