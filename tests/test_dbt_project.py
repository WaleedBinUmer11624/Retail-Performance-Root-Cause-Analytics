"""dbt port of the governed layer (dbt/): a reconciled port, not a replacement.

Offline checks always run: the generated star-schema models match the governed T-SQL, every one of the
85 Phase 3 rules is a dbt test whose expectation equals Phase 3's own result, the dbt variables and seed
mirror the governed configuration, and no credential or evaluation-only file is referenced.

The live checks run `dbt build` into a temporary folder and assert the governed figures. They skip
cleanly when dbt is not installed (found through the RPCA_DBT environment variable, a sibling virtual
environment ../rpca-dbt-venv as README describes, or PATH) or when the raw and curated data are absent.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt"
DQ_RESULTS = ROOT / "reports" / "phase3" / "dq_rule_results.csv"
DQ_CFG = yaml.safe_load((ROOT / "config" / "dq_config.yaml").read_text(encoding="utf-8"))
SQL_CFG = yaml.safe_load((ROOT / "config" / "sql_model_config.yaml").read_text(encoding="utf-8"))
PROJECT = yaml.safe_load((DBT_DIR / "dbt_project.yml").read_text(encoding="utf-8"))
RULE_FILES = [DBT_DIR / "models" / "staging" / "raw" / "_models.yml",
              DBT_DIR / "models" / "intermediate" / "dq" / "_models.yml"]


def phase3_results() -> dict:
    with open(DQ_RESULTS, encoding="utf-8") as fh:
        return {r["rule_id"]: (int(r["rows_failed"]), int(r["rows_checked"])) for r in csv.DictReader(fh)}


def dbt_expectations() -> list:
    """(rule_id, failed, checked, where) for every data-quality test in the dbt project."""
    out = []
    for path in RULE_FILES:
        for model in yaml.safe_load(path.read_text(encoding="utf-8"))["models"]:
            for test in model.get("data_tests", []):
                (args,) = [v["arguments"] for v in test.values()]
                out.append((args["rule_id"], int(args["failed"]), int(args["checked"]), path.name))
    for path in sorted((DBT_DIR / "tests" / "dq").glob("*.sql")):
        m = re.search(r"dq_result\('([A-Z]+-\d+)', (\d+), (\d+),", path.read_text(encoding="utf-8"))
        assert m, path
        out.append((m.group(1), int(m.group(2)), int(m.group(3)), path.name))
    return out


# ============================================================ offline (always)
def test_every_phase3_rule_is_one_dbt_test_with_phase3_expectations():
    expected = phase3_results()
    found = dbt_expectations()
    ids = [r for r, *_ in found]
    assert len(expected) == 85
    assert sorted(ids) == sorted(expected), "every rule exactly once"
    for rule, failed, checked, where in found:
        assert (failed, checked) == expected[rule], f"{rule} in {where}"


def stale_generated_files(script: str) -> list:
    """Committed files that differ from what the generator script in dbt/scripts would write now."""
    sys.path.insert(0, str(DBT_DIR / "scripts"))
    try:
        gen = __import__(script)
    finally:
        sys.path.pop(0)
    return [p.relative_to(ROOT).as_posix() for p, text in gen.build().items()
            if not p.exists() or p.read_bytes().decode("utf-8") != text]


def test_generated_models_match_the_governed_tsql():
    stale = stale_generated_files("generate_governed_models")
    assert not stale, f"regenerate with python dbt/scripts/generate_governed_models.py: {stale}"


def test_generic_rule_tests_match_their_generator():
    stale = stale_generated_files("generate_dq_rule_tests")
    assert not stale, f"regenerate with python dbt/scripts/generate_dq_rule_tests.py: {stale}"


def test_contract_seed_mirrors_dq_config():
    with open(DBT_DIR / "seeds" / "dq_contract.csv", encoding="utf-8") as fh:
        seed = [(r["table_name"], r["column_name"], r["contract_type"]) for r in csv.DictReader(fh)]
    cfg = [(t, c, k) for t in DQ_CFG["inputs"] for c, k in DQ_CFG["contract"][t]["types"].items()]
    assert seed == cfg


def test_project_vars_mirror_the_governed_configuration():
    v, tol, tim, dom = PROJECT["vars"], DQ_CFG["tolerances"], DQ_CFG["timeliness"], DQ_CFG["domains"]
    assert v["period_start"] == str(DQ_CFG["period"]["start"]) and v["period_end"] == str(DQ_CFG["period"]["end"])
    pairs = {"money_tolerance": "money", "price_reference_tolerance": "price_reference",
             "decimal_shift_ratio": "decimal_shift_ratio", "max_plausible_line_quantity": "max_plausible_line_quantity",
             "max_discount_share": "max_discount_share", "target_outlier_ratio": "target_outlier_ratio",
             "target_decimal_shift_band": "target_decimal_shift_band", "low_volume_day_ratio": "low_volume_day_ratio"}
    for var, key in pairs.items():
        assert v[var] == tol[key], var
    assert v["expected_max_lag_days"] == tim["expected_max_lag_days"]
    assert v["return_policy_days"] == tim["return_policy_days"]
    assert v["christmas_return_window"] == tim["christmas_return_window"]
    for var, key in {"categories": "categories", "regions": "regions", "store_formats": "store_formats",
                     "return_reasons": "return_reasons", "promotion_types": "promotion_types",
                     "product_status": "product_status"}.items():
        assert v[var] == dom[key], var
    assert v["recon_tolerances"] == SQL_CFG["tolerances"]
    assert v["kpi_tolerance_class"] == SQL_CFG["kpi_tolerance_class"]
    assert v["curated_tables"] == SQL_CFG["inputs"]["curated_tables"]
    assert v["dq_failed_offset"] == 0


def test_no_credentials_and_build_outputs_are_git_ignored():
    profiles = (DBT_DIR / "profiles.yml").read_text(encoding="utf-8")
    for word in ("keyfile", "password", "token", "client_secret", "private_key"):
        assert word not in profiles.lower(), word
    assert "method: oauth" in profiles and "env_var('BQ_PROJECT_ID'" in profiles
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in ("dbt/target/", "dbt/logs/", "dbt/*.duckdb"):
        assert entry in ignored, entry


def test_dbt_project_never_names_evaluation_only_files():
    banned = ("_scenario_answer_key", "_planted_issues_log", "_hidden_scenario", "evaluation/", "calibration")
    for path in DBT_DIR.rglob("*"):
        if path.is_file() and path.suffix in (".sql", ".yml", ".py", ".md", ".csv") and "target" not in path.parts:
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                assert word not in text, f"{word} in {path.relative_to(ROOT)}"


# ============================================================ live: dbt build (skips without dbt or data)
def find_dbt():
    exe = "dbt.exe" if os.name == "nt" else "dbt"
    candidates = [os.environ.get("RPCA_DBT"),
                  ROOT.parent / "rpca-dbt-venv" / ("Scripts" if os.name == "nt" else "bin") / exe,
                  shutil.which("dbt")]
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


def dbt_command(dbt, args, work, extra_env=None):
    env = {**os.environ, "RPCA_DBT_DUCKDB_PATH": str(work / "brightwater_dbt.duckdb"),
           "DBT_SEND_ANONYMOUS_USAGE_STATS": "false", **(extra_env or {})}
    cmd = [dbt, *args, "--profiles-dir", ".", "--target-path", str(work / "target"), "--log-path", str(work / "logs")]
    return subprocess.run(cmd, cwd=DBT_DIR, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=1800)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    dbt = find_dbt()
    if not dbt:
        pytest.skip("dbt is not installed (set RPCA_DBT, or create ../rpca-dbt-venv from requirements-dbt.txt)")
    needed = [ROOT / "data" / "raw" / "fact_sales.csv", ROOT / "data" / "processed" / "curated" / "fact_sales.csv"]
    if not all(p.exists() for p in needed):
        pytest.skip("raw and curated data not present (README Steps 4 and 5)")
    work = tmp_path_factory.mktemp("dbt")
    run = dbt_command(dbt, ["build"], work)
    results = json.loads((work / "target" / "run_results.json").read_text(encoding="utf-8")) \
        if (work / "target" / "run_results.json").exists() else {"results": []}
    return {"dbt": dbt, "work": work, "run": run, "results": results["results"]}


def query(built, sql):
    """Rows of one query on the build's DuckDB file; the connection is closed again so dbt can reopen the file."""
    if built["run"].returncode != 0:
        pytest.skip("build failed; reported by test_dbt_build_passes_and_every_node_ran")
    import duckdb
    con = duckdb.connect(str(built["work"] / "brightwater_dbt.duckdb"), read_only=True)
    try:
        return con.sql(sql).fetchall()
    finally:
        con.close()


def test_dbt_build_passes_and_every_node_ran(built):
    assert built["run"].returncode == 0, built["run"].stdout[-3000:]
    res = built["results"]
    assert len(res) == 163, "72 models, 1 seed, 90 tests"
    assert all(r["status"] in ("success", "pass") for r in res)
    tests = [r for r in res if r["unique_id"].startswith("test.")]
    assert len(tests) == 90
    assert len([r for r in tests if ".dq_" in r["unique_id"]]) == 85


def test_dq_failure_counts_equal_phase3(built):
    expected = phase3_results()
    union = " union all ".join(f"select '{r}', count(*) from dq_audit.\"dq_{r.replace('-', '_')}\"" for r in expected)
    counts = dict(query(built, union))
    for rule, (failed, _) in expected.items():
        assert counts[rule] == failed, rule


def test_reconciliation_45_of_45_and_kpi_validation_38_of_38(built):
    assert query(built, "select status, count(*) from recon.v_reconciliation group by 1") == [("PASS", 45)]
    assert query(built, "select status, count(*) from recon.kpi_validation_result group by 1") == [("PASS", 38)]


def test_headline_h1_and_h2_2025(built):
    rows = {p: (float(n), float(y)) for p, n, y in query(
        built, "select period, net_revenue_cy, net_revenue_yoy_pct from mart.v_yoy_segment_period "
               "where segment_type = 'Estate' and retail_year = 2025 and period in ('H1', 'H2')")}
    assert rows["H2"][0] == pytest.approx(9457457.05, abs=0.005) and round(rows["H2"][1], 2) == -7.18
    assert rows["H1"][0] == pytest.approx(8629984.78, abs=0.005) and round(rows["H1"][1], 3) == 1.438


def test_same_figures_as_the_governed_duckdb_build(built):
    with open(ROOT / "reports" / "phase4" / "reconciliation_results_duckdb.csv", encoding="utf-8") as fh:
        governed = {r["metric_name"]: float(r["actual_value"]) for r in csv.DictReader(fh)}
    dbt_vals = dict(query(built, "select metric_name, actual_value from recon.v_reconciliation"))
    assert set(dbt_vals) == set(governed)
    for name, value in governed.items():
        assert dbt_vals[name] == pytest.approx(value, abs=1e-6), name
    for money in ("gross_sales", "discount_value", "sales_revenue", "returns_value", "net_revenue", "cogs", "gross_margin"):
        assert round(dbt_vals[money], 2) == round(governed[money], 2), money


def test_a_wrong_expectation_fails_the_build(built):
    if built["run"].returncode != 0:
        pytest.skip("build failed; reported by test_dbt_build_passes_and_every_node_ran")
    run = dbt_command(built["dbt"], ["test", "--select", "dq_FS_09", "--vars", "{dq_failed_offset: 1}"], built["work"])
    assert run.returncode != 0
    assert "Got 40 results, configured to fail if !=41" in run.stdout
