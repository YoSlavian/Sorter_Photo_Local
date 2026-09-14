"""Diagnostics shared by the builder, the validator and the CLI."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum

__all__ = ["Severity", "Diagnostic", "Diagnostics"]


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 0, "warning": 1, "info": 2}[self.value]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single finding, addressed at a model element where possible."""

    code: str
    severity: Severity
    message: str
    element_id: str | None = None
    line: int = 0

    def __str__(self) -> str:
        location = f" [{self.element_id}]" if self.element_id else ""
        origin = f" (line {self.line})" if self.line else ""
        return f"{self.severity.value.upper():7} {self.code}{location}{origin}: {self.message}"


class Diagnostics:
    """An ordered collection of :class:`Diagnostic` values."""

    __slots__ = ("_items",)

    def __init__(self, items: Iterable[Diagnostic] = ()) -> None:
        self._items: list[Diagnostic] = list(items)

    def add(
        self,
        code: str,
        severity: Severity,
        message: str,
        element_id: str | None = None,
        line: int = 0,
    ) -> Diagnostic:
        diagnostic = Diagnostic(code, severity, message, element_id, line)
        self._items.append(diagnostic)
        return diagnostic

    def error(self, code: str, message: str, element_id: str | None = None, line: int = 0) -> None:
        self.add(code, Severity.ERROR, message, element_id, line)

    def warning(self, code: str, message: str, element_id: str | None = None, line: int = 0) -> None:
        self.add(code, Severity.WARNING, message, element_id, line)

    def info(self, code: str, message: str, element_id: str | None = None, line: int = 0) -> None:
        self.add(code, Severity.INFO, message, element_id, line)

    def extend(self, other: Iterable[Diagnostic]) -> None:
        self._items.extend(other)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self._items if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self._items if d.severity is Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self._items)

    def sorted(self) -> list[Diagnostic]:
        return sorted(self._items, key=lambda d: (d.severity.rank, d.code, d.element_id or ""))

    def format(self) -> str:
        return "\n".join(str(d) for d in self.sorted())

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Diagnostics errors={len(self.errors)} total={len(self._items)}>"
