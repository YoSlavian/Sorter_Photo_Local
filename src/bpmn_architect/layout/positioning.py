"""Coordinate assignment: turning layers and orders into actual geometry.

Step three of the Sugiyama pipeline, and the step that decides whether a
diagram *looks* generated.  Two ideas do most of the work:

**Straight flows.**  Each node is pulled towards the median of the elements it
connects to, so the dominant path through the process comes out as a straight
horizontal line and branches fan out symmetrically around it.

**Exact separation.**  Pulling nodes around must never let them overlap.  The
one-dimensional problem "place these boxes as close as possible to their
preferred positions while keeping a minimum distance between neighbours" has an
exact solution — isotonic regression, solved here by pool-adjacent-violators in
linear time — so the layout is both tidy and provably overlap-free within a
column.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bpmn_architect.domain.model import ProcessModel
from bpmn_architect.layout.geometry import Bounds, LayoutMetrics, Point, size_for
from bpmn_architect.layout.ordering import Ordering
from bpmn_architect.layout.ranking import LayeredGraph

__all__ = ["Positions", "assign_positions"]

#: Odd count on purpose: the last sweep pulls every node towards its
#: *predecessors*, which straightens the main flow from left to right.
_REFINEMENT_SWEEPS = 7


@dataclass(slots=True)
class Positions:
    bounds: dict[str, Bounds] = field(default_factory=dict)
    virtual: dict[str, Point] = field(default_factory=dict)
    lane_bands: dict[str, Bounds] = field(default_factory=dict)
    #: Bottom of the area occupied by elements, excluding loop-back reserve.
    content_bottom: float = 0.0
    #: Free band reserved under each lane for loop-back edges.
    loop_reserve: dict[str, float] = field(default_factory=dict)

    def center_of(self, node_id: str) -> Point:
        if node_id in self.bounds:
            return self.bounds[node_id].center
        return self.virtual[node_id]

    def extent(self) -> Bounds:
        boxes = list(self.bounds.values()) or [Bounds(0, 0, 0, 0)]
        result = boxes[0]
        for box in boxes[1:]:
            result = result.union(box)
        return result


def assign_positions(
    graph: LayeredGraph,
    ordering: Ordering,
    *,
    metrics: LayoutMetrics,
    lane_order: list[str],
) -> Positions:
    """Compute bounds for every node, lane band and virtual bend point."""
    model = graph.model
    sizes = {node.id: size_for(node, metrics) for node in model.nodes}
    lane_of: dict[str, str] = {node.id: node.lane_id or "" for node in model.nodes}
    lane_of.update({v.id: v.lane_id or "" for v in graph.virtual_nodes.values()})
    lanes = lane_order or [""]

    column_x = _column_positions(
        graph, ordering, sizes, metrics, has_lanes=bool(lane_order) and lane_order != [""]
    )
    cells = _cells(ordering, lane_of, lanes)
    reserve = _loop_reserve(model, graph, lane_of, lanes, metrics)
    bands = _lane_bands(cells, sizes, lanes, reserve, metrics)

    centers = _initial_centers(cells, sizes, bands, reserve, metrics)
    _refine_centers(graph, ordering, cells, sizes, bands, reserve, centers, metrics)

    positions = Positions(lane_bands=bands, loop_reserve=reserve)
    for node in model.nodes:
        width, height = sizes[node.id]
        rank = graph.rank_of[node.id]
        positions.bounds[node.id] = Bounds(
            x=column_x[rank] + (_column_width(graph, ordering, sizes, rank, metrics) - width) / 2,
            y=centers[node.id] - height / 2,
            width=width,
            height=height,
        )
    for virtual in graph.virtual_nodes.values():
        rank = virtual.rank
        width = _column_width(graph, ordering, sizes, rank, metrics)
        positions.virtual[virtual.id] = Point(column_x[rank] + width / 2, centers[virtual.id])
    positions.content_bottom = max(
        (box.bottom for box in positions.bounds.values()), default=metrics.pool_origin_y
    )
    return positions


# --------------------------------------------------------------------------- #
# Columns
# --------------------------------------------------------------------------- #


def _column_width(
    graph: LayeredGraph,
    ordering: Ordering,
    sizes: dict[str, tuple[float, float]],
    rank: int,
    metrics: LayoutMetrics,
) -> float:
    if rank >= len(ordering.ranks):
        return metrics.virtual_width
    widths = [sizes[node_id][0] for node_id in ordering.ranks[rank] if node_id in sizes]
    return max(widths, default=metrics.virtual_width)


def _column_positions(
    graph: LayeredGraph,
    ordering: Ordering,
    sizes: dict[str, tuple[float, float]],
    metrics: LayoutMetrics,
    *,
    has_lanes: bool,
) -> list[float]:
    # A pool with lanes renders *two* vertical caption bands, the pool's and
    # the lane's; content that starts after only one of them collides with the
    # lane caption.
    captions = metrics.lane_header_width * (2 if has_lanes else 1)
    left = metrics.pool_origin_x + captions + metrics.lane_padding + _label_overhang(
        graph, ordering, sizes, metrics
    )
    positions: list[float] = []
    for rank in range(len(ordering.ranks)):
        positions.append(left)
        left += _column_width(graph, ordering, sizes, rank, metrics) + metrics.rank_gap
    return positions


# --------------------------------------------------------------------------- #
# Lane bands
# --------------------------------------------------------------------------- #


def _label_overhang(
    graph: LayeredGraph,
    ordering: Ordering,
    sizes: dict[str, tuple[float, float]],
    metrics: LayoutMetrics,
) -> float:
    """How far the first column's labels stick out to the left of their shapes.

    An event is 36px wide and its caption is drawn centred underneath it, so a
    named start event reaches well past its own outline. Without this the first
    caption lands on top of the lane caption.
    """
    if not ordering.ranks:
        return 0.0
    overhang = 0.0
    for node_id in ordering.ranks[0]:
        node = graph.model.get_node(node_id)
        if node is None or not node.name:
            continue
        width = sizes.get(node_id, (0.0, 0.0))[0]
        label_width = max(
            30.0, min(metrics.label_max_width, len(node.name) * metrics.label_char_width)
        )
        overhang = max(overhang, (label_width - width) / 2)
    return overhang


def _cells(
    ordering: Ordering, lane_of: dict[str, str], lanes: list[str]
) -> dict[tuple[str, int], list[str]]:
    """Group node ids by (lane, rank), preserving the computed order."""
    cells: dict[tuple[str, int], list[str]] = {
        (lane, rank): [] for lane in lanes for rank in range(len(ordering.ranks))
    }
    for rank, layer in enumerate(ordering.ranks):
        for node_id in layer:
            lane = lane_of.get(node_id, "")
            if lane not in lanes:
                lane = lanes[0]
            cells[(lane, rank)].append(node_id)
    return cells


def _stack_height(
    node_ids: list[str], sizes: dict[str, tuple[float, float]], metrics: LayoutMetrics
) -> float:
    if not node_ids:
        return 0.0
    heights = [sizes.get(node_id, (0.0, 0.0))[1] for node_id in node_ids]
    return sum(heights) + metrics.node_gap * (len(node_ids) - 1)


def _loop_reserve(
    model: ProcessModel,
    graph: LayeredGraph,
    lane_of: dict[str, str],
    lanes: list[str],
    metrics: LayoutMetrics,
) -> dict[str, float]:
    """Vertical space each lane needs underneath its elements for rework loops."""
    counts: dict[str, int] = dict.fromkeys(lanes, 0)
    for flow_id in graph.back_edges:
        flow = model.flow(flow_id)
        lane = lane_of.get(flow.source_id, "")
        if lane_of.get(flow.target_id, "") != lane:
            lane = lanes[-1]
        if lane not in counts:
            lane = lanes[-1]
        counts[lane] += 1
    return {
        lane: 0.0 if not count else metrics.loop_clearance + metrics.loop_spacing * count
        for lane, count in counts.items()
    }


def _lane_bands(
    cells: dict[tuple[str, int], list[str]],
    sizes: dict[str, tuple[float, float]],
    lanes: list[str],
    reserve: dict[str, float],
    metrics: LayoutMetrics,
) -> dict[str, Bounds]:
    bands: dict[str, Bounds] = {}
    top = metrics.pool_origin_y
    for lane in lanes:
        needed = max(
            (
                _stack_height(node_ids, sizes, metrics)
                for (cell_lane, _), node_ids in cells.items()
                if cell_lane == lane
            ),
            default=0.0,
        )
        height = max(metrics.lane_min_height, needed + 2 * metrics.lane_padding)
        height += reserve.get(lane, 0.0)
        bands[lane] = Bounds(x=metrics.pool_origin_x, y=top, width=0.0, height=height)
        top += height
    return bands


# --------------------------------------------------------------------------- #
# Vertical placement
# --------------------------------------------------------------------------- #


def _usable_band(
    band: Bounds, lane: str, reserve: dict[str, float], metrics: LayoutMetrics
) -> tuple[float, float]:
    low = band.y + metrics.lane_padding
    high = band.bottom - metrics.lane_padding - reserve.get(lane, 0.0)
    return low, max(low, high)


def _initial_centers(
    cells: dict[tuple[str, int], list[str]],
    sizes: dict[str, tuple[float, float]],
    bands: dict[str, Bounds],
    reserve: dict[str, float],
    metrics: LayoutMetrics,
) -> dict[str, float]:
    centers: dict[str, float] = {}
    for (lane, _rank), node_ids in cells.items():
        if not node_ids:
            continue
        low, high = _usable_band(bands[lane], lane, reserve, metrics)
        height = _stack_height(node_ids, sizes, metrics)
        cursor = (low + high) / 2 - height / 2
        for node_id in node_ids:
            node_height = sizes.get(node_id, (0.0, 0.0))[1]
            centers[node_id] = cursor + node_height / 2
            cursor += node_height + metrics.node_gap
    return centers


def _refine_centers(
    graph: LayeredGraph,
    ordering: Ordering,
    cells: dict[tuple[str, int], list[str]],
    sizes: dict[str, tuple[float, float]],
    bands: dict[str, Bounds],
    reserve: dict[str, float],
    centers: dict[str, float],
    metrics: LayoutMetrics,
) -> None:
    """Alternate median pulls with exact separation repair until stable."""
    neighbours = _neighbour_map(graph)
    for sweep in range(_REFINEMENT_SWEEPS):
        downward = sweep % 2 == 0
        rank_order = (
            range(len(ordering.ranks)) if downward else range(len(ordering.ranks) - 1, -1, -1)
        )
        for rank in rank_order:
            for lane, band in bands.items():
                node_ids = cells.get((lane, rank), [])
                if not node_ids:
                    continue
                desired = [
                    _median_of(
                        [
                            centers[other]
                            for other in neighbours[node_id][0 if downward else 1]
                            if other in centers
                        ],
                        centers[node_id],
                    )
                    for node_id in node_ids
                ]
                heights = [sizes.get(node_id, (0.0, 0.0))[1] for node_id in node_ids]
                low, high = _usable_band(band, lane, reserve, metrics)
                placed = place_with_separation(desired, heights, metrics.node_gap, low, high)
                for node_id, value in zip(node_ids, placed, strict=True):
                    centers[node_id] = value


def _neighbour_map(graph: LayeredGraph) -> dict[str, tuple[list[str], list[str]]]:
    """For each node: (predecessors, successors) in the layered graph."""
    neighbours: dict[str, tuple[list[str], list[str]]] = {
        node.id: ([], []) for node in graph.model.nodes
    }
    for virtual in graph.virtual_nodes.values():
        neighbours[virtual.id] = ([], [])
    for flow in graph.model.flows:
        if flow.id in graph.back_edges:
            continue
        chain = graph.chains.get(flow.id, [])
        path = [flow.source_id, *(virtual.id for virtual in chain), flow.target_id]
        for left, right in zip(path, path[1:], strict=False):
            neighbours[left][1].append(right)
            neighbours[right][0].append(left)
    return neighbours


def _median_of(values: list[float], fallback: float) -> float:
    if not values:
        return fallback
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def place_with_separation(
    desired: list[float],
    heights: list[float],
    gap: float,
    low: float,
    high: float,
) -> list[float]:
    """Place boxes near ``desired`` centres without overlap, inside ``[low, high]``.

    Solves ``min Σ (c_i - d_i)²`` subject to ``c_{i+1} - c_i ≥ (h_i + h_{i+1})/2 + gap``.
    Substituting out the separations turns the constraints into a monotonicity
    requirement, which pool-adjacent-violators solves exactly in ``O(n)``.
    """
    if not desired:
        return []
    offsets = [0.0]
    for index in range(1, len(desired)):
        separation = (heights[index - 1] + heights[index]) / 2 + gap
        offsets.append(offsets[index - 1] + separation)

    isotonic = _pool_adjacent_violators([d - o for d, o in zip(desired, offsets, strict=True)])
    centers = [value + offset for value, offset in zip(isotonic, offsets, strict=True)]

    top = centers[0] - heights[0] / 2
    bottom = centers[-1] + heights[-1] / 2
    shift = 0.0
    if top < low:
        shift = low - top
    elif bottom > high:
        shift = max(high - bottom, low - top)
    return [center + shift for center in centers]


def _pool_adjacent_violators(values: list[float]) -> list[float]:
    """Least-squares isotonic (non-decreasing) approximation of ``values``."""
    blocks: list[list[float]] = []  # [sum, count]
    for value in values:
        blocks.append([value, 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count
    result: list[float] = []
    for total, count in blocks:
        result.extend([total / count] * int(count))
    return result
