"""Robustness: the ways a real visitor, reviewer or user can break the project, and what they see instead.

Each test reproduces one scenario from the robustness audit (website and chat checks run in a browser in
tests/test_web_robustness.py). Setup scenarios run the real commands in a throwaway copy whose path
contains spaces; nothing in the repository is changed, and evaluation-only files are never copied.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _code_without_comments(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line.split("//")[0] if not line.strip().startswith(("\"", "'")) else line for line in text.splitlines())


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("BQ_PROJECT_ID",)}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# ============================================================ chat assistant
def test_chat_never_inserts_typed_text_as_html():
    """Typed text is shown with textContent only: no HTML sink exists anywhere in the chat script."""
    code = _code_without_comments(ROOT / "docs" / "chatbot.js")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in code, sink


def test_analytics_accepts_only_short_fixed_event_names():
    """analytics.js drops any chat event that is not a short lower-case name, so typed text cannot be sent."""
    source = (ROOT / "docs" / "analytics.js").read_text(encoding="utf-8")
    pattern = re.search(r"var SAFE = /(.+?)/;", source).group(1).replace("\\/", "/")
    safe = re.compile(pattern)
    for name in ("ask/revenue-fall", "chatbot_conversational_response/engines", "chat-open", "chip/stores"):
        assert safe.fullmatch(name), name
    for typed in ("<img src=x onerror=alert(1)>", "why did revenue fall", "لماذا",
                  "\U0001F600", "x" * 200, "ask/../../etc", "Ask/Revenue"):
        assert not safe.fullmatch(typed), typed


# ============================================================ website data
def test_every_store_and_category_combination_has_data():
    data = json.loads((ROOT / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    stores = {s["store_id"] for s in data["stores"]}
    categories = {c["category"] for c in data["categories"]}
    have = {(r["store_id"], r["category"]) for r in data["store_category"]}
    assert {(s, c) for s in stores for c in categories} <= have


def test_dashboard_names_each_load_failure_and_survives_a_blocked_chart_library():
    page = (ROOT / "docs" / "dashboard.html").read_text(encoding="utf-8")
    assert 'id="charts-error"' in page and 'typeof window.Chart === "undefined"' in page
    for reason in ("file:", "load:", "shape:"):
        assert reason in page, reason


# ============================================================ setup on a reviewer's machine
def test_hash_check_finds_the_project_wherever_it_is_cloned():
    """The protected-hash check used to point at the author's drive (E:); it now uses its own location."""
    for script in sorted((ROOT / "tmp").glob("*.py")):
        roots = [ln for ln in script.read_text(encoding="utf-8").splitlines() if re.match(r"\s*ROOT\s*=", ln)]
        assert not any(re.search(r"[A-Za-z]:\\|[A-Za-z]:/", ln) for ln in roots), (script.name, roots)
    out = subprocess.run([PY, str(ROOT / "tmp" / "hash_check.py")], capture_output=True, text=True, env=_clean_env(), timeout=300)
    assert "OVERALL:" in out.stdout and "Traceback" not in out.stderr, out.stderr[-500:]


def test_code_parses_on_python_3_10_and_later():
    """An older Python fails at package installation, not on this project's syntax."""
    files = [p for d in ("src", "tmp", "tests", "experimental") for p in (ROOT / d).rglob("*.py")]
    bad = []
    for p in files:
        try:
            ast.parse(p.read_text(encoding="utf-8"), feature_version=(3, 10))
        except SyntaxError as e:
            bad.append(f"{p.relative_to(ROOT)}:{e.lineno}")
    assert files and not bad, bad


def test_power_query_csv_imports_are_independent_of_the_windows_locale():
    """A decimal-comma locale cannot change the dashboard's numbers: every CSV import pins the en-US culture."""
    for pq in sorted((ROOT / "powerbi" / "power_query").glob("*.pq")):
        text = pq.read_text(encoding="utf-8")
        if "Csv.Document" in text and "TransformColumnTypes" in text:
            assert '"en-US"' in text, pq.name


def test_phase4_without_generated_data_names_the_missing_file(tmp_path):
    """Running Phase 4 before generating data stops at the first missing curated file (KI-08). Also shows a
    clone path with spaces works: the copy below lives in 'my clone with spaces'."""
    clone = tmp_path / "my clone with spaces"
    ignore = shutil.ignore_patterns("__pycache__", "_*")          # never copy evaluation-only files
    for folder in ("src", "sql"):
        shutil.copytree(ROOT / folder, clone / folder, ignore=ignore)
    (clone / "config").mkdir()
    for name in ("sql_model_config.yaml", "project_config.yaml"):
        shutil.copy2(ROOT / "config" / name, clone / "config" / name)
    (clone / "reports" / "phase3").mkdir(parents=True)
    for name in ("lineage.json", "kpi_reconciliation.csv"):
        shutil.copy2(ROOT / "reports" / "phase3" / name, clone / "reports" / "phase3" / name)
    out = subprocess.run([PY, "-m", "src.sql_model.run_model", "--engine", "duckdb"], cwd=clone,
                         capture_output=True, text=True, env=_clean_env(), timeout=300)
    assert out.returncode != 0
    assert "FileNotFoundError" in out.stderr and "curated" in out.stderr and "dim_date.csv" in out.stderr


def test_readme_explains_each_setup_failure():
    for phrase in ("FileNotFoundError", "opened directly from disk", "Chart.js", "Python 3.14",
                   "expire after 60 days", "rpt", "KI-08"):
        assert phrase in README, phrase


# ============================================================ optional engines
def test_paginated_tests_name_the_missing_rpt_views():
    text = (ROOT / "tests" / "test_paginated_reports.py").read_text(encoding="utf-8")
    assert "rpt views not created; run sql/reporting/01_rpt_views.sql" in text
    assert "run it after each SQL Server build" in README


@pytest.mark.parametrize("args", [[], ["--teardown"]])
def test_bigquery_without_a_project_gives_one_instruction(args):
    if (ROOT / "config" / "bigquery_local.yaml").exists():
        pytest.skip("a local BigQuery project is configured on this machine")
    out = subprocess.run([PY, "-m", "src.bigquery_model.run_bigquery", *args], cwd=ROOT, capture_output=True, text=True,
                         env=_clean_env(), timeout=120)
    text = out.stdout + out.stderr
    assert out.returncode != 0 and "No BigQuery project ID" in text and "Traceback" not in text, text[-500:]


def test_bigquery_missing_client_is_named(monkeypatch):
    import builtins
    from src.bigquery_model import settings
    real_import = builtins.__import__

    def no_google(name, *a, **k):
        if name.startswith("google"):
            raise ImportError(name)
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_google)
    assert "requirements-bigquery.txt" in settings.credentials_problem()


def test_expired_sandbox_tables_ask_for_a_rebuild():
    from src.bigquery_model.engine import BigQueryEngine
    from src.bigquery_model.settings import build_problem

    class Gone:
        def get_table(self, table_id):
            raise LookupError("Not found: table expired")

    class Present:
        def get_table(self, table_id):
            return object()
    expired = BigQueryEngine("proj", "p_", "EU", 1, client=Gone())
    message = build_problem(expired)
    assert "expire after 60 days" in message and "run_bigquery" in message
    assert build_problem(BigQueryEngine("proj", "p_", "EU", 1, client=Present())) is None
