"""Guarded readers for the explicit Phase 11 evidence allowlist.

Inputs: configured CSV artifacts and text sources under the project root. Outputs: rows or text,
each with provenance (file, phase, method, SHA-256 of the bytes read, filters, row count).
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .path_guard import guard_path
from .provenance import SourceProvenance


class ArtifactError(RuntimeError):
    """Raised when configured evidence cannot be resolved or parsed."""


@dataclass(frozen=True)
class ArtifactTable:
    """CSV rows read through the guard, with their provenance."""
    rows: tuple[dict[str, str], ...]
    provenance: SourceProvenance

    def to_dict(self) -> dict:
        """JSON-ready records plus provenance."""
        return {"records": [dict(row) for row in self.rows], "provenance": self.provenance.to_dict()}


@dataclass(frozen=True)
class TextSource:
    """Full text of an allowlisted document, with its provenance."""
    text: str
    provenance: SourceProvenance


def _config_value(config: dict, dotted_key: str) -> str:
    value: object = config.get("evidence_artifacts", {})
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ArtifactError("Evidence artifact is not configured")
        value = value[part]
    if not isinstance(value, str):
        raise ArtifactError("Evidence artifact path is invalid")
    return value


def _phase_label(relative: str) -> str:
    parts = Path(relative).parts
    if len(parts) > 1 and parts[0] == "reports" and parts[1].startswith("phase"):
        return parts[1]
    if parts and parts[0] == "docs":
        return "documentation"
    return "project"


class ArtifactResolver:
    """Reads only configured artifact paths and applies the central denylist first."""

    def __init__(self, project_root: str | Path, config: dict):
        self.root = Path(project_root).resolve()
        self.config = config

    def resolve(self, relative_path: str | Path) -> Path:
        """Apply the central path guard; raises before any file access if denied."""
        return guard_path(self.root, relative_path)

    def read_csv_artifact(self, dotted_key: str, filters: Mapping[str, object] | None = None,
                          limit: int = 500) -> ArtifactTable:
        """Read the CSV configured under evidence_artifacts.<dotted_key>."""
        relative = _config_value(self.config, dotted_key)
        return self.read_csv_path(relative, filters=filters, limit=limit, method=f"configured_artifact:{dotted_key}")

    def read_csv_path(self, relative_path: str | Path,
                      filters: Mapping[str, object] | None = None,
                      limit: int = 500,
                      method: str = "guarded_csv") -> ArtifactTable:
        """Read a guarded CSV, apply exact-match filters and a row cap, and record provenance."""
        # bool is a subclass of int, so reject it explicitly.
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            raise ValueError("CSV row limit must be an integer from 1 to 5000")
        path = self.resolve(relative_path)
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        rows = list(reader)
        selected = dict(filters or {})
        unknown = set(selected) - set(reader.fieldnames or [])
        # A misspelt filter column would match nothing and look like "no evidence"; fail instead.
        if unknown:
            raise ArtifactError("Filter contains a column outside the source schema")
        if selected:
            rows = [row for row in rows if all(row.get(key) == str(value) for key, value in selected.items())]
        rows = rows[:limit]
        relative = path.relative_to(self.root).as_posix()
        provenance = SourceProvenance(
            source_file=relative,
            phase=_phase_label(relative),
            retrieval_method=method,
            content_sha256=hashlib.sha256(raw).hexdigest(),
            filters={key: str(value) for key, value in selected.items()},
            record_count=len(rows),
        )
        return ArtifactTable(tuple(rows), provenance)

    def read_text_source(self, relative_path: str | Path) -> TextSource:
        """Read one document, only if it is on the configured retrieval allowlist."""
        path = self.resolve(relative_path)
        configured = self.config.get("retrieval", {}).get("text_sources", [])
        configured_paths = {self.resolve(value) for value in configured}
        if path not in configured_paths:
            raise ArtifactError("Text source is not in the configured retrieval allowlist")
        raw = path.read_bytes()
        relative = path.relative_to(self.root).as_posix()
        return TextSource(
            raw.decode("utf-8-sig"),
            SourceProvenance(
                source_file=relative,
                phase=_phase_label(relative),
                retrieval_method="configured_text_source",
                content_sha256=hashlib.sha256(raw).hexdigest(),
            ),
        )

    def read_configured_text_sources(self) -> tuple[TextSource, ...]:
        """Read every allowlisted document."""
        paths = self.config.get("retrieval", {}).get("text_sources", [])
        # Guard every path first, so one denied entry stops the run before any file is read.
        guarded = [self.resolve(path) for path in paths]
        return tuple(self.read_text_source(path.relative_to(self.root).as_posix()) for path in guarded)