# Phase 10: Weekly Estate Forecasting

Phase 10 produces a 13-week forward forecast of estate net revenue, one retail week per row, and
publishes the evidence needed to judge it: a rolling-origin back-test over every registered model,
an explicit rule for choosing between them, calibrated intervals, and a validation catalogue that
fails the phase rather than warning about it.

Everything in this phase reads. The warehouse is opened once, for a single `SELECT`, to build the
weekly input. No database object is created or changed.

## 1. The input, and why the old one was rejected

The configured input used to be `reports/phase5/weekly_yoy_full_year.csv`. It cannot support this
phase and was replaced, not patched:

| Requirement | That file |
|---|---|
| `retail_year`, `week_start_date`, `net_revenue` columns | absent |
| Enough history for 52 training weeks plus a 13-week horizon | 52 rows, 2025 only |
| Reconcile to governed H2 2024 and H2 2025 | 2024 is not present at all |

`reports/phase5/weekly_yoy_full_year.csv` is frozen by the Phase 6 manifest and was not modified.
Phase 10 reads its own ungoverned input instead.

The authoritative source is the governed warehouse view `mart.v_performance_store_week`, which
already carries store × retail-week net revenue on the same definition the Phase 4 and Phase 6
reconciliations use: sales revenue less returns value, with returns attributed to their own return
week. Summing that view over stores gives one estate row per retail week.

    python -m src.forecasting.run_phase10 --build-input

produces `reports/phase10/weekly_estate_history.csv` (104 rows, retail years 2024 and 2025) and
`reports/phase10/weekly_estate_history_provenance.csv`, which records the source view, the
database, the row count, the week range, the rounding and the fact that no write was issued.

### The reconciliation gate

The weekly rows are summed over retail weeks 27 to 52 and compared, in `Decimal`, with the approved
governed headline:

| Period | Weekly sum | Approved |
|---|---:|---:|
| H2 2024 | 10,188,727.55 | 10,188,727.55 |
| H2 2025 | 9,457,457.05 | 9,457,457.05 |
| Change | −731,270.50 | −7.177251% YoY |

`contracts.reconcile_h2_headline` raises rather than adjusts: the approved values are constants,
and the input has to match them. The headline is never re-fitted to make a model look better.

### What the input gate checks before anything is trained

Contract columns present; estate grain with no store or category column; no duplicate
(retail_year, retail_week); chronological by `week_start_date`; every week starting on a Monday;
every gap exactly 7 days; at least `minimum_training_weeks + primary_horizon_weeks` rows; and the
two H2 reconciliations above.

## 2. Back-test design

    python -m src.forecasting.run_phase10 --dry-run   # configuration, paths, freeze gates
    python -m src.forecasting.run_phase10             # back-test, selection, forecast, catalogue

104 observed weeks, 10 rolling origins stepping 4 weeks, from a 52-week training window. At every
origin the model sees `values[:train_end]` and predicts the next 13 weeks; the origin's own test
week and everything after it is withheld. Training is the strict prefix before the test window:
the catalogue asserts it rather than trusting it.

Five models are evaluated at every origin, and all four baselines are compared:

| Model | Family | Mean MAE | Mean RMSE | Mean WAPE | Mean MASE |
|---|---|---:|---:|---:|---:|
| B2_seasonal_naive | baseline | 24,143 | 30,302 | 0.0765 | 1.520 |
| B1_naive | baseline | 61,878 | 74,782 | 0.1916 | 3.095 |
| B3_moving_average | baseline | 73,744 | 85,985 | 0.2299 | 3.553 |
| holt_linear | challenger | 110,473 | 126,738 | 0.3405 | 5.801 |
| B4_trend | baseline | 126,345 | 137,176 | 0.3955 | 7.006 |

## 3. The selected-model rule

Stated before the result, because a rule written after the back-test is not a rule:

1. A model is eligible only if it was evaluated at every rolling origin.
2. The best baseline is the eligible baseline with the lowest mean of the selection metric (WAPE).
3. The challenger is promoted only if its mean metric beats that baseline by **more than**
   `challenger_margin` (0.0). A tie does not get the promotion.
4. Ties break on `tie_breakers` (MASE, then RMSE, then MAE), then on registry order.

Result: `holt_linear` did not beat `B2_seasonal_naive` (0.3405 vs 0.0765, improvement −0.2640), so
**the baseline stays**. The winner is recorded with its evidence in
`reports/phase10/forecast_selected_model.csv`.

## 4. The forecast and its intervals

`reports/phase10/forecast_weekly.csv`: 13 weeks from 2025-12-29 (retail week 2026-W01) to
2026-03-23, seasonal-naive point forecasts.

`reports/phase10/forecast_intervals.csv`: 80% and 95% bands. Radii come from the 130 signed
out-of-sample errors `B2_seasonal_naive` produced across the 10 back-test origins, taken as
empirical quantiles. Nothing is widened, smoothed or assumed; if there were not enough errors for
the requested coverage, the run would stop rather than guess.

## 5. Outputs

| File | Contents |
|---|---|
| `weekly_estate_history.csv` | contract-shaped estate × retail-week input |
| `weekly_estate_history_provenance.csv` | source, range, rounding, no-write statement |
| `forecast_backtest_results.csv` | one row per model per origin |
| `forecast_model_comparison.csv` | metrics averaged over origins |
| `forecast_selected_model.csv` | the decision and its evidence |
| `forecast_weekly.csv` | 13-week point forecast |
| `forecast_intervals.csv` | 80% and 95% bands |
| `phase10_validation_checks.csv` | the 29-check gate, all PASS |

Reruns are byte-identical. `tests/test_phase10_forecasting.py::test_runner_is_deterministic_across_repeated_runs`
enforces it.

## 6. Limitations, stated plainly

- **The challenger lost.** Holt linear trend is materially worse than a seasonal naive on this
  series. Nothing was done to rescue it; the rule was applied as written.
- **Two years is a thin base.** 104 weeks gives 10 origins. A seasonal-naive winner on two years of
  data is a weak claim, and the back-test cannot separate genuine seasonality from the single
  2024→2025 decline pattern it has seen once.
- **Intervals are a constant-width empirical band.** The radius is one quantile of pooled absolute
  errors, so it does not widen with horizon step. A 13-week-out error is therefore treated like a
  one-week-out error, which almost certainly understates the true 13-week uncertainty.
- **Net revenue is not forecast causally.** Availability, promotions, returns and footfall are
  known only after the fact and are never assumed into the future; `features.validate_future_features`
  refuses any model that tries.
- **Three observed weeks are short.** Retail weeks 2024-W52 and 2025-W52 carry 6 days and the week
  after 2025-W52 carries 3; the data ends 2025-12-31. The 3-day week is excluded because it is
  outside both closed retail years and would distort every trailing-window and seasonal-lag model.
  The two 6-day weeks are retained because the governed H2 totals already include them.
- **No scenario causal model.** `scenarios.apply_scenario` shifts a baseline by a supplied weekly
  adjustment and is labelled "SCENARIO / SENSITIVITY, NOT A CAUSAL FORECAST". It is not wired into
  the published forecast.
- **The forecast is not a restatement of the Phase 6 root cause.** Phase 6 found that roughly half
  the H2 2025 decline is unexplained by the data. A seasonal-naive forecast carries that unexplained
  level forward; it does not predict that it will continue.
