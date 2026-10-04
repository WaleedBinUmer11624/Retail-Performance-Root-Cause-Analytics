# Retail Performance & Root-Cause Analytics System
## Phase 1: Business Requirements Document (BRD)

| Item | Detail |
|---|---|
| Project | Retail Performance & Root-Cause Analytics System |
| Company | Brightwater Retail Ltd (fictional) |
| Author | Waleed Bin Umer |
| Version | 1.0 |
| Date | 27 September 2026 |
| Status | Approved |
| Approved by | Waleed Bin Umer (project owner), 27 September 2026 |

> All company, store and product data in this project is synthetic. It was generated to simulate a realistic Irish multi-store retailer and does not represent any real business.

---

## 1. Company Scenario

**Brightwater Retail Ltd** is a mid-market Irish retailer selling home, tech and lifestyle products. Founded in 2009 and headquartered in Dublin, it trades from **20 stores** across the Republic of Ireland in three formats.

| Format | Stores | Typical size | Profile |
|---|---|---|---|
| Flagship | 3 | 1,200 m² | City-centre / major shopping centre, full range |
| Standard | 10 | 700 m² | Retail parks and regional towns, core range |
| Compact | 7 | 350 m² | Smaller towns, reduced range |

### 1.1 Store estate

| Store ID | Store | County | Region | Format |
|---|---|---|---|---|
| S01 | Dublin Grafton Street | Dublin | Dublin | Flagship |
| S02 | Dublin Dundrum | Dublin | Dublin | Flagship |
| S03 | Dublin Blanchardstown | Dublin | Dublin | Standard |
| S04 | Dublin Swords | Dublin | Dublin | Standard |
| S05 | Dublin Tallaght | Dublin | Dublin | Standard |
| S06 | Bray | Wicklow | Leinster | Compact |
| S07 | Naas | Kildare | Leinster | Standard |
| S08 | Navan | Meath | Leinster | Compact |
| S09 | Drogheda | Louth | Leinster | Standard |
| S10 | Kilkenny | Kilkenny | Leinster | Compact |
| S11 | Wexford | Wexford | Leinster | Compact |
| S12 | Athlone | Westmeath | Leinster | Standard |
| S13 | Cork Patrick Street | Cork | Munster | Flagship |
| S14 | Cork Mahon Point | Cork | Munster | Standard |
| S15 | Limerick | Limerick | Munster | Standard |
| S16 | Waterford | Waterford | Munster | Standard |
| S17 | Tralee | Kerry | Munster | Compact |
| S18 | Galway | Galway | Connacht | Standard |
| S19 | Sligo | Sligo | Connacht | Compact |
| S20 | Letterkenny | Donegal | Ulster (ROI) | Compact |

Store attributes to be held: store ID, name, town, county, region, format, floor area, open date, manager, headcount (FTE), weekly trading hours.

### 1.2 Product range

Approximately **600 active SKUs** across 7 categories. Compact stores range roughly 60% of SKUs.

| Category | Approx. SKUs | Price band (EUR) | Target margin | Seasonality |
|---|---|---|---|---|
| Home & Kitchen | 140 | 5 to 150 | 45% | Mild Q4 peak |
| Electronics & Tech | 90 | 15 to 600 | 22% | Strong Q4 peak |
| Health & Beauty | 110 | 3 to 60 | 50% | Flat, Q4 gifting |
| Toys & Games | 80 | 5 to 120 | 40% | Very strong Q4 peak |
| Garden & Outdoor | 60 | 5 to 250 | 42% | Spring / summer peak |
| Stationery & Crafts | 70 | 1 to 40 | 55% | Back-to-school (Aug / Sep) |
| Seasonal & Gifts | 50 | 3 to 80 | 48% | Q4 only |

Product attributes to be held: product ID, SKU name, category, subcategory, brand, supplier, list price, unit cost, launch date, status.

### 1.3 Trading facts

- **Data period:** 1 January 2024 to 31 December 2025 (104 trading weeks). Weeks run Monday to Sunday.
- **Currency:** EUR. All revenue is reported **excluding VAT**.
- **Scale:** roughly EUR 18 to 20 million annual revenue; average basket about EUR 45.
- **Operational data available:** point-of-sale transactions (line level), weekly stock snapshots, returns, promotion calendar, weekly store targets set by Finance.

---

## 2. Business Problem

### 2.1 Situation

Brightwater's H2 2025 board pack shows that **net revenue for July to December 2025 is approximately 8% below July to December 2024**. On a half-year base of roughly EUR 10 million, this is a shortfall of around EUR 0.8 million.

Management can see **what** happened. They cannot yet answer:

- **Why** did revenue fall?
- **Where** did the decline originate (which stores, regions, categories, SKUs, weeks)?
- **What** should be done first, and what needs further investigation?

Current reporting is a set of weekly spreadsheets built by hand from POS exports. Store, stock and returns data are reported separately, numbers differ between reports, and no one owns data quality.

### 2.2 Problem statement

> Build a trusted, repeatable analytics system that explains the H2 2025 revenue decline by quantifying the contribution of each measurable driver, locating where each driver originated, and separating proven findings from hypotheses, so that management can prioritise action.

### 2.3 Comparison basis

To avoid misleading comparisons, the headline decline is measured as:

- **Primary:** 26 week-aligned trading weeks of H2 2025 vs the equivalent 26 weeks of H2 2024 (same weekdays, so day-of-week mix does not distort the result).
- **Like-for-like (LFL):** stores trading in both full periods. All 20 stores traded throughout, so LFL equals total, but the logic is built so this holds if stores open or close.
- **Metric:** Net Revenue (defined in Section 5).

---

## 3. Stakeholders

| Stakeholder | Role | What they need | Primary question |
|---|---|---|---|
| CEO | Decision-maker | One-page answer: size of the problem, top causes, actions | What should we do first? |
| CFO / FP&A | Owns targets and the numbers | Reconciled revenue, margin, target variance | Can I trust these numbers, and which stores miss targets? |
| Head of Retail Operations | Runs the store estate | Store and region performance, staffing context | Which stores are driving the decline and why? |
| Regional Managers (4) | Manage store groups | Store drill-downs, weekly trend | Which of my stores need attention this week? |
| Category Managers | Own ranges and pricing | Category / SKU performance, price and mix | Which categories and SKUs are underperforming? |
| Supply Chain / Inventory Manager | Stock flow and suppliers | Availability, stock-outs, cover | Are stock-outs costing us sales, and where? |
| Marketing / Promotions Manager | Plans promotions | Promotion uplift vs cost | Are promotions actually growing sales? |
| Customer Service / Returns | Handles returns | Return rates and reasons | Are returns rising, and in which products? |
| Data / BI Team | Builds and maintains the system | Pipeline, data-quality monitoring, documentation | Is the data complete and correct this week? |

---

## 4. Business Requirements

### 4.1 Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| BR-01 | Report Net Revenue, Gross Margin, Transactions, AOV and UPT by day, week, month, store, region, format, category and SKU. | Must |
| BR-02 | Compare any period with the prior period (WoW, MoM) and the same period last year (YoY), including like-for-like. | Must |
| BR-03 | Decompose the change in revenue into measurable drivers (transactions, basket value, returns, availability, promotions, mix) expressed in percentage points and EUR. | Must |
| BR-04 | Identify which stores, regions and categories contribute most to the decline (contribution analysis). | Must |
| BR-05 | Measure stock availability and estimate sales lost to stock-outs, clearly labelled as an estimate with its method. | Must |
| BR-06 | Measure promotion performance: uplift vs a non-promoted baseline, discount cost and margin impact. | Must |
| BR-07 | Measure returns by value and rate, by store, category and SKU. | Must |
| BR-08 | Compare actual revenue with weekly targets; flag stores that miss targets persistently. | Must |
| BR-09 | Classify every root-cause finding by evidence level (Section 6.2). | Must |
| BR-10 | Run automated data-quality checks and publish a Data Quality Report before data reaches reporting. | Must |
| BR-11 | Generate short, plain-English management insights, each traceable to a calculated figure. | Should |
| BR-12 | Flag anomalous store-weeks and compare simple forecast vs actual. | Should |
| BR-13 | Provide drill-through from company level to store and SKU level in Power BI. | Should |
| BR-14 | Optional: let users ask natural-language questions answered only from verified outputs. | Could |

### 4.2 Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Trust:** Power BI totals must reconcile to SQL totals (tolerance: exact match on revenue, units and transactions). |
| NFR-02 | **Transparency:** no bad data is silently removed. Every issue is logged, and every correction follows a documented rule. |
| NFR-03 | **Reproducibility:** the full pipeline runs end-to-end from raw files with one command. |
| NFR-04 | **Refresh:** designed for a weekly refresh (Monday morning, covering the previous trading week). |
| NFR-05 | **Maintainability:** modular, reusable functions; logging and exception handling; version control in Git. |
| NFR-06 | **Performance:** full pipeline completes in under 15 minutes on a standard laptop. |
| NFR-07 | **Documentation:** every KPI has one written definition used identically in SQL, Python and DAX. |

### 4.3 Scope

**In scope:** store sales, products, stock, returns, promotions, targets, store attributes, data quality, root-cause analysis, dashboard, automated insights.

**Out of scope:** online sales, customer-level / loyalty data, footfall counters, supplier invoices, labour scheduling detail, competitor data, weather data. Where these would explain a finding, the finding is recorded as a **hypothesis requiring further data**, not a conclusion.

### 4.4 Assumptions and constraints

1. Revenue is recorded excluding VAT; discounts are applied at line level.
2. Returns are recorded against the store where they are returned, on the return date, and linked to the original transaction where possible.
3. Stock is captured as a weekly closing snapshot per store and SKU, not daily.
4. Targets are set weekly per store by Finance before the year starts.
5. Unit cost is a standard cost per SKU per period.
6. The project runs on free tooling (see Section 7).
7. Because there is no customer ID, "transactions" (receipts) is used as the proxy for customer visits.

---

## 5. KPI Definitions

One definition per KPI. The same logic will be implemented in SQL, Python and DAX.

### 5.1 Sales and margin

| KPI | Definition / formula | Notes |
|---|---|---|
| Gross Sales | SUM(quantity x unit_price) | Before discount, excl. VAT |
| Discount Value | SUM(discount) | Line-level discounts |
| Sales Revenue | Gross Sales - Discount Value | Before returns |
| Returns Value | SUM(refund value of returned items) | From fact_returns |
| **Net Revenue** | Sales Revenue - Returns Value | **Headline metric** |
| COGS | SUM(quantity x unit_cost) - cost of returned-to-stock items | |
| Gross Margin (EUR) | Net Revenue - COGS | |
| Gross Margin % | Gross Margin / Net Revenue | |
| Transactions | COUNT(DISTINCT transaction_id) | Proxy for customer visits |
| Average Order Value (AOV) | Sales Revenue / Transactions | Also called ATV |
| Units per Transaction (UPT) | Units sold / Transactions | |
| Average Selling Price (ASP) | Sales Revenue / Units sold | |

**Key identity used in root-cause analysis:**

```
Sales Revenue = Transactions x UPT x ASP
Net Revenue   = Sales Revenue - Returns Value
```

This identity lets the revenue change be split exactly into a traffic effect, a basket-size effect, a price/mix effect and a returns effect.

### 5.2 Growth and comparison

| KPI | Definition |
|---|---|
| YoY Growth % | (Current period - Same period last year) / Same period last year |
| LFL Growth % | YoY Growth % restricted to stores trading in both full periods |
| WoW / MoM Growth % | Change vs the immediately preceding week / month |
| Rolling 4-Week Revenue | Net Revenue summed over the current and previous 3 weeks |
| Contribution to Change (pp) | (Segment change in EUR) / (Total prior-period revenue) x 100 |
| Share of Decline % | Segment change in EUR / Total change in EUR |

### 5.3 Inventory and availability

| KPI | Definition | Notes |
|---|---|---|
| Stock Availability % | Ranged store-SKU-weeks with closing stock > 0 / All ranged store-SKU-weeks | Only SKUs ranged in that store |
| Stock-out Rate % | 1 - Stock Availability % | |
| Sell-through % | Units sold / (Units sold + Closing stock) for the period | |
| Weeks of Cover | Closing stock / Average weekly units sold (last 4 weeks) | |
| Estimated Lost Sales (EUR) | For stock-out store-SKU-weeks: expected weekly sales (baseline from in-stock weeks) - actual sales | **Estimate**, method disclosed |

### 5.4 Promotions, returns and targets

| KPI | Definition |
|---|---|
| Promo Revenue Share % | Sales Revenue on promoted lines / Sales Revenue |
| Promo Uplift % | (Units during promotion - Baseline units) / Baseline units, baseline = same SKU and store, comparable non-promoted weeks |
| Promo Discount Cost | Discount Value on promoted lines |
| Incremental Promo Margin | Incremental gross margin from uplift - Promo Discount Cost |
| Return Rate % (value) | Returns Value / Sales Revenue |
| Return Rate % (units) | Returned units / Units sold |
| Target Achievement % | Net Revenue / Target Revenue |
| Revenue Variance to Target | Net Revenue - Target Revenue |
| Target Miss Streak | Consecutive weeks a store is below 100% of target |

### 5.5 Data quality

| KPI | Definition |
|---|---|
| DQ Check Pass Rate % | Checks with status PASS / Total checks run |
| Record Failure Rate % | Failed records / Records checked, per check |
| Revenue Affected by DQ Issues (EUR) | Revenue on records that failed at least one check |

---

## 6. Analytical Questions

### 6.1 Stakeholder questions and how each will be answered

| # | Question | Main measures | Method |
|---|---|---|---|
| Q1 | Why has revenue declined? | Net Revenue, driver bridge | Revenue decomposition (traffic x UPT x ASP - returns), then drill into drivers |
| Q2 | Which stores are driving the decline? | Contribution (pp), Share of Decline % | Store contribution analysis, ranking, region / format rollups |
| Q3 | Which categories are underperforming? | Category YoY, contribution, margin | Category contribution analysis, mix vs rate effect |
| Q4 | Are stock-outs contributing to lost sales? | Availability %, Estimated Lost Sales | Compare availability YoY; estimate lost sales on stock-out weeks for high-revenue SKUs |
| Q5 | Have customer transactions declined? | Transactions, YoY | Transactions by store / week; separate traffic from basket effects |
| Q6 | Has average transaction value changed? | AOV, UPT, ASP | Split AOV change into basket size (UPT) and price / mix (ASP) |
| Q7 | Are returns affecting performance? | Returns Value, Return Rate % | Returns YoY by store, category, SKU; pp contribution to decline |
| Q8 | Are promotions actually increasing sales? | Promo Uplift %, Incremental Promo Margin | Baseline vs promo comparison; check for post-promo dip (pull-forward) |
| Q9 | Which stores consistently miss targets? | Target Achievement %, Miss Streak | Weekly target variance; flag stores missing in, for example, 8 or more of the last 13 weeks |
| Q10 | What should management investigate first? | All of the above | Prioritise drivers by EUR impact x evidence strength x controllability |

### 6.2 Evidence standard

Every finding in the root-cause analysis is tagged with one of four evidence levels. This prevents correlation being presented as causation.

| Level | Meaning | Example wording |
|---|---|---|
| **Observed change** | A measured change in a metric. No claim about cause. | "Transactions fell 5.1% YoY in H2 2025." |
| **Statistical association** | Two measures move together (correlation, co-occurrence). Not proof of cause. | "Stores with larger availability drops also had larger revenue drops (r = -0.6)." |
| **Root-cause evidence** | A mechanism is directly visible in the data and the effect is quantified with a defensible method. | "In store-SKU-weeks with zero stock, sales were zero; estimated lost sales of EUR X based on in-stock baseline." |
| **Hypothesis** | A plausible explanation that the available data cannot confirm. Requires further investigation or new data. | "The transaction decline in Dublin suburban stores may reflect new local competition. Footfall and competitor data needed to confirm." |

---

## 7. Proposed Architecture

### 7.1 Data flow

```
[1] Python data generator  -->  data/raw/*.csv  (messy, with planted issues)
                                    |
[2] Python data-quality checks  -->  reports/data_quality_report.csv
                                    |
[3] Python cleaning (documented rules, every fix logged)
                                    |
[4] Load to SQL Server staging schema (stg)
                                    |
[5] SQL transformations  -->  star schema (dw): dimensions + facts
                                    |
[6] SQL validation (row counts, totals, key integrity)
                                    |
[7] SQL analysis views (mart)  <--  Python analytics, anomaly detection, insight generation
                                    |
[8] Power BI (import mode) reads mart / dw views
```

### 7.2 Technology choices

| Layer | Tool | Why this and not something else |
|---|---|---|
| Data generation, DQ, orchestration | Python 3.11+ (pandas, numpy) | Flexible for rule-based checks, logging and synthetic data; industry-standard for analysts |
| Storage and modelling | SQL Server 2022 Developer or Express (free) | SQL Server is common in Irish enterprise retail and pairs naturally with Power BI. Express has a 10 GB limit, well above this project's needs |
| Query tool | SQL Server Management Studio (SSMS) | Standard SQL Server client |
| Python to SQL | SQLAlchemy + pyodbc | Reliable bulk loading and querying |
| Reporting | Power BI Desktop | Required BI tool; import mode is fast and suits this data volume |
| Testing | pytest | Unit tests for DQ rules and KPI calculations |
| Version control | Git + GitHub | Portfolio and change history |
| Scheduling (optional) | Windows Task Scheduler running `run_pipeline.py` | Honest, simple automation. Airflow, Spark or cloud services are not needed at this scale and are deliberately not used |

### 7.3 Why SQL and Python are split this way

- **SQL** does set-based work on the modelled data: joins, aggregations, window functions, the star schema, KPI views. This is where the business logic lives, so it is visible, testable and reusable by Power BI.
- **Python** does work that SQL is poor at: generating data, running a configurable library of data-quality checks with logging, statistical tests, anomaly detection, forecasting and text generation.
- **Power BI** presents results. DAX measures are kept simple and reconcile to SQL.

### 7.4 Planned data volumes

| Table | Grain | Approx. rows |
|---|---|---|
| dim_store | One row per store | 20 |
| dim_product | One row per SKU | ~600 (plus planted duplicates) |
| dim_date | One row per calendar day | 731 |
| fact_sales | One row per transaction line | ~1.2 to 1.5 million |
| fact_inventory | One row per store, SKU, week (closing snapshot) | ~1 million |
| fact_returns | One row per returned line | ~40,000 to 60,000 |
| fact_promotions | One row per promotion, SKU, store | ~15,000 to 25,000 |
| fact_targets | One row per store, week | ~2,080 |

---

## 8. Expected Deliverables

| Phase | Deliverable | Location |
|---|---|---|
| 1 | Business Requirements Document (this file) | `docs/01_business_requirements.md` |
| 2 | Data generator, raw datasets, planted-issue log | `src/data_generation/`, `data/raw/`, `data/raw/_planted_issues_log.csv` |
| 3 | Data model documentation, ERD, SQL DDL | `docs/03_data_model.md`, `sql/schema/` |
| 4 | Data-quality framework and report | `src/data_quality/`, `reports/data_quality_report.csv` |
| 5 | ETL pipeline, SQL transformations, validation | `src/etl/`, `sql/transformations/`, `sql/validation/`, `run_pipeline.py` |
| 6 | Business-question SQL analysis library | `sql/analysis/` |
| 7 | Root-cause analysis and revenue bridge | `sql/analysis/rca/`, `src/analytics/`, `reports/root_cause_analysis.md` |
| 8 | Power BI report, DAX measure library, design notes | `powerbi/`, `docs/08_powerbi_design.md` |
| 9 | Exploratory analysis, anomaly detection, forecast vs actual | `notebooks/`, `src/forecasting/` |
| 10 | Automated management insights | `src/analytics/insights.py`, `reports/management_insights.md` |
| 11 | Optional AI explanation layer (separate, experimental) | `experimental/ai_layer/` |
| 12 | README, repo structure, interview preparation guide | `README.md`, `docs/12_interview_guide.md` |

### 8.1 Project acceptance criteria

1. The pipeline runs end-to-end from raw data with one command.
2. The data-quality framework detects at least 95% of the planted issues recorded in the planted-issue log.
3. Power BI totals match SQL totals exactly for revenue, units and transactions.
4. The revenue bridge explains the full decline (drivers plus a clearly labelled residual sum to the headline).
5. Every root-cause finding carries an evidence level.
6. Every automated insight statement links to a calculated value.

---

## 9. Sign-off Record

All open items raised in version 0.1 were resolved at sign-off. The decisions below record how; they do not change any requirement above.

| # | Item | Decision |
|---|---|---|
| 1 | Environment | Windows, Python 3.11+, SQL Server 2022 Developer, SSMS, Power BI Desktop |
| 2 | Comparison basis | H2 2025 vs H2 2024, week-aligned retail weeks 27 to 52 (confirmed) |
| 3 | Data volume | About 1.2 to 1.5 million sales lines (confirmed) |
| 4 | Planted scenario | Agreed; held separately from analyst-facing documentation as an evaluation-only asset |

### Document history

| Version | Date | Change |
|---|---|---|
| 0.1 | 27 September 2026 | Draft for sign-off |
| 1.0 | 27 September 2026 | Approved. Document control and sign-off record updated; requirements unchanged |
