"""Structured request tracing for the Phase 11 layer, with credential redaction.

Implements brief section 16. Every request carries a request id, its question category, the
tools that ran, the source ids that were cited, latency and any error. Anything that looks like
a credential is redacted before a record is written, so no API key, SQL password, token or
connection string can reach a log file.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

LOGGER_NAME = "phase11.assistant"
REDACTED = "[redacted]"

# A credential only counts as a credential when it is introduced by a key or a scheme, so an
# ordinary sentence containing the word "token" is not mangled.
_SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("connection_string", re.compile(
        r"(?i)\b(?:server|host|data\s*source|initial\s*catalog)\s*=\s*[^;\r\n]+")),
    ("password", re.compile(r"(?i)\b(?:password|pwd)\s*=\s*[^;\s\"',}]+")),
    ("credential", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|access[_-]?token|auth[_-]?token|authorization)\b"
        r"\s*[:=]\s*\"?[^\",;\s}]+")),
    ("bearer", re.compile(r"(?i)\bbearer\s+\S+")),
    ("userinfo_url", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@\S+")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")),
)


def redact(text: str) -> str:
    """Return `text` with every credential-looking span replaced."""
    if not isinstance(text, str):
        return text
    cleaned = text
    for _label, pattern in _SECRET_RULES:
        cleaned = pattern.sub(REDACTED, cleaned)
    return cleaned


def new_request_id() -> str:
    """Random 32-character hex id for one request."""
    return uuid.uuid4().hex


@dataclass
class RequestTrace:
    """One request's observable facts. Business values are never recorded, only structure."""

    request_id: str
    question_category: str
    mode: str
    provider: str
    model: str
    source_ids: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    unavailable_tools: list[str] = field(default_factory=list)
    retrieval_hits: int = 0
    blocked_injections: int = 0
    narrative_admitted: bool = False
    grounded: bool = False
    confidence: str = "UNASSESSED"
    token_usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    started_at: float = field(default_factory=time.perf_counter)
    latency_ms: float = 0.0

    def finish(self) -> "RequestTrace":
        """Stamp latency since the trace started; returns self for chaining."""
        self.latency_ms = round((time.perf_counter() - self.started_at) * 1000, 3)
        return self

    def to_dict(self) -> dict:
        """JSON-ready record with ids sorted and de-duplicated for stable logs."""
        return {
            "request_id": self.request_id,
            "question_category": self.question_category,
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "source_ids": sorted(set(self.source_ids)),
            "tool_calls": list(self.tool_calls),
            "unavailable_tools": sorted(set(self.unavailable_tools)),
            "retrieval_hits": self.retrieval_hits,
            "blocked_injections": self.blocked_injections,
            "narrative_admitted": self.narrative_admitted,
            "grounded": self.grounded,
            "confidence": self.confidence,
            "token_usage": dict(self.token_usage),
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


def trace_to_json(trace: RequestTrace) -> str:
    """Serialise the trace and redact credentials from the final text, not field by field."""
    return redact(json.dumps(trace.to_dict(), sort_keys=True, ensure_ascii=False, default=str))


def log_trace(trace: RequestTrace, logger: logging.Logger | None = None) -> str:
    """Write one redacted JSON line and return the exact text that was written."""
    target = logger if logger is not None else logging.getLogger(LOGGER_NAME)
    line = trace_to_json(trace)
    target.log(logging.ERROR if trace.error else logging.INFO, "%s", line)
    return line