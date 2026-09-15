"""Local model backend for any OpenAI-compatible server.

Covers Ollama, vLLM, LM Studio and llama.cpp, which all expose the same
``/v1/chat/completions`` shape.  Only the default base URL differs from
:class:`OpenAIProvider`, so the request logic is inherited rather than copied.
"""

from __future__ import annotations

from bpmn_architect.interpreters.providers.base import LLMConfig
from bpmn_architect.interpreters.providers.openai_provider import OpenAIProvider

__all__ = ["LocalProvider"]

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "llama3.1"


class LocalProvider(OpenAIProvider):
    """A model served locally behind an OpenAI-compatible endpoint."""

    name = "local"

    def __init__(self, config: LLMConfig | None = None) -> None:
        config = config or LLMConfig(provider="local")
        if not config.base_url:
            config.base_url = DEFAULT_BASE_URL
        if not config.model:
            config.model = DEFAULT_MODEL
        if not config.api_key:
            config.api_key = "not-needed"  # these servers ignore the key
        super().__init__(config)

    def available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return bool(self.config.base_url)
