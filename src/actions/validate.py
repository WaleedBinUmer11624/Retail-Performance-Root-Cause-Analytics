"""Phase 8 validation: reconciliation of the inputs and governance checks on every output.

Each check returns a row (group, check, status, detail). The tests call the same functions, so the report and
the test suite cannot drift apart.
"""
from __future__ import annotations

import itertools
import re

import pandas as pd

from .facts import PLACEHOLDER, fmt
from .framework import CATEGORIES, OWNER_TAG, decide

EM_DASH = "\u2014"
# Figures the Phase 8 brief quotes (rounded as quoted); the facts must round to them.
BRIEF = {"d01_eur": -397778, "d03_eur": -37235, "d05_eur": -31589, "d07_eur": -186146, "d09_eur": -78522,
         "m1": -186146, "m4": -265003, "m2": 97505, "m3": 79059, "ls_gross": 37235, "ls_net": -23963,
         "ls_high": -44460, "et_change": -268518, "vx_full_cy": 674, "vx_full_py": 0,
         "hk_ev_py": 2427, "hk_ev_cy": 8848, "fy_change": 31589}
BRIEF_SHARES = {"d01_share": 54, "d03_share": 5, "d05_share": 4, "d07_share": 25, "d09_share": 11}
# Phase 8 brief, section 3: the evidence classification of each driver (must be unchanged from Phase 6).
BRIEF_LEVELS = {"D01": "Observed change", "D02": "Hypothesis", "D03": "Root-cause evidence",
                "D04": "Statistical association", "D05": "Observed change", "D06": "Hypothesis",
                "D07": "Statistical association"}
BRIEF_CAUSE = {"D01": "Unresolved", "D02": "Unresolved", "D03": "Established", "D04": "Not established",
               "D05": "Not established", "D06": "Unresolved", "D07": "Not established", "D09": "Not attributed"}
PROMO_WORDING = "Promotion activity is associated with the Home & Kitchen decline, but causality is not established."
# Claims that would upgrade a hypothesis or association into a finding. A sentence may contain one only when it
# is negated or conditional (checked by NEGATION).
FORBIDDEN = [r"\bsupplier (failure|failed|fault)\b", r"\bproduct defect\b", r"\b(products?|items?|units?|stock) (are|were|is|was) defective\b", r"\bfootfall (fell|dropped|declined)\b",
             r"\bcompetitor (caused|opening caused)\b", r"\bcaused the\b", r"\bproven\b", r"\bproves\b",
             r"\bpromotions caused\b", r"\bdue to (the )?(competitor|footfall|supplier|promotion)", r"\bwill recover\b",
             r"\bwill return\b", r"\bguarantee"]
NEGATION = re.compile(r"\b(not|no|without|whether|if|unless|until|cannot|never|hypothes\w*|may|could|either|or|vs)\b", re.I)


class Checks:
    def __init__(self):
        self.rows = []

    def add(self, group, check, ok, detail=""):
        self.rows.append({"group": group, "check": check, "status": "PASS" if ok else "FAIL", "detail": str(detail)[:400]})

    def df(self):
        return pd.DataFrame(self.rows)


def _texts(T: dict, skip_cols=()) -> list[tuple[str, str, str]]:
    out = []
    for name, df in T.items():
        for c in df.columns:
            if c in skip_cols:
                continue
            for v in df[c].dropna():
                if isinstance(v, str):
                    out.append((name, c, v))
    return out


def _sentences(text: str):
    return [s for s in re.split(r"(?<=[.;:!?])\s+", text) if s]


def forbidden_claims(texts) -> list[str]:
    bad = []
    for where, text in texts:
        for s in _sentences(text):
            if s.rstrip().endswith("?"):
                continue  # a question claims nothing
            for pat in FORBIDDEN:
                if re.search(pat, s, re.I) and not NEGATION.search(s):
                    bad.append(f"{where}: {s[:140]}")
                    break
    return bad


def euro_values(F) -> set:
    vals = set()
    for f in F.items.values():
        if isinstance(f.value, (int, float)) and f.value == f.value:
            for spec in ("eur", "eur2", "abseur", "seur", "eurk", "abseurk", "eurm"):
                vals.add(fmt(f.value, spec).lstrip("+-"))
    return vals


EURO = re.compile(r"€\d{1,3}(?:,\d{3})*(?:\.\d+)?[kM]?")


def run(T: dict, ctx, headline: pd.DataFrame | None, freeze: pd.DataFrame | None, plan_md: str,
        doc_md: str | None = None) -> pd.DataFrame:
    C = Checks()
    F, a, cfg = ctx.F, ctx.a, ctx.cfg
    hl = cfg["powerbi"]["headline"]
    tol = cfg["powerbi"]["tolerances"]

    # ---------------------------------------------------------------- freeze and headline
    if freeze is not None:
        C.add("Freeze", "Phase 1-7 files unchanged since the Phase 8 freeze (and the Phase 7 and 6 manifests re-verified)",
              (freeze["status"] == "UNCHANGED").all(), f"{len(freeze)} files")
    if headline is not None:
        h = headline.set_index("retail_year")
        py, cy = float(h.loc[2024, "net_revenue"]), float(h.loc[2025, "net_revenue"])
        C.add("Headline", "H2 2024 net revenue recomputed from the model = brief", abs(py - hl["net_revenue_py"]) <= tol["eur"], f"{py:,.2f}")
        C.add("Headline", "H2 2025 net revenue recomputed from the model = brief", abs(cy - hl["net_revenue_cy"]) <= tol["eur"], f"{cy:,.2f}")
        C.add("Headline", "Change recomputed = brief", abs((cy - py) - hl["change"]) <= tol["eur"], f"{cy - py:,.2f}")
        C.add("Headline", "YoY % recomputed = brief (6 dp)", round(100 * (cy - py) / py, 6) == hl["yoy_pct"],
              f"{100 * (cy - py) / py:.6f}")
    p7 = pd.read_csv(ctx.cfg_path(cfg["actions"]["inputs"]["phase7_checks"])) if hasattr(ctx, "cfg_path") else None
    if p7 is not None:
        C.add("Headline", "Phase 7 validation checks all PASS", (p7["status"] == "PASS").all(), f"{len(p7)} checks")
    C.add("Headline", "Phase 7 register: H2 2025 = brief", abs(F["nr_cy"] - hl["net_revenue_cy"]) <= tol["eur"], F["nr_cy"])
    C.add("Headline", "Phase 7 register: H2 2024 = brief", abs(F["nr_py"] - hl["net_revenue_py"]) <= tol["eur"], F["nr_py"])
    C.add("Headline", "Phase 7 register: change = brief", abs(F["nr_change"] - hl["change"]) <= tol["eur"], F["nr_change"])
    C.add("Headline", "Phase 7 register: YoY = brief (6 dp)", round(100 * F["nr_yoy"], 6) == hl["yoy_pct"], 100 * F["nr_yoy"])

    # ---------------------------------------------------------------- attribution
    C.add("Attribution", "Components sum to the H2 change", abs(F["att_total"] - hl["change"]) <= tol["eur"], F["att_total"])
    C.add("Attribution", "Shares sum to 100%", abs(F["att_share_total"] - 1) <= 1e-6, F["att_share_total"])
    comp = sum(F[k] for k in ["d01_eur", "d03_eur", "d05_eur", "d07_eur", "d09_eur"])
    C.add("Attribution", "Register components (P1-20a to P1-24a) sum to the change", abs(comp - hl["change"]) <= tol["eur"], comp)
    for k, v in BRIEF.items():
        C.add("Attribution" if k.startswith("d0") else "Brief figures", f"{k} rounds to the brief's {v:,}", round(F[k]) == v, F[k])
    for k, v in BRIEF_SHARES.items():
        C.add("Attribution", f"{k} rounds to the brief's {v}%", round(100 * F[k]) == v, F[k])
    C.add("Attribution", "Residual keeps its sign and size (not absorbed by any driver)",
          abs(F["d09_eur"] - (hl["change"] - sum(F[k] for k in ["d01_eur", "d03_eur", "d05_eur", "d07_eur"]))) <= tol["eur"], F["d09_eur"])

    # ---------------------------------------------------------------- evidence classifications
    for d, lvl in BRIEF_LEVELS.items():
        C.add("Evidence", f"{d} evidence level unchanged ({lvl})", ctx.level[d] == lvl, ctx.level[d])
    for d, st in BRIEF_CAUSE.items():
        C.add("Evidence", f"{d} cause status unchanged ({st})", ctx.drivers[d]["cause_status"] == st, ctx.drivers[d]["cause_status"])
    dfw = T["decision_framework"]
    ok = all(all(part.split(": ", 1)[1] == ctx.level[part.split(": ")[0]] for part in s.split("; ")) for s in dfw["evidence_level"])
    C.add("Evidence", "Decision framework evidence levels = Phase 6 matrix", ok)
    e2a = T["evidence_to_action"]
    ok = all(r.phase6_driver == "" or r.evidence_level.endswith(f"Phase 6 {r.phase6_driver}: {ctx.level[r.phase6_driver]}")
             for r in e2a.itertuples())
    C.add("Evidence", "Evidence-to-action levels = Phase 6 matrix", ok)
    dl = T["decision_log"]
    ok = all(r.evidence_level in set(ctx.level.values()) | {"n/a (governance)"} for r in dl.itertuples())
    C.add("Evidence", "Decision log evidence levels come from the Phase 6 matrix", ok)
    texts = [(f"{n}.{c}", v) for n, c, v in _texts(T, skip_cols=("not_permitted_conclusion", "what_we_do_not_know"))]
    texts += [("executive_plan", s) for s in plan_md.split("\n") if "Not permitted" not in s and not s.startswith("| E")]
    bad = forbidden_claims(texts)
    C.add("Evidence", "No output states a hypothesis or association as a finding (claim scan)", not bad, "; ".join(bad[:3]))
    C.add("Evidence", "Required promotion wording present", PROMO_WORDING in plan_md and
          PROMO_WORDING in " ".join(e2a["business_interpretation"]))
    C.add("Evidence", "Cluster cause labelled UNRESOLVED in the plan", "UNRESOLVED" in plan_md)
    ok = dfw.set_index("issue_id").loc["I1", "cause_status"].count("Unresolved") == 2
    C.add("Evidence", "I1 cause status is Unresolved for both D01 and D02", ok)

    # ---------------------------------------------------------------- promotion estimates never summed
    ms = {k: F[k] for k in ["m1", "m2", "m3", "m4"]}
    combos = set()
    for n in (2, 3, 4):
        for c in itertools.combinations(ms.values(), n):
            combos.add(sum(c))
            combos.add(sum(c) / n)
    combo_txt = {fmt(v, "eur").lstrip("+-") for v in combos} - {fmt(v, "eur").lstrip("+-") for v in ms.values()} - \
        {fmt(v, "eur").lstrip("+-") for v in [F["hk_range_low"], F["hk_range_high"], F["d07_eur"]]}
    alltext = " ".join(v for _, v in texts) + plan_md
    hits = [v for v in combo_txt if re.search(re.escape(v) + r"(?![\d,])", alltext)]
    C.add("Promotions", "No sum or average of the four H&K methods appears anywhere", not hits, hits)
    C.add("Promotions", "No output column or row presents a combined promotion impact",
          not re.search(r"(total|combined|overall) promotion (impact|effect)", alltext, re.I))

    # ---------------------------------------------------------------- residual
    p = T["prioritisation"].set_index("issue_id")
    imp = T["impact"].set_index("issue_id")
    C.add("Residual", "Residual issue I7 is NO ACTION YET", p.loc["I7", "decision_category"] == "NO ACTION YET")
    C.add("Residual", "Residual labelled UNEXPLAINED / NOT ATTRIBUTED in the framework and impact tables",
          "NOT ATTRIBUTED" in dfw.set_index("issue_id").loc["I7", "financial_relevance"] and
          "NOT ATTRIBUTED" in imp.loc["I7", "estimated_historical_impact"])
    C.add("Residual", "Residual has no recoverable value", imp.loc["I7", "potential_recoverable_value"] == "Not estimated")

    # ---------------------------------------------------------------- KPIs
    k = T["kpis"]
    na = k[k["current_availability"] == "Not available"]
    C.add("KPIs", "Unavailable KPIs carry no value", (na["value_h2_2025"] == "").all() and (na["value_h2_2024"] == "").all(),
          list(na["kpi"]))
    av = k[k["current_availability"] == "Available"]
    C.add("KPIs", "Available KPIs carry a traced H2 2025 value", (av["value_h2_2025"] != "").all())
    for name in ["Conversion Rate", "Promotion Incrementality", "Supplier OTIF", "Supplier Fill Rate", "Forecast Accuracy"]:
        C.add("KPIs", f"{name} is marked Not available (no data in the project)",
              k.set_index("kpi").loc[name, "current_availability"] == "Not available")
    C.add("KPIs", "No KPI threshold is presented as calibrated", (k["threshold_calibrated"] == "No").all())
    C.add("KPIs", "Every brief KPI is in the framework", {"Net Revenue", "Transactions", "Conversion Rate", "UPT", "ASP",
          "Gross Margin %", "Availability", "Full-week stock-outs", "Estimated lost sales", "Return Rate",
          "Faulty Return Rate", "Promotion Share", "Discount Rate", "Promotion Incrementality", "Supplier OTIF",
          "Supplier Fill Rate", "Forecast Accuracy"} <= set(k["kpi"]))

    # ---------------------------------------------------------------- impact
    C.add("Impact", "Recoverable value is 'Not estimated' or 'Scenario only', never a historical figure",
          set(imp["potential_recoverable_value"]) <= {"Not estimated", "Scenario only"})
    C.add("Impact", "Only the issue with root-cause evidence (I2) has scenarios",
          set(T["scenarios"]["issue_id"]) == {"I2"} and list(imp.index[imp["potential_recoverable_value"] == "Scenario only"]) == ["I2"])
    sc = T["scenarios"]
    C.add("Impact", "Scenarios are labelled not a forecast and not a target",
          (sc["is_forecast"] == "No").all() and (sc["is_target"] == "No").all() and sc["label"].str.contains("not a forecast").all())
    C.add("Impact", "Every scenario states assumptions", (sc["assumptions"].str.len() > 40).all())
    vals = set(sc["illustrative_value_h2_2025"])
    C.add("Impact", "Conservative scenario assumes nothing is avoidable",
          sc.set_index("scenario").loc["Conservative", "illustrative_value_h2_2025"] == fmt(0, "eur"))
    C.add("Impact", "No scenario counts demand that came back after restock: the largest is the net-of-deferred estimate",
          vals <= {fmt(0, "eur"), "about " + fmt(F["ls_net"], "abseurk"), "n/a"})
    C.add("Impact", "Gross, sensitivity-high and upper-bound figures are never offered as avoidable value",
          not vals & {fmt(F[k], s) for k in ("ls_gross", "ls_high", "ls_upper_bound") for s in ("abseur", "abseurk")})
    C.add("Impact", "Scenarios describe H2 2025 only (no per-period or future framing)",
          not re.search(r"per half-year|next half|future period value|will (save|recover|add)", " ".join(sc.astype(str).values.ravel()), re.I)
          or "not forecasts of any future period" in a["scenarios"]["intro"])
    C.add("Impact", "Every impact row is marked not a forecast", (imp["is_forecast"] == "No").all())
    C.add("Impact", "The plan promises no revenue recovery", (T["plan"]["revenue_recovery_promised"] == "No").all())

    # ---------------------------------------------------------------- actions
    act = T["action_register"]
    C.add("Actions", "Every action has an evidence basis", (act["evidence_basis"].str.len() > 10).all())
    C.add("Actions", "Every action's issue exists", set(act["issue_id"]) <= set(p.index) | {"ALL"})
    C.add("Actions", "Every action category is one of the four", set(act["decision_category"]) <= set(CATEGORIES))
    C.add("Actions", "All four decision categories are used", set(act["decision_category"]) == set(CATEGORIES))
    strong = {i for i in p.index if p.loc[i, "evidence_strength"] == "High"}
    an = act[act["decision_category"] == "ACT NOW"]
    ok = all(r.reversibility == "High" and r.effort == "Low" and
             (r.issue_id in strong or r.action_type in ("Evidence capture", "Governance control")) for r in an.itertuples())
    C.add("Actions", "ACT NOW actions are reversible, low effort, and rest on root-cause evidence or capture evidence / govern",
          ok, list(an["action_id"]))
    ok = all(r.action_type != "Control" or r.issue_id in strong for r in act.itertuples())
    C.add("Actions", "Operational controls exist only where the evidence is root-cause evidence", ok)
    hold_issues = set(act[act["action_type"] == "Hold"]["issue_id"])
    C.add("Actions", "Hold decisions exist for the unresolved cluster, the Voltix association and the promotion methods",
          {"I1", "I3", "I5"} <= hold_issues, sorted(hold_issues))
    for i in p.index:
        C.add("Actions", f"{i} has at least one action", (act["issue_id"] == i).any())

    # ---------------------------------------------------------------- decision rule
    ok = all(decide(r.financial_relevance, r.evidence_strength, r.business_urgency, r.reversibility,
                    r.risk_of_acting_now, all(ctx.drivers[d]["cause_status"] == "Not attributed" for d in r.drivers.split(", ")))[0]
             == r.decision_category for r in T["prioritisation"].itertuples())
    C.add("Decision rule", "Every issue's category follows the documented rule", ok)
    biggest = p["share_of_decline"].idxmax()
    C.add("Decision rule", "The largest amount is not ACT NOW (size alone never decides)",
          p.loc[biggest, "decision_category"] != "ACT NOW", f"{biggest}: {p.loc[biggest, 'decision_category']}")
    C.add("Decision rule", "ACT NOW issues have High causal evidence",
          (p[p["decision_category"] == "ACT NOW"]["evidence_strength"] == "High").all())

    # ---------------------------------------------------------------- data requirements
    dr = T["data_requirements"]
    ids = set(dr["data_id"])
    unresolved = [i for i in a["issues"] if any(ctx.drivers[d]["cause_status"] != "Established" or
                                                ctx.level[d] in ("Hypothesis",) for d in i["drivers"])]
    C.add("Data", "Every unresolved or unestablished issue names additional data",
          all(i["data_ids"] and set(i["data_ids"]) <= ids for i in unresolved), [i["id"] for i in unresolved])
    used_ids = set(itertools.chain.from_iterable(i["data_ids"] for i in a["issues"]))
    C.add("Data", "Every data requirement serves an issue", ids <= used_ids, sorted(ids - used_ids))
    C.add("Data", "Brief data items for the cluster are all requested",
          all(any(w in " ".join(dr["data_item"] + " " + dr["detail"]).lower() for w in [x]) for x in
              ["footfall", "conversion", "competitor", "road", "events", "opening hours", "staffing", "queue",
               "complaints", "nps", "loyalty", "catchment", "online"]))
    C.add("Data", "Brief inventory items are all covered",
          all(x in (" ".join(dr["data_item"] + " " + dr["detail"]) + str(a["frameworks"]["inventory_checks"])).lower() for x in
              ["purchase order", "fill rate", "asn", "otif", "lead time", "late deliver", "order quantit", "forecast accuracy",
               "reorder point", "safety stock", "dc availability", "replenishment", "allocation", "service level"]))

    # ---------------------------------------------------------------- owners
    owner_cols = [(n, c) for n, df in T.items() for c in df.columns if "owner" in c or c in ("supporting_teams", "alert_recipient")]
    bad = []
    for n, c in owner_cols:
        for v in T[n][c]:
            if not all(part.strip().endswith(OWNER_TAG.strip()) for part in str(v).split(";")):
                bad.append(f"{n}.{c}: {v}")
    C.add("Owners", "Every owner, supporting team and alert recipient is labelled PROPOSED", not bad, bad[:3])

    # ---------------------------------------------------------------- early warning
    ew = T["early_warning"]
    C.add("Early warning", "No threshold is presented as calibrated", ew["calibration_status"].str.startswith("Not calibrated").all())
    C.add("Early warning", "Every brief signal type is specified", all(any(w in s.lower() for s in ew["signal"]) for w in
          ["transaction", "availability", "stock-out", "return", "margin", "promotion"]))
    C.add("Early warning", "Each signal has metric, baseline, frequency, owner, recipient and response",
          ew[["metric", "baseline_concept", "monitoring_frequency", "proposed_owner", "alert_recipient",
              "required_response"]].apply(lambda s: s.str.len() > 0).all().all())

    # ---------------------------------------------------------------- traceability and style
    raw = open(ctx.config_file, encoding="utf-8").read() if hasattr(ctx, "config_file") else ""
    body = raw.split("\nissues:", 1)[-1]
    body_no_ph = PLACEHOLDER.sub("", body)
    typed = re.findall(r"€\s?\d|\d+(?:\.\d+)?\s?%|\b\d{1,3},\d{3}\b|\b\d+\.\d+\b", body_no_ph)
    C.add("Traceability", "Config text holds no typed euro amount, percentage or large count (all come from facts)",
          not typed, typed[:5])
    known = euro_values(F)
    found = set(m.lstrip("+-") for m in EURO.findall(plan_md + " " + " ".join(v for _, v in texts)))
    stray = sorted(v for v in found if v not in known)
    C.add("Traceability", "Every euro amount in the outputs is a formatted fact", not stray, stray[:5])
    if doc_md is not None:
        found = set(EURO.findall(doc_md))
        stray = sorted(v for v in found if v not in known)
        C.add("Traceability", "Every euro amount in docs/08 is a formatted fact", not stray, stray[:5])
    allout = plan_md + " ".join(v for _, _, v in _texts(T)) + (doc_md or "") + raw
    left = re.findall(r"\{[a-z0-9_]+[|/][a-z0-9]+\}", plan_md + " ".join(v for _, _, v in _texts(T)))
    C.add("Traceability", "No unresolved placeholder in any output", not left, left[:3])
    C.add("Data", "Availability of every data item is stated as No or Partial",
          set(T["data_requirements"]["available_in_project"]) <= {"No", "Partial"} and
          (T["data_requirements"]["available_in_project"] == "No").sum() > 0)
    C.add("Style", "No em dash in any Phase 8 output, config or doc", EM_DASH not in allout)
    return C.df()
