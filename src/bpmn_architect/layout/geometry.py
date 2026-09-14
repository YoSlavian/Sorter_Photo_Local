"""Geometric primitives and the metrics that define the diagram's look."""

from __future__ import annotations

from dataclasses import dataclass

from bpmn_architect.domain.model import Node, NodeKind

__all__ = ["Point", "Bounds", "LayoutMetrics", "size_for"]


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def moved(self, dx: float = 0.0, dy: float = 0.0) -> Point:
        return Point(self.x + dx, self.y + dy)

    def rounded(self) -> Point:
        return Point(round(self.x, 1), round(self.y, 1))


@dataclass(frozen=True, slots=True)
class Bounds:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    def moved(self, dx: float = 0.0, dy: float = 0.0) -> Bounds:
        return Bounds(self.x + dx, self.y + dy, self.width, self.height)

    def with_center_y(self, center_y: float) -> Bounds:
        return Bounds(self.x, center_y - self.height / 2, self.width, self.height)

    def with_x(self, x: float) -> Bounds:
        return Bounds(x, self.y, self.width, self.height)

    def union(self, other: Bounds) -> Bounds:
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        return Bounds(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)

    def rounded(self) -> Bounds:
        return Bounds(round(self.x, 1), round(self.y, 1), round(self.width, 1), round(self.height, 1))


@dataclass(frozen=True, slots=True)
class LayoutMetrics:
    """All tunable distances in one place.

    The defaults reproduce the spacing Camunda Modeler uses when a human drags
    elements onto the canvas, so generated diagrams sit comfortably next to
    hand-drawn ones.
    """

    task_width: float = 100.0
    task_height: float = 80.0
    gateway_size: float = 50.0
    event_size: float = 36.0
    sub_process_width: float = 120.0
    sub_process_height: float = 90.0

    #: Free space between two consecutive columns (ranks).
    rank_gap: float = 60.0
    #: Free space between two elements stacked inside one column.
    node_gap: float = 40.0
    #: Width reserved in a column for an edge that only passes through.
    virtual_width: float = 24.0

    lane_header_width: float = 30.0
    lane_padding: float = 24.0
    lane_min_height: float = 120.0
    pool_origin_x: float = 160.0
    pool_origin_y: float = 80.0

    #: Distance below the last element at which a loop-back edge is routed.
    loop_clearance: float = 26.0
    #: Vertical distance between two loop-back edges sharing a lane.
    loop_spacing: float = 18.0

    label_height: float = 14.0
    label_char_width: float = 6.2
    label_max_width: float = 120.0


_DEFAULT_METRICS = LayoutMetrics()


def size_for(node: Node, metrics: LayoutMetrics | None = None) -> tuple[float, float]:
    """Return the (width, height) BPMN prescribes for ``node``."""
    metrics = metrics or _DEFAULT_METRICS
    if node.kind.is_event:
        return metrics.event_size, metrics.event_size
    if node.kind.is_gateway:
        return metrics.gateway_size, metrics.gateway_size
    if node.kind in {NodeKind.SUB_PROCESS, NodeKind.CALL_ACTIVITY}:
        return metrics.sub_process_width, metrics.sub_process_height
    return metrics.task_width, metrics.task_height
