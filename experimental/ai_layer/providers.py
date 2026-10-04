"""Provider boundary with deterministic mock and optional remote adapters.

Input: a GenerationRequest with separate system, user and evidence parts. Output: completion text,
or ProviderError. Only the mock runs by default; remote adapters need explicit environment settings.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .settings import RuntimeSettings


class ProviderError(RuntimeError):
    """Raised when a provider cannot return a completion."""


@dataclass(frozen=True)
class GenerationRequest:
    """Prompt parts kept separate so evidence can never be read as instructions."""
    system_prompt: str
    user_prompt: str
    evidence: tuple[dict, ...] = ()
    max_tokens: int = 1200


class LanguageModelProvider(Protocol):
    """Interface every provider adapter implements."""
    name: str

    def complete(self, request: GenerationRequest) -> str:
        """Return the completion text for the request."""
        ...


class MockProvider:
    """No-network provider for deterministic tests and offline demonstrations."""

    name = "mock"

    def complete(self, request: GenerationRequest) -> str:
        """Deterministic text naming the evidence count and sources; never calls the network."""
        sources = sorted({
            str(item.get("provenance", {}).get("source_file", ""))
            for item in request.evidence
            if item.get("provenance", {}).get("source_file")
        })
        if not request.evidence:
            return "Insufficient evidence to answer from the available project data."
        suffix = ", ".join(sources)
        return f"Mock response. {len(request.evidence)} evidence item(s) were supplied from: {suffix}."


class OpenAICompatibleProvider:
    """Adapter for OpenAI-compatible endpoints, including local Ollama endpoints."""

    name = "openai-compatible"

    def __init__(self, settings: RuntimeSettings):
        if not settings.base_url:
            raise ProviderError("BRIGHTWATER_LLM_BASE_URL is required for an OpenAI-compatible endpoint")
        self.base_url = settings.base_url.rstrip("/")
        self.api_key = settings.api_key
        self.model = settings.model
        self.timeout = settings.timeout_seconds

    def complete(self, request: GenerationRequest) -> str:
        """POST to the chat-completions endpoint at temperature 0 and return the reply text."""
        endpoint = self.base_url
        # Accept a bare host, a /v1 base or the full endpoint, as different servers document it.
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions" if endpoint.endswith("/v1") else "/v1/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": 0,
            "max_tokens": request.max_tokens,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError("OpenAI-compatible completion failed") from error
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("OpenAI-compatible provider returned empty content")
        return content.strip()


class AnthropicProvider:
    """Optional Anthropic adapter. The SDK is imported only when this adapter is called."""

    name = "anthropic"

    def __init__(self, settings: RuntimeSettings):
        if not settings.api_key:
            raise ProviderError("BRIGHTWATER_LLM_API_KEY is required for Anthropic")
        self.api_key = settings.api_key
        self.model = settings.model
        self.timeout = settings.timeout_seconds

    def complete(self, request: GenerationRequest) -> str:
        """Call the Messages API and join the text blocks of the reply."""
        try:
            import anthropic
        except ImportError as error:
            raise ProviderError("Anthropic support is optional; install the anthropic package to use it") from error
        try:
            client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
            response = client.messages.create(
                model=self.model,
                max_tokens=request.max_tokens,
                system=request.system_prompt,
                messages=[{"role": "user", "content": request.user_prompt}],
            )
            content = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        except Exception as error:  # SDK exceptions vary by supported SDK version.
            raise ProviderError("Anthropic completion failed") from error
        if not content.strip():
            raise ProviderError("Anthropic provider returned empty content")
        return content.strip()


def create_provider(settings: RuntimeSettings) -> LanguageModelProvider:
    """Build the adapter named in settings; an unknown name is an error, not a silent mock."""
    provider = settings.provider.casefold()
    if provider == "mock":
        return MockProvider()
    if provider in {"openai", "openai-compatible", "ollama"}:
        return OpenAICompatibleProvider(settings)
    if provider == "anthropic":
        return AnthropicProvider(settings)
    raise ProviderError("Unsupported Phase 11 provider")