"""Phase 8 tests: business action plan, decision support and impact framework.

The session fixture runs Phase 8 once (DuckDB engine: the Phase 4 model is rebuilt for the headline check,
about 20 seconds) into a temporary folder. The tests check the Phase 8 brief's requirements on the fresh outputs,
independently of the validation module where that is practical, and check that the committed outputs in
reports/phase8/ are identical to a fresh run.
"""
from __future__ import annotations

import itertools
import re
from pathlib import Path

import pandas as pd
import pytest

from src.actions import access as AC
from src.actions import facts as FC
from src.actions import framework as FW
from src.actions import run_phase8
from src.actions import validate as VA
from src.analytics.model_access import PROJECT_ROOT, InputError

ROOT = PROJECT_ROOT
BRIEF_FILES = ["phase8_executive_action_plan.md", "phase8_action_register.csv", "phase8_30_60_90_plan.csv",
               "phase8_kpi_monitoring_framework.csv", "phase8_evidence_to_action_matrix.csv",
               "phase8_decision_log_template.csv", "phase8_data_requirements.csv",
               "phase8_early_warning_requirements.csv"]
DOC = ROOT / "docs" / "08_business_action_and_decision_framework.md"


@pytest.fixture(scope="session")
def phase8(tmp_path_factory):
    if not (ROOT / "reports" / "phase8" / "phase1_7_input_manifest.csv").exists():
        pytest.skip("Phase 8 freeze manifest not recorded")
    out = tmp_path_factory.mktemp("phase8_reports")
    try:
        res = run_phase8.run("duckdb", out_dir=out)
    except InputError as e:  # curated data not generated in this checkout
        pytest.skip(f"Phase 8 inputs unavailable: {e}")
    return res


def _csv(res, name):
    return pd.read_csv(res["out"] / name, keep_default_na=False)


def _all_text(res) -> str:
    out = res["out"]
    parts = [(out / f).read_text(encoding="utf-8") for f in BRIEF_FILES]
    parts += [p.read_text(encoding="utf-8") for p in out.glob("phase8_*.csv") if "validation" not in p.name
              and "fact_register" not in p.name]
    return "\n".join(parts)


# ----------------------------------------------------------------------------- run, freeze, headline
def test_run_passes(phase8):
    c = phase8["checks"]
    assert phase8["passed"], c[c["status"] != "PASS"].to_string()


def test_every_validation_check_passes(phase8):
    c = phase8["checks"]
    bad = c[c["status"] != "PASS"]
    assert len(c) >= 100
    assert bad.empty, "\n".join(f"{r.group}: {r.check} ({r.detail})" for r in bad.itertuples())


def test_brief_deliverables_exist(phase8):
    for f in BRIEF_FILES:
        assert (phase8["out"] / f).exists(), f
    assert DOC.exists()


def test_freeze_covers_phase1_to_7(phase8):
    f = phase8["freeze"]
    assert len(f) >= 289 and (f["status"] == "UNCHANGED").all()
    files = set(f["file"])
    for must in ["reports/phase6/driver_attribution.csv", "reports/phase7/dashboard_number_register.csv",
                 "docs/07_power_bi_dashboard_design.md", "src/powerbi/dax.py", "powerbi/dax/measures.dax",
                 "reports/phase5/headline_kpis.csv", "sql/powerbi/01_powerbi_views.sql"]:
        assert must in files, must
    assert not any("phase7_validation_report" in x or "run_log" in x for x in files)


def test_freeze_detects_a_changed_file(monkeypatch):
    cfg = AC.load_config()
    target = "reports/phase6/driver_attribution.csv"
    real = AC.sha256_normalised
    # Path.as_posix() keeps this platform-independent: str(Path) uses backslashes on Windows, so a
    # str-based suffix test never matches there and the fake hash is silently never substituted.
    monkeypatch.setattr(AC, "sha256_normalised",
                        lambda p: "0" * 64 if Path(p).as_posix().endswith(target) else real(p))
    with pytest.raises(InputError, match="changed since the Phase 8 freeze"):
        AC.verify_freeze(cfg)


def test_headline_recomputed_from_model(phase8):
    h = phase8["headline"].set_index("retail_year")
    assert round(h.loc[2024, "net_revenue"], 2) == 10188727.55
    assert round(h.loc[2025, "net_revenue"], 2) == 9457457.05
    change = h.loc[2025, "net_revenue"] - h.loc[2024, "net_revenue"]
    assert round(change, 2) == -731270.50
    assert round(100 * change / h.loc[2024, "net_revenue"], 6) == -7.177251


def test_phase7_checks_all_pass():
    p7 = pd.read_csv(ROOT / "reports" / "phase7" / "phase7_validation_checks.csv")
    assert (p7["status"] == "PASS").all()


# ----------------------------------------------------------------------------- attribution and evidence
def test_attribution_reconciles_independently():
    d = pd.read_csv(ROOT / "reports" / "phase6" / "driver_attribution.csv")
    assert abs(d["amount_eur"].sum() - (-731270.50)) < 0.01
    assert abs(d["share_of_change"].sum() - 1) < 1e-6
    assert [round(x) for x in d["amount_eur"]] == [-397778, -37235, -31589, -186146, -78522]


def test_evidence_levels_unchanged(phase8):
    m = pd.read_csv(ROOT / "reports" / "phase6" / "root_cause_evidence_matrix.csv").set_index("driver_id")
    for d, lvl in VA.BRIEF_LEVELS.items():
        assert m.loc[d, "evidence_level"] == lvl
    fw = _csv(phase8, "phase8_decision_framework.csv")
    for s in fw["evidence_level"]:
        for part in s.split("; "):
            d, lvl = part.split(": ", 1)
            assert m.loc[d, "evidence_level"] == lvl, part
    e2a = _csv(phase8, "phase8_evidence_to_action_matrix.csv")
    for r in e2a.itertuples():
        if r.phase6_driver:
            assert r.evidence_level.endswith(m.loc[r.phase6_driver, "evidence_level"])


def test_no_recommendation_upgrades_a_hypothesis(phase8):
    """Issues whose cause rests on a hypothesis or association never get ACT NOW or an operational control;
    the permitted conclusions for hypothesis and association rows say so."""
    prio = _csv(phase8, "phase8_prioritisation_matrix.csv").set_index("issue_id")
    act = _csv(phase8, "phase8_action_register.csv")
    for i in ["I1", "I3", "I4", "I5", "I6", "I7"]:
        assert prio.loc[i, "decision_category"] != "ACT NOW", i
        assert not ((act["issue_id"] == i) & (act["action_type"] == "Control")).any(), i
    e2a = _csv(phase8, "phase8_evidence_to_action_matrix.csv").set_index("id")
    for i in ["E04", "E08"]:
        assert "hypothes" in e2a.loc[i, "permitted_conclusion"].lower()
    assert "associated" in e2a.loc["E06", "permitted_conclusion"] and "associated" in e2a.loc["E10", "permitted_conclusion"]
    for i in ["E03", "E05", "E06", "E07", "E10"]:
        assert e2a.loc[i, "not_permitted_conclusion"], i
    assert "supplier failed" in e2a.loc["E05", "not_permitted_conclusion"] or "Supplier failure" in e2a.loc["E06", "not_permitted_conclusion"]


def test_claim_scan_catches_overstatement():
    bad = VA.forbidden_claims([("x", "The supplier failed to deliver."), ("x", "Promotions caused the decline.")])
    assert len(bad) == 2
    ok = VA.forbidden_claims([("x", "Whether the supplier failed is unknown."), ("x", "Are items defective?"),
                              ("x", "That promotions caused the category decline is not established.")])
    assert not ok


def test_required_wording(phase8):
    plan = (phase8["out"] / "phase8_executive_action_plan.md").read_text(encoding="utf-8")
    assert VA.PROMO_WORDING in plan
    assert "UNRESOLVED" in plan and "UNEXPLAINED / NOT ATTRIBUTED" in plan
    assert "Stock-out concentration is associated with Voltix SKUs." in plan


# ----------------------------------------------------------------------------- promotions, residual, impact
def test_promotion_estimates_never_summed(phase8):
    c = pd.read_csv(ROOT / "reports" / "phase6" / "hk_promotion_counterfactuals.csv")
    vals = {k: float(c[c["method"].str.startswith(k)].iloc[0]["effect_eur"]) for k in ["M1 category DiD (sales)", "M2", "M3", "M4"]}
    text = _all_text(phase8) + DOC.read_text(encoding="utf-8")
    singles = {f"{abs(v):,.0f}" for v in vals.values()}
    for n in (2, 3, 4):
        for combo in itertools.combinations(vals.values(), n):
            for v in (sum(combo), sum(combo) / n):
                s = f"{abs(v):,.0f}"
                if s in singles or s in {"380,272", "97,505"}:
                    continue
                assert not re.search(r"€" + re.escape(s) + r"(?![\d,])", text), f"combined promotion figure €{s} found"


def test_residual_stays_unattributed(phase8):
    prio = _csv(phase8, "phase8_prioritisation_matrix.csv").set_index("issue_id")
    imp = _csv(phase8, "phase8_impact_framework.csv").set_index("issue_id")
    fw = _csv(phase8, "phase8_decision_framework.csv").set_index("issue_id")
    assert prio.loc["I7", "decision_category"] == "NO ACTION YET"
    assert "NOT ATTRIBUTED" in fw.loc["I7", "financial_relevance"]
    assert imp.loc["I7", "potential_recoverable_value"] == "Not estimated"
    act = _csv(phase8, "phase8_action_register.csv")
    assert set(act[act["issue_id"] == "I7"]["action_type"]) == {"Analysis"}


def test_historical_impact_not_labelled_recoverable(phase8):
    imp = _csv(phase8, "phase8_impact_framework.csv")
    assert set(imp["potential_recoverable_value"]) <= {"Not estimated", "Scenario only"}
    assert list(imp[imp["potential_recoverable_value"] == "Scenario only"]["issue_id"]) == ["I2"]
    sc = _csv(phase8, "phase8_impact_scenarios.csv").set_index("scenario")
    assert sc.loc["Conservative", "illustrative_value_h2_2025"] == "€0"
    assert (sc["is_forecast"] == "No").all() and (sc["is_target"] == "No").all()
    # demand that came back after restock is already in H2 2025 revenue: only the net estimate can be avoidable
    lost = pd.read_csv(ROOT / "reports" / "phase6" / "sensitivity_analysis.csv")
    net = abs(lost[lost["variant"].str.contains("deferred demand", na=False)]["estimate_eur"].iloc[0])
    vals = set(sc["illustrative_value_h2_2025"])
    assert vals <= {"€0", f"about €{net / 1e3:,.0f}k", "n/a"}, vals
    for bad in ("€37,235", "€44,460", "€100,411", "€37k", "€44k", "€100k"):
        assert bad not in vals


def test_unavailable_kpis_have_no_values(phase8):
    k = _csv(phase8, "phase8_kpi_monitoring_framework.csv")
    na = k[k["current_availability"] == "Not available"]
    assert len(na) >= 7
    assert (na["value_h2_2025"] == "").all() and (na["value_h2_2024"] == "").all()
    assert (k["threshold_calibrated"] == "No").all()


def test_kpi_values_trace_to_phase7_register(phase8):
    reg = pd.read_csv(ROOT / "reports" / "phase7" / "dashboard_number_register.csv").set_index("id")
    k = _csv(phase8, "phase8_kpi_monitoring_framework.csv").set_index("kpi")
    assert k.loc["Net Revenue", "value_h2_2025"] == f"€{float(reg.loc['P1-01', 'value']):,.2f}"
    assert k.loc["Discount Rate", "value_h2_2025"].startswith(f"{100 * float(reg.loc['P5-10', 'value']):.1f}%")
    assert k.loc["Availability", "value_h2_2024"].startswith(f"{100 * float(reg.loc['P3-07', 'value']):.1f}%")


# ----------------------------------------------------------------------------- actions, data, owners
def test_every_action_has_an_evidence_basis(phase8):
    act = _csv(phase8, "phase8_action_register.csv")
    m = pd.read_csv(ROOT / "reports" / "phase6" / "root_cause_evidence_matrix.csv")
    levels = set(m["evidence_level"])
    for r in act.itertuples():
        assert r.evidence_basis, r.action_id
        assert r.issue_id == "ALL" or any(l in r.evidence_basis for l in levels), r.action_id
    now = act[act["decision_category"] == "ACT NOW"]
    assert (now["reversibility"] == "High").all() and (now["effort"] == "Low").all()


def test_every_unresolved_issue_names_data(phase8):
    fw = _csv(phase8, "phase8_decision_framework.csv")
    dr = set(_csv(phase8, "phase8_data_requirements.csv")["data_id"])
    for r in fw.itertuples():
        if any(s in r.cause_status for s in ("Unresolved", "Not established", "Not attributed")):
            ids = re.findall(r"DR\d\d", r.additional_data_required)
            assert ids and set(ids) <= dr, r.issue_id


def test_owners_labelled_proposed(phase8):
    for f in ["phase8_action_register.csv", "phase8_30_60_90_plan.csv", "phase8_kpi_monitoring_framework.csv",
              "phase8_data_requirements.csv", "phase8_early_warning_requirements.csv", "phase8_decision_log_template.csv",
              "phase8_decision_framework.csv"]:
        df = _csv(phase8, f)
        for c in [c for c in df.columns if "owner" in c or c in ("supporting_teams", "alert_recipient")]:
            for v in df[c]:
                for part in v.split(";"):
                    assert part.strip().endswith("(PROPOSED)"), f"{f}.{c}: {v}"


def test_decision_log_template_fields(phase8):
    dl = _csv(phase8, "phase8_decision_log_template.csv")
    assert list(dl.columns) == ["decision_id", "date", "issue", "evidence_reviewed", "evidence_level", "decision",
                                "owner", "expected_outcome", "kpi", "review_date", "status", "result", "learning"]
    assert (dl["date"] == "").all() and (dl["result"] == "").all() and (dl["learning"] == "").all()
    assert (dl["status"] == "Proposed").all()


def test_plan_windows_and_no_recovery_promise(phase8):
    p = _csv(phase8, "phase8_30_60_90_plan.csv")
    assert set(p["window_days"]) == {"0-30", "31-60", "61-90"}
    assert (p["revenue_recovery_promised"] == "No").all()
    text = " ".join(p["activity"]).lower()
    assert "recover" not in text or "no revenue recovery" in text


def test_early_warning_not_calibrated(phase8):
    ew = _csv(phase8, "phase8_early_warning_requirements.csv")
    assert ew["calibration_status"].str.startswith("Not calibrated").all()
    assert len(ew) >= 6


# ----------------------------------------------------------------------------- decision rule
def test_decision_rule_size_never_decides():
    assert FW.decide("High", "Low", "High", "High", "High", False)[0] == "INVESTIGATE FIRST"
    assert FW.decide("Low", "High", "Low", "High", "Low", False)[0] == "ACT NOW"
    assert FW.decide("High", "Medium", "Low", "High", "Low", False)[0] == "INVESTIGATE FIRST"
    assert FW.decide("Low", "Low", "Low", "High", "Medium", False)[0] == "MONITOR"
    assert FW.decide("High", "High", "High", "High", "Low", True)[0] == "NO ACTION YET"


def test_categories_follow_rule_and_largest_is_not_act_now(phase8):
    p = _csv(phase8, "phase8_prioritisation_matrix.csv")
    assert set(p["decision_category"]) == set(FW.CATEGORIES)
    big = p.loc[pd.to_numeric(p["share_of_decline"], errors="coerce").idxmax()]
    assert big["issue_id"] == "I1" and big["decision_category"] == "INVESTIGATE FIRST"
    assert list(p[p["decision_category"] == "ACT NOW"]["issue_id"]) == ["I2"]


# ----------------------------------------------------------------------------- traceability and reproducibility
def test_facts_rederive_from_sources():
    cfg = AC.load_config()
    F = FC.build(cfg)
    reg = pd.read_csv(ROOT / "reports" / "phase7" / "dashboard_number_register.csv").set_index("id")
    for key, rid in FC.REGISTER_FACTS.items():
        v = reg.loc[rid, "value"]
        try:
            assert abs(float(v) - float(F.items[key].value)) < 1e-9, key
        except ValueError:
            assert str(v) == str(F.items[key].value), key
    sens = pd.read_csv(ROOT / "reports" / "phase6" / "sensitivity_analysis.csv")
    net = sens[sens["variant"].str.contains("deferred demand", na=False)]["estimate_eur"].iloc[0]
    assert abs(net - F.items["ls_net"].value) < 1e-6
    res = pd.read_csv(ROOT / "reports" / "phase6" / "driver_residual_breakdown.csv")
    assert abs(res["amount_eur"].sum() - F.items["d09_eur"].value) < 0.01


def test_config_holds_no_typed_figures():
    raw = (ROOT / "config" / "action_config.yaml").read_text(encoding="utf-8").split("\nissues:", 1)[1]
    raw = FC.PLACEHOLDER.sub("", raw)
    assert not re.findall(r"€\s?\d|\d+(?:\.\d+)?\s?%|\b\d{1,3},\d{3}\b|\b\d+\.\d+\b", raw)


def test_config_rows_parse_cleanly():
    """A comma inside an unquoted YAML flow mapping silently splits a value into a new key."""
    import yaml
    d = yaml.safe_load((ROOT / "config" / "action_config.yaml").read_text(encoding="utf-8"))
    for sec in ["data_requirements", "actions", "plan", "kpis", "early_warning", "evidence_to_action", "decision_log", "impact"]:
        base = set.union(*[set(r) for r in d[sec]])
        for r in d[sec]:
            assert all(v is not None for k, v in r.items() if k != "driver"), (sec, r.get("id"))
        assert len(base) <= max(len(r) for r in d[sec]) + 1, (sec, base)


def test_committed_outputs_match_fresh_run(phase8):
    committed = ROOT / "reports" / "phase8"
    for f in sorted(p.name for p in phase8["out"].glob("phase8_*.csv")):
        if "validation" in f:
            continue
        a = (phase8["out"] / f).read_text(encoding="utf-8")
        b = (committed / f).read_text(encoding="utf-8")
        assert a == b, f
    assert (phase8["out"] / "phase8_executive_action_plan.md").read_text(encoding="utf-8") == \
        (committed / "phase8_executive_action_plan.md").read_text(encoding="utf-8")


def test_no_evaluation_file_opened(phase8):
    o = phase8["opened"]
    assert not o["refused"]
    assert not any("answer_key" in p or "planted" in p or "hidden_scenario" in p for p in o["project_files"])


def test_no_em_dash_anywhere(phase8):
    text = _all_text(phase8) + DOC.read_text(encoding="utf-8") + (ROOT / "README.md").read_text(encoding="utf-8")
    text += (ROOT / "config" / "action_config.yaml").read_text(encoding="utf-8")
    text += (ROOT / "reports" / "phase8" / "phase8_independent_review.md").read_text(encoding="utf-8")
    assert "\u2014" not in text
