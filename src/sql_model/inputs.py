"""Phase 4 inputs: the approved Phase 3 curated files and Phase 3's own trusted outputs.

Only the files named in config/sql_model_config.yaml (section inputs) can be opened here. The curated
files are verified against the SHA-256 recorded by Phase 3 (reports/phase3/lineage.json) before any
load, so the model is provably built from the frozen, approved data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class InputError(RuntimeError):
    pass


def load_config() -> tuple[dict, dict]:
    cfg = yaml.safe_load((PROJECT_ROOT / "config" / "sql_model_config.yaml").read_text())
    project = yaml.safe_load((PROJECT_ROOT / "config" / "project_config.yaml").read_text())
    return cfg, project


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _allowed(cfg: dict, rel: str) -> Path:
    inp = cfg["inputs"]
    allowed = {inp["phase3_lineage"], inp["phase3_kpis"]} | \
              {f"{inp['curated_dir']}/{t}.csv" for t in inp["curated_tables"]}
    if rel not in allowed or Path(rel).name.startswith("_"):
        raise InputError(f"{rel} is not an approved Phase 4 input")
    return PROJECT_ROOT / rel


def phase3_lineage(cfg: dict) -> dict:
    return json.loads(_allowed(cfg, cfg["inputs"]["phase3_lineage"]).read_text())


def verify_curated(cfg: dict) -> dict:
    """Curated files must be byte-identical to what Phase 3 wrote and recorded."""
    lin = phase3_lineage(cfg)["outputs"]
    report = {}
    for t in cfg["inputs"]["curated_tables"]:
        path = _allowed(cfg, f"{cfg['inputs']['curated_dir']}/{t}.csv")
        got = _sha256(path)
        if got != lin[t]["sha256"]:
            raise InputError(f"{t}: curated file differs from the Phase 3 frozen output")
        report[t] = {"rows": lin[t]["rows"], "sha256": got}
    return report


def read_curated(cfg: dict, table: str) -> pd.DataFrame:
    """Curated CSV as text, blanks as NULL (what staging receives)."""
    path = _allowed(cfg, f"{cfg['inputs']['curated_dir']}/{table}.csv")
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
    return df.astype(object).where(df != "", None)


def expected_metrics(cfg: dict, curated: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Expected values for recon.expected, each with its tolerance and source."""
    tol = cfg["tolerances"]
    lin = phase3_lineage(cfg)["outputs"]
    rows = []

    def add(name, group, value, tol_class, source):
        rows.append({"metric_name": name, "metric_group": group, "expected_value": float(value),
                     "tolerance_abs": float(tol[tol_class]), "expected_source": source})

    src_lin = "reports/phase3/lineage.json (curated row counts)"
    for t in cfg["inputs"]["curated_tables"]:
        add(f"rows_stg_{t}", "row_count", lin[t]["rows"], "row_count", src_lin)
    add("rows_dw_dim_date", "row_count", lin["dim_date"]["rows"], "row_count", src_lin)
    add("rows_dw_dim_store", "row_count", lin["dim_store"]["rows"], "row_count", src_lin)
    add("rows_dw_dim_product", "row_count", lin["dim_product"]["rows"], "row_count", src_lin)
    for t in ("fact_sales", "fact_returns", "fact_inventory", "fact_targets"):
        add(f"rows_dw_{t}", "row_count", lin[t]["rows"], "row_count", src_lin)
    add("rows_dw_fact_promotion_coverage", "row_count", lin["fact_promotions"]["rows"], "row_count", src_lin)

    src_cur = "data/processed/curated (Phase 3 output)"
    s, p = curated["fact_sales"], curated["fact_promotions"]
    add("rows_dw_dim_promotion", "row_count", p["promotion_id"].nunique(), "row_count", src_cur + ": distinct promotion_id")
    add("unknown_product_sales_lines", "unknown_member", (s["product_id"] == "UNKNOWN").sum(), "row_count",
        src_cur + ": product_id = UNKNOWN")
    add("unknown_promotion_sales_lines", "unknown_member", (s["promotion_id"] == "UNKNOWN").sum(), "row_count",
        src_cur + ": promotion_id = UNKNOWN")
    add("not_promoted_sales_lines", "unknown_member", s["promotion_id"].isna().sum(), "row_count",
        src_cur + ": promotion_id blank")
    for name in ("unknown_store_fact_rows", "unknown_date_fact_rows", "unknown_product_other_fact_rows",
                 "conversion_failures"):
        add(name, "unknown_member" if name != "conversion_failures" else "load_integrity", 0, "row_count",
            "must be zero: every curated key is valid (Phase 3 validation)")

    kpi = pd.read_csv(_allowed(cfg, cfg["inputs"]["phase3_kpis"])).set_index("kpi")["clean_complete"]
    for name, cls in cfg["kpi_tolerance_class"].items():
        add(name, "kpi", kpi[name], cls, "reports/phase3/kpi_reconciliation.csv (clean_complete)")
    return pd.DataFrame(rows)
