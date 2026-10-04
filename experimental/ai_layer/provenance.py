"""Provenance records shared by structured tools and text retrieval."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class SourceProvenance:
    """Where a piece of evidence came from and a hash of the exact bytes read."""
    source_file: str
    phase: str
    retrieval_method: str
    content_sha256: str
    filters: Mapping[str, str] = field(default_factory=dict)
    record_count: int | None = None
    row_index: int | None = None

    def to_dict(self) -> dict:
        """JSON-ready copy of every field."""
        return {
            "source_file": self.source_file,
            "phase": self.phase,
            "retrieval_method": self.retrieval_method,
            "content_sha256": self.content_sha256,
            "filters": dict(self.filters),
            "record_count": self.record_count,
            "row_index": self.row_index,
        }