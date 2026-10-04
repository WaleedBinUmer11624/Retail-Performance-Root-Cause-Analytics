"""Analytical counterfactual scenarios. These answer 'how much revenue would this driver account for under
stated assumptions'. They are NOT forecasts and NOT targets."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build(R: dict) -> pd.DataFrame:
    c, sc, el, rt, pr, ov = R["central"], R["store_cluster"], R["electronics"], R["returns"], R["promotions"], R["overlap"]
    sens = R["sensitivity_summary"].set_index("driver")
    py, cy = R["py"], R["cy"]
    prim = sc["primary_control"]
    ex = sc["eur"][prim]
    rows = []

    def rng(driver):
        r = sens.loc[driver]
        return float(r["min"]), float(r["max"]), bool(r["robust"])

    lo, hi, rob = rng("store_cluster_excess")
    rows.append({"scenario": "A", "name": "Store-cluster transactions at the control-store baseline",
                 "question": "If S03-S05 had followed the matched control stores' YoY path from their own pre-period level",
                 "revenue_impact_eur": -c["cluster_excess"], "range_low_eur": -hi, "range_high_eur": -lo,
                 "margin_impact_eur": -ex["gross_margin"]["excess"],
                 "assumptions": "Control stores show what the cluster would have done; the cluster's H1 gap to the controls "
                                "would have persisted; DiD pre-trend flat (checked).",
                 "confidence": "High for the size (robust across control groups and windows; placebo p "
                               f"{sc['placebo']['p_value_one_sided']:.4f}, the smallest attainable); cause unresolved",
                 "evidence_level": "Observed change", "robust_in_sensitivity": rob})
    a2 = R["scenario_a2"]
    rows.append({"scenario": "A2", "name": "All stores' H2 transactions at their own H1 YoY trend",
                 "question": "If every store's H2 receipts had changed YoY as its H1 receipts did",
                 "revenue_impact_eur": a2["revenue_impact"], "range_low_eur": np.nan, "range_high_eur": np.nan,
                 "margin_impact_eur": a2["margin_impact"],
                 "assumptions": "H1 YoY transaction trend continues into H2; AOV, return rate and margin rate as actually "
                                "observed in H2 per store.",
                 "confidence": "Low: H1 trend is a simple extrapolation", "evidence_level": "Hypothesis",
                 "robust_in_sensitivity": False})
    lo, hi, rob = rng("electronics_stockouts_primary")
    ulo, uhi, _ = rng("electronics_stockouts_upper")
    rows.append({"scenario": "B", "name": "Electronics availability at the prior-year baseline",
                 "question": "If full-week stock-outs had stayed at the prior-year level",
                 "revenue_impact_eur": -c["stockouts_primary"], "range_low_eur": -hi, "range_high_eur": -lo,
                 "margin_impact_eur": -c["stockouts_primary"] * R["et_line_margin_rate"],
                 "assumptions": "Lost demand = baseline expected sales in full-week stock-outs; no substitution; margin at "
                                "the category line-margin rate. Range = sensitivity variants, including the estimate net of "
                                f"deferred demand recovered after stock returned (EUR {el['recovery_offset_eur']:,.0f}). The "
                                f"BR-05 upper bound incl. partial weeks (EUR {-c['stockouts_upper']:,.0f}) is not evidence and "
                                "is not used.",
                 "confidence": "Medium" if rob else "Low: the estimate does not survive netting off deferred demand",
                 "evidence_level": "Root-cause evidence" if rob else "Statistical association",
                 "robust_in_sensitivity": rob})
    rows.append({"scenario": "C", "name": "Returns at the prior-year return rate",
                 "question": "If every store had refunded the prior-year share of its sales",
                 "revenue_impact_eur": R["scenario_c"]["revenue_impact"], "range_low_eur": np.nan,
                 "range_high_eur": np.nan, "margin_impact_eur": R["scenario_c"]["margin_impact"],
                 "assumptions": "Prior-year return rate by value applied to current sales (arithmetic, no range). Of this, "
                                f"Electronics 'Faulty' returns at their prior-year level account for EUR "
                                f"{R['scenario_c']['faulty_only']:,.0f}.",
                 "confidence": "High for the arithmetic; it says nothing about why returns rose",
                 "evidence_level": "Observed change", "robust_in_sensitivity": True})
    lo, hi, rob = rng("home_kitchen_promotion")
    rows.append({"scenario": "D", "name": "Home & Kitchen promotional behaviour comparable with the prior year",
                 "question": "If H&K had kept the prior-year discount rate and relative performance",
                 "revenue_impact_eur": -c["promotion"], "range_low_eur": -hi, "range_high_eur": -lo,
                 "margin_impact_eur": -pr["m1"]["margin_effect_eur"],
                 "assumptions": "Central = M1 category DiD (H&K vs control categories in the same store-weeks). Range "
                                "includes M4 (discount rate) and the M2 / M3 methods that point the other way.",
                 "confidence": "Low to medium: methods disagree in sign (see sensitivity)",
                 "evidence_level": "Statistical association", "robust_in_sensitivity": rob})
    excl = ov["attribution"].set_index("component")["amount_eur"]
    comp = excl.drop(excl.index[-1])
    rows.append({"scenario": "E", "name": "Combination of the mutually exclusive components",
                 "question": "Sum of the exclusive attribution components (cluster excess, stock-outs, 'Faulty' returns, "
                             "H&K), after removing any overlap with the cluster excess",
                 "revenue_impact_eur": -float(comp.sum()), "range_low_eur": np.nan, "range_high_eur": np.nan,
                 "margin_impact_eur": np.nan,
                 "assumptions": "Components are exclusive by construction (overlap.py); the residual is not attributed.",
                 "confidence": "As weak as its weakest component (D)", "evidence_level": "Statistical association",
                 "robust_in_sensitivity": False})
    df = pd.DataFrame(rows)
    df["share_of_decline_recovered"] = df["revenue_impact_eur"] / -(cy["net_revenue"] - py["net_revenue"])
    return df
