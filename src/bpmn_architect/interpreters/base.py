"""The interpretation contract: text in, IR out, whoever produces it.

Studio can read a description with the built-in rule parser, with a language
model, or with both.  Everything downstream — graph building, validation,
layout, rendering — must not care which.  That is what this module fixes in
place: a single protocol returning the same :class:`IRProcess` the rule parser
has always produced.

The core therefore never imports a model SDK.  Providers live behind
:mod:`bpmn_architect.interpreters.providers` and are optional installs; with
none of them present the deterministic interpreter still works, which keeps
``pip install bpmn-architect`` dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from bpmn_architect.domain.ir import IRProcess
from bpmn_architect.errors import BpmnArchitectError

__all__ = [
    "InterpreterMode",
    "InterpretationResult",
    "BPMNInterpreter",
    "InterpreterError",
    "LLMUnavailable",
]


class InterpreterMode(Enum):
    """How much freedom the interpreter has.

    ``DETERMINISTIC`` is the default and the only mode that is bit-for-bit
    reproducible; the others trade that for coverage of wording the rule set
    does not know.
    """

    DETERMINISTIC = "deterministic"
    AI = "ai"
    HYBRID = "hybrid"

    @property
    def needs_provider(self) -> bool:
        return self in {InterpreterMode.AI, InterpreterMode.HYBRID}


class InterpreterError(BpmnArchitectError):
    """The interpreter could not turn the text into an IR tree."""


class LLMUnavailable(InterpreterError):
    """An AI mode was requested but no usable provider is configured."""


@dataclass(slots=True)
class InterpretationResult:
    """An IR tree plus a record of how it was produced."""

    ir: IRProcess
    mode: InterpreterMode = InterpreterMode.DETERMINISTIC
    #: Human-readable notes about decisions the interpreter made.
    notes: list[str] = field(default_factory=list)
    #: Provider identifier, empty for the deterministic interpreter.
    provider: str = ""
    #: True when the result is reproducible from the same input.
    deterministic: bool = True

    def note(self, message: str) -> None:
        self.notes.append(message)


@runtime_checkable
class BPMNInterpreter(Protocol):
    """Anything that can read a description into an IR tree."""

    def interpret(self, text: str) -> InterpretationResult:
        """Turn ``text`` into an :class:`IRProcess`.

        Implementations must raise :class:`InterpreterError` rather than
        returning a partial tree: callers decide whether to fall back.
        """
        ...
