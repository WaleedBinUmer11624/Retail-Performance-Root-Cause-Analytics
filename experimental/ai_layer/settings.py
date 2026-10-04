"""Runtime settings for the optional Phase 11 layer.

Inputs: config/phase11_config.yaml and BRIGHTWATER_LLM_* environment variables.
Output: frozen RuntimeSettings; the provider defaults to the offline mock when nothing is set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from .path_guard import guard_path


@dataclass(frozen=True)
class RuntimeSettings:
    """Resolved configuration, provider choice and credentials for one run."""
    project_root: Path
    phase_config: dict
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    timeout_seconds: int


def load_settings(project_root: str | os.PathLike[str],
                  environ: Mapping[str, str] | None = None) -> RuntimeSettings:
    """Read config and environment; `environ` overrides os.environ, e.g. {} in tests."""
    root = Path(project_root).resolve()
    config_path = guard_path(root, "config/phase11_config.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    environment = os.environ if environ is None else environ
    llm = config.get("llm", {})
    provider = environment.get("BRIGHTWATER_LLM_PROVIDER", "mock").strip().casefold()
    model_name = llm.get("model_env_var", "BRIGHTWATER_LLM_MODEL")
    key_name = llm.get("provider_env_var", "BRIGHTWATER_LLM_API_KEY")
    model = environment.get(model_name, llm.get("offline_renderer", "deterministic_v1")).strip()
    # Secrets come only from the environment, never from the YAML file.
    api_key = environment.get(key_name, "").strip() or None
    base_url = environment.get("BRIGHTWATER_LLM_BASE_URL", "").strip() or None
    timeout = int(llm.get("timeout_seconds", 30))
    if not 1 <= timeout <= 300:
        raise ValueError("LLM timeout must be between 1 and 300 seconds")
    return RuntimeSettings(root, config, provider, model, api_key, base_url, timeout)