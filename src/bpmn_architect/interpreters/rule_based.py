"""The deterministic interpreter: the existing rule parser behind the protocol."""

from __future__ import annotations

from bpmn_architect.interpreters.base import (
    BPMNInterpreter,
    InterpretationResult,
    InterpreterMode,
)
from bpmn_architect.parsing import ParserOptions, parse

__all__ = ["RuleBasedInterpreter"]


class RuleBasedInterpreter(BPMNInterpreter):
    """Wraps :func:`bpmn_architect.parsing.parse` without changing its behaviour.

    Zero dependencies, fully reproducible, and the fallback for every other
    mode — so a missing API key degrades the product's quality, never its
    availability.
    """

    def __init__(self, *, syntax: str = "auto", options: ParserOptions | None = None) -> None:
        self.syntax = syntax
        self.options = options

    def interpret(self, text: str) -> InterpretationResult:
        return InterpretationResult(
            ir=parse(text, syntax=self.syntax, options=self.options),
            mode=InterpreterMode.DETERMINISTIC,
            deterministic=True,
        )
