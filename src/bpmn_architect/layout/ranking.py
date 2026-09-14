"""Layer assignment: cycle breaking, longest-path ranking, virtual nodes.

Step one of the Sugiyama pipeline.  A BPMN process is a directed graph that is
almost always *almost* acyclic: the only cycles come from rework loops, which
are semantically "go back", not "flow forward".  Detecting them explicitly lets
the router draw them the way modellers draw them by hand — as a line running
back underneath the flow — instead of squeezing them into the layer structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bpmn_architect.domain.model import ProcessModel

__all__ = ["LayeredGraph", "VirtualNode", "assign_layers"]


@dataclass(slots=True)
class VirtualNode:
    """A placeholder occupying a rank so that a long edge has room to pass."""

    id: str
    rank: int
    flow_id: str
    lane_id: str | None = None
    order: int = 0


@dataclass(slots=True)
class LayeredGraph:
    """The result of layer assignment."""

    model: ProcessModel
    rank_of: dict[str, int] = field(default_factory=dict)
    #: Flow ids that point backwards (rework loops); routed separately.
    back_edges: set[str] = field(default_factory=set)
    #: Chains of virtual nodes, keyed by flow id, ordered source -> target.
    chains: dict[str, list[VirtualNode]] = field(default_factory=dict)
    virtual_nodes: dict[str, VirtualNode] = field(default_factory=dict)

    @property
    def rank_count(self) -> int:
        return max(self.rank_of.values(), default=-1) + 1

    def nodes_in_rank(self, rank: int) -> list[str]:
        return [node_id for node_id, value in self.rank_of.items() if value == rank]

    def is_virtual(self, node_id: str) -> bool:
        return node_id in self.virtual_nodes


def assign_layers(model: ProcessModel) -> LayeredGraph:
    """Assign every node to a layer and prepare long-edge placeholders."""
    graph = LayeredGraph(model=model)
    graph.back_edges = _find_back_edges(model)
    graph.rank_of = _longest_path_ranking(model, graph.back_edges)
    _insert_virtual_nodes(model, graph)
    return graph


def _find_back_edges(model: ProcessModel) -> set[str]:
    """Iterative DFS; an edge to a node on the current stack closes a cycle."""
    back_edges: set[str] = set()
    state: dict[str, int] = {}  # 0 = visiting, 1 = done
    roots = [node.id for node in model.start_events] or [
        node.id for node in model.nodes if not model.incoming(node.id)
    ]
    if not roots and model.nodes:
        roots = [model.nodes[0].id]

    for root in [*roots, *(node.id for node in model.nodes)]:
        if root in state:
            continue
        stack: list[tuple[str, list[str]]] = [(root, [f.id for f in model.outgoing(root)])]
        state[root] = 0
        while stack:
            node_id, pending = stack[-1]
            if not pending:
                state[node_id] = 1
                stack.pop()
                continue
            flow = model.flow(pending.pop())
            target = flow.target_id
            if state.get(target) == 0:
                back_edges.add(flow.id)
            elif target not in state:
                state[target] = 0
                stack.append((target, [f.id for f in model.outgoing(target)]))
    return back_edges


def _longest_path_ranking(model: ProcessModel, back_edges: set[str]) -> dict[str, int]:
    """Rank = length of the longest path from a source, computed topologically."""
    forward: dict[str, list[str]] = {node.id: [] for node in model.nodes}
    in_degree: dict[str, int] = {node.id: 0 for node in model.nodes}
    for flow in model.flows:
        if flow.id in back_edges:
            continue
        forward[flow.source_id].append(flow.target_id)
        in_degree[flow.target_id] += 1

    # Start events first keeps the left-hand column semantically meaningful.
    queue = [node.id for node in model.start_events if in_degree[node.id] == 0]
    queue += [
        node.id
        for node in model.nodes
        if in_degree[node.id] == 0 and node.id not in queue
    ]
    rank = dict.fromkeys(in_degree, 0)
    order: list[str] = []
    while queue:
        node_id = queue.pop(0)
        order.append(node_id)
        for target in forward[node_id]:
            rank[target] = max(rank[target], rank[node_id] + 1)
            in_degree[target] -= 1
            if in_degree[target] == 0:
                queue.append(target)

    # Any node left over sits on a cycle the DFS could not break (defensive).
    for node in model.nodes:
        if node.id not in order:
            sources = [rank.get(p, 0) for p in model.predecessors(node.id)]
            rank[node.id] = max(sources, default=0) + 1
    return rank


def _insert_virtual_nodes(model: ProcessModel, graph: LayeredGraph) -> None:
    """Give every long forward edge a placeholder in each rank it crosses."""
    for flow in model.flows:
        if flow.id in graph.back_edges:
            continue
        source_rank = graph.rank_of[flow.source_id]
        target_rank = graph.rank_of[flow.target_id]
        if target_rank - source_rank <= 1:
            continue
        source_lane = model.node(flow.source_id).lane_id
        target_lane = model.node(flow.target_id).lane_id
        span = target_rank - source_rank
        chain: list[VirtualNode] = []
        for offset, rank in enumerate(range(source_rank + 1, target_rank), start=1):
            lane = source_lane if offset <= span / 2 else target_lane
            virtual = VirtualNode(
                id=f"_v_{flow.id}_{rank}", rank=rank, flow_id=flow.id, lane_id=lane
            )
            chain.append(virtual)
            graph.virtual_nodes[virtual.id] = virtual
            graph.rank_of[virtual.id] = rank
        graph.chains[flow.id] = chain
