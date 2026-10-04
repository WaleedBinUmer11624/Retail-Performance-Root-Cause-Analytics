"""Phase 6 tests: freeze, reconciliation, store cluster, comparison groups, counterfactuals, overlap, evidence,
determinism, sensitivity, independence from evaluation assets.

The session fixture runs the whole Phase 6 pipeline once (DuckDB engine, about 40 seconds) into a temporary
folder while recording every file it opens.
"""
from __future__ import annotations

import ast
import builtins
import re
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from tests.conftest import assert_reproducible

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "processed" / "curated"
REPORTS = ROOT / "reports" / "phase6"
EVALUATION_ASSETS = ("_hidden_scenario", "_scenario_answer_key", "_planted_issues_log", "_generation_manifest",
                     "phase2_calibration_report", "phase2_full_validation", "phase2_full_scale_projection",
                     "phase3_detection_scorecard", "phase3_correction_accuracy", "phase3_extra_findings",
                     "phase3_not_detected", "phase3_freeze", "evaluate_phase3", "reports/evaluation", "evaluation/",
                     "independent_blind_profile", "reconcile_headline", "answer_key", "planted")
PHASE6_CODE = sorted((ROOT / "src" / "rca").glob("*.py"))
PHASE6_SQL = sorted((ROOT / "sql" / "analysis" / "rca").glob("*.sql"))
PHASE6_CONFIG = [ROOT / "config" / "rca_config.yaml"]
BRD_LEVELS = {"Observed change", "Statistical association", "Root-cause evidence", "Hypothesis"}

needs_curated = pytest.mark.skipif(not (CURATED / "fact_sales.csv").exists(), reason="curated data not present")


@pytest.fixture(scope="session")
def phase6(tmp_path_factory):
    from src.rca import run_phase6
    out = tmp_path_factory.mktemp("phase6")
    opened = []
    real_open = builtins.open

    def tracing_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    with mock.patch("builtins.open", tracing_open), mock.patch("io.open", tracing_open):
        res = run_phase6.run("duckdb", out_dir=out, make_figures=False)
    res["traced"] = opened
    return res


def _cfg():
    from src.rca.access import load_config
    return load_config()


# ============================================================================= freeze
def test_freeze_manifest_covers_phase1_5():
    man = pd.read_csv(ROOT / "reports" / "phase6" / "phase1_5_input_manifest.csv")
    files = set(man["file"])
    assert len(man) >= 80 and man["sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    for must in ("src/analytics/run_phase5.py", "config/analytics_config.yaml", "reports/phase5/headline_kpis.csv",
                 "reports/phase5/revenue_bridge.csv", "tests/test_phase5_analytics.py",
                 "reports/phase4/reconciliation_results_duckdb.csv"):
        assert must in files, must


def test_freeze_verifies_on_the_current_tree():
    from src.rca.access import verify_freeze
    df = verify_freeze(_cfg())
    assert (df["status"] == "UNCHANGED").all()


def test_freeze_detects_a_changed_phase5_file(monkeypatch):
    from src.rca import access as A
    real = A.sha256_normalised
    monkeypatch.setattr(A, "sha256_normalised", lambda p: "0" * 64 if Path(p).name == "headline_kpis.csv" else real(p))
    with pytest.raises(A.InputError, match="changed"):
        A.verify_freeze(_cfg())


# ============================================================================= headline
@needs_curated
def test_headline_reconciles_to_phase4_and_phase5(phase6):
    R = phase6["R"]
    rec = R["headline_recon"]
    assert (rec["status"] == "PASS").all(), rec
    assert {"Phase 4", "facts", "Phase 5 headline_kpis.csv"} <= set(rec["reference_source"])
    total = R["cy"]["net_revenue"] - R["py"]["net_revenue"]
    b4 = pd.read_csv(ROOT / "reports" / "phase4" / "reconciliation_results_duckdb.csv").set_index("metric_name")["actual_value"]
    assert abs(total - (b4["h2_2025_net_revenue"] - b4["h2_2024_net_revenue"])) <= 0.02


@needs_curated
def test_all_validation_checks_pass(phase6):
    c = phase6["checks"]
    assert len(c) >= 30 and (c["status"] == "PASS").all(), c[c["status"] != "PASS"].to_string()
    assert phase6["passed"]


# ============================================================================= store cluster
@needs_curated
def test_cluster_matches_phase5_hand_off(phase6):
    p5 = pd.read_csv(ROOT / "reports" / "phase5" / "store_contribution.csv")
    assert phase6["R"]["cluster"] == sorted(p5.loc[p5["in_decline_cluster"], "store_id"])


@needs_curated
def test_control_groups_exclude_the_cluster(phase6):
    sc = phase6["R"]["store_cluster"]
    cl = set(phase6["R"]["cluster"])
    assert set(sc["groups"]) >= {"matched", "standard_non_cluster", "dublin_non_cluster", "all_non_cluster"}
    for name, ids in sc["groups"].items():
        assert ids and not (set(ids) & cl), name
    assert len(sc["groups"]["matched"]) == _cfg()["rca"]["store_cluster"]["matched_k"]


@needs_curated
def test_cluster_ratio_did_identity_and_consistency(phase6):
    sc = phase6["R"]["store_cluster"]
    for grp, d in sc["eur"].items():
        for m, e in d.items():
            assert abs(e["actual"] - e["counterfactual"] - e["excess"]) < 1e-6, (grp, m)
    prim = sc["primary_control"]
    assert sc["eur"][prim]["net_revenue"]["excess"] < 0
    assert sc["did"][(prim, "ly_transactions")]["did_pct"] < 0


@needs_curated
def test_cluster_onset_and_placebo(phase6):
    sc = phase6["R"]["store_cluster"]
    on, pl = sc["onset"], sc["placebo"]
    assert on["best_model"] in {"step", "ramp", "linear"}
    assert pd.Timestamp(on["onset_date"]).year == _cfg()["rca"]["store_cluster"]["onset_year"]
    assert pl["placebo_n"] == 680 and 0 < pl["p_value_one_sided"] <= 1
    assert pl["actual"] <= pl["placebo_min"] or pl["p_value_one_sided"] > 1 / (pl["placebo_n"] + 1)


def test_step_changepoint_and_ramp_unit():
    from src.rca.stats import linear_fit, ramp_fit, step_changepoint
    rng = np.random.default_rng(1)
    y = np.r_[np.zeros(60), -10 * np.ones(60)] + rng.normal(0, 1, 120)
    s = step_changepoint(y, 20)
    assert abs(s["index"] - 60) <= 2 and abs(s["shift"] + 10) < 1
    r = ramp_fit(y, 10, 20)
    assert r["ramp_days"] <= 2 and r["bic"] < linear_fit(y)["bic"]


def test_did_and_placebo_unit():
    from src.rca.stats import did, permutation_placebo
    assert did(np.array([1.0, 1.0]), np.array([0.0, 0.0]), np.array([1.0, 1.0]), np.array([1.0, 1.0])) == -1.0
    vals = {"A": -1.0, "B": 0.0, "C": 0.1, "D": -0.1, "E": 0.05, "F": 0.0}
    stat = lambda tr, co: np.mean([vals[t] for t in tr]) - np.mean([vals[c] for c in co])  # noqa: E731
    p = permutation_placebo(["A"], ["B", "C", "D", "E", "F"], 1, stat)
    assert p["placebo_n"] == 5 and p["actual"] < p["placebo_min"] and p["p_value_one_sided"] == pytest.approx(1 / 6)


def test_robust_summary_rule():
    from src.rca.stats import robust_summary
    assert robust_summary([-90, -110, -120], -100, 0.5)["robust"]
    assert not robust_summary([-90, 10], -100, 0.5)["robust"]               # sign flip
    assert not robust_summary([-90, -200], -100, 0.5)["robust"]             # outside +-50%


# ============================================================================= comparison groups (E&T, promotions)
@needs_curated
def test_supplier_test_compares_against_the_other_suppliers(phase6):
    el = phase6["R"]["electronics"]
    t = el["supplier_tests"].iloc[0]
    assert t["supplier"] == el["top_supplier"]
    assert t["ci_low"] <= t["difference"] <= t["ci_high"]
    assert 0 < t["permutation_p_two_sided"] <= 1
    shares = el["by_supplier_category"]["share_of_lost_primary_change"]
    assert abs(shares.sum() - 1) < 1e-9


@needs_curated
def test_primary_lost_sales_equal_the_frozen_phase5_figure(phase6):
    el = phase6["R"]["electronics"]
    p5 = pd.read_csv(ROOT / "reports" / "phase5" / "availability_diagnostics.csv")
    ref = p5[(p5["level"] == "Category") & (p5["key"] == el["category"])].iloc[0]["est_lost_sales_cy_ESTIMATE"]
    assert abs(el["totals_category"]["primary_cy"] - ref) <= 0.01
    t = el["totals_category"]
    assert t["upper_change"] >= t["primary_change"] >= 0


@needs_curated
def test_promotion_controls_exclude_the_treated_category(phase6):
    c = _cfg()["rca"]["promotions"]
    assert c["category"] not in c["control_categories"]
    pr = phase6["R"]["promotions"]
    lo, hi = pr["m1"]["ci_eur"]
    assert lo <= pr["m1"]["effect_eur"] <= hi
    assert abs(pr["by_store"]["m1_effect_eur"].sum() - pr["m1"]["effect_eur"]) < 0.01


def test_range_distribution_partition_unit():
    from src.rca.electronics import range_distribution
    stores = pd.DataFrame({"store_key": [1, 2], "store_id": ["S01", "S03"]})
    rows = []
    for y, prods in ((2024, ["A", "B"]), (2025, ["A", "C"])):
        for p in prods:
            for w in range(2 if (p == "A" and y == 2025) else 3):
                rows.append({"store_key": 1, "product_key": p, "product_id": p, "supplier_name": "X", "category": "E",
                             "retail_year": y, "sales_revenue": 10.0})
    rows.append({"store_key": 2, "product_key": "A", "product_id": "A", "supplier_name": "X", "category": "E",
                 "retail_year": 2025, "sales_revenue": 999.0})             # cluster store: excluded
    t = range_distribution(pd.DataFrame(rows), stores, "E", 2024, 2025, ["S03"]).set_index("sku_status")
    assert t.loc["delisted", "sales_change"] == -30 and t.loc["new", "sales_change"] == 30
    assert t.loc["continuing", "distribution_effect"] == pytest.approx(-10)
    assert t.loc["continuing", "distribution_effect"] + t.loc["continuing", "rate_effect"] == t.loc["continuing", "sales_change"]


def test_faulty_rate_table_unit():
    from src.rca.returns_rca import rate_table
    ret = pd.DataFrame({"k": ["a", "a", "b", "b"], "return_retail_year": [2024, 2025, 2024, 2025],
                        "return_quantity": [1, 4, 1, 1], "refund_value": [10.0, 40.0, 10.0, 10.0]})
    units = pd.DataFrame({"k": ["a", "a", "b", "b"], "retail_year": [2024, 2025, 2024, 2025],
                          "units_sold": [100, 100, 100, 100]})
    t = rate_table(ret, units, "k", 2024, 2025).set_index("k")
    assert t.loc["a", "excess_units"] == pytest.approx(3) and t.loc["b", "excess_units"] == pytest.approx(0)
    assert t.loc["a", "p_increase"] < t.loc["b", "p_increase"]


# ============================================================================= overlap and double counting
def test_cluster_overlap_and_exclusive_attribution_unit():
    from src.rca.overlap import cluster_overlap, exclusive_attribution
    py_net = pd.Series({"C1": 100.0, "K1": 100.0, "K2": 100.0})
    amt = pd.Series({"C1": -30.0, "K1": -10.0, "K2": -10.0})
    d = cluster_overlap(amt, py_net, ["C1"], ["K1", "K2"])
    assert d["expected_in_cluster_at_control_rate"] == pytest.approx(-10)
    assert d["overlap_with_cluster_excess"] == pytest.approx(-20)
    assert d["exclusive"] == pytest.approx(-30)
    a = exclusive_attribution(-100.0, -50.0, {"x": d})
    assert a["amount_eur"].sum() == pytest.approx(-100.0) and a["share_of_change"].sum() == pytest.approx(1.0)
    # the cluster has LESS of the driver than the control rate implies: nothing is removed, never inflated
    low = cluster_overlap(pd.Series({"C1": -2.0, "K1": -10.0, "K2": -10.0}), py_net, ["C1"], ["K1", "K2"])
    assert low["overlap_with_cluster_excess"] == 0.0 and low["exclusive"] == pytest.approx(low["total"])
    # opposite-sign cluster amount (cluster improved): nothing is removed either
    opp = cluster_overlap(pd.Series({"C1": 5.0, "K1": -10.0, "K2": -10.0}), py_net, ["C1"], ["K1", "K2"])
    assert opp["overlap_with_cluster_excess"] == 0.0 and abs(opp["exclusive"]) <= abs(opp["total"])


@needs_curated
def test_attribution_closes_and_avoids_double_counting(phase6):
    R = phase6["R"]
    total = R["cy"]["net_revenue"] - R["py"]["net_revenue"]
    attr = R["overlap"]["attribution"]
    assert abs(attr["amount_eur"].sum() - total) < 0.01
    perim = R["overlap"]["perimeter"]
    assert abs(perim["net_revenue_change"].sum() - total) < 0.01 and len(perim) == 6
    for r in R["overlap"]["details"].itertuples():
        assert abs(r.exclusive - (r.total - r.overlap_with_cluster_excess)) < 1e-6
    pw = R["overlap"]["pairwise"]
    assert np.allclose(pw.to_numpy(), pw.T.to_numpy())
    for r in R["overlap"]["details"].itertuples():
        assert abs(r.exclusive) <= abs(r.total) + 1e-9, r.driver
    rb = R["overlap"]["residual_breakdown"]
    assert abs(rb["amount_eur"].sum() - attr.iloc[-1]["amount_eur"]) < 0.01
    naive = R["central"]["cluster_excess"] + sum(float(p) for p in perim.query("store_group == 'Other stores' and "
                                                                                "category_group != 'Other categories'")
                                                 ["net_revenue_change"])
    assert abs(attr["amount_eur"].iloc[:-1].sum()) <= abs(total) + 0.01 or abs(naive) > abs(total)


# ============================================================================= counterfactuals
@needs_curated
def test_counterfactual_scenarios_reconcile(phase6):
    R = phase6["R"]
    sn = R["scenarios"].set_index("scenario")
    assert set(sn.index) >= {"A", "B", "C", "D", "E"}
    assert sn.loc["A", "revenue_impact_eur"] == pytest.approx(-R["central"]["cluster_excess"])
    assert sn.loc["B", "revenue_impact_eur"] == pytest.approx(-R["central"]["stockouts_primary"])
    assert sn.loc["D", "revenue_impact_eur"] == pytest.approx(-R["central"]["promotion"])
    comp = -R["overlap"]["attribution"]["amount_eur"].iloc[:-1].sum()
    assert sn.loc["E", "revenue_impact_eur"] == pytest.approx(comp, abs=0.01)
    assert set(sn["evidence_level"]) <= BRD_LEVELS
    summ = R["sensitivity_summary"].set_index("driver")
    for s, drv in (("A", "store_cluster_excess"), ("B", "electronics_stockouts_primary"), ("D", "home_kitchen_promotion")):
        assert sn.loc[s, "range_low_eur"] <= sn.loc[s, "revenue_impact_eur"] <= sn.loc[s, "range_high_eur"], s
        assert sn.loc[s, "range_low_eur"] == pytest.approx(-summ.loc[drv, "max"])       # ranges come from sensitivity
        assert sn.loc[s, "range_high_eur"] == pytest.approx(-summ.loc[drv, "min"])


# ============================================================================= evidence
@needs_curated
def test_evidence_matrix_fields_and_levels(phase6):
    ev = pd.read_csv(Path(phase6["out"]) / "root_cause_evidence_matrix.csv")
    spec = ["driver_id", "candidate_driver", "affected_scope", "observed_change", "mechanism", "estimated_impact_eur",
            "estimated_impact_pp", "evidence_supporting", "evidence_against", "method", "uncertainty", "evidence_level",
            "additional_data_required", "double_counting_risk", "conclusion"]
    assert all(c in ev.columns for c in spec)
    assert set(ev["evidence_level"]) <= BRD_LEVELS
    assert ev["driver_id"].is_unique and ev["additional_data_required"].notna().all()


@needs_curated
def test_root_cause_evidence_only_for_robust_quantified_mechanisms(phase6):
    R = phase6["R"]
    ev = R["evidence"].set_index("driver_id")
    sens = R["sensitivity_summary"].set_index("driver")
    rc = ev[ev["evidence_level"] == "Root-cause evidence"]
    fragile = {"D03": "electronics_stockouts_primary", "D07": "home_kitchen_promotion"}
    for d, drv in fragile.items():                                              # Root-cause evidence only if robust
        assert (ev.loc[d, "evidence_level"] == "Root-cause evidence") == bool(sens.loc[drv, "robust"]) or \
            ev.loc[d, "evidence_level"] != "Root-cause evidence", d
    assert set(rc.index) <= {"D03"}                                             # nothing else could qualify
    assert "upper" not in str(rc["candidate_driver"].tolist()).lower()             # the upper bound is never promoted
    assert ev.loc["D07", "evidence_level"] != "Root-cause evidence"                # method-dependent sign
    sn = R["scenarios"].set_index("scenario")
    assert (sn.loc["B", "evidence_level"] == "Root-cause evidence") == bool(sens.loc["electronics_stockouts_primary", "robust"])
    assert ev.loc["D02", "evidence_level"] == "Hypothesis" and ev.loc["D06", "evidence_level"] == "Hypothesis"


def test_level_rule_unit():
    from src.rca.evidence import level_for
    assert level_for(True, True, True) == "Root-cause evidence"
    assert level_for(True, False, True) == "Statistical association"
    assert level_for(False, True, True) == "Statistical association"
    assert level_for(True, True, False) == "Hypothesis"


# ============================================================================= sensitivity
@needs_curated
def test_sensitivity_runs_every_variant_family(phase6):
    s = phase6["R"]["sensitivity"]
    summ = phase6["R"]["sensitivity_summary"]
    assert len(s) >= 50 and summ["n_variants"].min() >= 3
    assert {"store_cluster_excess", "electronics_stockouts_primary", "electronics_stockouts_upper",
            "home_kitchen_promotion", "electronics_faulty_returns"} <= set(summ["driver"])
    assert (summ["min"] <= summ["max"]).all()
    assert not bool(summ.set_index("driver").loc["home_kitchen_promotion", "robust"])
    rec = s[s["method"].str.contains("net of recovery")]
    el = phase6["R"]["electronics"]
    assert len(rec) == 2
    prim = rec[rec["driver"] == "electronics_stockouts_primary"]["estimate_eur"].iloc[0]
    assert prim == pytest.approx(-(el["totals_category"]["primary_change"] - el["recovery_offset_eur"]))


# ============================================================================= determinism
@needs_curated
def test_outputs_are_reproducible(phase6):
    fresh = Path(phase6["out"])
    committed = sorted(p.name for p in REPORTS.glob("*.csv") if p.name not in ("phase1_5_input_manifest.csv",))
    assert len(committed) >= 45
    for name in committed:
        a = pd.read_csv(REPORTS / name)
        b = pd.read_csv(fresh / name)
        assert_reproducible(a, b, name)
    assert (REPORTS / "phase6_root_cause_report.md").read_text(encoding="utf-8") == \
        (fresh / "phase6_root_cause_report.md").read_text(encoding="utf-8")


# ============================================================================= report aggregation precision
# The unrounded attribution doubles sum to -731270.5000000001, a last bit across the .5 tie boundary,
# so `,+,.0f` rendered -731,271 while driver_attribution.csv, the headline and the run log all say -731,270.50.
UNROUNDED_ATTRIBUTION = pd.Series([-397778.209303217, -37235.346775933955, -31588.73,
                                   -186146.42044890166, -78521.79347194743])


def test_report_total_is_summed_at_the_canonical_table_precision():
    from src.rca.report import OUTPUT_DECIMALS, canonical_total
    assert OUTPUT_DECIMALS == 6, "the governed tables are published at 6 decimals"
    # the tie-break this guards is real: the raw sum and the canonical sum render differently
    assert f"{UNROUNDED_ATTRIBUTION.sum():+,.0f}" == "-731,271"
    assert f"{canonical_total(UNROUNDED_ATTRIBUTION):+,.0f}" == "-731,270"


def test_report_total_agrees_with_the_governed_attribution_table():
    from src.rca.report import OUTPUT_DECIMALS, canonical_total
    gov = pd.read_csv(REPORTS / "driver_attribution.csv")
    stored = float(gov["amount_eur"].sum())
    assert canonical_total(UNROUNDED_ATTRIBUTION) == pytest.approx(stored, abs=10 ** -OUTPUT_DECIMALS)
    line = [x for x in (REPORTS / "phase6_root_cause_report.md").read_text(encoding="utf-8").splitlines()
            if "Total (FACT)" in x]
    assert len(line) == 1 and f"{stored:+,.0f}" in line[0], line


def test_canonical_total_detects_material_change_without_widening_tolerance():
    from src.rca.report import canonical_total
    base = canonical_total(UNROUNDED_ATTRIBUTION)
    for delta in (0.01, 1.0, 1000.0):
        shifted = UNROUNDED_ATTRIBUTION.to_numpy(copy=True)
        shifted[0] += delta
        assert canonical_total(shifted) - base == pytest.approx(delta, abs=1e-6)   # far tighter than the EUR 0.01 tolerance
    assert canonical_total(UNROUNDED_ATTRIBUTION + 1000.0) != canonical_total(UNROUNDED_ATTRIBUTION)
    assert canonical_total([1.0, 2.5, 3.0]) == pytest.approx(6.5)      # order and dtype do not matter


# ============================================================================= independence
def test_phase6_code_never_names_an_evaluation_asset():
    offenders = [f"{f.relative_to(ROOT)}: {a}" for f in PHASE6_CODE + PHASE6_SQL + PHASE6_CONFIG
                 for a in EVALUATION_ASSETS if a in f.read_text(encoding="utf-8")]
    assert not offenders, offenders


def test_phase6_code_does_not_import_generator_evaluation_or_dq_code():
    for f in PHASE6_CODE:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for m in mods:
                assert not any(x in m for x in ("data_generation", "evaluation", "data_quality", "answer")), (f.name, m)


def test_input_guard_refuses_evaluation_and_raw_assets():
    from src.rca.access import InputError, allowed_path
    cfg = _cfg()
    for bad in ("data/raw/_planted_issues_log.csv", "data/raw/_scenario_answer_key.csv", "config/_hidden_scenario.yaml",
                "reports/evaluation/phase3_detection_scorecard.csv", "reports/phase2_calibration_report.json",
                "evaluation/evaluate_phase3_detection.py", "data/raw/fact_sales.csv", "data/sample/fact_sales.csv"):
        with pytest.raises(InputError):
            allowed_path(bad, cfg)


@needs_curated
def test_run_never_opens_an_evaluation_asset(phase6):
    traced = [p.replace("\\", "/") for p in phase6["traced"]]
    audited = phase6["opened"]
    bad = [p for p in traced + audited["project_files"] if any(a in p for a in EVALUATION_ASSETS) or
           any(part.startswith("_") and not part.startswith("__") for part in Path(p).parts)]
    assert not bad, bad
    assert not audited["refused"]
    data_reads = {Path(p).name for p in audited["project_files"] if p.startswith("data/")}
    assert data_reads <= {f"{t}.csv" for t in ("dim_date", "dim_store", "dim_product", "fact_sales", "fact_returns",
                                               "fact_inventory", "fact_promotions", "fact_targets")}
    assert not any(p.startswith(("data/raw", "data/sample", "data/processed/quarantine")) for p in audited["project_files"])


def test_rca_sql_reads_no_files_and_uses_governed_layers_only():
    from src.sql_model.scripts import split_batches, strip_comments
    pattern = re.compile(r"\b(read_csv\w*|read_parquet|read_json\w*|read_text|read_blob|sniff_csv|glob\s*\(|OPENROWSET|"
                         r"OPENDATASOURCE|BULK\s+INSERT|xp_cmdshell|COPY\s+\w+\s+FROM)", re.I)
    assert [p.name for p in PHASE6_SQL] == ["01_store_cluster.sql", "02_supply_and_returns.sql"]
    for f in PHASE6_SQL:
        body = strip_comments(f.read_text(encoding="utf-8"))
        assert not pattern.search(body), f.name
        assert "stg." not in body and "recon." not in body, f.name
        for b in split_batches(f):
            if b.target != "tsql":
                assert re.match(r"\s*CREATE OR ALTER VIEW rca\.", strip_comments(b.text)), (f.name, b.index)


def test_phase2_scenario_separation_guard_still_clean():
    from src.data_generation.validate_generated import EVALUATION_ONLY_ASSETS
    for f in PHASE6_CODE + PHASE6_SQL + PHASE6_CONFIG + [ROOT / "docs" / "06_root_cause_analysis.md"]:
        if f.exists():
            txt = f.read_text(encoding="utf-8")
            assert not any(a in txt for a in EVALUATION_ONLY_ASSETS), f.name


# ============================================================================= reporting
@needs_curated
def test_report_structure_and_tags(phase6):
    text = (Path(phase6["out"]) / "phase6_root_cause_report.md").read_text(encoding="utf-8")
    for h in ("Executive conclusion", "What happened", "Where it happened", "When it happened", "Revenue bridge",
              "Store-cluster investigation", "Electronics & Tech investigation", "Availability investigation",
              "Returns investigation", "Promotion investigation", "Driver overlap", "Counterfactual scenarios",
              "What the evidence supports", "What the evidence does NOT establish", "Remaining unknowns",
              "Additional data required", "Implications for Phase 7"):
        assert re.search(rf"^## {re.escape(h)}$", text, re.M), h
    for tag in ("FACT", "ESTIMATE", "STATISTICAL ASSOCIATION", "HYPOTHESIS", "UNRESOLVED"):
        assert tag in text, tag
    for word in ("planted", "answer key", "ground truth", "hidden scenario", "scorecard"):
        assert word not in text.lower(), word
    assert "not forecasts" in text


@needs_curated
def test_no_causal_overclaim_wording(phase6):
    text = (Path(phase6["out"]) / "phase6_root_cause_report.md").read_text(encoding="utf-8").lower()
    for phrase in ("caused by the promotion", "proves", "defective products caused", "voltix caused", "because of the competitor"):
        assert phrase not in text, phrase


def test_figures_exist():
    names = sorted(p.name for p in (REPORTS / "figures").glob("*.png"))
    assert names == ["01_root_cause_tree.png", "02_driver_waterfall.png", "03_cluster_vs_controls.png",
                     "04_category_store_heatmap.png", "05_electronics_availability_timeline.png",
                     "06_stockout_revenue_overlay.png", "07_supplier_concentration.png",
                     "08_faulty_return_concentration.png", "09_hk_promotion_counterfactual.png",
                     "10_driver_overlap_matrix.png", "11_evidence_matrix.png"]


def test_no_em_dash_in_phase6_files():
    em_dash = chr(0x2014)
    files = PHASE6_CODE + PHASE6_SQL + PHASE6_CONFIG + [ROOT / "docs" / "06_root_cause_analysis.md", ROOT / "README.md",
                                                        Path(__file__)] + \
        sorted(REPORTS.glob("*.md")) + sorted(REPORTS.glob("*.csv"))
    offenders = [str(f.relative_to(ROOT)) for f in files if f.exists() and em_dash in f.read_text(encoding="utf-8")]
    assert not offenders, offenders
