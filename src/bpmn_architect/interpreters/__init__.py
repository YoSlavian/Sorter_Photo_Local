"""Interpretation layer: text to IR, deterministically or with a model."""

from __future__ import annotations

from bpmn_architect.interpreters.base import (
    BPMNInterpreter,
    InterpretationResult,
    InterpreterError,
    InterpreterMode,
    LLMUnavailable,
)
from bpmn_architect.interpreters.hybrid import HybridInterpreter
from bpmn_architect.interpreters.llm import LLMInterpreter
from bpmn_architect.interpreters.providers import LLMConfig, LLMProvider, resolve_provider
from bpmn_architect.interpreters.rule_based import RuleBasedInterpreter
from bpmn_architect.parsing import ParserOptions

__all__ = [
    "BPMNInterpreter",
    "HybridInterpreter",
    "InterpretationResult",
    "InterpreterError",
    "InterpreterMode",
    "LLMConfig",
    "LLMProvider",
    "LLMInterpreter",
    "LLMUnavailable",
    "RuleBasedInterpreter",
    "create_interpreter",
    "resolve_provider",
]


def create_interpreter(
    mode: InterpreterMode | str = InterpreterMode.DETERMINISTIC,
    *,
    config: LLMConfig | None = None,
    provider: LLMProvider | None = None,
    syntax: str = "auto",
    options: ParserOptions | None = None,
) -> BPMNInterpreter:
    """Build the interpreter for ``mode``.

    Deterministic mode never touches a provider, so it works in an offline
    install; the AI modes resolve one lazily and fail with a clear message if
    none is configured.
    """
    resolved = InterpreterMode(mode) if isinstance(mode, str) else mode
    if resolved is InterpreterMode.DETERMINISTIC:
        return RuleBasedInterpreter(syntax=syntax, options=options)
    if resolved is InterpreterMode.AI:
        return LLMInterpreter(provider, config)
    return HybridInterpreter(provider, config, syntax=syntax, options=options)
