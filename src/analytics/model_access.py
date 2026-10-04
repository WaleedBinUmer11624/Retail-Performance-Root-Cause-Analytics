"""Phase 5 inputs: whitelist, freeze manifest, the analytical model and the diagnostic SQL.

Independence rule: Phase 5 reads the Phase 4 governed model and nothing that describes how the data
was generated. Files are opened only through `allowed_path`, which accepts the files listed in
config/analytics_config.yaml (inputs.allowed_files) and the frozen Phase 1 to 4 inputs, and refuses
every file whose name starts with "_" or whose path runs through an evaluation folder. The model
itself is built by the Phase 4 runner (which verifies the curated files' SHA-256 against Phase 3
lineage) or, on SQL Server, read from the database Phase 4 built.
"""
from __future__ import annotations

import fnmatch
import hashlib
from decimal import Decimal
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".sql", ".py", ".md", ".yaml", ".yml", ".csv", ".json", ".txt", ".mmd"}


class InputError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- configuration
def load_config() -> tuple[dict, dict, dict]:
    """(analytics config, project config, Phase 4 model config)."""
    read = lambda rel: yaml.safe_load(allowed_path(rel, _bootstrap=True).read_text(encoding="utf-8"))  # noqa: E731
    return read("config/analytics_config.yaml"), read("config/project_config.yaml"), read("config/sql_model_config.yaml")


def _is_refused(rel: str) -> bool:
    parts = Path(rel.replace("\\", "/")).parts
    return any(p.startswith("_") and not p.startswith("__") for p in parts) or \
        any(p.lower() in ("evaluation", "raw", "sample", "quarantine") for p in parts)


def allowed_path(rel: str, cfg: dict | None = None, _bootstrap: bool = False) -> Path:
    """Resolve a project-relative path, refusing anything outside the Phase 5 whitelist."""
    rel = rel.replace("\\", "/")
    if _is_refused(rel):
        raise InputError(f"{rel} is not an approved Phase 5 input (evaluation-only or raw asset)")
    if _bootstrap and rel.startswith("config/") and rel.endswith(".yaml"):
        return PROJECT_ROOT / rel
    cfg = cfg or load_config()[0]
    allowed = set(cfg["inputs"]["allowed_files"])
    patterns = cfg["inputs"]["frozen_inputs"]
    if rel not in allowed and not any(fnmatch.fnmatch(rel, p) for p in patterns):
        raise InputError(f"{rel} is not an approved Phase 5 input")
    return PROJECT_ROOT / rel


# ----------------------------------------------------------------------------- freeze manifest
def sha256_normalised(path: Path) -> str:
    """SHA-256 of a file; text files are hashed with LF line endings so Windows checkouts verify too."""
    h = hashlib.sha256()
    if path.suffix.lower() in TEXT_SUFFIXES:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk.replace(b"\r\n", b"\n"))
    else:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
    return h.hexdigest()


def frozen_files(cfg: dict) -> list[str]:
    out = []
    for pattern in cfg["inputs"]["frozen_inputs"]:
        hits = sorted(p.relative_to(PROJECT_ROOT).as_posix() for p in PROJECT_ROOT.glob(pattern) if p.is_file())
        if not hits:
            raise InputError(f"frozen input pattern {pattern} matches no file")
        out += [h for h in hits if not _is_refused(h)]
    return sorted(set(out))


def record_freeze(cfg: dict) -> pd.DataFrame:
    rows = [{"file": f, "sha256": sha256_normalised(allowed_path(f, cfg)),
             "bytes": allowed_path(f, cfg).stat().st_size} for f in frozen_files(cfg)]
    df = pd.DataFrame(rows)
    path = PROJECT_ROOT / cfg["inputs"]["freeze_manifest"]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n")
    return df


def verify_freeze(cfg: dict) -> pd.DataFrame:
    """Compare every frozen Phase 1 to 4 input with the manifest. Raises if anything changed."""
    path = allowed_path(cfg["inputs"]["freeze_manifest"], cfg)
    if not path.exists():
        raise InputError("freeze manifest missing: run python -m src.analytics.run_phase5 --record-freeze once")
    manifest = pd.read_csv(path)
    current = set(frozen_files(cfg))
    rows = []
    for r in manifest.itertuples():
        p = PROJECT_ROOT / r.file
        got = sha256_normalised(allowed_path(r.file, cfg)) if p.exists() else None
        rows.append({"file": r.file, "sha256_recorded": r.sha256, "sha256_now": got,
                     "status": "UNCHANGED" if got == r.sha256 else ("MISSING" if got is None else "CHANGED")})
    for extra in sorted(current - set(manifest["file"])):
        rows.append({"file": extra, "sha256_recorded": None, "sha256_now": sha256_normalised(PROJECT_ROOT / extra),
                     "status": "NEW"})
    df = pd.DataFrame(rows)
    bad = df[df["status"] != "UNCHANGED"]
    if len(bad):
        raise InputError("Phase 1 to 4 inputs changed since the Phase 5 freeze:\n" + bad.to_string(index=False))
    return df


# ----------------------------------------------------------------------------- model
def open_model(engine_name: str, cfg: dict, project: dict, out_dir: Path | None = None):
    """Return (engine, build_summary). DuckDB: build the Phase 4 model from the frozen curated data.
    SQL Server: connect to the database Phase 4 built and require its reconciliation to pass."""
    from src.sql_model import run_model
    from src.sql_model.engines import SqlServerEngine

    if engine_name == "duckdb":
        build_dir = Path(out_dir) / "model_build" if out_dir else PROJECT_ROOT / cfg["outputs"]["model_build"]
        res = run_model.run("duckdb", ":memory:", out_dir=build_dir, keep_engine=True)
        engine = res["engine"]
        engine.con.execute("SET enable_progress_bar = false")
        if not res["passed"]:
            engine.close()
            raise InputError(f"Phase 4 model build failed reconciliation: {res['summary']}")
        engine.con.execute("CREATE SCHEMA IF NOT EXISTS diag")
        recon = res["reconciliation"]
        return engine, {"engine": "duckdb", "build": res["summary"], "reconciliation": recon}
    if engine_name == "mssql":
        engine = SqlServerEngine(project["database"])
        recon = fetch(engine, "SELECT * FROM recon.v_reconciliation")
        if not (recon["status"] == "PASS").all():
            raise InputError("SQL Server model does not reconcile to Phase 3: rebuild it with src.sql_model.run_model")
        return engine, {"engine": "mssql", "build": None, "reconciliation": recon}
    raise ValueError(engine_name)


def diagnostic_scripts(cfg: dict) -> list[Path]:
    return sorted((PROJECT_ROOT / cfg["inputs"]["diagnostics_sql_dir"]).glob("[0-9][0-9]_*.sql"))


def run_diagnostic_sql(engine, cfg: dict) -> list[dict]:
    from src.sql_model.scripts import split_batches
    import time

    log = []
    for path in diagnostic_scripts(cfg):
        t0 = time.time()
        batches = [b for b in split_batches(path) if b.runs_on(engine.name)]
        for b in batches:
            engine.run_batch(b)
        log.append({"script": path.relative_to(PROJECT_ROOT).as_posix(), "batches": len(batches),
                    "seconds": round(time.time() - t0, 2)})
    return log


def fetch(engine, tsql: str) -> pd.DataFrame:
    """Query the model; DECIMAL values (pyodbc returns Decimal) become float, counts become int64 where whole."""
    df = engine.query(tsql)
    for c in df.columns:
        if df[c].dtype == object and df[c].map(lambda v: isinstance(v, Decimal)).any():
            df[c] = df[c].map(lambda v: float(v) if isinstance(v, Decimal) else v).astype(float)
    return df


def benchmark(engine_name: str, cfg: dict) -> pd.DataFrame:
    """Phase 4 reconciliation results for the engine used (falls back to the DuckDB build's results)."""
    for name in (f"reports/phase4/reconciliation_results_{engine_name}.csv", "reports/phase4/reconciliation_results_duckdb.csv"):
        p = allowed_path(name, cfg)
        if p.exists():
            df = pd.read_csv(p)
            df["source_file"] = name
            return df
    raise InputError("Phase 4 reconciliation results not found")
