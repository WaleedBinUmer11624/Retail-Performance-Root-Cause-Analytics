"""The question contract: what the analyst is allowed to be asked, and what it must resolve first.

A question is parsed into a typed intent plus a dimension set. Two things are deliberately strict.
A dimension the system cannot verify against a governed dimension table is an error, not a guess.
And a question whose period or comparison cannot be resolved is either answered for the stated
interpretation or refused; it is never quietly given a period nobody asked for.

Inputs: the question text and the governed dimension lookup. Output: a ParsedQuestion with intent,
filters, period and any clarifications still needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

INTENTS = (
    "kpi_performance",
    "target_variance",
    "yoy_performance",
    "wow_performance",
    "store_performance",
    "category_performance",
    "transaction_contribution",
    "availability_evidence",
    "returns_evidence",
    "promotion_evidence",
    "root_cause_attribution",
    "monitoring_signals",
    "forecasting",
    "data_quality",
    "recommended_actions",
)

# Ambiguity that must be resolved before an answer, never assumed away.
REQUIRED_WHEN_UNSPECIFIED = {
    "target_variance": ("period",),
    "wow_performance": ("period",),
    "store_performance": ("entity",),
    "category_performance": ("entity",),
    "availability_evidence": ("entity",),
    "returns_evidence": ("entity",),
    "promotion_evidence": ("entity",),
}

EVIDENCE_LEVELS = ("FACT", "ATTRIBUTION", "ASSOCIATION", "INTERPRETATION", "LIMITATION")


class QuestionError(ValueError):
    """The question cannot be answered from validated evidence."""


@dataclass
class ParsedQuestion:
    """A question resolved into intent, entity filters and period."""
    question: str
    intent: str
    store_id: str | None = None
    store_group: str | None = None
    category: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    retail_year: int | None = None
    retail_half: str | None = None
    retail_week_key: int | None = None
    comparison: str = "prior_year"
    kpi: str = "net_revenue"
    period: str | None = None
    needs_clarification: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def filters(self) -> dict:
        """Only the filters that were actually set."""
        return {key: value for key, value in {
            "store_id": self.store_id, "store_group": self.store_group, "category": self.category,
            "supplier": self.supplier, "product_id": self.product_id, "retail_year": self.retail_year,
            "retail_half": self.retail_half, "retail_week_key": self.retail_week_key,
            "comparison": self.comparison, "kpi": self.kpi,
        }.items() if value is not None}

    def to_dict(self) -> dict:
        """JSON-ready copy."""
        return {"question": self.question, "intent": self.intent, "filters": self.filters(),
                "comparison": self.comparison, "period": self.period,
                "needs_clarification": list(self.needs_clarification), "notes": list(self.notes)}


# Order matters: the first match wins, so specific intents sit above broad ones like "store".
_INTENT_PATTERNS = [
    (r"\bforecast|next\s+\d+\s+weeks|predict|projection\b", "forecasting"),
    (r"\bsignal|alert|early[- ]warning|monitor\w*\b", "monitoring_signals"),
    (r"\bdata quality|completeness|timeliness|missing data|lineage\b", "data_quality"),
    (r"\baction|should we|recommend|next step|what do we do\b", "recommended_actions"),
    (r"\btarget|miss(ed|ing)? (its |the )?target|variance to target|achievement\b", "target_variance"),
    (r"\battribution|contribut\w+|decline|what drove|root cause|why did\b", "root_cause_attribution"),
    (r"\bavailability|stock[- ]?out|in stock|range[d]? cells?\b", "availability_evidence"),
    (r"\breturns?\b", "returns_evidence"),
    (r"\bpromotion\w*|discount|on offer|price cut\b", "promotion_evidence"),
    (r"\btransaction\w*|receipts?|basket|footfall|volume\b", "transaction_contribution"),
    (r"\byoy|year[- ]on[- ]year|versus last year|vs last year|compared to last year\b", "yoy_performance"),
    (r"\bwow|week[- ]on[- ]week|vs last week|compared to last week\b", "wow_performance"),
    (r"\bcategor\w+|electronics|home & kitchen|garden|health & beauty|toys|stationery|seasonal\b",
     "category_performance"),
    (r"\bstore|shop|s\d{2}\b", "store_performance"),
    (r"\bkpi|how (is|are|did).*(perform|doing|going)\b", "kpi_performance"),
]

PERIOD_HINTS = {
    "h2 2025": (2025, "H2"), "h2 2024": (2024, "H2"),
    "h1 2025": (2025, "H1"), "h1 2024": (2024, "H1"),
    "2025 h2": (2025, "H2"), "2024 h2": (2024, "H2"),
    "full year 2025": (2025, "FY"), "full year 2024": (2024, "FY"),
    "fy2025": (2025, "FY"), "fy2024": (2024, "FY"),
}

_WEEK = re.compile(r"\b(20\d{2})-?w(\d{1,2})\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d{2})\b")


def detect_intent(question: str) -> str | None:
    """First matching intent for the question, or None if nothing matches."""
    text = question.lower()
    for pattern, intent in _INTENT_PATTERNS:
        if re.search(pattern, text):
            return intent
    return None


def parse(question: str, dimensions: dict) -> ParsedQuestion:
    """Parse into a typed intent. `dimensions` is the governed dimension lookup, so a store or
    category that does not exist is reported as unknown rather than guessed at."""
    if not isinstance(question, str) or not question.strip():
        raise QuestionError("An empty question cannot be answered")
    if len(question) > 500:
        raise QuestionError("The question is too long to parse safely")

    notes: list[str] = []
    intent = detect_intent(question)
    if intent is None:
        raise QuestionError(
            "I could not map this to a supported analytical intent. Supported intents: "
            + ", ".join(INTENTS)
        )
    if intent not in INTENTS:
        raise QuestionError(f"Unsupported intent: {intent}")

    parsed = ParsedQuestion(question=question.strip(), intent=intent)
    text = question.lower()

    match = re.search(r"\bs(\d{2})\b", text) or re.search(r"\bstore\s*0?(\d{1,2})\b", text)
    if match:
        candidate = f"S{int(match.group(1)):02d}"
        if candidate not in dimensions["stores"]:
            raise QuestionError(
                f"{candidate} is not a trading store in the governed dimension. "
                f"Known stores run from {min(dimensions['stores'])} to {max(dimensions['stores'])}."
            )
        parsed.store_id = candidate
    else:
        for store_id, name in dimensions["store_names"]:
            if name.lower() in text:
                parsed.store_id = store_id
                break

    for category in dimensions["categories"]:
        if category.lower() in text:
            parsed.category = category
            break
    for supplier in dimensions["suppliers"]:
        if supplier.lower() in text:
            parsed.supplier = supplier
            break
    if parsed.store_id is None and re.search(r"\b(cluster|investigated cluster)\b", text):
        parsed.store_group = "cluster"
    if parsed.store_id is None and re.search(r"\b(control|matched control|control stores)\b", text):
        parsed.store_group = "matched_control"

    week = _WEEK.search(text)
    if week:
        parsed.retail_year = int(week.group(1))
        parsed.retail_week_key = int(week.group(1)) * 100 + int(week.group(2))
    for phrase, (year, half) in PERIOD_HINTS.items():
        if phrase in text:
            parsed.retail_year = year
            parsed.retail_half = half
            break
    if parsed.retail_year is None:
        year = _YEAR.search(text)
        if year:
            parsed.retail_year = int(year.group(1))
    if re.search(r"\b(h1|first half)\b", text) and parsed.retail_half is None:
        parsed.retail_half = "H1"
    if re.search(r"\b(h2|second half)\b", text) and parsed.retail_half is None:
        parsed.retail_half = "H2"

    if re.search(r"\b(miss(ed|ing)?|underperform\w*|below target|short of)\b", text):
        parsed.comparison = "target"
    elif re.search(r"\b(yoy|year[- ]on[- ]year|last year|prior year)\b", text):
        parsed.comparison = "prior_year"
    elif re.search(r"\b(wow|week[- ]on[- ]week|last week)\b", text):
        parsed.comparison = "prior_week"

    if re.search(r"\btransactions?\b", text) and "transaction" in intent:
        parsed.kpi = "net_revenue"
    if re.search(r"\bavailability\b", text):
        parsed.kpi = "stock_availability"

    relative = re.search(r"\b(last week|past week|most recent week)\b", text)
    if relative:
        parsed.period = "last_complete_retail_week"
        notes.append("'last week' is read as the most recent complete retail week in the warehouse")
    elif parsed.retail_week_key is not None:
        parsed.period = f"{parsed.retail_year}-W{parsed.retail_week_key % 100:02d}"
    elif parsed.retail_half is not None:
        parsed.period = f"{parsed.retail_year} {parsed.retail_half}"
    elif parsed.retail_year is not None:
        parsed.period = f"{parsed.retail_year}"

    missing = []
    for requirement in REQUIRED_WHEN_UNSPECIFIED.get(intent, ()):
        if requirement == "entity" and not (parsed.store_id or parsed.store_group or parsed.category
                                            or parsed.supplier):
            missing.append("entity")
        if requirement == "period" and parsed.period is None:
            missing.append("period")
    if intent in ("root_cause_attribution", "kpi_performance", "yoy_performance",
                  "transaction_contribution") and not (parsed.store_id or parsed.store_group
                                                        or parsed.category or parsed.supplier):
        missing.append("entity")
    if intent in ("root_cause_attribution", "kpi_performance", "yoy_performance") \
            and parsed.period is None:
        missing.append("period")
    parsed.needs_clarification = tuple(dict.fromkeys(missing))
    parsed.notes = tuple(notes)
    return parsed


def clarification_question(parsed: ParsedQuestion) -> str:
    """Ask for exactly what is missing, in the user's own terms."""
    asks = []
    if "entity" in parsed.needs_clarification:
        asks.append("which store, store group, category or supplier you mean")
    if "period" in parsed.needs_clarification:
        asks.append("the period (for example 2025-W52, H2 2025 or the last complete retail week)")
    return "Before I can answer, I need " + " and ".join(asks) + "."
