"""Phase 5 tests: periods, reconciliation, contribution, bridge, estimates, evidence, independence, reproducibility.

The session fixture runs the whole Phase 5 pipeline once (DuckDB engine, about 25 seconds) into a
temporary folder while recording every file it opens.
"""
from __future__ import annotations

import ast
import builtins
import io
import re
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from tests.conftest import assert_reproducible

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "processed" / "curated"
REPORTS = ROOT / "reports" / "phase5"
EVALUATION_ASSETS = ("_hidden_scenario", "_scenario_answer_key", "_planted_issues_log", "_generation_manifest",
                     "phase2_calibration_report", "phase2_full_validation", "phase2_full_scale_projection",
                     "phase3_detection_scorecard", "phase3_correction_accuracy", "phase3_extra_findings",
                     "phase3_not_detected", "phase3_freeze", "evaluate_phase3", "reports/evaluation", "evaluation/",
                     "independent_blind_profile", "reconcile_headline", "answer_key", "planted")
PHASE5_CODE = sorted((ROOT / "src" / "analytics").glob("*.py"))
PHASE5_SQL = sorted((ROOT / "sql" / "analysis" / "diagnostics").glob("*.sql"))
PHASE5_CONFIG = [ROOT / "config" / "analytics_config.yaml"]

needs_curated = pytest.mark.skipif(not (CURATED / "fact_sales.csv").exists(), reason="curated data not present")


@pytest.fixture(scope="session")
def phase5(tmp_path_factory):
    from src.analytics import run_phase5
    out = tmp_path_factory.mktemp("phase5")
    opened = []
    real_open = builtins.open

    def tracing_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    with mock.patch("builtins.open", tracing_open), mock.patch("io.open", tracing_open):
        res = run_phase5.run("duckdb", out_dir=out, make_figures=False)
    res["traced"] = opened
    return res


def _cfg():
    from src.analytics.model_access import load_config
    return load_config()


# ============================================================================= periods
def test_h2_period_selection():
    from src.analytics.period_comparison import load_periods
    _, project, _ = _cfg()
    per = load_periods(project)
    assert (per.cy_year, per.py_year, per.week_from, per.week_to, per.n_weeks) == (2025, 2024, 27, 52, 26)
    bad = {"comparison": {"current_period": {"retail_year": 2025, "retail_week_from": 27, "retail_week_to": 52},
                          "prior_period": {"retail_year": 2024, "retail_week_from": 26, "retail_week_to": 52}}}
    with pytest.raises(ValueError):
        load_periods(bad)
    bad["comparison"]["prior_period"] = {"retail_year": 2023, "retail_week_from": 27, "retail_week_to": 52}
    with pytest.raises(ValueError):
        load_periods(bad)


@needs_curated
def test_26_week_alignment(phase5):
    from src.analytics.period_comparison import check_week_alignment
    R = phase5["R"]
    assert R["alignment"]["passed"].all()
    w = R["weekly"]
    assert len(w) == 26 and list(w["retail_week"]) == list(range(27, 53))
    assert (pd.to_datetime(w["week_start_cy"]) - pd.to_datetime(w["week_start_py"])).dt.days.eq(364).all()
    assert not check_week_alignment(w.drop(index=3), R["periods"])["passed"].all()      # a missing week is caught
    shifted = w.assign(week_start_py=pd.to_datetime(w["week_start_py"]) + pd.Timedelta(days=1))
    assert not check_week_alignment(shifted, R["periods"])["passed"].all()              # weekday misalignment is caught


# ============================================================================= reconciliation
@needs_curated
def test_headline_reconciles_to_phase4(phase5):
    R = phase5["R"]
    rec = R["headline_recon"]
    assert (rec["status"] == "PASS").all(), rec
    bench = pd.read_csv(ROOT / "reports" / "phase4" / "reconciliation_results_duckdb.csv").set_index("metric_name")
    assert abs(R["py"]["net_revenue"] - bench.loc["h2_2024_net_revenue", "actual_value"]) <= 0.01
    assert abs(R["cy"]["net_revenue"] - bench.loc["h2_2025_net_revenue", "actual_value"]) <= 0.01
    yoy = 100 * (R["cy"]["net_revenue"] / R["py"]["net_revenue"] - 1)
    assert abs(yoy - bench.loc["h2_yoy_pct", "actual_value"]) <= 1e-4


@needs_curated
def test_headline_mismatch_is_detected(phase5):
    from src.analytics.period_comparison import check_headline_against_phase4
    R = phase5["R"]
    bench = pd.read_csv(ROOT / "reports" / "phase4" / "reconciliation_results_duckdb.csv")
    bench["source_file"] = "test"
    bench.loc[bench["metric_name"] == "h2_2025_net_revenue", "actual_value"] += 0.02
    facts = pd.DataFrame([{"retail_year": y, **{k: R[p][k] for k in ("sales_revenue", "returns_value", "net_revenue",
                                                                       "transactions", "units_sold")}}
                          for y, p in ((2024, "py"), (2025, "cy"))])
    rec = check_headline_against_phase4(R["py"], R["cy"], facts, bench, R["periods"], _cfg()[2]["tolerances"])
    assert (rec["status"] == "FAIL").sum() == 1


@needs_curated
def test_all_validation_checks_pass(phase5):
    c = phase5["checks"]
    assert len(c) >= 60 and (c["status"] == "PASS").all(), c[c["status"] != "PASS"].to_string()
    assert phase5["passed"]


# ============================================================================= contribution
@needs_curated
def test_contribution_totals(phase5):
    R = phase5["R"]
    total = R["cy"]["net_revenue"] - R["py"]["net_revenue"]
    yoy = 100 * total / R["py"]["net_revenue"]
    for k in ("store", "region", "format", "category"):
        df = R[k]
        assert abs(df["net_revenue_change"].sum() - total) <= 0.01, k
        assert abs(df["contribution_pp"].sum() - yoy) <= 1e-6, k
        assert abs(df["share_of_change"].sum() - 1) <= 1e-9, k
    assert len(R["store"]) == 20 and len(R["category"]) == 8          # 7 categories + Unknown product member


def test_contribution_table_unit():
    from src.analytics.contribution import contribution_table
    df = pd.DataFrame({"k": ["a", "b", "c"], "net_revenue_py": [100.0, 50.0, 10.0], "net_revenue_cy": [90.0, 40.0, 5.0]})
    out = contribution_table(df, "k", 160.0, -25.0).set_index("k")
    assert out.loc["a", "contribution_pp"] == pytest.approx(-6.25)
    assert out.loc["c", "net_revenue_yoy_pct"] == pytest.approx(-50.0)
    assert out.loc["a", "share_of_change"] == pytest.approx(0.4)
    assert out.loc["c", "yoy_pct_rank"] == 1 and out.loc["a", "contribution_rank"] in (1, 2)


def test_ranking_determinism():
    from src.analytics.contribution import contribution_table
    rng = np.random.default_rng(7)
    df = pd.DataFrame({"k": [f"S{i:02d}" for i in range(20)], "net_revenue_py": 100.0,
                       "net_revenue_cy": rng.choice([90.0, 95.0, 100.0], 20)})    # many ties on purpose
    a = contribution_table(df, "k", 2000.0, -50.0)
    for seed in range(5):
        b = contribution_table(df.sample(frac=1, random_state=seed), "k", 2000.0, -50.0)
        assert a[["k", "contribution_rank", "yoy_pct_rank"]].equals(b[["k", "contribution_rank", "yoy_pct_rank"]])
    tied = a[a["net_revenue_change"] == a["net_revenue_change"].min()]
    assert list(tied["k"]) == sorted(tied["k"])                                  # ties broken by key


# ============================================================================= bridge
def test_shapley_is_exact_and_symmetric():
    from src.analytics.contribution import shapley_three
    rng = np.random.default_rng(1)
    t0, u0, p0, t1, u1, p1 = (rng.uniform(1, 100, 1000) for _ in range(6))
    et, eu, ep = shapley_three(t0, u0, p0, t1, u1, p1)
    assert np.allclose(et + eu + ep, t1 * u1 * p1 - t0 * u0 * p0, rtol=0, atol=1e-8)
    # symmetry: permuting the factors permutes the effects
    eu2, ep2, et2 = shapley_three(u0, p0, t0, u1, p1, t1)
    assert np.allclose(et, et2) and np.allclose(eu, eu2) and np.allclose(ep, ep2)
    # a factor that does not change gets zero effect
    z = shapley_three(t0, u0, p0, t0, u1, p1)[0]
    assert np.allclose(z, 0)


@needs_curated
def test_revenue_bridge_reconciles(phase5):
    R = phase5["R"]
    e = R["bridge_effects"]
    total = R["cy"]["net_revenue"] - R["py"]["net_revenue"]
    parts = e["transactions_effect"] + e["upt_effect"] + e["asp_effect"] + e["returns_effect"]
    assert abs(parts - total) <= 0.01 and abs(e["shapley_residual"]) <= 0.01
    b = R["bridge"]
    assert abs(b["running_total_eur"].iloc[-2] - R["cy"]["net_revenue"]) <= 0.01
    assert R["seg_bridge"]["reconciliation_difference"].abs().max() <= 0.01
    assert R["cat_bridge"]["reconciliation_difference"].abs().max() <= 0.01
    assert abs(sum(R["aov_effects"]) - (R["cy"]["aov"] - R["py"]["aov"])) <= 1e-9


# ============================================================================= robustness
def test_no_divide_by_zero():
    from src.analytics.contribution import bridge_effects, safe_div, yoy_pct
    assert np.isnan(safe_div(1.0, 0.0)) and np.isnan(yoy_pct(5.0, 0.0))
    s = safe_div(pd.Series([1.0, 2.0]), pd.Series([0.0, 4.0]))
    assert np.isnan(s.iloc[0]) and s.iloc[1] == 0.5
    with np.errstate(all="raise"):
        safe_div(np.array([1.0, 0.0]), np.array([0.0, 0.0]))
    from src.analytics.contribution import contribution_table
    df = pd.DataFrame({"k": ["a"], "net_revenue_py": [0.0], "net_revenue_cy": [10.0]})
    out = contribution_table(df, "k", 100.0, 0.0)
    assert np.isnan(out["net_revenue_yoy_pct"].iloc[0]) and np.isnan(out["share_of_change"].iloc[0])
    e = bridge_effects(10, 20, 200.0, 5.0, 10, 20, 200.0, 5.0)
    assert e["net_revenue_change"] == 0 and e["transactions_effect"] == 0


@needs_curated
def test_no_infinite_values_in_outputs(phase5):
    for f in Path(phase5["out"]).glob("*.csv"):
        num = pd.read_csv(f).select_dtypes(include=[np.number])
        assert not np.isinf(num.to_numpy(dtype=float)).any(), f.name


# ============================================================================= lost sales
def _toy_panel(units, in_stock, promo=None):
    from src.analytics.diagnostics import Panel
    n = len(units)
    weeks = pd.DataFrame({"retail_week_key": [202427 + i for i in range(n)], "retail_year": 2024,
                          "retail_week": [27 + i for i in range(n)]})
    cells = pd.DataFrame({"retail_week_key": weeks["retail_week_key"], "store_key": 1, "product_key": 1, "category": "C",
                          "units_sold": units, "sales_revenue": [10.0 * u for u in units], "promo_units_sold": 0,
                          "discount_value": 0.0, "cost_of_sales": [6.0 * u for u in units],
                          "promo_days": promo if promo is not None else [0] * n, "is_in_stock": in_stock,
                          "opening_stock": [0 if not s else 5 for s in in_stock], "received_qty": 0,
                          "closing_stock": [0 if not s else 5 for s in in_stock]})
    return Panel(cells, weeks)


def test_lost_sales_estimate_unit():
    from src.analytics.diagnostics import estimate_expected, lost_sales_cells
    units = [4, 4, 4, 4, 0, 4, 4, 4, 4, 9]
    stock = [1, 1, 1, 1, 0, 1, 1, 1, 1, 0]                 # week 31 fully out; week 36 sold out with high sales
    p = _toy_panel(units, stock)
    est = estimate_expected(p, [4, 8], 3)
    lost = lost_sales_cells(p, est, (2024, 2025), 27, 52).set_index("retail_week")
    assert lost.loc[31, "expected_units"] == pytest.approx(4.0)
    assert lost.loc[31, "est_lost_units"] == pytest.approx(4.0) and lost.loc[31, "est_lost_sales_eur"] == pytest.approx(40.0)
    assert lost.loc[36, "est_lost_units"] == 0                # actual above expected: never negative
    assert (lost["est_lost_sales_eur"] >= 0).all()


def test_lost_sales_needs_minimum_history():
    from src.analytics.diagnostics import estimate_expected, lost_sales_cells
    p = _toy_panel([3, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0])
    lost = lost_sales_cells(p, estimate_expected(p, [4], 3), (2024, 2025), 27, 52)
    assert not lost["has_estimate"].any() and lost["est_lost_sales_eur"].isna().all()


def test_lost_sales_baseline_excludes_promoted_weeks():
    from src.analytics.diagnostics import estimate_expected
    units = [2, 2, 20, 2, 0, 2, 2, 2]
    p = _toy_panel(units, [1, 1, 1, 1, 0, 1, 1, 1], promo=[0, 0, 7, 0, 0, 0, 0, 0])
    est = estimate_expected(p, [4], 3)
    assert est["expected_units"][0, 0, 4] == pytest.approx(2.0)   # the promoted 20-unit week is not in the baseline


@needs_curated
def test_lost_sales_non_negative_and_labelled(phase5):
    lost = phase5["R"]["lost_cells"]
    assert (lost["est_lost_sales_eur"].dropna() >= 0).all() and (lost["est_lost_units"].dropna() >= 0).all()
    av = pd.read_csv(Path(phase5["out"]) / "availability_diagnostics.csv")
    assert all("ESTIMATE" in c for c in av.columns if c.startswith("est_lost"))
    assert phase5["R"]["mechanism"]["by_type"][0]["actual_units"] == 0      # no stock all week -> no sales


# ============================================================================= targets
def test_target_streaks_unit():
    from src.analytics.diagnostics import target_diagnostics
    cfg = _cfg()[0]
    weeks = [40, 41, 42, 44, 45, 46, 47, 48]                 # week 43 has no target: it breaks a streak
    net = [90, 90, 90, 90, 90, 110, 90, 90]
    tw = pd.DataFrame({"retail_year": 2025, "retail_week": weeks, "store_id": "S99", "store_name": "x", "region": "r",
                       "store_format": "f", "net_revenue": net, "target_net_revenue": 100.0})
    out = target_diagnostics(tw, cfg, 2024, 2025, 52).iloc[0]
    assert out["missed_weeks"] == 7 and out["longest_miss_streak"] == 3
    assert out["last13_missed_weeks"] == 7 and not out["persistent_underperformer"]      # 7 < 8 of the last 13


# ============================================================================= evidence
def test_evidence_levels_are_the_brd_four():
    from src.analytics.evidence import EVIDENCE_LEVELS, Finding
    assert EVIDENCE_LEVELS == ("Observed change", "Statistical association", "Root-cause evidence", "Hypothesis")
    with pytest.raises(ValueError):
        Finding("a", "b", "c", 0.0, 0.0, "Probable cause", "", "", "", "", "")


@needs_curated
def test_shortlist_evidence_and_columns(phase5):
    sl = pd.read_csv(Path(phase5["out"]) / "investigation_shortlist.csv")
    required = ["finding_id", "area", "finding", "metric", "financial_impact_eur", "contribution_pp", "evidence_level",
                "supporting_analysis", "business_interpretation", "recommended_next_analysis", "limitations"]
    assert all(c in sl.columns for c in required)
    assert sl["evidence_level"].isin(["Observed change", "Statistical association", "Root-cause evidence", "Hypothesis"]).all()
    assert sl["finding_id"].is_unique and len(sl) >= 15
    assert (sl["evidence_level"] == "Hypothesis").sum() >= 3
    corr = sl[sl["metric"].str.contains("Correlation")]
    assert len(corr) and (corr["evidence_level"] == "Statistical association").all()
    hyp = sl[sl["evidence_level"] == "Hypothesis"]
    assert hyp["limitations"].str.contains("data required|Additional", case=False).all()


def test_root_cause_rule_falls_back_when_not_met():
    from src.analytics.evidence import stockout_rule
    cfg = _cfg()[0]
    mech = {"full_week_out_cells": 10, "full_week_out_actual_to_expected": 0.0, "coverage": 1.0}
    assert stockout_rule(mech, {"bias_ratio": 1.0}, cfg)[0]
    assert not stockout_rule(mech, {"bias_ratio": 1.4}, cfg)[0]                    # estimator not trustworthy
    assert not stockout_rule({**mech, "full_week_out_actual_to_expected": 0.9}, {"bias_ratio": 1.0}, cfg)[0]


def test_association_is_always_labelled_association():
    from src.analytics.diagnostics import association
    a = association([1, 2, 3, 4, 5], [2, 4, 6, 8, 10.5], "x", "y", "test", 0.05)
    assert a["evidence_label"] == "Statistical association" and a["pearson_r"] > 0.99
    b = association([1, 1, 1], [1, 2, 3], "x", "y", "flat", 0.05)
    assert np.isnan(b["pearson_r"]) and not b["significant_at_alpha"]


# ============================================================================= independence guard
def test_phase5_code_never_names_an_evaluation_asset():
    offenders = [f"{f.relative_to(ROOT)}: {a}" for f in PHASE5_CODE + PHASE5_SQL + PHASE5_CONFIG
                 for a in EVALUATION_ASSETS if a in f.read_text(encoding="utf-8")]
    assert not offenders, offenders


def test_phase5_code_does_not_import_generator_evaluation_or_dq_code():
    for f in PHASE5_CODE:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for m in mods:
                assert not any(x in m for x in ("data_generation", "evaluation", "data_quality")), (f.name, m)


def test_input_guard_refuses_evaluation_and_raw_assets():
    from src.analytics.model_access import InputError, allowed_path
    cfg = _cfg()[0]
    for bad in ("data/raw/_planted_issues_log.csv", "data/raw/_scenario_answer_key.csv", "config/_hidden_scenario.yaml",
                "reports/evaluation/phase3_detection_scorecard.csv", "reports/phase2_calibration_report.json",
                "evaluation/evaluate_phase3_detection.py", "data/raw/fact_sales.csv", "data/sample/fact_sales.csv",
                "reports/phase2_full_validation_report.md", "data/processed/quarantine/fact_sales_rejected.csv"):
        with pytest.raises(InputError):
            allowed_path(bad, cfg)
    assert allowed_path("data/processed/curated/fact_sales.csv", cfg).name == "fact_sales.csv"


@needs_curated
def test_run_never_opens_an_evaluation_asset(phase5):
    traced = [p.replace("\\", "/") for p in phase5["traced"]]
    audited = phase5["opened"]
    bad = [p for p in traced + audited["project_files"] if any(a in p for a in EVALUATION_ASSETS) or
           any(part.startswith("_") and not part.startswith("__") for part in Path(p).parts)]
    assert not bad, bad
    assert not audited["refused"]
    data_reads = {Path(p).name for p in audited["project_files"] if p.startswith("data/")}
    assert data_reads <= {f"{t}.csv" for t in ("dim_date", "dim_store", "dim_product", "fact_sales", "fact_returns",
                                               "fact_inventory", "fact_promotions", "fact_targets")}
    assert "reports/phase4/reconciliation_results_duckdb.csv" in audited["project_files"]


def test_freeze_guard_detects_a_changed_input(monkeypatch):
    from src.analytics import model_access as MA
    cfg = _cfg()[0]
    if not (ROOT / cfg["inputs"]["freeze_manifest"]).exists():
        pytest.skip("freeze manifest not recorded")
    real = MA.sha256_normalised
    monkeypatch.setattr(MA, "sha256_normalised",
                        lambda p: "0" * 64 if p.name == "04_create_fact_tables.sql" else real(p))
    with pytest.raises(MA.InputError, match="changed"):
        MA.verify_freeze(cfg)


# ============================================================================= SQL layer
def test_diagnostic_sql_is_valid_tsql():
    import sqlglot
    from src.sql_model.scripts import split_batches, strip_comments
    names = [p.name for p in PHASE5_SQL]
    assert names == [f"0{i}_{n}.sql" for i, n in enumerate(
        ["headline_trend", "store_contribution", "region_format_analysis", "category_contribution",
         "transaction_basket_analysis", "returns_diagnostics", "availability_diagnostics", "promotion_diagnostics",
         "target_performance"], start=1)]
    for p in PHASE5_SQL:
        for b in split_batches(p):
            if b.target == "tsql":
                continue
            for stmt in sqlglot.parse(strip_comments(b.text), read="tsql"):
                assert stmt is not None
            body = strip_comments(b.text)
            assert re.match(r"\s*CREATE OR ALTER VIEW diag\.", body), (p.name, b.index)
            for m in re.finditer(r"\bORDER\s+BY\b", body):                   # views: ORDER BY only inside OVER ( ... )
                assert "OVER (" in body[max(0, m.start() - 120):m.start()], (p.name, b.index)
    first = split_batches(PHASE5_SQL[0])[0]
    assert first.target == "tsql" and "CREATE SCHEMA diag" in first.text
    text = "\n".join(p.read_text(encoding="utf-8") for p in PHASE5_SQL)
    assert "stg." not in strip_comments(text) and "recon." not in strip_comments(text)   # governed layer only


# ============================================================================= reproducibility and reporting
@needs_curated
def test_outputs_are_reproducible(phase5):
    """A fresh run reproduces every committed Phase 5 table."""
    fresh = Path(phase5["out"])
    committed = sorted(p.name for p in REPORTS.glob("*.csv") if p.name != "phase1_4_input_manifest.csv")
    assert committed, "no committed Phase 5 outputs"
    for name in committed:
        a = pd.read_csv(REPORTS / name)
        b = pd.read_csv(fresh / name)
        assert_reproducible(a, b, name)


def test_reproducibility_comparison_is_numeric_where_it_must_be():
    """Regression guard for assert_reproducible.

    A mixed column (numbers and words) is compared numerically, so a last-bit platform difference is
    tolerated, but a material numeric difference and any textual change must still fail.
    """
    base = pd.DataFrame({"value": [26, 0.7692307692307693, "persistent", -731270.5, 0.6227742177479151]})
    same = pd.DataFrame({"value": [26, 0.7692307692307693, "persistent", -731270.5000000001, 0.6227742177479147]})
    assert_reproducible(base, same, "t.csv")          # last-bit float noise passes

    material = pd.DataFrame({"value": [26, 0.7692307692307693, "persistent", -731271.5, 0.6227742177479151]})
    with pytest.raises(AssertionError, match="beyond tolerance"):
        assert_reproducible(base, material, "t.csv")

    reworded = pd.DataFrame({"value": [26, 0.7692307692307693, "persistently", -731270.5, 0.6227742177479151]})
    with pytest.raises(AssertionError, match="differs"):
        assert_reproducible(base, reworded, "t.csv")

    # a material difference hidden in a numerically typed column must also fail
    numeric = pd.DataFrame({"v": [1.0, 2.0, 3.0]})
    with pytest.raises(AssertionError, match="beyond tolerance"):
        assert_reproducible(numeric, pd.DataFrame({"v": [1.0, 2.5, 3.0]}), "n.csv")

    # structural differences are still caught
    with pytest.raises(AssertionError):
        assert_reproducible(base, base.iloc[:4].reset_index(drop=True), "t.csv")


@needs_curated
def test_executive_summary_answers_the_ten_questions(phase5):
    text = (Path(phase5["out"]) / "phase5_executive_summary.md").read_text(encoding="utf-8")
    for n in range(1, 11):
        assert re.search(rf"^## {n}\. ", text, re.M), n
    assert "ESTIMATE" in text and "**Returns.**" in text and "**Targets.**" in text
    for word in ("planted", "answer key", "ground truth", "hidden scenario", "scorecard"):
        assert word not in text.lower(), word


def test_no_em_dash_in_phase5_files():
    em_dash = chr(0x2014)                      # the owner's style rule: no em dash anywhere
    files = PHASE5_CODE + PHASE5_SQL + PHASE5_CONFIG + [ROOT / "docs" / "05_exploratory_analysis.md", ROOT / "README.md",
                                                        Path(__file__)] + \
        sorted(REPORTS.glob("*.md")) + sorted(REPORTS.glob("*.csv"))
    offenders = [str(f.relative_to(ROOT)) for f in files if f.exists() and em_dash in f.read_text(encoding="utf-8")]
    assert not offenders, offenders


def test_diagnostic_sql_reads_no_files():
    """The guard on Python opens cannot see files a database engine reads itself, so the SQL is scanned too."""
    from src.sql_model.scripts import strip_comments
    pattern = re.compile(r"\b(read_csv\w*|read_parquet|read_json\w*|read_text|read_blob|sniff_csv|glob\s*\(|OPENROWSET|"
                         r"OPENDATASOURCE|BULK\s+INSERT|xp_cmdshell|COPY\s+\w+\s+FROM)", re.I)
    for f in PHASE5_SQL:
        assert not pattern.search(strip_comments(f.read_text(encoding="utf-8"))), f.name


def test_returns_rate_and_volume_split_is_exact():
    from src.analytics.diagnostics import _returns_row
    r = _returns_row("Estate", "x", "", 100.0, 130.0, 2000.0, 1800.0, 10, 12, 400, 380, 1e6, 30.0)
    assert r["returns_rate_effect"] + r["returns_volume_effect"] == pytest.approx(30.0)
    assert r["returns_volume_effect"] < 0 < r["returns_rate_effect"]              # sales fell, rate rose
    assert r["contribution_pp"] == pytest.approx(-100 * 30.0 / 1e6)


def _toy_promo_panel():
    """Category C, 4 SKUs selling 2 units a week; SKU 1 is promoted in week 33 (10 units) with a dip after."""
    from src.analytics.diagnostics import Panel
    weeks = pd.DataFrame({"retail_week_key": [202427 + i for i in range(14)], "retail_year": 2024,
                          "retail_week": [27 + i for i in range(14)]})
    rows = []
    for prod in (1, 2, 3, 4):
        for i, wk in enumerate(weeks["retail_week_key"]):
            u = 2
            promo_units, disc, days = 0, 0.0, 0
            if prod == 1 and i == 6:
                u, promo_units, disc, days = 10, 10, 20.0, 7
            if prod == 1 and i in (7, 8):
                u = 1
            rows.append({"retail_week_key": wk, "store_key": 1, "product_key": prod, "category": "C", "units_sold": u,
                         "sales_revenue": 10.0 * u - disc, "promo_units_sold": promo_units, "discount_value": disc,
                         "cost_of_sales": 6.0 * u, "promo_days": days, "is_in_stock": 1, "opening_stock": 9,
                         "received_qty": 0, "closing_stock": 9})
    return Panel(pd.DataFrame(rows), weeks)


def test_promotion_uplift_margin_and_pull_forward_unit():
    from src.analytics.diagnostics import estimate_expected, promotion_uplift
    cfg = _cfg()[0]
    panel = _toy_promo_panel()
    est = estimate_expected(panel, [4], 3)
    events = pd.DataFrame([{"promotion_key": 7, "promotion_type": "Percent Off", "store_key": 1, "product_key": 1,
                            "start_date": pd.Timestamp("2024-08-12"), "end_date": pd.Timestamp("2024-08-18"),
                            "discount_pct": 0.2, "retail_week_key": 202433, "promo_days_in_week": 7}])
    products = pd.DataFrame({"product_key": [1, 2, 3, 4], "product_id": ["P1", "P2", "P3", "P4"]})
    agg, ev = promotion_uplift(panel, est, events, cfg, 2024, 2025, 27, 52, products)
    e = ev.iloc[0]
    assert e["valid"] and e["baseline_weeks"] == 4
    assert e["baseline_units"] == pytest.approx(2.0) and e["promo_units"] == 10
    assert e["incremental_units"] == pytest.approx(8.0)
    assert e["incremental_promo_margin"] == pytest.approx(8 * (10 - 6) - 20)          # BRD 5.4
    est_row = agg[(agg["level"] == "Estate") & (agg["retail_year"] == 2024)].iloc[0]
    assert est_row["uplift_pct"] == pytest.approx(400.0)
    # pull-forward dip: post weeks sell 1 unit; expected = baseline rate x category index, and in this 4-SKU toy the
    # promoted SKU's own dip lowers the index to 1.75 (negligible with the real 50 to 140 SKUs x 20 stores per category)
    assert est_row["post_promo_vs_baseline_pct"] == pytest.approx(100 * (1 / 1.75 - 1))


@needs_curated
def test_hypotheses_are_worded_as_hypotheses(phase5):
    sl = pd.read_csv(Path(phase5["out"]) / "investigation_shortlist.csv")
    hyp = sl[sl["evidence_level"] == "Hypothesis"]
    assert hyp["headline"].str.startswith("Hypothesis:").all() and hyp["finding"].str.startswith("Hypothesis:").all()
    assert not sl[sl["evidence_level"] != "Hypothesis"]["headline"].str.contains(r"\bcaused\b").any()
    not_net = sl[sl["impact_basis"].str.startswith("Not a")]
    assert not_net["financial_impact_eur"].isna().all()                              # only net revenue effects carry EUR
