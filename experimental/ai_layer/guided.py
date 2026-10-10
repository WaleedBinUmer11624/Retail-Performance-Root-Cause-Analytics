"""Guided intents: one governed driver per question, answered in plain sentences.

The general path (orchestrator.GroundedAssistant._answer) gathers a whole tool bundle and renders
its rows. That suits an analyst, but it shares one bundle between unrelated questions and scores
the badge on the strongest record in it, so a promotion question could carry the stock-out
driver's root-cause badge. A guided intent fixes both:

  * each intent reads only the evidence for its own driver;
  * its badge comes from that driver's governed evidence_level label (Phase 6 evidence matrix,
    or the label the governed Phase 9 alert log carries), never from another record;
  * its answer is a few sentences built from the selected rows only, and every claim it publishes
    holds every figure the sentences quote, so the section 6 gate can check them.

Guided intents apply only when the caller did not ask for a mode. Explicit executive and
investigation requests keep the general path unchanged. Nothing here computes a new result:
figures are copied from governed rows, rounded for display, and shown as magnitudes or
percentages where the sentence needs them (the claim states both forms).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from . import grounding
from .response_schema import EvidenceClaim, normalise_evidence_type
from .tools import ToolResult

FORECAST_LABEL = "Forecast (Phase 10)"

Fetch = Callable[[str, Mapping[str, str]], ToolResult]


class GuidedEvidenceMissing(ValueError):
    """A governed row a guided answer depends on is absent, so the answer cannot be built."""


@dataclass(frozen=True)
class GuidedAnswer:
    """A guided answer before it is wrapped in the response contract."""
    sentences: tuple[str, ...]
    claims: tuple[EvidenceClaim, ...]
    evidence_label: str          # the governed label, as the source states it
    scale_level: str             # the governed scale entry the badge is read from, or FORECAST_LABEL
    reference: str               # where the label comes from, e.g. "Phase 6 evidence matrix, D07"
    cause_status: str
    limitations: tuple[str, ...] = ()
    follow_ups: tuple[str, ...] = ()

    @property
    def answer(self) -> str:
        """The sentences as one paragraph."""
        return " ".join(self.sentences)

    @property
    def governed_label(self) -> str:
        """The published label: one of the four Phase 6 levels, Forecast, or Fact."""
        if self.scale_level == FORECAST_LABEL:
            return "Forecast"
        if self.evidence_label.upper().startswith("FACT"):
            return "Fact"
        return self.scale_level

    @property
    def evidence_strength(self) -> int | None:
        """The governed 0-3 strength for the label; a forecast is not on the scale.

        A fact scores as an observed change, as everywhere else in the grounding rules.
        """
        if self.scale_level == FORECAST_LABEL:
            return None
        return grounding.strength_for_level(self.scale_level)

    def confidence(self) -> tuple[str, str]:
        """Badge and rationale from this driver's own governed label."""
        if self.scale_level == FORECAST_LABEL:
            return "MODERATE", "Forecast evidence only; forecasts are capped at moderate."
        return grounding.confidence_for_level(self.scale_level)

    def executive_summary(self) -> str:
        """The evidence level and cause status, stated where the reader will see them."""
        confidence, rationale = self.confidence()
        return (f"Evidence level: {self.evidence_label} ({self.reference}); "
                f"cause status: {self.cause_status}. Confidence {confidence}: {rationale}")


@dataclass(frozen=True)
class GuidedIntent:
    """A question pattern and the builder that answers it."""
    key: str
    pattern: re.Pattern
    build: Callable[[str, Fetch], GuidedAnswer]


# ------------------------------------------------------------------ formatting and claims

def _tolerance(value: float) -> float:
    # The same tolerance the numeric grounding check applies (grounding._matches_value).
    return max(abs(value) * 0.001, 0.005)


def _rounded(value: float, decimals: tuple[int, ...]) -> float:
    """The coarsest rounding the grounding check still accepts as the governed value."""
    for places in decimals:
        candidate = round(value, places)
        if abs(candidate - value) <= _tolerance(value):
            return candidate
    return round(value, decimals[-1])


def eur(value: float) -> str:
    """EUR 614,363; a negative value keeps its sign."""
    shown = _rounded(value, (0, 1, 2))
    text = f"{abs(shown):,.0f}" if shown == int(shown) else f"{abs(shown):,.2f}"
    return f"{'-' if shown < 0 else ''}EUR {text}"


def pct(value: float) -> str:
    """84.0%, 9.31%, 2.0%: the fewest decimals that still trace to the governed value."""
    shown = _rounded(value, (1, 2, 3))
    places = 1 if round(shown, 1) == shown else (2 if round(shown, 2) == shown else 3)
    return f"{shown:.{places}f}%"


def _number(row: Mapping, field: str) -> float:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise GuidedEvidenceMissing(f"governed field {field!r} is missing or not numeric") from error


def _source_for(result: ToolResult, label: str) -> str:
    """The governed file a labelled block of rows came from (provenance is positional)."""
    labels = list(result.data)
    provenance = list(result.provenance)
    if len(labels) == len(provenance):
        return str(provenance[labels.index(label)]["source_file"])
    return str(provenance[0]["source_file"])


def make_claim(intent: str, result: ToolResult, label: str, row: Mapping, fields: Sequence[str],
               *, index: int, evidence_level: str | None = None,
               as_percent: Sequence[str] = (), magnitude: Sequence[str] = (),
               metric: str | None = None, scope: str = "") -> EvidenceClaim:
    """One claim holding the governed fields a sentence quotes.

    `as_percent` adds a fraction field restated as a percentage, and `magnitude` adds the absolute
    value of a negative figure, so a sentence such as "a EUR 186,146 shortfall" traces to a value
    the claim states. Both are unit restatements of the governed value, labelled as such.
    `scope` keeps evidence ids unique when one tool is called once per entity.
    """
    parts = [f"{name}={row[name]}" for name in fields if str(row.get(name, "")).strip()]
    for name in as_percent:
        parts.append(f"{name} as %={_number(row, name) * 100}")
    for name in magnitude:
        parts.append(f"{name} magnitude={abs(_number(row, name))}")
    level_type = grounding.claim_type_for_level(
        evidence_level, fallback=normalise_evidence_type(result.evidence_type))
    value = _number(row, metric) if metric else None
    return EvidenceClaim(
        evidence_id=f"guided:{intent}:{result.tool}{':' + scope if scope else ''}:{label}:{index}",
        evidence_type=level_type,
        claim=f"{label}: " + "; ".join(parts),
        source_ids=(_source_for(result, label),),
        metric=metric,
        value=value,
        filters={"evidence_level": evidence_level} if evidence_level else {},
    )


def _one(rows: Sequence[Mapping], description: str, **match: str) -> tuple[int, Mapping]:
    """The single governed row matching every field given, with its 1-based position."""
    found = [(index, row) for index, row in enumerate(rows, start=1)
             if all(str(row.get(key)) == value for key, value in match.items())]
    if len(found) != 1:
        raise GuidedEvidenceMissing(f"expected one governed row for {description}, found {len(found)}")
    return found[0]


def _driver(fetch: Fetch, driver_id: str) -> tuple[ToolResult, Mapping]:
    result = fetch("get_evidence_matrix", {"driver_id": driver_id})
    _, row = _one(result.data.get("matrix", []), f"driver {driver_id}", driver_id=driver_id)
    return result, row


def _driver_claim(intent: str, result: ToolResult, row: Mapping, fields: Sequence[str],
                  **kwargs) -> EvidenceClaim:
    """The evidence-matrix claim for a driver, carrying its governed evidence_level label."""
    return make_claim(intent, result, "matrix", row,
                      ("driver_id", "driver", "evidence_level", "cause_status") + tuple(fields),
                      index=1, evidence_level=row["evidence_level"], **kwargs)


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _needs(text: str, count: int = 3) -> str:
    """The first few items of a governed 'additional data required' list, as running text."""
    items = [item.strip() for item in text.split(",") if item.strip()][:count]
    if items and items[0][1:2].islower():  # keep acronyms such as "QA" intact
        items[0] = items[0][:1].lower() + items[0][1:]
    return _join(items)


def _stores_in(text: str) -> list[str]:
    return re.findall(r"\bS\d{2}\b", text)


def _asks(question: str, pattern: str) -> bool:
    return re.search(pattern, question, re.IGNORECASE) is not None


# ------------------------------------------------------------------ builders

_BRIDGE_WORDING = {
    # step name in the governed bridge -> (wording when it reduced revenue, when it added revenue)
    "Transactions effect": ("fewer transactions", "more transactions"),
    "UPT effect": ("fewer units per transaction", "more units per transaction"),
    "ASP effect": ("a lower average selling price", "a higher average selling price"),
    "Returns effect": ("higher returns", "lower returns"),
}


def build_revenue_bridge(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 5 revenue bridge: where the H2 change sits, by component."""
    intent = "revenue_bridge"
    summary = fetch("get_revenue_summary", {})
    bridge = fetch("get_revenue_bridge", {})
    headline = summary.data.get("headline", [])
    claims: list[EvidenceClaim] = []
    figures = {}
    for key, label in (("prior", "Net Revenue H2 2024"), ("current", "Net Revenue H2 2025"),
                       ("change", "Revenue change"), ("yoy", "Net Revenue YoY %")):
        index, row = _one(headline, label, label=label)
        figures[key] = _number(row, "value")
        claims.append(make_claim(intent, summary, "headline", row, ("id", "label", "value", "evidence_tag"),
                                 index=index, metric="value",
                                 as_percent=("value",) if key == "yoy" else (),
                                 magnitude=("value",) if key == "change" else ()))
    effects = []
    for index, row in enumerate(bridge.data.get("bridge", []), start=1):
        if row.get("kind") != "effect":
            continue
        value = _number(row, "value_eur")
        if round(value, 2) == 0:
            continue  # a zero step (e.g. the interaction term) adds nothing to the sentence
        effects.append((row["step"], value, _number(row, "share_of_change")))
        claims.append(make_claim(intent, bridge, "bridge", row,
                                 ("step", "value_eur", "share_of_change", "method_note"),
                                 index=index, metric="value_eur", as_percent=("share_of_change",),
                                 magnitude=("value_eur",) if value < 0 else ()))
    if not effects:
        raise GuidedEvidenceMissing("the revenue bridge has no effect rows")

    def phrase(step: str, value: float, share: float) -> str:
        down, up = _BRIDGE_WORDING.get(step, (step, step))
        return f"{down if value < 0 else up} {eur(abs(value))} ({pct(share * 100)} of the change)"

    change, yoy = figures["change"], figures["yoy"] * 100
    direction, noun = ("fell", "fall") if change < 0 else ("rose", "rise")
    total = (f"Net revenue {direction} from {eur(figures['prior'])} in H2 2024 to "
             f"{eur(figures['current'])} in H2 2025, a {noun} of {eur(abs(change))} ({pct(yoy)}).")
    ordered = sorted(effects, key=lambda item: abs(item[1]), reverse=True)
    split = "The revenue bridge splits the change into " + _join(
        [phrase(*item) for item in ordered]) + "."
    sentences = [total, split]
    transactions = next((item for item in effects if item[0] == "Transactions effect"), None)
    if transactions and _asks(question, r"\btransactions?\b"):
        sentences = [f"Fewer transactions account for {eur(abs(transactions[1]))} of the "
                     f"{eur(abs(change))} fall, {pct(transactions[2] * 100)} of the change.",
                     total, split]
    sentences.append("The bridge is a measured split of the change: it shows where the fall sits, "
                     "not why it happened.")
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label="FACT (measured revenue bridge)", scale_level="Observed change",
        reference="Phase 5 revenue bridge and the Phase 7 number register",
        cause_status="Not applicable (a decomposition, not a cause)",
        follow_ups=("Ask which stores drove the decline, for the largest attributed driver.",),
    )


def build_store_cluster(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 6 driver D01: the S03-S05 store cluster against matched control stores."""
    intent = "store_cluster"
    matrix, d01 = _driver(fetch, "D01")
    cluster = fetch("get_cluster_analysis", {})
    attribution = fetch("get_driver_attribution", {})
    stores = _stores_in(d01["driver"])
    if not stores:
        raise GuidedEvidenceMissing("driver D01 names no stores")
    g_index, group = _one(cluster.data.get("groups", []), "primary control group", primary="True")
    t_index, did_tx = _one(cluster.data.get("did", []), "matched transactions DiD",
                           control_group=group["control_group"], outcome="ly_transactions")
    r_index, did_rev = _one(cluster.data.get("did", []), "matched net revenue DiD",
                            control_group=group["control_group"], outcome="ly_net_revenue")
    _, onset = _one(cluster.data.get("onset", []), "cluster onset")
    a_rows = [(i, row) for i, row in enumerate(attribution.data.get("attribution", []), start=1)
              if row.get("component", "").startswith("Store-cluster")]
    if len(a_rows) != 1:
        raise GuidedEvidenceMissing("expected one store-cluster attribution row")
    a_index, share_row = a_rows[0]
    claims = [
        _driver_claim(intent, matrix, d01, ("observed_effect", "financial_impact_eur", "impact_range",
                                            "what_we_do_not_know"),
                      metric="financial_impact_eur", magnitude=("financial_impact_eur",)),
        make_claim(intent, cluster, "groups", group, ("control_group", "stores", "n_stores", "primary"),
                   index=g_index),
        make_claim(intent, cluster, "did", did_tx, ("control_group", "outcome", "did_pct"), index=t_index,
                   metric="did_pct", magnitude=("did_pct",)),
        make_claim(intent, cluster, "did", did_rev, ("control_group", "outcome", "did_pct", "ratio_did_excess"),
                   index=r_index, metric="did_pct", magnitude=("did_pct",)),
        make_claim(intent, cluster, "onset", onset, ("series", "onset_date", "step_shift_pct", "ramp_days",
                                                     "best_model", "abrupt"),
                   index=1, metric="step_shift_pct"),
        make_claim(intent, attribution, "attribution", share_row, ("component", "amount_eur", "share_of_change"),
                   index=a_index, metric="share_of_change", as_percent=("share_of_change",)),
    ]
    excess = _number(d01, "financial_impact_eur")
    low, high = sorted(abs(float(x.replace(",", ""))) for x in
                       re.findall(r"\d[\d,]*(?:\.\d+)?", d01["impact_range"])[:2])
    which = (f"The decline is concentrated in {len(stores)} stores: {_join(stores)}. Against matched "
             f"control stores ({group['stores']}), their transactions were "
             f"{pct(abs(_number(did_tx, 'did_pct')))} lower and their net revenue "
             f"{pct(abs(_number(did_rev, 'did_pct')))} lower (difference-in-differences).")
    size = (f"That gap is worth {eur(abs(excess))} of net revenue, "
            f"{pct(_number(share_row, 'share_of_change') * 100)} of the total change "
            f"(range {eur(low)} to {eur(high)}).")
    shape = "abrupt step" if onset.get("abrupt") == "True" else onset.get("best_model", "change")
    when = (f"The drop began on {onset['onset_date']} as an {shape} of "
            f"{pct(_number(onset, 'step_shift_pct'))} against the primary control stores, "
            f"not a gradual slide.")
    cause = (f"Evidence level: {d01['evidence_level']} (D01). The cause is "
             f"{d01['cause_status'].lower()}: it is not observable in the project data.")
    sentences = [when, which, size, cause] if _asks(question, r"\bwhen\b|\bstart|\bbegin|\bonset") \
        else [which, size, when, cause]
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label=d01["evidence_level"], scale_level=d01["evidence_level"],
        reference="Phase 6 evidence matrix, D01", cause_status=d01["cause_status"],
        limitations=(d01["what_we_do_not_know"],),
        follow_ups=("Ask what is not known about the decline, for the data needed to explain it.",),
    )


def build_electronics_stockouts(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 6 driver D03: Electronics full-week stock-outs."""
    intent = "electronics_stockouts"
    matrix, d03 = _driver(fetch, "D03")
    matrix4, d04 = _driver(fetch, "D04")
    stockouts = fetch("get_stockout_analysis", {})
    recovery = fetch("get_stockout_net_of_recovery", {})
    s_index, sens = _one(stockouts.data.get("sensitivity", []), "stock-out sensitivity",
                         driver="electronics_stockouts_primary")
    n_index, net = _one(recovery.data.get("net_of_recovery", []), "stock-out loss net of recovery",
                        driver="electronics_stockouts_primary")
    supply = next((part.strip() for part in d04["what_we_do_not_know"].split(".")
                   if "cannot say" in part), "")
    claims = [
        _driver_claim(intent, matrix, d03, ("observed_effect", "financial_impact_eur", "impact_range",
                                            "what_we_do_not_know", "conclusion"),
                      metric="financial_impact_eur", magnitude=("financial_impact_eur",)),
        make_claim(intent, stockouts, "sensitivity", sens, ("driver", "n_variants", "min", "max", "central"),
                   index=s_index, metric="central", magnitude=("min", "max", "central")),
        make_claim(intent, recovery, "net_of_recovery", net, ("driver", "method", "variant", "estimate_eur"),
                   index=n_index, metric="estimate_eur", magnitude=("estimate_eur",)),
        # Context for the open question only; it carries no evidence level, so it cannot move the badge.
        make_claim(intent, matrix4, "matrix", d04, ("driver_id", "driver", "cause_status", "what_we_do_not_know"),
                   index=2),
    ]
    gross = abs(_number(d03, "financial_impact_eur"))
    low, high = sorted((abs(_number(sens, "min")), abs(_number(sens, "max"))))
    sentences = [
        f"Electronics & Tech full-week stock-outs cost an estimated {eur(gross)} in lost sales gross "
        f"(range {eur(low)} to {eur(high)} across {sens['n_variants']} variants).",
        f"Net of the demand that came back after restock, the loss is "
        f"{eur(abs(_number(net, 'estimate_eur')))}.",
        f"Observed: {d03['observed_effect'].rstrip('.')}.",
        "Why the stock ran out (supplier delivery or Brightwater's own ordering) is not established"
        + (f": {supply[:1].lower() + supply[1:]}." if supply else "."),
        f"Evidence level: {d03['evidence_level']} (D03) for the stock-out loss itself; cause "
        f"{d03['cause_status'].lower()}.",
    ]
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label=d03["evidence_level"], scale_level=d03["evidence_level"],
        reference="Phase 6 evidence matrix, D03", cause_status=d03["cause_status"],
        limitations=(d03["what_we_do_not_know"],),
        follow_ups=("Ask which products lost the most to stock-outs.",),
    )


def build_faulty_returns(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 6 driver D05 ('Faulty' returns), with the defect question it leaves open (D06)."""
    intent = "faulty_returns"
    matrix, d05 = _driver(fetch, "D05")
    matrix6, d06 = _driver(fetch, "D06")
    claims = [
        _driver_claim(intent, matrix, d05, ("observed_effect", "financial_impact_eur", "impact_range",
                                            "what_we_do_not_know"),
                      metric="financial_impact_eur", magnitude=("financial_impact_eur",)),
        make_claim(intent, matrix6, "matrix", d06,
                   ("driver_id", "driver", "evidence_level", "cause_status", "additional_data_required"),
                   index=2),
    ]
    sentences = [
        f"Not established. Observed: {d05['observed_effect'].rstrip('.')}.",
        f"What is not known: {d05['what_we_do_not_know'].rstrip('.')}.",
        f"Whether this is a product quality problem or a change in how stores record returns is a "
        f"{d06['evidence_level'].lower()} only (D06); it would need {_needs(d06['additional_data_required'])}.",
        f"Evidence level: {d05['evidence_level']} (D05); cause {d05['cause_status'].lower()}.",
    ]
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label=d05["evidence_level"], scale_level=d05["evidence_level"],
        reference="Phase 6 evidence matrix, D05", cause_status=d05["cause_status"],
        limitations=(d05["what_we_do_not_know"],),
        follow_ups=("Ask what is not known about the decline.",),
    )


# Method code prefix in the governed counterfactual table, and a plain name for it.
_HK_METHODS: tuple[tuple[str, str], ...] = (
    ("M1 ", "category difference-in-differences"),
    ("M4 ", "discount-rate accounting"),
    ("M2 ", "dose-response"),
    ("M3 ", "event-level"),
)


def build_hk_promotions(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 6 driver D07: Home & Kitchen promotions."""
    intent = "hk_promotions"
    matrix, d07 = _driver(fetch, "D07")
    promotions = fetch("get_promotion_analysis", {})
    rows = promotions.data.get("counterfactuals", [])
    # The four revenue methods, shown side by side; none is presented as the main one. The two
    # extra M1 rows are gross-margin variants of M1, not separate methods.
    methods = []
    for prefix, name in _HK_METHODS:
        index, row = _one(rows, f"{prefix} revenue estimate", method=next(
            (r["method"] for r in rows if r.get("method", "").startswith(prefix)
             and "gross margin" not in r.get("method", "")), ""))
        methods.append((index, row, name))
    claims = [
        _driver_claim(intent, matrix, d07, ("observed_effect", "financial_impact_eur", "impact_range",
                                            "what_we_do_not_know"),
                      metric="financial_impact_eur"),
    ] + [make_claim(intent, promotions, "counterfactuals", row, ("method", "effect_eur"), index=index,
                    metric="effect_eur") for index, row, _ in methods]

    def signed(value: float) -> str:
        return eur(value) if value < 0 else "+" + eur(value)

    listed = "; ".join(f"{row['method'].split()[0]} {name} {signed(_number(row, 'effect_eur'))}"
                       for _, row, name in methods)
    signs = {_number(row, "effect_eur") < 0 for _, row, _ in methods}
    sentences = [
        "Not established: the data shows a statistical association, not a proven cause.",
        f"Observed: {d07['observed_effect'].rstrip('.')}.",
        f"{len(methods)} methods estimate the H&K effect: {listed}.",
        ("The methods disagree in sign, so the effect depends on the method; they are alternative "
         "estimates and are never added together." if len(signs) > 1 else
         "The methods are alternative estimates and are never added together."),
        f"Evidence level: {d07['evidence_level']} (D07); cause {d07['cause_status'].lower()}.",
    ]
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label=d07["evidence_level"], scale_level=d07["evidence_level"],
        reference="Phase 6 evidence matrix, D07", cause_status=d07["cause_status"],
        limitations=(d07["what_we_do_not_know"],),
        follow_ups=("A controlled test (holdout stores) would be needed to settle the effect.",),
    )


def build_forecast(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 10 forecast: the selected model, its 13 weeks, intervals and backtest accuracy."""
    intent = "forecast"
    forecast = fetch("get_forecast", {})
    intervals = fetch("get_forecast_intervals", {})
    comparison = fetch("get_forecast_model_comparison", {})
    selected = {row["field"]: row["value"] for row in forecast.data.get("selected_model", [])}
    model = selected.get("selected_model")
    weeks = [row for row in forecast.data.get("weekly_forecast", []) if row.get("model") == model]
    if not model or not weeks:
        raise GuidedEvidenceMissing("the selected forecast model or its weekly values are missing")
    claims: list[EvidenceClaim] = []
    for field in ("selected_model", "selected_family", "selection_metric", "best_baseline_metric",
                  "best_challenger", "best_challenger_metric", "promoted_challenger", "rule"):
        index, row = _one(forecast.data["selected_model"], field, field=field)
        numeric = field in {"best_baseline_metric", "best_challenger_metric"}
        claims.append(make_claim(intent, forecast, "selected_model", row, ("field", "value"), index=index,
                                 as_percent=("value",) if numeric else ()))
    first, last = weeks[0], weeks[-1]
    high = max(weeks, key=lambda row: _number(row, "point_forecast"))
    low = min(weeks, key=lambda row: _number(row, "point_forecast"))
    picked = {id(row): row for row in (first, last, high, low)}
    for row in picked.values():
        claims.append(make_claim(intent, forecast, "weekly_forecast", row,
                                 ("horizon_step", "week_start_date", "model", "point_forecast"),
                                 index=weeks.index(row) + 1, metric="point_forecast"))
    bands = {}
    for coverage in ("0.8", "0.95"):
        index, row = _one(intervals.data.get("intervals", []), f"{coverage} interval, first week",
                          week_start_date=first["week_start_date"], model=model, coverage=coverage)
        bands[coverage] = row
        claims.append(make_claim(intent, intervals, "intervals", row,
                                 ("week_start_date", "model", "coverage", "lower", "upper"), index=index,
                                 as_percent=("coverage",)))
    c_index, best = _one(comparison.data.get("comparison", []), "selected model comparison", model=model)
    claims.append(make_claim(intent, comparison, "comparison", best, ("model", "family", "mean_wape"),
                             index=c_index, metric="mean_wape", as_percent=("mean_wape",)))
    claims.append(EvidenceClaim(
        evidence_id=f"guided:{intent}:limitation", evidence_type="LIMITATION",
        claim=grounding.FORECAST_NOTE,
        source_ids=tuple(sorted({claim.source_ids[0] for claim in claims}))))

    wape = pct(_number(best, "mean_wape") * 100)
    band80, band95 = bands["0.8"], bands["0.95"]
    outlook = (f"The selected model, {model} (a {selected.get('selected_family', 'governed')} model), "
               f"forecasts weekly net revenue for the {len(weeks)} weeks starting {first['week_start_date']}. "
               f"The first week is forecast at {eur(_number(first, 'point_forecast'))} "
               f"(80% interval {eur(_number(band80, 'lower'))} to {eur(_number(band80, 'upper'))}; "
               f"95% interval {eur(_number(band95, 'lower'))} to {eur(_number(band95, 'upper'))}).")
    span = (f"Weekly values range from {eur(_number(low, 'point_forecast'))} (week starting "
            f"{low['week_start_date']}) to {eur(_number(high, 'point_forecast'))} (week starting "
            f"{high['week_start_date']}); the last week, starting {last['week_start_date']}, is "
            f"{eur(_number(last, 'point_forecast'))}.")
    choice = (f"{model} was selected because it had the lowest backtest error: mean "
              f"{selected.get('selection_metric', 'error').upper()} {wape}, against "
              f"{pct(float(selected['best_challenger_metric']) * 100)} for the best challenger "
              f"({selected.get('best_challenger')}). A challenger replaces the baseline only when it beats "
              f"it by more than the set margin.")
    note = "These are forecasts, not actual results."
    if _asks(question, r"\bmodel\b|\bselected\b|\baccura|\bwhy\b|\bwape\b"):
        sentences = [choice, outlook, note]
    else:
        sentences = [outlook, span, f"Backtest accuracy: mean WAPE {wape}.", note]
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label=FORECAST_LABEL, scale_level=FORECAST_LABEL,
        reference="Phase 10 selected model and forecast", cause_status="Not applicable (forecast)",
        limitations=(grounding.FORECAST_NOTE,),
        follow_ups=("Ask how much the forecast interval widens over the 13-week horizon.",),
    )


_SEVERITY_ORDER = ("WATCH", "WARNING", "CRITICAL")


def build_early_warning(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 9 store alerts (EW01) for the D01 cluster stores, against the governed onset."""
    intent = "early_warning"
    matrix, d01 = _driver(fetch, "D01")
    cluster = fetch("get_cluster_analysis", {})
    signals = fetch("get_monitoring_signals", {})
    _, onset = _one(cluster.data.get("onset", []), "cluster onset")
    s_index, summary = _one(signals.data.get("summary", []), "EW01 store summary",
                            signal="EW01", entity_type="store")
    claims = [
        make_claim(intent, matrix, "matrix", d01, ("driver_id", "driver", "observed_effect"), index=1),
        make_claim(intent, cluster, "onset", onset, ("series", "onset_date"), index=1),
        make_claim(intent, signals, "summary", summary,
                   ("signal", "entity_type", "rule", "watch", "warning", "critical",
                    "alert_episodes", "entities_alerted"), index=s_index),
    ]
    stores = _stores_in(d01["driver"])
    firsts: dict[str, dict[str, Mapping]] = {}
    labels: set[str] = set()
    for store in stores:
        alerts = fetch("get_store_alerts", {"store_id": store})
        rows = sorted(((i, row) for i, row in enumerate(alerts.data.get("alerts", []), start=1)
                       if row.get("signal") == "EW01" and row.get("retail_week", "").startswith(
                           onset["onset_date"][:4])),
                      key=lambda item: item[1]["retail_week_key"])
        firsts[store] = {}
        for severity in ("WATCH", "CRITICAL"):
            hit = next(((i, row) for i, row in rows if row.get("severity") == severity), None)
            if hit is None:
                continue
            i, row = hit
            firsts[store][severity] = row
            labels.add(row["evidence_level"])
            claims.append(make_claim(intent, alerts, "alerts", row,
                                     ("alert_id", "alert_date", "signal", "entity_id", "retail_week",
                                      "severity", "evidence_level", "cause_status"),
                                     index=i, evidence_level=row["evidence_level"].split(" (")[0],
                                     scope=store))
    if not any(firsts.values()) or len(labels) != 1:
        raise GuidedEvidenceMissing("the cluster stores have no single-labelled EW01 alerts")
    label = labels.pop()
    critical = [(store, first["CRITICAL"]["retail_week"]) for store, first in firsts.items()
                if "CRITICAL" in first]
    watch = [(store, first["WATCH"]["retail_week"]) for store, first in firsts.items() if "WATCH" in first]
    by_week: dict[str, list[str]] = {}
    for store, week in critical:
        by_week.setdefault(week, []).append(store)
    critical_text = "; ".join(f"{_join(names)} in {week}" for week, names in sorted(by_week.items()))
    # ISO dates compare correctly as text.
    after = [first["CRITICAL"]["alert_date"] > onset["onset_date"] for first in firsts.values()
             if "CRITICAL" in first]
    timing = ("so every critical alert came after it, not before" if after and all(after) else
              "so at least one critical alert came before it" if any(not flag for flag in after) else
              "and none of these stores reached a critical alert")
    sentences = [
        f"The store signal (EW01, {summary['rule'].split(':')[0].replace('_', ' ')}) raised its first "
        f"critical alerts for the cluster stores in {onset['onset_date'][:4]} as follows: {critical_text}.",
        f"The governed step change in these stores is dated {onset['onset_date']}, {timing}.",
        f"Earlier watch-level alerts were raised ("
        + _join([f"{store} from {week}" for store, week in sorted(watch, key=lambda item: item[1])])
        + f"), but watch alerts are common: across {summary['entities_alerted']} stores EW01 raised "
        f"{summary['watch']} watch, {summary['warning']} warning and {summary['critical']} critical "
        f"store-weeks.",
        "An alert flags a change; it does not explain it.",
    ]
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label=label, scale_level=label.split(" (")[0],
        reference="Phase 9 alert log, EW01", cause_status="Not established",
        limitations=("Whether an earlier alert would have changed the outcome is not something the "
                     "governed data can show.",),
        follow_ups=("Ask when the store drop started.",),
    )


def build_data_quality(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 3 load-time data quality, then the Phase 9 monitoring checks and gate (EW08)."""
    intent = "data_quality"
    load = fetch("get_load_data_quality", {})
    signals = fetch("get_monitoring_signals", {})
    checks = signals.data.get("data_quality", [])
    if not checks:
        raise GuidedEvidenceMissing("the data-quality check catalogue is empty")

    # Phase 3: the run lineage holds the governed totals; the rule and validation tables must agree
    # with it, or the answer is not built.
    lineage = {row["field"]: row["value"] for row in load.data.get("lineage", [])}
    rules = load.data.get("rule_results", [])
    validation = load.data.get("curated_validation", [])
    by_status: dict[str, int] = {}
    for row in rules:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    v_status: dict[str, int] = {}
    for row in validation:
        v_status[row["status"]] = v_status.get(row["status"], 0) + 1
    quarantine = {key.split(":", 1)[1]: int(value) for key, value in lineage.items()
                  if key.startswith("quarantine_rows:")}
    if (str(len(rules)) != lineage.get("rules_evaluated")
            or str(by_status.get("FAIL", 0)) != lineage.get("rules_failed")
            or any(str(count) != lineage.get(f"validation_{status}") for status, count in v_status.items())
            or not quarantine):
        raise GuidedEvidenceMissing("the Phase 3 rule and validation tables disagree with the run lineage")
    claims = [make_claim(intent, load, "lineage", row, ("field", "value"), index=i)
              for i, row in enumerate(load.data["lineage"], start=1)]
    claims.append(EvidenceClaim(
        evidence_id=f"guided:{intent}:get_load_data_quality:rule_results:status_counts",
        evidence_type="FACT",
        claim="rule_results: rows by status " + "; ".join(
            f"{status}={count}" for status, count in sorted(by_status.items())) + f" ({len(rules)} rules)",
        source_ids=(_source_for(load, "rule_results"),)))
    claims.append(EvidenceClaim(
        evidence_id=f"guided:{intent}:get_load_data_quality:curated_validation:status_counts",
        evidence_type="FACT",
        claim="curated_validation: checks by status " + "; ".join(
            f"{status}={count}" for status, count in sorted(v_status.items())) + f" ({len(validation)} checks)",
        source_ids=(_source_for(load, "curated_validation"),)))
    claims += [make_claim(intent, signals, "data_quality", row,
                          ("check_id", "severity", "check", "blocks_business_alerts"), index=i)
               for i, row in enumerate(checks, start=1)]
    gate = [(i, row) for i, row in enumerate(signals.data.get("summary", []), start=1)
            if row.get("signal") == "EW08"]
    labels = {row["evidence_level"] for row in signals.data.get("alerts", []) if row.get("signal") == "EW08"}
    if len(gate) != 1 or len(labels) != 1:
        raise GuidedEvidenceMissing("expected one EW08 summary row with one governed label")
    g_index, gate_row = gate[0]
    label = labels.pop()
    claims.append(make_claim(intent, signals, "summary", gate_row,
                             ("signal", "entity_type", "rule", "watch", "warning", "critical"),
                             index=g_index, evidence_level="Observed change"))
    blocking = [row["check_id"] for row in checks if row.get("blocks_business_alerts") == "True"]
    largest = sorted(quarantine.items(), key=lambda item: item[1], reverse=True)
    status_words = {"PASS": "passed", "FAIL": "found issues", "INFO": "were informational"}
    sentences = [
        f"At load (Phase 3), {lineage['rules_evaluated']} data-quality rules were evaluated: "
        + _join([f"{by_status[status]} {status_words.get(status, status.lower())}"
                 for status in ("PASS", "FAIL", "INFO") if status in by_status]) + ".",
        f"{sum(quarantine.values()):,} rows were quarantined in total ("
        + ", ".join(f"{table} {count:,}" for table, count in largest) + ").",
        f"The curated tables then passed {v_status.get('PASS', 0)} of {len(validation)} validation checks"
        + (f", with {v_status['WARN']} warnings." if v_status.get("WARN") else "."),
        f"In monitoring (Phase 9), {len(checks)} checks ({checks[0]['check_id']} to {checks[-1]['check_id']}) "
        f"run before alerts are issued; {len(blocking)} of them ({_join(blocking)}) hold back business "
        f"alerts when they fail, and the data-quality gate ({gate_row['signal']}) flagged "
        f"{gate_row['warning']} warning and {gate_row['critical']} critical store-weeks.",
    ]
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label=label, scale_level="Observed change",
        reference="Phase 3 rule results, validation and lineage; Phase 9 checks and EW08",
        cause_status="Not applicable (data check)",
        limitations=("The quarantine total is the sum of the six per-table counts in the Phase 3 run lineage.",),
        follow_ups=("Ask what early warning signals fired.",),
    )


def build_unknowns(question: str, fetch: Fetch) -> GuidedAnswer:
    """Phase 6 evidence matrix: the hypothesis-level drivers and the open causes."""
    intent = "unknowns"
    matrix = fetch("get_evidence_matrix", {})
    rows = list(enumerate(matrix.data.get("matrix", []), start=1))
    hypotheses = [(i, row) for i, row in rows if row.get("evidence_level") == "Hypothesis"]
    open_causes = [(i, row) for i, row in rows
                   if row.get("evidence_level") != "Hypothesis"
                   and row.get("cause_status") in {"Not established", "Unresolved"}]
    if not hypotheses:
        raise GuidedEvidenceMissing("the evidence matrix has no hypothesis-level drivers")
    claims = [make_claim(intent, matrix, "matrix", row,
                         ("driver_id", "driver", "evidence_level", "cause_status", "additional_data_required"),
                         index=i, evidence_level=row["evidence_level"]) for i, row in hypotheses]
    claims += [make_claim(intent, matrix, "matrix", row, ("driver_id", "driver", "cause_status"), index=i)
               for i, row in open_causes]
    sentences = [f"{len(hypotheses)} drivers are still only hypotheses with no direct evidence: "
                 + _join([f"{row['driver_id']} ({row['driver']})" for _, row in hypotheses]) + "."]
    for _, row in hypotheses:
        sentences.append(f"{row['driver_id']} would need {_needs(row['additional_data_required'])}.")
    if open_causes:
        sentences.append("For " + _join([row["driver_id"] for _, row in open_causes])
                         + " the change is measured but its cause is not established.")
    ids = ", ".join(row["driver_id"] for _, row in hypotheses)
    return GuidedAnswer(
        sentences=tuple(sentences), claims=tuple(claims),
        evidence_label="Hypothesis", scale_level="Hypothesis",
        reference=f"Phase 6 evidence matrix, {ids}", cause_status="Unresolved",
        follow_ups=("Open the priority 1 investigation items for the hypothesis-level drivers.",),
    )


# Narrow on purpose: a guided pattern must not capture a question the general path already answers
# well (the Phase 11 evaluation suite). Order matters; the first match wins.
GUIDED_INTENTS: tuple[GuidedIntent, ...] = tuple(
    GuidedIntent(key, re.compile(pattern, re.IGNORECASE), build) for key, pattern, build in (
        ("forecast", r"\bforecast", build_forecast),
        ("early_warning", r"\bearly[- ]warning\b|\bsignals? (fired|triggered)\b|\bcaught\b.*\b(earlier|sooner)\b",
         build_early_warning),
        ("data_quality", r"\bdata[- ]quality\b", build_data_quality),
        ("faulty_returns", r"\bfaulty\b", build_faulty_returns),
        ("hk_promotions", r"\bhome (&|and) kitchen\b.*\bpromotion|\bpromotions?\b.*\b(home (&|and) kitchen|h&k)\b",
         build_hk_promotions),
        ("electronics_stockouts", r"\belectronics\b.*\bstock[- ]?outs?\b|\bstock[- ]?outs?\b.*\bcost\b",
         build_electronics_stockouts),
        ("store_cluster", r"\bstore cluster\b|\bwhich stores?\b.*\b(drove|drive|driving|behind|declin|fall|fell|drop)"
         r"|\bwhen did\b.*\b(store|drop|declin|fall)", build_store_cluster),
        ("revenue_bridge", r"\bwhy did (net )?revenue (fall|fell|declin|drop)|\b(net )?revenue (fall|fell|declin|drop)"
         r".*\bH2\b|\bfewer transactions\b|\bdecline came from\b", build_revenue_bridge),
        ("unknowns", r"\bnot known\b|\bunknowns?\b|\bunresolved\b|\bstill (unknown|unexplained)\b", build_unknowns),
    ))


def guided_intent_for(question: str) -> GuidedIntent | None:
    """The guided intent a question asks for, or None to use the general path."""
    if not isinstance(question, str):
        return None
    return next((intent for intent in GUIDED_INTENTS if intent.pattern.search(question)), None)
