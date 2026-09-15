"""Claude backend, built on the official Anthropic SDK.

Installed as an optional extra (``pip install "bpmn-architect[anthropic]"``) so
that the core package keeps its zero-dependency promise.
"""

from __future__ import annotations

from typing import Any

from bpmn_architect.interpreters.base import LLMUnavailable
from bpmn_architect.interpreters.providers.base import LLMConfig

__all__ = ["AnthropicProvider", "DEFAULT_MODEL"]

#: Claude Opus 5 - the current default model for this integration.
DEFAULT_MODEL = "claude-opus-5"


class AnthropicProvider:
    """Interprets process descriptions with Claude."""

    name = "anthropic"

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig(provider="anthropic")
        self._client: Any | None = None

    # -- availability --------------------------------------------------------

    def available(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        # An unset ANTHROPIC_API_KEY does not mean there are no credentials:
        # the SDK also resolves an `ant auth login` profile.  Construction is
        # the only honest test, and it is cheap.
        try:
            self._ensure_client()
        except LLMUnavailable:
            return False
        return True

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as error:  # pragma: no cover - depends on the install
            raise LLMUnavailable(
                "the Anthropic SDK is not installed; "
                'run: pip install "bpmn-architect[anthropic]"'
            ) from error
        try:
            if self.config.api_key:
                self._client = anthropic.Anthropic(
                    api_key=self.config.api_key, timeout=self.config.timeout
                )
            else:
                self._client = anthropic.Anthropic(timeout=self.config.timeout)
        except Exception as error:  # noqa: BLE001 - surfaced as a clear message
            raise LLMUnavailable(f"could not create the Anthropic client: {error}") from error
        return self._client

    # -- completion ----------------------------------------------------------

    def complete(self, system: str, user: str) -> str:
        import anthropic

        client = self._ensure_client()
        try:
            response = client.messages.create(
                model=self.config.model or DEFAULT_MODEL,
                max_tokens=self.config.max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": self.config.effort},
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIStatusError as error:
            raise LLMUnavailable(
                f"Anthropic API error {error.status_code}: {error.message}"
            ) from error
        except anthropic.APIConnectionError as error:
            raise LLMUnavailable(f"could not reach the Anthropic API: {error}") from error

        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMUnavailable(
                f"the model declined to answer{f' ({category})' if category else ''}"
            )

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        if not text.strip():
            raise LLMUnavailable("the model returned an empty answer")
        return text
