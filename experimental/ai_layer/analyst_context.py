"""Guarded composition wrapper around the existing core AnalystContext.

Inputs: the project root, the Phase 11 config, an optional read-only engine and the artifact paths
to preload. Output: an analyst context whose every file read has passed the central path guard.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd

from src.analyst.evidence import AnalystContext, InsufficientEvidence

from .artifacts import ArtifactResolver


class GuardedAnalystContext:
    """Expose the core analyst API while guarding every file-backed resolution."""

    def __init__(self, project_root: str | Path, config: dict, engine=None,
                 artifact_paths: Mapping[str, str] | None = None):
        self.root = Path(project_root).resolve()
        self.config = config
        self.resolver = ArtifactResolver(self.root, config)
        frames: dict[str, pd.DataFrame] = {}
        self._provenance: dict[str, dict] = {}
        for key, relative_path in (artifact_paths or {}).items():
            table = self.resolver.read_csv_path(relative_path, limit=5000, method=f"guarded_context:{key}")
            frames[key] = pd.DataFrame(list(table.rows))
            self._provenance[key] = table.provenance.to_dict()
        self._core = AnalystContext(self.root, config, engine=engine, artifacts=frames)

    def _configured_path(self, key: str) -> str:
        evidence = self.config.get("evidence_artifacts", {})
        for phase, entries in evidence.items():
            if isinstance(entries, dict) and key in entries:
                return entries[key]
        raise InsufficientEvidence(f"No configured artifact for '{key}'")

    def path(self, key: str) -> Path:
        """Guarded absolute path of a configured evidence artifact."""
        return self.resolver.resolve(self._configured_path(key))

    def artifact(self, key: str) -> pd.DataFrame:
        """A preloaded artifact frame; refused if it bypassed the guarded resolver."""
        # The core context could load files itself, so only serve what the guard already read.
        if key not in self._provenance:
            raise InsufficientEvidence(f"Artifact '{key}' was not loaded through the guarded resolver")
        return self._core.artifact(key)

    def artifact_provenance(self, key: str) -> dict:
        """Copy of the provenance recorded when the artifact was loaded."""
        if key not in self._provenance:
            raise InsufficientEvidence(f"Artifact '{key}' was not loaded through the guarded resolver")
        return dict(self._provenance[key])

    def query(self, template: str, params: dict) -> pd.DataFrame:
        """Run a registered read-only SQL template through the core context."""
        return self._core.query(template, params)

    @property
    def dimensions(self) -> dict:
        """Known dimension members from the core context."""
        return self._core.dimensions

    @property
    def query_log(self) -> list[str]:
        """SQL issued so far, for the audit trail."""
        return self._core.query_log

    @property
    def sql_available(self) -> bool:
        """True only when a live read-only engine is connected.

        Offline runs and mock mode have no engine, so a caller must serve the question from the
        frozen governed artefacts instead of assuming the warehouse answered it.
        """
        return self._core.engine is not None

    def last_complete_week(self) -> dict:
        """Final row of the preloaded weekly calendar."""
        weeks = self._core.artifacts.get("weeks")
        if weeks is None or not len(weeks):
            raise InsufficientEvidence("No retail week calendar is available")
        if isinstance(weeks, pd.DataFrame):
            return weeks.iloc[-1].to_dict()
        return weeks[-1]