"""Phase 8 decision framework: builds every management table from config/action_config.yaml and the fact base.

Nothing here estimates anything. Evidence levels come from the frozen Phase 6 evidence matrix, cause status and
causal-evidence strength from the frozen Phase 7 configuration, numbers from src/actions/facts.py. The only
logic is the documented decision rule (`decide`) and the rating thresholds in the config.
"""
from __future__ import annotations

import pandas as pd

from .access import PROJECT_ROOT, allowed_path, read_csv
from .facts import Facts, render

CATEGORIES = ["ACT NOW", "INVESTIGATE FIRST", "MONITOR", "NO ACTION YET"]
OWNER_TAG = " (PROPOSED)"
MATRIX = "reports/phase6/root_cause_evidence_matrix.csv"


def yn(v) -> str:
    """YAML reads bare Yes / No as booleans: turn them back into the words the tables show."""
    return {True: "Yes", False: "No"}.get(v, v) if isinstance(v, bool) else str(v)


def proposed(owner: str) -> str:
    """Owners are not findings of the analysis: every owner is labelled PROPOSED."""
    parts = [p.strip() for p in str(owner).split(";") if p.strip()]
    return "; ".join(p + OWNER_TAG for p in parts)


class Context:
    def __init__(self, cfg: dict, F: Facts):
        self.cfg, self.F = cfg, F
        self.a = cfg["actions"]
        m = read_csv(MATRIX, cfg)
        self.level = dict(zip(m["driver_id"], m["evidence_level"]))
        self.matrix = m.set_index("driver_id")
        self.drivers = cfg["powerbi"]["drivers"]
        self.strength = {k: v["strength"] for k, v in cfg["powerbi"]["evidence_levels"].items()}
        self.issues = {i["id"]: i for i in self.a["issues"]}
        self.data = {d["id"]: d for d in self.a["data_requirements"]}
        self.used: dict[str, set] = {}
        self.config_file = PROJECT_ROOT / "config" / "action_config.yaml"

    def cfg_path(self, rel: str):
        return allowed_path(rel, self.cfg)

    def r(self, text, table: str):
        """Render placeholders, recording which facts each output table uses."""
        return render(text, self.F, self.used.setdefault(table, set()))

    def evidence(self, drivers) -> str:
        return "; ".join(f"{d}: {self.level[d]}" for d in drivers)

    def cause(self, drivers) -> str:
        return "; ".join(f"{d}: {self.drivers[d]['cause_status']}" for d in drivers)


# ----------------------------------------------------------------------------- ratings and the decision rule
def financial(ctx: Context, issue: dict) -> tuple[float | None, str, str]:
    """(share of the decline, rating, basis). Partition: not quantified. Slice: its own share, flagged."""
    F, th = ctx.F, ctx.a["ratings"]["financial_relevance"]
    total = abs(F["nr_change"])
    if issue["relevance"] == "partition":
        return None, "Not quantified", "A partition of the category change (FACT), not an estimate; not re-counted."
    if issue["relevance"] == "slice":
        amount = F["d04_eur"]
        basis = f"Slice of {issue['slice_of']} (Phase 6 D04 amount); not additional to it."
    else:
        key = {"D01": "d01_eur", "D03": "d03_eur", "D05": "d05_eur", "D07": "d07_eur", "D09": "d09_eur"}[issue["attribution_driver"]]
        amount = F[key]
        basis = f"Phase 6 attribution, driver {issue['attribution_driver']}."
    share = abs(amount) / total
    rating = "High" if share >= th["High"] else ("Medium" if share >= th["Medium"] else "Low")
    return share, rating, basis


def evidence_strength(ctx: Context, issue: dict) -> tuple[int, str]:
    s = max(ctx.strength[ctx.level[d]] for d in issue["drivers"])
    th = ctx.a["ratings"]["evidence_strength"]
    return s, ("High" if s >= th["High"] else ("Medium" if s >= th["Medium"] else "Low"))


def not_attributed(ctx: Context, issue: dict) -> bool:
    return all(ctx.drivers[d]["cause_status"] == "Not attributed" for d in issue["drivers"])


def decide(fin: str, ev: str, urgency: str, reversibility: str, risk: str, unattributed: bool) -> tuple[str, int]:
    """The documented decision rule (config decision_rule_text). Returns (category, rule number)."""
    if unattributed:
        return "NO ACTION YET", 1
    if ev == "High" and reversibility == "High" and risk == "Low":
        return "ACT NOW", 2
    if fin in ("High", "Medium") or urgency == "High" or risk == "High":
        return "INVESTIGATE FIRST", 3
    return "MONITOR", 4


def prioritisation(ctx: Context) -> pd.DataFrame:
    rows = []
    for i in ctx.a["issues"]:
        share, fin, fin_basis = financial(ctx, i)
        s, ev = evidence_strength(ctx, i)
        rt = {k: v[0] for k, v in i["ratings"].items()}
        cat, rule = decide(fin, ev, rt["business_urgency"], rt["reversibility"], rt["risk_of_acting_now"], not_attributed(ctx, i))
        row = {"issue_id": i["id"], "issue": i["title"], "drivers": ", ".join(i["drivers"]),
               "share_of_decline": None if share is None else round(share, 6), "financial_relevance": fin,
               "financial_basis": fin_basis, "evidence_level_phase6": ctx.evidence(i["drivers"]),
               "causal_evidence_strength_0_3": s, "evidence_strength": ev}
        for k in ["business_urgency", "implementation_effort", "reversibility", "data_requirement",
                  "risk_of_acting_now", "time_to_validate"]:
            row[k] = rt[k]
            row[k + "_reason"] = i["ratings"][k][1]
        flips = {}
        for k, alts in [("business_urgency", ["High", "Medium", "Low"]), ("reversibility", ["High", "Medium", "Low"]),
                        ("risk_of_acting_now", ["High", "Medium", "Low"])]:
            for alt in alts:
                if alt == rt[k]:
                    continue
                trial = dict(rt, **{k: alt})
                c2, _ = decide(fin, ev, trial["business_urgency"], trial["reversibility"], trial["risk_of_acting_now"],
                               not_attributed(ctx, i))
                if c2 != cat:
                    flips.setdefault((c2, k), []).append(alt)
        row.update({"decision_category": cat, "rule_applied": rule,
                    "pivotal_judgements": "; ".join(f"{c2} if {k.replace('_', ' ')} were {' or '.join(v)}"
                                                    for (c2, k), v in flips.items())
                                          or "none: no single judgement rating changes it",
                    "rule_text": ctx.a["decision_rule_text"][rule - 1],
                    "ratings_status": "financial relevance and evidence strength computed from frozen results; "
                                      "other ratings are PROPOSED judgements"})
        rows.append(row)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- tables
def decision_framework(ctx: Context, prio: pd.DataFrame) -> pd.DataFrame:
    cat = dict(zip(prio["issue_id"], prio["decision_category"]))
    fin = prio.set_index("issue_id")
    rows = []
    for i in ctx.a["issues"]:
        t = "decision_framework"
        rows.append({
            "issue_id": i["id"], "issue": i["title"], "drivers": ", ".join(i["drivers"]),
            "decision_category": cat[i["id"]],
            "observed_evidence": ctx.r(i["observed_evidence"], t),
            "financial_relevance": f"{fin.loc[i['id'], 'financial_relevance']}. " + ctx.r(i["financial_note"], t),
            "evidence_level": ctx.evidence(i["drivers"]), "cause_status": ctx.cause(i["drivers"]),
            "cause_note": i.get("cause_note", ""),
            "what_we_know": ctx.r(i["what_we_know"], t), "what_we_do_not_know": ctx.r(i["what_we_do_not_know"], t),
            "business_risk": ctx.r(i["business_risk"], t), "immediate_safe_action": ctx.r(i["immediate_safe_action"], t),
            "investigation_required": ctx.r(i["investigation_required"], t),
            "additional_data_required": "; ".join(f"{d} {ctx.data[d]['item']}" for d in i["data_ids"]),
            "proposed_owner": proposed(i["owner"]), "supporting_teams": proposed(i["supporting"]),
            "kpi_to_monitor": ctx.r(i["kpi"], t), "trigger_escalation": ctx.r(i["trigger"], t),
            "review_frequency": i["review_frequency"],
            "decision_after_investigation": ctx.r(i["decision_after_investigation"], t)})
    return pd.DataFrame(rows)


def action_register(ctx: Context) -> pd.DataFrame:
    rows = []
    for a in ctx.a["actions"]:
        t = "action_register"
        if a["issue"] == "ALL":
            issue, basis = "All issues", "Phase 8 governance; applies to every Phase 6 driver"
        else:
            iss = ctx.issues[a["issue"]]
            issue = iss["title"]
            basis = f"{ctx.evidence(iss['drivers'])} ({MATRIX})"
        rows.append({"action_id": a["id"], "issue_id": a["issue"], "issue": issue,
                     "decision_category": a["category"], "action_type": a["type"],
                     "action": ctx.r(a["action"], t), "why": ctx.r(a["why"], t), "evidence_basis": basis,
                     "proposed_owner": proposed(a["owner"]), "supporting_teams": proposed(a["supporting"]),
                     "kpi": ctx.r(a["kpi"], t), "trigger": ctx.r(a["trigger"], t), "timing_window_days": a["window"],
                     "effort": a["effort"], "reversibility": a["reversibility"], "status": "Proposed"})
    return pd.DataFrame(rows)


def plan(ctx: Context) -> pd.DataFrame:
    rows = []
    for p in ctx.a["plan"]:
        rows.append({"window_days": p["window"], "focus": p["focus"], "activity": ctx.r(p["activity"], "plan"),
                     "issues": ", ".join(p["issues"]), "actions": ", ".join(p["actions"]),
                     "deliverable": p["deliverable"], "proposed_owner": proposed(p["owner"]),
                     "revenue_recovery_promised": "No"})
    return pd.DataFrame(rows)


def kpis(ctx: Context) -> pd.DataFrame:
    rows = []
    for k in ctx.a["kpis"]:
        t = "kpis"
        rows.append({"kpi_id": k["id"], "kpi": k["kpi"], "definition": k["definition"], "business_purpose": k["purpose"],
                     "proposed_owner": proposed(k["owner"]), "frequency": k["frequency"],
                     "threshold_concept": ctx.r(k["threshold"], t), "data_source": k["source"],
                     "current_availability": yn(k["availability"]), "exists_in_project": yn(k["exists"]),
                     "value_h2_2025": ctx.r(k["value_cy"], t), "value_h2_2024": ctx.r(k["value_py"], t),
                     "threshold_calibrated": "No", "issues": ", ".join(k["issues"])})
    return pd.DataFrame(rows)


def data_requirements(ctx: Context) -> pd.DataFrame:
    prio = {"0-30": "High", "31-60": "Medium", "61-90": "Low", "90+": "Low"}
    rows = []
    for d in ctx.a["data_requirements"]:
        t = "data_requirements"
        rows.append({"data_id": d["id"], "data_item": d["item"], "detail": ctx.r(d["detail"], t),
                     "question_it_answers": d["question"], "issues": ", ".join(d["issues"]),
                     "typical_source": d["source"], "proposed_owner": proposed(d["owner"]),
                     "available_in_project": yn(d["available_in_project"]), "availability_note": d.get("available_note", ""),
                     "needed_by_days": d["needed_by"], "priority": prio[d["needed_by"]]})
    return pd.DataFrame(rows)


def early_warning(ctx: Context) -> pd.DataFrame:
    rows = []
    for e in ctx.a["early_warning"]:
        t = "early_warning"
        rows.append({"signal_id": e["id"], "signal": e["signal"], "metric": ctx.r(e["metric"], t), "grain": e["grain"],
                     "baseline_concept": ctx.r(e["baseline"], t), "threshold_concept": ctx.r(e["threshold"], t),
                     "monitoring_frequency": e["frequency"], "proposed_owner": proposed(e["owner"]),
                     "alert_recipient": proposed(e["recipient"]), "required_response": ctx.r(e["response"], t),
                     "data_available_now": yn(e["data_now"]), "calibration_status": "Not calibrated: concept only",
                     "motivated_by": e["motivated_by"]})
    return pd.DataFrame(rows)


def evidence_to_action(ctx: Context) -> pd.DataFrame:
    rows = []
    for e in ctx.a["evidence_to_action"]:
        t = "evidence_to_action"
        drv = e["driver"]
        level = e["tag"] if drv is None else f"{e['tag']}; Phase 6 {drv}: {ctx.level[drv]}"
        rows.append({"id": e["id"], "finding": ctx.r(e["finding"], t), "evidence_level": level,
                     "phase6_driver": drv or "", "business_interpretation": ctx.r(e["interpretation"], t),
                     "permitted_conclusion": ctx.r(e["permitted"], t),
                     "not_permitted_conclusion": ctx.r(e["not_permitted"], t),
                     "recommended_next_step": ctx.r(e["next_step"], t)})
    return pd.DataFrame(rows)


DECISION_LOG_COLUMNS = ["decision_id", "date", "issue", "evidence_reviewed", "evidence_level", "decision", "owner",
                        "expected_outcome", "kpi", "review_date", "status", "result", "learning"]


def decision_log(ctx: Context) -> pd.DataFrame:
    rows = []
    for d in ctx.a["decision_log"]:
        issue = "All issues" if d["issue"] == "ALL" else f"{d['issue']} {ctx.issues[d['issue']]['title']}"
        level = "n/a (governance)" if d["driver"] is None else ctx.level[d["driver"]]
        rows.append({"decision_id": d["id"], "date": "", "issue": issue, "evidence_reviewed": d["evidence"],
                     "evidence_level": level, "decision": d["decision"], "owner": proposed(d["owner"]),
                     "expected_outcome": d["expected"], "kpi": d["kpi"],
                     "review_date": d["review"] if "after approval" in d["review"] else f"{d['review']} after approval", "status": "Proposed", "result": "", "learning": ""})
    return pd.DataFrame(rows, columns=DECISION_LOG_COLUMNS)


def impact(ctx: Context) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for x in ctx.a["impact"]:
        t = "impact"
        rows.append({"issue_id": x["issue"], "issue": ctx.issues[x["issue"]]["title"],
                     "observed_historical_impact": ctx.r(x["observed"], t),
                     "estimated_historical_impact": ctx.r(x["estimated"], t),
                     "potential_recoverable_value": x["recoverable"], "why": ctx.r(x["recoverable_reason"], t),
                     "is_forecast": "No"})
    sc = []
    for s in ctx.a["scenarios"]["rows"]:
        t = "scenarios"
        sc.append({"issue_id": s["issue"], "scenario": s["scenario"], "illustrative_value_h2_2025": ctx.r(s["value"], t),
                   "assumptions": ctx.r(s["assumption"], t), "basis": s["basis"],
                   "is_forecast": "No", "is_target": "No",
                   "label": "SCENARIO: restatement of the H2 2025 estimate under stated assumptions, not a forecast"})
    return pd.DataFrame(rows), pd.DataFrame(sc)


def frameworks(ctx: Context) -> pd.DataFrame:
    fw = ctx.a["frameworks"]
    rows = []
    t = "frameworks"
    for s in fw["cluster_sequence"]["steps"]:
        rows.append({"framework": "I1 cluster investigation sequence", "item": f"Step {s['step']}: {s['question']}",
                     "field_1": ctx.r(s["supports"], t), "field_2": ctx.r(s["otherwise"], t),
                     "data": ", ".join(s["data"])})
    for s in fw["inventory_checks"]["rows"]:
        rows.append({"framework": "I2/I3 inventory investigation", "item": f"{s['check']}: {s['question']}",
                     "field_1": "Points to supply: " + s["supply"], "field_2": "Points to ordering: " + s["ordering"],
                     "data": s["data"]})
    for s in fw["returns_classification"]["rows"]:
        rows.append({"framework": "I4 'Faulty' returns classification", "item": s["explanation"],
                     "field_1": "Evidence for: " + ctx.r(s["evidence_for"], t),
                     "field_2": "Evidence against: " + ctx.r(s["evidence_against"], t),
                     "data": s["data"]})
    for s in fw["promotion_framework"]["rows"]:
        rows.append({"framework": "I5 promotion decision framework", "item": f"{s['topic']}: {s['question']}",
                     "field_1": "Now: " + ctx.r(s["now"], t), "field_2": "Measure: " + s["measure"], "data": ""})
    for s in fw["test_design"]["items"]:
        rows.append({"framework": "I5 controlled depth test design", "item": ctx.r(s, t), "field_1": "", "field_2": "", "data": ""})
    for s in fw["residual_dimensions"]["rows"]:
        rows.append({"framework": "I7 residual investigation", "item": s["dimension"], "field_1": s["check"],
                     "field_2": "", "data": s["data"]})
    return pd.DataFrame(rows)


def build(cfg: dict, F: Facts) -> tuple[dict, Context]:
    ctx = Context(cfg, F)
    prio = prioritisation(ctx)
    imp, scen = impact(ctx)
    tables = {
        "prioritisation": prio,
        "decision_framework": decision_framework(ctx, prio),
        "action_register": action_register(ctx),
        "plan": plan(ctx),
        "kpis": kpis(ctx),
        "data_requirements": data_requirements(ctx),
        "early_warning": early_warning(ctx),
        "evidence_to_action": evidence_to_action(ctx),
        "decision_log": decision_log(ctx),
        "impact": imp,
        "scenarios": scen,
        "frameworks": frameworks(ctx),
    }
    return tables, ctx
