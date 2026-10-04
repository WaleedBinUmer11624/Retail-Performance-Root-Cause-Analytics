"""Load project, generator and (hidden) scenario configuration files.

Input: YAML files under config/. Output: parsed dicts; a missing file raises FileNotFoundError.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_generator_config(path: Path | None = None) -> dict[str, Any]:
    """Generator settings: calendar, stores, categories, volumes and pricing."""
    return _load_yaml(path or CONFIG_DIR / "generator_config.yaml")


def load_project_config(path: Path | None = None) -> dict[str, Any]:
    """Project-wide settings such as paths and database connection."""
    return _load_yaml(path or CONFIG_DIR / "project_config.yaml")


def load_hidden_scenario(path: Path | None = None) -> dict[str, Any]:
    """Only the data generator may call this. Analysis code must not."""
    return _load_yaml(path or CONFIG_DIR / "_hidden_scenario.yaml")
