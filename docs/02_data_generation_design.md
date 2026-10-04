# Phase 2: Data Generation Design

| Item | Detail |
|---|---|
| Project | Retail Performance & Root-Cause Analytics System |
| Company | Brightwater Retail Ltd (fictional, synthetic data) |
| Author | Waleed Bin Umer |
| Version | 1.0 (full dataset generated and validated; awaiting Phase 2 sign-off) |
| Date | 27 September 2026 |
| Depends on | `docs/01_business_requirements.md` |

> This document describes how the synthetic data is produced: datasets, grain, keys, distributions and business rules. It is written for analysts. It deliberately does **not** describe the specific business events planted in the data. Those live in a separate hidden scenario file so that the root-cause analysis in Phase 7 has to discover them from the data.

---

## 1. Purpose and principles

The generator simulates two years of trading for a 20-store Irish retailer and writes the files a real POS, stock and finance system would export. Five principles drive every design decision:

1. **Simulate behaviour, not results.** Demand, stock, promotions and returns are modelled as mechanisms (a customer visits, picks items, finds stock or does not, sometimes returns them). KPIs such as revenue decline are never written directly; they emerge.
2. **Internal consistency.** Units sold in `fact_sales` reconcile exactly to `sold_qty` in `fact_inventory`. Without this, stock-out analysis would be meaningless.
3. **Realistic mess on top of clean truth.** Clean data is generated first, then data-quality problems are planted and every one is logged. This lets Phase 4 be scored objectively.
4. **Everything configurable.** Assumptions live in `config/generator_config.yaml`, not in code.
5. **Reproducible.** A fixed seed gives byte-identical files (tested).

---

## 2. Run modes

| Mode | Stores | SKUs | Period | Output | Approx. sales lines |
|---|---|---|---|---|---|
| `sample` | 4 (S04, S13, S16, S19) | all 600 | 1 Jan 2024 to 31 Dec 2025 | `data/sample/` | ~300,000 |
| `full` | all 20 | all 600 | 1 Jan 2024 to 31 Dec 2025 | `data/raw/` | 1,339,245 (generated) |
| calibration dry run | all 20 | all 600 | 1 Jan 2024 to 31 Dec 2025 | report only, no data files | (in memory) |

**Why the sample is a store sample, not a SKU sample.** A first design sampled 10% of SKUs across all stores. It produced misleading totals: one discontinued SKU's demand moved to successor SKUs outside the sample, and one fast seller dominated the sample's revenue. Keeping all SKUs preserves range changes, cannibalisation, substitution and category mix. The four sample stores cover every format (Standard, Flagship, Compact) and three regions (Dublin, Munster, Connacht). Because the sample is not estate-weighted, **sample-level percentage changes are not estimates of company-level results**.

Commands (from the project root):

```
python -m src.data_generation.generate_data --mode sample
python -m src.data_generation.validate_generated --data data/sample
python -m src.data_generation.calibration          # projected full-scale KPIs, no data written
python -m src.data_generation.calibrate_scenario   # estate-level dry run, EVALUATION ONLY (see below)
python -m src.data_generation.generate_data --mode full
python -m src.data_generation.full_validation_report   # full-data validation, EVALUATION ONLY
python -m pytest
```

**Calibration dry run.** `calibrate_scenario.py` runs the complete 20-store pipeline in memory, with the same seed and code path as `--mode full`, and writes only `reports/phase2_calibration_report.json`. Because generation is deterministic, the full run reproduces those figures exactly (this is tested). The report contains answer-key figures, so it is an evaluation-only asset: analysis code must not read it.

---

## 3. Generator architecture

```
config/generator_config.yaml ─┐
config/_hidden_scenario.yaml ─┤ (scenario file read ONLY by the generator)
                              ▼
calendar_builder ──► weeks, dim_date, day-of-week weights
dimensions       ──► dim_store, dim_product, ranging matrix, store selection
promotions       ──► promotion calendar ──► depth / uplift / pull-forward arrays
demand           ──► expected demand lines per store x SKU x week
scenario         ──► behavioural overrides (traffic, supplier fill rates)
simulation       ──► demand lines ─► weekly stock constraint ─► sold lines + inventory
transactions     ──► baskets, receipts, prices, discounts ─► fact_sales
returns          ──► fact_returns
targets          ──► fact_targets
answer_key       ──► measured impact of hidden behaviours (evaluation only)
dq_injection     ──► planted problems + _planted_issues_log.csv
generate_data    ──► orchestration, logging, CSV output, manifest
validate_generated / calibration ──► checks against the BRD
```

| Module (`src/data_generation/`) | Responsibility |
|---|---|
| `config_loader.py` | Loads the YAML files |
| `calendar_builder.py` | Retail weeks, `dim_date`, day weights, closed days, bank holidays |
| `dimensions.py` | Stores, products, prices, costs, launch/discontinuation, ranging |
| `reference_data.py` | Name parts for products and store managers |
| `promotions.py` | Promotion events, `fact_promotions`, demand multipliers |
| `demand.py` | Seasonality model and expected demand |
| `scenario.py` | Applies hidden behavioural overrides |
| `simulation.py` | Stock-constrained sales and weekly inventory |
| `transactions.py` | Receipts, times, prices, discounts, costs |
| `returns.py` | Returns with lags, reasons, restockability |
| `targets.py` | Finance targets |
| `dq_injection.py` | Planted data-quality problems and log |
| `answer_key.py` | Evaluation-only impact measurement |
| `generate_data.py` | Entry point |
| `validate_generated.py` | Sample validation against the BRD |
| `calibration.py` | Analytical full-scale projection |
| `calibrate_scenario.py` | Estate-level calibration dry run (evaluation only) |
| `reconcile_headline.py` | Recalculates the H2 headline from persisted files and reconciles it to the answer key (evaluation only) |
| `full_validation_report.py` | Builds the full-dataset validation report, including a reproducibility re-run (evaluation only) |

Each component uses its own random stream (seed plus a fixed offset), so changing one component never shifts another component's data.

---

## 4. Dataset dependency order

```
dim_date ─┐
dim_store ├─► ranging ─► promotion calendar ─► expected demand ─► simulation ─┬─► fact_sales ─► fact_returns
dim_product┘                                                                   ├─► fact_inventory
                                                   expected demand (plan) ────►└─► fact_targets
                                                         all tables ─► planted DQ issues ─► CSV files
```

Why this order: demand needs ranging and promotions; sales and inventory must come from one simulation to reconcile; returns need the actual sold lines; targets need a planning view that does not know what actually happened; data-quality problems are planted last so the log can reference final row keys.

---

## 5. Datasets

SQL Server types shown are the intended Phase 3 types.

### 5.1 `dim_store` (20 rows)

**Grain:** one row per store. **PK:** `store_id`.

| Column | Type | Notes |
|---|---|---|
| store_id | VARCHAR(3) | S01 to S20 |
| store_name, town, county | VARCHAR(50) | |
| region | VARCHAR(20) | Dublin, Leinster, Munster, Connacht, Ulster (ROI) |
| store_format | VARCHAR(10) | Flagship, Standard, Compact |
| floor_area_m2 | INT | format size +/- 10% |
| open_date | DATE | |
| manager_name | VARCHAR(50) | fictional |
| headcount_fte | DECIMAL(4,1) | format level +/- 10% |
| weekly_trading_hours | INT | |
| latitude, longitude | DECIMAL(9,4) | town-level, for maps |

### 5.2 `dim_product` (600 SKUs)

**Grain:** one row per SKU. **PK:** `product_id`. **FK:** none (supplier is an attribute).

| Column | Type | Notes |
|---|---|---|
| product_id | VARCHAR(6) | P00001 to P00600 |
| product_name | VARCHAR(80) | brand + variant + item |
| category, subcategory | VARCHAR(40) | 7 categories, 39 subcategories |
| brand | VARCHAR(30) | |
| supplier_id, supplier_name | VARCHAR | 15 suppliers |
| list_price | DECIMAL(10,2) | current (2025) price, excl. VAT |
| unit_cost | DECIMAL(10,2) | current (2025) standard cost |
| launch_date | DATE | always a Monday |
| discontinued_date | DATE, nullable | always a Monday |
| status | VARCHAR(12) | Active, Discontinued |

Historical prices are carried on each sales line (`unit_price`, `unit_cost`), which is how a POS extract behaves.

### 5.3 `dim_date` (731 rows)

**Grain:** one row per calendar day, 1 Jan 2024 to 31 Dec 2025. **PK:** `date_key` (INT, yyyymmdd).

Columns: `date`, `day_of_week` (1 = Monday), `day_name`, `is_weekend`, `calendar_month`, `month_name`, `calendar_quarter`, `calendar_year`, `retail_year`, `retail_week`, `retail_week_start`, `retail_half` (H1 = weeks 1 to 26), `is_bank_holiday`, `holiday_name`, `is_trading_day`, `same_day_last_year` (date minus 364 days).

**Retail calendar:** retail year 2024 starts Monday 1 Jan 2024; retail year 2025 starts Monday 30 Dec 2024. Week N of 2025 therefore has exactly the same weekdays as week N of 2024, which makes the H2 comparison (weeks 27 to 52) week-aligned. 29 to 31 Dec 2025 fall in retail 2026 week 1.

### 5.4 `fact_sales` (POS transaction lines)

**Grain:** one row per receipt line. **PK:** (`transaction_id`, `line_number`). **FKs:** `store_id` → dim_store, `product_id` → dim_product, `transaction_date` → dim_date, `promotion_id` → fact_promotions.

| Column | Type | Notes |
|---|---|---|
| transaction_id | VARCHAR(20) | `S04-20250714-00123` = store, date, sequence by time |
| line_number | INT | 1..n within the receipt |
| transaction_date | DATE (raw: text) | text in the raw file because of legacy formats |
| transaction_time | TIME | HH:MM |
| store_id, product_id | VARCHAR | |
| category | VARCHAR(40) | POS category text (denormalised, not trusted) |
| quantity | INT | |
| unit_price | DECIMAL(10,2) | excl. VAT, price on the day |
| discount | DECIMAL(10,2) | line discount in EUR |
| revenue | DECIMAL(10,2) | quantity x unit_price - discount |
| unit_cost, cost | DECIMAL(10,2) | standard cost on the day; cost = quantity x unit_cost |
| margin | DECIMAL(10,2) | revenue - cost |
| promotion_id | VARCHAR(8), nullable | |
| extract_batch_id | VARCHAR(20) | daily batch `B20250715`; late file `LATE-...` |
| extract_timestamp | DATETIME | when the row reached the extract |

`fact_sales_late_batch.csv` has the same layout and holds sales delivered after the main extract was cut.

### 5.5 `fact_inventory` (weekly stock snapshots)

**Grain:** one row per store x SKU x retail week (closing snapshot on Sunday), for SKUs ranged in the store while they have a stock position. **PK:** (`store_id`, `product_id`, `snapshot_date`).

| Column | Type | Notes |
|---|---|---|
| snapshot_date | DATE | Sunday |
| retail_year, retail_week | INT | |
| store_id, product_id | VARCHAR | |
| opening_stock | INT | = previous week's closing stock |
| received_qty | INT | deliveries at the start of the week |
| sold_qty | INT | units sold (stock system view) |
| adjustment_qty | INT | shrinkage, range-exit write-offs (<= 0) |
| closing_stock | INT | the `inventory_level` KPI input |

**Identity:** `closing = opening + received - sold + adjustment`. Returned goods go to a central returns hub and do not re-enter store stock (a documented assumption).

### 5.6 `fact_returns`

**Grain:** one row per returned line. **PK:** `return_id`. **FKs:** `store_id` (store of return), `product_id`, (`original_transaction_id`, `original_line_number`) → fact_sales.

| Column | Type | Notes |
|---|---|---|
| return_id | VARCHAR(8) | R0000001 |
| return_date | DATE | |
| store_id | VARCHAR(3) | usually the store of sale; sometimes another store in the region |
| original_transaction_id, original_line_number | nullable | null for legitimate no-receipt returns (about 3%) |
| product_id | VARCHAR(6) | |
| return_quantity | INT | full line or partial |
| refund_value | DECIMAL(10,2) | line revenue x returned qty / sold qty (discount honoured) |
| return_reason | VARCHAR(30) | Changed mind, Faulty, Not as described, Damaged, Gift return |
| restockable_flag | BIT | used for the COGS credit in the BRD definition |

### 5.7 `fact_promotions`

**Grain:** one row per promotion x SKU x store. **PK:** (`promotion_id`, `product_id`, `store_id`).

Columns: `promotion_id`, `promotion_name`, `promotion_type` (Percent Off, Clearance), `product_id`, `store_id`, `start_date`, `end_date` (whole retail weeks), `discount_pct`.

### 5.8 `fact_targets`

**Grain:** one row per store x retail week (retail years 2024 and 2025). **PK:** (`store_id`, `retail_year`, `retail_week`).

Columns: `store_id`, `retail_year`, `retail_week`, `week_start_date`, `week_end_date`, `target_net_revenue` (EUR, rounded to 10), `target_version`, `target_set_date`.

### 5.9 Expected row counts

| File | Sample (4 stores, actual) | Full (20 stores, generated) |
|---|---|---|
| dim_store | 20 | 20 |
| dim_product | 610 (600 + 10 planted duplicates) | 610 |
| dim_date | 731 | 731 |
| fact_sales | 299,800 | 1,339,245 |
| fact_sales_late_batch | 2,198 | 2,270 |
| fact_inventory | 197,380 | 939,437 |
| fact_returns | 7,841 | 34,733 |
| fact_promotions | 10,009 | 49,434 |
| fact_targets | 415 | 2,079 |

The full-run counts were first projected by the calibration dry run and then confirmed exactly by the generated files. The full dataset is 228 MB of CSV and generates in about 30 seconds; it is git-ignored and reproducible from config and seed.

---

## 6. Generation logic

### 6.1 Demand model

Expected demand lines for store *s*, SKU *p*, week *w*:

```
E[w,s,p] = base_lines x format_factor x region_factor x store_level x store_trend(w)
         x chain_shock(w) x store_week_shock(w,s)
         x category_share x SKU_share(s,p,w)
         x seasonality(category, retail_week) x market_trend(w) x price_response(p,w)
         x promotion_multiplier(w,s,p) x cell_noise
```

| Component | Setting | Why |
|---|---|---|
| base_lines | 660 lines/week for a Standard store | calibrated to the BRD scale (about EUR 20M, 1.35M lines) |
| format factor | Flagship 1.80, Standard 1.00, Compact 0.55 | store size and footfall |
| region factor | Dublin 1.08 ... Ulster (ROI) 0.93 | catchment wealth and density |
| store level | lognormal, sigma 0.08 | location quality differs between stores |
| store trend | normal, sigma 3% per year | some stores grow, some decline naturally |
| chain shock | lognormal, sigma 3.5% weekly | weather, consumer confidence |
| store-week shock | lognormal, sigma 6% | local events, staffing |
| SKU share | popularity x ranged x live, normalised within category per store-week | launches cannibalise; exits hand demand to remaining SKUs |
| seasonality | see 6.2 | |
| market trend | -0.5% per year | soft discretionary market |
| price response | (new price / old price) ^ -0.8 from 1 Jan 2025 | customers react to the annual price review |
| cell noise | lognormal, sigma 0.20 | SKU-level randomness |

All lognormal shocks are mean-preserving (they do not bias totals). The number of demand lines is Poisson around E.

### 6.2 Seasonality

Each category has an index over retail weeks 1 to 52, normalised to mean 1:

`index = off_season_base + Q4 peak (Gaussian, centred wk 50) + Black Friday (wk 48) + summer peak (wk 21) + back-to-school (wk 34) - January dip`

| Category | Shape |
|---|---|
| Home & Kitchen | mild Q4 peak, Black Friday, January dip |
| Electronics & Tech | strong Black Friday and Christmas |
| Health & Beauty | nearly flat, Christmas gifting |
| Toys & Games | very strong Q4 (December about 3x June) |
| Garden & Outdoor | spring/summer; low base in winter |
| Stationery & Crafts | back-to-school in August |
| Seasonal & Gifts | about 70% of the year's revenue in Q4 |

Day of week: Saturday busiest (21%), Monday and Tuesday quietest (11%). Bank holidays x1.2, St Stephen's Day x1.45, Christmas Eve x1.3, closed on Christmas Day. Receipts are timed between 09:00 and 21:00 with lunchtime and early-evening peaks.

### 6.3 Products, prices and costs

- Prices are drawn per SKU around a category median x subcategory multiplier (lognormal, sigma 0.45), clipped to the BRD price band, converted to a VAT-inclusive shelf price ending in 9, then back to the ex-VAT price.
- Annual price review on 1 Jan 2025: +1% (Electronics) to +3.5% (Health & Beauty). Standard costs rise 2%.
- Unit cost = price x (1 - margin), margin around the category target (lognormal, sigma 0.12).
- Popularity is lognormal (sigma 1.0) and weaker for expensive items (price ^ -0.45), which gives realistic long-tail sales.
- About 5% of SKUs launch during 2025 and about 4% are discontinued during the period, which creates natural mix change.

### 6.4 Ranging

Flagships range every SKU; Standard stores about 86%; Compact stores about 60%. Each store ranks SKUs by popularity with a local-taste random term, so ranges overlap but are not identical.

### 6.5 Promotions

- Each category runs chain-wide events on a cadence (default a new 2-week event every 6 weeks), covering about 22% of the category's SKUs, chosen with a preference for popular SKUs. About 92% of stores take part in each event.
- Depths 10% to 25%. Post-Christmas clearance on Seasonal & Gifts (40% to 50%) in retail weeks 1 to 3.
- **Uplift** during the promotion = 1 + elasticity x depth + display effect (default elasticity 2.2, display 0.10).
- **Pull-forward:** customers stock up, so the following 2 weeks lose a share of the incremental units (default 30%, higher for durable or stockpile-able categories). This is why a promotion's true value must be measured over the whole promo-plus-dip window, not just the promo week.
- Non-promotional markdowns (damaged box, price match) on 1.5% of lines at 10% to 20%.

### 6.6 Inventory and stock-outs

Weekly periodic review with an order-up-to level:

```
order_up_to = ceil(forecast x cover_weeks + 1.3 x sqrt(forecast)), minimum 2 units on display
received    = Binomial(order_up_to - opening_stock, supplier fill rate)
```

- Cover: Flagship 1.6, Standard 1.8, Compact 2.1 weeks.
- The replenishment forecast knows seasonality and planned promotions but has 18% error, which creates natural stock-outs (about 95% availability in 2024).
- Supplier fill rate: normally about 97% per supplier-week.
- Within a week, customer lines are served in day order against the stock on the shelf. A line that finds no stock is lost, except that 25% of customers buy a substitute from the same subcategory if it is in stock.
- Shrinkage: 1.5% chance per store-SKU-week of losing one unit. When a SKU exits the range, remaining stock is written off.

### 6.7 Transactions and baskets

Sold lines in a store-day are shuffled and cut into receipts: each line starts a new receipt with probability 0.62 (about 1.6 lines per receipt). Quantity per line depends on category (Stationery and Health & Beauty more multi-buy). Resulting UPT is about 2.1 and AOV about EUR 44 to 46.

### 6.8 Returns

- Base probability a line is returned: 0.8% (Stationery) to 5% (Electronics). Christmas purchases (15 Nov to 24 Dec) x1.8, with returns allowed until 31 January.
- Lag: gamma distribution (median about 6 days), capped by the 30-day policy.
- 85% full-quantity returns; refunds honour the discount paid.
- 6% returned to another store in the same region; 3% no-receipt returns.
- Restockable reasons: Changed mind, Not as described, Gift return.

### 6.9 Targets

Finance's planning model uses the demand model **without** random shocks, **without** knowledge of future store trends or unplanned events, and with the promotion plan known when the budget was set (November of the prior year). Planned net revenue is uplifted by plan growth (2024: +2%, 2025: +3%), then a planning error is applied per store (sigma 3%) and per week (sigma 5%). Targets are therefore realistic stretch targets, not a copy of actuals.

### 6.10 Scenario hooks

The generator can apply time-bound behavioural overrides from a separate file: store footfall multipliers, supplier fill-rate changes, promotion policy changes, return-probability changes and delivery-timing changes. The content of that file is intentionally not documented here. Analysis code must not read it, which is enforced by an automated test.

---

## 7. Planted data-quality problems

After the clean data is built, realistic problems are planted at the rates in `config/generator_config.yaml` (`data_quality_issues`). Types include duplicate receipts, missing and invalid keys, null prices and discounts, incorrect and negative prices, negative and extreme quantities, malformed and out-of-range dates, a legacy date format, revenue that does not match its components, inconsistent category and region labels, duplicate product records, broken stock flows, negative stock, missing and duplicate snapshots, invalid return references, impossible returns, promotions ending before they start, duplicate and missing targets, late-arriving and missing batches.

**Rules:**
- Row-level problems are drawn from disjoint rows (one planted problem per row) so evaluation is unambiguous.
- Every problem is written to `_planted_issues_log.csv` with: `issue_id, table_name, file_name, issue_type, row_key, column_name, original_value, planted_value, expected_check, notes`.
- Some problems have knock-on effects that are realistic, not separately planted: for example, returns that reference a receipt in a missing batch appear orphaned, and inventory shows sales that the POS extract does not.

The log is an **evaluation key for Phase 4**. The data-quality framework must find these problems from the data, not from the log.

---

## 8. Key modelling decisions

| Decision | Alternative considered | Why this choice |
|---|---|---|
| Line-level demand served against weekly stock | Generate sales and stock independently | Only this makes sales and stock reconcile, so stock-out analysis is valid |
| Weekly stock snapshots | Daily snapshots | Matches the BRD assumption and keeps ~1M rows; daily would be ~7M |
| Week-aligned retail calendar | Calendar months | Removes day-of-week distortion from YoY comparisons |
| Category demand shared across live SKUs | Each SKU independent | Launches must cannibalise, otherwise range changes create fake growth (found and fixed during calibration) |
| Targets from a plan view without shocks | Targets = actuals x growth | Targets must not know the future; otherwise target variance explains nothing |
| Returns go to a central hub | Returns restock the store | Keeps the stock identity simple and matches many chains; restockable flag still feeds COGS |
| Transaction ID encodes store and date | Random IDs | Mirrors real POS keys and allows a documented recovery rule for missing store IDs |
| Store-based sample | SKU-based sample | See section 2 |
| Separate random stream per component | One global stream | Changing one component does not silently change others |

---

## 9. Validation

`validate_generated.py` builds a **clean view** (raw rows minus every row named in the planted log, duplicates collapsed, late batch added) and runs 79 checks in 14 groups: keys, transaction integrity, referential integrity, dates, business rules, sales-to-inventory reconciliation, KPI identities, expected ranges, seasonality, store/product rules, planted-issue presence, headline (reported vs underlying net revenue), estate calibration and scenario separation.

**Reported vs underlying headline.** Validation computes H2 net revenue two ways from the files: *reported* uses the main extract only (what a pipeline that ignores the late file would show), *underlying* adds the late batch. The difference must equal the late batch's revenue exactly. This separation (reporting artefact vs genuine trading change) is something Phase 4 and Phase 7 must reproduce independently. `pytest` wraps these checks plus unit tests and a reproducibility test.

Results are written to `reports/phase2_sample_validation.csv` and `reports/phase2_sample_validation_kpis.csv`.

**Full dataset.** The same 79 checks run against the persisted 20-store files (`reports/phase2_full_validation.csv`). `full_validation_report.py` adds file sizes, row counts against the projection, a headline recalculated from the files and a byte-for-byte reproducibility re-run, written to `reports/phase2_full_validation_report.md` and `.json`. Those reports contain answer-key figures and are evaluation-only.

**Validator correction during the full run.** One check (return lag) initially failed on the full data because it read the original sale's date from the sale line's `transaction_date`, which for two lines carried a planted out-of-range date. The check now takes the sale date from `transaction_id`, which is authoritative. This was a validator defect only; no generated data changed.

---

## 10. Known limitations

- About 60 receipts per store per day is low for a real chain but consistent with a small specialist retailer and keeps the project laptop-sized.
- No customer IDs: receipts are the proxy for visits (BRD assumption 7).
- One VAT rate (23%) is applied to all products; in Ireland some categories (for example, some children's items) are zero-rated.
- Weather, competitors and footfall are not modelled as separate data sources; weather and consumer mood appear only as random shocks, and no footfall or competitor files are produced.
- The sample is not estate-weighted, so its percentage changes are not company-level estimates.
- Random streams are separated by component, not by year. Changing a 2025 setting can therefore reshuffle 2024 noise slightly (about 0.1% of the H2 2024 base during calibration). A per-year stream would remove this but was not needed for this project.
