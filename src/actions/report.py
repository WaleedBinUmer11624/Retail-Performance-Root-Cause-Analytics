"""Phase 8 executive action plan (markdown), generated from the framework tables so every figure is traced."""
from __future__ import annotations

import pandas as pd

from .facts import render


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return str(v).replace("|", "/").replace("\n", " ")


def md_table(df: pd.DataFrame, cols: list, headers: list | None = None) -> str:
    headers = headers or cols
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in df[cols].itertuples(index=False):
        out.append("| " + " | ".join(_cell(v) for v in r) + " |")
    return "\n".join(out)


AUDIENCE = ("Head of Retail, Commercial Director, Finance Director, Supply Chain Manager, Trading Manager, "
            "Operations Manager, Data/BI Lead")


def executive_plan(T: dict, ctx, figure_rel: str) -> str:
    F, cfg = ctx.F, ctx.a

    def r(text):
        return render(text, F, ctx.used.setdefault("executive_plan", set()))

    prio, dfw, act = T["prioritisation"], T["decision_framework"], T["action_register"]
    L = []
    L += ["# Brightwater Retail: H2 2025 net revenue decline, executive action plan", "",
          f"**For:** {AUDIENCE}  ",
          "**Status:** PROPOSED for management review. Every analytical figure is a validated Phase 5 to 7 result; "
          "owners, judgement ratings, timings, durations and threshold concepts are proposals.  ",
          "**Basis:** frozen Phase 1 to 7 outputs (checksums verified at the start of this run). This plan adds no "
          "new analysis and does not depend on the Power BI Desktop build (Phase 7A).", ""]

    # ------------------------------------------------------------------ 1. one page
    L += ["## 1. The position in one page", "",
          r("**What happened (FACT).** H2 2025 net revenue was {nr_cy|eur2} against {nr_py|eur2} in H2 2024: "
            "{nr_change|eur2} ({nr_yoy|pct2}). The figure reconciles to the cent across Phases 4 to 7."), "",
          "**What we know, and how firmly.**", ""]
    rows = []
    for i in dfw.itertuples():
        p = prio.set_index("issue_id").loc[i.issue_id]
        share = "not quantified" if p["share_of_decline"] != p["share_of_decline"] else f"{100 * p['share_of_decline']:.0f}%"
        if i.issue_id in {x["id"] for x in cfg["issues"] if x["relevance"] == "slice"}:
            share = f"({share}, within I2)"
        cause = i.cause_note or i.cause_status
        rows.append({"Issue": f"{i.issue_id} {i.issue}", "Share of decline": share,
                     "Evidence (Phase 6)": i.evidence_level, "Cause": cause,
                     "Decision": f"**{i.decision_category}**"})
    L += [md_table(pd.DataFrame(rows), list(rows[0].keys())), ""]
    L += [r("Shares come from the exclusive Phase 6 attribution: unrounded, the five components (I1, I2, I4, I5, I7) add to "
            "100% of the {nr_change|eur2} change; the rounded figures shown add to 99%. I3 is a slice of I2 and is not "
            "added; I6 is a partition, not an estimate."), ""]
    now = act[act["decision_category"] == "ACT NOW"]
    L += ["**What we can safely do now (ACT NOW).** " + cfg["action_rule_text"].strip(), ""]
    L += [f"- **{a.action_id}** {a.action} *(owner: {a.proposed_owner})*" for a in now.itertuples()]
    L += ["", "**What we must investigate before acting (INVESTIGATE FIRST).**", ""]
    for i in dfw[dfw["decision_category"] == "INVESTIGATE FIRST"].itertuples():
        L.append(f"- **{i.issue_id} {i.issue}:** {i.what_we_do_not_know}")
    holds = act[act["action_type"] == "Hold"]
    L += ["", "**What we will deliberately not do yet (NO ACTION YET).**", ""]
    L += [f"- **{a.action_id}** {a.action}" for a in holds.itertuples()]
    L += ["- **A24** The residual stays UNEXPLAINED / NOT ATTRIBUTED; it is analysed, not acted on.", "",
          "**What this plan does not promise.** No revenue recovery is forecast or promised. Historical estimates "
          "are not recoverable value (section 9), and the effect of every control is to be measured, not assumed.", ""]

    # ------------------------------------------------------------------ 2. where the decline sits
    L += ["## 2. Where the decline sits", "", md_table(pd.DataFrame([
        {"Component": "Store-cluster excess decline (S03, S04, S05)", "Amount": r("{d01_eur|eur}"), "Share": r("{d01_share|pct0}"),
         "Figure": "ESTIMATE", "Cause": "UNRESOLVED"},
        {"Component": "Electronics & Tech full-week stock-outs", "Amount": r("{d03_eur|eur}"), "Share": r("{d03_share|pct0}"),
         "Figure": "ESTIMATE", "Cause": "Root-cause evidence (mechanism)"},
        {"Component": "Electronics & Tech 'Faulty' returns increase", "Amount": r("{d05_eur|eur}"), "Share": r("{d05_share|pct0}"),
         "Figure": "FACT", "Cause": "Defect is a HYPOTHESIS"},
        {"Component": "Home & Kitchen category-specific change (M1)", "Amount": r("{d07_eur|eur}"), "Share": r("{d07_share|pct0}"),
         "Figure": "ESTIMATE", "Cause": "STATISTICAL ASSOCIATION only"},
        {"Component": "Residual", "Amount": r("{d09_eur|eur}"), "Share": r("{d09_share|pct0}"),
         "Figure": "Remainder", "Cause": "UNEXPLAINED / NOT ATTRIBUTED"},
        {"Component": "**Total**", "Amount": r("**{att_total|eur2}**"), "Share": r("**{att_share_total|pct0}**"),
         "Figure": "", "Cause": ""}]), ["Component", "Amount", "Share", "Figure", "Cause"]), "",
        r("The four Home & Kitchen methods are never added: M1 {m1|seur}, M4 {m4|seur}, M2 {m2|seur}, M3 {m3|seur}. "
          "Promotion activity is associated with the Home & Kitchen decline, but causality is not established."), ""]

    # ------------------------------------------------------------------ 3. prioritisation
    L += ["## 3. How priorities were set", "",
          "Size can make an issue worth investigating; only evidence can make it ACT NOW. The rule, applied in code "
          "and tested:", ""]
    L += [f"{n}. {t}" for n, t in enumerate(cfg["decision_rule_text"], 1)]
    L += ["", f"![Prioritisation grid]({figure_rel})", "",
          md_table(prio, ["issue_id", "financial_relevance", "evidence_strength", "business_urgency",
                          "implementation_effort", "reversibility", "data_requirement", "risk_of_acting_now",
                          "time_to_validate", "decision_category", "rule_applied"],
                   ["Issue", "Financial", "Evidence", "Urgency", "Effort", "Reversibility", "Data need",
                    "Risk of acting now", "Time to validate", "Decision", "Rule"]), "",
          "Financial relevance and evidence strength are computed from the frozen results; the other ratings are "
          "PROPOSED judgements with a written reason in `phase8_prioritisation_matrix.csv`, so the categories depend "
          "on them too. Reversibility is High for every issue (all immediate actions can be stopped at no cost), so "
          "it does not separate issues. Which single judgement would change each category:", ""]
    L += [f"- **{x.issue_id}** ({x.decision_category}): {x.pivotal_judgements}." for x in prio.itertuples()]
    L += ["", "I6 is rated 'Not quantified' because the Phase 6 range split is a partition, not an estimate of a cause; "
          "the rule treats it like Low. Level definitions:", ""]
    L += [f"- **{k.replace('_', ' ').capitalize()}:** {v}" for k, v in cfg["ratings"]["definitions"].items()]
    L.append("")

    # ------------------------------------------------------------------ 4. issue by issue
    L += ["## 4. Issue by issue", ""]
    for i in dfw.itertuples():
        acts = act[act["issue_id"] == i.issue_id]
        L += [f"### {i.issue_id}. {i.issue}: {i.decision_category}", "",
              f"- **What happened:** {i.observed_evidence}",
              f"- **Financial relevance:** {i.financial_relevance}",
              f"- **Evidence level:** {i.evidence_level}. **Cause status:** {i.cause_note or i.cause_status}.",
              f"- **What we know:** {i.what_we_know}",
              f"- **What we do not know:** {i.what_we_do_not_know}",
              f"- **Why it matters (business risk):** {i.business_risk}",
              f"- **What we can safely do:** {i.immediate_safe_action}",
              f"- **What we must investigate:** {i.investigation_required}",
              f"- **Additional data required:** {i.additional_data_required}",
              f"- **Who:** {i.proposed_owner}; supported by {i.supporting_teams}",
              f"- **How we measure it:** {i.kpi_to_monitor}",
              f"- **Trigger / escalation:** {i.trigger_escalation}",
              f"- **When we review it:** {i.review_frequency}",
              f"- **Decision after investigation:** {i.decision_after_investigation}", ""]
        if len(acts):
            L += [md_table(acts, ["action_id", "decision_category", "action_type", "action", "timing_window_days"],
                           ["Action", "Category", "Type", "What", "Days"]), ""]

    # ------------------------------------------------------------------ 5. frameworks
    fw = cfg["frameworks"]
    L += ["## 5. Investigation frameworks", "", f"### 5.1 {fw['cluster_sequence']['title']}", "",
          r(fw["cluster_sequence"]["note"]), ""]
    seq = pd.DataFrame([{"Step": s["step"], "Question": s["question"], "Data": ", ".join(s["data"]),
                         "If found": r(s["supports"]), "Otherwise": r(s["otherwise"])} for s in fw["cluster_sequence"]["steps"]])
    L += [md_table(seq, list(seq.columns)), "", f"### 5.2 {fw['inventory_checks']['title']}", "",
          fw["inventory_checks"]["note"], ""]
    inv = pd.DataFrame(fw["inventory_checks"]["rows"])
    L += [md_table(inv, ["check", "question", "supply", "ordering", "data"],
                   ["Check", "Question", "Points to supply", "Points to ordering", "Data"]), "",
          f"### 5.3 {fw['returns_classification']['title']}", "", fw["returns_classification"]["note"], ""]
    rc = pd.DataFrame([{k: r(v) if isinstance(v, str) else v for k, v in x.items()}
                       for x in fw["returns_classification"]["rows"]])
    L += [md_table(rc, ["explanation", "evidence_for", "evidence_against", "data"],
                   ["Explanation", "Evidence that would support it", "Evidence against it", "Data"]), "",
          f"### 5.4 {fw['promotion_framework']['title']}", ""]
    pf = pd.DataFrame([{"Topic": s["topic"], "Question": s["question"], "What we have now": r(s["now"]),
                        "How to measure": s["measure"]} for s in fw["promotion_framework"]["rows"]])
    L += [md_table(pf, list(pf.columns)), "", f"### 5.5 {fw['test_design']['title']}", ""]
    L += [f"- {r(s)}" for s in fw["test_design"]["items"]]
    L += ["", f"### 5.6 {fw['residual_dimensions']['title']}", "", fw["residual_dimensions"]["note"], ""]
    rd = pd.DataFrame(fw["residual_dimensions"]["rows"])
    L += [md_table(rd, ["dimension", "check", "data"], ["Dimension", "Check", "Data"]), ""]

    # ------------------------------------------------------------------ 6. plan
    L += ["## 6. 30 / 60 / 90 day plan", "",
          "Days count from management approval. The plan sequences validation, data, low-risk controls, testing "
          "and evaluation; it does not promise a revenue recovery.", ""]
    for w, title in [("0-30", "0 to 30 days: validate, acquire data, start low-risk controls"),
                     ("31-60", "31 to 60 days: test hypotheses, analyse supply, launch the promotion test"),
                     ("61-90", "61 to 90 days: evaluate, standardise, close unsupported hypotheses (the promotion "
                               "depth decision follows at a post-test gate, planned around day 150 to 180)")]:
        L += [f"**{title}**", "", md_table(T["plan"][T["plan"]["window_days"] == w],
                                           ["focus", "activity", "deliverable", "proposed_owner"],
                                           ["Focus", "Activity", "Deliverable", "Owner"]), ""]

    # ------------------------------------------------------------------ 7. KPIs
    k = T["kpis"]
    L += ["## 7. KPI monitoring framework", "",
          f"{(k['current_availability'] == 'Available').sum()} KPIs exist in the project today, "
          f"{k['current_availability'].str.startswith('Available (').sum()} is available as an analysis estimate only and "
          f"{(k['current_availability'] == 'Not available').sum()} need data Brightwater does not yet hold. Unavailable KPIs "
          "carry no value: none is estimated. No threshold is calibrated yet.", "",
          md_table(k, ["kpi", "definition", "proposed_owner", "frequency", "current_availability", "value_h2_2024",
                       "value_h2_2025", "threshold_concept"],
                   ["KPI", "Definition", "Owner", "Frequency", "Available", "H2 2024", "H2 2025", "Threshold (concept)"]), ""]

    # ------------------------------------------------------------------ 8. early warning
    L += ["## 8. Early-warning requirements", "",
          "A specification for a later monitoring phase. No forecasting is built here and no threshold is set: each "
          "must be back-tested for false alarms and detection delay before use.", "",
          md_table(T["early_warning"], ["signal_id", "signal", "metric", "baseline_concept", "threshold_concept",
                                        "monitoring_frequency", "alert_recipient", "required_response"],
                   ["ID", "Signal", "Metric", "Baseline", "Threshold (concept)", "Frequency", "Alert to", "Response"]), ""]

    # ------------------------------------------------------------------ 9. impact
    L += ["## 9. Business impact: history is not a forecast", "",
          "Three separate things: what was measured (FACT), what was estimated about the past (ESTIMATE), and what "
          "might be recoverable in future. The third is not estimated unless the mechanism is known.", "",
          md_table(T["impact"], ["issue_id", "observed_historical_impact", "estimated_historical_impact",
                                 "potential_recoverable_value", "why"],
                   ["Issue", "Observed (historical)", "Estimated (historical)", "Recoverable", "Why"]), "",
          "**Scenarios (I2 only).** " + r(cfg["scenarios"]["intro"]), "",
          md_table(T["scenarios"], ["scenario", "illustrative_value_h2_2025", "assumptions", "basis"],
                   ["Scenario", "Illustrative value (H2 2025)", "Assumptions", "Basis"]), "",
          r(cfg["scenarios"]["margin_note"]), ""]

    # ------------------------------------------------------------------ 10. evidence to action
    L += ["## 10. Evidence-to-action controls", "",
          "What each finding allows management to conclude, and what it does not.", "",
          md_table(T["evidence_to_action"], ["id", "finding", "evidence_level", "permitted_conclusion",
                                             "not_permitted_conclusion", "recommended_next_step"],
                   ["ID", "Finding", "Evidence", "Permitted conclusion", "Not permitted", "Next step"]), ""]

    # ------------------------------------------------------------------ 11. decision log
    L += ["## 11. Decision log (first entries)", "",
          "Dates, results and learning are empty until management takes each decision; "
          "`phase8_decision_log_template.csv` is the template.", "",
          md_table(T["decision_log"], ["decision_id", "issue", "decision", "evidence_level", "owner", "review_date", "status"],
                   ["ID", "Issue", "Decision", "Evidence level", "Owner", "Review", "Status"]), ""]

    # ------------------------------------------------------------------ 12. data
    dr = T["data_requirements"]
    L += ["## 12. Additional data required", "",
          f"{len(dr)} data items; {(dr['available_in_project'] == 'No').sum()} are not in the project at all and "
          f"{(dr['available_in_project'] == 'Partial').sum()} exist only as a proxy. Full list: "
          "`phase8_data_requirements.csv`.", "",
          md_table(dr, ["data_id", "data_item", "question_it_answers", "issues", "proposed_owner", "needed_by_days"],
                   ["ID", "Data", "Question it answers", "Issues", "Owner", "Needed by (days)"]), ""]

    # ------------------------------------------------------------------ 13. limitations
    L += ["## 13. Limitations", "",
          "- Every number describes H2 2025 against H2 2024 in synthetic data; nothing here is a forecast.",
          "- Owners, ratings other than financial relevance and evidence strength, timings and threshold concepts are "
          "proposals for management, not findings.",
          "- The KPIs marked Not available need data Brightwater does not hold in this project; the plan names the data, "
          "it does not estimate the values.",
          "- The promotion test can detect only large effects with the number of eligible stores, and its result "
          "arrives after day 90; the design says how to handle both, and an inconclusive result is not a reason to cut.",
          "- The plan does not depend on the Power BI Desktop build (Phase 7A); it uses only validated Phase 5 to 7 outputs.",
          "", "## Sources", "",
          "Frozen inputs: `reports/phase6/root_cause_evidence_matrix.csv`, `driver_attribution.csv`, "
          "`sensitivity_summary.csv`, `counterfactual_scenarios.csv` and the other Phase 6 tables named in "
          "`phase8_fact_register.csv`; `reports/phase7/dashboard_number_register.csv`; `reports/phase5/headline_kpis.csv`.", ""]
    return "\n".join(L)
