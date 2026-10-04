"""Grounded orchestration for the Phase 11 assistant (brief sections 10, 11, 12 and 15).

Two modes are supported. Executive mode answers what happened, when, where, how large, what
supports it and what is still uncertain. Investigation mode goes deeper and is allowed to be more
detailed. Forecast questions use the frozen Phase 10 artifacts and are labelled as forecasts.

The language model never computes anything. It is offered deterministic evidence and its output is
admitted only after the section 6 grounding gate accepts it. The default provider is the offline
mock, so the whole path is exercisable with no API key and no network (section 15).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from src.analyst.evidence import InsufficientEvidence
from src.analyst.intents import detect_intent

from . import grounding
from .assembly import EvidenceBundle
from .artifacts import ArtifactError
from .injection import (
    ArgumentRejected,
    RefusalRequired,
    build_generation_request,
    refuse_injected_question,
    refuse_out_of_scope,
    scan_untrusted_text,
    validate_tool_arguments,
)
from .observability import RequestTrace, log_trace, new_request_id
from .path_guard import PathDeniedError
from .providers import GenerationRequest, LanguageModelProvider
from .response_schema import EvidenceClaim, GroundedResponse, normalise_evidence_type
from .retrieval import KeywordIndex
from .tools import ToolError, ToolRegistry

EXECUTIVE = "executive"
INVESTIGATION = "investigation"

# Evidence selection is a closed table, not a model decision. A mode or intent names its tools.
EXECUTIVE_TOOLS: tuple[str, ...] = (
    "get_revenue_summary", "get_driver_attribution", "get_evidence_matrix", "get_investigation_evidence",
)
INVESTIGATION_TOOLS: tuple[str, ...] = (
    "get_revenue_bridge", "get_cluster_analysis", "get_stockout_analysis", "get_supplier_analysis",
    "get_returns_analysis", "get_promotion_analysis", "get_evidence_matrix",
)
FORECAST_TOOLS: tuple[str, ...] = (
    "get_forecast", "get_forecast_intervals", "get_forecast_model_comparison",
)
INTENT_TOOLS: Mapping[str, tuple[str, ...]] = {
    "forecasting": FORECAST_TOOLS,
    "root_cause_attribution": EXECUTIVE_TOOLS,
    "availability_evidence": ("get_stockout_analysis", "get_evidence_matrix"),
    "returns_evidence": ("get_returns_analysis", "get_evidence_matrix"),
    "promotion_evidence": ("get_promotion_analysis", "get_evidence_matrix"),
    "transaction_contribution": ("get_cluster_analysis", "get_revenue_bridge"),
    "monitoring_signals": ("get_monitoring_signals",),
    "store_performance": ("get_store_performance",),
    "product_performance": ("get_stockout_analysis", "get_returns_analysis"),
    "category_performance": ("get_revenue_bridge", "get_driver_attribution"),
    "recommended_actions": ("get_investigation_evidence", "get_evidence_matrix"),
    "data_quality": ("get_monitoring_signals",),
}

# Columns are rendered from the governed file as it holds them, so no claim can depend on a
# guessed column name. Identity, the primary metric and the governed evidence level are always
# shown; any remaining field fills the remaining slots in file order.
_MAX_CLAIM_FIELDS = 6
_CLAIM_ROW_LIMIT = 12

_IDENTITY_FIELDS: tuple[str, ...] = (
    "driver_id", "component", "action_id", "field", "issue_id", "model", "method_code",
    "store_id", "product_id", "supplier_name", "topic", "priority", "page",
)
_METRIC_PREFERENCE: tuple[str, ...] = (
    "financial_impact_eur", "estimated_impact_eur", "amount_eur", "lost_primary_change",
    "effect_eur", "point_forecast", "value", "change",
)
_MAX_RETRIEVAL_HITS = 5

# Share of a question's meaningful words the gathered evidence must cover before it may answer.
_TOPIC_COVERAGE_MINIMUM = 0.5

# Refusals decided from the question alone, before any evidence is gathered. Anything else was
# refused only after retrieval, and its limitation must say so.
_PRE_RETRIEVAL_REFUSALS = frozenset({"out_of_scope", "prompt_injection", "empty_question"})

# The project's own identifier forms, used to pass a named entity to the tool that serves it.
_IDENTIFIER_PATTERNS: Mapping[str, str] = {
    "store_id": r"\bS\d{2}\b",
    "product_id": r"\bP\d{5}\b",
    "driver_id": r"\bD\d{2}\b",
}

# Intents the governed documentation itself answers. Every other intent needs a governed record.
_DOCUMENTATION_INTENTS = frozenset({"recommended_actions"})

SYSTEM_RULES = (
    "You are the Brightwater retail analytics assistant. Answer only from the supplied evidence. "
    "Every figure you state must appear in the evidence block. Never invent percentages, revenue "
    "values, stores, products, dates, drivers, forecast values or confidence levels. If the "
    "evidence does not support a conclusion, say that evidence is insufficient. Do not present an "
    "association as a proven cause."
)


# Phase 11 vocabulary that src.analyst.intents does not carry, mapped onto the same governed
# intents. The core parser is the first pass and is never modified; this only adds the words the
# executive and evidence questions in this brief actually use.
_EXTRA_INTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brevenue bridge\b|\bdrivers?\b", "root_cause_attribution"),
    (r"\bevidence matrix\b|\broot[- ]cause\b", "root_cause_attribution"),
    (r"\bexecutive summary\b|\bsummar", "root_cause_attribution"),
    (r"\bwhat happened\b|\bincident\b", "root_cause_attribution"),
    (r"\brisks?\b|\buncertaint", "root_cause_attribution"),
    (r"\bmethodolog|\bhow (was|were|did) .*(calculat|measur|comput)", "recommended_actions"),
    (r"\bshould (we|be)\b|\bnext step\b|\brecommend", "recommended_actions"),
    (r"\b(products?|skus?)\b", "product_performance"),
)

_RETRIEVAL_EXCERPT_CHARS = 220

# Words that carry no analytical meaning when deciding whether retrieved evidence is on topic.
_TOPIC_STOPWORDS = frozenset({
    "about", "after", "again", "against", "along", "also", "been", "before", "being", "between",
    "both", "could", "does", "doing", "done", "during", "each", "from", "have", "having", "here",
    "into", "itself", "just", "main", "more", "most", "much", "must", "only", "other", "over",
    "same", "should", "show", "shows", "some", "such", "than", "that", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "under", "very", "were", "what", "when",
    "where", "which", "while", "with", "would", "your", "give", "tell", "explain", "because",
    "potentially", "contributed", "used", "many", "much", "every", "any", "how",
})


def topic_terms(text: str) -> set[str]:
    """The meaningful words of a question, used to judge whether evidence is on topic."""
    return {word for word in re.findall(r"[a-z]{4,}", text.casefold())
            if word not in _TOPIC_STOPWORDS}


# A four-digit year, not the leading digits of a longer number such as a row count or a week key.
_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def _years_in(text: str) -> set[int]:
    return {int(match.group(0)) for match in _YEAR.finditer(text)}


def _addresses_question(question: str, corpus: str) -> bool:
    """True when the gathered evidence covers enough of what the question actually asked.

    Requiring every word would refuse answerable questions, because an analytical question
    paraphrases the evidence rather than quoting it. Requiring one word is too weak: "stores"
    appears in almost every artefact, so a question about competitor openings would look answered
    by any store-level table. Half the question's meaningful words is the balance.
    """
    terms = topic_terms(question)
    if not terms:
        return True
    haystack = corpus.casefold()
    matched = sum(1 for term in terms if term in haystack)
    return matched / len(terms) >= _TOPIC_COVERAGE_MINIMUM


def _period_in_evidence(question: str, corpus: str) -> bool:
    """True unless the question names a year the gathered evidence never mentions.

    The governed artefacts carry 2024 and 2025 actuals and the 2026 forecast horizon. A question
    about a period the evidence never mentions cannot be answered from it, whatever else it asks.
    """
    asked = _years_in(question)
    if not asked:
        return True
    return asked <= _years_in(corpus)


def detect_phase11_intent(question: str) -> str:
    """Resolve a question to a governed intent, or an empty string when none applies."""
    intent = detect_intent(question)
    if intent:
        return intent
    for pattern, resolved in _EXTRA_INTENT_PATTERNS:
        if re.search(pattern, question, re.IGNORECASE):
            return resolved
    return ""


def _cell(value: object) -> str:
    return "" if value is None else str(value).strip()


def _ordered_fields(fields: list[tuple[str, str]],
                    limit: int = _MAX_CLAIM_FIELDS) -> tuple[list[tuple[str, str]], str | None]:
    """Choose what a claim shows: identity first, then the primary metric, then evidence level."""
    by_key = dict(fields)
    ordered: list[tuple[str, str]] = []

    def include(name: str) -> None:
        if by_key.get(name) and all(existing != name for existing, _ in ordered):
            ordered.append((name, by_key[name]))

    for name in _IDENTITY_FIELDS:
        include(name)
    metric = next((name for name in _METRIC_PREFERENCE if by_key.get(name)), None)
    if metric:
        include(metric)
    include("evidence_level")
    for name, value in fields:
        if len(ordered) >= limit:
            break
        include(name)
    return ordered[:limit], metric


def build_claims(result, limit: int = _CLAIM_ROW_LIMIT) -> list[EvidenceClaim]:
    """Turn one tool result into evidence claims, classified against the governed scale.

    A tool may bundle several governed files. When it does, the provenance entries line up with
    the data labels positionally, and each claim is attributed to the file its own rows came from.
    """
    claims: list[EvidenceClaim] = []
    provenance = list(result.provenance)
    labels = list(result.data)
    fallback = normalise_evidence_type(result.evidence_type)
    if len(provenance) == len(labels):
        pairs = list(zip(labels, provenance))
    elif provenance:
        pairs = [(label, provenance[0]) for label in labels]
    else:
        return claims
    for label, source in pairs:
        source_id = str(source["source_file"])
        rows = result.data.get(label)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows[:limit], start=1):
            if not isinstance(row, Mapping):
                continue
            fields = [(str(key), _cell(value)) for key, value in row.items() if _cell(value)]
            if not fields:
                continue
            selected, metric_name = _ordered_fields(fields)
            level = dict(fields).get("evidence_level")
            claim_type = grounding.claim_type_for_level(level, fallback=fallback)
            rendered = "; ".join(f"{key}={value}" for key, value in selected)
            value: float | int | None = None
            if metric_name:
                try:
                    value = float(dict(fields)[metric_name])
                except ValueError:
                    value = None
            claims.append(EvidenceClaim(
                evidence_id=f"tool:{result.tool}:{label}:{index}",
                evidence_type=claim_type,
                claim=f"{label}: {rendered}",
                source_ids=(source_id,) if source_id else (),
                metric=metric_name,
                value=value,
                filters={"evidence_level": level} if level else {},
            ))
    return claims


def compose_answer(claims: Sequence[EvidenceClaim], intent: str, mode: str) -> str:
    """Build the answer deterministically. Nothing here is generated text."""
    if not claims:
        return grounding.INSUFFICIENT_EVIDENCE_ANSWER
    if mode == EXECUTIVE:
        lead = f"{len(claims)} governed evidence record(s) support the following for '{intent}'."
    else:
        lead = f"Investigation detail for '{intent}', drawn from {len(claims)} governed record(s)."
    body = " | ".join(claim.claim for claim in claims[:4])
    return f"{lead} {body}"


def compose_executive_summary(claims: Sequence[EvidenceClaim], confidence: str, rationale: str,
                              has_forecast: bool, limitations: Sequence[str]) -> str:
    """One-paragraph summary of evidence strength, forecast status and limitation count."""
    if not claims:
        return grounding.INSUFFICIENT_EVIDENCE_ANSWER
    parts = [
        f"Evidence strength is {confidence}: {rationale}",
        "Forecasts are included and are projections, not actual results." if has_forecast else "",
        f"{len(limitations)} stated limitation(s) apply." if limitations else "",
    ]
    return " ".join(part for part in parts if part)


class GroundedAssistant:
    """Offline-first question answering over frozen project evidence."""

    def __init__(self, tools: ToolRegistry, retriever: KeywordIndex,
                 provider: LanguageModelProvider, config: Mapping,
                 provider_name: str = "mock", model: str = "deterministic_v1",
                 logger: logging.Logger | None = None):
        self.tools = tools
        self.retriever = retriever
        self.provider = provider
        self.config = config
        self.provider_name = provider_name
        self.model = model
        self.logger = logger if logger is not None else logging.getLogger("phase11.assistant")

    def resolve_mode(self, question: str, mode: str | None) -> tuple[str, str]:
        """Pick the mode and tool set deterministically from the question's governed intent.

        A forecast question always uses the Phase 10 tools. Otherwise an explicitly requested mode
        wins, because the caller has already decided how deep the answer should be.
        """
        intent = detect_phase11_intent(question)
        if intent == "forecasting":
            return FORECAST_TOOLS, intent
        if mode in {EXECUTIVE, INVESTIGATION}:
            return (EXECUTIVE_TOOLS if mode == EXECUTIVE else INVESTIGATION_TOOLS), intent
        selected = INTENT_TOOLS.get(intent)
        if selected:
            return selected, intent
        return EXECUTIVE_TOOLS, intent

    def ask(self, question: str, mode: str | None = None) -> GroundedResponse:
        """Answer one question; refusals and errors become structured responses, and every
        request writes exactly one redacted trace line."""
        tools, intent = self.resolve_mode(question, mode)
        trace = RequestTrace(request_id=new_request_id(), question_category=intent or "unclassified",
                             mode=mode or "auto", provider=self.provider_name, model=self.model)
        try:
            response = self._answer(question, intent, tools, trace)
        except RefusalRequired as refusal:
            trace.error = refusal.category
            response = self._refusal_response(refusal, refusal.limitations)
            trace.grounded = True
        except (ToolError, ArgumentRejected, ArtifactError, PathDeniedError,
                InsufficientEvidence, ValueError) as error:
            trace.error = type(error).__name__
            response = self._error_response(error)
        trace.confidence = response.confidence
        trace.grounded = True
        trace.finish()
        log_trace(trace, self.logger)
        return response

    def _refusal_response(self, refusal: RefusalRequired,
                          extra_limitations: Sequence[str] = ()) -> GroundedResponse:
        if refusal.category in _PRE_RETRIEVAL_REFUSALS:
            limitation = (f"The request was refused before retrieval because {refusal.reason} "
                          f"({refusal.category}).")
        else:
            # The refusal came after evidence was gathered, so it must not claim otherwise.
            limitation = (f"No governed evidence was admitted because {refusal.reason} "
                          f"({refusal.category}).")
        # Any injection findings or tool errors found before the refusal must still be reported.
        all_limitations = (limitation,) + tuple(extra_limitations)
        return GroundedResponse(
            answer=grounding.INSUFFICIENT_EVIDENCE_ANSWER,
            executive_summary="No governed evidence was retrieved for this request.",
            evidence=(), sources=(), confidence="INSUFFICIENT",
            limitations=all_limitations,
            recommended_follow_up=(
                "Re-ask as a business question about revenue, stores, products, returns, "
                "promotions, root cause or the forecast.",),
        )

    def _error_response(self, error: Exception) -> GroundedResponse:
        return GroundedResponse(
            answer=grounding.INSUFFICIENT_EVIDENCE_ANSWER,
            executive_summary="The governed evidence could not be retrieved for this question.",
            evidence=(), sources=(), confidence="INSUFFICIENT",
            limitations=(f"Evidence retrieval failed: {type(error).__name__}.",),
            recommended_follow_up=("Ask again once the governed artefacts are available.",),
        )

    def _answer(self, question: str, intent: str, tools: Sequence[str],
                trace: RequestTrace) -> GroundedResponse:
        refuse_out_of_scope(question, self.config.get("out_of_scope_patterns", ()))
        refuse_injected_question(question)
        if not intent:
            # No governed intent means no governed evidence can answer this, and answering with
            # whatever evidence happens to be nearby would be misleading rather than helpful.
            raise RefusalRequired(
                "question does not match a governed analytical intent", "unsupported_question")

        bundle = EvidenceBundle(question=question, intent=intent)
        limitations: list[str] = []
        for name in tools:
            try:
                arguments = validate_tool_arguments(self._tool_arguments(question, name),
                                                    self._allowed_arguments(name))
                bundle.add_tool(self.tools.run(name, arguments))
                trace.tool_calls.append(name)
            except (ToolError, ArgumentRejected, ArtifactError, PathDeniedError,
                    InsufficientEvidence, ValueError) as error:
                trace.unavailable_tools.append(name)
                limitations.append(f"{name} was unavailable: {type(error).__name__}.")

        hits = self._retrieve(question, trace, limitations)
        for hit in hits:
            bundle.add_retrieval([hit])
            findings = scan_untrusted_text(hit.text)
            if findings:
                trace.blocked_injections += len(findings)
                limitations.append(
                    f"Retrieved chunk {hit.provenance.get('source_file')} contained "
                    f"{len(findings)} instruction-like span(s) that were treated as data, not commands.")

        claims, governed = self._claims(bundle, trace)
        if not governed and intent not in _DOCUMENTATION_INTENTS:
            # No governed record answered the question and the documentation is context, not
            # evidence. Reporting a documentation excerpt as the answer would misrepresent it.
            raise RefusalRequired(
                "no governed evidence record addresses this question", "unsupported_question",
                limitations=tuple(limitations))
        sources = self._sources(bundle)
        corpus = " ".join(claim.claim for claim in claims) + " " + \
            " ".join(hit.text for hit in hits)
        if not _period_in_evidence(question, corpus):
            raise RefusalRequired(
                f"the question names a period the governed evidence does not cover; "
                f"it mentions {', '.join(str(year) for year in sorted(_years_in(corpus)))}",
                "out_of_period", limitations=tuple(limitations))
        if governed and not _addresses_question(question, " ".join(item.claim for item in governed)):
            # A governed record was found, but it does not cover what was asked. Documentation may
            # share a word with the question without answering it, so only records are counted.
            raise RefusalRequired(
                "no governed evidence record addresses this question", "unsupported_question",
                limitations=tuple(limitations))
        has_forecast = any(claim.evidence_type == "FORECAST" for claim in claims)
        if has_forecast:
            claims.append(EvidenceClaim(
                evidence_id="limitation:forecast",
                evidence_type="LIMITATION",
                claim=grounding.FORECAST_NOTE,
                source_ids=tuple(source["source_file"] for source in sources),
            ))
            limitations.append(grounding.FORECAST_NOTE)

        confidence, rationale = grounding.assess_confidence(claims)
        mode = EXECUTIVE if tools == tuple(EXECUTIVE_TOOLS) else INVESTIGATION
        answer = compose_answer(claims, intent, mode)
        answer = self._admit_narrative(question, answer, claims, trace, limitations)

        trace.source_ids.extend(source["source_file"] for source in sources)
        payload = GroundedResponse(
            answer=answer,
            executive_summary=compose_executive_summary(claims, confidence, rationale,
                                                        has_forecast, limitations),
            evidence=tuple(claims),
            sources=tuple(sources),
            confidence=confidence,
            limitations=tuple(dict.fromkeys(limitations)),
            recommended_follow_up=self._follow_ups(claims, has_forecast),
        )
        payload.to_dict()
        return payload

    def _admit_narrative(self, question: str, answer: str, claims: Sequence[EvidenceClaim],
                         trace: RequestTrace, limitations: list[str]) -> str:
        """Offer the provider a narrative, but keep it only if the section 6 gate accepts it.

        Grounding is checked first, so invented values and unwarranted causes are always
        discarded and reported. A narrative that survives grounding but adds nothing beyond the
        deterministic rendering also loses, so a thin answer can never displace governed evidence.
        """
        records = [claim.to_dict() for claim in claims]
        request = build_generation_request(question, records, SYSTEM_RULES)
        structural = {float(len(claims)), float(len(records))}
        try:
            narrative = self.provider.complete(request)
        except Exception as error:
            trace.error = type(error).__name__
            limitations.append("The language model was unavailable, so the deterministic "
                               "evidence-only answer was returned.")
            return answer
        if not isinstance(narrative, str) or not narrative.strip():
            return answer
        report = grounding.check_grounding(narrative, claims, structural_values=structural)
        if not report.grounded:
            limitations.append("The generated narrative failed grounding and was discarded; the "
                               "answer is the deterministic evidence-only rendering.")
            return answer
        if len(narrative.strip()) <= len(answer):
            return answer
        trace.narrative_admitted = True
        return narrative.strip()

    def _allowed_arguments(self, name: str) -> set[str]:
        return set(self.tools.allowed_arguments(name))

    def _tool_arguments(self, question: str, name: str) -> dict[str, str]:
        """Read a governed entity identifier out of the question, for the tools that take one.

        Only the project's own identifier forms are recognised, and only for the argument a tool
        declares, so a question cannot steer a tool to an artefact or a query it does not serve.
        """
        allowed = self._allowed_arguments(name)
        arguments: dict[str, str] = {}
        for argument, pattern in _IDENTIFIER_PATTERNS.items():
            if argument not in allowed:
                continue
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                arguments[argument] = match.group(0).upper()
        return arguments

    def _retrieve(self, question: str, trace: RequestTrace, limitations: list[str]) -> list:
        try:
            hits = self.retriever.search(question, top_k=_MAX_RETRIEVAL_HITS)
        except ValueError as error:
            limitations.append(f"Text retrieval was skipped: {type(error).__name__}.")
            return []
        trace.retrieval_hits = len(hits)
        return hits

    def _claims(self, bundle: EvidenceBundle, trace: RequestTrace) -> tuple[list[EvidenceClaim], list[EvidenceClaim]]:
        """Return every admitted claim, and separately the ones a governed record supports.

        Documentation is context. It is admitted only when no governed record was available, and
        the split lets the caller hold documentation to a lower standard than evidence.
        """
        claims: list[EvidenceClaim] = []
        for result in bundle.tool_results:
            claims.extend(build_claims(result))
        governed = list(claims)
        if not claims:
            for index, hit in enumerate(bundle.retrieval_hits, start=1):
                source = hit.provenance
                claims.append(EvidenceClaim(
                    evidence_id=f"text:{index}",
                    evidence_type="INTERPRETATION",
                    claim=f"Documentation chunk: "
                          f"{' '.join(hit.text.split())[:_RETRIEVAL_EXCERPT_CHARS]}",
                    source_ids=(str(source["source_file"]),),
                ))
        return claims, governed

    def _sources(self, bundle: EvidenceBundle) -> list[dict]:
        seen: dict[str, dict] = {}
        for result in bundle.tool_results:
            for source in result.provenance:
                seen.setdefault(str(source["source_file"]), self._source_entry(source))
        for hit in bundle.retrieval_hits:
            entry = self._source_entry(hit.provenance)
            seen.setdefault(str(entry["source_file"]), entry)
        return [seen[key] for key in sorted(seen)]

    @staticmethod
    def _source_entry(provenance: Mapping) -> dict:
        """Keep only the provenance fields the response contract publishes.

        Retrieval provenance also carries chunk coordinates, which are internal and would
        otherwise fail the source contract.
        """
        return {
            "source_file": str(provenance["source_file"]),
            "phase": str(provenance["phase"]),
            "retrieval_method": str(provenance["retrieval_method"]),
            "content_sha256": str(provenance["content_sha256"]),
            "filters": dict(provenance.get("filters") or {}),
            "record_count": provenance.get("record_count"),
            "row_index": provenance.get("row_index"),
        }

    def _follow_ups(self, claims: Sequence[EvidenceClaim], has_forecast: bool) -> tuple[str, ...]:
        follow_ups: list[str] = []
        unresolved = [claim for claim in claims
                      if grounding.strength_for_level((claim.filters or {}).get("evidence_level")) == 0]
        if unresolved:
            follow_ups.append("Open the priority 1 investigation items, since the remaining "
                              "drivers are hypotheses with no root-cause evidence.")
        if any(claim.evidence_type in {"ASSOCIATION", "INFERENCE"} for claim in claims):
            follow_ups.append("Ask which stores and cohorts concentrate the associated drivers.")
        if has_forecast:
            follow_ups.append("Ask how much the forecast interval widens over the 13-week horizon.")
        if not follow_ups:
            follow_ups.append("Ask for the supporting driver attribution and evidence levels.")
        return tuple(follow_ups)


def offline_generation_request(question: str) -> GenerationRequest:
    """The exact request shape used in mock mode, exposed so tests can assert on it."""
    return build_generation_request(question, (), SYSTEM_RULES)