"""Edge routing: orthogonal waypoints and label placement.

Step four of the pipeline.  Waypoints are what a BPMN tool actually stores, so
this is where layout quality becomes visible.  Three routing styles cover
everything a process diagram needs:

* **straight** — source and target share a horizontal line (the happy path);
* **elbow** — a split leaves through the top/bottom face and a join is entered
  through it, which is how modellers draw gateways by hand;
* **loop-back** — rework edges run underneath the elements they skip, in a band
  reserved for them during positioning, so they never cross an element.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bpmn_architect.domain.model import ProcessModel
from bpmn_architect.layout.geometry import Bounds, LayoutMetrics, Point
from bpmn_architect.layout.positioning import Positions
from bpmn_architect.layout.ranking import LayeredGraph

__all__ = ["EdgeRoutes", "route_edges", "label_bounds_for"]

_EPSILON = 1.5
#: Vertical difference below which an edge is drawn as a single straight line.
_STRAIGHT_TOLERANCE = 4.0


@dataclass(slots=True)
class EdgeRoutes:
    waypoints: dict[str, list[Point]] = field(default_factory=dict)
    edge_labels: dict[str, Bounds] = field(default_factory=dict)
    node_labels: dict[str, Bounds] = field(default_factory=dict)


def route_edges(
    model: ProcessModel,
    graph: LayeredGraph,
    positions: Positions,
    metrics: LayoutMetrics,
) -> EdgeRoutes:
    routes = EdgeRoutes()
    loop_index = _loop_indices(model, graph, positions)

    for flow in model.flows:
        source = positions.bounds[flow.source_id]
        target = positions.bounds[flow.target_id]
        if flow.id in graph.back_edges:
            points = _route_loop(
                model,
                flow.source_id,
                flow.target_id,
                source,
                target,
                positions,
                metrics,
                loop_index.get(flow.id, 0),
            )
        else:
            via = [positions.virtual[v.id] for v in graph.chains.get(flow.id, [])]
            points = _route_forward(model, flow.source_id, flow.target_id, source, target, via)
        routes.waypoints[flow.id] = [point.rounded() for point in _simplify(points)]
        if flow.name:
            routes.edge_labels[flow.id] = _edge_label(routes.waypoints[flow.id], flow.name, metrics)

    for node in model.nodes:
        if not node.name:
            continue
        if node.kind.is_event or node.kind.is_gateway:
            routes.node_labels[node.id] = label_bounds_for(
                positions.bounds[node.id], node.name, metrics, below=node.kind.is_event
            )
    return routes


# --------------------------------------------------------------------------- #
# Forward edges
# --------------------------------------------------------------------------- #


def _route_forward(
    model: ProcessModel,
    source_id: str,
    target_id: str,
    source: Bounds,
    target: Bounds,
    via: list[Point],
) -> list[Point]:
    diverging = len(model.outgoing(source_id)) > 1
    converging = len(model.incoming(target_id)) > 1
    delta_y = target.center_y - source.center_y

    if via:
        start = Point(source.right, source.center_y)
        end = Point(target.x, target.center_y)
        return _orthogonalize([start, *via, end], lead_out=True)

    if abs(delta_y) <= _STRAIGHT_TOLERANCE:
        y = (source.center_y + target.center_y) / 2
        return [Point(source.right, y), Point(target.x, y)]

    # Leaving through a horizontal face only pays off when the target is
    # clearly above or below; otherwise the edge would double back on itself.
    if (
        diverging
        and model.node(source_id).kind.is_gateway
        and abs(delta_y) > source.height / 2 + 10
    ):
        exit_y = source.bottom if delta_y > 0 else source.y
        return [
            Point(source.center_x, exit_y),
            Point(source.center_x, target.center_y),
            Point(target.x, target.center_y),
        ]

    if (
        converging
        and model.node(target_id).kind.is_gateway
        and abs(delta_y) > target.height / 2 + 10
    ):
        entry_y = target.y if delta_y > 0 else target.bottom
        return [
            Point(source.right, source.center_y),
            Point(target.center_x, source.center_y),
            Point(target.center_x, entry_y),
        ]

    middle = (source.right + target.x) / 2
    return [
        Point(source.right, source.center_y),
        Point(middle, source.center_y),
        Point(middle, target.center_y),
        Point(target.x, target.center_y),
    ]


def _orthogonalize(points: list[Point], *, lead_out: bool) -> list[Point]:
    """Insert corner points so that every segment is axis-parallel."""
    result = [points[0]]
    for index, point in enumerate(points[1:], start=1):
        last = result[-1]
        if abs(point.x - last.x) > _EPSILON and abs(point.y - last.y) > _EPSILON:
            if index == 1 and lead_out:
                middle = (last.x + point.x) / 2
                result.append(Point(middle, last.y))
                result.append(Point(middle, point.y))
            else:
                result.append(Point(last.x, point.y))
        result.append(point)
    return result


# --------------------------------------------------------------------------- #
# Loop-back edges
# --------------------------------------------------------------------------- #


def _loop_indices(
    model: ProcessModel, graph: LayeredGraph, positions: Positions
) -> dict[str, int]:
    """Stagger loops that share a lane so their lines never coincide."""
    counters: dict[str, int] = {}
    indices: dict[str, int] = {}
    for flow_id in sorted(graph.back_edges):
        flow = model.flow(flow_id)
        lane = _loop_lane(model, flow.source_id, flow.target_id, positions)
        indices[flow_id] = counters.get(lane, 0)
        counters[lane] = indices[flow_id] + 1
    return indices


def _loop_lane(
    model: ProcessModel, source_id: str, target_id: str, positions: Positions
) -> str:
    source_lane = model.node(source_id).lane_id or ""
    target_lane = model.node(target_id).lane_id or ""
    if source_lane == target_lane and source_lane in positions.lane_bands:
        return source_lane
    return next(reversed(positions.lane_bands)) if positions.lane_bands else ""


def _route_loop(
    model: ProcessModel,
    flow_source_id: str,
    flow_target_id: str,
    source: Bounds,
    target: Bounds,
    positions: Positions,
    metrics: LayoutMetrics,
    index: int,
) -> list[Point]:
    """Run the edge back underneath the elements it skips."""
    lane = _loop_lane(model, flow_source_id, flow_target_id, positions)
    band = positions.lane_bands.get(lane)
    if band is None:
        baseline = positions.content_bottom + metrics.loop_clearance
    else:
        reserve = positions.loop_reserve.get(lane, 0.0)
        baseline = max(
            band.bottom - reserve + metrics.loop_clearance,
            max(source.bottom, target.bottom) + metrics.loop_clearance,
        )
    y = baseline + metrics.loop_spacing * index
    return [
        Point(source.center_x, source.bottom),
        Point(source.center_x, y),
        Point(target.center_x, y),
        Point(target.center_x, target.bottom),
    ]


# --------------------------------------------------------------------------- #
# Labels and clean-up
# --------------------------------------------------------------------------- #


def _simplify(points: list[Point]) -> list[Point]:
    """Drop duplicates and collinear midpoints."""
    cleaned: list[Point] = []
    for point in points:
        if cleaned and abs(point.x - cleaned[-1].x) < _EPSILON and abs(point.y - cleaned[-1].y) < _EPSILON:
            continue
        cleaned.append(point)
    if len(cleaned) < 3:
        return cleaned
    result = [cleaned[0]]
    for previous, current, following in zip(cleaned, cleaned[1:], cleaned[2:], strict=False):
        horizontal = abs(previous.y - current.y) < _EPSILON and abs(current.y - following.y) < _EPSILON
        vertical = abs(previous.x - current.x) < _EPSILON and abs(current.x - following.x) < _EPSILON
        if not (horizontal or vertical):
            result.append(current)
    result.append(cleaned[-1])
    return result


def _text_width(text: str, metrics: LayoutMetrics) -> float:
    return max(30.0, min(metrics.label_max_width, len(text) * metrics.label_char_width))


def label_bounds_for(
    bounds: Bounds, text: str, metrics: LayoutMetrics, *, below: bool
) -> Bounds:
    """Label box for a shape: events carry theirs below, gateways above."""
    width = _text_width(text, metrics)
    lines = max(1, int(len(text) * metrics.label_char_width // metrics.label_max_width) + 1)
    height = metrics.label_height * lines
    y = bounds.bottom + 6 if below else bounds.y - height - 6
    return Bounds(x=bounds.center_x - width / 2, y=y, width=width, height=height).rounded()


def _edge_label(points: list[Point], text: str, metrics: LayoutMetrics) -> Bounds:
    """Place a flow label next to the segment leaving the source element."""
    start, following = points[0], points[1]
    width = _text_width(text, metrics)
    if abs(start.y - following.y) < _EPSILON:  # horizontal first segment
        x = (start.x + following.x) / 2 - width / 2
        y = start.y - metrics.label_height - 4
    else:  # vertical first segment - put the label beside the line
        x = start.x + 6
        y = (start.y + following.y) / 2 - metrics.label_height / 2
    return Bounds(x=x, y=y, width=width, height=metrics.label_height).rounded()
