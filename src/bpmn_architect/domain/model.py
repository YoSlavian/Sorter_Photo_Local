"""Semantic BPMN process model.

This module is the stable core of the system: a small, dependency-free,
in-memory representation of a BPMN 2.0 process graph.  Every other layer
(parsing, building, validation, layout, rendering) is expressed in terms of
the types declared here and in terms of nothing else.

The model deliberately stays *semantic*: it knows about flow nodes, sequence
flows and lanes, but nothing about coordinates.  Geometry lives in
:mod:`bpmn_architect.layout` and is attached at render time.  Keeping the two
apart is what allows the same process to be laid out by different strategies
without touching the graph itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "NodeKind",
    "EventDefinition",
    "GatewayDirection",
    "Node",
    "Flow",
    "Lane",
    "ProcessModel",
]


class NodeKind(Enum):
    """The BPMN element type of a flow node.

    The value is the local name of the BPMN 2.0 XML element, which lets the
    renderer stay a thin mapping instead of a large ``if``-ladder.
    """

    START_EVENT = "startEvent"
    END_EVENT = "endEvent"
    INTERMEDIATE_CATCH_EVENT = "intermediateCatchEvent"
    INTERMEDIATE_THROW_EVENT = "intermediateThrowEvent"

    TASK = "task"
    USER_TASK = "userTask"
    SERVICE_TASK = "serviceTask"
    SCRIPT_TASK = "scriptTask"
    MANUAL_TASK = "manualTask"
    SEND_TASK = "sendTask"
    RECEIVE_TASK = "receiveTask"
    BUSINESS_RULE_TASK = "businessRuleTask"

    SUB_PROCESS = "subProcess"
    CALL_ACTIVITY = "callActivity"

    EXCLUSIVE_GATEWAY = "exclusiveGateway"
    PARALLEL_GATEWAY = "parallelGateway"
    INCLUSIVE_GATEWAY = "inclusiveGateway"
    EVENT_BASED_GATEWAY = "eventBasedGateway"

    # -- category predicates -------------------------------------------------

    @property
    def is_event(self) -> bool:
        return self in _EVENT_KINDS

    @property
    def is_gateway(self) -> bool:
        return self in _GATEWAY_KINDS

    @property
    def is_activity(self) -> bool:
        return self in _ACTIVITY_KINDS

    @property
    def is_start(self) -> bool:
        return self is NodeKind.START_EVENT

    @property
    def is_end(self) -> bool:
        return self is NodeKind.END_EVENT


_EVENT_KINDS = frozenset(
    {
        NodeKind.START_EVENT,
        NodeKind.END_EVENT,
        NodeKind.INTERMEDIATE_CATCH_EVENT,
        NodeKind.INTERMEDIATE_THROW_EVENT,
    }
)
_GATEWAY_KINDS = frozenset(
    {
        NodeKind.EXCLUSIVE_GATEWAY,
        NodeKind.PARALLEL_GATEWAY,
        NodeKind.INCLUSIVE_GATEWAY,
        NodeKind.EVENT_BASED_GATEWAY,
    }
)
_ACTIVITY_KINDS = frozenset(
    {
        NodeKind.TASK,
        NodeKind.USER_TASK,
        NodeKind.SERVICE_TASK,
        NodeKind.SCRIPT_TASK,
        NodeKind.MANUAL_TASK,
        NodeKind.SEND_TASK,
        NodeKind.RECEIVE_TASK,
        NodeKind.BUSINESS_RULE_TASK,
        NodeKind.SUB_PROCESS,
        NodeKind.CALL_ACTIVITY,
    }
)


class EventDefinition(Enum):
    """Optional event trigger attached to an event node."""

    NONE = "none"
    MESSAGE = "messageEventDefinition"
    TIMER = "timerEventDefinition"
    SIGNAL = "signalEventDefinition"
    ERROR = "errorEventDefinition"
    ESCALATION = "escalationEventDefinition"
    CONDITIONAL = "conditionalEventDefinition"
    TERMINATE = "terminateEventDefinition"

    @property
    def is_none(self) -> bool:
        return self is EventDefinition.NONE


class GatewayDirection(Enum):
    """How a gateway is used in the graph.

    Computed rather than declared; it drives validation and label placement.
    """

    UNSPECIFIED = "Unspecified"
    DIVERGING = "Diverging"
    CONVERGING = "Converging"
    MIXED = "Mixed"


@dataclass(slots=True)
class Node:
    """A BPMN flow node."""

    id: str
    kind: NodeKind
    name: str = ""
    lane_id: str | None = None
    event_definition: EventDefinition = EventDefinition.NONE
    documentation: str = ""
    #: Free-form annotations produced upstream (source sentence, timer value, ...).
    attrs: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Node.id must not be empty")
        if not self.kind.is_event and not self.event_definition.is_none:
            raise ValueError(
                f"event definition {self.event_definition.value!r} is only valid on events, "
                f"not on {self.kind.value!r}"
            )

    @property
    def label(self) -> str:
        return self.name or self.id


@dataclass(slots=True)
class Flow:
    """A BPMN sequence flow (a directed edge between two flow nodes)."""

    id: str
    source_id: str
    target_id: str
    name: str = ""
    condition: str = ""
    is_default: bool = False

    def __post_init__(self) -> None:
        if self.source_id == self.target_id:
            raise ValueError(f"sequence flow {self.id!r} must not be a self-loop")
        if self.is_default and self.condition:
            raise ValueError(
                f"sequence flow {self.id!r} cannot be a default flow and carry a condition"
            )

    @property
    def is_conditional(self) -> bool:
        return bool(self.condition)


@dataclass(slots=True)
class Lane:
    """A lane of the (single) pool — normally one participating role."""

    id: str
    name: str
    order: int = 0


class ProcessModel:
    """A BPMN process: flow nodes, sequence flows and optional lanes.

    The container owns identity and referential integrity.  Nodes and flows are
    kept in insertion order, which makes generated XML stable and diffable — a
    property the golden-file tests rely on.
    """

    def __init__(self, id: str = "Process_1", name: str = "", *, is_executable: bool = False):
        self.id = id
        self.name = name
        self.is_executable = is_executable
        self._nodes: dict[str, Node] = {}
        self._flows: dict[str, Flow] = {}
        self._lanes: dict[str, Lane] = {}
        self._outgoing: dict[str, list[str]] = {}
        self._incoming: dict[str, list[str]] = {}

    # -- construction --------------------------------------------------------

    def add_node(self, node: Node) -> Node:
        if node.id in self._nodes:
            raise ValueError(f"duplicate node id {node.id!r}")
        if node.lane_id is not None and node.lane_id not in self._lanes:
            raise ValueError(f"node {node.id!r} references unknown lane {node.lane_id!r}")
        self._nodes[node.id] = node
        self._outgoing.setdefault(node.id, [])
        self._incoming.setdefault(node.id, [])
        return node

    def add_flow(self, flow: Flow) -> Flow:
        if flow.id in self._flows:
            raise ValueError(f"duplicate flow id {flow.id!r}")
        for ref in (flow.source_id, flow.target_id):
            if ref not in self._nodes:
                raise ValueError(f"sequence flow {flow.id!r} references unknown node {ref!r}")
        self._flows[flow.id] = flow
        self._outgoing[flow.source_id].append(flow.id)
        self._incoming[flow.target_id].append(flow.id)
        return flow

    def add_lane(self, lane: Lane) -> Lane:
        if lane.id in self._lanes:
            raise ValueError(f"duplicate lane id {lane.id!r}")
        self._lanes[lane.id] = lane
        return lane

    def remove_flow(self, flow_id: str) -> None:
        flow = self._flows.pop(flow_id)
        self._outgoing[flow.source_id].remove(flow_id)
        self._incoming[flow.target_id].remove(flow_id)

    def remove_node(self, node_id: str) -> None:
        """Remove a node together with every flow that touches it."""
        for flow_id in [*self._outgoing.get(node_id, []), *self._incoming.get(node_id, [])]:
            if flow_id in self._flows:
                self.remove_flow(flow_id)
        self._nodes.pop(node_id, None)
        self._outgoing.pop(node_id, None)
        self._incoming.pop(node_id, None)

    # -- access --------------------------------------------------------------

    @property
    def nodes(self) -> list[Node]:
        return list(self._nodes.values())

    @property
    def flows(self) -> list[Flow]:
        return list(self._flows.values())

    @property
    def lanes(self) -> list[Lane]:
        return sorted(self._lanes.values(), key=lambda lane: (lane.order, lane.id))

    @property
    def has_lanes(self) -> bool:
        return bool(self._lanes)

    def node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def flow(self, flow_id: str) -> Flow:
        return self._flows[flow_id]

    def lane(self, lane_id: str) -> Lane:
        return self._lanes[lane_id]

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def outgoing(self, node_id: str) -> list[Flow]:
        return [self._flows[f] for f in self._outgoing.get(node_id, [])]

    def incoming(self, node_id: str) -> list[Flow]:
        return [self._flows[f] for f in self._incoming.get(node_id, [])]

    def successors(self, node_id: str) -> list[str]:
        return [f.target_id for f in self.outgoing(node_id)]

    def predecessors(self, node_id: str) -> list[str]:
        return [f.source_id for f in self.incoming(node_id)]

    def nodes_of_kind(self, *kinds: NodeKind) -> list[Node]:
        wanted = frozenset(kinds)
        return [n for n in self._nodes.values() if n.kind in wanted]

    @property
    def start_events(self) -> list[Node]:
        return self.nodes_of_kind(NodeKind.START_EVENT)

    @property
    def end_events(self) -> list[Node]:
        return self.nodes_of_kind(NodeKind.END_EVENT)

    def nodes_in_lane(self, lane_id: str) -> list[Node]:
        return [n for n in self._nodes.values() if n.lane_id == lane_id]

    def gateway_direction(self, node_id: str) -> GatewayDirection:
        out_count = len(self._outgoing.get(node_id, []))
        in_count = len(self._incoming.get(node_id, []))
        if out_count > 1 and in_count > 1:
            return GatewayDirection.MIXED
        if out_count > 1:
            return GatewayDirection.DIVERGING
        if in_count > 1:
            return GatewayDirection.CONVERGING
        return GatewayDirection.UNSPECIFIED

    # -- traversal -----------------------------------------------------------

    def reachable_from(self, roots: Iterable[str]) -> set[str]:
        """Forward closure over sequence flows."""
        seen: set[str] = set()
        stack = [r for r in roots if r in self._nodes]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.successors(current))
        return seen

    def reaching(self, targets: Iterable[str]) -> set[str]:
        """Backward closure over sequence flows."""
        seen: set[str] = set()
        stack = [t for t in targets if t in self._nodes]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.predecessors(current))
        return seen

    def __iter__(self) -> Iterator[Node]:
        return iter(self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ProcessModel {self.id!r} nodes={len(self._nodes)} "
            f"flows={len(self._flows)} lanes={len(self._lanes)}>"
        )
