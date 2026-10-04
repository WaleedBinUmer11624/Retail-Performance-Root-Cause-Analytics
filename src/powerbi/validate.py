"""Phase 7 reconciliation: the dashboard's measures (via their Python reference) and imported Phase 6 tables
against the frozen Phase 4, 5 and 6 results. Every check is a row with value, reference, tolerance, status.
"""
from __future__ import annotations

import math
import re

import pandas as pd

from src.analytics.model_access import sha256_normalised

from . import dax as DX
from .access import allowed_path, read_csv
from .reference import MEASURES as REF_MEASURES
from .reference import Ctx, Model, evaluate, h2


class Checks:
    def __init__(self):
        self.rows = []

    def add(self, group, check, value, reference, tol, source, passed=None):
        num = isinstance(value, (int, float)) and isinstance(reference, (int, float))
        diff = abs(float(value) - float(reference)) if num else float("nan")
        ok = passed if passed is not None else (num and not math.isnan(diff) and diff <= tol)
        self.rows.append({"group": group, "check": check, "value": value, "reference": reference,
                          "abs_difference": diff, "tolerance": tol, "reference_source": source,
                          "status": "PASS" if ok else "FAIL"})

    def frame(self):
        return pd.DataFrame(self.rows)


def run(M: Model, cfg: dict, extracts: dict, schema: dict) -> pd.DataFrame:
    C = Checks()
    pc = cfg["powerbi"]
    tol = pc["tolerances"]
    hd = pc["headline"]
    cy, py = h2(hd["retail_year_cy"]), h2(hd["retail_year_py"])
    ev = lambda m, c=cy: evaluate(M, m, c)  # noqa: E731

    # ---------------------------------------------------------------- 1. headline vs brief, Phase 4, 5, 6
    nr_cy, nr_py = ev("Net Revenue"), ev("Net Revenue PY")
    chg, yoy = ev("Net Revenue YoY"), 100 * ev("Net Revenue YoY %")
    for lab, v, ref in (("H2 2025 net revenue", nr_cy, hd["net_revenue_cy"]), ("H2 2024 net revenue", nr_py, hd["net_revenue_py"]),
                        ("H2 net revenue change", chg, hd["change"])):
        C.add("Headline", f"{lab} = Phase 7 brief", v, ref, tol["eur"], "config/powerbi_config.yaml (brief)")
    C.add("Headline", "YoY % = Phase 7 brief (6 dp)", round(yoy, 6), hd["yoy_pct"], tol["pct_points"], "brief")
    C.add("Headline", "H2 2024 via the PY measure = H2 2024 filtered directly", nr_py, ev("Net Revenue", py), tol["eur"],
          "PY time intelligence")
    b4 = read_csv("reports/phase4/reconciliation_results_duckdb.csv", cfg).set_index("metric_name")["actual_value"]
    C.add("Phase 4", "H2 2025 net revenue", nr_cy, float(b4["h2_2025_net_revenue"]), tol["eur"], "reports/phase4/reconciliation_results_duckdb.csv")
    C.add("Phase 4", "H2 2024 net revenue", nr_py, float(b4["h2_2024_net_revenue"]), tol["eur"], "reports/phase4/reconciliation_results_duckdb.csv")
    C.add("Phase 4", "H2 YoY %", yoy, float(b4["h2_yoy_pct"]), 1e-6, "reports/phase4/reconciliation_results_duckdb.csv")
    k5 = read_csv("reports/phase5/headline_kpis.csv", cfg).set_index("metric")
    m5 = {"sales_revenue": "Sales Revenue", "returns_value": "Returns Value", "net_revenue": "Net Revenue",
          "gross_margin": "Gross Margin", "gross_margin_pct": "Gross Margin %", "transactions": "Transactions",
          "units_sold": "Units", "aov": "Average Transaction Value", "upt": "UPT", "asp": "ASP",
          "return_rate_value": "Return Rate", "promo_revenue_share": "Promotion Share", "discount_value": "Discount Value"}
    for key, meas in m5.items():
        is_ratio = key in ("gross_margin_pct", "aov", "upt", "asp", "return_rate_value", "promo_revenue_share")
        t = 1e-6 if is_ratio else tol["eur"]
        C.add("Phase 5", f"{meas} H2 2025", ev(meas), float(k5.loc[key, "h2_current"]), t, "reports/phase5/headline_kpis.csv")
        C.add("Phase 5", f"{meas} H2 2024", ev(meas, py), float(k5.loc[key, "h2_prior"]), t, "reports/phase5/headline_kpis.csv")
    r6 = read_csv("reports/phase6/headline_reconciliation.csv", cfg).set_index("check")["recomputed"]
    C.add("Phase 6", "H2 2025 net revenue", nr_cy, float(r6["H2 2025 net revenue vs Phase 4"]), tol["eur"], "reports/phase6/headline_reconciliation.csv")
    C.add("Phase 6", "H2 2024 net revenue", nr_py, float(r6["H2 2024 net revenue vs Phase 4"]), tol["eur"], "reports/phase6/headline_reconciliation.csv")
    C.add("Phase 6", "H2 change", chg, float(r6["net_revenue change vs Phase 5 headline"]), tol["eur"], "reports/phase6/headline_reconciliation.csv")

    # ---------------------------------------------------------------- 2. weekly trend (Page 1) vs Phase 5
    wk = read_csv("reports/phase5/headline_trend.csv", cfg)
    worst = 0.0
    for r in wk.itertuples():
        c = Ctx({"Date": {"retail_year": hd["retail_year_cy"], "retail_week": int(r.retail_week)}})
        worst = max(worst, abs(evaluate(M, "Net Revenue", c) - r.net_revenue_cy),
                    abs(evaluate(M, "Net Revenue PY", c) - r.net_revenue_py),
                    abs(evaluate(M, "Transactions PY", c) - r.transactions_py))
    C.add("Weekly", f"26 H2 weeks: Net Revenue, Net Revenue PY and Transactions PY (largest difference)", worst, 0.0,
          tol["eur"], "reports/phase5/headline_trend.csv")

    # ---------------------------------------------------------------- 3. stores vs Phase 5
    st = read_csv("reports/phase5/store_contribution.csv", cfg)
    cols = {"net_revenue": ("Net Revenue", tol["eur"]), "transactions": ("Transactions", 0),
            "aov": ("Average Transaction Value", 1e-6), "upt": ("UPT", 1e-6), "asp": ("ASP", 1e-6),
            "return_rate_value": ("Return Rate", 1e-6), "availability": ("Availability", 1e-6),
            "target_achievement": ("Target Achievement %", 1e-6)}
    worst = {k: 0.0 for k in cols}
    for r in st.itertuples():
        for side, ctx in (("cy", cy), ("py", py)):
            c = ctx.with_("Store", store_id=r.store_id)
            for key, (meas, _) in cols.items():
                worst[key] = max(worst[key], abs(evaluate(M, meas, c) - getattr(r, f"{key}_{side}")))
    for key, (meas, t) in cols.items():
        C.add("Stores", f"{meas}: 20 stores x 2 periods (largest difference)", worst[key], 0.0, t,
              "reports/phase5/store_contribution.csv")

    tp = read_csv("reports/phase5/target_performance.csv", cfg)
    for yr, ctx in ((hd["retail_year_cy"], cy), (hd["retail_year_py"], py)):
        g = tp[tp["retail_year"] == yr]
        C.add("Targets", f"estate Target Achievement % H2 {yr}", ev("Target Achievement %", ctx),
              float(g["net_revenue"].sum() / g["target_net_revenue"].sum()), 1e-6, "reports/phase5/target_performance.csv")

    # ---------------------------------------------------------------- 4. categories vs Phase 5
    ca = read_csv("reports/phase5/category_contribution.csv", cfg)
    cols = {"net_revenue": ("Net Revenue", tol["eur"]), "sales_revenue": ("Sales Revenue", tol["eur"]),
            "transactions_with_category": ("Transactions", 0), "units_sold": ("Units", 0), "asp": ("ASP", 1e-6),
            "gross_margin": ("Gross Margin", tol["eur"]), "returns_value": ("Returns Value", tol["eur"]),
            "return_rate_value": ("Return Rate", 1e-6), "availability": ("Availability", 1e-6),
            "promo_revenue_share": ("Promotion Share", 1e-6), "discount_value": ("Discount Value", tol["eur"])}
    worst = {k: 0.0 for k in cols}
    for r in ca.itertuples():
        for side, ctx in (("cy", cy), ("py", py)):
            c = ctx.with_("Product", category=r.category)
            for key, (meas, _) in cols.items():
                worst[key] = max(worst[key], abs(evaluate(M, meas, c) - getattr(r, f"{key}_{side}")))
    for key, (meas, t) in cols.items():
        C.add("Categories", f"{meas}: 7 categories x 2 periods (largest difference)", worst[key], 0.0, t,
              "reports/phase5/category_contribution.csv")

    # ---------------------------------------------------------------- 5. Phase 6 figures the measures reproduce
    et, hk, sup = pc["focus_category_availability"], pc["focus_category_promotions"], pc["focus_supplier"]
    ek = read_csv("reports/phase6/electronics_kpis.csv", cfg).set_index("metric")
    c_et = cy.with_("Product", category=et)
    C.add("Phase 6", f"{et} net revenue change", ev("Net Revenue YoY", c_et), float(ek.loc["net_revenue", "change"]),
          tol["eur"], "reports/phase6/electronics_kpis.csv")
    C.add("Phase 6", f"{et} availability H2 2025", ev("Availability", c_et), float(ek.loc["availability", "current"]),
          1e-6, "reports/phase6/electronics_kpis.csv")
    C.add("Phase 6", f"{et} availability H2 2024", ev("Availability PY", c_et), float(ek.loc["availability", "prior"]),
          1e-6, "reports/phase6/electronics_kpis.csv")
    sc = read_csv("reports/phase6/electronics_supplier_comparison.csv", cfg).set_index("supplier_name")
    c_sup = c_et.with_("Product", supplier_name=sup)
    C.add("Phase 6", f"{sup} full-week stock-outs H2 2025", ev("Full-Week Stock-Outs", c_sup),
          float(sc.loc[sup, "full_week_out_cells_cy"]), 0, "reports/phase6/electronics_supplier_comparison.csv")
    C.add("Phase 6", f"{sup} full-week stock-outs H2 2024", ev("Full-Week Stock-Outs PY", c_sup),
          float(sc.loc[sup, "full_week_out_cells_py"]), 0, "reports/phase6/electronics_supplier_comparison.csv")
    C.add("Phase 6", f"{sup} availability H2 2025", ev("Availability", c_sup), float(sc.loc[sup, "availability_cy"]),
          1e-6, "reports/phase6/electronics_supplier_comparison.csv")
    mech = read_csv("reports/phase6/cluster_mechanisms.csv", cfg).set_index("metric")
    for grp, col in (("Investigated cluster", "cluster"), ("Matched control", "control")):
        c = cy.with_("Store", store_group=grp)
        C.add("Phase 6", f"{grp}: transactions per store H2 2025", ev("Transactions", c) / len(M.rows("Store", Ctx()).pipe(
            lambda d: d[d["store_group"] == grp])), float(mech.loc["transactions_per_store", f"{col}_cy"]), 1e-6,
            "reports/phase6/cluster_mechanisms.csv")
        C.add("Phase 6", f"{grp}: transactions YoY % (= per-store change)", 100 * ev("Transactions YoY %", c),
              float(mech.loc["transactions_per_store", f"{col}_change"]), 1e-4, "reports/phase6/cluster_mechanisms.csv")
    fr = read_csv("reports/phase6/faulty_returns_reasons.csv", cfg).set_index("return_reason")
    for reason in fr.index:
        c = c_et.with_("Returns", return_reason=reason)
        C.add("Phase 6", f"{et} '{reason}' returns change", ev("Returns Value YoY", c),
              float(fr.loc[reason, "value_change"]), tol["eur"], "reports/phase6/faulty_returns_reasons.csv")
    coh = read_csv("reports/phase6/faulty_returns_by_cohort.csv", cfg)
    worst = 0.0
    for r in coh.itertuples():
        c = Ctx({"Date": {"year_month": int(r.sale_year_month)}, "Product": {"category": et},
                 "Returns": {"return_reason": "Faulty"}})
        units_ret = float(M.rows("Returns", Ctx(c.filters, True))["return_quantity"].sum())
        worst = max(worst, abs(100 * units_ret / evaluate(M, "Units", c) - r.rate_per_100))
    C.add("Phase 6", "Faulty cohort rate per 100 units by sale month (24 months, largest difference)", worst, 0.0, 1e-6,
          "reports/phase6/faulty_returns_by_cohort.csv")
    m4 = read_csv("reports/phase6/hk_promotion_counterfactuals.csv", cfg)
    txt = m4[m4["method"].str.startswith("M4")]["detail"].iloc[0]
    lo, hi = (float(x) for x in re.findall(r"([\d.]+)%", txt)[:2])
    c_hk = cy.with_("Product", category=hk)
    C.add("Phase 6", f"{hk} discount rate H2 2024 (1 dp, as reported)", round(100 * ev("Discount Rate PY", c_hk), 1), lo,
          1e-9, "reports/phase6/hk_promotion_counterfactuals.csv (M4 detail)")
    C.add("Phase 6", f"{hk} discount rate H2 2025 (1 dp, as reported)", round(100 * ev("Discount Rate", c_hk), 1), hi,
          1e-9, "reports/phase6/hk_promotion_counterfactuals.csv (M4 detail)")

    # ---------------------------------------------------------------- 6. attribution and evidence (imported tables)
    at = extracts["p6_driver_attribution"]
    C.add("Attribution", "components add up to the H2 change (model)", float(at["amount_eur"].sum()), chg, tol["eur"],
          "powerbi/data/p6_driver_attribution.csv vs measures")
    C.add("Attribution", "shares add up to 100%", float(at["share_of_change"].sum()), 1.0, 1e-6, "p6_driver_attribution")
    brief = {"D01": -397778, "D03": -37235, "D05": -31589, "D07": -186146, "D09": -78522}
    for r in at.itertuples():
        C.add("Attribution", f"{r.driver_id} amount = brief (whole euros)", round(r.amount_eur), brief[r.driver_id], 0,
              "brief section 4")
    em = extracts["p6_evidence_matrix"].set_index("driver_id")
    src = read_csv("reports/phase6/root_cause_evidence_matrix.csv", cfg).set_index("driver_id")
    C.add("Evidence", "evidence levels identical to the Phase 6 matrix", int((em["evidence_level"] != src["evidence_level"]).sum()),
          0, 0, "reports/phase6/root_cause_evidence_matrix.csv")
    rce_ok = all((em.loc[d, "evidence_level"] == "Root-cause evidence") == (em.loc[d, "cause_status"] == "Established")
                 for d in em.index)
    C.add("Evidence", "cause 'Established' only where Phase 6 says Root-cause evidence", rce_ok, True, 0,
          "config drivers vs Phase 6", rce_ok)
    unres = all("UNRESOLVED" in str(src.loc[d, "conclusion"]) for d in em.index if em.loc[d, "cause_status"] == "Unresolved"
                and d != "D01") and "UNRESOLVED" in str(src.loc["D02", "conclusion"])
    C.add("Evidence", "'Unresolved' labels match Phase 6 conclusions (D01 via its cause D02)", unres, True, 0,
          "reports/phase6/root_cause_evidence_matrix.csv", unres)
    hyp_ok = all(em.loc[d, "cause_status"] != "Established" for d in em.index
                 if em.loc[d, "evidence_level"] in ("Hypothesis", "Statistical association"))
    C.add("Evidence", "no association or hypothesis is labelled as an established cause", hyp_ok, True, 0,
          "config drivers", hyp_ok)
    at_lv = all(r.evidence_level == ("Not attributed" if r.driver_id == "D09" else src.loc[r.driver_id, "evidence_level"])
                for r in at.itertuples())
    C.add("Evidence", "attribution evidence labels = Phase 6 matrix", at_lv, True, 0, "Phase 6", at_lv)
    methods = extracts["p6_hk_methods"]
    C.add("Promotions", "four H&K methods kept separate (no combined figure)", len(methods), 4, 0, "p6_hk_methods")
    C.add("Promotions", "methods disagree in sign (the reported story)",
          bool((methods["effect_eur"] < 0).any() and (methods["effect_eur"] > 0).any()), True, 0, "p6_hk_methods",
          bool((methods["effect_eur"] < 0).any() and (methods["effect_eur"] > 0).any()))

    # ---------------------------------------------------------------- guards (blank instead of a wrong number)
    pr = cy.with_("Promotion", member_type="Promotion")
    blank = all(math.isnan(ev(m, pr)) for m in ("Net Revenue", "Returns Value", "Gross Margin", "Availability"))
    C.add("Guards", "Promotion filter: returns, net revenue, margin and availability are blank (no promotion key)",
          blank, True, 0, "measure design", blank)
    C.add("Guards", "Promotion filter: Sales Revenue still answers", ev("Sales Revenue", pr) > 0, True, 0,
          "measure design", ev("Sales Revenue", pr) > 0)
    tb = math.isnan(ev("Target Achievement %", cy.with_("Product", category=et)))
    C.add("Guards", "Category filter: Target Achievement is blank (targets are per store)", tb, True, 0,
          "measure design", tb)

    # ---------------------------------------------------------------- 7. traceability of every extract
    man = pd.read_csv(allowed_path("reports/phase7/phase1_6_input_manifest.csv", cfg)).set_index("file")["sha256"]
    bad = []
    for r in extracts["_manifest"].itertuples():
        if r.source_sha256 != man.get(r.source_file) or r.source_sha256 != sha256_normalised(allowed_path(r.source_file, cfg)):
            bad.append(r.extract)
    C.add("Traceability", "every Power BI extract comes from a frozen, unchanged Phase 5/6 file", len(bad), 0, 0,
          "reports/phase7/phase1_6_input_manifest.csv", not bad)

    # ---------------------------------------------------------------- 8. DAX static checks
    st_rows = pd.DataFrame(DX.static_checks(schema))
    for chk, g in st_rows.groupby("check"):
        fails = g[g["status"] != "PASS"]
        C.add("DAX", f"{chk} ({len(g)} measures)" if len(g) > 1 else chk, len(fails), 0, 0, "src/powerbi/dax.py",
              fails.empty)
    missing = [m.reference for m in DX.MEASURES if m.reference and m.reference not in REF_MEASURES]
    C.add("DAX", "every referenced Python counterpart exists", len(missing), 0, 0, "src/powerbi/reference.py", not missing)
    return C.frame()
