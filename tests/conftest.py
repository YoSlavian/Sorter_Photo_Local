"""Shared fixtures and structural helpers for the test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:  # allows `pytest` without an editable install
    sys.path.insert(0, str(SRC))

from bpmn_architect.layout.geometry import Bounds, Point  # noqa: E402
from bpmn_architect.pipeline import DiagramResult, generate  # noqa: E402

EXAMPLES = ROOT / "examples"

ORDER_REQUEST = """\
Обработка заявки клиента

Процесс начинается с получения заявки от клиента.
Менеджер проверяет заявку.
Если заявка корректна, то бухгалтер выставляет счёт, иначе менеджер отклоняет заявку.
После этого менеджер уведомляет клиента.
Процесс завершается.
"""


@pytest.fixture
def order_request() -> DiagramResult:
    return generate(ORDER_REQUEST)


@pytest.fixture(params=sorted(p.name for p in EXAMPLES.iterdir() if p.is_file()))
def example(request: pytest.FixtureRequest) -> DiagramResult:
    """Every shipped example, one test invocation each."""
    return generate((EXAMPLES / request.param).read_text(encoding="utf-8"))


def overlaps(left: Bounds, right: Bounds, tolerance: float = 0.5) -> bool:
    """True when two boxes share interior area."""
    return (
        left.x < right.right - tolerance
        and right.x < left.right - tolerance
        and left.y < right.bottom - tolerance
        and right.y < left.bottom - tolerance
    )


def on_border(point: Point, bounds: Bounds, tolerance: float = 1.5) -> bool:
    """True when ``point`` lies on the outline of ``bounds``."""
    inside_x = bounds.x - tolerance <= point.x <= bounds.right + tolerance
    inside_y = bounds.y - tolerance <= point.y <= bounds.bottom + tolerance
    on_vertical = abs(point.x - bounds.x) <= tolerance or abs(point.x - bounds.right) <= tolerance
    on_horizontal = abs(point.y - bounds.y) <= tolerance or abs(point.y - bounds.bottom) <= tolerance
    return inside_x and inside_y and (on_vertical or on_horizontal)


def node_names(result: DiagramResult) -> list[str]:
    return [node.name for node in result.model.nodes]


def find(result: DiagramResult, name: str):  # type: ignore[no-untyped-def]
    """Return the single node whose name contains ``name``."""
    matches = [node for node in result.model.nodes if name.casefold() in node.name.casefold()]
    assert matches, f"no node matching {name!r} in {node_names(result)}"
    return matches[0]
