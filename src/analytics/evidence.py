"""BRD 6.2 evidence framework and the Phase 5 investigation shortlist.

Every finding carries exactly one evidence level:
    Observed change          a measured change in a metric; no claim about cause
    Statistical association  two measures move together across segments; not proof of cause
    Root-cause evidence      a mechanism is directly visible in the data and its effect is quantified
                             with a defensible, disclosed method
    Hypothesis               a plausible explanation the available data cannot confirm

Rules that keep the levels honest (enforced in code, tested):
    * an association is never promoted: correlation results are always "Statistical association"
    * "Root-cause evidence" is only assigned when the rule for that mechanism passes (for stock-outs:
      zero sales in weeks with no stock at all, estimator back-test within tolerance, coverage >= 90%);
      otherwise the finding falls back to "Hypothesis"
    * every interpretation that goes beyond the measured data is a separate "Hypothesis" finding that
      names the data needed to test it
financial_impact_eur holds ONLY effects on the H2 net revenue change (negative = lower revenue); findings
about other quantities (discount cost, target variance, availability %) leave it blank and state the
figure in the text. Findings describe overlapping slices of one decline, so their impacts must not be
added together; impact_basis says what each figure measures, and a hypothesis carries the slice it
would explain.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

EVIDENCE_LEVELS = ("Observed change", "Statistical association", "Root-cause evidence", "Hypothesis")
SHORTLIST_COLUMNS = ["finding_id", "area", "headline", "finding", "metric", "financial_impact_eur", "contribution_pp",
                     "evidence_level", "supporting_analysis", "business_interpretation", "recommended_next_analysis",
                     "limitations", "impact_basis", "investigation_priority"]


@dataclass
class Finding:
    area: str
    finding: str
    metric: str
    financial_impact_eur: float
    contribution_pp: float
    evidence_level: str
    supporting_analysis: str
    business_interpretation: str
    recommended_next_analysis: str
    limitations: str
    impact_basis: str
    finding_id: str = ""
    investigation_priority: str = ""
    headline: str = ""

    def __post_init__(self):
        if self.evidence_level not in EVIDENCE_LEVELS:
            raise ValueError(f"evidence level {self.evidence_level!r} is not one of {EVIDENCE_LEVELS}")


def eur(v: float) -> str:
    return f"EUR {v:,.0f}" if v >= 0 else f"-EUR {abs(v):,.0f}"


def pct(v: float, d: int = 1) -> str:
    return f"{v:+.{d}f}%"


def stockout_rule(mech: dict, backtest: dict, cfg: dict) -> tuple[bool, str]:
    c = cfg["lost_sales"]
    checks = {
        "weeks with no stock all week sold at most "
        f"{c['mechanism_max_actual_to_expected']:.0%} of expected": mech["full_week_out_cells"] > 0 and
        mech["full_week_out_actual_to_expected"] <= c["mechanism_max_actual_to_expected"],
        f"estimator back-test bias within +/-{c['backtest_max_abs_bias']:.0%}":
            abs(backtest["bias_ratio"] - 1) <= c["backtest_max_abs_bias"],
        "at least 90% of stock-out weeks have a baseline": mech["coverage"] >= 0.9,
    }
    ok = all(checks.values())
    text = "; ".join(f"{k}: {'met' if v else 'NOT met'}" for k, v in checks.items())
    return ok, text


def priority(impact: float, total_change: float) -> str:
    """Investigation priority for Phase 6: size of the net-revenue slice a finding explains (or would explain).

    Evidence strength and controllability are deliberately NOT folded in here: a large slice with weak
    evidence is exactly what Phase 6 must investigate first. They are scored in Phase 6 (BRD Q10)."""
    if impact is None or np.isnan(impact) or not total_change:
        return "Context"
    share = impact / total_change
    return "High" if share >= 0.20 else ("Medium" if share >= 0.05 else "Low")


def build_shortlist(R: dict, cfg: dict) -> pd.DataFrame:
    per = R["periods"]
    py, cy = R["py"], R["cy"]
    total_py = py["net_revenue"]
    total = cy["net_revenue"] - py["net_revenue"]
    pp = lambda v: 100.0 * v / total_py  # noqa: E731
    F: list[Finding] = []
    e = R["bridge_effects"]
    prof = R["profile"]
    alpha = cfg["evidence"]["association_alpha"]

    # ------------------------------------------------------------------ headline and timing
    F.append(Finding(
        "Headline", f"Net revenue fell {eur(abs(total))} ({pct(100 * total / total_py, 2)}) in {per.label_cy} against "
        f"{per.label_py} ({eur(total_py)} to {eur(cy['net_revenue'])}), week-aligned retail weeks {per.week_from} to "
        f"{per.week_to}.", "Net Revenue", total, pp(total), "Observed change",
        "headline_trend.csv; reconciled to Phase 4 within EUR 0.01 (phase5_validation_report.md)",
        "The decline is real and measured on the governed definition; it is the quantity every other finding explains a part of.",
        "None: this is the target of the Phase 6 root-cause case.",
        "Synthetic data; excludes VAT; returns counted on the return date at the returning store.",
        "Total change in net revenue"))
    F[-1].headline = f"Net revenue {eur(total)} ({pct(100 * total / total_py, 2)}) YoY."
    ctx_onset = prof.get("context_sustained_onset_week")
    F.append(Finding(
        "Timing", f"The decline starts at the beginning of H2: H1 {per.cy_year} was {pct(prof['h1_yoy_pct'])} YoY, the rolling "
        f"4-week YoY turns negative in week {prof['sustained_onset_week_rolling']} and stays negative to week {per.week_to}. "
        f"{prof['weeks_negative']} of {prof['weeks']} weeks are down. Weeks {per.week_from} to {prof['step_split_week'] - 1} "
        f"average {pct(prof['step_mean_before_pct'])}, weeks {prof['step_split_week']} to {per.week_to} average "
        f"{pct(prof['step_mean_after_pct'])}.", "Weekly Net Revenue YoY %", np.nan, np.nan, "Observed change",
        "headline_trend.csv, weekly_yoy_full_year.csv, figures/01_weekly_net_revenue.png",
        f"Pattern: {prof['shape']} ({prof['persistence']}; step test R2 {prof['r2_step']:.2f}, linear trend R2 "
        f"{prof['r2_linear']:.2f}, weeks {prof['first_half_weeks']} {pct(prof['first_half_yoy_pct'])} vs weeks "
        f"{prof['second_half_weeks']} {pct(prof['second_half_yoy_pct'])}). The five weakest weeks "
        f"({', '.join('W' + str(w) for w in prof['top_negative_weeks'])}) carry {prof['top_negative_weeks_share']:.0%} of the decline.",
        "Date the onset per store and category in Phase 6 and match it to operational events.",
        "Weekly YoY is noisy (single weeks move by +/-20%); the step test is descriptive, not a formal change-point test."
        + (f" On the full-year series (whose rolling window includes late-H1 weeks) the rolling YoY stays negative from week "
           f"{ctx_onset}." if ctx_onset else ""),
        "Not a EUR driver (timing only)"))
    F[-1].headline = f"Decline begins with H2 (H1 {pct(prof['h1_yoy_pct'])}); {prof['weeks_negative']} of {prof['weeks']} H2 weeks down."

    # ------------------------------------------------------------------ bridge
    k_asp = R["cat_bridge"].sort_values("asp_effect").iloc[0]["category"]
    F.append(Finding(
        "Revenue bridge", f"Fewer transactions account for {eur(e['transactions_effect'])} of the change "
        f"({e['transactions_effect'] / total:.0%} of it): receipts fell {abs(100 * (cy['transactions'] / py['transactions'] - 1)):.2f}% "
        f"({py['transactions']:,.0f} to {cy['transactions']:,.0f}).", "Transactions effect (Shapley)",
        e["transactions_effect"], pp(e["transactions_effect"]), "Observed change",
        "transaction_basket_decomposition.csv, revenue_bridge.csv, figures/02_revenue_bridge.png",
        ("Most of the decline is fewer customer visits (receipts), not smaller or cheaper baskets." if
         e["transactions_effect"] / total >= 0.5 else "Fewer receipts are one of several components of the decline."),
        "Split the transaction fall by store and week (see the store findings) and test traffic explanations in Phase 6.",
        "Transactions are receipts, a proxy for visits; no footfall data exists to separate traffic from conversion.",
        "Shapley transactions effect within Sales Revenue"))
    F[-1].headline = f"Fewer transactions: {eur(e['transactions_effect'])} ({e['transactions_effect'] / total:.0%} of the fall)."
    F.append(Finding(
        "Revenue bridge", f"Basket effects: UPT {eur(e['upt_effect'])} (UPT {e['upt_py']:.3f} to {e['upt_cy']:.3f}) and ASP "
        f"{eur(e['asp_effect'])} (ASP EUR {e['asp_py']:.2f} to EUR {e['asp_cy']:.2f}); AOV changed "
        f"{pct(100 * (cy['aov'] / py['aov'] - 1), 2)}.", "UPT and ASP effects (Shapley)", e["upt_effect"] + e["asp_effect"],
        pp(e["upt_effect"] + e["asp_effect"]), "Observed change", "transaction_basket_decomposition.csv, figures/05_basket_kpis.png",
        f"At estate level spend per visit moved {pct(100 * (cy['aov'] / py['aov'] - 1), 1)}; the estate ASP hides larger category "
        f"movements (largest category ASP effect: {k_asp} {eur(float(R['cat_bridge'].set_index('category').loc[k_asp, 'asp_effect']))}).",
        "Decompose ASP into like-for-like price, discount and mix effects by category in Phase 6.",
        "Estate ASP mixes price, discount depth and category mix; segment bridges do not add up to the estate bridge.",
        "Shapley UPT + ASP effects within Sales Revenue"))
    F[-1].headline = f"Basket size and price: {eur(e['upt_effect'] + e['asp_effect'])} combined ({(e['upt_effect'] + e['asp_effect']) / total:.0%} of the fall)."
    F.append(Finding(
        "Revenue bridge", f"Higher returns reduce net revenue by a further {eur(abs(e['returns_effect']))}: returns value "
        f"{eur(py['returns_value'])} to {eur(cy['returns_value'])}; return rate by value {100 * py['return_rate_value']:.2f}% to "
        f"{100 * cy['return_rate_value']:.2f}%.", "Returns effect", e["returns_effect"], pp(e["returns_effect"]),
        "Observed change", "returns_diagnostics.csv (level Estate)",
        (f"Returns are {e['returns_effect'] / total:.0%} of the estate decline; " +
         ("they rose while sales fell, so the return rate rose faster than the returns value." if
          cy["returns_value"] > py["returns_value"] and cy["sales_revenue"] < py["sales_revenue"] else
          "they moved in line with sales.")),
        "See the returns concentration finding.", "Returns are dated at the return, not the original sale.",
        "Minus the change in Returns Value"))
    F[-1].headline = f"Higher returns: {eur(e['returns_effect'])}."

    # ------------------------------------------------------------------ stores and regions
    st = R["store"]
    cl = R["store_cluster"]
    cs = st[st["store_id"].isin(cl)]
    cl_change = float(cs["net_revenue_change"].sum())
    common = []
    for col in ("region", "store_format"):
        vals = cs[col].unique()
        if len(vals) == 1:
            common.append(f"{col.replace('store_', '')} {vals[0]}")
    cw = R["cluster_weekly"]
    cl_onset = sustained_onset_from(cw, "cluster_net_revenue_yoy_pct")
    rest_yoy = 100 * ((st.loc[~st["store_id"].isin(cl), "net_revenue_cy"].sum() /
                       st.loc[~st["store_id"].isin(cl), "net_revenue_py"].sum()) - 1)
    cl_bridge = R["seg_bridge"][(R["seg_bridge"]["segment_type"] == "Store") & (R["seg_bridge"]["segment_name"].isin(cl))]
    F.append(Finding(
        "Stores", f"{len(cl)} stores ({', '.join(f'{r.store_id} {r.store_name}' for r in cs.itertuples())}; "
        f"{' and '.join(common) if common else 'no shared region or format'}) account for {cl_change / total:.0%} of the "
        f"decline ({eur(cl_change)}; {pct(100 * (cs['net_revenue_cy'].sum() / cs['net_revenue_py'].sum() - 1))} YoY). "
        f"The other {len(st) - len(cl)} stores together are {pct(rest_yoy)}.", "Store contribution (pp)", cl_change,
        pp(cl_change), "Observed change", "store_contribution.csv, store_cluster_weekly.csv, figures/03_store_contribution.png",
        f"{'The decline is concentrated, not estate-wide.' if len(cl) <= 0.25 * len(st) else 'The decline is spread across many stores.'} "
        f"Transactions YoY in these stores: {', '.join(f'{r.transactions_yoy_pct:+.0f}%' for r in cs.itertuples())}; their transactions effect is "
        f"{eur(float(cl_bridge['transactions_effect'].sum()))} of their {eur(cl_change)}.",
        "Phase 6: store-week and daypart timing of the transaction fall in these stores; compare with the other stores in the same region.",
        f"Store results rely on complete store-day coverage ({len(R['coverage_gaps'])} store-week gap(s) found, see Data coverage).",
        "Sum of the stores' net revenue change"))
    F[-1].headline = f"{len(cl)} stores ({', '.join(cl)}) carry {cl_change / total:.0%} of the fall ({eur(cl_change)})."
    F.append(Finding(
        "Stores", f"In the {len(cl)} stores the fall is abrupt and persistent: their weekly YoY is negative in every week from "
        f"week {cl_onset if cl_onset else 'n/a'} and averages "
        f"{cw.loc[cw['retail_week'] > (cl_onset or 0), 'cluster_net_revenue_yoy_pct'].mean():.0f}% after it, while the other "
        f"stores average {cw['rest_net_revenue_yoy_pct'].mean():.1f}% per week (range "
        f"{cw['rest_net_revenue_yoy_pct'].min():.0f}% to {cw['rest_net_revenue_yoy_pct'].max():+.0f}%).",
        "Weekly Net Revenue YoY % (cluster vs rest)", np.nan, np.nan, "Observed change",
        "store_cluster_weekly.csv, figures/01_weekly_net_revenue.png",
        (f"Transactions explain {float(cl_bridge['transactions_effect'].sum()) / cl_change:.0%} of these stores' fall and it starts "
         "within weeks of the start of H2 in all of them: the signature of a local event rather than an estate-wide trading problem."
         if float(cl_bridge['transactions_effect'].sum()) / cl_change >= 0.7 else
         "The fall in these stores is not mainly a transaction fall; basket or returns components matter."),
        "Identify what changed at these stores around that week (Phase 6).",
        "Timing is inferred from weekly data; exact dates need store operational logs.", "Not a EUR driver (timing only)"))
    F[-1].headline = f"Their fall is abrupt (from week {cl_onset}) and persistent, about {cw.loc[cw['retail_week'] > (cl_onset or 0), 'cluster_net_revenue_yoy_pct'].mean():.0f}% a week."
    F.append(Finding(
        "Stores", f"Hypothesis: a local, traffic-related change may have hit the {' / '.join(common) or 'affected'} stores (for example a "
        "new competitor, access or roadworks disruption, or a local footfall shift), reducing visits from early H2.",
        "Transactions", cl_change, pp(cl_change), "Hypothesis",
        "store_contribution.csv (transactions YoY), store_cluster_weekly.csv",
        "Consistent with the pattern (visits down, basket stable, timing shared), but nothing in the model records competitors, "
        "footfall or local events.",
        "Obtain footfall counts, competitor openings, local events and store operating logs for these stores; compare "
        "same-region stores that did not decline.",
        "Additional data required: the available data cannot confirm or reject this.", "Cluster change (same slice as above)"))
    F[-1].headline = f"Hypothesis: a local traffic event around {', '.join(cl)} may have reduced visits."
    rg = R["region"].iloc[0]
    br = R["breadth"].set_index(["segment_type", "segment_name"])
    b = br.loc[("Region", rg["region"])]
    rf = R["region_format"]
    rfr = rf[rf["region"] == rg["region"]].sort_values("net_revenue_change")
    F.append(Finding(
        "Region / format", f"{rg['region']} contributes {eur(rg['net_revenue_change'])} ({rg['share_of_change']:.0%} of the decline, "
        f"{pct(rg['net_revenue_yoy_pct'])}); {int(b['stores_declining'])} of {int(b['stores'])} of its stores declined, but the split "
        f"by format is uneven: " + "; ".join(f"{r.store_format} {pct(r.net_revenue_yoy_pct)} ({eur(r.net_revenue_change)})"
                                           for r in rfr.itertuples()) + ".",
        "Region contribution (pp)", float(rg["net_revenue_change"]), float(rg["contribution_pp"]), "Observed change",
        "region_contribution.csv, format_contribution.csv, region_format_matrix.csv",
        "The regional figure is driven by specific stores; a region-wide explanation would have to explain why other formats in the region held up.",
        "Treat the store cluster, not the region, as the unit of investigation.",
        "Region and format are confounded in a 20-store estate (few stores per cell).", "Region's net revenue change"))
    F[-1].headline = f"{rg['region']}: {rg['share_of_change']:.0%} of the fall, mostly its {rfr.iloc[0]['store_format']}-format stores."

    # ------------------------------------------------------------------ categories
    cat = R["category"][R["category"]["category"] != "Unknown"]
    cb = R["cat_bridge"].set_index("category")
    crm = R["category_region"]
    lost_cat = R["availability"][R["availability"]["level"] == "Category"].set_index("key")
    for r in cat[cat["share_of_change"] >= cfg["products"]["material_category_share"]].itertuples():
        x = cb.loc[r.category]
        parts = sorted([("transactions (receipts containing the category)", x["transactions_effect"]),
                        ("units per receipt", x["upt_effect"]), ("ASP", x["asp_effect"]),
                        ("returns", x["returns_effect"])], key=lambda t: t[1])
        F.append(Finding(
            "Categories", f"{r.category} contributes {eur(r.net_revenue_change)} ({r.share_of_change:.0%} of the decline, "
            f"{pct(r.net_revenue_yoy_pct)}). Largest components: {parts[0][0]} {eur(parts[0][1])}, {parts[1][0]} "
            f"{eur(parts[1][1])}. Availability {100 * r.availability_py:.1f}% to {100 * r.availability_cy:.1f}%, promo share "
            f"{100 * r.promo_revenue_share_py:.1f}% to {100 * r.promo_revenue_share_cy:.1f}%, return rate "
            f"{100 * r.return_rate_value_py:.1f}% to {100 * r.return_rate_value_cy:.1f}%, gross margin "
            f"{100 * r.gross_margin_pct_py:.1f}% to {100 * r.gross_margin_pct_cy:.1f}%. "
            + _region_split(crm, r.category, r.net_revenue_change)
            + _lost_note(lost_cat, r.category),
            "Category contribution (pp)", float(r.net_revenue_change), float(r.contribution_pp), "Observed change",
            "category_contribution.csv, transaction_basket_decomposition.csv (level Category), category_region_matrix.csv, "
            "product_diagnostics.csv", _category_reading(r, x),
            "Phase 6: separate the part of this category's fall that belongs to the store cluster from the part spread across the estate.",
            "Category transactions are receipts containing the category (not additive across categories).",
            "Category's net revenue change"))
        F[-1].headline = f"{r.category}: {eur(r.net_revenue_change)} ({r.share_of_change:.0%} of the fall), mainly {parts[0][0].split(' (')[0]}."

    # ------------------------------------------------------------------ availability
    av = R["availability"]
    est = av[av["level"] == "Estate"].iloc[0]
    worst_cat = av[(av["level"] == "Category")].sort_values("availability_change_pp").iloc[0]
    sup = av[(av["level"] == "Supplier x Category")].sort_values("availability_change_pp")
    sup_w = sup[sup["sub_key"] == worst_cat["key"]]
    n_cat_drop = int((av[(av["level"] == "Category")]["availability_change_pp"] <= -2).sum())
    F.append(Finding(
        "Availability", f"Estate availability moved from {100 * est['availability_py']:.1f}% to {100 * est['availability_cy']:.1f}% "
        f"({est['availability_change_pp']:+.2f} pp), but {worst_cat['key']} fell {abs(worst_cat['availability_change_pp']):.1f} pp "
        f"({100 * worst_cat['availability_py']:.1f}% to {100 * worst_cat['availability_cy']:.1f}%); by supply source the largest "
        f"drops in that category are " + "; ".join(f"{r.key} {r.availability_change_pp:+.1f} pp" for r in sup_w.head(2).itertuples()) + ".",
        "Stock Availability %", np.nan, np.nan, "Observed change",
        "availability_diagnostics.csv (levels Estate, Category, Supplier x Category, Week)",
        (f"The availability problem is narrow: {n_cat_drop} categor{'y' if n_cat_drop == 1 else 'ies'} fell by 2 pp or more, "
         "and within it particular supply sources." if n_cat_drop <= 2 else
         f"The availability fall is broad: {n_cat_drop} categories fell by 2 pp or more."),
        "Phase 6: replenishment history (received quantities, order and delivery data) for the affected supplier's SKUs.",
        "Availability counts store-SKU-weeks with zero closing stock; it does not see part-week stock-outs that recovered.",
        "Not a EUR figure (see the estimated lost sales finding)"))
    F[-1].headline = (f"Availability fell {abs(worst_cat['availability_change_pp']):.1f} pp in {worst_cat['key']} "
                      f"(estate {est['availability_change_pp']:+.2f} pp).")
    mech, bt = R["mechanism"], R["backtest"]
    ok, rule_text = stockout_rule(mech, bt, cfg)
    lt = R["lost_totals"]
    lost_change = lt["lost_cy"] - lt["lost_py"]
    upper_change = lt["upper_cy"] - lt["upper_py"]
    cat_lost = av[av["level"] == "Category"].sort_values("est_lost_sales_change_ESTIMATE", ascending=False).iloc[0]
    sup_lost = sup_w.sort_values("est_lost_sales_change_ESTIMATE", ascending=False).iloc[0]
    F.append(Finding(
        "Availability", f"ESTIMATE: in store-SKU-weeks with no stock at any point (opening stock 0, nothing received) sales were "
        f"{mech['full_week_out_actual_units']:.0f} units against {mech['full_week_out_expected_units']:.0f} expected; the "
        f"estimated sales lost in such weeks rose from {eur(lt['lost_py'])} to {eur(lt['lost_cy'])} ({eur(lost_change)}, "
        f"{lost_change / abs(total):.0%} of the decline). {cat_lost['key']} accounts for "
        f"{eur(cat_lost['est_lost_sales_change_ESTIMATE'])}, {sup_lost['key']} SKUs for {eur(sup_lost['est_lost_sales_change_ESTIMATE'])}.",
        "Estimated Lost Sales (BR-05, ESTIMATE, full-week stock-outs)", -lost_change, pp(-lost_change),
        "Root-cause evidence" if ok else "Hypothesis",
        f"availability_diagnostics.csv, lost_sales_method_check.csv; back-test of the expected level on in-stock, non-promoted "
        f"weeks: actual/expected {bt['bias_ratio']:.3f} (WAPE {bt['wape_store_category_week']:.1%} at store x category x week). "
        f"Rule: {rule_text}.",
        "Stock-outs are a visible, quantified mechanism behind part of the decline: where there was no stock there were no "
        "sales, and the expected sales are estimated with a back-tested baseline.",
        "Phase 6: confirm with replenishment data why these SKUs went out of stock.",
        "An estimate (conservative): assumes demand equals the store-SKU's nearby in-stock, non-promoted rate adjusted by the "
        "category's weekly seasonality; ignores substitution to other SKUs; excludes partial-week stock-outs (next finding).",
        "Increase in estimated lost sales, full-week stock-outs (negative = revenue lost)"))
    F[-1].headline = f"Full-week stock-outs cost an estimated {eur(lost_change)} more (ESTIMATE), mostly {cat_lost['key']}."
    F.append(Finding(
        "Availability", f"Hypothesis: partial-week stock-outs (restocked or sold out during the week) may have cost up to "
        f"{eur(upper_change - lost_change)} more. Literal BR-05 upper bound over all stock-out weeks: {eur(lt['upper_py'])} to "
        f"{eur(lt['upper_cy'])}.", "Estimated Lost Sales (BR-05 upper bound, ESTIMATE)", -(upper_change - lost_change),
        pp(-(upper_change - lost_change)), "Hypothesis", "lost_sales_method_check.csv",
        f"Not evidence: in aggregate these weeks sold more than expected, and the per-week clipped estimate reports "
        f"EUR {bt['clipped_false_lost_eur_per_cell']:.1f} per in-stock week where nothing was lost (noise floor) against "
        f"EUR {mech['partial_upper_per_cell_eur']:.1f} per partial stock-out week.",
        "Phase 6: daily or intraday stock positions (or till timestamps) to date when each SKU ran out.",
        "Additional data required: the weekly snapshot cannot show how long a SKU was out within the week.",
        "Upper bound minus the full-week estimate (not additional evidence)"))
    F[-1].headline = f"Hypothesis: partial-week stock-outs may have cost up to {eur(upper_change - lost_change)} more."
    a_store = R["assoc"][R["assoc"]["level"] == "Store"].iloc[0]
    a_cell = R["assoc"][(R["assoc"]["level"] == "Store x Category") & R["assoc"]["x"].str.startswith("change in est")].iloc[0]
    F.append(Finding(
        "Availability", f"Across stores, availability change and revenue change are {'not ' if not a_store['significant_at_alpha'] else ''}"
        f"significantly related (Pearson r = {a_store['pearson_r']:.2f}, p = {a_store['pearson_p']:.2f}, n = {int(a_store['n'])}). "
        f"Across store x category cells, larger increases in estimated lost sales go with larger revenue falls "
        f"(r = {a_cell['pearson_r']:.2f}, p = {a_cell['pearson_p']:.4f}, n = {int(a_cell['n'])}; Spearman rho = {a_cell['spearman_rho']:.2f}).",
        "Correlation (availability vs revenue change)", np.nan, np.nan, "Statistical association",
        "availability_association.csv, figures/06_availability_vs_revenue.png",
        (f"Availability does not explain which stores declined most (store cluster availability change "
         f"{float((cs['availability_cy'] - cs['availability_py']).mean()) * 100:+.2f} pp on average, estate "
         f"{est['availability_change_pp']:+.2f} pp). " if not a_store['significant_at_alpha'] else
         "Stores with larger availability drops also fell more. ") +
        ("The cell-level link rests on a few large cells (Pearson significant, Spearman not)." if
         a_cell["significant_at_alpha"] and a_cell["spearman_p"] >= alpha else
         "The cell-level link is " + ("consistent across cells." if a_cell["significant_at_alpha"] else "not significant.")),
        "No further correlation work; use the SKU-level lost-sales estimate instead.",
        "Correlation, not causation; small n for stores; cell-level result driven by outliers.", "Not a EUR figure"))
    F[-1].headline = (f"Store availability change {'does not track' if not a_store['significant_at_alpha'] else 'tracks'} "
                      f"store revenue change (r = {a_store['pearson_r']:.2f}, p = {a_store['pearson_p']:.2f}).")
    F.append(Finding(
        "Availability", f"Hypothesis: a replenishment or supply problem with {sup_lost['key']} ({sup_lost['sub_key']}) may have caused "
        f"the stock-outs (availability {100 * sup_lost['availability_py']:.1f}% to {100 * sup_lost['availability_cy']:.1f}%, "
        f"{eur(sup_lost['est_lost_sales_change_ESTIMATE'])} of the full-week lost-sales estimate increase).",
        "Stock Availability % by supplier", -float(sup_lost["est_lost_sales_change_ESTIMATE"]),
        pp(-float(sup_lost["est_lost_sales_change_ESTIMATE"])), "Hypothesis", "availability_diagnostics.csv (Supplier x Category)",
        f"The availability drop follows the supplier: {sup_lost['key']} {sup_lost['sub_key']} availability "
        f"{100 * sup_lost['availability_py']:.1f}% to {100 * sup_lost['availability_cy']:.1f}% across the estate; store execution "
        "alone would not follow one supplier.",
        "Phase 6: received_qty and closing-stock sequences for the supplier's SKUs; request purchase orders, delivery "
        "confirmations and supplier fill-rate data.",
        "Additional data required: the model has stock and receipts but no orders or supplier communications. Some affected "
        "SKUs have no supplier on the product master ('Unknown supplier'), which limits the supplier view.",
        "The supplier's slice of the full-week lost-sales estimate (same slice as the lost-sales finding)"))
    F[-1].headline = f"Hypothesis: a supply problem with {sup_lost['key']} may have caused the {sup_lost['sub_key']} stock-outs."

    # ------------------------------------------------------------------ returns
    rs = R["returns_summary"]
    rr = R["returns"]
    reason = rr[rr["level"] == "Category x Reason"].sort_values("returns_change", ascending=False).iloc[0]
    F.append(Finding(
        "Returns", f"Returns rose where one recorded reason rose: '{reason['sub_key']}' returns in {reason['key']} went from "
        f"{eur(reason['returns_value_py'])} to {eur(reason['returns_value_cy'])} ({eur(reason['returns_change'])}), while the estate "
        f"total rose {eur(rs['returns_change'])}. {rs['concentration_cells']} store x category cells hold "
        f"{rs['concentration_share_of_gross_increase']:.0%} of the gross increase: {rs['concentration_cells_list']}.",
        "Returns Value, Return Rate %", -float(reason["returns_change"]), pp(-float(reason["returns_change"])), "Observed change",
        "returns_diagnostics.csv (levels Category x Reason, Store x Category, Product), figures/07_returns_trend.png",
        ("The returns increase is concentrated in a few store and category cells, not a general change in customer behaviour."
         if rs["concentration_share_of_gross_increase"] >= 0.5 else "The returns increase is spread across many stores and categories."),
        f"Phase 6: '{reason['sub_key']}' returns by product, supplier and original sale date (batch timing).",
        "return_reason is the reason recorded at the till, not a verified fault.", "Increase in returns in that category and reason"))
    F[-1].headline = (f"'{reason['sub_key']}' returns in {reason['key']} up {eur(reason['returns_change'])}; "
                      f"{rs['concentration_cells']} store x category cells hold {rs['concentration_share_of_gross_increase']:.0%} of the increase.")
    F.append(Finding(
        "Returns", f"Hypothesis: a product quality problem in specific {reason['key']} products may have increased '{reason['sub_key']}' returns.",
        "Returns by recorded reason", -float(reason["returns_change"]), pp(-float(reason["returns_change"])), "Hypothesis",
        "returns_diagnostics.csv (Product rows), product_diagnostics.csv (returns_affected)",
        "Plausible given the reason code, but the data cannot distinguish a genuine defect from a change in how staff record reasons.",
        "Request supplier batch or lot data, QA inspections and customer complaint logs.",
        "Additional data required.", "Same slice as the returns finding above"))
    F[-1].headline = f"Hypothesis: a quality problem in some {reason['key']} products may have raised '{reason['sub_key']}' returns."

    # ------------------------------------------------------------------ promotions
    ps = R["promo_summary"]
    pe = ps[ps["level"] == "Estate"].set_index("retail_year")
    a0, a1 = pe.loc[per.py_year], pe.loc[per.cy_year]
    F.append(Finding(
        "Promotions", f"Promotion intensity rose: promo revenue share {100 * a0['promo_revenue_share']:.1f}% to "
        f"{100 * a1['promo_revenue_share']:.1f}%, discount cost {eur(a0['promo_discount_cost'])} to {eur(a1['promo_discount_cost'])}, "
        f"average discount depth {100 * a0['promo_avg_discount_depth']:.1f}% to {100 * a1['promo_avg_discount_depth']:.1f}%, "
        f"promoted-line margin {100 * a0['promo_line_margin_pct']:.1f}% to {100 * a1['promo_line_margin_pct']:.1f}%.",
        "Promo Revenue Share %, Promo Discount Cost", np.nan, np.nan, "Observed change",
        "promotion_diagnostics.csv (level Estate, Category), headline_trend.csv",
        f"More revenue now comes through discounted sales; discount cost is {a1['promo_discount_cost'] / a0['promo_discount_cost']:.1f}x the prior year.",
        "See the category promotion finding.",
        "Discount cost reduces Sales Revenue directly, but without promotions some of the volume would not exist; it is not a net loss.",
        "Not a net revenue effect (discount cost; its revenue effect sits in the ASP effects)"))
    F[-1].headline = f"Discount cost up {eur(a1['promo_discount_cost'] - a0['promo_discount_cost'])}; promo share {100 * a0['promo_revenue_share']:.1f}% to {100 * a1['promo_revenue_share']:.1f}%."
    pu = R["promo_uplift"]
    pcat = pu[pu["level"] == "Category"].copy()
    wide = pcat.pivot(index="key", columns="retail_year", values=["events", "uplift_pct", "incremental_promo_margin",
                                                                  "promo_discount_cost", "post_promo_vs_baseline_pct",
                                                                  "avg_discount_pct"])
    wide["disc_change"] = wide[("promo_discount_cost", per.cy_year)] - wide[("promo_discount_cost", per.py_year)]
    k = wide["disc_change"].idxmax()
    w = wide.loc[k]
    cr = R["category"].set_index("category").loc[k]
    ue = pu[(pu["level"] == "Estate")].set_index("retail_year")
    F.append(Finding(
        "Promotions", f"{k}: promotion events {int(w[('events', per.py_year)]):,} to {int(w[('events', per.cy_year)]):,}, average "
        f"discount {100 * w[('avg_discount_pct', per.py_year)]:.0f}% to {100 * w[('avg_discount_pct', per.cy_year)]:.0f}%, uplift "
        f"{w[('uplift_pct', per.py_year)]:.0f}% to {w[('uplift_pct', per.cy_year)]:.0f}% but incremental promo margin "
        f"{eur(w[('incremental_promo_margin', per.py_year)])} to {eur(w[('incremental_promo_margin', per.cy_year)])}; post-promotion "
        f"weeks {w[('post_promo_vs_baseline_pct', per.cy_year)]:+.0f}% vs baseline. Category ASP "
        f"{pct(100 * (cr['asp_cy'] / cr['asp_py'] - 1))}, gross margin {100 * cr['gross_margin_pct_py']:.1f}% to "
        f"{100 * cr['gross_margin_pct_cy']:.1f}%.",
        "Promo Uplift %, Incremental Promo Margin", float(cb.loc[k, "asp_effect"]), pp(float(cb.loc[k, "asp_effect"])),
        "Observed change", "promotion_diagnostics.csv (Category, Discount depth), promotion_events.csv",
        (f"Deeper, more frequent promotions in {k} lifted promoted volume but "
         + ("did not pay for their discount" if w[('incremental_promo_margin', per.cy_year)] < 0 else "still paid for their discount")
         + ("; the category's revenue fell mainly through a lower selling price." if cb.loc[k, "asp_effect"] <= min(
             cb.loc[k, "transactions_effect"], cb.loc[k, "upt_effect"], cb.loc[k, "returns_effect"]) else ".")),
        "Phase 6: category-week counterfactual (sales with and without promotion), cannibalisation of non-promoted SKUs.",
        "Uplift uses a pre-promotion baseline of the same store-SKU (seasonally adjusted); overlapping promotions are excluded.",
        "Category ASP effect (Shapley)"))
    F[-1].headline = f"{k} promotions: {w[('events', per.cy_year)] / w[('events', per.py_year)]:.1f}x the events, deeper discounts, incremental margin {eur(w[('incremental_promo_margin', per.cy_year)])}; ASP effect {eur(float(cb.loc[k, 'asp_effect']))}."
    F.append(Finding(
        "Promotions", f"Pull-forward: estate post-promotion weeks are {ue.loc[per.py_year, 'post_promo_vs_baseline_pct']:+.1f}% "
        f"({per.label_py}) and {ue.loc[per.cy_year, 'post_promo_vs_baseline_pct']:+.1f}% ({per.label_cy}) against baseline.",
        "Post-promotion units vs baseline", np.nan, np.nan, "Observed change", "promotion_diagnostics.csv (post_promo_vs_baseline_pct)",
        ("Some demand is pulled forward in both years; " +
         ("the estate-level dip barely changed, so pull-forward alone does not explain the decline." if
          abs(ue.loc[per.cy_year, 'post_promo_vs_baseline_pct'] - ue.loc[per.py_year, 'post_promo_vs_baseline_pct']) < 2 else
          "the dip changed materially between the years.")),
        "Include post-promotion dips in the Phase 6 promotion counterfactual.",
        "Two post weeks only; measured against an estimated baseline.", "Not a EUR figure"))
    F[-1].headline = (f"Post-promotion dip {ue.loc[per.py_year, 'post_promo_vs_baseline_pct']:+.0f}% and "
                      f"{ue.loc[per.cy_year, 'post_promo_vs_baseline_pct']:+.0f}% vs baseline (prior, current year).")
    F.append(Finding(
        "Promotions", f"Hypothesis: the {k} promotion programme may have reduced revenue (price investment without enough incremental "
        "volume, and cannibalisation of full-price sales).", "Category ASP and margin", float(cb.loc[k, "asp_effect"]),
        pp(float(cb.loc[k, "asp_effect"])), "Hypothesis", "promotion_diagnostics.csv, category_contribution.csv",
        "Consistent with the measured changes, but a counterfactual (what would have sold without the promotions) is needed.",
        "Phase 6: counterfactual by category-week; promotion calendar and planning rationale from Marketing.",
        "Additional analysis required; association between promotion intensity and revenue is not causation.",
        "Same slice as the category promotion finding"))
    F[-1].headline = f"Hypothesis: the {k} promotion programme may have reduced revenue."

    # ------------------------------------------------------------------ targets
    t = R["targets"]
    t1, t0 = t[t["retail_year"] == per.cy_year], t[t["retail_year"] == per.py_year]
    n1, n0 = int(t1["persistent_underperformer"].sum()), int(t0["persistent_underperformer"].sum())
    ach1 = 100 * t1["net_revenue"].sum() / t1["target_net_revenue"].sum()
    ach0 = 100 * t0["net_revenue"].sum() / t0["target_net_revenue"].sum()
    worst = t1.sort_values("target_achievement_pct").head(3)
    F.append(Finding(
        "Targets", f"{n1} of {len(t1)} stores meet the BRD persistent-underperformance rule (missed 8+ of the last 13 weeks) in "
        f"{per.label_cy}, against {n0} in {per.label_py}; estate target achievement {ach0:.1f}% to {ach1:.1f}%. Lowest in "
        f"{per.label_cy}: " + ", ".join(f"{r.store_id} {r.target_achievement_pct:.0f}%" for r in worst.itertuples()) + ".",
        "Target Achievement %", np.nan, np.nan, "Observed change",
        "target_performance.csv, target_weekly.csv, figures/08_target_heatmap.png",
        "Target misses are an outcome, not a cause. " + (
            "Because most stores missed in both years, the rule does not separate the declining stores from the rest; "
            "achievement % ranks them better." if min(n0, n1) >= 0.5 * len(t1) else
            "The rule separates a minority of stores, which can be compared with the contribution ranking."),
        "Review how targets are set with Finance before using misses as a performance signal.",
        f"Targets are Finance plans; store-weeks without a target: {int(26 * len(t0) - t0['target_weeks'].sum())} "
        f"({per.label_py}), {int(26 * len(t1) - t1['target_weeks'].sum())} ({per.label_cy}). Variance to target "
        f"{per.label_cy}: {eur(float(t1['variance_to_target'].sum()))}.", "Not a net revenue effect (outcome vs plan)"))
    F[-1].headline = f"{n1} of {len(t1)} stores persistently miss target ({n0} in the prior year); an outcome, not a cause."

    # ------------------------------------------------------------------ range and data coverage
    rc = R["range_change"]
    gone = rc[rc["status"] == "sold in prior period only"]
    new = rc[rc["status"] == "sold in current period only"]
    both = rc[rc["status"] == "sold in both periods"].set_index("category")
    net_range = float(new["net_revenue_cy"].sum() - gone["net_revenue_py"].sum())
    top = (new.set_index("category")["net_revenue_cy"].sub(gone.set_index("category")["net_revenue_py"], fill_value=0)
           .sort_values(ascending=False))
    kc = top.index[0]
    F.append(Finding(
        "Range", f"Range churn: SKUs sold only in {per.label_py} had {eur(gone['net_revenue_py'].sum())} "
        f"({int(gone['products'].sum())} SKUs); SKUs sold only in {per.label_cy} took {eur(new['net_revenue_cy'].sum())} "
        f"({int(new['products'].sum())} SKUs); net {eur(net_range)}. Largest net churn: {kc} {eur(float(top.iloc[0]))}, where "
        f"SKUs sold in both periods changed {eur(float(both.loc[kc, 'net_revenue_change']))}.",
        "Net revenue of delisted and new SKUs", net_range, pp(net_range), "Observed change", "range_change.csv",
        "Measured only: new SKUs brought revenue while continuing SKUs fell in the same category; whether the new SKUs added "
        "sales or replaced (cannibalised) existing ones is not tested.",
        "Phase 6: test cannibalisation between new and continuing SKUs by category and store.",
        "Delisting is inferred from sales and ranging, not from a range-plan record.", "Net revenue of SKUs sold in one period only"))
    F[-1].headline = f"Range churn: {eur(-gone['net_revenue_py'].sum())} delisted, {eur(new['net_revenue_cy'].sum())} new SKUs (net {eur(net_range)})."
    gaps = R["coverage_gaps"]
    for g in gaps.itertuples():
        srow = st.set_index("store_id").loc[g.store_id]
        daily = srow["net_revenue_py"] / srow["trading_days_py"] if g.retail_year == per.py_year else np.nan
        missing = int(g.normal_trading_days - g.trading_days)
        F.append(Finding(
            "Data coverage", f"{g.store_id} has {missing} fewer trading days than other stores in retail week {int(g.retail_week)} of "
            f"{int(g.retail_year)} (no sales recorded); at its average daily net revenue this is about {eur(missing * daily)} of "
            "prior-year revenue missing, which flatters its YoY.", "Trading days", np.nan, np.nan, "Observed change",
            "diag.v_store_week_coverage",
            "Too small to change any conclusion; disclosed so the store's YoY is read correctly.",
            "None needed for Phase 6; flag in store-level reporting.",
            "The cause of the gap (closure or missing data) is not recorded in the model.",
            "Not a net revenue effect (data coverage)"))
        F[-1].headline = f"{g.store_id}: {missing} missing prior-year trading days (about {eur(missing * daily)}), flatters its YoY."

    df = pd.DataFrame([asdict(f) for f in F])
    df["finding_id"] = [f"F{i:02d}" for i in range(1, len(df) + 1)]
    df["investigation_priority"] = [("Context" if ar in ("Headline", "Data coverage") else priority(v, total))
                                    for v, ar in zip(df["financial_impact_eur"], df["area"])]
    return df[SHORTLIST_COLUMNS]


def sustained_onset_from(cw: pd.DataFrame, col: str):
    v = cw[col].fillna(0).to_numpy()
    if not len(v) or v[-1] >= 0:
        return None
    i = len(v) - 1
    while i > 0 and v[i - 1] < 0:
        i -= 1
    return int(cw["retail_week"].iloc[i])


def _category_reading(r, x) -> str:
    comps = {"transactions": x["transactions_effect"], "upt": x["upt_effect"], "asp": x["asp_effect"],
             "returns": x["returns_effect"]}
    lead = min(comps, key=comps.get)
    text = {"transactions": "Fewer receipts contain the category; with estate traffic down this is partly the store cluster "
                            "and partly category-specific (availability or range).",
            "asp": "The category sells at a lower price per unit; discounting and mix are the candidate mechanisms.",
            "upt": "Customers buy fewer units of the category per receipt.",
            "returns": "Returns are the largest component."}[lead]
    return text


def _region_split(crm: pd.DataFrame, category: str, change: float) -> str:
    g = crm[crm["category"] == category].sort_values("net_revenue_change")
    top = g.iloc[0]
    return f"{top['net_revenue_change'] / change:.0%} of the category's decline is in {top['region']}."


def _lost_note(lost_cat: pd.DataFrame, category: str) -> str:
    if category not in lost_cat.index:
        return ""
    v = float(lost_cat.loc[category, "est_lost_sales_change_ESTIMATE"])
    return f" Estimated lost sales from stock-outs rose {eur(v)} (ESTIMATE)." if abs(v) >= 10000 else ""
