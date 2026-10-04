"""Phase 7 inputs: whitelist, Phase 1-6 freeze, model and Power BI SQL views.

Phase 7 opens files only through `allowed_path`: the files named in config/powerbi_config.yaml
(inputs.allowed_files) and the frozen Phase 1-6 files (Phase 1-4 list in config/analytics_config.yaml,
Phase 5 list in config/rca_config.yaml, Phase 6 list in config/powerbi_config.yaml). Anything
underscore-prefixed or under an evaluation, raw, sample or quarantine folder is refused.
"""
from __future__ import annotations

import fnmatch
import time
from pathlib import Path

import pandas as pd
import yaml

from src.analytics.model_access import PROJECT_ROOT, InputError, _is_refused, fetch, open_model, sha256_normalised

PBI_SCHEMA = "pbi"


def _read_yaml(rel: str) -> dict:
    if _is_refused(rel) or not rel.startswith("config/"):
        raise InputError(f"{rel} is not an approved Phase 7 configuration file")
    return yaml.safe_load((PROJECT_ROOT / rel).read_text(encoding="utf-8"))


def load_config() -> dict:
    return {"powerbi": _read_yaml("config/powerbi_config.yaml"), "rca": _read_yaml("config/rca_config.yaml"),
            "analytics": _read_yaml("config/analytics_config.yaml"), "project": _read_yaml("config/project_config.yaml"),
            "sql_model": _read_yaml("config/sql_model_config.yaml")}


def _patterns(cfg: dict) -> list[str]:
    return (list(cfg["analytics"]["inputs"]["frozen_inputs"]) + list(cfg["rca"]["inputs"]["phase5_frozen"]) +
            list(cfg["powerbi"]["inputs"]["phase6_frozen"]))


def allowed_path(rel: str, cfg: dict) -> Path:
    rel = rel.replace("\\", "/")
    if _is_refused(rel):
        raise InputError(f"{rel} is not an approved Phase 7 input (evaluation-only or raw asset)")
    if rel not in set(cfg["powerbi"]["inputs"]["allowed_files"]) and not any(fnmatch.fnmatch(rel, p) for p in _patterns(cfg)):
        raise InputError(f"{rel} is not an approved Phase 7 input")
    return PROJECT_ROOT / rel


def read_csv(rel: str, cfg: dict) -> pd.DataFrame:
    return pd.read_csv(allowed_path(rel, cfg))


def read_text(rel: str, cfg: dict) -> str:
    return allowed_path(rel, cfg).read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- freeze
def frozen_files(cfg: dict) -> list[str]:
    out = set()
    for pattern in _patterns(cfg):
        hits = [p.relative_to(PROJECT_ROOT).as_posix() for p in PROJECT_ROOT.glob(pattern) if p.is_file()]
        if not hits:
            raise InputError(f"frozen pattern {pattern} matches no file")
        out |= {h for h in hits if not _is_refused(h)}
    return sorted(out)


def record_freeze(cfg: dict) -> pd.DataFrame:
    rows = [{"file": f, "sha256": sha256_normalised(PROJECT_ROOT / f), "bytes": (PROJECT_ROOT / f).stat().st_size}
            for f in frozen_files(cfg)]
    df = pd.DataFrame(rows)
    path = PROJECT_ROOT / cfg["powerbi"]["inputs"]["freeze_manifest"]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n")
    return df


def verify_freeze(cfg: dict) -> pd.DataFrame:
    """Every Phase 1-6 input and output must match the manifest recorded at the start of Phase 7. The Phase 6
    manifest (Phase 1-5 files) is re-verified as well, so a change to any earlier phase stops the run."""
    path = allowed_path(cfg["powerbi"]["inputs"]["freeze_manifest"], cfg)
    if not path.exists():
        raise InputError("Phase 7 freeze manifest missing: run python -m src.powerbi.run_phase7 --record-freeze once")
    man = pd.read_csv(path)
    rows = []
    for r in man.itertuples():
        p = PROJECT_ROOT / r.file
        got = sha256_normalised(p) if p.exists() else None
        rows.append({"file": r.file, "sha256_recorded": r.sha256, "sha256_now": got,
                     "status": "UNCHANGED" if got == r.sha256 else ("MISSING" if got is None else "CHANGED")})
    for extra in sorted(set(frozen_files(cfg)) - set(man["file"])):
        rows.append({"file": extra, "sha256_recorded": None, "sha256_now": sha256_normalised(PROJECT_ROOT / extra),
                     "status": "NEW"})
    df = pd.DataFrame(rows)
    bad = df[df["status"] != "UNCHANGED"]
    if len(bad):
        raise InputError("Phase 1-6 files changed since the Phase 7 freeze:\n" + bad.to_string(index=False))
    # the earlier phase's own manifest must still verify too (defence in depth)
    from src.rca.access import load_config as rca_cfg, verify_freeze as rca_verify
    rca_verify(rca_cfg())
    return df


# ----------------------------------------------------------------------------- model and SQL
def open_pbi_model(engine_name: str, cfg: dict, out_dir: Path):
    """Phase 4 model + the Phase 7 pbi views (the Power BI source layer). Returns (engine, info, sql_log)."""
    engine, info = open_model(engine_name, cfg["analytics"], cfg["project"], out_dir)
    if engine.name == "duckdb":
        engine.con.execute(f"CREATE SCHEMA IF NOT EXISTS {PBI_SCHEMA}")
    from src.sql_model.scripts import split_batches
    log = []
    for path in sorted((PROJECT_ROOT / cfg["powerbi"]["inputs"]["pbi_sql_dir"]).glob("[0-9][0-9]_*.sql")):
        t0 = time.time()
        batches = [b for b in split_batches(path) if b.runs_on(engine.name)]
        for b in batches:
            engine.run_batch(b)
        log.append({"script": path.relative_to(PROJECT_ROOT).as_posix(), "batches": len(batches),
                    "seconds": round(time.time() - t0, 2)})
    return engine, info, log


def query(engine, sql: str) -> pd.DataFrame:
    return fetch(engine, sql)
