"""Root-cause evidence matrix (BRD 6.2 levels only; no stronger category is invented).

Rules
  * Observed change: a measured change, including a change measured relative to a control group.
  * Statistical association: a relationship across units / over time; also any causal estimate whose sign or size
    is NOT robust in the sensitivity analysis (a fragile estimate cannot be root-cause evidence).
  * Root-cause evidence: a mechanism directly visible in the data (e.g. no stock -> no sales) AND quantified by a
    disclosed method AND robust in the sensitivity analysis.
  * Hypothesis: an explanation the available data cannot test; it names the data required.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LEVELS = ("Observed change", "Statistical association", "Root-cause evidence", "Hypothesis")
COLUMNS = ["driver_id", "candidate_driver", "affected_scope", "observed_change", "mechanism", "estimated_impact_eur",
           "estimated_impact_pp", "impact_range_eur", "evidence_supporting", "evidence_against", "method", "uncertainty",
           "evidence_level", "additional_data_required", "double_counting_risk", "conclusion"]


def eur(v):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else (f"EUR {v:,.0f}" if v >= 0 else f"-EUR {abs(v):,.0f}")


def level_for(mechanism_visible: bool, robust: bool, testable: bool) -> str:
    if not testable:
        return "Hypothesis"
    if mechanism_visible and robust:
        return "Root-cause evidence"
    return "Statistical association"


def cy_year(R: dict) -> int:
    return R["periods"].cy_year


def build(R: dict) -> pd.DataFrame:
    py, cy = R["py"], R["cy"]
    total = cy["net_revenue"] - py["net_revenue"]
    pp = lambda v: 100 * v / py["net_revenue"]  # noqa: E731
    c, sc, el, rt, pr = R["central"], R["store_cluster"], R["electronics"], R["returns"], R["promotions"]
    sens = R["sensitivity_summary"].set_index("driver")
    rng = lambda d: f"{eur(sens.loc[d, 'min'])} to {eur(sens.loc[d, 'max'])}"  # noqa: E731
    prim = sc["primary_control"]
    ex = sc["eur"][prim]["net_revenue"]
    did_t = sc["did"][(prim, "ly_transactions")]
    mech = sc["mechanisms"]["comparison"].set_index("metric")
    on = sc["onset"]
    cl = ", ".join(R["cluster"])
    wd, hr, mx = sc["mechanisms"]["weekday"], sc["mechanisms"]["hour"], sc["mechanisms"]["category_mix"]
    rows = []

    def add(**k):
        rows.append(k)

    add(driver_id="D01", candidate_driver=f"Loss of customer transactions specific to stores {cl}",
        affected_scope=f"Stores {cl}, all categories, all weekdays and hours",
        observed_change=f"Transactions {did_t['did_pct']:+.1f}% vs matched controls (DiD); step change on "
                        f"{on['onset_date']:%d %b %Y}",
        mechanism="Fewer receipts; basket value, basket size, price, promotions, availability and returns move close to the "
                  "controls (differences of a few points at most, against a transaction gap of about 25%)",
        estimated_impact_eur=c["cluster_excess"], estimated_impact_pp=pp(c["cluster_excess"]),
        impact_range_eur=rng("store_cluster_excess"),
        evidence_supporting=f"Excess {'robust' if sens.loc['store_cluster_excess', 'robust'] else 'NOT robust'} across "
                            f"{int(sens.loc['store_cluster_excess', 'n_variants'])} control-group and window variants; "
                            f"pre-trend slope p {did_t['pre_trend']['p_value']:.2f}; "
                            f"placebo p {sc['placebo']['p_value_one_sided']:.4f} ({sc['placebo']['placebo_n']} placebo groups); "
                            f"abrupt step ({on['ramp']['ramp_days']}-day transition) in all three stores within "
                            f"{(pd.to_datetime(on['per_store']['onset_date']).max() - pd.to_datetime(on['per_store']['onset_date']).min()).days} days",
        evidence_against="The cluster was selected in Phase 5 because it declined most, so the placebo p-value (the smallest "
                         "attainable) overstates significance; no matched control store is in Dublin (the cluster's region), "
                         "and the Dublin control group has a different format. The cause is not observable",
        method="Difference-in-differences on store-week YoY log ratios; ratio DiD for EUR; daily change-point model",
        uncertainty=f"Range {rng('store_cluster_excess')} across controls and windows",
        evidence_level="Observed change",
        additional_data_required="None for the size",
        double_counting_risk="Would contain any above-control-rate stock-outs, returns or H&K effects in the cluster; in these "
                             "data the cluster had less of each than the control rate implies, so no overlap is removed",
        conclusion="Confirmed and quantified: a sudden, uniform loss of receipts in three stores. The largest single driver.")
    add(driver_id="D02", candidate_driver="External local cause of the cluster traffic loss (competitor, access, local event)",
        affected_scope=f"Stores {cl}", observed_change="Not observable in the model",
        mechanism="A change outside the stores reduced visits from mid-July",
        estimated_impact_eur=c["cluster_excess"], estimated_impact_pp=pp(c["cluster_excess"]),
        impact_range_eur=rng("store_cluster_excess"),
        evidence_supporting=(
            "Pattern fits an outside cause: the transaction gap vs controls ranges "
            f"{wd['difference_pp'].min():+.0f} to {wd['difference_pp'].max():+.0f} pp by weekday, "
            f"{hr['difference_pp'].min():+.0f} to {hr['difference_pp'].max():+.0f} pp by hour and "
            f"{mx['difference_pp'].min():+.0f} to {mx['difference_pp'].max():+.0f} pp by category (all strongly negative). "
            "Internal levers moved almost like the controls (cluster minus control change): "
            f"availability {mech.loc['availability', 'difference']:+.2f} pp, promo revenue share "
            f"{mech.loc['promo_revenue_share', 'difference']:+.2f} pp, ASP {mech.loc['asp', 'difference']:+.2f}%, "
            f"ranged SKUs {mech.loc['ranged_skus_per_store_week', 'difference']:+.2f}%, return rate "
            f"{mech.loc['return_rate_value', 'difference']:+.2f} pp"),
        evidence_against="No direct evidence; an internal operational change not recorded in the model (e.g. opening hours, "
                         "store works) would produce the same pattern",
        method="Elimination of observable internal explanations", uncertainty="Unresolved",
        evidence_level="Hypothesis",
        additional_data_required="Footfall counters, competitor openings and promotions near the three stores, road / access "
                                 "works, local events, store operating logs (hours, closures, refits)",
        double_counting_risk="Same slice as D01 (not additional)",
        conclusion="UNRESOLVED. Transaction loss remains unexplained after controlling for observable factors.")
    t = el["totals_category"]
    from .electronics import recovery_by_week
    rec = recovery_by_week(el["recovery"], el["top_supplier"]) if len(el["recovery"]) else el["recovery"]
    rec_cy = rec[rec["retail_year"] == cy_year(R)] if len(rec) else rec
    rec_txt = ", ".join(f"week {int(r.weeks_after)} after: {r.actual_to_expected:.2f}x expected" for r in rec_cy.itertuples()) \
        if len(rec_cy) else "not measurable"
    rows_sup = el["supplier_tests"].iloc[0]
    n_sup = int(len(el["by_supplier_category"]))
    add(driver_id="D03", candidate_driver="Electronics & Tech full-week stock-outs",
        affected_scope=f"{el['category']}, all stores; {el['top_supplier']} SKUs {el['totals_top_supplier']['primary_change'] / t['primary_change']:.0%}",
        observed_change=f"Full-week stock-out store-SKU-weeks {int(el['by_supplier_category']['full_week_out_cells_py'].sum())} to "
                        f"{int(el['by_supplier_category']['full_week_out_cells_cy'].sum())}; category availability "
                        f"{100 * el['kpis'].set_index('metric').loc['availability', 'prior']:.1f}% to "
                        f"{100 * el['kpis'].set_index('metric').loc['availability', 'current']:.1f}%",
        mechanism="No stock, no sales (zero units sold in every full-week stock-out)",
        estimated_impact_eur=c["stockouts_primary"], estimated_impact_pp=pp(c["stockouts_primary"]),
        impact_range_eur=f"{rng('electronics_stockouts_primary')} (primary); upper bound {eur(c['stockouts_upper'])}",
        evidence_supporting=f"Mechanism visible (no stock, no sales); estimator back-test {el['backtest']['bias_ratio']:.3f}; "
                            f"the gross estimate holds across the baseline variants with full coverage",
        evidence_against=f"After restock, {el['top_supplier']} SKUs sold above the expected rate ({rec_txt}). Allowing for the "
                         "prior-year post-restock pattern, sales after episodes with a full-week stock-out ran "
                         f"{eur(el['recovery_offset_eur'])} above it: demand deferred rather than lost, which offsets "
                         f"{min(1.0, max(0.0, el['recovery_offset_eur'] / t['primary_change'])):.0%} of the gross estimate. "
                         "Substitution to other SKUs is not measured",
        method="Phase 5 in-stock baseline (seasonally adjusted, +/-4 to 13 weeks); full-week stock-outs only",
        uncertainty=f"Primary {rng('electronics_stockouts_primary')}; upper bound {rng('electronics_stockouts_upper')} (not evidence)",
        evidence_level=level_for(True, bool(sens.loc["electronics_stockouts_primary", "robust"]), True),
        additional_data_required="Daily stock positions to measure partial-week stock-outs; basket data on substitution",
        double_counting_risk="Would overlap the cluster excess only by the cluster's above-control-rate share (none here); no "
                             "overlap with returns (different ledger line) or H&K (different category)",
        conclusion=("Supported and robust: a real mechanism, but small: about "
                    f"{abs(c['stockouts_primary'] / total):.0%} of the decline gross, and less net of the demand that "
                    "returned after restock." if sens.loc["electronics_stockouts_primary", "robust"] else
                    "A real mechanism, but small and not robust: the gross estimate is about "
                    f"{abs(c['stockouts_primary'] / total):.0%} of the decline, and deferred demand after restock may offset "
                    "most or all of it."))
    add(driver_id="D04", candidate_driver=f"Supplier concentration: {el['top_supplier']}",
        affected_scope=f"{el['top_supplier']} SKUs in {el['category']}",
        observed_change=f"SKU stock-out rate change {rows_sup['supplier_mean']:+.1f} pp vs {rows_sup['other_mean']:+.1f} pp for "
                        f"other suppliers' SKUs; mean opening stock of its SKUs fell while receipts per week did not",
        mechanism="Lower stock cover per SKU (smaller or later replenishment) leading to longer stock-outs",
        estimated_impact_eur=-el["totals_top_supplier"]["primary_change"],
        estimated_impact_pp=pp(-el["totals_top_supplier"]["primary_change"]), impact_range_eur="part of D03",
        evidence_supporting=f"Difference {rows_sup['difference']:+.1f} pp, 95% CI {rows_sup['ci_low']:+.1f} to "
                            f"{rows_sup['ci_high']:+.1f}, permutation p {rows_sup['permutation_p_two_sided']:.3f} "
                            f"({min(1.0, rows_sup['permutation_p_two_sided'] * n_sup):.3f} after a Bonferroni adjustment for "
                            f"the {n_sup} suppliers, since the supplier was picked as the worst before testing); survives "
                            f"leaving out any single SKU (min {rows_sup['leave_one_sku_out_min']:+.1f} pp)",
        evidence_against=f"Other deteriorating groups: " + "; ".join(
            f"{r.supplier_name} ({int(r.skus_cy)} SKUs) {r.availability_change_pp:+.1f} pp" for r in
            el["by_supplier_category"].iloc[1:].itertuples() if r.availability_change_pp <= -2) +
            ". The data cannot say whether the supplier failed to deliver or Brightwater ordered less",
        method="SKU-level comparison vs other suppliers (bootstrap CI, permutation test, leave-one-SKU-out)",
        uncertainty="Concentration robust; cause not identifiable",
        evidence_level="Statistical association",
        additional_data_required="Purchase orders, supplier confirmations and ASNs, delivery lead times and fill rates, "
                                 "Brightwater's own ordering parameters (min / max, safety stock) for these SKUs",
        double_counting_risk="Subset of D03 (not additional)",
        conclusion="The concentration survives comparison with the other suppliers; whether supply or ordering caused it "
                   "is a Hypothesis.")
    rs = rt["concentration"].set_index("dimension")
    sst = rt["supplier_split_in_significant_stores"].set_index("supplier_name")["value_change"]
    top_share_sst = float(sst.max() / sst[sst > 0].sum()) if (sst > 0).any() else float("nan")
    cl_fault = float(rt["by_store"].loc[rt["by_store"]["in_cluster"], "value_change"].sum())
    fc = c["faulty_returns"]
    coh = rt["cohort"]
    add(driver_id="D05", candidate_driver="Increase in Electronics & Tech 'Faulty' returns",
        affected_scope=f"Stores {', '.join(rt['significant_stores'])}; sale cohorts from "
                       f"{int(coh.loc[coh['rate_per_100'] > 2, 'sale_year_month'].min()) if (coh['rate_per_100'] > 2).any() else 'n/a'}",
        observed_change=f"'Faulty' refunds {eur(-fc)} higher; recorded faulty rate per 100 units sold up in "
                        f"{int(rs.loc['store_id', 'entities_significant_p01'])} stores (conditional binomial test, p < 0.01)",
        mechanism="More E&T items refunded with the till reason 'Faulty'",
        estimated_impact_eur=fc, estimated_impact_pp=pp(fc), impact_range_eur=rng("electronics_faulty_returns"),
        evidence_supporting=f"Top 5 stores hold {rs.loc['store_id', 'top_k_share_of_gross']:.0%} of the gross increase; "
                            f"{int((sst > 0).sum())} of {len(sst)} suppliers rose in the significant stores; there the "
                            f"'Faulty' rate moved {rt['faulty_rate_change_sig_pp']:+.2f} and all other reasons "
                            f"{rt['other_reason_rate_change_sig_pp']:+.2f} returned units per 100 sold; "
                            f"sale-to-return lag unchanged (KS p {rt['lag_ks_p']:.2f})",
        evidence_against="Spread over many products (top 5 hold only "
                         f"{rs.loc['product_id', 'top_k_share_of_gross']:.0%}); the till reason is not a verified defect",
        method="Rates per 100 units sold by product, supplier, store, sale cohort; conditional binomial tests of the rate "
               "increase (both years' rates uncertain)",
        uncertainty=f"{rng('electronics_faulty_returns')} depending on the rate basis",
        evidence_level="Observed change",
        additional_data_required="QA inspection results, batch / lot or serial numbers, supplier defect and RMA reports, "
                                 "warranty claims, store returns-handling audits",
        double_counting_risk=f"Returns ledger, separate from lost sales; the cluster's own 'Faulty' refunds changed "
                             f"{eur(cl_fault)} (below the control-store rate), so no overlap with the cluster excess is removed",
        conclusion="Concentrated in a few stores and recent sale cohorts, across products: consistent with either a local "
                   "product batch or a change in how those stores record returns. Cause is a Hypothesis.")
    add(driver_id="D06", candidate_driver="Product quality problem vs store recording practice behind 'Faulty' returns",
        affected_scope="Same as D05", observed_change="Not observable",
        mechanism="Either defective stock shipped to these stores, or a change in till reason coding / returns policy",
        estimated_impact_eur=fc, estimated_impact_pp=pp(fc), impact_range_eur=rng("electronics_faulty_returns"),
        evidence_supporting=f"In the stores with significant increases, {int((sst > 0).sum())} of {len(sst)} suppliers rose, "
                            f"while the largest holds {top_share_sst:.0%} of the increase: neither a single-supplier defect "
                            "nor a store- or distribution-side cause can be excluded",
        evidence_against="No QA data either way",
        method="None possible with current data", uncertainty="Unresolved", evidence_level="Hypothesis",
        additional_data_required="QA inspection results, batch / lot or serial numbers, supplier defect and RMA reports, "
                                 "warranty claims, store returns-handling audits, and the distribution centre / delivery "
                                 "route serving these stores",
        double_counting_risk="Same slice as D05 (not additional)",
        conclusion="UNRESOLVED.")
    m1, m4 = pr["m1"], pr["m4"]
    rob = bool(sens.loc["home_kitchen_promotion", "robust"])
    add(driver_id="D07", candidate_driver="Home & Kitchen promotion programme (deeper, more frequent discounts)",
        affected_scope="Home & Kitchen, all stores",
        observed_change=f"Discount rate on gross sales {100 * m4['discount_rate_py']:.1f}% to {100 * m4['discount_rate_cy']:.1f}%; "
                        f"H&K sales {m1['delta_pct_sales']:+.1f}% vs control categories in the same store-weeks, units "
                        f"{m1['delta_pct_units']:+.1f}%",
        mechanism="Lower price per unit on a larger share of sales without a net volume gain",
        estimated_impact_eur=c["promotion"], estimated_impact_pp=pp(c["promotion"]),
        impact_range_eur=rng("home_kitchen_promotion"),
        evidence_supporting=f"M1 DiD 95% CI {eur(m1['ci_eur'][0])} to {eur(m1['ci_eur'][1])}; pre-period gap slope "
                            f"{m1['pre_trend_slope_per_week']:+.4f} log points a week; units {m1['delta_pct_units']:+.1f}% "
                            f"(CI {100 * (np.exp(m1['ci_log_units'][0]) - 1):+.1f}% to {100 * (np.exp(m1['ci_log_units'][1]) - 1):+.1f}%)"
                            f", so the fall is mostly price; M4 discount accounting {eur(m4['effect_eur_volume_held'])}",
        evidence_against=f"Event-level (M3 {eur(pr['m3']['effect_eur'])}) and dose-response (M2 {eur(pr['m2']['effect_eur'])}) "
                         f"methods say the extra promotions ADDED revenue. Their baselines are exposed to back-to-back "
                         f"promotions ({pr['m3']['baseline_contamination_share'].get(cy_year(R), float('nan')):.0%} of current-year "
                         f"events follow another promotion of the same store-SKU within the baseline window), but the "
                         "disagreement is real",
        method="M1 category DiD; M2 dose-response; M3 event-level; M4 discount-rate accounting",
        uncertainty=f"Range {rng('home_kitchen_promotion')}; sign depends on method",
        evidence_level="Statistical association" if not rob else "Root-cause evidence",
        additional_data_required="Promotion calendar with objectives, planned vs actual depth, a controlled test (holdout "
                                 "stores) or at least SKU-level price elasticities",
        double_counting_risk="Different category from D03 / D05; the cluster's share is below the control-store rate, so no "
                             "overlap with the cluster excess is removed",
        conclusion="Associated with the H&K decline and plausible, but not established: the counterfactual is method-dependent.")
    rdist = el["range_distribution"]
    by_status = rdist.groupby("sku_status")["sales_change"].sum()
    dist_eff = float(rdist["distribution_effect"].sum())
    rate_eff = float(rdist["rate_effect"].sum())
    top = el["top_supplier"]
    tv = rdist[rdist["supplier_name"] == top].set_index("sku_status")["sales_change"]
    add(driver_id="D08", candidate_driver="Range and distribution change in Electronics & Tech",
        affected_scope=f"{el['category']}, stores outside the cluster",
        observed_change=f"Outside the cluster, category sales {eur(float(rdist['sales_change'].sum()))}: delisted SKUs "
                        f"{eur(by_status.get('delisted', 0.0))}, new SKUs {eur(by_status.get('new', 0.0))}, continuing SKUs "
                        f"{eur(by_status.get('continuing', 0.0))} (fewer ranged store-SKU-weeks {eur(dist_eff)}; lower sales "
                        f"per ranged store-SKU-week {eur(rate_eff)})",
        mechanism="Revenue moves between delisted, new and continuing SKUs; continuing SKUs sold less per ranged week",
        estimated_impact_eur=np.nan, estimated_impact_pp=np.nan, impact_range_eur="n/a (a partition, not an estimate)",
        evidence_supporting=f"Measured SKU by SKU (FACT). New {top} SKUs {eur(tv.get('new', 0.0))} while its continuing SKUs "
                            f"{eur(tv.get('continuing', 0.0))}: consistent with customers switching to the new models",
        evidence_against="Competing explanations for the continuing-SKU fall: partial-week stock-outs (not in the primary "
                         "lost-sales estimate), substitution to new SKUs while older ones were out of stock, and switching "
                         "between models; none can be separated without daily stock and customer-level data",
        method="SKU status by presence in each H2; distribution effect = change in ranged store-SKU-weeks x prior-year sales "
               "per ranged week", uncertainty="n/a", evidence_level="Observed change",
        additional_data_required="Range plan and delisting dates, customer-level purchase history (switching between models)",
        double_counting_risk="A partition of the category change; not added to the attribution. The unexplained part sits "
                             "in the residual (D09)",
        conclusion="The range churn itself added revenue outside the cluster (new SKUs more than replaced delisted ones); the "
                   "decline sits in continuing SKUs. Whether new SKUs took their sales, partial-week stock-outs or substitution "
                   "during stock-outs explain it is a Hypothesis.")
    res = R["overlap"]["attribution"]
    resid = float(res.iloc[-1]["amount_eur"])
    rb = R["overlap"]["residual_breakdown"]
    add(driver_id="D09", candidate_driver="Residual: change not attributed to the drivers above",
        affected_scope="Mainly Electronics & Tech outside the cluster",
        observed_change="; ".join(f"{r.part} {eur(r.amount_eur)}" for r in rb.itertuples()),
        mechanism="Not identified", estimated_impact_eur=resid, estimated_impact_pp=pp(resid), impact_range_eur="n/a",
        evidence_supporting="Closes the exclusive attribution exactly; outside the cluster, categories other than E&T and H&K "
                            "were flat, so this is not estate-wide softness",
        evidence_against="n/a", method="Total minus exclusive components; split by where it sits",
        uncertainty="Absorbs the uncertainty of every component", evidence_level="Observed change",
        additional_data_required="Daily stock positions per SKU, customer-level purchase history (switching between E&T models), market data for E&T",
        double_counting_risk="None by construction", conclusion="Not attributed. Mostly E&T continuing-SKU sales outside the "
                                                                 "cluster (see D08).")
    df = pd.DataFrame(rows)[COLUMNS]
    assert df["evidence_level"].isin(LEVELS).all()
    return df
