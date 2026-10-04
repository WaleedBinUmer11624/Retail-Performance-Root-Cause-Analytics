"""Assemble structured tool and retrieval evidence for a future renderer/provider.

Inputs: tool results and retrieval hits for one question. Output: a dict of numbered evidence
items and the de-duplicated sources they cite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .retrieval import RetrievalHit
from .tools import ToolResult


@dataclass
class EvidenceBundle:
    """All evidence gathered for one question, in the order it was collected."""
    question: str
    intent: str
    filters: dict = field(default_factory=dict)
    tool_results: list[ToolResult] = field(default_factory=list)
    retrieval_hits: list[RetrievalHit] = field(default_factory=list)

    def add_tool(self, result: ToolResult) -> None:
        """Append one structured tool result."""
        self.tool_results.append(result)

    def add_retrieval(self, hits: Iterable[RetrievalHit]) -> None:
        """Append retrieved text passages."""
        self.retrieval_hits.extend(hits)

    def to_dict(self) -> dict:
        """Serialise evidence; retrieved text is typed INTERPRETATION, never a governed figure."""
        sources: dict[str, dict] = {}
        evidence: list[dict] = []
        for result in self.tool_results:
            result_sources = [dict(source) for source in result.provenance]
            for source in result_sources:
                sources[source["source_file"]] = source
            evidence.append({
                "evidence_id": f"tool:{result.tool}:{len(evidence)+1}",
                "evidence_type": result.evidence_type,
                "tool": result.tool,
                "data": result.data,
                "source_ids": [source["source_file"] for source in result_sources],
            })
        for index, hit in enumerate(self.retrieval_hits, start=1):
            source = dict(hit.provenance)
            sources[source["source_file"]] = source
            evidence.append({
                "evidence_id": f"text:{index}",
                "evidence_type": "INTERPRETATION",
                "text": hit.text,
                "score": hit.score,
                "source_ids": [source["source_file"]],
            })
        return {
            "question": self.question,
            "intent": self.intent,
            "filters": dict(self.filters),
            "evidence": evidence,
            "sources": list(sources.values()),
        }