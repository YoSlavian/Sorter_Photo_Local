"""Graph construction: IR block tree -> :class:`ProcessModel`.

The builder walks the block tree once, carrying a list of **open ports** — the
element outputs that still need a target.  A block consumes the ports handed to
it and returns the ports it leaves open.  Splits fan the ports out, joins
collect them back, and terminating blocks (end events, resolved jumps) return
none at all.

Because joins are created by the same code that created the matching split, an
unbalanced gateway pair is structurally impossible; the validator therefore
only has to check the things the builder cannot know, such as whether a jump
target actually exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bpmn_architect.domain.ir import (
    ActivityType,
    BranchType,
    EventPosition,
    EventTrigger,
    IRActivity,
    IRBranch,
    IRElement,
    IREvent,
    IRGoto,
    IRParallel,
    IRProcess,
    IRSequence,
)
from bpmn_architect.domain.model import (
    EventDefinition,
    Flow,
    Lane,
    Node,
    NodeKind,
    ProcessModel,
)
from bpmn_architect.ids import IdFactory, sanitize_id
from bpmn_architect.validation.diagnostics import Diagnostics

__all__ = ["BuildOptions", "BuildResult", "ProcessBuilder", "build_model"]


_ACTIVITY_KIND: dict[ActivityType, NodeKind] = {
    ActivityType.TASK: NodeKind.TASK,
    ActivityType.USER: NodeKind.USER_TASK,
    ActivityType.SERVICE: NodeKind.SERVICE_TASK,
    ActivityType.MANUAL: NodeKind.MANUAL_TASK,
    ActivityType.SCRIPT: NodeKind.SCRIPT_TASK,
    ActivityType.SEND: NodeKind.SEND_TASK,
    ActivityType.RECEIVE: NodeKind.RECEIVE_TASK,
    ActivityType.BUSINESS_RULE: NodeKind.BUSINESS_RULE_TASK,
    ActivityType.SUB_PROCESS: NodeKind.SUB_PROCESS,
    ActivityType.CALL: NodeKind.CALL_ACTIVITY,
}

_BRANCH_KIND: dict[BranchType, NodeKind] = {
    BranchType.EXCLUSIVE: NodeKind.EXCLUSIVE_GATEWAY,
    BranchType.INCLUSIVE: NodeKind.INCLUSIVE_GATEWAY,
    BranchType.EVENT_BASED: NodeKind.EVENT_BASED_GATEWAY,
}

_TRIGGER_DEFINITION: dict[EventTrigger, EventDefinition] = {
    EventTrigger.NONE: EventDefinition.NONE,
    EventTrigger.MESSAGE: EventDefinition.MESSAGE,
    EventTrigger.TIMER: EventDefinition.TIMER,
    EventTrigger.SIGNAL: EventDefinition.SIGNAL,
    EventTrigger.ERROR: EventDefinition.ERROR,
    EventTrigger.ESCALATION: EventDefinition.ESCALATION,
    EventTrigger.CONDITIONAL: EventDefinition.CONDITIONAL,
    EventTrigger.TERMINATE: EventDefinition.TERMINATE,
}

_ID_PREFIX: dict[NodeKind, str] = {
    NodeKind.START_EVENT: "StartEvent",
    NodeKind.END_EVENT: "EndEvent",
    NodeKind.INTERMEDIATE_CATCH_EVENT: "Event",
    NodeKind.INTERMEDIATE_THROW_EVENT: "Event",
}

_STEP_REFERENCE_RE = re.compile(
    r"(?:шаг\w*|этап\w*|пункт\w*|п\.|step|item)\s*[№#]?\s*(?P<number>\d+)", re.IGNORECASE
)
_STOP_WORDS = frozenset(
    {
        "к", "на", "в", "во", "и", "с", "со", "по", "для", "от", "до", "за",
        "шаг", "шагу", "этап", "этапу", "пункт", "the", "to", "a", "an", "of",
        "step", "back", "again", "назад", "обратно", "повторно",
    }
)
_DEFAULT_END_NAME = {"ru": "Процесс завершён", "en": "Process completed"}
_DEFAULT_START_NAME = {"ru": "Начало процесса", "en": "Process start"}


@dataclass(slots=True)
class BuildOptions:
    """Structural choices; none of them changes what the description means."""

    process_id: str = ""
    process_name: str = ""
    use_lanes: bool = True
    executable: bool = False
    #: Emit the source condition text as a ``conditionExpression``.
    emit_conditions: bool = True
    #: Drop gateways that ended up with a single input and a single output.
    collapse_degenerate_gateways: bool = True
    #: Terminate every path that would otherwise dangle with an end event.
    auto_close_open_ends: bool = True


@dataclass(slots=True)
class _Port:
    """An element output still waiting for a target."""

    node_id: str
    label: str = ""
    condition: str = ""
    is_default: bool = False


@dataclass(slots=True)
class BuildResult:
    model: ProcessModel
    diagnostics: Diagnostics = field(default_factory=Diagnostics)


class ProcessBuilder:
    """Turns an :class:`IRProcess` into a :class:`ProcessModel`."""

    def __init__(self, options: BuildOptions | None = None) -> None:
        self.options = options or BuildOptions()

    def build(self, process_ir: IRProcess) -> BuildResult:
        self._ir = process_ir
        self._ids = IdFactory()
        self._diagnostics = Diagnostics()
        self._anchors: dict[str, str] = {}
        self._activity_order: list[str] = []
        self._pending_jumps: list[tuple[list[_Port], IRGoto]] = []
        #: Ports left open by jumps that could not be resolved.
        self._orphan_ports: list[_Port] = []
        self._lane_ids: dict[str, str] = {}

        process_id = self.options.process_id or process_ir.options.get("id") or "Process_1"
        model = ProcessModel(
            id=sanitize_id(process_id, fallback="Process_1"),
            name=self.options.process_name or process_ir.name,
            is_executable=self.options.executable,
        )
        self._ids.reserve(model.id)
        self._model = model

        if self.options.use_lanes:
            self._create_lanes(process_ir)

        open_ports = self._emit_sequence(process_ir.root, [])
        self._resolve_jumps()
        self._finalize(open_ports)
        return BuildResult(model=model, diagnostics=self._diagnostics)

    # -- lanes ---------------------------------------------------------------

    def _create_lanes(self, process_ir: IRProcess) -> None:
        for order, name in enumerate(process_ir.lane_names()):
            if not name:
                continue
            lane = Lane(id=self._ids.next("Lane"), name=name, order=order)
            self._model.add_lane(lane)
            self._lane_ids[name.casefold()] = lane.id

    def _lane_for(self, actor: str | None) -> str | None:
        if not actor or not self.options.use_lanes:
            return None
        return self._lane_ids.get(actor.casefold())

    # -- sequence emission ---------------------------------------------------

    def _emit_sequence(self, sequence: IRSequence, incoming: list[_Port]) -> list[_Port]:
        ports = incoming
        for element in sequence:
            ports = self._emit_element(element, ports)
        return ports

    def _emit_element(self, element: IRElement, incoming: list[_Port]) -> list[_Port]:
        if isinstance(element, IRBranch):
            return self._emit_branch(element, incoming)
        if isinstance(element, IRParallel):
            return self._emit_parallel(element, incoming)
        if isinstance(element, IRGoto):
            self._pending_jumps.append((incoming, element))
            return []
        if isinstance(element, IREvent):
            return self._emit_event(element, incoming)
        if isinstance(element, IRActivity):
            return self._emit_activity(element, incoming)
        raise TypeError(f"unsupported IR element: {type(element).__name__}")

    def _emit_activity(self, element: IRActivity, incoming: list[_Port]) -> list[_Port]:
        kind = _ACTIVITY_KIND[element.activity_type]
        node = self._add_node(kind, element.text, element, prefix="Activity")
        self._activity_order.append(node.id)
        self._connect(incoming, node.id)
        return [_Port(node.id)]

    def _emit_event(self, element: IREvent, incoming: list[_Port]) -> list[_Port]:
        position = element.position
        if position is EventPosition.START and incoming:
            # A "start" in the middle of a flow is really an intermediate catch;
            # accepting it keeps sloppy descriptions usable.
            self._diagnostics.warning(
                "B101",
                f"start event {element.text!r} has inbound flow; modelled as an "
                f"intermediate catch event",
                line=element.line,
            )
            position = EventPosition.INTERMEDIATE_CATCH

        kind = {
            EventPosition.START: NodeKind.START_EVENT,
            EventPosition.END: NodeKind.END_EVENT,
            EventPosition.INTERMEDIATE_CATCH: NodeKind.INTERMEDIATE_CATCH_EVENT,
            EventPosition.INTERMEDIATE_THROW: NodeKind.INTERMEDIATE_THROW_EVENT,
        }[position]

        definition = _TRIGGER_DEFINITION[element.trigger]
        if kind is NodeKind.START_EVENT and definition in {
            EventDefinition.TERMINATE,
            EventDefinition.ERROR,
        }:
            definition = EventDefinition.NONE
        node = self._add_node(
            kind, element.text, element, prefix=_ID_PREFIX.get(kind, "Event"), definition=definition
        )
        if element.timer:
            node.attrs["timer"] = element.timer
        self._connect(incoming, node.id)
        if kind is NodeKind.END_EVENT:
            return []
        return [_Port(node.id)]

    def _emit_branch(self, element: IRBranch, incoming: list[_Port]) -> list[_Port]:
        kind = _BRANCH_KIND[element.branch_type]
        split = self._add_node(kind, element.text, element, prefix="Gateway")
        self._connect(incoming, split.id)

        surviving: list[_Port] = []
        for arm in element.arms:
            port = _Port(
                node_id=split.id,
                label=arm.label,
                condition=arm.condition if self.options.emit_conditions else "",
                is_default=arm.is_default,
            )
            surviving.extend(self._emit_sequence(arm.body, [port]))

        if not surviving:
            return []
        if len(surviving) == 1:
            return surviving
        join = self._add_node(kind, "", element, prefix="Gateway")
        self._connect(surviving, join.id)
        return [_Port(join.id)]

    def _emit_parallel(self, element: IRParallel, incoming: list[_Port]) -> list[_Port]:
        split = self._add_node(NodeKind.PARALLEL_GATEWAY, "", element, prefix="Gateway")
        self._connect(incoming, split.id)

        surviving: list[_Port] = []
        for branch in element.branches:
            surviving.extend(self._emit_sequence(branch, [_Port(split.id)]))

        if not surviving:
            return []
        if len(surviving) == 1:
            return surviving
        join = self._add_node(NodeKind.PARALLEL_GATEWAY, "", element, prefix="Gateway")
        self._connect(surviving, join.id)
        return [_Port(join.id)]

    # -- primitives ----------------------------------------------------------

    def _add_node(
        self,
        kind: NodeKind,
        name: str,
        element: IRElement | None = None,
        *,
        prefix: str = "Element",
        definition: EventDefinition = EventDefinition.NONE,
    ) -> Node:
        node = Node(
            id=self._ids.next(prefix),
            kind=kind,
            name=name.strip(),
            lane_id=self._lane_for(element.actor if element else None),
            event_definition=definition,
        )
        if element is not None:
            if element.source:
                node.attrs["source"] = element.source
            if element.line:
                node.attrs["line"] = str(element.line)
            if element.anchor:
                self._anchors[element.anchor.casefold()] = node.id
        self._model.add_node(node)
        return node

    def _connect(self, ports: list[_Port], target_id: str) -> None:
        for port in ports:
            source = self._model.node(port.node_id)
            is_default = port.is_default and source.kind.is_gateway
            self._model.add_flow(
                Flow(
                    id=self._ids.next("Flow"),
                    source_id=port.node_id,
                    target_id=target_id,
                    name=port.label,
                    condition="" if is_default else port.condition,
                    is_default=is_default,
                )
            )

    # -- jumps ---------------------------------------------------------------

    def _resolve_jumps(self) -> None:
        for ports, goto in self._pending_jumps:
            target_id = self._resolve_target(goto)
            if target_id is None:
                self._diagnostics.warning(
                    "B201",
                    f"could not resolve jump target {goto.target!r}; the branch is left open",
                    line=goto.line,
                )
                self._orphan_ports.extend(ports)
                continue
            for port in ports:
                if port.node_id == target_id:
                    self._diagnostics.warning(
                        "B202",
                        f"jump to {goto.target!r} would create a self-loop; ignored",
                        element_id=target_id,
                        line=goto.line,
                    )
                    continue
                self._connect([port], target_id)

    def _resolve_target(self, goto: IRGoto) -> str | None:
        raw = (goto.target or goto.text).strip()
        if not raw:
            return None
        anchor = raw.lstrip("@").casefold()
        if anchor in self._anchors:
            return self._anchors[anchor]
        if goto.anchor and goto.anchor.casefold() in self._anchors:
            return self._anchors[goto.anchor.casefold()]

        if match := _STEP_REFERENCE_RE.search(raw):
            index = int(match.group("number")) - 1
            if 0 <= index < len(self._activity_order):
                return self._activity_order[index]

        candidates = [
            node
            for node in self._model.nodes
            if node.name and (node.kind.is_activity or node.kind.is_event)
        ]
        target_tokens = _tokenize(raw)
        if not target_tokens:
            return None
        best_id, best_score = None, 0.0
        for node in candidates:
            score = _similarity(target_tokens, _tokenize(node.name))
            if score > best_score:
                best_id, best_score = node.id, score
        return best_id if best_score >= 0.5 else None

    # -- finalisation --------------------------------------------------------

    def _finalize(self, open_ports: list[_Port]) -> None:
        ports = [*open_ports, *self._orphan_ports]
        self._ensure_start_event()
        if self.options.collapse_degenerate_gateways:
            self._collapse_degenerate_gateways()
        self._close_open_ends(ports)
        self._assign_missing_lanes()

    def _ensure_start_event(self) -> None:
        if self._model.start_events:
            return
        roots = [
            node
            for node in self._model.nodes
            if not self._model.incoming(node.id) and not node.kind.is_end
        ]
        start = Node(
            id=self._ids.next("StartEvent"),
            kind=NodeKind.START_EVENT,
            name=_DEFAULT_START_NAME.get(self._ir.language, _DEFAULT_START_NAME["en"]),
            lane_id=roots[0].lane_id if roots else None,
        )
        self._model.add_node(start)
        targets = roots or [node for node in self._model.nodes if node.id != start.id][:1]
        for node in targets:
            self._model.add_flow(
                Flow(id=self._ids.next("Flow"), source_id=start.id, target_id=node.id)
            )
        self._diagnostics.info("B301", "no start event in the description; one was added", start.id)

    def _close_open_ends(self, ports: list[_Port]) -> None:
        if not self.options.auto_close_open_ends:
            return
        dangling = [
            node
            for node in self._model.nodes
            if not node.kind.is_end and not self._model.outgoing(node.id)
        ]
        if not dangling:
            return
        name = _DEFAULT_END_NAME.get(self._ir.language, _DEFAULT_END_NAME["en"])
        end = Node(
            id=self._ids.next("EndEvent"),
            kind=NodeKind.END_EVENT,
            name=name,
            lane_id=dangling[-1].lane_id,
        )
        self._model.add_node(end)
        labels = {port.node_id: port for port in ports}
        for node in dangling:
            port = labels.get(node.id, _Port(node.id))
            self._connect([_Port(node.id, port.label, port.condition, port.is_default)], end.id)
        self._diagnostics.info(
            "B302",
            f"{len(dangling)} open path(s) were terminated with an end event",
            end.id,
        )

    def _collapse_degenerate_gateways(self) -> None:
        """Remove gateways that neither split nor merge anything."""
        for node in list(self._model.nodes):
            if not node.kind.is_gateway:
                continue
            incoming = self._model.incoming(node.id)
            outgoing = self._model.outgoing(node.id)
            if len(incoming) != 1 or len(outgoing) != 1:
                continue
            inbound, outbound = incoming[0], outgoing[0]
            if inbound.source_id == outbound.target_id:
                continue
            merged = Flow(
                id=inbound.id,
                source_id=inbound.source_id,
                target_id=outbound.target_id,
                name=inbound.name or outbound.name,
                condition=inbound.condition or outbound.condition,
                is_default=inbound.is_default,
            )
            self._model.remove_node(node.id)
            self._model.add_flow(merged)

    def _assign_missing_lanes(self) -> None:
        if not self._model.has_lanes:
            return
        default_lane = self._model.lanes[0].id
        for _ in range(3):
            changed = False
            for node in self._model.nodes:
                if node.lane_id is not None:
                    continue
                lane = _first_lane(self._model.predecessors(node.id), self._model) or _first_lane(
                    self._model.successors(node.id), self._model
                )
                if lane is not None:
                    node.lane_id = lane
                    changed = True
            if not changed:
                break
        for node in self._model.nodes:
            if node.lane_id is None:
                node.lane_id = default_lane


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _first_lane(node_ids: list[str], model: ProcessModel) -> str | None:
    for node_id in node_ids:
        lane = model.node(node_id).lane_id
        if lane is not None:
            return lane
    return None


def _tokenize(text: str) -> set[str]:
    """Stem-ish tokens used for fuzzy jump-target matching."""
    words = re.findall(r"\w+", text.casefold())
    return {word[:5] for word in words if word not in _STOP_WORDS and len(word) > 2}


def _similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def build_model(process_ir: IRProcess, options: BuildOptions | None = None) -> BuildResult:
    """Convenience wrapper around :class:`ProcessBuilder`."""
    return ProcessBuilder(options).build(process_ir)
