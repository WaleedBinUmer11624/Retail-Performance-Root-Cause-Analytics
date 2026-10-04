"""Phase 6 inputs: whitelist, Phase 1-5 freeze, model, SQL and data loading.

Phase 6 opens files only through `allowed_path`: the files named in config/rca_config.yaml
(inputs.allowed_files), the Phase 1-4 frozen inputs (config/analytics_config.yaml) and the Phase 5
frozen files (config/rca_config.yaml inputs.phase5_frozen). Anything underscore-prefixed or under an
evaluation, raw, sample or quarantine folder is refused.
"""
from __future__ import annotations

import fnmatch
import time
from pathlib import Path

import pandas as pd
import yaml

from src.analytics.model_access import (PROJECT_ROOT, InputError, _is_refused, fetch, open_model, run_diagnostic_sql,
                                        sha256_normalised)

RCA_SCHEMA = "rca"


def _read_yaml(rel: str) -> dict:
    if _is_refused(rel) or not rel.startswith("config/"):
        raise InputError(f"{rel} is not an approved Phase 6 configuration file")
    return yaml.safe_load((PROJECT_ROOT / rel).read_text(encoding="utf-8"))


def load_config() -> dict:
    """All configuration Phase 6 needs, keyed by source."""
    return {"rca": _read_yaml("config/rca_config.yaml"), "analytics": _read_yaml("config/analytics_config.yaml"),
            "project": _read_yaml("config/project_config.yaml"), "sql_model": _read_yaml("config/sql_model_config.yaml")}


def _patterns(cfg: dict) -> list[str]:
    return list(cfg["analytics"]["inputs"]["frozen_inputs"]) + list(cfg["rca"]["inputs"]["phase5_frozen"])


def allowed_path(rel: str, cfg: dict) -> Path:
    rel = rel.replace("\\", "/")
    if _is_refused(rel):
        raise InputError(f"{rel} is not an approved Phase 6 input (evaluation-only or raw asset)")
    if rel not in set(cfg["rca"]["inputs"]["allowed_files"]) and not any(fnmatch.fnmatch(rel, p) for p in _patterns(cfg)):
        raise InputError(f"{rel} is not an approved Phase 6 input")
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
    path = PROJECT_ROOT / cfg["rca"]["inputs"]["freeze_manifest"]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n")
    return df


def verify_freeze(cfg: dict) -> pd.DataFrame:
    """Every Phase 1-5 input and output must match the manifest recorded at the start of Phase 6."""
    path = allowed_path(cfg["rca"]["inputs"]["freeze_manifest"], cfg)
    if not path.exists():
        raise InputError("Phase 6 freeze manifest missing: run python -m src.rca.run_phase6 --record-freeze once")
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
        raise InputError("Phase 1-5 inputs changed since the Phase 6 freeze:\n" + bad.to_string(index=False))
    return df


# ----------------------------------------------------------------------------- model and SQL
def open_rca_model(engine_name: str, cfg: dict, out_dir: Path):
    """Phase 4 model + Phase 5 diag views + Phase 6 rca views. Returns (engine, info, sql_log)."""
    engine, info = open_model(engine_name, cfg["analytics"], cfg["project"], out_dir)
    log = run_diagnostic_sql(engine, cfg["analytics"])
    if engine.name == "duckdb":
        engine.con.execute(f"CREATE SCHEMA IF NOT EXISTS {RCA_SCHEMA}")
    from src.sql_model.scripts import split_batches
    for path in sorted((PROJECT_ROOT / cfg["rca"]["inputs"]["rca_sql_dir"]).glob("[0-9][0-9]_*.sql")):
        t0 = time.time()
        batches = [b for b in split_batches(path) if b.runs_on(engine.name)]
        for b in batches:
            engine.run_batch(b)
        log.append({"script": path.relative_to(PROJECT_ROOT).as_posix(), "batches": len(batches),
                    "seconds": round(time.time() - t0, 2)})
    return engine, info, log


QUERIES = {
    "store_day": "SELECT * FROM rca.v_store_day",
    "receipt": "SELECT * FROM rca.v_receipt",
    "store_category_week": "SELECT * FROM rca.v_store_category_week",
    "store_category_h2": "SELECT * FROM rca.v_store_category_h2",
    "return_detail": "SELECT * FROM rca.v_return_detail",
    "product_sale_month": "SELECT * FROM rca.v_product_sale_month",
    "stockout_episode": "SELECT * FROM rca.v_stockout_episode",
    "stock_cell_week": "SELECT * FROM diag.v_stock_cell_week",
    "promo_event_week": "SELECT * FROM diag.v_promo_event_week",
    "h2_headline": "SELECT * FROM diag.v_h2_headline",
    "h2_headline_from_facts": "SELECT * FROM diag.v_h2_headline_from_facts",
    "segment_contribution": "SELECT * FROM diag.v_segment_h2_contribution",
    "category_contribution": "SELECT * FROM diag.v_category_h2_contribution",
    "weeks": "SELECT retail_week_key, retail_year, retail_week FROM dw.dim_retail_week WHERE retail_week_key IN "
             "(SELECT DISTINCT retail_week_key FROM dw.fact_inventory)",
    "stores": "SELECT store_key, store_id, store_name, region, store_format, floor_area_m2 FROM dw.dim_store WHERE store_key > 0",
    "products": "SELECT product_key, product_id, product_name, category, subcategory, supplier_name, list_price, unit_cost "
                "FROM dw.dim_product",
}


def load_data(engine) -> dict:
    data = {k: fetch(engine, q) for k, q in QUERIES.items()}
    # SQL result order is not guaranteed; sort every frame on all its columns so resampling and ties are reproducible
    for k, df in data.items():
        data[k] = df.sort_values(list(df.columns), kind="mergesort", na_position="last").reset_index(drop=True)
    for k in ("store_day",):
        data[k]["calendar_date"] = pd.to_datetime(data[k]["calendar_date"])
    for c in ("return_date", "original_sale_date"):
        data["return_detail"][c] = pd.to_datetime(data["return_detail"][c])
    return data
