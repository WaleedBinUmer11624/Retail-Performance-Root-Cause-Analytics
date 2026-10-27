"""Robustness audit round 2: the ways a reviewer, a data engineer or a recruiter can trip over the parts added
since the first audit (the data release, the reviewer path, the dbt port and its published docs), and what
they see instead. Browser checks for the chat and the published dbt docs are in tests/test_web_robustness.py.

Every dbt scenario runs the real dbt in a throwaway folder (inputs pointed at a temporary project root, a
temporary DuckDB file and target folder), so nothing in the repository is changed. The dbt scenarios skip
cleanly when dbt is not installed; the link check of the release download skips when offline.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from tests.test_dbt_project import find_dbt

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
README = (ROOT / "README.md").read_text(encoding="utf-8")
PAGES = "https://waleedbinumer11624.github.io/Retail-Performance-Root-Cause-Analytics/"
REPO = "https://github.com/WaleedBinUmer11624/Retail-Performance-Root-Cause-Analytics/"
RELEASE = REPO + "releases/download/v1.0-data/brightwater_raw_data.zip"
RAW = ["dim_store", "dim_product", "dim_date", "fact_sales", "fact_sales_late_batch", "fact_inventory", "fact_returns",
       "fact_promotions", "fact_targets"]


# ============================================================ links (README, site pages, chat)
def _links() -> list[tuple[str, str]]:
    """(where, link) for every link in the README, the two site pages and the chat's link constants."""
    out = [("README.md", u) for u in re.findall(r"\]\(([^)\s]+)\)", README)]
    out += [("README.md", u) for u in re.findall(r"https://[^\s\"'`)<>]+", README)]
    for page in ("index.html", "dashboard.html"):
        html = (DOCS / page).read_text(encoding="utf-8")
        out += [(f"docs/{page}", u) for u in re.findall(r'(?:href|src)="([^"]+)"', html)]
    chat = (DOCS / "chatbot.js").read_text(encoding="utf-8")
    out += [("docs/chatbot.js", u) for u in re.findall(r'(?:ENGINES_DOC|DBT_DOCS) = "([^"]+)"', chat)]
    out += [("docs/chatbot.js", u) for u in re.findall(r'\["[^"]+", "(paginated/[^"]+)"', chat)]
    return out


def _local_target(where: str, link: str) -> Path | None:
    """The file a project link must resolve to, or None for anchors and third-party sites."""
    link = link.split("#")[0].split("?")[0]
    if not link or link.startswith(("mailto:", "javascript:", "data:")):
        return None
    if link.startswith(PAGES):
        rel = link[len(PAGES):]
        return DOCS / (rel + "index.html" if rel == "" or rel.endswith("/") else rel)
    m = re.match(re.escape(REPO) + r"(?:blob|tree)/main/(.*)", link)
    if m:
        return ROOT / m.group(1)
    if link.startswith(("http://", "https://", "//")):
        return None                                        # third-party (LinkedIn, CDNs, analytics) or the release download
    base = ROOT if where == "README.md" else DOCS
    target = base / link
    return target / "index.html" if link.endswith("/") else target


def test_site_and_readme_links_resolve():
    """Every project link in the README, on index.html and dashboard.html, and in the chat resolves to a file in
    this commit, so the published site (GitHub Pages serves docs/) and the GitHub links cannot 404."""
    checked, broken = 0, []
    for where, link in _links():
        target = _local_target(where, link)
        if target is None:
            continue
        checked += 1
        if not target.exists():
            broken.append(f"{where}: {link}")
    assert checked >= 40, checked
    assert not broken, broken


def test_release_download_is_live():
    """The data release named in README Step 4 is downloadable (a HEAD request; skipped offline)."""
    assert README.count(RELEASE) >= 2                      # Windows and Mac/Linux commands
    try:
        r = urllib.request.urlopen(urllib.request.Request(RELEASE, method="HEAD"), timeout=20)
    except OSError as err:
        if getattr(err, "code", None):
            raise
        pytest.skip(f"offline: {err}")
    assert r.status == 200


# ============================================================ README: data release and reviewer path
def test_readme_extract_commands_overwrite_and_extract_in_place():
    """Running Step 4 again must not fail on existing files, and the zip must land in the project folder itself."""
    assert "Expand-Archive brightwater_raw_data.zip -DestinationPath . -Force" in README
    assert "unzip -o brightwater_raw_data.zip -d ." in README
    assert "Extract All" in README and "data\\raw` must sit directly inside it" in README


def test_readme_step5_restores_reports_and_names_the_phase3_error():
    """Skipping the restore is documented (KI-10), and Phase 3 without the data has a troubleshooting row (KI-12)."""
    assert "python -m src.data_quality.run_dq" in README and "git checkout -- reports" in README
    assert "Phase 3 run and committed reports restored (git checkout -- reports)" in README
    assert "Phase 3 stops with `FileNotFoundError` for `data\\raw\\dim_store.csv`" in README
    ki = (ROOT / "docs" / "known_issues.md").read_text(encoding="utf-8")
    assert "## KI-10 " in ki and "## KI-12 " in ki


def test_phase3_without_the_data_names_the_missing_file(tmp_path):
    """KI-12: Phase 3 (frozen) run with the zip extracted into a subfolder stops at the first missing raw file.
    The copy lives in a folder whose name has spaces; evaluation-only files are never copied."""
    clone = tmp_path / "clone with spaces"
    ignore = shutil.ignore_patterns("__pycache__", "_*")
    for folder in ("src", "config"):
        shutil.copytree(ROOT / folder, clone / folder, ignore=ignore)
    (clone / "brightwater_raw_data" / "data" / "raw").mkdir(parents=True)      # Explorer's Extract All
    env = {k: v for k, v in os.environ.items() if k != "BQ_PROJECT_ID"}
    out = subprocess.run([sys.executable, "-m", "src.data_quality.run_dq"], cwd=clone, capture_output=True, text=True,
                         timeout=300, env=env)
    assert out.returncode != 0
    assert "FileNotFoundError" in out.stderr and "dim_store.csv" in out.stderr
    processed = clone / "data" / "processed"
    assert not [f for f in processed.rglob("*") if f.is_file()]               # no file half-written


# ============================================================ dbt port: static
def test_readme_path_c_has_commands_for_every_platform_and_its_own_environment():
    assert "..\\..\\rpca-dbt-venv\\Scripts\\dbt build --profiles-dir ." in README
    assert "../../rpca-dbt-venv/bin/dbt build --profiles-dir ." in README
    assert "own virtual environment" in README and "protobuf" in README
    req = (ROOT / "requirements-dbt.txt").read_text(encoding="utf-8")
    base = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pinned = re.search(r"^duckdb==([\d.]+)", req, re.M).group(1)
    minimum = re.search(r"^duckdb>=([\d.]+)", base, re.M).group(1)
    assert tuple(map(int, pinned.split("."))) >= tuple(map(int, minimum.split(".")))


def test_dbt_project_requires_dbt_1_10_and_checks_its_inputs():
    project = (ROOT / "dbt" / "dbt_project.yml").read_text(encoding="utf-8")
    assert 'require-dbt-version: [">=1.10.0", "<2.0.0"]' in project
    assert '"{{ check_inputs() }}"' in project


def test_non_duckdb_target_stops_at_parse():
    macro = (ROOT / "dbt" / "macros" / "generate_schema_name.sql").read_text(encoding="utf-8")
    assert "target.type != 'duckdb'" in macro and "src.bigquery_model.run_bigquery" in macro
    profiles = (ROOT / "dbt" / "profiles.yml").read_text(encoding="utf-8")
    assert "type: bigquery" in profiles and "keyfile" not in profiles


def test_a_stray_database_in_the_project_root_is_git_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/brightwater_dbt.duckdb" in ignored and "dbt/*.duckdb" in ignored


# ============================================================ publish_docs.py
def _publish():
    sys.path.insert(0, str(ROOT / "dbt" / "scripts"))
    try:
        import publish_docs
    finally:
        sys.path.pop(0)
    return publish_docs


def _fake_target(folder: Path, manifest_nodes: dict) -> Path:
    target = folder / "target"
    target.mkdir()
    (target / "index.html").write_text('<script>var m = "MANIFEST.JSON INLINE DATA"; var c = "CATALOG.JSON INLINE DATA";'
                                       "</script>", encoding="utf-8")
    meta = {"env": {}, "send_anonymous_usage_stats": False}
    (target / "manifest.json").write_text(json.dumps({"metadata": meta, "nodes": manifest_nodes}), encoding="utf-8")
    (target / "catalog.json").write_text(json.dumps({"metadata": dict(meta), "nodes": {}}), encoding="utf-8")
    return target


def test_publish_docs_before_dbt_docs_generate_gives_one_instruction(tmp_path):
    out = tmp_path / "site" / "index.html"
    with pytest.raises(SystemExit, match="dbt docs have not been generated.*dbt docs generate"):
        _publish().publish(tmp_path / "target", out)
    assert not out.exists()


@pytest.mark.parametrize("leak", ["/Users/alice/project/dbt", "/home/alice/project", "D:\\\\work\\\\project",
                                  "/Volumes/Data/project"])
def test_publish_docs_refuses_machine_paths_and_keeps_the_previous_page(tmp_path, leak):
    target = _fake_target(tmp_path, {"model.x": {"compiled_code": f"select * from read_csv('{leak}/a.csv')"}})
    out = tmp_path / "site" / "index.html"
    out.parent.mkdir()
    out.write_text("previous page", encoding="utf-8")
    with pytest.raises(SystemExit, match="machine details left"):
        _publish().publish(target, out)
    assert out.read_text(encoding="utf-8") == "previous page"
    assert not list(out.parent.glob("*.partial"))


def test_publish_docs_scrubs_root_path_and_writes_the_page(tmp_path):
    target = _fake_target(tmp_path, {"model.x": {"root_path": "C:\\somewhere\\dbt", "original_file_path": "models\\a.sql"}})
    out = tmp_path / "site" / "index.html"
    _publish().publish(target, out)
    page = out.read_text(encoding="utf-8")
    assert '"root_path":""' in page and '"original_file_path":"models/a.sql"' in page and "somewhere" not in page
    assert "INLINE DATA" not in page and not list(out.parent.glob("*.partial"))


# ============================================================ dbt port: live (skips without dbt)
@pytest.fixture(scope="module")
def dbt_exe():
    exe = find_dbt()
    if not exe:
        pytest.skip("dbt is not installed (set RPCA_DBT, or create ../rpca-dbt-venv from requirements-dbt.txt)")
    return exe


def _dbt(exe, work: Path, *args, cwd: Path = ROOT / "dbt", profiles: str = ".", project_root: Path | None = None):
    cmd = [exe, *args, "--profiles-dir", profiles, "--target-path", str(work / "target"), "--log-path", str(work / "logs")]
    if project_root is not None:
        cmd += ["--vars", json.dumps({"project_root": project_root.as_posix()})]
    env = {**os.environ, "RPCA_DBT_DUCKDB_PATH": str(work / "check.duckdb"), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    run = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=600)
    return run.returncode, run.stdout + run.stderr


def _fake_project(root: Path, raw: list[str] = (), curated: list[str] = ()) -> Path:
    (root / "dbt").mkdir(parents=True)
    (root / "dbt" / "dbt_project.yml").write_text("", encoding="utf-8")
    for rel in [f"data/raw/{t}.csv" for t in raw] + [f"data/processed/curated/{t}.csv" for t in curated]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("", encoding="utf-8")
    return root


def test_dbt_before_steps_4_and_5_gives_one_instruction(dbt_exe, tmp_path):
    rc, out = _dbt(dbt_exe, tmp_path, "run", "-s", "stg_raw__dim_store", project_root=_fake_project(tmp_path / "p"))
    assert rc != 0 and "The raw data is missing from data/raw" in out and "README Step 4" in out
    assert "IO Error" not in out                           # stopped before any model read a file


def test_dbt_names_a_zip_extracted_into_a_subfolder(dbt_exe, tmp_path):
    project = _fake_project(tmp_path / "p")
    nested = project / "brightwater_raw_data" / "data" / "raw"
    nested.mkdir(parents=True)
    (nested / "fact_sales.csv").write_text("", encoding="utf-8")
    rc, out = _dbt(dbt_exe, tmp_path, "run", "-s", "stg_raw__dim_store", project_root=project)
    assert rc != 0 and "extracted into a subfolder" in out and "brightwater_raw_data" in out


def test_dbt_before_phase3_names_step_5(dbt_exe, tmp_path):
    project = _fake_project(tmp_path / "p", raw=RAW)
    rc, out = _dbt(dbt_exe, tmp_path, "run", "-s", "stg_raw__dim_store", project_root=project)
    assert rc != 0 and "The curated data is missing" in out and "python -m src.data_quality.run_dq" in out


def test_dbt_from_the_project_root_says_cd_dbt(dbt_exe, tmp_path):
    rc, out = _dbt(dbt_exe, tmp_path, "run", "--project-dir", "dbt", "-s", "stg_raw__dim_store", cwd=ROOT, profiles="dbt")
    assert rc != 0 and "dbt must run from the dbt folder" in out and "cd dbt" in out


def test_dbt_bigquery_target_stops_before_connecting(dbt_exe, tmp_path):
    rc, out = _dbt(dbt_exe, tmp_path, "parse", "--target", "bigquery")
    if "Could not find adapter type bigquery" in out:
        pytest.skip("dbt-bigquery is not installed; the static check covers the guard")
    assert rc != 0 and "The dbt port runs on DuckDB only" in out


def test_dbt_names_a_locked_database(dbt_exe, tmp_path):
    """Another program holding the dbt database open: DuckDB's own message names the file and the cause."""
    import duckdb
    con = duckdb.connect(str(tmp_path / "check.duckdb"))
    try:
        rc, out = _dbt(dbt_exe, tmp_path, "run", "-s", "stg_raw__dim_store")
    finally:
        con.close()
    assert rc != 0 and "check.duckdb" in out
    assert "another process" in out or "lock" in out.lower()
    assert "Cannot open file ... brightwater_dbt.duckdb ... being used by another process" in README
