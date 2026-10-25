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


def credentials_available() -> bool:
    """True when the BigQuery client is installed and Application Default Credentials resolve."""
    try:
        import google.auth
        from google.cloud import bigquery  # noqa: F401
        google.auth.default(scopes=["https://www.googleapis.com/auth/bigquery"])
        return True
    except Exception:  # noqa: BLE001
        return False


def redact(text: str, project: str | None) -> str:
    return text.replace(project, PROJECT_PLACEHOLDER) if project and isinstance(text, str) else text
