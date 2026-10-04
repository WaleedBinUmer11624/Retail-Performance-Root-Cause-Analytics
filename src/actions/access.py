"""Phase 8 inputs: whitelist, Phase 1-7 freeze and the headline check.

Phase 8 is a decision framework built on the validated Phase 1-7 results. It opens files only through
`allowed_path`: the files named in config/action_config.yaml (inputs.allowed_files) and the frozen Phase 1-7
files (the Phase 1-6 patterns of the earlier phases plus inputs.phase7_frozen). Anything underscore-prefixed or
under an evaluation, raw, sample or quarantine folder is refused.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

import pandas as pd
import yaml

from src.analytics.model_access import PROJECT_ROOT, InputError, _is_refused, sha256_normalised


def _read_yaml(rel: str) -> dict:
    if _is_refused(rel) or not rel.startswith("config/"):
        raise InputError(f"{rel} is not an approved Phase 8 configuration file")
    return yaml.safe_load((PROJECT_ROOT / rel).read_text(encoding="utf-8"))


def load_config() -> dict:
    return {"actions": _read_yaml("config/action_config.yaml"), "powerbi": _read_yaml("config/powerbi_config.yaml"),
            "rca": _read_yaml("config/rca_config.yaml"), "analytics": _read_yaml("config/analytics_config.yaml"),
            "project": _read_yaml("config/project_config.yaml"), "sql_model": _read_yaml("config/sql_model_config.yaml")}


def _patterns(cfg: dict) -> list[str]:
    return (list(cfg["analytics"]["inputs"]["frozen_inputs"]) + list(cfg["rca"]["inputs"]["phase5_frozen"]) +
            list(cfg["powerbi"]["inputs"]["phase6_frozen"]) + list(cfg["actions"]["inputs"]["phase7_frozen"]))


def allowed_path(rel: str, cfg: dict) -> Path:
    rel = rel.replace("\\", "/")
    if _is_refused(rel):
        raise InputError(f"{rel} is not an approved Phase 8 input (evaluation-only or raw asset)")
    if rel not in set(cfg["actions"]["inputs"]["allowed_files"]) and not any(fnmatch.fnmatch(rel, p) for p in _patterns(cfg)):
        raise InputError(f"{rel} is not an approved Phase 8 input")
    return PROJECT_ROOT / rel


def read_csv(rel: str, cfg: dict) -> pd.DataFrame:
    return pd.read_csv(allowed_path(rel, cfg))


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
    path = PROJECT_ROOT / cfg["actions"]["inputs"]["freeze_manifest"]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n")
    return df


def verify_freeze(cfg: dict) -> pd.DataFrame:
    """Every Phase 1-7 file must match the manifest recorded at the start of Phase 8. The Phase 7 manifest
    (Phase 1-6 files) and, through it, the Phase 6 manifest (Phase 1-5 files) are re-verified as well."""
    path = allowed_path(cfg["actions"]["inputs"]["freeze_manifest"], cfg)
    if not path.exists():
        raise InputError("Phase 8 freeze manifest missing: run python -m src.actions.run_phase8 --record-freeze once")
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
        raise InputError("Phase 1-7 files changed since the Phase 8 freeze:\n" + bad.to_string(index=False))
    from src.powerbi.access import load_config as pbi_cfg, verify_freeze as pbi_verify
    pbi_verify(pbi_cfg())
    return df


# ----------------------------------------------------------------------------- headline
HEADLINE_SQL = """
WITH s AS (
    SELECT d.retail_year, SUM(f.sales_revenue) AS sales_revenue
    FROM pbi.fact_sales f JOIN pbi.dim_date d ON d.date_key = f.date_key
    WHERE d.retail_half = 'H2' AND d.retail_year IN (2024, 2025)
    GROUP BY d.retail_year),
r AS (
    SELECT d.retail_year, SUM(f.refund_value) AS returns_value
    FROM pbi.fact_returns f JOIN pbi.dim_date d ON d.date_key = f.return_date_key
    WHERE d.retail_half = 'H2' AND d.retail_year IN (2024, 2025)
    GROUP BY d.retail_year)
SELECT s.retail_year, s.sales_revenue, r.returns_value, s.sales_revenue - r.returns_value AS net_revenue
FROM s JOIN r ON r.retail_year = s.retail_year
ORDER BY s.retail_year
"""


def recompute_headline(engine_name: str, out_dir: Path) -> pd.DataFrame:
    """Rebuild the Phase 4 model (DuckDB) or connect to SQL Server, create the Phase 7 pbi views and sum the facts.
    Independent of every earlier phase's Python code path: a plain SQL sum over the Power BI source views."""
    from src.powerbi.access import load_config as pbi_cfg, open_pbi_model, query
    engine, _, _ = open_pbi_model(engine_name, pbi_cfg(), out_dir)
    try:
        return query(engine, HEADLINE_SQL)
    finally:
        engine.close()
