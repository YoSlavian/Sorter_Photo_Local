"""Exception hierarchy shared by every layer."""

from __future__ import annotations

__all__ = [
    "BpmnArchitectError",
    "ParseError",
    "BuildError",
    "ValidationFailed",
    "LayoutError",
    "RenderError",
]


class BpmnArchitectError(Exception):
    """Base class for all errors raised by the library."""


class ParseError(BpmnArchitectError):
    """The input description could not be turned into an IR tree."""

    def __init__(self, message: str, line: int = 0, snippet: str = ""):
        self.line = line
        self.snippet = snippet
        location = f" (line {line})" if line else ""
        context = f": {snippet!r}" if snippet else ""
        super().__init__(f"{message}{location}{context}")


class BuildError(BpmnArchitectError):
    """The IR tree could not be turned into a BPMN graph."""


class ValidationFailed(BpmnArchitectError):
    """The resulting graph violates BPMN structural rules."""

    def __init__(self, message: str, diagnostics: list[object] | None = None):
        self.diagnostics = diagnostics or []
        super().__init__(message)


class LayoutError(BpmnArchitectError):
    """The graph could not be laid out."""


class RenderError(BpmnArchitectError):
    """The diagram could not be serialised."""
