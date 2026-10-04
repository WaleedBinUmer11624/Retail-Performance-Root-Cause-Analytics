"""Phase 11 checkpoint 2 tests: central path guard, guarded artifact and text reads, tool
registry limits, response schema, and provider adapters that never need a key or network."""
from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experimental.ai_layer.analyst_context import GuardedAnalystContext
from experimental.ai_layer.artifacts import ArtifactError, ArtifactResolver
from experimental.ai_layer.path_guard import PathDeniedError, guard_path
from experimental.ai_layer.providers import (
    AnthropicProvider,
    GenerationRequest,
    MockProvider,
    OpenAICompatibleProvider,
    ProviderError,
    create_provider,
)
from experimental.ai_layer.response_schema import validate_response
from experimental.ai_layer.retrieval import KeywordIndex
from experimental.ai_layer.settings import RuntimeSettings, load_settings
from experimental.ai_layer.tools import ToolError, ToolRegistry


@pytest.fixture
def phase_config():
    """Parsed Phase 11 configuration."""
    import yaml

    return yaml.safe_load((ROOT / "config/phase11_config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def resolver(phase_config):
    """Guarded artifact resolver rooted at the project."""
    return ArtifactResolver(ROOT, phase_config)


@pytest.mark.parametrize("candidate", [
    "config/_hidden_scenario.yaml",
    "reports/_scenario_answer_key_future.csv",
    "reports/phase9/_planted_issues_log.txt",
    "reports/evaluation/golden.csv",
    "reports/phase2/calibration_results.csv",
    "reports/PHASE6/CALIBRATION_notes.md",
])
def test_central_path_guard_denies_required_fragments(candidate):
    with pytest.raises(PathDeniedError):
        guard_path(ROOT, candidate)


def test_central_path_guard_rejects_project_root_escape():
    with pytest.raises(PathDeniedError):
        guard_path(ROOT, "../outside.csv")


def test_artifact_resolver_denies_configured_path_before_file_access(phase_config):
    config = copy.deepcopy(phase_config)
    config["evidence_artifacts"]["phase6"]["attribution"] = "reports/evaluation/not_read.csv"
    resolver = ArtifactResolver(ROOT, config)
    with pytest.raises(PathDeniedError):
        resolver.read_csv_artifact("phase6.attribution")


def test_retriever_denies_configured_text_source_before_indexing(phase_config):
    config = copy.deepcopy(phase_config)
    config["retrieval"]["text_sources"] = ["reports/phase2/calibration_notes.md"]
    with pytest.raises(PathDeniedError):
        KeywordIndex.from_resolver(ArtifactResolver(ROOT, config))


def test_denied_paths_never_reach_file_reads_or_indexing(tmp_path, monkeypatch):
    config = {
        "evidence_artifacts": {"phase6": {"attribution": "reports/evaluation/answer.csv"}},
        "retrieval": {"text_sources": ["reports/_planted_issues_log_fake.md"]},
    }
    resolver = ArtifactResolver(tmp_path, config)

    def fail_if_read(_path):
        raise AssertionError("denied path reached a file read")

    monkeypatch.setattr(Path, "read_bytes", fail_if_read)
    with pytest.raises(PathDeniedError):
        resolver.read_csv_artifact("phase6.attribution")
    with pytest.raises(PathDeniedError):
        KeywordIndex.from_resolver(resolver)


def test_analyst_context_wrapper_denies_core_path_resolution(phase_config):
    with pytest.raises(PathDeniedError):
        GuardedAnalystContext(ROOT, phase_config,
                              artifact_paths={"blocked": "reports/_scenario_answer_key_fake.csv"})


def test_tool_registry_rejects_caller_supplied_path(resolver):
    tools = ToolRegistry(resolver)
    with pytest.raises(ToolError):
        tools.run("get_revenue_summary", {"path": "reports/evaluation/data.csv"})


def test_structured_tool_uses_governed_headline_fallback(resolver):
    result = ToolRegistry(resolver).run("get_revenue_summary")
    rows = result.data["headline"]
    assert rows
    assert any(row["label"] == "Net Revenue H2 2025" for row in rows)
    assert result.provenance[0]["source_file"] == "reports/phase7/dashboard_number_register.csv"
    assert len(result.provenance[0]["content_sha256"]) == 64


def test_missing_phase6_headline_uses_existing_phase7_number_register(phase_config):
    configured = phase_config["evidence_artifacts"]["phase6"]["headline"]
    assert configured == "reports/phase7/dashboard_number_register.csv"
    assert (ROOT / configured).is_file()
    assert not (ROOT / "reports/phase6/headline_kpis.csv").exists()


def test_keyword_index_returns_safe_text_with_provenance(resolver):
    index = KeywordIndex.from_resolver(resolver)
    hits = index.search("cluster transaction decline evidence", top_k=3)
    assert hits
    assert all("evaluation" not in hit.provenance["source_file"].casefold() for hit in hits)
    assert all(len(hit.provenance["content_sha256"]) == 64 for hit in hits)


def test_response_schema_accepts_resolved_provenance():
    source = {
        "source_file": "reports/phase6/driver_attribution.csv",
        "phase": "phase6",
        "retrieval_method": "configured_artifact:phase6.attribution",
        "content_sha256": "a" * 64,
        "filters": {},
        "record_count": 5,
        "row_index": None,
    }
    payload = {
        "answer": "Evidence summary.",
        "executive_summary": "One governed driver was retrieved.",
        "evidence": [{
            "evidence_id": "E1", "evidence_type": "ATTRIBUTION", "claim": "A measured attribution row.",
            "source_ids": [source["source_file"]], "metric": "amount_eur", "value": -10,
            "comparison_period": "H2 2025", "filters": {},
        }],
        "sources": [source],
        "confidence": "UNASSESSED",
        "limitations": [],
        "recommended_follow_up": [],
    }
    validate_response(payload)
    payload["evidence"][0]["source_ids"] = ["reports/evaluation/fake.csv"]
    with pytest.raises(ValueError, match="source_id"):
        validate_response(payload)


def test_mock_provider_requires_no_api_key():
    settings = load_settings(ROOT, {})
    provider = create_provider(settings)
    assert isinstance(provider, MockProvider)
    assert provider.complete(GenerationRequest("system", "question")) == \
        "Insufficient evidence to answer from the available project data."


def test_openai_compatible_adapter_uses_mocked_http_only():
    settings = RuntimeSettings(ROOT, {}, "openai-compatible", "local-model", None,
                                "http://localhost:11434/v1", 2)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "Local mock answer"}}]}).encode()

    with patch("urllib.request.urlopen", return_value=FakeResponse()) as open_url:
        answer = OpenAICompatibleProvider(settings).complete(GenerationRequest("sys", "question"))
    assert answer == "Local mock answer"
    assert open_url.call_args.args[0].full_url == "http://localhost:11434/v1/chat/completions"


def test_anthropic_adapter_imports_sdk_lazily_without_network():
    settings = RuntimeSettings(ROOT, {}, "anthropic", "mock-model", "test-only-key", None, 2)

    class FakeMessages:
        def create(self, **_kwargs):
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Offline adapter response")])

    class FakeClient:
        def __init__(self, **_kwargs):
            self.messages = FakeMessages()

    fake_module = types.SimpleNamespace(Anthropic=FakeClient)
    with patch.dict(sys.modules, {"anthropic": fake_module}):
        answer = AnthropicProvider(settings).complete(GenerationRequest("sys", "question"))
    assert answer == "Offline adapter response"


def test_environment_settings_default_to_offline_and_never_require_secret():
    settings = load_settings(ROOT, {})
    assert settings.provider == "mock"
    assert settings.api_key is None
    assert settings.base_url is None
