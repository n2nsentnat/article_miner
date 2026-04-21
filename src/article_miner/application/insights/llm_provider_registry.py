"""Registry of LiteLLM insight provider strategies (model id + completion kwargs from env).

CLIs pick a provider name; this module resolves the concrete ``model`` string and any
provider-specific kwargs (e.g. Ollama ``api_base``) without duplicating if/elif chains.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Defaults when env vars are unset (match previous CLI behavior).
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_GEMINI_MODEL = "gemini/gemini-2.0-flash"
_DEFAULT_CLAUDE_MODEL = "anthropic/claude-3-5-sonnet-20241022"
_DEFAULT_OLLAMA_MODEL = "ollama/gemma3:4b"
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


@dataclass(frozen=True)
class InsightLlmResolution:
    """Result of resolving a named insight LLM provider."""

    model: str
    extra_completion_kwargs: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class InsightLlmProviderStrategy(Protocol):
    """Strategy: map process env to LiteLLM model id and optional kwargs."""

    def resolve(self, env: Mapping[str, str]) -> InsightLlmResolution: ...


class _OpenAiStrategy:
    def resolve(self, env: Mapping[str, str]) -> InsightLlmResolution:
        model = env.get("INSIGHT_MODEL_OPENAI", _DEFAULT_OPENAI_MODEL)
        return InsightLlmResolution(model=model)


class _GeminiStrategy:
    def resolve(self, env: Mapping[str, str]) -> InsightLlmResolution:
        model = env.get("INSIGHT_MODEL_GEMINI", _DEFAULT_GEMINI_MODEL)
        return InsightLlmResolution(model=model)


class _ClaudeStrategy:
    def resolve(self, env: Mapping[str, str]) -> InsightLlmResolution:
        model = env.get("INSIGHT_MODEL_CLAUDE", _DEFAULT_CLAUDE_MODEL)
        return InsightLlmResolution(model=model)


class _OllamaStrategy:
    def resolve(self, env: Mapping[str, str]) -> InsightLlmResolution:
        raw = env.get("OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL.replace("ollama/", ""))
        model = raw if raw.startswith("ollama/") else f"ollama/{raw}"
        base = env.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL)
        return InsightLlmResolution(
            model=model, extra_completion_kwargs={"api_base": base}
        )


# Canonical registry keys (lowercase). Aliases map to these via normalize_insight_provider().
_INSIGHT_LLM_STRATEGIES: dict[str, InsightLlmProviderStrategy] = {
    "openai": _OpenAiStrategy(),
    "gemini": _GeminiStrategy(),
    "claude": _ClaudeStrategy(),
    "ollama": _OllamaStrategy(),
}

_PROVIDER_API_KEY_ENV: dict[str, str | None] = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "ollama": None,
}


def normalize_insight_provider(name: str) -> str:
    """Return canonical provider key: lowercase strip; ``anthropic`` → ``claude``."""
    key = name.strip().lower()
    if key == "anthropic":
        return "claude"
    return key


def registered_insight_providers() -> tuple[str, ...]:
    """Sorted canonical provider ids."""
    return tuple(sorted(_INSIGHT_LLM_STRATEGIES.keys()))


def resolve_insight_llm_provider(
    name: str,
    env: Mapping[str, str],
) -> InsightLlmResolution:
    """Resolve provider label to model + kwargs. Raises ``KeyError`` if unknown."""
    key = normalize_insight_provider(name)
    strategy = _INSIGHT_LLM_STRATEGIES[key]
    return strategy.resolve(env)


def expected_api_key_env_name(canonical_provider: str) -> str | None:
    """Env var that should be set for API access, or ``None`` for local Ollama."""
    return _PROVIDER_API_KEY_ENV.get(normalize_insight_provider(canonical_provider))


def register_insight_llm_strategy(
    canonical_name: str,
    strategy: InsightLlmProviderStrategy,
) -> None:
    """Register or replace a strategy (mainly for tests / extension)."""
    key = canonical_name.strip().lower()
    _INSIGHT_LLM_STRATEGIES[key] = strategy
    if key not in _PROVIDER_API_KEY_ENV:
        _PROVIDER_API_KEY_ENV[key] = None
