"""OpenAI backend, built on the official OpenAI SDK.

Installed as an optional extra (``pip install "bpmn-architect[openai]"``).
"""

from __future__ import annotations

from typing import Any

from bpmn_architect.interpreters.base import LLMUnavailable
from bpmn_architect.interpreters.providers.base import LLMConfig

__all__ = ["OpenAIProvider"]

DEFAULT_MODEL = "gpt-4.1"


class OpenAIProvider:
    """Interprets process descriptions with an OpenAI model."""

    name = "openai"

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig(provider="openai")
        self._client: Any | None = None

    def available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return bool(self.config.api_key) or bool(self.config.base_url)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover - depends on the install
            raise LLMUnavailable(
                'the OpenAI SDK is not installed; run: pip install "bpmn-architect[openai]"'
            ) from error
        options: dict[str, Any] = {"timeout": self.config.timeout}
        if self.config.api_key:
            options["api_key"] = self.config.api_key
        if self.config.base_url:
            options["base_url"] = self.config.base_url
        try:
            self._client = OpenAI(**options)
        except Exception as error:  # noqa: BLE001 - surfaced as a clear message
            raise LLMUnavailable(f"could not create the OpenAI client: {error}") from error
        return self._client

    def complete(self, system: str, user: str) -> str:
        client = self._ensure_client()
        try:
            response = client.chat.completions.create(
                model=self.config.model or DEFAULT_MODEL,
                max_tokens=self.config.max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as error:  # noqa: BLE001 - network and API errors alike
            raise LLMUnavailable(f"the OpenAI request failed: {error}") from error
        text = response.choices[0].message.content or ""
        if not text.strip():
            raise LLMUnavailable("the model returned an empty answer")
        return text
