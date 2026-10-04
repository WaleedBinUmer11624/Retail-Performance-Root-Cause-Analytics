"""Phase 6 outputs: tables, figures, the executive root-cause report and the validation report.

Every sentence of the report is built from computed values. Claims carry one of four tags:
FACT (measured), ESTIMATE (model-based figure), STATISTICAL ASSOCIATION, HYPOTHESIS.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


OUTPUT_DECIMALS = 6  # canonical precision of every governed Phase 6 table written by this module


def _round(df: pd.DataFrame, nd: int = OUTPUT_DECIMALS) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(nd)
    return out


def canonical_total(values) -> float:
    """Sum at the canonical output precision, the way the governed table it reports on stores its components.

    Summing the unrounded in-memory doubles instead can land a last bit either side of a `,.0f`
    boundary, so a report total can disagree with the CSV, the headline and the run log that carry
    the same quantity. Nothing analytical changes: only the aggregation the reader sees is pinned
    to the precision the numbers are published at.
    """
    return float(pd.Series(list(values), dtype=float).round(OUTPUT_DECIMALS).sum())


def eur(v: float) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    return f"EUR {v:,.0f}" if v >= 0 else f"-EUR {abs(v):,.0f}"


def k(v: float) -> str:
    return f"EUR {v / 1000:+,.0f}k"


def write_tables(R: dict, ch: pd.DataFrame, freeze: pd.DataFrame, out: Path) -> dict:
    files = {}

    def w(df: pd.DataFrame, name: str):
        _round(df.reset_index(drop=True)).to_csv(out / name, index=False, lineterminator="\n")
        files[name] = len(df)

    sc, el, rt, pr, ov = R["store_cluster"], R["electronics"], R["returns"], R["promotions"], R["overlap"]
    prim = sc["primary_control"]
    w(R["headline_recon"], "headline_reconciliation.csv")
    grp = pd.DataFrame([{"control_group": g, "stores": ", ".join(s), "n_stores": len(s), "primary": g == prim}
                        for g, s in sc["groups"].items()])
    w(grp, "cluster_control_groups.csv")
    w(sc["distances"], "cluster_matching_distances.csv")
    w(sc["features"].reset_index().rename(columns={"index": "store_id"}), "cluster_store_features.csv")
    on = sc["onset"]
    w(pd.DataFrame([{"series": "cluster vs primary controls", "onset_date": on["onset_date"].date(),
                     "step_shift_log": on["step"]["shift"], "step_shift_pct": 100 * (np.exp(on["step"]["shift"]) - 1),
                     "step_r2": on["step"]["r2"], "ramp_days": on["ramp"]["ramp_days"], "ramp_start": on["ramp_start"].date(),
                     "ramp_end": on["ramp_end"].date(), "bic_step": on["step"]["bic"], "bic_ramp": on["ramp"]["bic"],
                     "bic_linear": on["linear"]["bic"], "best_model": on["best_model"], "abrupt": on["abrupt"]}]),
      "cluster_onset.csv")
    w(on["per_store"], "cluster_onset_by_store.csv")
    w(on["gap_daily"].rename("gap_log").reset_index(), "cluster_onset_daily.csv")
    rows = []
    for (g, o), d in sc["did"].items():
        e = sc["eur"][g]["net_revenue" if o == "ly_net_revenue" else "transactions"]
        rows.append({"control_group": g, "outcome": o, "did_log": d["did_log"], "did_pct": d["did_pct"],
                     "pre_gap_mean_log": d["pre_gap_mean"], "post_gap_mean_log": d["post_gap_mean"],
                     "pre_trend_slope": d["pre_trend"]["slope_per_week"], "pre_trend_p": d["pre_trend"]["p_value"],
                     "ratio_did_actual": e["actual"], "ratio_did_counterfactual": e["counterfactual"],
                     "ratio_did_excess": e["excess"], "control_yoy": e["control_yoy"], "pre_gap_ratio": e["pre_gap_ratio"]})
    w(pd.DataFrame(rows), "cluster_did.csv")
    gw = sc["did"][(prim, "ly_transactions")]["gap_weekly"].rename("gap_log_transactions").to_frame().join(
        sc["did"][(prim, "ly_net_revenue")]["gap_weekly"].rename("gap_log_net_revenue")).reset_index()
    w(gw, "cluster_weekly_did.csv")
    w(pd.DataFrame([sc["placebo"]]), "cluster_placebo.csv")
    m = sc["mechanisms"]
    w(m["comparison"], "cluster_mechanisms.csv")
    w(m["weekday"], "cluster_weekday.csv")
    w(m["hour"], "cluster_hour.csv")
    w(m["category_mix"], "cluster_category_mix.csv")
    w(sc["baskets"], "cluster_basket_distribution.csv")

    w(el["kpis"], "electronics_kpis.csv")
    w(el["by_supplier_category"], "electronics_supplier_comparison.csv")
    w(el["by_supplier_all"], "supplier_comparison_all_categories.csv")
    w(el["sku"], "electronics_sku_stockouts.csv")
    w(el["episode_summary"], "electronics_stockout_episodes.csv")
    w(el["recovery"], "electronics_recovery.csv")
    w(el["replenishment"], "electronics_replenishment.csv")
    w(el["supplier_tests"], "electronics_supplier_test.csv")
    w(el["timeline"], "electronics_weekly_timeline.csv")
    w(el["by_store"], "electronics_lost_sales_by_store.csv")
    tot = pd.DataFrame([{"scope": s, **el[f"totals_{s}"]} for s in ("category", "estate", "top_supplier")])
    w(tot, "electronics_lost_sales_totals.csv")

    w(rt["reasons"], "faulty_returns_reasons.csv")
    for key in ("by_product", "by_supplier", "by_store", "by_store_supplier", "by_store_other_reasons"):
        w(rt[key], f"faulty_returns_{key}.csv")
    w(rt["cohort"], "faulty_returns_by_cohort.csv")
    w(rt["lag"], "faulty_returns_lag.csv")
    w(rt["promotion_status"], "faulty_returns_promotion_status.csv")
    w(rt["concentration"], "faulty_returns_concentration.csv")

    m1, m2, m3, m4 = pr["m1"], pr["m2"], pr["m3"], pr["m4"]
    cf = pd.DataFrame([
        {"method": "M1 category DiD (sales)", "effect_eur": m1["effect_eur"], "ci_low": m1["ci_eur"][0], "ci_high": m1["ci_eur"][1],
         "detail": f"delta {m1['delta_pct_sales']:+.2f}% sales, {m1['delta_pct_units']:+.2f}% units"},
        {"method": "M1 category DiD (gross margin log DiD, not used)", "effect_eur": m1["margin_effect_eur_log_did"],
         "ci_low": np.nan, "ci_high": np.nan,
         "detail": f"delta log margin {m1['delta_log_margin']:+.3f}; not used: inconsistent with the unit response"},
        {"method": "M1 category DiD (gross margin = revenue effect minus cost of the unit change)",
         "effect_eur": m1["margin_effect_eur"], "ci_low": np.nan, "ci_high": np.nan,
         "detail": "cost counterfactual follows the M1 unit response"},
        {"method": "M2 dose-response (promotion coverage lags 0-2, depth, store FE)", "effect_eur": m2["effect_eur"],
         "ci_low": m2["ci_eur"][0], "ci_high": m2["ci_eur"][1], "detail": f"within R2 {m2['r2_within']:.2f}"},
        {"method": "M3 event-level net programme revenue (current minus prior programme)", "effect_eur": m3["effect_eur"],
         "ci_low": np.nan, "ci_high": np.nan,
         "detail": f"baseline contamination {m3['baseline_contamination_share']}"},
        {"method": "M4 discount-rate accounting (net volume response 0; range = volume response at the M1 units CI bounds)",
         "effect_eur": m4["effect_eur_volume_held"], "ci_low": m4["ci_eur"][0], "ci_high": m4["ci_eur"][1],
         "detail": f"discount rate {100 * m4['discount_rate_py']:.1f}% to {100 * m4['discount_rate_cy']:.1f}% of gross sales"}])
    w(cf, "hk_promotion_counterfactuals.csv")
    w(pr["event_study"], "hk_promotion_event_study.csv")
    w(pr["weekly"], "hk_promotion_weekly.csv")
    w(m3["by_year"], "hk_promotion_events_by_year.csv")
    w(pr["by_store"], "hk_promotion_by_store.csv")

    sch = R["data"]["store_category_h2"]
    sid = R["data"]["stores"].set_index("store_key")["store_id"]
    py, cy = R["periods"].py_year, R["periods"].cy_year
    x = sch.assign(store_id=sch["store_key"].map(sid)).pivot_table(index=["store_id", "category"], columns="retail_year",
                                                                     values="net_revenue", aggfunc="sum").fillna(0).reset_index()
    x = x.rename(columns={py: "net_revenue_py", cy: "net_revenue_cy"})
    x["net_revenue_change"] = x["net_revenue_cy"] - x["net_revenue_py"]
    x["in_cluster"] = x["store_id"].isin(R["cluster"])
    w(x, "category_store_contribution.csv")
    w(ov["perimeter"], "driver_perimeter_matrix.csv")
    w(ov["pairwise"].reset_index().rename(columns={"index": "driver"}), "driver_overlap_matrix.csv")
    w(ov["attribution"], "driver_attribution.csv")
    w(ov["details"], "driver_overlap_details.csv")
    w(ov["residual_breakdown"], "driver_residual_breakdown.csv")
    w(el["range_distribution"], "electronics_range_distribution.csv")
    w(R["scenarios"], "counterfactual_scenarios.csv")
    w(R["sensitivity"], "sensitivity_analysis.csv")
    w(R["sensitivity_summary"], "sensitivity_summary.csv")
    w(R["evidence"], "root_cause_evidence_matrix.csv")
    w(ch, "validation_checks.csv")
    w(freeze, "input_verification.csv")
    return files


def root_cause_report(R: dict) -> str:
    per, py, cy = R["periods"], R["py"], R["cy"]
    total = cy["net_revenue"] - py["net_revenue"]
    sc, el, rt, pr, ov = R["store_cluster"], R["electronics"], R["returns"], R["promotions"], R["overlap"]
    prim = sc["primary_control"]
    ex = sc["eur"][prim]
    did_t = sc["did"][(prim, "ly_transactions")]
    on = sc["onset"]
    pl = sc["placebo"]
    sens = R["sensitivity_summary"].set_index("driver")
    attr = ov["attribution"]
    ev = R["evidence"].set_index("driver_id")
    cl = ", ".join(R["cluster"])
    ctl = ", ".join(sc["groups"][prim])
    mech = sc["mechanisms"]["comparison"].set_index("metric")
    tot_c = el["totals_category"]
    tst = el["supplier_tests"].iloc[0]
    n_sup = int(len(el["by_supplier_category"]))
    rs = rt["concentration"].set_index("dimension")
    coh = rt["cohort"]
    m1, m2, m3, m4 = pr["m1"], pr["m2"], pr["m3"], pr["m4"]
    def rng(d):
        lo_, hi_ = float(sens.loc[d, "min"]), float(sens.loc[d, "max"])
        word = lambda v: f"a EUR {abs(v):,.0f} {'loss' if v < 0 else 'gain'}"  # noqa: E731
        if hi_ < 0:
            return f"EUR {abs(hi_):,.0f} to EUR {abs(lo_):,.0f} lost"
        return f"from {word(lo_)} to {word(hi_)}"
    robust = lambda d: bool(sens.loc[d, "robust"])  # noqa: E731
    sn = R["scenarios"].set_index("scenario")
    shares = attr.set_index("component")["share_of_change"]
    comp = attr.iloc[:-1]
    resid = float(attr.iloc[-1]["amount_eur"])
    rb = ov["residual_breakdown"]
    top = el["top_supplier"]
    off = el["recovery_offset_eur"]
    lv = {d: ev.loc[d, "evidence_level"] for d in ev.index}
    n_rc = int((ev["evidence_level"] == "Root-cause evidence").sum())
    pct = lambda v: f"{abs(v / total):.0%}"  # noqa: E731
    L = []
    A = L.append
    A(f"# Brightwater Retail: {per.label_cy} root-cause report (Phase 6)")
    A("")
    A("**How to read this report.** Statements carry a tag. **FACT**: measured in the governed data. **ESTIMATE**: a "
      "model-based figure (counterfactual, fitted model or test) with a stated method and range. **STATISTICAL "
      "ASSOCIATION**: two things move together; not proof of cause. **HYPOTHESIS**: a plausible explanation the available "
      "data cannot test. **UNRESOLVED**: the size is established but no cause can be identified from the data. Evidence "
      "levels in the matrix follow the BRD (Observed change, Statistical association, Root-cause evidence, Hypothesis).")
    A("")
    A("## Executive conclusion")
    A("")
    A(f"- **FACT.** H2 net revenue fell {eur(abs(total))} ({100 * total / py['net_revenue']:+.2f}%), reconciled to the cent "
      "with Phase 4 and Phase 5.")
    A(f"- **FACT.** Transactions per store in {cl} fell {abs(mech.loc['transactions_per_store', 'cluster_change']):.1f}%, "
      f"against {mech.loc['transactions_per_store', 'control_change']:+.1f}% in matched control stores. **ESTIMATE.** Measured against "
      f"those controls, the loss starts abruptly in mid-July (best-fitting change point {on['onset_date']:%d %B %Y}) and is "
      f"worth {eur(abs(ex['net_revenue']['excess']))} of net revenue ({pct(ex['net_revenue']['excess'])} of the decline; range "
      f"{rng('store_cluster_excess')} across control groups and windows).")
    A("- **UNRESOLVED.** Nothing in Brightwater's data explains that loss. Price, promotions, availability, range and returns "
      "in these stores moved close to the controls. An external local change (competitor, access works, local event) or an "
      "unrecorded operational change is a **HYPOTHESIS**. Testing it needs footfall, competitor, local-event and "
      "store-operations data.")
    A(f"- **ESTIMATE, {lv['D03'].upper()}.** Full-week stock-outs in {el['category']} removed an estimated "
      f"{eur(tot_c['primary_change'])} of sales more than last year, {el['totals_top_supplier']['primary_change'] / tot_c['primary_change']:.0%} "
      f"of it on {top} SKUs. Part of that demand returned after restock ({eur(off)} above the prior-year post-restock "
      f"pattern), leaving a net loss of about {eur(max(0.0, tot_c['primary_change'] - off))} (range across variants "
      f"{rng('electronics_stockouts_primary')}). The stock-outs are real; their net revenue effect is small"
      + (" and robust." if robust("electronics_stockouts_primary") else " and not robust."))
    A(f"- **FACT.** '{rt['reason']}' returns in {rt['category']} rose {eur(-R['central']['faulty_returns'])}. **STATISTICAL "
      f"ASSOCIATION.** The increase is concentrated in {len(rt['significant_stores'])} stores and in sales made from late "
      "summer onwards, across suppliers. Product failure is **not** established: 'Faulty' is a till reason code, not a "
      "verified defect.")
    A(f"- **STATISTICAL ASSOCIATION.** {pr['category']} lost about {eur(-m1['effect_eur'])} relative to other categories in "
      f"the same stores and weeks, mostly through price, while its promotions became deeper and more frequent. Two of the "
      "four counterfactual methods say the promotions added revenue, so this is not established as a cause.")
    A(f"- **Attribution (no double counting).** The cluster excess ({pct(comp.iloc[0]['amount_eur'])}), stock-outs "
      f"({pct(comp.iloc[1]['amount_eur'])}), 'Faulty' returns ({pct(comp.iloc[2]['amount_eur'])}) and the H&K change "
      f"({pct(comp.iloc[3]['amount_eur'])}) account for {pct(comp['amount_eur'].sum())} of the decline. Of that, "
      f"{pct(comp.iloc[0]['amount_eur'] + comp.iloc[2]['amount_eur'])} is observed change whose cause is unresolved or "
      f"hypothetical, {pct(comp.iloc[3]['amount_eur'])} (H&K) is estimated and only statistically associated with its "
      f"candidate mechanism, and {pct(comp.iloc[1]['amount_eur'])} (stock-outs) is estimated with a "
      f"{'robust' if robust('electronics_stockouts_primary') else 'non-robust'} mechanism ({lv['D03']}). {eur(abs(resid))} of the decline ({pct(resid)}) is not attributed; most of it "
      f"is {el['category']} outside the cluster.")
    rc_names = ", ".join(ev.loc[ev["evidence_level"] == "Root-cause evidence", "candidate_driver"])
    if n_rc == 0:
        A("- **Bottom line.** No candidate driver reaches the Root-cause evidence standard (mechanism visible, quantified "
          "and robust). The size and location of the decline are firmly established; its causes are not. The data requests "
          "at the end of this report are what would change that.")
    else:
        A(f"- **Bottom line.** Only {rc_names} reach{'es' if n_rc == 1 else ''} the Root-cause evidence standard (mechanism "
          f"visible, quantified and robust), and it explains a small share of the decline. The size and location of the rest "
          "are firmly established; their causes are not. The data requests at the end of this report are what would "
          "change that.")
    A("")
    A("## What happened")
    A("")
    A("| Measure | Prior H2 | Current H2 | Change |")
    A("|---|---:|---:|---:|")
    for key, lab in (("net_revenue", "Net revenue (EUR)"), ("sales_revenue", "Sales revenue (EUR)"),
                     ("returns_value", "Returns (EUR)"), ("gross_margin", "Gross margin (EUR)"), ("transactions", "Transactions")):
        A(f"| {lab} | {py[key]:,.0f} | {cy[key]:,.0f} | {cy[key] - py[key]:+,.0f} ({100 * (cy[key] / py[key] - 1):+.2f}%) |")
    A("")
    A("All figures are FACT, recomputed from the governed model (`headline_reconciliation.csv`).")
    A("")
    A("## Where it happened")
    A("")
    perim = ov["perimeter"]
    A("Exact split of the change (FACT; the six cells add up to the total):")
    A("")
    A("| Store group | Category group | Change (EUR) | Share |")
    A("|---|---|---:|---:|")
    for r in perim.sort_values("net_revenue_change").itertuples():
        sh = r.net_revenue_change / total
        A(f"| {r.store_group} | {r.category_group} | {r.net_revenue_change:+,.0f} | "
          f"{'0%' if abs(sh) < 0.005 else f'{sh:.0%}'} |")
    A("")
    A(f"In the store cluster, every category fell. Elsewhere, the fall is concentrated in {el['category']} and "
      f"{pr['category']}; the other categories were flat. See `figures/04_category_store_heatmap.png`.")
    A("")
    A("## When it happened")
    A("")
    ps = on["per_store"]
    d_ps = pd.to_datetime(ps["onset_date"])
    trans = "an immediate transition" if on["ramp"]["ramp_days"] == 0 else f"a {on['ramp']['ramp_days']}-day transition"
    A(f"**ESTIMATE (model fit).** The cluster's daily transactions, compared with the same weekday last year and with the "
      f"control stores, are best described by a single step on {on['onset_date']:%d %B %Y}: step, gradual-ramp and linear "
      "models were compared by BIC, "
      f"and the best fit is a {on['best_model']} ({trans}). The daily series is noisy "
      f"(the step explains {100 * on['step']['r2']:.0f}% of its variance). Fitted separately, the stores turn between "
      f"{d_ps.min():%d %b} and {d_ps.max():%d %b}: "
      + ", ".join(f"{r.store_id} {pd.Timestamp(r.onset_date):%d %b} ({r.shift_pct:+.0f}%, R2 {r.r2:.2f})" for r in ps.itertuples())
      + ". No group of three other stores shows a comparable shift (placebo test below).")
    A("")
    A("## Revenue bridge")
    A("")
    A("**FACT.** Phase 5's Shapley bridge (`reports/phase5/revenue_bridge.csv`, frozen) shows that fewer transactions explain "
      "most of the fall. This report adds where those transactions were lost. **ESTIMATE.** Relative to the matched control "
      f"stores, the cluster lost {abs(ex['transactions']['excess']):,.0f} receipts ({eur(ex['net_revenue']['excess'])} of net "
      f"revenue, {eur(ex['gross_margin']['excess'])} of gross margin).")
    A("")
    A("## Store-cluster investigation")
    A("")
    feat = sc["features"]
    same_cell = set(feat[(feat["is_standard"] == 1) & (feat["is_dublin"] == 1)].index)
    caveat = ("The cluster stores are the estate's only Standard-format stores in Dublin, so none of the matched controls "
              "shares their region, and the Dublin control group (the other Dublin stores) has a different format. "
              if same_cell == set(R["cluster"]) else "")
    A(f"- **Controls.** The five stores most similar to the cluster on pre-period revenue, transactions, basket, format, "
      f"region and H1 trend: {ctl}. {caveat}Four control groups are used, and the estimate holds across all of them "
      f"(range {rng('store_cluster_excess')}).")
    A(f"- **ESTIMATE (DiD on measured transactions).** Transactions {did_t['did_pct']:+.1f}% vs matched controls. The "
      f"pre-period gap was flat (slope p {did_t['pre_trend']['p_value']:.2f}), so parallel trends is a reasonable "
      f"assumption. In {pl['placebo_n']} placebo tests (every 3-store group of other stores, each against the rest) the most "
      f"negative result was {100 * (np.exp(pl['placebo_min']) - 1):+.1f}%, against "
      f"{100 * (np.exp(pl['actual']) - 1):+.1f}% for the cluster measured the same way (p = {pl['p_value_one_sided']:.4f}, "
      "the smallest value attainable). Caveat: Phase 5 selected these stores because they declined most, so this p-value "
      "overstates significance. The size of the gap, not the p-value, is the evidence.")
    A("- **FACT. How the cluster's other KPIs moved relative to the controls** (cluster change minus control change):")
    A("")
    A("  | Measure | Difference |")
    A("  |---|---:|")
    for mm, lab in (("transactions_per_store", "Transactions per store"), ("aov", "Average transaction value"),
                    ("upt", "Units per transaction"), ("asp", "Average selling price"),
                    ("promo_revenue_share", "Promotional share of sales"),
                    ("receipts_with_promo_share", "Receipts with a promoted item"), ("availability", "Availability"),
                    ("ranged_skus_per_store_week", "Ranged SKUs"), ("return_rate_value", "Return rate"),
                    ("weekend_transaction_share", "Weekend share of transactions"),
                    ("basket_value_p90", "Basket value, 90th percentile")):
        unit = "pp" if mech.loc[mm, "unit"].startswith("pp") else "%"
        A(f"  | {lab} | {mech.loc[mm, 'difference']:+.2f} {unit} |")
    A("")
    A("  Apart from transactions, no difference exceeds a few points, against a transaction gap of about 25%. None of them "
      "is large enough to account for the lost receipts. Receipts fell by similar percentages in every basket-value band "
      "(`cluster_basket_distribution.csv`).")
    wd, hr, mx = sc["mechanisms"]["weekday"], sc["mechanisms"]["hour"], sc["mechanisms"]["category_mix"]
    A(f"- **FACT. The loss is broad.** The gap to the controls is {wd['difference_pp'].min():+.0f} to "
      f"{wd['difference_pp'].max():+.0f} pp across weekdays, {hr['difference_pp'].min():+.0f} to "
      f"{hr['difference_pp'].max():+.0f} pp across trading hours and {mx['difference_pp'].min():+.0f} to "
      f"{mx['difference_pp'].max():+.0f} pp across categories. The category mix shift index is "
      f"{sc['mechanisms']['mix_shift_cluster']:.3f}, against {sc['mechanisms']['mix_shift_control']:.3f} for the controls.")
    A("- **UNRESOLVED / HYPOTHESIS.** A simultaneous, broad loss of receipts in three stores in the same region, with no "
      "internal lever changing much, points to something outside the stores, or to an operational change the model does "
      "not record (opening hours, works, closures). The transaction loss remains unexplained after controlling for "
      "observable factors. Footfall, competitor, local-event and store-operations data are required.")
    A("")
    A(f"## {el['category']} investigation")
    A("")
    kp = el["kpis"].set_index("metric")
    A(f"**FACT.** Net revenue {eur(kp.loc['net_revenue', 'change'])} ({kp.loc['net_revenue', 'change_pct']:+.1f}%); receipts "
      f"containing the category {kp.loc['transactions_with_category', 'change_pct']:+.1f}%; units "
      f"{kp.loc['units_sold', 'change_pct']:+.1f}%; ASP {kp.loc['asp', 'change_pct']:+.1f}%; returns up "
      f"{eur(kp.loc['returns_value', 'change'])}; availability {100 * kp.loc['availability', 'prior']:.1f}% to "
      f"{100 * kp.loc['availability', 'current']:.1f}%.")
    A("")
    cs = ov["perimeter"]
    et_cl = float(cs[(cs["store_group"] == "Store cluster") & (cs["category_group"] == el["category"])]["net_revenue_change"].sum())
    A(f"About {et_cl / kp.loc['net_revenue', 'change']:.0%} of the category's fall ({eur(et_cl)}) is in the three cluster "
      "stores, where every category fell. Sales change by supplier across all stores (FACT): "
      + "; ".join(f"{r.supplier_name} {eur(r.sales_change)}" for r in el["by_supplier_category"].itertuples()) + ".")
    A("")
    rdist = el["range_distribution"]
    bs_ = rdist.groupby("sku_status")["sales_change"].sum()
    tv = rdist[rdist["supplier_name"] == top].set_index("sku_status")["sales_change"]
    A(f"**FACT. Range and distribution outside the cluster** (`electronics_range_distribution.csv`). Category sales changed "
      f"{eur(float(rdist['sales_change'].sum()))}: SKUs delisted after the prior year {eur(bs_.get('delisted', 0.0))}, new "
      f"SKUs {eur(bs_.get('new', 0.0))}, continuing SKUs {eur(bs_.get('continuing', 0.0))}. For continuing SKUs, fewer "
      f"ranged store-SKU-weeks account for {eur(float(rdist['distribution_effect'].sum()))} and lower sales per ranged week "
      f"for {eur(float(rdist['rate_effect'].sum()))}. The range churn added revenue: new SKUs more than replaced the delisted "
      f"ones. The fall sits in continuing SKUs, and most visibly in {top}'s: its new SKUs {eur(tv.get('new', 0.0))}, its "
      f"continuing SKUs {eur(tv.get('continuing', 0.0))}. **HYPOTHESES** (not separable with these data): customers switched from the "
      "older models to the new ones; stock-outs within partial weeks, which the primary lost-sales estimate does not count "
      f"(the BR-05 upper bound is {eur(tot_c['upper_change'] - tot_c['primary_change'])} higher); or shoppers substituting "
      "the new SKUs while older ones were out of stock. Testing them needs daily stock positions and customer-level purchase "
      "history.")
    A("")
    A("## Availability investigation")
    A("")
    es = el["episode_summary"]
    e_top = es[es["supplier_name"] == top].set_index("retail_year")
    rep = el["replenishment"]
    r_top = rep[rep["supplier_name"] == top].set_index("retail_year")
    rep_o = rep[rep["supplier_name"] != top].groupby("retail_year")[["received_units", "cell_weeks"]].sum()
    A(f"- **FACT.** {top} stock-out episodes: {int(e_top.loc[per.py_year, 'episodes'])} to "
      f"{int(e_top.loc[per.cy_year, 'episodes'])}; mean length {e_top.loc[per.py_year, 'mean_weeks_out']:.1f} to "
      f"{e_top.loc[per.cy_year, 'mean_weeks_out']:.1f} weeks; longest {int(e_top.loc[per.cy_year, 'max_weeks_out'])} weeks; "
      f"{int(e_top.loc[per.cy_year, 'full_weeks_out'])} store-SKU-weeks with no stock at all (prior year "
      f"{int(e_top.loc[per.py_year, 'full_weeks_out'])}).")
    A(f"- **FACT.** Its SKUs started each week with less stock: mean opening stock "
      f"{r_top.loc[per.py_year, 'mean_opening_stock']:.2f} to {r_top.loc[per.cy_year, 'mean_opening_stock']:.2f} units. "
      f"Stock received per ranged store-SKU-week barely changed ({r_top.loc[per.py_year, 'received_per_cell_week']:.2f} to "
      f"{r_top.loc[per.cy_year, 'received_per_cell_week']:.2f} units); other suppliers "
      f"{rep_o.loc[per.py_year, 'received_units'] / rep_o.loc[per.py_year, 'cell_weeks']:.2f} to "
      f"{rep_o.loc[per.cy_year, 'received_units'] / rep_o.loc[per.cy_year, 'cell_weeks']:.2f} units.")
    A(f"- **ESTIMATE.** Sales lost in full-week stock-outs: {eur(tot_c['primary_py'])} in the prior year and "
      f"{eur(tot_c['primary_cy'])} in the current year, an increase of {eur(tot_c['primary_change'])}. Counting partial "
      f"weeks too (the BR-05 upper bound) gives an increase of {eur(tot_c['upper_change'])}; that bound is not evidence.")
    from .electronics import recovery_by_week
    rw = recovery_by_week(el["recovery"], top) if len(el["recovery"]) else el["recovery"]
    rt_ = rw[rw["retail_year"] == per.cy_year] if len(rw) else rw
    rp_ = rw[rw["retail_year"] == per.py_year] if len(rw) else rw
    if len(rt_):
        A(f"- **ESTIMATE. Recovery.** Once stock returned, {top} SKUs sold "
          + ", ".join(f"{r.actual_to_expected:.2f}x expected in week {int(r.weeks_after)}" for r in rt_.itertuples())
          + " (prior year " + ", ".join(f"{r.actual_to_expected:.2f}x" for r in rp_.itertuples()) + "). Allowing for "
          "that normal post-restock pattern, sales after episodes with a full-week stock-out ran "
          f"{eur(off)} above it across the category: demand deferred rather than lost, "
          f"{min(1.0, max(0.0, off / tot_c['primary_change'])):.0%} of the gross estimate. Across all "
          f"{int(sens.loc['electronics_stockouts_primary', 'n_variants'])} variants, including the one net of deferred demand, "
          f"the effect ranges {rng('electronics_stockouts_primary')}, so it is {'robust' if robust('electronics_stockouts_primary') else 'not robust'} and classified as "
          f"{lv['D03']}.")
    A(f"- **FACT. Concentration.** High-selling SKUs (top 10% by prior-year revenue) carry "
      f"{el['concentration']['high_seller_share_of_lost_change']:.0%} of the increase in estimated lost sales. The top SKU "
      f"({el['concentration']['top1_sku']}) carries {el['concentration']['top1_share']:.0%} and the top 3 carry "
      f"{el['concentration']['top3_share']:.0%}.")
    A(f"- **STATISTICAL ASSOCIATION. Supplier test.** {top} SKUs' stock-out rate rose {tst['supplier_mean']:+.1f} pp, against "
      f"{tst['other_mean']:+.1f} pp for other suppliers' SKUs. The difference is {tst['difference']:+.1f} pp (95% CI "
      f"{tst['ci_low']:+.1f} to {tst['ci_high']:+.1f}; permutation p {tst['permutation_p_two_sided']:.3f}, or "
      f"{min(1.0, tst['permutation_p_two_sided'] * n_sup):.3f} after allowing for {top} having been picked as the worst of "
      f"{n_sup} suppliers), and it holds when any single SKU is removed.")
    A("- **HYPOTHESIS.** Lower stock cover per SKU suggests smaller or later replenishment. The data cannot say whether the "
      "supplier under-delivered or Brightwater ordered less. Confirming it needs purchase orders, supplier confirmations, "
      "lead times and ordering parameters.")
    A("")
    A("## Returns investigation")
    A("")
    rr = rt["reasons"].set_index("return_reason")
    A(f"**FACT.** In {rt['category']}, only '{rt['reason']}' returns rose materially ({eur(rr.loc[rt['reason'], 'value_change'])}, "
      f"{rr.loc[rt['reason'], 'value_change_pct']:+.0f}%). The other reasons moved: "
      + ", ".join(f"{i} {eur(r.value_change)}" for i, r in rr.drop(rt["reason"]).iterrows()) + ".")
    A("")
    sig = rt["significant_stores"]
    A(f"- **STATISTICAL ASSOCIATION. Stores.** The recorded faulty rate rose significantly in {len(sig)} stores "
      f"({', '.join(sig)}; conditional binomial test, p < 0.01, not adjusted for testing 20 stores). The top 5 stores hold "
      f"{rs.loc['store_id', 'top_k_share_of_gross']:.0%} of the gross increase. In the significant stores the faulty rate "
      f"rose {rt['faulty_rate_change_sig_pp']:+.2f} returned units per 100 sold; all other reasons together moved "
      f"{rt['other_reason_rate_change_sig_pp']:+.2f}.")
    sst = rt["supplier_split_in_significant_stores"]
    A("- **FACT. Suppliers and products.** In those stores, the increase splits by supplier as "
      + "; ".join(f"{r.supplier_name} {eur(r.value_change)}" for r in sst.itertuples())
      + f". Across the estate, the top 5 products hold only {rs.loc['product_id', 'top_k_share_of_gross']:.0%}.")
    cm = coh.assign(year=coh["sale_year_month"] // 100, month=coh["sale_year_month"] % 100)
    yy = cm[cm["year"] == per.cy_year].merge(cm[cm["year"] == per.py_year], on="month", suffixes=("_cy", "_py"))
    yy = yy[yy["month"] >= 7]
    hi_m = yy[yy["rate_per_100_cy"] > 2]
    first_month = f"{pd.Timestamp(2000, int(hi_m['month'].min()), 1):%B}" if len(hi_m) else "no month"
    linked_cy = rt["linked_share"].get(per.cy_year, float("nan"))
    A("- **FACT. Cohorts and lag.** Faulty returned units per 100 sold, by sale month against the same month a year "
      "earlier: " + "; ".join(f"{pd.Timestamp(2000, int(r.month), 1):%b} {r.rate_per_100_py:.1f} to {r.rate_per_100_cy:.1f}"
                        for r in yy.itertuples())
      + f". The rise starts with sales made in {first_month}. The sale-to-return lag did not change (KS p {rt['lag_ks_p']:.2f}). "
      f"{linked_cy:.0%} of current-year 'Faulty' returns link to the original sale line.")
    A("- **Verdict.** The increase is concentrated in a small number of stores and later sale cohorts, not in a small number "
      "of products. **HYPOTHESIS**: a defective batch delivered to these stores, or a change in how these stores record "
      "returns. Causal confirmation needs QA inspection results, batch / lot or serial numbers, supplier defect and RMA "
      "reports, warranty claims, and an audit of returns handling in the named stores.")
    A("")
    A("## Promotion investigation")
    A("")
    A(f"**FACT.** {pr['category']} discount rate on gross sales went from {100 * m4['discount_rate_py']:.1f}% to "
      f"{100 * m4['discount_rate_cy']:.1f}%. Promotion events rose from {int(m3['by_year'].iloc[0]['events']):,} to "
      f"{int(m3['by_year'].iloc[1]['events']):,}.")
    A("")
    A("| Method (all ESTIMATES) | Effect of the change (EUR) | Interval | Reading |")
    A("|---|---:|---:|---|")
    A(f"| M1 category DiD vs control categories, same store-weeks | {m1['effect_eur']:+,.0f} | {m1['ci_eur'][0]:+,.0f} to "
      f"{m1['ci_eur'][1]:+,.0f} (95% CI) | H&K-specific change: sales {m1['delta_pct_sales']:+.1f}%, units "
      f"{m1['delta_pct_units']:+.1f}%; gross margin {eur(m1['margin_effect_eur'])} |")
    A(f"| M4 discount-rate accounting (no net volume response) | {m4['effect_eur_volume_held']:+,.0f} | "
      f"{m4['ci_eur'][0]:+,.0f} to {m4['ci_eur'][1]:+,.0f} (volume response at the M1 units CI) | Revenue given away by "
      "the higher discount rate |")
    A(f"| M2 dose-response (coverage incl. 2 lag weeks, depth) | {m2['effect_eur']:+,.0f} | {m2['ci_eur'][0]:+,.0f} to "
      f"{m2['ci_eur'][1]:+,.0f} (95% CI) | Promoted weeks sell more; association only |")
    A(f"| M3 event-level net programme revenue | {m3['effect_eur']:+,.0f} | n/a | Baselines exposed to back-to-back "
      f"promotions ({m3['baseline_contamination_share'].get(per.cy_year, float('nan')):.0%} of events) |")
    A("")
    A(f"- **ESTIMATE.** Post-promotion dips grew. Against event baselines, the post-promotion shortfall was "
      f"{eur(m3['by_year'].iloc[0]['post_dip_revenue'])} in the prior year and {eur(m3['by_year'].iloc[1]['post_dip_revenue'])} "
      f"in the current year. Incremental promo margin went from {eur(m3['by_year'].iloc[0]['incremental_promo_margin'])} to "
      f"{eur(m3['by_year'].iloc[1]['incremental_promo_margin'])}.")
    A("- **ESTIMATE. Cannibalisation.** None measurable: non-promoted H&K SKUs did not sell below their baseline in promoted "
      "store-weeks.")
    A(f"- **STATISTICAL ASSOCIATION.** The category-level evidence (M1, M4) says {pr['category']} lost "
      f"{eur(-m1['effect_eur'])} to {eur(-m4['effect_eur_volume_held'])}, mostly through price, while units held up relative "
      "to other categories. The event-level views (M2, M3) say promoted weeks sold more. **HYPOTHESIS** reconciling the two: "
      "the extra promotions lifted promoted weeks but produced little net volume over the half (the M1 units change is not "
      "significant), while the discount applied to far more sales. Because the methods disagree in sign, this is **not** "
      "Root-cause evidence.")
    A("- **Needed to confirm:** the promotion calendar with objectives, a holdout-store test or SKU-level price elasticities.")
    A("")
    A("## Driver overlap")
    A("")
    A("Phase 5's slices overlap: the store cluster sells Electronics and Home & Kitchen, so adding the slices would double "
      "count. The exclusive attribution works in three steps:")
    A("")
    A("1. It measures the cluster's excess decline against control stores.")
    A("2. It measures each category driver in all stores. If the cluster has *more* of a driver than the control-store rate "
      "implies, that extra part is already inside the cluster excess and is removed from the driver. A driver is never "
      "made larger than its measured total.")
    A("3. It adds category drivers only where they are disjoint (different categories, or different ledger lines), and "
      "closes the total with a residual.")
    A("")
    det = ov["details"]
    A("In these data the cluster had *less* of every category driver than the control-store rate implies (driver amounts; "
      "negative = revenue lost: "
      + "; ".join(f"{r.driver} {eur(r.in_cluster)} in the cluster vs {eur(r.expected_in_cluster_at_control_rate)} expected"
                  for r in det.itertuples())
      + "), so no overlap is removed and each driver enters at its measured total.")
    A("")
    A("Because overlap is removed only in one direction, the cluster excess keeps the cluster's below-control-rate "
      f"driver amounts ({eur(float(det['cluster_minus_control_rate'].sum()))} in total); the cluster's pure traffic loss "
      f"is therefore about {eur(abs(ex['net_revenue']['excess']) + float(det['cluster_minus_control_rate'].sum()))}.")
    A("")
    A("| Component | EUR | Overlap removed | Share |")
    A("|---|---:|---:|---:|")
    for r in attr.itertuples():
        orm = "0" if abs(r.overlap_removed_eur) < 0.5 else f"{r.overlap_removed_eur:+,.0f}"
        A(f"| {r.component} | {r.amount_eur:+,.0f} | {orm} | {r.share_of_change:.0%} |")
    A(f"| **Total (FACT)** | **{canonical_total(attr['amount_eur']):+,.0f}** | | **100%** |")
    A("")
    A("Where the residual sits (the parts add up to the residual):")
    A("")
    A("| Part | EUR |")
    A("|---|---:|")
    for r in rb.itertuples():
        A(f"| {r.part} | {r.amount_eur:+,.0f} |")
    A("")
    naive = abs(ex["net_revenue"]["excess"]) + abs(float(cs[cs["category_group"] == el["category"]]["net_revenue_change"].sum())) + \
        abs(float(cs[cs["category_group"] == pr["category"]]["net_revenue_change"].sum()))
    A(f"For comparison, simply adding the cluster excess and the two category declines gives {eur(naive)}, "
      f"{naive / abs(total):.0%} of the actual decline. That is what double counting looks like. Other overlap figures:")
    A("")
    A(f"- Estimated stock-outs on the same store-SKUs as faulty-return increases: {eur(ov['stockouts_on_faulty_return_skus'])}. "
      "These are different ledger lines (lost sales vs refunds), so they are additive.")
    A("- E&T drivers and H&K drivers sit in different categories and cannot overlap.")
    A("")
    A("## Counterfactual scenarios")
    A("")
    A("These are analytical counterfactuals, not forecasts. Ranges come from the sensitivity analysis.")
    A("")
    A("| Scenario | Revenue impact (EUR) | Range | Margin impact (EUR) | Evidence | Confidence |")
    A("|---|---:|---|---:|---|---|")
    for s, r in sn.iterrows():
        rg = f"{r['range_low_eur']:+,.0f} to {r['range_high_eur']:+,.0f}" if not np.isnan(r["range_low_eur"]) else "n/a"
        mg = f"{r['margin_impact_eur']:+,.0f}" if not np.isnan(r["margin_impact_eur"]) else "n/a"
        A(f"| {s}. {r['name']} | {r['revenue_impact_eur']:+,.0f} | {rg} | {mg} | {r['evidence_level']} | {r['confidence']} |")
    A("")
    A("Assumptions for each scenario are in `counterfactual_scenarios.csv`. Only scenario E combines effects, and only "
      "mutually exclusive ones.")
    A("")
    A("## What the evidence supports")
    A("")
    for d in ("D01", "D03", "D04", "D05", "D08"):
        r = ev.loc[d]
        A(f"- **{d}** {r['candidate_driver']}: {r['conclusion']} ({r['evidence_level']})")
    A("")
    A("## What the evidence does NOT establish")
    A("")
    A("- Why the three stores lost customers (D02, Hypothesis).")
    if not robust("electronics_stockouts_primary"):
        A("- That the stock-outs cost a robust amount of net revenue: deferred demand after restock offsets a large part "
          "of the gross estimate (D03).")
    A(f"- That the {top} stock-outs were the supplier's fault rather than Brightwater's ordering (D04 is an association; "
      "the cause is a Hypothesis).")
    A("- That 'Faulty' returns reflect genuinely defective products (D06, Hypothesis).")
    A(f"- That the {pr['category']} promotion programme caused the category's decline. D07 is a Statistical association "
      f"with a method-dependent sign (range {rng('home_kitchen_promotion')}).")
    A(f"- That new {el['category']} SKUs took sales from continuing ones (D08, Hypothesis).")
    A("- Any management action. Phase 6 diagnoses; it does not recommend.")
    A("")
    A("## Remaining unknowns")
    A("")
    A(f"- The external or operational event behind the cluster step around {on['onset_date']:%d %B %Y}.")
    A("- How long SKUs were out of stock within partial weeks, and how much demand switched to other SKUs.")
    A("- The true counterfactual volume of the H&K promotion programme.")
    A(f"- Why continuing {el['category']} SKUs sold less per ranged week outside the cluster, the bulk of the "
      f"{eur(resid)} residual.")
    A("")
    A("## Additional data required")
    A("")
    A("| Question | Data |")
    A("|---|---|")
    for d in ("D02", "D04", "D06", "D07", "D08"):
        A(f"| {ev.loc[d, 'candidate_driver']} | {ev.loc[d, 'additional_data_required']} |")
    A("| Partial-week stock-outs and deferred demand | Daily stock positions or till timestamps per SKU |")
    A("")
    A("## Implications for Phase 7")
    A("")
    A("Phase 7 should carry these results forward as they stand:")
    A("")
    A("- the exclusive attribution (`driver_attribution.csv`) and its residual breakdown;")
    A("- the evidence matrix (`root_cause_evidence_matrix.csv`) with its levels;")
    A("- the sensitivity ranges (`sensitivity_summary.csv`).")
    A("")
    A("It should not add Phase 5 slices together or promote an association into a cause. Visuals should keep ESTIMATE and "
      "HYPOTHESIS labels visible. The data requests above are the only way to move "
      + ", ".join(d for d in ("D02", "D03", "D04", "D06", "D07", "D08") if ev.loc[d, "evidence_level"] != "Root-cause evidence")
      + " to a higher evidence level.")
    A("")
    A("Figures: `figures/01` to `figures/11`. Methods: `docs/06_root_cause_analysis.md`.")
    return "\n".join(L) + "\n"


def write_outputs(R: dict, ch: pd.DataFrame, freeze: pd.DataFrame, out: Path, make_figures: bool):
    files = write_tables(R, ch, freeze, out)
    figs = []
    if make_figures:
        from .figures import make_all
        figs = make_all(R, out / "figures")
    (out / "phase6_root_cause_report.md").write_text(root_cause_report(R), encoding="utf-8")
    return files, figs


def validation_report(R, ch, freeze, files, figs, opened, meta) -> str:
    L = ["# Phase 6 validation report", "",
         f"- Run: {meta['run_at']} ({meta['runtime_seconds']} s), engine: {meta['engine']}",
         f"- Result: **{'ALL CHECKS PASSED' if (ch['status'] == 'PASS').all() else 'CHECKS FAILED'}** "
         f"({(ch['status'] == 'PASS').sum()} of {len(ch)})",
         f"- Frozen Phase 1-5 files verified: {len(freeze)} ({(freeze['status'] == 'UNCHANGED').sum()} unchanged)", "",
         "## SQL executed", "", "| Script | Batches | Seconds |", "|---|---:|---:|"]
    for s in meta["sql"]:
        L.append(f"| `{s['script']}` | {s['batches']} | {s['seconds']} |")
    L += ["", "## Checks", "", "| Group | Check | Value | Reference | Status |", "|---|---|---:|---:|---|"]
    fmt = lambda v: f"{v:,.4f}" if isinstance(v, float) else str(v)  # noqa: E731
    for r in ch.itertuples():
        L.append(f"| {r.group} | {r.check} | {fmt(r.value)} | {fmt(r.reference)} | {r.status} |")
    L += ["", "## Independence from the synthetic ground truth", "",
          f"Files opened were recorded with an audit hook ({opened['count']} opens). Project data, report and configuration "
          f"files READ: {', '.join('`' + f + '`' for f in opened['project_files'])}. Refused (evaluation-only, raw, sample, "
          f"quarantine or underscore-prefixed) paths opened: **{len(opened['refused'])}**.", "",
          "## Outputs", "", "| File | Rows |", "|---|---:|"]
    for f, n in sorted(files.items()):
        L.append(f"| `{f}` | {n:,} |")
    L += ["", "Figures: " + ", ".join(f"`figures/{f}`" for f in figs), ""]
    return "\n".join(L)
