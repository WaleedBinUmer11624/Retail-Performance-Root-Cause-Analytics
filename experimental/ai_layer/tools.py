"""Deterministic Phase 5-10 evidence tools.

Input: a tool name and allowlisted scalar arguments. Output: a ToolResult holding governed rows
and the provenance of every file read. Tools never accept a path or SQL text.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable

from .analyst_context import GuardedAnalystContext
from .artifacts import ArtifactError, ArtifactResolver, ArtifactTable
from .provenance import SourceProvenance


class ToolError(ValueError):
    """Raised when a tool name or argument is not supported."""


@dataclass(frozen=True)
class ToolResult:
    """Output of one tool call: data, provenance and evidence type."""
    tool: str
    data: dict
    provenance: tuple[dict, ...]
    evidence_type: str = "FACT"

    def to_dict(self) -> dict:
        """JSON-ready copy."""
        return {"tool": self.tool, "data": self.data, "provenance": list(self.provenance),
                "evidence_type": self.evidence_type}


class ToolRegistry:
    """Closed registry. No tool accepts a filesystem path or arbitrary SQL."""

    def __init__(self, resolver: ArtifactResolver, analyst: GuardedAnalystContext | None = None):
        self.resolver = resolver
        self.analyst = analyst
        self._tools: dict[str, tuple[Callable[[dict], ToolResult], set[str]]] = {
            "get_revenue_summary": (self._revenue_summary, set()),
            "get_revenue_bridge": (self._revenue_bridge, set()),
            "get_driver_attribution": (self._driver_attribution, set()),
            "get_evidence_matrix": (self._evidence_matrix, {"driver_id"}),
            "get_cluster_analysis": (self._cluster_analysis, set()),
            "get_store_performance": (self._store_performance, {"store_id", "from_week_key", "to_week_key"}),
            "get_product_performance": (self._product_performance, {"product_id"}),
            "get_stockout_analysis": (self._stockout_analysis, set()),
            "get_returns_analysis": (self._returns_analysis, set()),
            "get_supplier_analysis": (self._supplier_analysis, set()),
            "get_promotion_analysis": (self._promotion_analysis, set()),
            "get_investigation_evidence": (self._investigation_evidence, set()),
            "get_forecast": (self._forecast, set()),
            "get_forecast_intervals": (self._forecast_intervals, set()),
            "get_forecast_model_comparison": (self._forecast_comparison, set()),
            "get_monitoring_signals": (self._monitoring_signals, set()),
            "get_store_alerts": (self._store_alerts, {"store_id"}),
            "get_stockout_net_of_recovery": (self._stockout_net_of_recovery, set()),
            "get_load_data_quality": (self._load_data_quality, set()),
            "get_metric_definition": (self._metric_definition, {"measure"}),
        }

    @property
    def names(self) -> tuple[str, ...]:
        """Registered tool names, sorted."""
        return tuple(sorted(self._tools))

    def allowed_arguments(self, name: str) -> frozenset[str]:
        """Argument names a tool accepts, so callers can validate before dispatch."""
        if name not in self._tools:
            raise ToolError("Unknown evidence tool")
        return frozenset(self._tools[name][1])

    def run(self, name: str, arguments: dict | None = None) -> ToolResult:
        """Dispatch a registered tool after rejecting any argument it does not declare."""
        if name not in self._tools:
            raise ToolError("Unknown evidence tool")
        args = dict(arguments or {})
        function, allowed = self._tools[name]
        unknown = set(args) - allowed
        if unknown:
            raise ToolError("Tool received unsupported arguments")
        return function(args)

    def _table(self, key: str, filters: dict | None = None, limit: int = 500) -> ArtifactTable:
        return self.resolver.read_csv_artifact(key, filters=filters, limit=limit)

    def _bundle(self, tool: str, keys: dict[str, str], filters: dict | None = None,
                limit: int = 500, evidence_type: str = "FACT") -> ToolResult:
        """Read several governed tables as one result. A filter applies to every table it is given.

        A bundled tool reports one entity, so the filter that identifies it must reach all of its
        tables; a table without that column is a schema error rather than a silently unfiltered
        result.
        """
        data: dict[str, list[dict[str, str]]] = {}
        provenance: list[dict] = []
        for label, artifact_key in keys.items():
            table = self._table(artifact_key, filters=filters, limit=limit)
            data[label] = [dict(row) for row in table.rows]
            provenance.append(table.provenance.to_dict())
        return ToolResult(tool, data, tuple(provenance), evidence_type)

    def _revenue_summary(self, _: dict) -> ToolResult:
        return self._bundle("get_revenue_summary", {"headline": "phase6.headline"},
                            filters={"page": "1 Executive overview"}, limit=100)

    def _revenue_bridge(self, _: dict) -> ToolResult:
        return self._bundle("get_revenue_bridge", {"bridge": "phase5.revenue_bridge"}, limit=100)

    def _driver_attribution(self, _: dict) -> ToolResult:
        return self._bundle("get_driver_attribution", {"attribution": "phase6.attribution"}, limit=100,
                            evidence_type="ATTRIBUTION")

    def _evidence_matrix(self, args: dict) -> ToolResult:
        filters = {"driver_id": args["driver_id"]} if "driver_id" in args else None
        if filters and (not isinstance(filters["driver_id"], str) or not re.fullmatch(r"D\d{2}", filters["driver_id"])):
            raise ToolError("driver_id must use the governed D01-D99 form")
        return self._bundle("get_evidence_matrix", {"matrix": "phase6.evidence_matrix"}, filters=filters,
                            limit=100, evidence_type="INTERPRETATION")

    def _cluster_analysis(self, _: dict) -> ToolResult:
        return self._bundle("get_cluster_analysis", {
            "groups": "phase6.cluster_groups", "did": "phase6.cluster_did", "onset": "phase6.cluster_onset",
        }, limit=500, evidence_type="ATTRIBUTION")

    def _store_performance(self, args: dict) -> ToolResult:
        store_id = args.get("store_id")
        if not isinstance(store_id, str) or not re.fullmatch(r"S\d{2}", store_id):
            raise ToolError("store_id must be a governed S01-S99 identifier")
        if self.analyst is not None and self.analyst.sql_available:
            return self._store_performance_from_sql(args, store_id)
        # No read-only SQL engine is connected, so the governed store-level Phase 6 tables are the
        # evidence. They carry the same frozen store analysis the query template would return.
        result = self._bundle("get_store_performance", {
            "returns": "phase6.faulty_returns_by_store",
            "lost_sales": "phase6.store_lost_sales",
            "onset": "phase6.store_onset",
        }, filters={"store_id": store_id}, limit=50)
        if not any(rows for rows in result.data.values()):
            raise ToolError("store_id is not present in the governed store tables")
        return result

    def _store_performance_from_sql(self, args: dict, store_id: str) -> ToolResult:
        start = args.get("from_week_key")
        end = args.get("to_week_key")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end)):
            raise ToolError("week keys must be integers")
        if start > end or end - start > 200:
            raise ToolError("week window must be ordered and at most 200 key units")
        if store_id not in self.analyst.dimensions["stores"]:
            raise ToolError("store_id is not present in the governed store dimension")
        frame = self.analyst.query("week_store_kpi", {"store_id": store_id,
                                                      "from_week_key": start,
                                                      "to_week_key": end})
        records = frame.to_dict(orient="records")
        raw = json.dumps(records, sort_keys=True, default=str).encode("utf-8")
        provenance = SourceProvenance(
            source_file="query_template:week_store_kpi", phase="SQL", retrieval_method="registered_select_template",
            content_sha256=hashlib.sha256(raw).hexdigest(), filters={
                "store_id": store_id, "from_week_key": str(start), "to_week_key": str(end),
            }, record_count=len(records),
        )
        return ToolResult("get_store_performance", {"weekly_kpis": records},
                          (provenance.to_dict(),), "FACT")

    def _product_performance(self, args: dict) -> ToolResult:
        product_id = args.get("product_id")
        if not isinstance(product_id, str) or not re.fullmatch(r"P\d{5}", product_id):
            raise ToolError("product_id must use the governed P00000 identifier form")
        return self._bundle("get_product_performance", {"stockout_skus": "phase6.electronics_stockouts"},
                            filters={"product_id": product_id}, limit=50)

    def _stockout_analysis(self, _: dict) -> ToolResult:
        return self._bundle("get_stockout_analysis", {
            "kpis": "phase6.electronics_kpis", "sku_stockouts": "phase6.electronics_stockouts",
            "episodes": "phase6.electronics_episodes", "supplier_test": "phase6.electronics_supplier_test",
            "sensitivity": "phase6.sensitivity",
        }, limit=500, evidence_type="ESTIMATE")

    def _returns_analysis(self, _: dict) -> ToolResult:
        return self._bundle("get_returns_analysis", {
            "by_store": "phase6.faulty_returns_by_store", "by_product": "phase6.faulty_returns_by_product",
            "by_supplier": "phase6.faulty_returns_by_supplier",
        }, limit=500, evidence_type="ASSOCIATION")

    def _supplier_analysis(self, _: dict) -> ToolResult:
        return self._bundle("get_supplier_analysis", {
            "comparison": "phase6.electronics_supplier_comparison", "test": "phase6.electronics_supplier_test",
            "stockouts": "phase6.electronics_stockouts",
        }, limit=500, evidence_type="ASSOCIATION")

    def _promotion_analysis(self, _: dict) -> ToolResult:
        return self._bundle("get_promotion_analysis", {
            "counterfactuals": "phase6.promotion_counterfactuals", "weekly": "phase6.promotion_weekly",
            "events_by_year": "phase6.promotion_events",
        }, limit=500, evidence_type="ASSOCIATION")

    def _investigation_evidence(self, _: dict) -> ToolResult:
        return self._bundle("get_investigation_evidence", {"actions": "phase8.action_register",
                                                             "matrix": "phase6.evidence_matrix"},
                            limit=500, evidence_type="INTERPRETATION")

    def _forecast(self, _: dict) -> ToolResult:
        return self._bundle("get_forecast", {
            "selected_model": "phase10.selected_model", "weekly_forecast": "phase10.forecast",
        }, limit=100, evidence_type="FORECAST")

    def _forecast_intervals(self, _: dict) -> ToolResult:
        return self._bundle("get_forecast_intervals", {"intervals": "phase10.intervals"}, limit=100,
                            evidence_type="FORECAST")

    def _forecast_comparison(self, _: dict) -> ToolResult:
        return self._bundle("get_forecast_model_comparison", {
            "comparison": "phase10.comparison", "backtest": "phase10.backtest",
            "selected_model": "phase10.selected_model",
        }, limit=500, evidence_type="FORECAST")

    def _monitoring_signals(self, _: dict) -> ToolResult:
        return self._bundle("get_monitoring_signals", {
            "alerts": "phase9.alerts", "summary": "phase9.alert_summary", "data_quality": "phase9.data_quality",
        }, limit=500, evidence_type="FACT")

    def _store_alerts(self, args: dict) -> ToolResult:
        # get_monitoring_signals caps the alert log at its first 500 rows, which stops before the
        # second-half alerts. Filtering on one store reads that store's full alert history.
        store_id = args.get("store_id")
        if not isinstance(store_id, str) or not re.fullmatch(r"S\d{2}", store_id):
            raise ToolError("store_id must be a governed S01-S99 identifier")
        return self._bundle("get_store_alerts", {"alerts": "phase9.alerts"},
                            filters={"entity_type": "store", "entity_id": store_id}, limit=500)

    def _stockout_net_of_recovery(self, _: dict) -> ToolResult:
        return self._bundle("get_stockout_net_of_recovery",
                            {"net_of_recovery": "phase6.stockout_net_of_recovery"},
                            limit=50, evidence_type="ESTIMATE")

    def _load_data_quality(self, _: dict) -> ToolResult:
        """Phase 3 load-time data quality: rule results, curated validation and the run lineage.

        The lineage is a JSON run record, so its governed counts are flattened into field/value
        rows; nothing is recomputed.
        """
        result = self._bundle("get_load_data_quality", {
            "rule_results": "phase3.dq_rule_results", "curated_validation": "phase3.curated_validation",
        }, limit=500)
        document, provenance = self.resolver.read_json_artifact("phase3.lineage")
        if not isinstance(document, dict):
            raise ToolError("The Phase 3 lineage is not a JSON object")
        rows = [{"field": key, "value": str(document[key])}
                for key in ("rules_evaluated", "rules_failed") if key in document]
        rows += [{"field": f"validation_{status}", "value": str(count)}
                 for status, count in (document.get("validation") or {}).items()]
        rows += [{"field": f"quarantine_rows:{table}", "value": str(count)}
                 for table, count in (document.get("quarantine_rows") or {}).items()]
        data = dict(result.data, lineage=rows)
        return ToolResult("get_load_data_quality", data,
                          result.provenance + (provenance.to_dict(),), "FACT")

    def _metric_definition(self, args: dict) -> ToolResult:
        measure = args.get("measure")
        if not isinstance(measure, str) or not measure.strip() or len(measure) > 120:
            raise ToolError("measure must be a non-empty name of at most 120 characters")
        table = self._table("phase7.measure_dictionary", filters={"measure": measure.strip()}, limit=2)
        if len(table.rows) != 1:
            raise ToolError("Measure name is unknown or ambiguous in the governed dictionary")
        return ToolResult("get_metric_definition", {"definition": dict(table.rows[0])},
                          (table.provenance.to_dict(),), "FACT")