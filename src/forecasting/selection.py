"""Baseline comparison and the selected-model rule.

The rule is deliberately blunt and stated up front, because a forecasting phase that picks a
winner after seeing the back-test is not a back-test:

  1. A model is eligible only if it produced a result at every rolling origin.
  2. The best baseline is the eligible baseline with the lowest mean of the selection metric.
  3. The challenger replaces it only if its mean metric beats the best baseline's by more than the
     configured margin. A challenger that merely ties does not get the promotion.
  4. Ties, inside or across groups, break on the configured tie-breakers, then on registry order,
     so the outcome never depends on dictionary or file ordering.
"""
from __future__ import annotations

from dataclasses import dataclass

METRICS = ("mae", "rmse", "wape", "mase", "bias")


@dataclass(frozen=True)
class ModelSummary:
    """A model's mean back-test metrics and the number of origins it completed."""
    model: str
    family: str
    origins: int
    mean_metrics: dict[str, float]

    def metric(self, name: str) -> float:
        """Mean value of the named metric."""
        return float(self.mean_metrics[name])


def model_family(name: str) -> str:
    """Registry names B1 to B4 are baselines; anything else is a challenger."""
    return "baseline" if name.startswith("B") else "challenger"


def summarise(backtest_rows: list[dict], registry_order: list[str]) -> list[ModelSummary]:
    """Mean of every metric over the origins each model actually completed."""
    rank = {name: index for index, name in enumerate(registry_order)}
    grouped: dict[str, list[dict]] = {}
    for row in backtest_rows:
        grouped.setdefault(row["model"], []).append(row)
    summaries = []
    for name in sorted(grouped, key=lambda key: rank.get(key, len(rank))):
        rows = grouped[name]
        summaries.append(
            ModelSummary(
                model=name,
                family=model_family(name),
                origins=len(rows),
                mean_metrics={metric: sum(float(row[metric]) for row in rows) / len(rows) for metric in METRICS},
            )
        )
    return summaries


def _ordered(summaries: list[ModelSummary], rank: dict[str, int], selection: dict) -> list[ModelSummary]:
    primary = selection["metric"]
    tie_breakers = selection.get("tie_breakers", [])
    return sorted(
        summaries,
        key=lambda item: (item.metric(primary),)
        + tuple(item.metric(name) for name in tie_breakers)
        + (rank.get(item.model, len(rank)),),
    )


def select_model(summaries: list[ModelSummary], registry_order: list[str], selection: dict,
                 expected_origins: int | None = None) -> dict:
    """Apply the rule and return the decision with its evidence, ready to be written out."""
    rank = {name: index for index, name in enumerate(registry_order)}
    if not summaries:
        raise ValueError("No back-test results to select from")
    if expected_origins is None:
        expected_origins = max(item.origins for item in summaries)
    if selection.get("require_all_origins", True) and any(item.origins != expected_origins
                                                          for item in summaries):
        raise ValueError(
            f"Model selection requires every model at every rolling origin; expected {expected_origins}"
        )

    ordered = _ordered(summaries, rank, selection)
    best_baseline = next((item for item in ordered if item.family == "baseline"), None)
    best_challenger = next((item for item in ordered if item.family == "challenger"), None)
    if best_baseline is None or best_challenger is None:
        raise ValueError("Selection needs at least one baseline and one challenger")

    metric = selection["metric"]
    margin = float(selection.get("challenger_margin", 0.0))
    improvement = best_baseline.metric(metric) - best_challenger.metric(metric)
    promoted = improvement > margin
    winner = best_challenger if promoted else best_baseline

    return {
        "selected_model": winner.model,
        "selected_family": winner.family,
        "selection_metric": metric,
        "challenger_margin": margin,
        "best_baseline": best_baseline.model,
        "best_baseline_metric": best_baseline.metric(metric),
        "best_challenger": best_challenger.model,
        "best_challenger_metric": best_challenger.metric(metric),
        "improvement": improvement,
        "promoted_challenger": promoted,
        "rule": "challenger promoted only when its mean metric beats the best baseline by more than "
                "the margin; ties break on the configured tie-breakers, then on registry order",
    }
