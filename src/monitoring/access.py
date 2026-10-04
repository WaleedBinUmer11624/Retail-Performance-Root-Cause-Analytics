"""Phase 9 inputs: whitelist, Phase 1-8 freeze (dependency manifest) and the monitoring SQL layer.

Phase 9 opens files only through `allowed_path`: files named in config/monitoring_config.yaml (inputs.allowed_files,
inputs.phase3_dq) and the frozen Phase 1-8 files. Anything underscore-prefixed or under an evaluation, raw, sample or
quarantine folder is refused, so no answer-key file can enter the pipeline.
"""
from __future__ import annotations

import fnmatch
import sys
import time
from pathlib import Path, PurePosixPath

import pandas as pd
import yaml

from src.analytics.model_access import PROJECT_ROOT, InputError, _is_refused, fetch, open_model, sha256_normalised

MON_SCHEMA = "mon"
VIEWS = ["week_calendar", "kpi_store_week", "kpi_category_week", "kpi_product_week", "kpi_store_category_week",
         "inventory_store_week", "returns_product_week"]


# ======================================================================== evaluation-isolation policy
# OpenRecorder (src/analytics/run_phase5.py, a Phase 5 governed module) refuses any path that has a
# single-underscore component. That rule exists to block answer-key files such as
# _hidden_scenario.yaml / _scenario_answer_key.csv / _planted_issues_log.csv. The virtual environment
# lives INSIDE the project root, so its bytecode cache is also "under the project" and is swept up by
# the same rule. Ordinary library modules whose names legitimately begin with one underscore
# (duckdb._version, duckdb._dbapi_type_object, sqlglot._typing, sqlglot._version) are therefore
# recorded as violations, even though they are Python import reads from the interpreter environment
# and not project data access.
#
# `classify_opened` separates those reads. The exemption is:
#   * rooted to the RESOLVED sys.prefix / sys.base_prefix of the running interpreter - never to a
#     file suffix, extension or glob, so a .pyc is not exempt merely for being a .pyc;
#   * refused outright for any evaluation-only marker, so an answer key placed inside the virtual
#     environment is still caught;
#   * incapable of covering project data: the environment roots are <project>/.venv and the base
#     interpreter directory, and no governed project directory (data, reports, config, src, tests,
#     docs, sql, powerbi) lies beneath either.
PROHIBITED_NAMES = frozenset({"_hidden_scenario.yaml", "_scenario_answer_key.csv", "_planted_issues_log.csv"})
PROHIBITED_DIRS = frozenset({"evaluation", "raw", "sample", "quarantine"})


def environment_roots() -> tuple[Path, ...]:
    """Resolved roots of the active interpreter environment.

    Deliberately excludes sys.path: the project root and the test root are on sys.path, so including
    it would exempt the entire project tree.
    """
    roots = []
    for raw in (sys.prefix, sys.base_prefix, sys.exec_prefix):
        try:
            roots.append(Path(raw).resolve())
        except (OSError, ValueError, RuntimeError):
            continue
    return tuple(dict.fromkeys(roots))


def _evaluation_marker(parts: tuple[str, ...]) -> bool:
    """True when the path carries an evaluation-only marker, whatever its extension or location."""
    if any(p.lower() in PROHIBITED_DIRS for p in parts):
        return True
    for part in parts:
        # a prohibited answer-key file is refused by name, and also when disguised by an extra
        # suffix such as _hidden_scenario.yaml.bak or _planted_issues_log.csv.pyc
        stem = part.split(".")[0].lower()
        if part.lower() in PROHIBITED_NAMES or stem in {n.split(".")[0] for n in PROHIBITED_NAMES}:
            return True
    return False


def is_environment_read(rel: str) -> bool:
    """True when a project-relative path is a Python import/runtime read from the active environment.

    Must be false for anything under a governed project directory, and false for any path carrying an
    evaluation-only marker.
    """
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if _evaluation_marker(parts):
        return False
    try:
        resolved = (PROJECT_ROOT / rel).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return any(resolved == root or root in resolved.parents for root in environment_roots())


def classify_opened(opened: dict) -> dict:
    """Split interpreter-environment import reads out of an OpenRecorder summary.

    'refused' keeps every project-data violation exactly as recorded; only reads that resolve inside
    the active interpreter environment and carry no evaluation-only marker move to 'runtime_reads'.
    The meaning of validation check V19 ("No evaluation-only or refused path opened") is unchanged:
    it still passes only when no evaluation-only path was opened.
    """
    runtime = sorted({p for p in opened.get("refused", []) if is_environment_read(p)})
    out = dict(opened)
    out["refused"] = sorted(set(opened.get("refused", [])) - set(runtime))
    out["runtime_reads"] = runtime
    return out


def _read_yaml(rel: str) -> dict:
    if _is_refused(rel) or not rel.startswith("config/"):
        raise InputError(f"{rel} is not an approved Phase 9 configuration file")
    return yaml.safe_load((PROJECT_ROOT / rel).read_text(encoding="utf-8"))


def load_config() -> dict:
    return {"monitoring": _read_yaml("config/monitoring_config.yaml"), "actions": _read_yaml("config/action_config.yaml"),
            "powerbi": _read_yaml("config/powerbi_config.yaml"), "rca": _read_yaml("config/rca_config.yaml"),
            "analytics": _read_yaml("config/analytics_config.yaml"), "project": _read_yaml("config/project_config.yaml"),
            "sql_model": _read_yaml("config/sql_model_config.yaml")}


def _patterns(cfg: dict) -> list[str]:
    return (list(cfg["analytics"]["inputs"]["frozen_inputs"]) + list(cfg["rca"]["inputs"]["phase5_frozen"]) +
            list(cfg["powerbi"]["inputs"]["phase6_frozen"]) + list(cfg["actions"]["inputs"]["phase7_frozen"]) +
            list(cfg["monitoring"]["inputs"]["phase8_frozen"]) + list(cfg["monitoring"]["inputs"]["phase3_dq"]))


def allowed_path(rel: str, cfg: dict) -> Path:
    rel = rel.replace("\\", "/")
    if _is_refused(rel):
        raise InputError(f"{rel} is not an approved Phase 9 input (evaluation-only or raw asset)")
    if rel not in set(cfg["monitoring"]["inputs"]["allowed_files"]) and not any(fnmatch.fnmatch(rel, p) for p in _patterns(cfg)):
        raise InputError(f"{rel} is not an approved Phase 9 input")
    return PROJECT_ROOT / rel


def read_csv(rel: str, cfg: dict, **kw) -> pd.DataFrame:
    return pd.read_csv(allowed_path(rel, cfg), **kw)


# ----------------------------------------------------------------------------- freeze / dependency manifest
def _phase_of(rel: str, cfg: dict) -> str:
    groups = [("Phase 1-4", cfg["analytics"]["inputs"]["frozen_inputs"]), ("Phase 5", cfg["rca"]["inputs"]["phase5_frozen"]),
              ("Phase 6", cfg["powerbi"]["inputs"]["phase6_frozen"]), ("Phase 7", cfg["actions"]["inputs"]["phase7_frozen"]),
              ("Phase 8", cfg["monitoring"]["inputs"]["phase8_frozen"]), ("Phase 3 DQ audit", cfg["monitoring"]["inputs"]["phase3_dq"])]
    for name, pats in groups:
        if any(fnmatch.fnmatch(rel, p) for p in pats):
            return name
    return "other"


def frozen_files(cfg: dict) -> list[str]:
    out = set()
    for pattern in _patterns(cfg):
        hits = [p.relative_to(PROJECT_ROOT).as_posix() for p in PROJECT_ROOT.glob(pattern) if p.is_file()]
        if not hits:
            raise InputError(f"frozen pattern {pattern} matches no file")
        out |= {h for h in hits if not _is_refused(h)}
    return sorted(out)


def record_freeze(cfg: dict) -> pd.DataFrame:
    rows = [{"file": f, "phase": _phase_of(f, cfg), "sha256": sha256_normalised(PROJECT_ROOT / f),
             "bytes": (PROJECT_ROOT / f).stat().st_size} for f in frozen_files(cfg)]
    df = pd.DataFrame(rows)
    path = PROJECT_ROOT / cfg["monitoring"]["inputs"]["freeze_manifest"]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n")
    return df


def verify_freeze(cfg: dict) -> pd.DataFrame:
    """Every Phase 1-8 file (and the Phase 3 DQ audit files Phase 9 reads) must match the dependency manifest
    recorded at the start of Phase 9. The Phase 8, 7 and 6 manifests are re-verified as well."""
    path = allowed_path(cfg["monitoring"]["inputs"]["freeze_manifest"], cfg)
    if not path.exists():
        raise InputError("Phase 9 dependency manifest missing: run python -m src.monitoring.run_phase9 --record-freeze once")
    man = pd.read_csv(path)
    rows = []
    for r in man.itertuples():
        p = PROJECT_ROOT / r.file
        got = sha256_normalised(p) if p.exists() else None
        rows.append({"file": r.file, "phase": r.phase, "sha256_recorded": r.sha256, "sha256_now": got,
                     "status": "UNCHANGED" if got == r.sha256 else ("MISSING" if got is None else "CHANGED")})
    for extra in sorted(set(frozen_files(cfg)) - set(man["file"])):
        rows.append({"file": extra, "phase": _phase_of(extra, cfg), "sha256_recorded": None,
                     "sha256_now": sha256_normalised(PROJECT_ROOT / extra), "status": "NEW"})
    df = pd.DataFrame(rows)
    bad = df[df["status"] != "UNCHANGED"]
    if len(bad):
        raise InputError("Phase 1-8 files changed since the Phase 9 freeze:\n" + bad.to_string(index=False))
    from src.actions.access import load_config as act_cfg, verify_freeze as act_verify
    act_verify(act_cfg())
    return df


# ----------------------------------------------------------------------------- monitoring layer
def load_monitoring_tables(engine_name: str, cfg: dict, out_dir: Path) -> tuple[dict, dict, list]:
    """Phase 4 model (DuckDB rebuild or SQL Server) + the mon views; returns (tables, build info, sql log)."""
    from src.sql_model.scripts import split_batches
    engine, info = open_model(engine_name, cfg["analytics"], cfg["project"], out_dir)
    try:
        if engine.name == "duckdb":
            engine.con.execute(f"CREATE SCHEMA IF NOT EXISTS {MON_SCHEMA}")
        log = []
        for path in sorted((PROJECT_ROOT / cfg["monitoring"]["inputs"]["monitoring_sql_dir"]).glob("[0-9][0-9]_*.sql")):
            t0 = time.time()
            batches = [b for b in split_batches(path) if b.runs_on(engine.name)]
            for b in batches:
                engine.run_batch(b)
            log.append({"script": path.relative_to(PROJECT_ROOT).as_posix(), "batches": len(batches),
                        "seconds": round(time.time() - t0, 2)})
        tables = {v: fetch(engine, f"SELECT * FROM {MON_SCHEMA}.{v}") for v in VIEWS}
    finally:
        engine.close()
    for t in tables.values():
        for c in ("run_time", "last_extract_timestamp"):
            if c in t.columns:
                t[c] = pd.to_datetime(t[c])
        for c in ("week_start", "week_end"):
            if c in t.columns:
                t[c] = pd.to_datetime(t[c])
    return tables, info, log
