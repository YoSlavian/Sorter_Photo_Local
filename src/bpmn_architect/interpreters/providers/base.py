"""Provider contract for language-model backends.

A provider does one thing: given a system prompt and a description, return the
model's raw text answer.  It knows nothing about BPMN — prompt construction and
answer parsing live one level up, in
:mod:`bpmn_architect.interpreters.llm`, so adding a provider means implementing
a single method.

Every provider imports its SDK **inside** the method that needs it.  The core
package must stay installable with no dependencies, and an unconfigured
provider must fail with a clear message rather than an ImportError at start-up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from bpmn_architect.interpreters.base import LLMUnavailable

__all__ = ["LLMConfig", "LLMProvider", "resolve_provider"]


@dataclass(slots=True)
class LLMConfig:
    """Everything a provider needs, resolved from arguments or the environment."""

    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 16000
    #: Effort/verbosity hint, passed through where the provider supports it.
    effort: str = "high"
    timeout: float = 120.0

    @classmethod
    def from_env(cls, provider: str | None = None) -> LLMConfig:
        """Build a config from ``BPMN_ARCHITECT_*`` and provider-native variables."""
        name = (provider or os.getenv("BPMN_ARCHITECT_LLM_PROVIDER") or "anthropic").casefold()
        config = cls(provider=name)
        config.model = os.getenv("BPMN_ARCHITECT_LLM_MODEL", "")
        config.base_url = os.getenv("BPMN_ARCHITECT_LLM_BASE_URL", "")
        if name == "anthropic":
            config.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        elif name == "openai":
            config.api_key = os.getenv("OPENAI_API_KEY", "")
        else:
            config.api_key = os.getenv("BPMN_ARCHITECT_LLM_API_KEY", "")
        return config


@runtime_checkable
class LLMProvider(Protocol):
    """A text-in, text-out language model backend."""

    name: str

    def available(self) -> bool:
        """True when the provider can actually be called right now."""
        ...

    def complete(self, system: str, user: str) -> str:
        """Return the model's answer, or raise :class:`LLMUnavailable`."""
        ...


def resolve_provider(config: LLMConfig | None = None) -> LLMProvider:
    """Instantiate the provider named by ``config``."""
    config = config or LLMConfig.from_env()
    name = config.provider.casefold()
    if name == "anthropic":
        from bpmn_architect.interpreters.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config)
    if name == "openai":
        from bpmn_architect.interpreters.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(config)
    if name in {"local", "ollama", "vllm", "llamacpp", "openai-compatible"}:
        from bpmn_architect.interpreters.providers.local_provider import LocalProvider

        return LocalProvider(config)
    raise LLMUnavailable(
        f"unknown LLM provider {config.provider!r}; "
        f"expected one of: anthropic, openai, local"
    )
