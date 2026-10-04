"""Dependency wiring for the optional, offline-first Phase 11 layer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .analyst_context import GuardedAnalystContext
from .artifacts import ArtifactResolver
from .orchestrator import GroundedAssistant
from .providers import LanguageModelProvider, create_provider
from .retrieval import KeywordIndex
from .settings import RuntimeSettings, load_settings
from .tools import ToolRegistry


@dataclass(frozen=True)
class Phase11Runtime:
    """Every wired component of the assistant, built once per run."""
    settings: RuntimeSettings
    resolver: ArtifactResolver
    analyst: GuardedAnalystContext
    tools: ToolRegistry
    retriever: KeywordIndex
    provider: LanguageModelProvider
    assistant: GroundedAssistant


def create_runtime(project_root: str | Path, engine=None, environ=None) -> Phase11Runtime:
    """Load settings and wire resolver, analyst context, tools, retriever, provider and assistant."""
    settings = load_settings(project_root, environ=environ)
    resolver = ArtifactResolver(settings.project_root, settings.phase_config)
    weekly_path = settings.phase_config["evidence_artifacts"]["phase10"]["weekly_history"]
    analyst = GuardedAnalystContext(
        settings.project_root, settings.phase_config, engine=engine,
        artifact_paths={"weeks": weekly_path},
    )
    tools = ToolRegistry(resolver, analyst)
    retriever = KeywordIndex.from_resolver(resolver)
    provider = create_provider(settings)
    return Phase11Runtime(
        settings=settings,
        resolver=resolver,
        analyst=analyst,
        tools=tools,
        retriever=retriever,
        provider=provider,
        assistant=GroundedAssistant(
            tools=tools,
            retriever=retriever,
            provider=provider,
            config=settings.phase_config,
            provider_name=settings.provider,
            model=settings.model,
        ),
    )