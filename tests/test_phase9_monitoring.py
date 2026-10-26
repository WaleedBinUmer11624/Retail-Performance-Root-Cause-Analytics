"""Phase 9 tests: operational monitoring, early warning and anomaly detection.

The session fixture runs Phase 9 once (DuckDB engine: the Phase 4 model is rebuilt, about 30 seconds) into a temporary
folder. Unit tests exercise the baseline, persistence, severity, DQ-gate and change-point logic on small synthetic
series with known answers; integration tests check the brief's requirements on the fresh outputs and that the
committed outputs in reports/phase9/ equal a fresh run.

Some tests pin results on the known 2025 episodes (first detection weeks, alert coverage of the shortage). They are
REGRESSION checks of this back-test, labelled as such: they must not be used as targets when thresholds are
recalibrated on new data (review follow-up N5).
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analytics.model_access import PROJECT_ROOT, InputError

# Paths inside the interpreter environment that is running these tests, wherever it lives: inside the
# project as .venv/, or outside it as README Step 2 recommends (KI-06). The guard resolves project root
# plus path, and an absolute path resolves to itself, so these work in both layouts.
ENV = Path(sys.prefix).resolve()


def env_path(*parts: str) -> str:
    return ENV.joinpath(*parts).as_posix()
from src.monitoring import access as AC
from src.monitoring import alerts as AL
from src.monitoring import backtest as BT
from src.monitoring import baselines as BL
from src.monitoring import run_phase9
from src.monitoring import signals as S

ROOT = PROJECT_ROOT
OUT = ROOT / "reports" / "phase9"
DOC = ROOT / "docs" / "09_monitoring_early_warning.md"
BRIEF_FILES = ["weekly_alerts.csv", "alert_summary.csv", "alert_backtest_results.csv", "threshold_sensitivity.csv",
               "signal_dictionary.csv", "phase9_executive_summary.md", "phase9_validation_report.md"]
SIGNALS = ["EW01", "EW02", "EW03", "EW04", "EW05", "EW06", "EW07", "EW08"]


@pytest.fixture(scope="session")
def p9(tmp_path_factory):
    """One fresh Phase 9 run on DuckDB into a temp folder, shared by the session."""
    if not (OUT / "phase1_8_dependency_manifest.csv").exists():
        pytest.skip("Phase 9 dependency manifest not recorded")
    out = tmp_path_factory.mktemp("phase9_reports")
    try:
        res = run_phase9.run("duckdb", out_dir=out)
    except InputError as e:  # curated data not generated in this checkout
        pytest.skip(f"Phase 9 inputs unavailable: {e}")
    return res


@pytest.fixture(scope="session")
def cfg():
    """Parsed monitoring configuration."""
    return AC.load_config()


def _csv(res, name):
    return pd.read_csv(res["out"] / name, keep_default_na=False)


def _synthetic(values, dq=None, entity="A"):
    n = len(values)
    return pd.DataFrame({"entity": entity, "t": np.arange(n), "value": np.asarray(values, dtype=float),
                         "dq_fail": np.zeros(n, dtype=bool) if dq is None else np.asarray(dq, dtype=bool)})


# ----------------------------------------------------------------------------- run, freeze, reconciliation
def test_run_passes_every_validation_check(p9):
    c = p9["checks"]
    assert p9["passed"], c[c["status"] != "PASS"].to_string()
    assert len(c) >= 21


def test_brief_deliverables_exist(p9):
    for f in BRIEF_FILES:
        assert (p9["out"] / f).exists(), f
    assert DOC.exists()
    assert len(list((p9["out"] / "figures").glob("p9_*.png"))) == 10


def test_freeze_covers_phase1_to_8(p9):
    f = p9["freeze"]
    assert (f["status"] == "UNCHANGED").all()
    assert {"Phase 1-4", "Phase 5", "Phase 6", "Phase 7", "Phase 8"} <= set(f["phase"])


def test_freeze_detects_a_changed_file(monkeypatch, cfg):
    target = "reports/phase8/phase8_early_warning_requirements.csv"
    real = AC.sha256_normalised
    monkeypatch.setattr(AC, "sha256_normalised", lambda p: "0" * 64 if str(p).replace("\\", "/").endswith(target) else real(p))
    with pytest.raises(InputError, match="changed since the Phase 9 freeze"):
        AC.verify_freeze(cfg)


def test_kpi_reconciliation_all_pass(p9):
    rec = p9["B"]["reconciliation"]
    assert len(rec) >= 20 and (rec["status"] == "PASS").all(), rec.to_string()


def test_kpi_dictionary_complete(p9):
    k = _csv(p9, "monitoring_kpi_dictionary.csv")
    need = {"weekly_net_revenue", "weekly_transactions", "weekly_units", "weekly_upt", "weekly_asp", "weekly_gross_margin",
            "weekly_return_rate", "weekly_availability", "weekly_stockout_rate", "weekly_full_week_stockouts",
            "weekly_promotion_share", "weekly_discount_rate", "weekly_data_completeness"}
    assert need <= set(k["kpi"])
    for col in ["definition", "grain", "numerator", "comparison_baseline", "required_dimensions", "data_source",
                "refresh_expectation"]:
        assert (k[col] != "").all(), col


# ----------------------------------------------------------------------------- baselines and leakage
def test_robust_baseline_is_median_of_prior_weeks():
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 100]
    p = BL.robust_walk_forward(_synthetic(vals), trailing=8, min_valid=8, exclude_low=-99, exclude_high=99, pooled=False)
    last = p[p["t"] == 8].iloc[0]
    assert last["baseline"] == pytest.approx(4.5)             # median of 1..8, not including 100 (week t itself)
    assert last["entity_mad"] == pytest.approx(2.0)
    assert last["scale"] == pytest.approx(2.0 * BL.MAD_TO_SD)
    assert p[p["t"] < 8]["baseline"].isna().all()               # fewer than 8 valid prior weeks


def test_dq_failed_and_anomalous_weeks_stay_out_of_baselines():
    vals = [0.0, 0.1, -0.1, 0.05, -0.05, 0.0, 0.1, -0.1, -2.0, 0.0, 0.0]
    dq = [False] * 11
    dq[3] = True
    p = BL.robust_walk_forward(_synthetic(vals, dq), trailing=13, min_valid=5, exclude_low=-2, exclude_high=3, pooled=False)
    assert p.loc[p["t"] == 9, "n_valid"].iloc[0] == 7           # 9 prior weeks minus the DQ week minus the anomaly
    assert p.loc[p["t"] == 10, "n_valid"].iloc[0] == 8


def test_no_future_leakage_in_baselines(cfg):
    rng = np.random.default_rng(1)
    a = _synthetic(rng.normal(0, 0.1, 40))
    b = a.copy()
    b.loc[b["t"] > 25, "value"] += 3.0
    kw = dict(trailing=13, min_valid=8, exclude_low=-2, exclude_high=3)
    pa, pb = BL.robust_walk_forward(a, **kw), BL.robust_walk_forward(b, **kw)
    m = pa["t"] <= 25
    assert np.allclose(pa.loc[m, "baseline"].fillna(0), pb.loc[m, "baseline"].fillna(0))
    ra, rb = BL.rolling_mean_sd(a.copy()), BL.rolling_mean_sd(b.copy())
    assert np.allclose(ra.loc[ra["t"] <= 25, "z_roll"].fillna(0), rb.loc[rb["t"] <= 25, "z_roll"].fillna(0))
    ta = BL.trailing_level(a, "value", 8)
    tb = BL.trailing_level(b, "value", 8)
    assert np.allclose(ta[a["t"] <= 25].fillna(0), tb[b["t"] <= 25].fillna(0))


def test_no_leakage_on_the_real_panel(p9, cfg):
    assert run_phase9.no_leakage_check(p9["B"], cfg)


def test_baseline_comparison_covers_the_brief_options(p9):
    b = _csv(p9, "baseline_comparison.csv")
    txt = " ".join(b["baseline"])
    for word in ["same retail week last year", "trailing 4-week mean", "trailing 8-week mean", "trailing 8-week median",
                 "13-week median", "13-week mean"]:
        assert word in txt, word
    # like for like: same store-weeks, same rule (review finding m2)
    assert b["store_weeks_tested"].nunique() == 1 and b["rule"].nunique() == 1
    b4 = b[b["baseline"].str.startswith("B4")].iloc[0]
    assert b4["unconfirmed_rate"] < b[b["baseline"].str.startswith("B2")]["unconfirmed_rate"].min()
    # the unguarded mean absorbs the anomaly: it stays active far less of the episode than the guarded median
    assert b4["episode_weeks_active_share"] > b[b["baseline"].str.startswith("B5")]["episode_weeks_active_share"].iloc[0]


# ----------------------------------------------------------------------------- thresholds, persistence, severity
def test_consecutive_run_breaks_on_gaps_and_entities():
    flag = pd.Series([True, True, False, True, True, True, True])
    ent = pd.Series(["A", "A", "A", "A", "A", "B", "B"])
    t = pd.Series([1, 2, 3, 4, 6, 1, 2])
    assert list(BL.consecutive(flag, ent, t)) == [1, 2, 0, 1, 1, 1, 2]


def test_threshold_and_persistence_application():
    f = pd.DataFrame({"entity": "A", "t": range(8), "baseline_ok": True,
                      "dq_fail": [False, False, False, True, False, False, False, False],
                      "b_x": [True, True, True, True, True, False, True, True]})
    fire, held = BT.fires(f, "b_x", 2)
    assert list(fire) == [False, True, True, False, False, False, False, True]
    assert list(held) == [False, False, False, True, False, False, False, False]


def _score_frame(n=12, breach_from=4, dq_week=None, signal="EW02"):
    t = np.arange(n)
    d = pd.DataFrame({"entity": "X", "t": t, "retail_week_key": 202501 + t, "signal": signal, "entity_type": "estate",
                      "baseline_ok": True, "dq_fail": False, "deviation": np.where(t >= breach_from, -0.2, 0.0),
                      "exposure": np.where(t >= breach_from, 10.0, 0.0), "entity_weekly_revenue": 1000.0})
    d["b_r"] = t >= breach_from
    if dq_week is not None:
        d.loc[d["t"] == dq_week, "dq_fail"] = True
    return d


def test_severity_ladder(cfg):
    sel = pd.Series({"rule_column": "b_r", "persistence_weeks": 2, "family": "f", "threshold": "x"})
    d = AL.score(_score_frame(), sel, cfg).sort_values("t")
    sev = list(d["severity"])
    assert sev[:4] == ["NORMAL"] * 4
    assert sev[4] == "WATCH"                                   # breached, persistence not met
    assert sev[5] == "WARNING"                                 # 2 consecutive weeks
    assert sev[8] == "CRITICAL"                                # WARNING for 4 consecutive weeks
    assert all(r for r in d.loc[d["level"] >= 1, "severity_reason"])


def test_dq_gate_caps_severity(cfg):
    sel = pd.Series({"rule_column": "b_r", "persistence_weeks": 2, "family": "f", "threshold": "x"})
    d = AL.score(_score_frame(dq_week=9), sel, cfg).set_index("t")
    assert d.loc[9, "severity"] == "WATCH" and bool(d.loc[9, "dq_hold"])
    assert "DQ gate failed" in d.loc[9, "severity_reason"]
    assert d.loc[10, "severity"] == "WATCH"                    # the run restarts after the held week


def test_dq_gating_in_the_back_test(p9):
    A, dq = p9["E"]["alerts"], p9["B"]["dq"]
    fails = dq[dq["dq_sales_status"] == "FAIL"][["store_id", "retail_week_key"]]
    assert set(map(tuple, fails.values)) == {("S13", 202442), ("S16", 202551), ("S16", 202552)}
    held = A[A["dq_hold"]]
    assert len(held) > 0 and (held["severity"] == "WATCH").all()
    assert held["message"].str.startswith("Held (DQ gate)").all()
    sw = p9["T"]["kpi_store_week"].drop_duplicates("store_id").set_index("store_id")
    groups = {"Estate", sw.loc["S16", "region"], sw.loc["S16", "store_format"]}
    est = A[(A["signal"] == "EW02") & (A["retail_week_key"] == 202552)]
    assert est.loc[est["entity_id"].isin(groups), "dq_hold"].all()       # totals that include S16 are held
    assert not est.loc[~est["entity_id"].isin(groups), "dq_hold"].any()  # other regions and formats are not


# ----------------------------------------------------------------------------- alert table
def test_alert_ids_unique_and_well_formed(p9):
    A = _csv(p9, "weekly_alerts.csv")
    assert A["alert_id"].is_unique
    assert A["alert_id"].str.match(r"^EW0[1-8]-[A-Z]{3}-[A-Z0-9]{1,12}-20\d{4}$").all()
    assert (A["alert_episode_id"] != "").all()


def test_alert_table_has_the_lifecycle_fields(p9):
    A = _csv(p9, "weekly_alerts.csv")
    need = ["alert_id", "alert_date", "retail_week", "signal", "entity_type", "entity_id", "actual_value", "baseline_value",
            "variance", "variance_pct", "severity", "persistence_weeks", "estimated_exposure", "dq_status", "evidence_level",
            "status", "owner", "created_at", "resolved_at", "notes"]
    assert set(need) <= set(A.columns)
    assert (A["status"] == "NEW").all() and (A["owner"] == "").all() and (A["resolved_at"] == "").all()
    assert (A["cause_status"] == "Not established").all()
    assert A["proposed_owner"].str.endswith("(PROPOSED)").all()


def test_lifecycle_transitions():
    lc = AL.lifecycle_table()
    assert list(lc["status"]) == ["NEW", "ACKNOWLEDGED", "INVESTIGATING", "ACTIONED", "MONITORING", "RESOLVED", "FALSE POSITIVE"]
    assert AL.valid_transition("NEW", "ACKNOWLEDGED")
    assert not AL.valid_transition("NEW", "RESOLVED")
    assert not AL.valid_transition("RESOLVED", "NEW")


def test_week_alignment_and_run_time(p9):
    A, cal = p9["E"]["alerts"], p9["T"]["week_calendar"]
    c = cal.set_index("retail_week_key")
    assert (c.loc[A["retail_week_key"], "days_in_week"] == 7).all()
    rt = pd.to_datetime(A["created_at"])
    we = pd.to_datetime(c.loc[A["retail_week_key"], "week_end"].values)
    assert ((rt - we) == pd.Timedelta(hours=30)).all()        # Monday 06:00 after the week closes
    lab = A["retail_week"].str.extract(r"(\d{4})-W(\d{2})").astype(int)
    assert (lab[0] * 100 + lab[1] == A["retail_week_key"]).all()


def test_prior_year_logic(p9):
    cal = p9["T"]["week_calendar"]
    c = cal[cal["retail_year"] == 2025].merge(cal[["retail_week_key", "retail_year", "retail_week"]].rename(
        columns={"retail_week_key": "py_week_key", "retail_year": "py_year", "retail_week": "py_week"}), on="py_week_key")
    assert len(c) == 52 and (c["py_year"] == 2024).all() and (c["retail_week"] == c["py_week"]).all()
    assert ((pd.to_datetime(c["week_start"]) - pd.to_datetime(cal.set_index("retail_week_key").loc[c["py_week_key"], "week_start"].values))
            == pd.Timedelta(days=364)).all()


def test_store_and_category_filters(p9):
    A = p9["E"]["alerts"]
    stores = set(p9["T"]["kpi_store_week"]["store_id"])
    cats = set(p9["T"]["kpi_category_week"]["category"]) - {"Unknown"}
    assert set(A.loc[A["entity_type"] == "store", "entity_id"]) <= stores
    assert set(A.loc[A["entity_type"] == "category", "entity_id"]) <= cats
    x = pd.read_csv(p9["out"] / "data" / "monitoring_signal_week.csv")
    for col in ["signal", "entity_type", "entity_id", "retail_week_key", "severity", "dq_status"]:
        assert col in x.columns
    # filtering the extract by signal and severity reproduces the alert counts
    for sig in SIGNALS:
        n_x = int(((x["signal"] == sig) & (x["severity"] != "NORMAL")).sum())
        assert n_x == int((A["signal"] == sig).sum()), sig


# ----------------------------------------------------------------------------- each signal
def test_every_signal_implemented_with_a_rule(p9):
    sd = _csv(p9, "signal_dictionary.csv")
    assert set(sd["signal"]) == set(SIGNALS)
    assert (sd["phase8_metric"] != "").all() and (sd["adaptation"] != "").all() and (sd["grain_reason"] != "").all()
    sel = p9["E"]["selected"]
    assert sel["within_budget"].all()


def test_ew01_detects_the_cluster_with_required_wording(p9):
    op = p9["E"]["operational"].set_index("store")
    for s in ["S03", "S04", "S05"]:
        assert op.loc[s, "first_detection_week"].startswith("2025-W")
        assert 0 <= op.loc[s, "detection_delay_weeks"] <= 8
        assert op.loc[s, "active_share_after_change_point"] >= 0.6   # sustained, not a one-off hit
        assert op.loc[s, "cause_status"] == "Cause not established from available internal data."
    A = p9["E"]["alerts"]
    assert A.loc[A["signal"] == "EW01", "message"].str.contains("Cause not established from available internal data.", regex=False).all()


def test_stockout_alerts_top_sellers_and_no_supplier_blame(p9):
    A = p9["E"]["alerts"]
    e4 = A[A["signal"] == "EW04"]
    top = p9["E"]["scored"][("EW04", "product")]
    assert (top["rank_pct"] <= 0.10).all()                     # only top-selling SKUs are monitored
    assert len(e4) > 0 and e4["alert_class"].str.startswith("ACTIONABLE").all()
    sup = _csv(p9, "ew04_supplier_concentration.csv")
    assert sup["note"].str.contains("does not establish").all()
    text = " ".join(e4["message"]).lower()
    assert "voltix" not in text and "caused" not in text


def test_return_alerts_wording_and_binomial(p9):
    A = p9["E"]["alerts"]
    e5 = A[A["signal"] == "EW05"]
    assert e5["message"].str.contains("Faulty-return activity exceeds expected range and requires investigation.", regex=False).all()
    assert not e5["message"].str.lower().str.contains("defect detected").any()
    # exact binomial tail against a direct sum
    x, n, p = 7, 20, 0.15
    direct = sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(x, n + 1))
    assert S.binom_sf(x, n, p) == pytest.approx(direct, rel=1e-12)
    assert S.binom_sf(0, 5, 0.3) == 1.0


def test_margin_alerts_track_margin_separately(p9):
    m = _csv(p9, "ew06_margin_context.csv")
    for col in ["gm_eur_change", "gm_pct_change_pp", "net_revenue_change_pct", "margin_fell_while_revenue_held"]:
        assert col in m.columns
    sel = p9["E"]["selected"].set_index("signal").loc["EW06"]
    assert int(sel["persistence_weeks"]) >= 2                  # a single week never becomes WARNING
    A = p9["E"]["alerts"]
    assert (A.loc[A["signal"] == "EW06", "cause_status"] == "Not established").all()


def test_promotion_alerts_make_no_causal_claim(p9):
    A = p9["E"]["alerts"]
    msg = " ".join(A.loc[A["signal"] == "EW07", "message"]).lower()
    assert "not established" in msg and "caused" not in msg
    pc = _csv(p9, "ew07_promotion_context.csv")
    for col in ["discount_rate_4w", "promotion_share_4w", "promotion_frequency_ratio", "asp_4w", "units_change_pct", "gm_pct_4w"]:
        assert col in pc.columns


def test_data_completeness_alerts(p9):
    A = p9["E"]["alerts"]
    e8 = A[A["signal"] == "EW08"]
    assert set(zip(e8["entity_id"], e8["retail_week_key"])) == {("S13", 202442), ("S16", 202551), ("S16", 202552)}
    dq = p9["B"]["dq"].set_index(["store_id", "retail_week_key"])
    assert bool(dq.loc[("S13", 202442), "C1"])                  # missing trading days
    assert dq.loc[("S16", 202551), "days_asat"] == 0            # nothing had arrived at the run
    cat = _csv(p9, "dq_check_catalogue.csv")
    assert len(cat) == 12 and "C12" in set(cat["check_id"])


def test_returns_warmup_holds_early_2025_return_comparisons(p9, cfg):
    """Review finding M1: returns of pre-extract sales are missing in early 2024, so the 2025 comparisons whose prior-year
    window touches the warm-up weeks are held (C12), never escalated."""
    A = p9["E"]["alerts"]
    early = A[A["signal"].isin(["EW05", "EW06"]) & (A["retail_week_key"] <= 202508)]
    assert len(early) and early["dq_hold"].all() and (early["severity"] == "WATCH").all()
    assert early["dq_note"].str.contains("C12").all()
    et = A[(A["signal"] == "EW05") & (A["entity_id"] == "Electronics & Tech") & A["severity"].isin(["WARNING", "CRITICAL"])]
    assert et["retail_week_key"].min() >= 202536


def test_estate_inventory_caveat_is_material_only(p9):
    """Review finding m3: a single store-SKU snapshot gap is not an estate caveat."""
    est = p9["B"]["estate_dq"]
    assert (est["dq_inventory_status"] == "WARN").sum() == int((est["missing_snapshot_share"] > 0.01).sum())
    A = p9["E"]["alerts"]
    assert (A.loc[A["signal"] == "EW04", "dq_status"] == "WARN").mean() < 0.5


# ----------------------------------------------------------------------------- change point, CUSUM
def test_changepoint_detects_a_step_and_ignores_noise():
    rng = np.random.default_rng(3)
    step = np.r_[rng.normal(0, 0.05, 20), rng.normal(-0.3, 0.05, 10)]
    d = S.online_changepoint(_synthetic(step), min_seg=3, deltas=[6])
    fired = d[d["b_cp6"]]
    assert len(fired) and 22 <= fired["t"].min() <= 24      # fires 3-5 weeks after the step at t=20
    assert fired["cp_tau_t"].iloc[-1] == 20
    noise = S.online_changepoint(_synthetic(rng.normal(0, 0.05, 30)), min_seg=3, deltas=[6])
    assert not noise["b_cp6"].any()
    up = S.online_changepoint(_synthetic(-step), min_seg=3, deltas=[6])
    assert not up["b_cp6"].any()                              # only adverse (downward) steps alarm


def test_changepoint_switches_off_after_recovery():
    """Review finding M3: the growing history keeps the step, but the alarm stops once the series is back."""
    rng = np.random.default_rng(5)
    v = np.r_[rng.normal(0, 0.03, 20), rng.normal(-0.3, 0.03, 8), rng.normal(0, 0.03, 6)]
    d = S.online_changepoint(_synthetic(v), min_seg=3, deltas=[6]).sort_values("t")
    assert d.loc[d["t"].between(23, 27), "b_cp6"].any()
    assert not d.loc[d["t"] >= 29, "b_cp6"].any()


def test_baseline_freezes_while_a_step_persists():
    """Review finding M3: a moderate sustained step (z between -2 and 0) must not drift into the baseline."""
    rng = np.random.default_rng(6)
    v = np.r_[rng.normal(0, 0.05, 20), [-0.4], rng.normal(-0.06, 0.02, 12)]
    panel = _synthetic(v)
    held = BL.robust_walk_forward(panel, trailing=13, min_valid=8, hold_release_weeks=4, hold_release_z=-1.0)
    free = BL.robust_walk_forward(panel, trailing=13, min_valid=8)
    last = held["t"].max()
    b_held = held.loc[held["t"] == last, "baseline"].iloc[0]
    b_free = free.loc[free["t"] == last, "baseline"].iloc[0]
    assert b_held > b_free and b_held > -0.03


def test_availability_alert_stays_on_through_the_shortage(p9):
    """Review finding M2: the guarded trailing mean does not follow the shortage down."""
    A = p9["E"]["alerts"]
    et = A[(A["signal"] == "EW03") & (A["entity_id"] == "Electronics & Tech") & A["severity"].isin(["WARNING", "CRITICAL"])]
    weeks = set(et["retail_week_key"])
    assert set(range(202533, 202549)) <= weeks


def test_changepoint_uses_only_the_past():
    rng = np.random.default_rng(4)
    a = _synthetic(rng.normal(0, 0.05, 30))
    b = a.copy()
    b.loc[b["t"] > 15, "value"] -= 1
    da, db = S.online_changepoint(a, 3, [6]), S.online_changepoint(b, 3, [6])
    assert np.allclose(da.loc[da["t"] <= 15, "cp_stat"].fillna(-1), db.loc[db["t"] <= 15, "cp_stat"].fillna(-1))


def test_cusum_accumulates_and_ignores_dq_weeks():
    d = _synthetic([0] * 5)
    d["z"] = [-1.0, -1.0, -5.0, -1.0, 2.0]
    d["dq_fail"] = [False, False, True, False, False]
    out = S.cusum(d, k=0.5, hs=[1])
    assert list(out["cusum"]) == pytest.approx([0.5, 1.0, 1.0, 1.5, 0.0])


def test_advanced_method_reported(p9):
    cp = _csv(p9, "changepoint_estimates.csv")
    assert set(cp["store"]) >= {"S03", "S04", "S05"}
    assert cp["reading"].str.contains("Cause not established").all()
    det = _csv(p9, "s03_s05_detection.csv")
    assert {"changepoint_online", "cusum", "robust_z", "rolling_z", "yoy_threshold", "peer_gap_threshold"} <= set(det["method"])


# ----------------------------------------------------------------------------- selection, sensitivity, burden
def test_selection_reads_only_the_noise_budget(p9, cfg):
    R = p9["E"]["results"].copy()
    ep_cols = [c for c in R.columns if c.startswith(("episode_", "median_detection", "max_detection", "known_episode", "pre_onset"))]
    for c in ep_cols:
        R[c] = 0
    a = BT.select(R, cfg)[["signal", "entity_type", "rule_column", "persistence_weeks"]].reset_index(drop=True)
    b = p9["E"]["selected"][["signal", "entity_type", "rule_column", "persistence_weeks"]].reset_index(drop=True)
    assert a.equals(b)


def test_episode_mask_effect_is_reported(p9, cfg):
    """Review finding M4: the known episodes shape selection through the noise mask; the effect is disclosed."""
    m = _csv(p9, "selection_mask_sensitivity.csv")
    assert len(m) == len(p9["E"]["selected"])
    assert {"rule_with_episode_mask", "rule_without_mask", "same_rule", "budget_measurable"} <= set(m.columns)
    est = m[(m["signal"] == "EW02") & (m["entity_type"] == "estate")].iloc[0]
    assert not bool(est["budget_measurable"])            # 20 non-episode weeks: one alert is already 5%
    text = (ROOT / "config" / "monitoring_config.yaml").read_text(encoding="utf-8")
    assert "No episode information is used" not in text


def test_changepoint_rule_is_selected_and_operated_within_budget(p9, cfg):
    """Review finding M3: the change-point rule goes through the same selection, and the rule as operated (both
    rules together) stays inside the budget."""
    sec = p9["E"]["secondary"]
    assert list(sec["family"]) == ["changepoint_online"] and sec["within_budget"].all()
    sel = p9["E"]["selected"]
    budget = cfg["monitoring"]["selection"]["warning_budget"]
    assert (sel["operational_unconfirmed_rate"] <= budget).all()
    assert sel.loc[sel["signal"] == "EW01", "confirm_column"].iloc[0] == sec["rule_column"].iloc[0]


def test_severity_sensitivity_reported(p9):
    v = _csv(p9, "severity_sensitivity.csv")
    assert {"as configured", "breadth rule off", "persistence 6 weeks", "exposure rule off"} <= set(v["variant"])
    g = v.groupby("variant")[["warning_plus", "critical"]].sum()
    assert (g["critical"] <= g["warning_plus"]).all()
    assert g.loc["breadth rule off", "critical"] <= g.loc["as configured", "critical"]


def test_threshold_sensitivity_is_monotonic(p9):
    s = _csv(p9, "threshold_sensitivity.csv")
    g = s[(s["signal"] == "EW01") & (s["family"] == "peer_gap_threshold")].copy()
    g["thr"] = g["threshold"].astype(float)
    for k, h in g.groupby("persistence_weeks"):
        h = h.sort_values("thr")
        assert (h["alerts"].diff().dropna() <= 0).all(), k       # higher threshold never adds alerts
    for thr, h in g.groupby("thr"):
        h = h.sort_values("persistence_weeks")
        assert (h["unconfirmed_alerts"].diff().dropna() <= 0).all(), thr
    for col in ["alerts", "median_detection_delay_weeks", "unconfirmed_rate", "episode_exposure_covered_share"]:
        assert col in s.columns


def test_false_positive_terminology(p9):
    fp = _csv(p9, "false_positive_analysis.csv")
    assert (fp["classification"] == "unconfirmed alert").all()
    assert {"isolated_alert", "alert_without_corroborating_evidence"} <= set(fp.columns)
    bt = _csv(p9, "alert_backtest_results.csv")
    for col in ["weeks_tested", "alerts", "alert_rate", "entities_affected", "repeat_alert_entities", "isolated_alerts",
                "persistent_episodes_4w", "episode_entities_detected", "unconfirmed_rate", "median_alert_duration_weeks"]:
        assert col in bt.columns
    text = " ".join(open(p, encoding="utf-8").read() for p in [p9["out"] / "phase9_executive_summary.md", DOC]).lower()
    text = re.sub(r"\s+", " ", text)
    assert "confirmed false positive" not in text.replace("nothing is called a confirmed false positive", "")


def test_exposure_never_summed_across_signals(p9):
    s = _csv(p9, "alert_summary.csv")
    assert "TOTAL" not in set(s["signal"]) and "All" not in set(s["signal"])
    assert s["exposure_note"].str.contains("never add").all()


# ----------------------------------------------------------------------------- determinism, independence, text
def test_deterministic_output(p9, cfg):
    E2 = run_phase9.evaluate(p9["T"], p9["B"], cfg)
    a = p9["E"]["alerts"].reset_index(drop=True)
    b = E2["alerts"].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(p9["E"]["results"].reset_index(drop=True), E2["results"].reset_index(drop=True))


def test_committed_outputs_match_fresh_run(p9):
    for f in ["weekly_alerts.csv", "alert_summary.csv", "alert_backtest_results.csv", "threshold_sensitivity.csv",
              "signal_dictionary.csv", "s03_s05_detection.csv", "false_positive_analysis.csv", "baseline_comparison.csv",
              "phase9_executive_summary.md"]:
        a = (p9["out"] / f).read_text(encoding="utf-8")
        b = (OUT / f).read_text(encoding="utf-8")
        assert a == b, f


# ============================================================ evaluation-isolation policy (regression)
# The virtual environment lives inside the project root, so its bytecode cache is swept up by the
# underscore rule that blocks answer-key files. These tests pin the classification that separates
# Python import reads from the active interpreter environment from real project-data violations.
def test_environment_import_reads_are_not_false_positives():
    from src.monitoring.access import is_environment_read
    for rel in (env_path("Lib", "site-packages", "duckdb", "__pycache__", "_version.cpython-314.pyc"),
                env_path("Lib", "site-packages", "duckdb", "__pycache__", "_dbapi_type_object.cpython-314.pyc"),
                env_path("Lib", "site-packages", "sqlglot", "__pycache__", "_typing.cpython-314.pyc"),
                env_path("Lib", "site-packages", "sqlglot", "__pycache__", "_version.cpython-314.pyc"),
                env_path("Lib", "site-packages", "numpy", "_core", "__pycache__", "_multiarray_umath.cpython-314.pyc")):
        assert is_environment_read(rel), rel


@pytest.mark.parametrize("rel,label", [
    ("reports/evaluation/answer.csv", "evaluation directory"),
    ("data/raw/planted.csv", "raw directory"),
    ("data/sample/demo.csv", "sample directory"),
    ("data/quarantine/q.csv", "quarantine directory"),
])
def test_evaluation_directories_are_still_refused(rel, label):
    from src.monitoring.access import is_environment_read
    assert not is_environment_read(rel), label


@pytest.mark.parametrize("rel", [
    "config/_hidden_scenario.yaml",
    "config/_scenario_answer_key.csv",
    "data/processed/curated/_planted_issues_log.csv",
    "reports/phase9/_hidden_scenario.yaml",
])
def test_named_answer_key_files_are_still_refused(rel):
    from src.analytics.model_access import _is_refused
    from src.monitoring.access import is_environment_read
    assert _is_refused(rel), rel
    assert not is_environment_read(rel), rel


@pytest.mark.parametrize("rel", [
    ".venv/_hidden_scenario.yaml",
    ".venv/Lib/site-packages/_scenario_answer_key.csv",
    ".venv/Lib/site-packages/_planted_issues_log.csv",
])
def test_answer_keys_hidden_inside_the_environment_are_still_refused(rel):
    """The environment exemption must not become a hiding place for answer keys."""
    from src.monitoring.access import is_environment_read
    assert not is_environment_read(rel), rel


@pytest.mark.parametrize("rel", [
    "config/_hidden_scenario.yaml.bak",
    "data/_planted_issues_log.csv.gz",
    ".venv/Lib/site-packages/_scenario_answer_key.csv.txt",
])
def test_disguised_answer_key_files_are_still_refused(rel):
    """Renaming or re-suffixing an answer key must not evade the policy."""
    from src.monitoring.access import is_environment_read
    assert not is_environment_read(rel), rel


def test_a_pyc_suffix_alone_never_grants_exemption():
    """Requirement: the fix is not a '*.pyc' exclusion. A project file is judged on its location
    and markers, not its extension."""
    from src.monitoring.access import is_environment_read
    # inside the environment but not an answer key -> environment read
    assert is_environment_read(env_path("Lib", "site-packages", "pkg", "__pycache__", "_mod.cpython-314.pyc"))
    # same extension, but in project data -> never exempt, and refused by the underscore rule
    assert not is_environment_read("data/processed/curated/_planted_issues_log.pyc")
    assert not is_environment_read("data/processed/curated/_secret.pyc")
    # a .pyc in a governed project dir that is NOT underscore-prefixed is not refused, but it is
    # certainly not an environment read either
    assert not is_environment_read("data/processed/curated/fact_sales.pyc")


def test_no_governed_project_directory_lies_under_the_environment_roots():
    """Structural proof that the exemption cannot cover project data."""
    from src.analytics.model_access import PROJECT_ROOT
    from src.monitoring.access import environment_roots, is_environment_read
    roots = environment_roots()
    assert roots, "no interpreter environment root resolved"
    for governed in ("data", "reports", "config", "src", "tests", "docs", "sql", "powerbi"):
        for root in roots:
            target = (PROJECT_ROOT / governed).resolve()
            assert not (target == root or root in target.parents), governed
        assert not is_environment_read(f"{governed}/anything.csv")
        assert not is_environment_read(f"{governed}/_private.csv")


def test_classify_opened_keeps_project_violations_and_splits_runtime_reads():
    from src.monitoring.access import classify_opened
    opened = {
        "count": 4,
        "project_files": ["data/processed/curated/fact_sales.csv", "reports/phase3/dq_issue_log.csv"],
        "written": [],
        "refused": [env_path("Lib", "site-packages", "sqlglot", "__pycache__", "_typing.cpython-314.pyc"),
                    "data/processed/curated/_planted_issues_log.csv",
                    env_path("_hidden_scenario.yaml")],
    }
    out = classify_opened(opened)
    # an evaluation-only name stays refused even inside the environment
    assert out["refused"] == sorted(["data/processed/curated/_planted_issues_log.csv", env_path("_hidden_scenario.yaml")])
    assert out["runtime_reads"] == [env_path("Lib", "site-packages", "sqlglot", "__pycache__", "_typing.cpython-314.pyc")]
    # project-input recording is untouched
    assert out["project_files"] == opened["project_files"]
    assert out["count"] == opened["count"]


def test_classify_opened_is_a_no_op_when_nothing_was_refused():
    from src.monitoring.access import classify_opened
    opened = {"count": 623, "project_files": ["config/monitoring_config.yaml"], "written": [], "refused": []}
    out = classify_opened(opened)
    assert out["refused"] == [] and out["runtime_reads"] == []


def test_openrecorder_still_records_real_project_reads(p9):
    """The recorder itself is untouched: normal project-input reads are still captured."""
    o = p9["opened"]
    assert len(o["project_files"]) > 50
    assert "data/processed/curated/fact_sales.csv" in o["project_files"]
    assert "reports/phase3/dq_issue_log.csv" in o["project_files"]
    assert "config/monitoring_config.yaml" in o["project_files"]


def test_no_evaluation_file_opened(p9):
    o = p9["opened"]
    assert not o["refused"]
    assert not any("answer_key" in p or "planted" in p or "hidden_scenario" in p or "calibration" in p
                   for p in o["project_files"])


def test_no_causal_overstatement_or_em_dash(p9):
    parts = [(p9["out"] / f).read_text(encoding="utf-8") for f in BRIEF_FILES]
    parts += [DOC.read_text(encoding="utf-8"), (ROOT / "README.md").read_text(encoding="utf-8"),
              (ROOT / "config" / "monitoring_config.yaml").read_text(encoding="utf-8")]
    review = OUT / "phase9_independent_review.md"
    if review.exists():
        parts.append(review.read_text(encoding="utf-8"))
    text = "\n".join(parts)
    assert "\u2014" not in text
    low = text.lower()
    for bad in ["supplier defect detected", "voltix caused", "promotions caused the", "competitor caused",
                "deployed in production", "is in production"]:
        assert bad not in low, bad
    assert "not deployed" in DOC.read_text(encoding="utf-8").lower() or "nothing is deployed" in DOC.read_text(encoding="utf-8").lower()
