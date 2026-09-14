"""Runs the structural rule set over a process model."""

from __future__ import annotations

from collections.abc import Iterable

from bpmn_architect.domain.model import ProcessModel
from bpmn_architect.validation.diagnostics import Diagnostics
from bpmn_architect.validation.rules import RULES, Rule

__all__ = ["Validator", "validate"]


class Validator:
    """Applies a rule set and collects the findings."""

    def __init__(self, rules: Iterable[Rule] | None = None) -> None:
        self.rules: tuple[Rule, ...] = tuple(rules) if rules is not None else RULES

    def validate(self, model: ProcessModel, into: Diagnostics | None = None) -> Diagnostics:
        diagnostics = into if into is not None else Diagnostics()
        for rule in self.rules:
            rule(model, diagnostics)
        return diagnostics


def validate(model: ProcessModel, into: Diagnostics | None = None) -> Diagnostics:
    """Convenience wrapper around :class:`Validator`."""
    return Validator().validate(model, into)
