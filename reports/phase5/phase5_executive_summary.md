# Brightwater Retail: H2 2025 performance diagnosis (Phase 5)

This is an exploratory diagnosis of the H2 2025 net revenue decline, built only from the governed Phase 4 model. Every figure is recalculated from the data and reconciled to Phase 4, and each finding carries a BRD evidence level. This is not yet a final root-cause conclusion (that is Phase 6).

## In brief

- Net revenue fell **EUR 731,270 (7.18%)**, from EUR 10,188,728 to EUR 9,457,457.
- **84% of the fall is fewer transactions.** Basket size and price together explain 14%, and returns 2%.
- **3 stores (S03, S04, S05, all Dublin Standard) carry 62% of the fall.** Their transactions fell 28%. The other 17 stores are down 3.3%.
- Two categories carry 70% of the fall: **Electronics & Tech** (availability down 6.1 pp, return rate up 1.9 pp, units down 10.7%); **Home & Kitchen** (promotional share up 14.9 pp, selling price down 6.7%).

## 1. How large is the decline?

| Measure | H2 2024 | H2 2025 | Change |
|---|---:|---:|---:|
| Net Revenue (EUR) | 10,188,728 | 9,457,457 | -731,270 (-7.18%) |
| Sales Revenue (EUR) | 10,557,441 | 9,840,828 | -716,613 (-6.79%) |
| Returns Value (EUR) | 368,713 | 383,371 | +14,657 (+3.98%) |
| Gross Margin (EUR) | 3,962,594 | 3,525,708 | -436,885 (-11.03%) |
| Gross Margin % | 38.9% | 37.3% | -1.6 pp |
| Transactions | 229,446 | 216,027 | -13,419 (-5.85%) |
| Average Order Value (EUR) | 46.01 | 45.55 | -1.00% |
| Units per Transaction | 2.127 | 2.120 | -0.33% |
| Average Selling Price (EUR) | 21.63 | 21.49 | -0.67% |

Gross margin fell 11.0% (-EUR 436,885), faster than revenue. The margin rate moved -1.6 pp, in line with deeper discounting (promoted-line margin 31.5% to 24.3%).

## 2. When did it happen?

H1 2025 was +1.4% on the prior year. The decline begins with H2:

- Weeks 27 to 31 average -1.4% a week, and weeks 32 to 52 average -8.8%.
- 20 of 26 weeks are down.
- The two halves of H2 are similar (-7.1% and -7.3%), so the pattern is **a persistent decline with no clear trend within the period** rather than a worsening trend.
- In the 3 stores above, the fall is abrupt: negative every week from week 28.

Weekly figures are volatile, so single weeks should not be over-read.

## 3. Which stores and regions contributed most?

| Store | Region / format | Change (EUR) | YoY | Share of decline | Transactions YoY |
|---|---|---:|---:|---:|---:|
| S03 Dublin Blanchardstown | Dublin / Standard | -171,317 | -31.1% | 23% | -29.6% |
| S04 Dublin Swords | Dublin / Standard | -153,953 | -28.8% | 21% | -26.6% |
| S05 Dublin Tallaght | Dublin / Standard | -124,702 | -27.3% | 17% | -26.9% |
| S01 Dublin Grafton Street | Dublin / Flagship | -48,578 | -5.1% | 7% | -4.2% |
| S15 Limerick | Munster / Standard | -45,488 | -9.6% | 6% | -6.5% |
| S14 Cork Mahon Point | Munster / Standard | -36,074 | -6.5% | 5% | -4.1% |

By region, Dublin contributes -EUR 503,056 (69% of the decline). By format within it: Standard stores -29.2%; Flagship stores -2.5%. Percentage falls and EUR contributions rank stores differently. The ranking above uses EUR contribution, because that is what moves the estate total.

For example, S18 Galway is down 4.4% but ranks 8 by EUR. That is above S19 Sligo (down 6.9%, rank 10), because it is the larger store.

**Targets.** 16 of 20 stores missed target in at least 8 of the last 13 weeks in H2 2025, against 16 in H2 2024. Estate target achievement went from 92.8% to 86.6%. A missed target is an outcome, not a cause. Achievement % ranks the declining stores lowest: S03 63%, S04 67%, S05 72%.

## 4. Which categories contributed most?

| Category | Change (EUR) | YoY | Share of decline | Largest component | Other notable changes |
|---|---:|---:|---:|---|---|
| Electronics & Tech | -268,518 | -11.8% | 37% | fewer receipts with the category (-242,992) | availability down 6.1 pp, return rate up 1.9 pp, units down 10.7% |
| Home & Kitchen | -239,994 | -9.3% | 33% | lower ASP (-178,055) | promotional share up 14.9 pp, selling price down 6.7% |
| Seasonal & Gifts | -84,120 | -6.1% | 12% | fewer receipts with the category (-101,117) | no single metric stands out |
| Toys & Games | -67,114 | -5.2% | 9% | fewer receipts with the category (-76,682) | no single metric stands out |
| Stationery & Crafts | -41,446 | -6.2% | 6% | fewer receipts with the category (-43,557) | no single metric stands out |
| Health & Beauty | -21,447 | -1.4% | 3% | fewer receipts with the category (-80,070) | no single metric stands out |
| Garden & Outdoor | -7,014 | -1.5% | 1% | fewer receipts with the category (-36,999) | no single metric stands out |

## 5. Transactions, basket size, price and returns

The bridge splits the change using two identities: Sales Revenue = Transactions x Units per Transaction x Average Selling Price, and Net Revenue = Sales Revenue - Returns. It uses the exact Shapley method, so there is no unexplained residual.

| Driver | EUR effect | Share of the decline | pp of prior-year revenue |
|---|---:|---:|---:|
| Transactions (fewer receipts) | -614,363 | 84% | -6.03 |
| Units per transaction | -34,173 | 5% | -0.34 |
| Average selling price | -68,077 | 9% | -0.67 |
| Returns | -14,657 | 2% | -0.14 |
| **Total** | **-731,270** | **100%** | **-7.18** |

**Returns.** The return rate rose from 3.49% to 3.90% of sales. The largest increase is 'Faulty' returns in Electronics & Tech (EUR 31,589, the reason recorded at the till). 4 store x category cells hold 56% of the gross increase.

## 6. Availability

Estate availability moved -0.65 pp (95.4% to 94.8%). Electronics & Tech fell from 95.4% to 89.3%, with the largest loss on SKUs supplied by Voltix Distribution Ltd.

- **Mechanism (visible in the data).** In 794 store-SKU-weeks with no stock at any point, sales were 0 units against 434 expected.
- **ESTIMATE.** Sales lost in those weeks rose from EUR 19 to EUR 37,280 (5% of the decline). This is the conservative figure.
- **Upper bound (not evidence).** Counting weeks that ran out part-way through gives up to EUR 102,112, but that figure cannot be separated from estimation noise.
- **Stores.** Availability does not explain which stores declined most. The store-level correlation is r = -0.24 (p = 0.31, not significant).

## 7. Promotions

Promotions became more intense. The promotional share of sales went from 12.7% to 16.9%, and discount cost from EUR 269,584 to EUR 528,924 (2.0x).

- **Home & Kitchen.** Promotion events 2,427 to 8,848, average discount 15% to 32%, uplift 90% to 176% but incremental promo margin EUR 26,974 to -EUR 33,508; post-promotion weeks -16% vs baseline. Category ASP -6.7%, gross margin 42.8% to 36.8%.
- **Pull-forward.** Post-promotion weeks are -12.1% and -12.9% against baseline (prior and current year).

The data shows what changed in the promotions. Whether they caused part of the decline needs a counterfactual (Phase 6).

## 8. Which findings are confirmed?

These findings are measured in the data (Observed change), a quantified mechanism (Root-cause evidence) or a correlation (Statistical association, which is not causation):

| ID | Area | Finding | Evidence level |
|---|---|---|---|
| F01 | Headline | Net revenue -EUR 731,270 (-7.18%) YoY. | Observed change |
| F02 | Timing | Decline begins with H2 (H1 +1.4%); 20 of 26 H2 weeks down. | Observed change |
| F03 | Revenue bridge | Fewer transactions: -EUR 614,363 (84% of the fall). | Observed change |
| F04 | Revenue bridge | Basket size and price: -EUR 102,250 combined (14% of the fall). | Observed change |
| F05 | Revenue bridge | Higher returns: -EUR 14,657. | Observed change |
| F06 | Stores | 3 stores (S03, S04, S05) carry 62% of the fall (-EUR 449,972). | Observed change |
| F07 | Stores | Their fall is abrupt (from week 28) and persistent, about -31% a week. | Observed change |
| F09 | Region / format | Dublin: 69% of the fall, mostly its Standard-format stores. | Observed change |
| F10 | Categories | Electronics & Tech: -EUR 268,518 (37% of the fall), mainly transactions. | Observed change |
| F11 | Categories | Home & Kitchen: -EUR 239,994 (33% of the fall), mainly ASP. | Observed change |
| F12 | Availability | Availability fell 6.1 pp in Electronics & Tech (estate -0.65 pp). | Observed change |
| F13 | Availability | Full-week stock-outs cost an estimated EUR 37,261 more (ESTIMATE), mostly Electronics & Tech. | Root-cause evidence (estimate) |
| F15 | Availability | Store availability change does not track store revenue change (r = -0.24, p = 0.31). | Statistical association |
| F17 | Returns | 'Faulty' returns in Electronics & Tech up EUR 31,589; 4 store x category cells hold 56% of the increase. | Observed change |
| F19 | Promotions | Discount cost up EUR 259,341; promo share 12.7% to 16.9%. | Observed change |
| F20 | Promotions | Home & Kitchen promotions: 3.6x the events, deeper discounts, incremental margin -EUR 33,508; ASP effect -EUR 178,055. | Observed change |
| F21 | Promotions | Post-promotion dip -12% and -13% vs baseline (prior, current year). | Observed change |
| F23 | Targets | 16 of 20 stores persistently miss target (16 in the prior year); an outcome, not a cause. | Observed change |
| F24 | Range | Range churn: -EUR 144,052 delisted, EUR 415,173 new SKUs (net EUR 271,121). | Observed change |
| F25 | Data coverage | S13: 2 missing prior-year trading days (about EUR 11,175), flatters its YoY. | Observed change |

## 9. Which findings are only hypotheses?

These explanations are plausible, but the available data cannot confirm them:

- **F08** A local traffic event around S03, S04, S05 may have reduced visits. *Needs:* Obtain footfall counts, competitor openings, local events and store operating logs for these stores; compare same-region stores that did not decline.
- **F14** Partial-week stock-outs may have cost up to EUR 60,389 more. *Needs:* Phase 6: daily or intraday stock positions (or till timestamps) to date when each SKU ran out.
- **F16** A supply problem with Voltix Distribution Ltd may have caused the Electronics & Tech stock-outs. *Needs:* Phase 6: received_qty and closing-stock sequences for the supplier's SKUs; request purchase orders, delivery confirmations and supplier fill-rate data.
- **F18** A quality problem in some Electronics & Tech products may have raised 'Faulty' returns. *Needs:* Request supplier batch or lot data, QA inspections and customer complaint logs.
- **F22** The Home & Kitchen promotion programme may have reduced revenue. *Needs:* Phase 6: counterfactual by category-week; promotion calendar and planning rationale from Marketing.

## 10. What Phase 6 should investigate

1. **The 3-store transaction fall** (-EUR 449,972). Find what changed locally around the start of H2. This needs footfall, competitor and local-event data that the model does not hold.
2. **Home & Kitchen promotions** (-EUR 178,055 ASP effect). Build a category-week counterfactual and test cannibalisation.
3. **Electronics & Tech stock-outs** (EUR 37,261 estimated, up to EUR 102,112). Trace the replenishment history of the Voltix Distribution Ltd SKUs and confirm with order and delivery data.
4. **'Faulty' returns in Electronics & Tech** (EUR 31,589). Break them down by product, supplier and original sale date.
5. **Overlaps.** Separate how much of each category's fall sits inside the store cluster, so drivers are not double counted.

## Caveats

- Findings describe overlapping slices of one decline. Their EUR figures must not be added together.
- Lost sales are an estimate. The baseline is back-tested at 0.993 actual/expected in aggregate, with 12.5% error at store x category x week.
- S13 has 2 missing trading days in week 42 of 2024, which slightly flatters its YoY.
- Some SKUs have no supplier on the product master.

Detail: `investigation_shortlist.csv` (all findings with evidence levels), `phase5_validation_report.md` (reconciliation and checks), `docs/05_exploratory_analysis.md` (methods).
