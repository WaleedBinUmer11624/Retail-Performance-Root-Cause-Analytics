"""BigQuery settings: the tracked configuration, plus the project ID from outside the repository.

The project ID is read from the environment variable named in config/bigquery_config.yaml, or from the
untracked local file it names (listed in .gitignore). It is never written to a tracked file, and the
build outputs replace it with <project>.
"""
from __future__ import annotations

import os

import yaml

from src.sql_model.inputs import PROJECT_ROOT

CONFIG = PROJECT_ROOT / "config" / "bigquery_config.yaml"
PROJECT_PLACEHOLDER = "<project>"


def load_bq_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def resolve_project(bq_cfg: dict | None = None) -> str | None:
    bq_cfg = bq_cfg or load_bq_config()
    value = os.environ.get(bq_cfg["project_id_env"], "").strip()
    if value:
        return value
    local = PROJECT_ROOT / bq_cfg["local_config"]
    if local.exists():
        data = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
        return str(data.get("project_id") or "").strip() or None
    return None


def credentials_problem() -> str | None:
    """None when the BigQuery client is installed and Application Default Credentials resolve; otherwise what to do."""
    try:
        import google.auth
        from google.cloud import bigquery  # noqa: F401
    except ImportError:
        return "The BigQuery client is not installed: python -m pip install -r requirements-bigquery.txt"
    try:
        google.auth.default(scopes=["https://www.googleapis.com/auth/bigquery"])
    except Exception:  # noqa: BLE001
        return "No Application Default Credentials: run gcloud auth application-default login"
    return None


def credentials_available() -> bool:
    return credentials_problem() is None


# Objects a finished build always has. Sandbox tables expire after 60 days while the datasets remain, so
# the datasets alone do not show that a build is usable.
READY_TABLES = ("recon.kpi_validation_result", "recon.actual", "dw.fact_sales")


def build_problem(engine) -> str | None:
    """None when the BigQuery build can be queried; otherwise why not and how to rebuild."""
    rebuild = "run python -m src.bigquery_model.run_bigquery"
    for table in READY_TABLES:
        try:
            engine.client.get_table(engine.table_id(table))
        except Exception:  # noqa: BLE001 - not found, expired or not readable
            return (f"BigQuery build not available ({table} is missing; sandbox tables expire after 60 days): "
                    f"{rebuild}")
    return None


def redact(text: str, project: str | None) -> str:
    return text.replace(project, PROJECT_PLACEHOLDER) if project and isinstance(text, str) else text
