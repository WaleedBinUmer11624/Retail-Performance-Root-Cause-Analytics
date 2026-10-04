"""Grounding, claim classification and evidence strength (brief sections 6 and 9).

Section 6 requires every substantive conclusion to be traceable to retrieved evidence, and requires
the assistant to say so plainly when evidence is missing rather than fill the gap. Section 9
forbids the language model inventing a confidence percentage, so confidence here is a deterministic
function of the project's own governed evidence-strength scale and never of generated text.

The strength scale is the project's, not ours: Phase 6 publishes an `evidence_strength` score
alongside its `evidence_level` label, and the mapping below is that published pairing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .response_schema import EvidenceClaim, EvidenceType

INSUFFICIENT_EVIDENCE_ANSWER = (
    "Insufficient evidence to determine this from the available project data."
)

FORECAST_NOTE = (
    "Forecast, not an actual result. Phase 10 produced these values; they are not measured outcomes."
)

# Phase 6 evidence_strength paired with its evidence_level label, as published in the governed
# evidence matrix. Higher means stronger support for the driver, never more certain about cause.
GOVERNED_STRENGTH_BY_LEVEL: Mapping[str, int] = {
    "Root-cause evidence": 3,
    "Statistical association": 2,
    "Observed change": 1,
    "Hypothesis": 0,
}

CLAIM_TYPE_BY_LEVEL: Mapping[str, EvidenceType] = {
    "Root-cause evidence": "MODEL",
    "Statistical association": "ASSOCIATION",
    "Observed change": "FACT",
    "Hypothesis": "INFERENCE",
}

_STRENGTH_TO_CONFIDENCE: Mapping[int, str] = {
    3: "STRONG",
    2: "MODERATE",
    1: "LIMITED",
    0: "INSUFFICIENT",
}

_CONFIDENCE_RATIONALE: Mapping[str, str] = {
    "STRONG": "At least one claim is backed by Phase 6 root-cause evidence.",
    "MODERATE": "The strongest claim is a statistical association, not an identified cause.",
    "LIMITED": "Only observed changes are supported, so the pattern is real but unexplained.",
    "INSUFFICIENT": "No governed evidence above hypothesis level supports this question.",
    "UNASSESSED": "No claim could be classified against the governed evidence scale.",
}

# Language that asserts a mechanism. It is admissible only on root-cause evidence.
_CAUSAL_LANGUAGE = re.compile(
    r"(?i)\b(caused|causes|causing|because of|due to|led to|leads to|resulted in|"
    r"responsible for|is the cause|root cause of|drove the|driven by)\b")
_ASSOCIATION_QUALIFIER = re.compile(
    r"(?i)\b(associated with|association|correlat\w+|consistent with|not established|"
    r"plausible|unresolved|hypothesis|not identified|cannot be identified)\b")

_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w])")
# Money and percentage figures, in the spellings the project's own artefacts use. The governed
# register abbreviates thousands and millions, so a magnitude suffix is expanded before comparing.
_MAGNITUDES = {"k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9}
_CURRENCY_PREFIX = re.compile(
    r"(?i)(?P<sign>[-+]?)\s*(?:[€$£]|(?:EUR|GBP|USD)\s*)\s*"
    r"(?P<number>-?\d[\d,]*(?:\.\d+)?)\s*(?P<scale>k|m|b|bn)?(?!\w)")
_PERCENT_PREFIX = re.compile(
    r"(?i)(?P<number>-?\d[\d,]*(?:\.\d+)?)\s*(?:%|percent|pct)(?!\w)")


@dataclass(frozen=True)
class GroundingIssue:
    """A reason a generated statement cannot be admitted."""

    category: str
    detail: str

    def to_dict(self) -> dict:
        """JSON-ready category and detail."""
        return {"category": self.category, "detail": self.detail}


@dataclass
class GroundingReport:
    """Issues found in a statement and the evidence values it was checked against."""
    issues: list[GroundingIssue] = field(default_factory=list)
    allowed_values: set[float] = field(default_factory=set)

    @property
    def grounded(self) -> bool:
        """True when no issue was found."""
        return not self.issues

    def add(self, category: str, detail: str) -> None:
        """Record one issue."""
        self.issues.append(GroundingIssue(category, detail))

    def to_dict(self) -> dict:
        """JSON-ready verdict and issues."""
        return {"grounded": self.grounded,
                "issues": [issue.to_dict() for issue in self.issues]}


def strength_for_level(evidence_level: str | None) -> int | None:
    """Read the governed strength for a Phase 6 evidence_level label."""
    if not isinstance(evidence_level, str):
        return None
    return GOVERNED_STRENGTH_BY_LEVEL.get(evidence_level.strip())


def claim_type_for_level(evidence_level: str | None, fallback: EvidenceType = "FACT") -> EvidenceType:
    """Classify a claim the way section 6 requires, from the governed label when there is one.

    ESTIMATE (a model-based value with a disclosed method) maps to MODEL, never FACT or CALCULATED.
    """
    if not isinstance(evidence_level, str):
        return fallback
    label = evidence_level.strip()
    if label in CLAIM_TYPE_BY_LEVEL:
        return CLAIM_TYPE_BY_LEVEL[label]
    if label == "ESTIMATE":
        return "MODEL"
    return fallback


def collect_allowed_values(payloads: Iterable[object]) -> set[float]:
    """Every number that appears in retrieved evidence, including inside short text fields."""
    allowed: set[float] = set()

    def walk(value: object) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            allowed.add(float(value))
        elif isinstance(value, str):
            for token in _NUMBER.findall(value):
                try:
                    allowed.add(float(token.replace(",", "")))
                except ValueError:
                    continue
        elif isinstance(value, Mapping):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)

    for payload in payloads:
        walk(payload)
    return allowed


def check_numeric_grounding(text: str, allowed: set[float]) -> GroundingReport:
    """Reject money and percentage figures in generated text that no evidence supports."""
    report = GroundingReport(allowed_values=set(allowed))
    if not isinstance(text, str) or not text.strip():
        return report
    for pattern in (_CURRENCY_PREFIX, _PERCENT_PREFIX):
        for match in pattern.finditer(text):
            number = _figure_value(match)
            if number is None or _matches_value(number, allowed):
                continue
            report.add("unsourced_value",
                       f"generated text states {match.group(0)!r}, which is absent from the "
                       "retrieved evidence")
    return report


def _figure_value(match: re.Match) -> float | None:
    raw = match.group("number").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    scale = match.groupdict().get("scale")
    if scale:
        value *= _MAGNITUDES[scale.casefold()]
    sign = match.groupdict().get("sign")
    if sign == "-":
        value = -abs(value)
    elif sign == "+":
        value = abs(value)
    return value


def _matches_value(value: float, allowed: set[float]) -> bool:
    if value in allowed:
        return True
    # A narrative may round or abbreviate a governed value; accept a match at the displayed
    # precision rather than demanding an exact float.
    for candidate in allowed:
        if abs(candidate - value) <= max(abs(candidate) * 0.001, 0.005):
            return True
    return False


def check_causal_language(text: str, strongest_strength: int | None) -> GroundingReport:
    """Refuse to let correlation be presented as causation (section 6)."""
    report = GroundingReport()
    if not isinstance(text, str) or not text.strip():
        return report
    causal = _CAUSAL_LANGUAGE.search(text)
    if causal and not _ASSOCIATION_QUALIFIER.search(text):
        if strongest_strength is None or strongest_strength < GOVERNED_STRENGTH_BY_LEVEL["Root-cause evidence"]:
            report.add("causal_overreach",
                       f"generated text asserts a cause using {causal.group(0)!r} while the "
                       "strongest governed evidence is below root-cause level")
    return report


def check_grounding(text: str, evidence: Sequence[EvidenceClaim],
                    structural_values: Iterable[float] = ()) -> GroundingReport:
    """Full section 6 gate for one generated statement."""
    payloads: list[object] = []
    strengths: list[int] = []
    for claim in evidence:
        payloads.append(claim.to_dict())
        if claim.evidence_type == "FORECAST":
            continue
        strengths.append(_strength_from_claim(claim))
    allowed = collect_allowed_values(payloads) | {float(value) for value in structural_values}
    report = GroundingReport(allowed_values=allowed)
    if not evidence:
        report.add("no_evidence", "no evidence was retrieved for this answer")
    numeric = check_numeric_grounding(text, allowed)
    report.issues.extend(numeric.issues)
    causal = check_causal_language(text, max(strengths) if strengths else None)
    report.issues.extend(causal.issues)
    if not isinstance(text, str) or not text.strip():
        report.add("empty_statement", "generated text is empty")
    return report


def _strength_from_claim(claim: EvidenceClaim) -> int:
    level = (claim.filters or {}).get("evidence_level")
    strength = strength_for_level(level)
    if strength is not None:
        return strength
    if claim.evidence_type in {"FACT", "CALCULATED", "MODEL"}:
        return GOVERNED_STRENGTH_BY_LEVEL["Observed change"]
    if claim.evidence_type in {"ATTRIBUTION", "ASSOCIATION"}:
        return GOVERNED_STRENGTH_BY_LEVEL["Statistical association"]
    return GOVERNED_STRENGTH_BY_LEVEL["Hypothesis"]


def assess_confidence(evidence: Sequence[EvidenceClaim]) -> tuple[str, str]:
    """Derive the confidence label and its rationale from governed evidence only.

    A forecast is capped at moderate: a fitted projection is never identified evidence about a
    cause, and Phase 10 publishes intervals rather than a root-cause strength.
    """
    if not evidence:
        return "INSUFFICIENT", _CONFIDENCE_RATIONALE["INSUFFICIENT"]
    non_forecast = [claim for claim in evidence if claim.evidence_type != "FORECAST"]
    strengths = [_strength_from_claim(claim) for claim in non_forecast]
    if not strengths:
        return "MODERATE", "Only forecast evidence supports this answer; forecasts are capped at moderate."
    strongest = max(strengths)
    if strongest >= GOVERNED_STRENGTH_BY_LEVEL["Root-cause evidence"] and any(
            claim.evidence_type == "FORECAST" for claim in evidence):
        return "MODERATE", ("Root-cause evidence is present but a forecast is included, so the "
                            "answer is capped at moderate.")
    label = _STRENGTH_TO_CONFIDENCE[strongest]
    return label, _CONFIDENCE_RATIONALE[label]