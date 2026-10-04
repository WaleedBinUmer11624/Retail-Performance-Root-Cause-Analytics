"""Machine-readable response contract and dependency-free validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


EvidenceType = Literal[
    "FACT", "CALCULATED", "MODEL", "ATTRIBUTION", "ASSOCIATION", "INTERPRETATION",
    "INFERENCE", "FORECAST", "LIMITATION",
]
ConfidenceLabel = Literal["UNASSESSED", "STRONG", "MODERATE", "LIMITED", "INSUFFICIENT"]

EVIDENCE_TYPES: tuple[EvidenceType, ...] = (
    "FACT", "CALCULATED", "MODEL", "ATTRIBUTION", "ASSOCIATION", "INTERPRETATION",
    "INFERENCE", "FORECAST", "LIMITATION",
)

# A tool may name an evidence type more precisely than the response contract publishes. The
# mapping is explicit so the precise meaning is kept in the tool layer and never silently
# downgraded. An estimate is modelled or statistical evidence, never a plain calculated result.
EVIDENCE_TYPE_ALIASES: Mapping[str, EvidenceType] = {
    "ESTIMATE": "MODEL",
}


def normalise_evidence_type(value: str) -> EvidenceType:
    """Publish a tool's evidence type, resolving precise names through the alias table."""
    if not isinstance(value, str):
        raise ValueError("evidence_type must be a string")
    candidate = value.strip().upper()
    if candidate in EVIDENCE_TYPES:
        return candidate  # type: ignore[return-value]
    if candidate in EVIDENCE_TYPE_ALIASES:
        return EVIDENCE_TYPE_ALIASES[candidate]
    raise ValueError(f"Unsupported evidence type: {value}")


@dataclass(frozen=True)
class EvidenceClaim:
    """One evidence statement, its type and the source ids that back it."""
    evidence_id: str
    evidence_type: EvidenceType
    claim: str
    source_ids: tuple[str, ...]
    metric: str | None = None
    value: str | float | int | None = None
    comparison_period: str | None = None
    filters: Mapping[str, str] | None = None

    def to_dict(self) -> dict:
        """JSON-ready copy."""
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "claim": self.claim,
            "source_ids": list(self.source_ids),
            "metric": self.metric,
            "value": self.value,
            "comparison_period": self.comparison_period,
            "filters": dict(self.filters or {}),
        }


@dataclass(frozen=True)
class GroundedResponse:
    """The complete answer payload returned to a caller."""
    answer: str
    executive_summary: str
    evidence: tuple[EvidenceClaim, ...]
    sources: tuple[dict, ...]
    confidence: ConfidenceLabel
    limitations: tuple[str, ...]
    recommended_follow_up: tuple[str, ...]

    def to_dict(self) -> dict:
        """Serialise and validate; a payload that breaks the schema is never returned."""
        payload = {
            "answer": self.answer,
            "executive_summary": self.executive_summary,
            "evidence": [item.to_dict() for item in self.evidence],
            "sources": [dict(item) for item in self.sources],
            "confidence": self.confidence,
            "limitations": list(self.limitations),
            "recommended_follow_up": list(self.recommended_follow_up),
        }
        validate_response(payload)
        return payload


RESPONSE_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "executive_summary", "evidence", "sources", "confidence",
                 "limitations", "recommended_follow_up"],
    "properties": {
        "answer": {"type": "string"},
        "executive_summary": {"type": "string"},
        "evidence": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["evidence_id", "evidence_type", "claim", "source_ids"],
            "properties": {
                "evidence_id": {"type": "string", "minLength": 1},
                "evidence_type": {"enum": ["FACT", "CALCULATED", "MODEL", "ATTRIBUTION", "ASSOCIATION", "INTERPRETATION", "INFERENCE", "FORECAST", "LIMITATION"]},
                "claim": {"type": "string", "minLength": 1},
                "source_ids": {"type": "array", "items": {"type": "string"}},
                "metric": {"type": ["string", "null"]},
                "value": {"type": ["string", "number", "null"]},
                "comparison_period": {"type": ["string", "null"]},
                "filters": {"type": "object", "additionalProperties": {"type": "string"}},
            },
        }},
        "sources": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["source_file", "phase", "retrieval_method", "content_sha256"],
            "properties": {
                "source_file": {"type": "string"},
                "phase": {"type": "string"},
                "retrieval_method": {"type": "string"},
                "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "filters": {"type": "object", "additionalProperties": {"type": "string"}},
                "record_count": {"type": ["integer", "null"]},
                "row_index": {"type": ["integer", "null"]},
            },
        }},
        "confidence": {"enum": ["UNASSESSED", "STRONG", "MODERATE", "LIMITED", "INSUFFICIENT"]},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "recommended_follow_up": {"type": "array", "items": {"type": "string"}},
    },
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid grounded response: {message}")


def validate_response(payload: Mapping) -> None:
    """Validate response structure using only the standard library."""
    required = set(RESPONSE_JSON_SCHEMA["required"])
    _require(isinstance(payload, Mapping), "payload must be an object")
    _require(set(payload) == required, "top-level keys differ from the response schema")
    for key in ("answer", "executive_summary"):
        _require(isinstance(payload[key], str), f"{key} must be a string")
    _require(payload["confidence"] in {"UNASSESSED", "STRONG", "MODERATE", "LIMITED", "INSUFFICIENT"},
             "confidence label is unsupported")
    for key in ("limitations", "recommended_follow_up"):
        _require(isinstance(payload[key], list) and all(isinstance(item, str) for item in payload[key]),
                 f"{key} must be an array of strings")
    _require(isinstance(payload["evidence"], list), "evidence must be an array")
    _require(isinstance(payload["sources"], list), "sources must be an array")
    source_files: set[str] = set()
    for source in payload["sources"]:
        _require(isinstance(source, Mapping), "sources entries must be objects")
        required_source = {"source_file", "phase", "retrieval_method", "content_sha256"}
        allowed_source = required_source | {"filters", "record_count", "row_index"}
        _require(required_source <= set(source) <= allowed_source,
                 "source provenance fields differ from the schema")
        _require(all(isinstance(source[key], str) and source[key].strip()
                     for key in ("source_file", "phase", "retrieval_method")),
                 "source identity fields must be non-empty strings")
        digest = source["content_sha256"]
        _require(isinstance(digest, str) and len(digest) == 64
                 and all(char in "0123456789abcdef" for char in digest),
                 "source content hash must be lowercase SHA-256")
        filters = source.get("filters", {})
        _require(isinstance(filters, Mapping)
                 and all(isinstance(key, str) and isinstance(value, str) for key, value in filters.items()),
                 "source filters must map strings to strings")
        source_files.add(source["source_file"])
    evidence_ids: set[str] = set()
    for item in payload["evidence"]:
        _require(isinstance(item, Mapping), "evidence entries must be objects")
        required_evidence = set(RESPONSE_JSON_SCHEMA["properties"]["evidence"]["items"]["required"])
        allowed_evidence = required_evidence | {"metric", "value", "comparison_period", "filters"}
        _require(required_evidence <= set(item) <= allowed_evidence,
                 "evidence entry keys differ from the schema")
        _require(isinstance(item["evidence_id"], str) and bool(item["evidence_id"].strip()),
                 "evidence_id must be non-empty")
        _require(item["evidence_id"] not in evidence_ids, "evidence_id values must be unique")
        evidence_ids.add(item["evidence_id"])
        _require(item["evidence_type"] in {"FACT", "CALCULATED", "MODEL", "ATTRIBUTION", "ASSOCIATION", "INTERPRETATION", "INFERENCE", "FORECAST", "LIMITATION"},
                 "evidence_type is unsupported")
        _require(isinstance(item["claim"], str) and bool(item["claim"].strip()), "claim must be non-empty")
        _require(isinstance(item["source_ids"], list) and all(isinstance(source, str) and source in source_files for source in item["source_ids"]),
                 "every evidence source_id must resolve to a source")