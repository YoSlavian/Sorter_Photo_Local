"""Crossing minimisation: ordering the nodes inside each layer.

Step two of the Sugiyama pipeline.  Node order within a layer decides how many
edge crossings the reader has to untangle, and crossings are the single
strongest predictor of how hard a diagram is to follow.

The implementation is the classical **median heuristic with adjacent-exchange
refinement**, run in alternating sweeps and keeping the best arrangement seen.
Two BPMN-specific constraints are layered on top:

* nodes may not leave their swimlane, so ordering happens *within* lane groups
  and lanes keep their declared order;
* the arrangement is only accepted when it strictly improves, which keeps the
  output deterministic — the same description always yields the same diagram.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bpmn_architect.layout.ranking import LayeredGraph

__all__ = ["Ordering", "order_nodes"]

_MAX_SWEEPS = 8


@dataclass(slots=True)
class Ordering:
    """Node ids per rank, ordered top to bottom."""

    ranks: list[list[str]] = field(default_factory=list)

    def index_of(self, node_id: str) -> int:
        for layer in self.ranks:
            if node_id in layer:
                return layer.index(node_id)
        return 0

    def positions(self) -> dict[str, int]:
        return {
            node_id: index for layer in self.ranks for index, node_id in enumerate(layer)
        }


def order_nodes(graph: LayeredGraph, lane_index: dict[str | None, int]) -> Ordering:
    """Order each layer so that edge crossings are (heuristically) minimal."""
    ranks = _initial_order(graph, lane_index)
    segments = _segments(graph)
    lane_of = _lane_of(graph)

    best = [list(layer) for layer in ranks]
    best_crossings = _count_all_crossings(best, segments)

    current = [list(layer) for layer in ranks]
    for sweep in range(_MAX_SWEEPS):
        downward = sweep % 2 == 0
        _median_sweep(current, segments, lane_of, lane_index, downward=downward)
        _transpose(current, segments, lane_of)
        crossings = _count_all_crossings(current, segments)
        if crossings < best_crossings:
            best, best_crossings = [list(layer) for layer in current], crossings
        if best_crossings == 0:
            break
    return Ordering(ranks=best)


# --------------------------------------------------------------------------- #
# Graph views
# --------------------------------------------------------------------------- #


def _lane_of(graph: LayeredGraph) -> dict[str, str | None]:
    lanes: dict[str, str | None] = {
        node.id: node.lane_id for node in graph.model.nodes
    }
    lanes.update({virtual.id: virtual.lane_id for virtual in graph.virtual_nodes.values()})
    return lanes


def _segments(graph: LayeredGraph) -> dict[int, list[tuple[str, str]]]:
    """Edges split per adjacent rank pair, long edges routed via their chain."""
    segments: dict[int, list[tuple[str, str]]] = {}
    for flow in graph.model.flows:
        if flow.id in graph.back_edges:
            continue
        chain = graph.chains.get(flow.id, [])
        path = [flow.source_id, *(virtual.id for virtual in chain), flow.target_id]
        for left, right in zip(path, path[1:], strict=False):
            rank = graph.rank_of[left]
            segments.setdefault(rank, []).append((left, right))
    return segments


def _initial_order(graph: LayeredGraph, lane_index: dict[str | None, int]) -> list[list[str]]:
    """Breadth-first seeding: follows the reading order of the description."""
    ranks: list[list[str]] = [[] for _ in range(graph.rank_count)]
    seen: set[str] = set()
    queue = [node.id for node in graph.model.start_events]
    queue += [node.id for node in graph.model.nodes if not graph.model.incoming(node.id)]
    queue += [node.id for node in graph.model.nodes]

    lane_of = _lane_of(graph)
    while queue:
        node_id = queue.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        ranks[graph.rank_of[node_id]].append(node_id)
        for flow in graph.model.outgoing(node_id):
            for virtual in graph.chains.get(flow.id, []):
                if virtual.id not in seen:
                    seen.add(virtual.id)
                    ranks[virtual.rank].append(virtual.id)
            if flow.id not in graph.back_edges:
                queue.append(flow.target_id)
    for virtual in graph.virtual_nodes.values():
        if virtual.id not in seen:
            seen.add(virtual.id)
            ranks[virtual.rank].append(virtual.id)
    for layer in ranks:
        layer.sort(key=lambda node_id: lane_index.get(lane_of.get(node_id), 0))
    return ranks


# --------------------------------------------------------------------------- #
# Heuristics
# --------------------------------------------------------------------------- #


def _median_sweep(
    ranks: list[list[str]],
    segments: dict[int, list[tuple[str, str]]],
    lane_of: dict[str, str | None],
    lane_index: dict[str | None, int],
    *,
    downward: bool,
) -> None:
    order = range(1, len(ranks)) if downward else range(len(ranks) - 2, -1, -1)
    for rank in order:
        neighbour_rank = rank - 1 if downward else rank + 1
        positions = {node_id: index for index, node_id in enumerate(ranks[neighbour_rank])}
        pairs = segments.get(min(rank, neighbour_rank), [])
        medians: dict[str, float] = {}
        for node_id in ranks[rank]:
            if downward:
                neighbours = [positions[left] for left, right in pairs if right == node_id]
            else:
                neighbours = [positions[right] for left, right in pairs if left == node_id]
            medians[node_id] = _median([value for value in neighbours if value is not None])

        current = {node_id: index for index, node_id in enumerate(ranks[rank])}
        ranks[rank].sort(
            key=lambda node_id: (
                lane_index.get(lane_of.get(node_id), 0),
                medians[node_id] if medians[node_id] >= 0 else current[node_id],
                current[node_id],
            )
        )


def _median(values: list[int]) -> float:
    if not values:
        return -1.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _transpose(
    ranks: list[list[str]],
    segments: dict[int, list[tuple[str, str]]],
    lane_of: dict[str, str | None],
) -> None:
    """Swap adjacent same-lane neighbours while that reduces crossings."""
    improved = True
    guard = 0
    while improved and guard < 4:
        improved = False
        guard += 1
        for rank, layer in enumerate(ranks):
            for index in range(len(layer) - 1):
                left, right = layer[index], layer[index + 1]
                if lane_of.get(left) != lane_of.get(right):
                    continue
                before = _local_crossings(ranks, segments, rank)
                layer[index], layer[index + 1] = right, left
                after = _local_crossings(ranks, segments, rank)
                if after < before:
                    improved = True
                else:
                    layer[index], layer[index + 1] = left, right


def _local_crossings(
    ranks: list[list[str]], segments: dict[int, list[tuple[str, str]]], rank: int
) -> int:
    total = 0
    if rank > 0:
        total += _count_crossings(ranks[rank - 1], ranks[rank], segments.get(rank - 1, []))
    if rank + 1 < len(ranks):
        total += _count_crossings(ranks[rank], ranks[rank + 1], segments.get(rank, []))
    return total


def _count_all_crossings(
    ranks: list[list[str]], segments: dict[int, list[tuple[str, str]]]
) -> int:
    return sum(
        _count_crossings(ranks[rank], ranks[rank + 1], segments.get(rank, []))
        for rank in range(len(ranks) - 1)
    )


def _count_crossings(
    upper: list[str], lower: list[str], pairs: list[tuple[str, str]]
) -> int:
    """Count pairwise inversions; O(E^2) is ample for process-sized graphs."""
    upper_index = {node_id: index for index, node_id in enumerate(upper)}
    lower_index = {node_id: index for index, node_id in enumerate(lower)}
    edges = [
        (upper_index[left], lower_index[right])
        for left, right in pairs
        if left in upper_index and right in lower_index
    ]
    crossings = 0
    for index, (u1, v1) in enumerate(edges):
        for u2, v2 in edges[index + 1 :]:
            if (u1 - u2) * (v1 - v2) < 0:
                crossings += 1
    return crossings
