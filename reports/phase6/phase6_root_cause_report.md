# Brightwater Retail: H2 2025 root-cause report (Phase 6)

**How to read this report.** Statements carry a tag. **FACT**: measured in the governed data. **ESTIMATE**: a model-based figure (counterfactual, fitted model or test) with a stated method and range. **STATISTICAL ASSOCIATION**: two things move together; not proof of cause. **HYPOTHESIS**: a plausible explanation the available data cannot test. **UNRESOLVED**: the size is established but no cause can be identified from the data. Evidence levels in the matrix follow the BRD (Observed change, Statistical association, Root-cause evidence, Hypothesis).

## Executive conclusion

- **FACT.** H2 net revenue fell EUR 731,270 (-7.18%), reconciled to the cent with Phase 4 and Phase 5.
- **FACT.** Transactions per store in S03, S04, S05 fell 27.8%, against -1.1% in matched control stores. **ESTIMATE.** Measured against those controls, the loss starts abruptly in mid-July (best-fitting change point 15 July 2025) and is worth EUR 397,778 of net revenue (54% of the decline; range EUR 377,245 to EUR 435,210 lost across control groups and windows).
- **UNRESOLVED.** Nothing in Brightwater's data explains that loss. Price, promotions, availability, range and returns in these stores moved close to the controls. An external local change (competitor, access works, local event) or an unrecorded operational change is a **HYPOTHESIS**. Testing it needs footfall, competitor, local-event and store-operations data.
- **ESTIMATE, ROOT-CAUSE EVIDENCE.** Full-week stock-outs in Electronics & Tech removed an estimated EUR 37,235 of sales more than last year, 83% of it on Voltix Distribution Ltd SKUs. Part of that demand returned after restock (EUR 13,272 above the prior-year post-restock pattern), leaving a net loss of about EUR 23,963 (range across variants EUR 23,963 to EUR 44,460 lost). The stock-outs are real; their net revenue effect is small and robust.
- **FACT.** 'Faulty' returns in Electronics & Tech rose EUR 31,589. **STATISTICAL ASSOCIATION.** The increase is concentrated in 5 stores and in sales made from late summer onwards, across suppliers. Product failure is **not** established: 'Faulty' is a till reason code, not a verified defect.
- **STATISTICAL ASSOCIATION.** Home & Kitchen lost about EUR 186,146 relative to other categories in the same stores and weeks, mostly through price, while its promotions became deeper and more frequent. Two of the four counterfactual methods say the promotions added revenue, so this is not established as a cause.
- **Attribution (no double counting).** The cluster excess (54%), stock-outs (5%), 'Faulty' returns (4%) and the H&K change (25%) account for 89% of the decline. Of that, 59% is observed change whose cause is unresolved or hypothetical, 25% (H&K) is estimated and only statistically associated with its candidate mechanism, and 5% (stock-outs) is estimated with a robust mechanism (Root-cause evidence). EUR 78,522 of the decline (11%) is not attributed; most of it is Electronics & Tech outside the cluster.
- **Bottom line.** Only Electronics & Tech full-week stock-outs reaches the Root-cause evidence standard (mechanism visible, quantified and robust), and it explains a small share of the decline. The size and location of the rest are firmly established; their causes are not. The data requests at the end of this report are what would change that.

## What happened

| Measure | Prior H2 | Current H2 | Change |
|---|---:|---:|---:|
| Net revenue (EUR) | 10,188,728 | 9,457,457 | -731,270 (-7.18%) |
| Sales revenue (EUR) | 10,557,441 | 9,840,828 | -716,613 (-6.79%) |
| Returns (EUR) | 368,713 | 383,371 | +14,657 (+3.98%) |
| Gross margin (EUR) | 3,962,594 | 3,525,708 | -436,885 (-11.03%) |
| Transactions | 229,446 | 216,027 | -13,419 (-5.85%) |

All figures are FACT, recomputed from the governed model (`headline_reconciliation.csv`).

## Where it happened

Exact split of the change (FACT; the six cells add up to the total):

| Store group | Category group | Change (EUR) | Share |
|---|---|---:|---:|
| Store cluster | Other categories | -223,220 | 31% |
| Other stores | Electronics & Tech | -157,074 | 21% |
| Other stores | Home & Kitchen | -124,686 | 17% |
| Store cluster | Home & Kitchen | -115,308 | 16% |
| Store cluster | Electronics & Tech | -111,445 | 15% |
| Other stores | Other categories | +461 | 0% |

In the store cluster, every category fell. Elsewhere, the fall is concentrated in Electronics & Tech and Home & Kitchen; the other categories were flat. See `figures/04_category_store_heatmap.png`.

## When it happened

**ESTIMATE (model fit).** The cluster's daily transactions, compared with the same weekday last year and with the control stores, are best described by a single step on 15 July 2025: step, gradual-ramp and linear models were compared by BIC, and the best fit is a step (an immediate transition). The daily series is noisy (the step explains 48% of its variance). Fitted separately, the stores turn between 09 Jul and 21 Jul: S03 16 Jul (-32%, R2 0.39), S04 09 Jul (-22%, R2 0.20), S05 21 Jul (-28%, R2 0.28). No group of three other stores shows a comparable shift (placebo test below).

## Revenue bridge

**FACT.** Phase 5's Shapley bridge (`reports/phase5/revenue_bridge.csv`, frozen) shows that fewer transactions explain most of the fall. This report adds where those transactions were lost. **ESTIMATE.** Relative to the matched control stores, the cluster lost 8,508 receipts (-EUR 397,778 of net revenue, -EUR 140,829 of gross margin).

## Store-cluster investigation

- **Controls.** The five stores most similar to the cluster on pre-period revenue, transactions, basket, format, region and H1 trend: S07, S09, S12, S16, S18. The cluster stores are the estate's only Standard-format stores in Dublin, so none of the matched controls shares their region, and the Dublin control group (the other Dublin stores) has a different format. Four control groups are used, and the estimate holds across all of them (range EUR 377,245 to EUR 435,210 lost).
- **ESTIMATE (DiD on measured transactions).** Transactions -25.5% vs matched controls. The pre-period gap was flat (slope p 0.93), so parallel trends is a reasonable assumption. In 680 placebo tests (every 3-store group of other stores, each against the rest) the most negative result was -6.4%, against -26.8% for the cluster measured the same way (p = 0.0015, the smallest value attainable). Caveat: Phase 5 selected these stores because they declined most, so this p-value overstates significance. The size of the gap, not the p-value, is the evidence.
- **FACT. How the cluster's other KPIs moved relative to the controls** (cluster change minus control change):

  | Measure | Difference |
  |---|---:|
  | Transactions per store | -26.64 % |
  | Average transaction value | -1.60 % |
  | Units per transaction | -0.75 % |
  | Average selling price | -0.86 % |
  | Promotional share of sales | +1.30 pp |
  | Receipts with a promoted item | +2.26 pp |
  | Availability | +0.04 pp |
  | Ranged SKUs | -0.20 % |
  | Return rate | -0.63 pp |
  | Weekend share of transactions | -1.07 pp |
  | Basket value, 90th percentile | -3.13 % |

  Apart from transactions, no difference exceeds a few points, against a transaction gap of about 25%. None of them is large enough to account for the lost receipts. Receipts fell by similar percentages in every basket-value band (`cluster_basket_distribution.csv`).
- **FACT. The loss is broad.** The gap to the controls is -30 to -23 pp across weekdays, -36 to -22 pp across trading hours and -32 to -24 pp across categories. The category mix shift index is 0.013, against 0.020 for the controls.
- **UNRESOLVED / HYPOTHESIS.** A simultaneous, broad loss of receipts in three stores in the same region, with no internal lever changing much, points to something outside the stores, or to an operational change the model does not record (opening hours, works, closures). The transaction loss remains unexplained after controlling for observable factors. Footfall, competitor, local-event and store-operations data are required.

## Electronics & Tech investigation

**FACT.** Net revenue -EUR 268,518 (-11.8%); receipts containing the category -10.1%; units -10.7%; ASP +0.7%; returns up EUR 26,289; availability 95.4% to 89.3%.

About 42% of the category's fall (-EUR 111,445) is in the three cluster stores, where every category fell. Sales change by supplier across all stores (FACT): Voltix Distribution Ltd EUR 1,438; Unknown supplier -EUR 34,924; Northbridge Tech Supplies -EUR 91,718; Emerald Electronics Wholesale -EUR 117,147.

**FACT. Range and distribution outside the cluster** (`electronics_range_distribution.csv`). Category sales changed -EUR 124,543: SKUs delisted after the prior year -EUR 95,472, new SKUs EUR 265,233, continuing SKUs -EUR 294,304. For continuing SKUs, fewer ranged store-SKU-weeks account for -EUR 28,774 and lower sales per ranged week for -EUR 265,530. The range churn added revenue: new SKUs more than replaced the delisted ones. The fall sits in continuing SKUs, and most visibly in Voltix Distribution Ltd's: its new SKUs EUR 252,306, its continuing SKUs -EUR 210,136. **HYPOTHESES** (not separable with these data): customers switched from the older models to the new ones; stock-outs within partial weeks, which the primary lost-sales estimate does not count (the BR-05 upper bound is EUR 63,175 higher); or shoppers substituting the new SKUs while older ones were out of stock. Testing them needs daily stock positions and customer-level purchase history.

## Availability investigation

- **FACT.** Voltix Distribution Ltd stock-out episodes: 609 to 1181; mean length 1.1 to 2.1 weeks; longest 13 weeks; 674 store-SKU-weeks with no stock at all (prior year 0).
- **FACT.** Its SKUs started each week with less stock: mean opening stock 2.58 to 1.83 units. Stock received per ranged store-SKU-week barely changed (0.89 to 0.88 units); other suppliers 1.19 to 1.03 units.
- **ESTIMATE.** Sales lost in full-week stock-outs: EUR 0 in the prior year and EUR 37,235 in the current year, an increase of EUR 37,235. Counting partial weeks too (the BR-05 upper bound) gives an increase of EUR 100,411; that bound is not evidence.
- **ESTIMATE. Recovery.** Once stock returned, Voltix Distribution Ltd SKUs sold 1.06x expected in week 1, 1.38x expected in week 2 (prior year 0.93x, 1.32x). Allowing for that normal post-restock pattern, sales after episodes with a full-week stock-out ran EUR 13,272 above it across the category: demand deferred rather than lost, 36% of the gross estimate. Across all 21 variants, including the one net of deferred demand, the effect ranges EUR 23,963 to EUR 44,460 lost, so it is robust and classified as Root-cause evidence.
- **FACT. Concentration.** High-selling SKUs (top 10% by prior-year revenue) carry 61% of the increase in estimated lost sales. The top SKU (P00149) carries 25% and the top 3 carry 50%.
- **STATISTICAL ASSOCIATION. Supplier test.** Voltix Distribution Ltd SKUs' stock-out rate rose +8.5 pp, against +1.6 pp for other suppliers' SKUs. The difference is +6.8 pp (95% CI +2.5 to +11.2; permutation p 0.002, or 0.010 after allowing for Voltix Distribution Ltd having been picked as the worst of 4 suppliers), and it holds when any single SKU is removed.
- **HYPOTHESIS.** Lower stock cover per SKU suggests smaller or later replenishment. The data cannot say whether the supplier under-delivered or Brightwater ordered less. Confirming it needs purchase orders, supplier confirmations, lead times and ordering parameters.

## Returns investigation

**FACT.** In Electronics & Tech, only 'Faulty' returns rose materially (EUR 31,589, +90%). The other reasons moved: Changed mind -EUR 1,154, Damaged EUR 484, Gift return -EUR 3,262, Not as described -EUR 1,368.

- **STATISTICAL ASSOCIATION. Stores.** The recorded faulty rate rose significantly in 5 stores (S13, S14, S07, S15, S16; conditional binomial test, p < 0.01, not adjusted for testing 20 stores). The top 5 stores hold 89% of the gross increase. In the significant stores the faulty rate rose +2.84 returned units per 100 sold; all other reasons together moved +0.05.
- **FACT. Suppliers and products.** In those stores, the increase splits by supplier as Voltix Distribution Ltd EUR 24,739; Northbridge Tech Supplies EUR 7,525; Emerald Electronics Wholesale EUR 2,191; Unknown supplier EUR 1,739. Across the estate, the top 5 products hold only 53%.
- **FACT. Cohorts and lag.** Faulty returned units per 100 sold, by sale month against the same month a year earlier: Jul 1.3 to 1.1; Aug 1.3 to 1.3; Sep 1.0 to 2.7; Oct 0.8 to 2.4; Nov 1.8 to 3.0; Dec 1.8 to 2.5. The rise starts with sales made in September. The sale-to-return lag did not change (KS p 0.60). 97% of current-year 'Faulty' returns link to the original sale line.
- **Verdict.** The increase is concentrated in a small number of stores and later sale cohorts, not in a small number of products. **HYPOTHESIS**: a defective batch delivered to these stores, or a change in how these stores record returns. Causal confirmation needs QA inspection results, batch / lot or serial numbers, supplier defect and RMA reports, warranty claims, and an audit of returns handling in the named stores.

## Promotion investigation

**FACT.** Home & Kitchen discount rate on gross sales went from 2.4% to 11.9%. Promotion events rose from 2,427 to 8,848.

| Method (all ESTIMATES) | Effect of the change (EUR) | Interval | Reading |
|---|---:|---:|---|
| M1 category DiD vs control categories, same store-weeks | -186,146 | -248,937 to -121,581 (95% CI) | H&K-specific change: sales -7.1%, units -1.7%; gross margin -EUR 159,258 |
| M4 discount-rate accounting (no net volume response) | -265,003 | -380,272 to -243,387 (volume response at the M1 units CI) | Revenue given away by the higher discount rate |
| M2 dose-response (coverage incl. 2 lag weeks, depth) | +97,505 | +87,312 to +161,234 (95% CI) | Promoted weeks sell more; association only |
| M3 event-level net programme revenue | +79,059 | n/a | Baselines exposed to back-to-back promotions (64% of events) |

- **ESTIMATE.** Post-promotion dips grew. Against event baselines, the post-promotion shortfall was EUR 23,214 in the prior year and EUR 110,409 in the current year. Incremental promo margin went from EUR 26,974 to -EUR 33,508.
- **ESTIMATE. Cannibalisation.** None measurable: non-promoted H&K SKUs did not sell below their baseline in promoted store-weeks.
- **STATISTICAL ASSOCIATION.** The category-level evidence (M1, M4) says Home & Kitchen lost EUR 186,146 to EUR 265,003, mostly through price, while units held up relative to other categories. The event-level views (M2, M3) say promoted weeks sold more. **HYPOTHESIS** reconciling the two: the extra promotions lifted promoted weeks but produced little net volume over the half (the M1 units change is not significant), while the discount applied to far more sales. Because the methods disagree in sign, this is **not** Root-cause evidence.
- **Needed to confirm:** the promotion calendar with objectives, a holdout-store test or SKU-level price elasticities.

## Driver overlap

Phase 5's slices overlap: the store cluster sells Electronics and Home & Kitchen, so adding the slices would double count. The exclusive attribution works in three steps:

1. It measures the cluster's excess decline against control stores.
2. It measures each category driver in all stores. If the cluster has *more* of a driver than the control-store rate implies, that extra part is already inside the cluster excess and is removed from the driver. A driver is never made larger than its measured total.
3. It adds category drivers only where they are disjoint (different categories, or different ledger lines), and closes the total with a residual.

In these data the cluster had *less* of every category driver than the control-store rate implies (driver amounts; negative = revenue lost: E&T stock-outs -EUR 4,855 in the cluster vs -EUR 6,576 expected; E&T faulty returns EUR 4,937 in the cluster vs -EUR 6,423 expected; H&K promotion period -EUR 21,391 in the cluster vs -EUR 29,454 expected), so no overlap is removed and each driver enters at its measured total.

Because overlap is removed only in one direction, the cluster excess keeps the cluster's below-control-rate driver amounts (EUR 21,143 in total); the cluster's pure traffic loss is therefore about EUR 418,921.

| Component | EUR | Overlap removed | Share |
|---|---:|---:|---:|
| Store-cluster excess decline (vs matched control stores) | -397,778 | 0 | 54% |
| Electronics & Tech full-week stock-outs (ESTIMATE) | -37,235 | 0 | 5% |
| Electronics & Tech 'Faulty' returns increase | -31,589 | 0 | 4% |
| Home & Kitchen category-specific change (promotion period) | -186,146 | 0 | 25% |
| Residual: not attributed | -78,522 | 0 | 11% |
| **Total (FACT)** | **-731,270** | | **100%** |

Where the residual sits (the parts add up to the residual):

| Part | EUR |
|---|---:|
| Other stores: Electronics & Tech change not explained by stock-outs or 'Faulty' returns | -88,168 |
| Other stores: Home & Kitchen change not explained by the category-specific (M1) change | +40,069 |
| Other stores: other categories (no driver identified) | +461 |
| Store cluster: change at the control-store rate, net of the cluster's driver amounts | -30,884 |

For comparison, simply adding the cluster excess and the two category declines gives EUR 906,290, 124% of the actual decline. That is what double counting looks like. Other overlap figures:

- Estimated stock-outs on the same store-SKUs as faulty-return increases: -EUR 14,250. These are different ledger lines (lost sales vs refunds), so they are additive.
- E&T drivers and H&K drivers sit in different categories and cannot overlap.

## Counterfactual scenarios

These are analytical counterfactuals, not forecasts. Ranges come from the sensitivity analysis.

| Scenario | Revenue impact (EUR) | Range | Margin impact (EUR) | Evidence | Confidence |
|---|---:|---|---:|---|---|
| A. Store-cluster transactions at the control-store baseline | +397,778 | +377,245 to +435,210 | +140,829 | Observed change | High for the size (robust across control groups and windows; placebo p 0.0015, the smallest attainable); cause unresolved |
| A2. All stores' H2 transactions at their own H1 YoY trend | +547,195 | n/a | +204,483 | Hypothesis | Low: H1 trend is a simple extrapolation |
| B. Electronics availability at the prior-year baseline | +37,235 | +23,963 to +44,460 | +8,182 | Root-cause evidence | Medium |
| C. Returns at the prior-year return rate | +39,685 | n/a | +23,804 | Observed change | High for the arithmetic; it says nothing about why returns rose |
| D. Home & Kitchen promotional behaviour comparable with the prior year | +186,146 | -97,505 to +380,272 | +159,258 | Statistical association | Low to medium: methods disagree in sign (see sensitivity) |
| E. Combination of the mutually exclusive components | +652,749 | n/a | n/a | Statistical association | As weak as its weakest component (D) |

Assumptions for each scenario are in `counterfactual_scenarios.csv`. Only scenario E combines effects, and only mutually exclusive ones.

## What the evidence supports

- **D01** Loss of customer transactions specific to stores S03, S04, S05: Confirmed and quantified: a sudden, uniform loss of receipts in three stores. The largest single driver. (Observed change)
- **D03** Electronics & Tech full-week stock-outs: Supported and robust: a real mechanism, but small: about 5% of the decline gross, and less net of the demand that returned after restock. (Root-cause evidence)
- **D04** Supplier concentration: Voltix Distribution Ltd: The concentration survives comparison with the other suppliers; whether supply or ordering caused it is a Hypothesis. (Statistical association)
- **D05** Increase in Electronics & Tech 'Faulty' returns: Concentrated in a few stores and recent sale cohorts, across products: consistent with either a local product batch or a change in how those stores record returns. Cause is a Hypothesis. (Observed change)
- **D08** Range and distribution change in Electronics & Tech: The range churn itself added revenue outside the cluster (new SKUs more than replaced delisted ones); the decline sits in continuing SKUs. Whether new SKUs took their sales, partial-week stock-outs or substitution during stock-outs explain it is a Hypothesis. (Observed change)

## What the evidence does NOT establish

- Why the three stores lost customers (D02, Hypothesis).
- That the Voltix Distribution Ltd stock-outs were the supplier's fault rather than Brightwater's ordering (D04 is an association; the cause is a Hypothesis).
- That 'Faulty' returns reflect genuinely defective products (D06, Hypothesis).
- That the Home & Kitchen promotion programme caused the category's decline. D07 is a Statistical association with a method-dependent sign (range from a EUR 380,272 loss to a EUR 97,505 gain).
- That new Electronics & Tech SKUs took sales from continuing ones (D08, Hypothesis).
- Any management action. Phase 6 diagnoses; it does not recommend.

## Remaining unknowns

- The external or operational event behind the cluster step around 15 July 2025.
- How long SKUs were out of stock within partial weeks, and how much demand switched to other SKUs.
- The true counterfactual volume of the H&K promotion programme.
- Why continuing Electronics & Tech SKUs sold less per ranged week outside the cluster, the bulk of the -EUR 78,522 residual.

## Additional data required

| Question | Data |
|---|---|
| External local cause of the cluster traffic loss (competitor, access, local event) | Footfall counters, competitor openings and promotions near the three stores, road / access works, local events, store operating logs (hours, closures, refits) |
| Supplier concentration: Voltix Distribution Ltd | Purchase orders, supplier confirmations and ASNs, delivery lead times and fill rates, Brightwater's own ordering parameters (min / max, safety stock) for these SKUs |
| Product quality problem vs store recording practice behind 'Faulty' returns | QA inspection results, batch / lot or serial numbers, supplier defect and RMA reports, warranty claims, store returns-handling audits, and the distribution centre / delivery route serving these stores |
| Home & Kitchen promotion programme (deeper, more frequent discounts) | Promotion calendar with objectives, planned vs actual depth, a controlled test (holdout stores) or at least SKU-level price elasticities |
| Range and distribution change in Electronics & Tech | Range plan and delisting dates, customer-level purchase history (switching between models) |
| Partial-week stock-outs and deferred demand | Daily stock positions or till timestamps per SKU |

## Implications for Phase 7

Phase 7 should carry these results forward as they stand:

- the exclusive attribution (`driver_attribution.csv`) and its residual breakdown;
- the evidence matrix (`root_cause_evidence_matrix.csv`) with its levels;
- the sensitivity ranges (`sensitivity_summary.csv`).

It should not add Phase 5 slices together or promote an association into a cause. Visuals should keep ESTIMATE and HYPOTHESIS labels visible. The data requests above are the only way to move D02, D04, D06, D07, D08 to a higher evidence level.

Figures: `figures/01` to `figures/11`. Methods: `docs/06_root_cause_analysis.md`.
