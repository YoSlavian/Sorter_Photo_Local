"""Reading BPMN 2.0 XML back into the domain model.

Files reaching this module come from three places: our own renderer, the
browser editor after a user dragged things around, and foreign tools such as
Camunda Modeler or Bizagi.  The last case drives the design:

* elements are matched by **namespace URI and local name**, never by prefix —
  every tool picks its own prefixes;
* the diagram-interchange section is optional; a file without it is imported
  and then laid out by our own engine;
* constructs the domain model does not represent (expanded sub-processes,
  boundary events, multiple pools) are imported as the closest supported
  element **with a diagnostic**, never dropped silently.

The last rule matters more than completeness: a user who opens a file must be
told what could not be preserved, rather than discovering it after saving.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from bpmn_architect.domain.model import (
    EventDefinition,
    Flow,
    Lane,
    Node,
    NodeKind,
    ProcessModel,
)
from bpmn_architect.errors import ParseError
from bpmn_architect.ids import sanitize_id
from bpmn_architect.layout.engine import Layout, layout_process
from bpmn_architect.layout.geometry import Bounds, Point
from bpmn_architect.rendering.bpmn_xml import BPMN_NS, BPMNDI_NS, DC_NS, DI_NS
from bpmn_architect.validation.diagnostics import Diagnostics

__all__ = ["BpmnImportResult", "import_bpmn", "read_bpmn"]

_KIND_BY_TAG = {kind.value: kind for kind in NodeKind}
_DEFINITION_BY_TAG = {
    definition.value: definition for definition in EventDefinition if not definition.is_none
}

#: Flow nodes the domain model cannot represent exactly, and what they become.
_SUBSTITUTIONS = {
    "boundaryEvent": (
        NodeKind.INTERMEDIATE_CATCH_EVENT,
        "boundary event {id!r} was imported as an intermediate event; "
        "its attachment to the activity is not preserved",
    ),
    "transaction": (
        NodeKind.SUB_PROCESS,
        "transaction {id!r} was imported as a sub-process",
    ),
    "adHocSubProcess": (
        NodeKind.SUB_PROCESS,
        "ad-hoc sub-process {id!r} was imported as a plain sub-process",
    ),
}

#: Elements that are legal BPMN but carry no flow semantics for us.
_IGNORED_TAGS = frozenset(
    {
        "documentation", "extensionElements", "laneSet", "sequenceFlow", "association",
        "textAnnotation", "dataObject", "dataObjectReference", "dataStoreReference",
        "ioSpecification", "property", "multiInstanceLoopCharacteristics",
        "standardLoopCharacteristics", "incoming", "outgoing", "auditing", "monitoring",
    }
)


@dataclass(slots=True)
class BpmnImportResult:
    """A model reconstructed from BPMN XML, plus what it cost."""

    model: ProcessModel
    layout: Layout
    diagnostics: Diagnostics = field(default_factory=Diagnostics)
    #: True when the file carried no usable diagram interchange section.
    layout_was_generated: bool = False


def read_bpmn(path: str) -> BpmnImportResult:
    """Import a BPMN file from disk."""
    with open(path, "rb") as handle:
        return import_bpmn(handle.read())


def import_bpmn(source: str | bytes) -> BpmnImportResult:
    """Import BPMN 2.0 XML into a :class:`ProcessModel` and its geometry."""
    try:
        root = ET.fromstring(source)
    except ET.ParseError as error:
        raise ParseError(f"the file is not well-formed XML: {error}") from error

    if root.tag != _q("definitions"):
        raise ParseError(
            f"expected a bpmn:definitions root element, found {_local(root.tag)!r}"
        )

    diagnostics = Diagnostics()
    process_element = _pick_process(root, diagnostics)
    if process_element is None:
        raise ParseError("the file contains no bpmn:process element")

    model = ProcessModel(
        id=sanitize_id(process_element.get("id") or "Process_1", fallback="Process_1"),
        name=process_element.get("name") or _participant_name(root, process_element),
        is_executable=process_element.get("isExecutable", "false") == "true",
    )

    lane_of = _read_lanes(process_element, model, diagnostics)
    _read_flow_nodes(process_element, model, lane_of, diagnostics)
    _read_sequence_flows(process_element, model, diagnostics)

    layout, generated = _read_layout(root, model, diagnostics)
    return BpmnImportResult(
        model=model, layout=layout, diagnostics=diagnostics, layout_was_generated=generated
    )


# --------------------------------------------------------------------------- #
# Semantic model
# --------------------------------------------------------------------------- #


def _pick_process(root: ET.Element, diagnostics: Diagnostics) -> ET.Element | None:
    processes = root.findall(_q("process"))
    if not processes:
        return None
    if len(processes) > 1:
        diagnostics.warning(
            "I301",
            f"the file declares {len(processes)} pools; only the first one is imported",
        )
    return processes[0]


def _participant_name(root: ET.Element, process: ET.Element) -> str:
    process_id = process.get("id")
    for participant in root.iter(_q("participant")):
        if participant.get("processRef") == process_id:
            return participant.get("name") or ""
    return ""


def _read_lanes(
    process: ET.Element, model: ProcessModel, diagnostics: Diagnostics
) -> dict[str, str]:
    """Create lanes and return a node id -> lane id index."""
    lane_of: dict[str, str] = {}
    order = 0
    for lane_set in process.findall(_q("laneSet")):
        for lane_element in lane_set.findall(_q("lane")):
            lane_id = sanitize_id(lane_element.get("id") or f"Lane_{order + 1}")
            if lane_element.find(_q("childLaneSet")) is not None:
                diagnostics.warning(
                    "I302",
                    f"lane {lane_id!r} contains nested lanes, which are flattened on import",
                    lane_id,
                )
            model.add_lane(
                Lane(id=lane_id, name=lane_element.get("name") or f"Lane {order + 1}", order=order)
            )
            for reference in lane_element.findall(_q("flowNodeRef")):
                if reference.text:
                    lane_of[reference.text.strip()] = lane_id
            order += 1
    return lane_of


def _read_flow_nodes(
    process: ET.Element,
    model: ProcessModel,
    lane_of: dict[str, str],
    diagnostics: Diagnostics,
) -> None:
    for element in process:
        tag = _local(element.tag)
        if tag in _IGNORED_TAGS:
            continue
        node_id = element.get("id")
        if not node_id:
            diagnostics.warning("I303", f"a {tag!r} element without an id was skipped")
            continue

        kind = _KIND_BY_TAG.get(tag)
        if kind is None:
            substitution = _SUBSTITUTIONS.get(tag)
            if substitution is None:
                diagnostics.warning(
                    "I304", f"unsupported element {tag!r} was imported as a task", node_id
                )
                kind = NodeKind.TASK
            else:
                kind, message = substitution
                diagnostics.warning("I305", message.format(id=node_id), node_id)

        if kind in {NodeKind.SUB_PROCESS, NodeKind.CALL_ACTIVITY} and any(
            _local(child.tag) in _KIND_BY_TAG for child in element
        ):
            diagnostics.warning(
                "I306",
                f"sub-process {node_id!r} was imported collapsed; its inner elements "
                f"are kept in the file but not shown on the canvas",
                node_id,
            )

        node = Node(
            id=sanitize_id(node_id),
            kind=kind,
            name=element.get("name") or "",
            lane_id=lane_of.get(node_id),
            event_definition=_event_definition(element, kind),
            documentation=_documentation(element),
        )
        _read_timer(element, node)
        try:
            model.add_node(node)
        except ValueError as error:
            diagnostics.warning("I307", str(error), node_id)


def _event_definition(element: ET.Element, kind: NodeKind) -> EventDefinition:
    if not kind.is_event:
        return EventDefinition.NONE
    for child in element:
        definition = _DEFINITION_BY_TAG.get(_local(child.tag))
        if definition is not None:
            return definition
    return EventDefinition.NONE


def _read_timer(element: ET.Element, node: Node) -> None:
    for child in element:
        if _local(child.tag) != EventDefinition.TIMER.value:
            continue
        for expression in child:
            value = (expression.text or "").strip()
            if value:
                node.attrs["timer"] = value
                return


def _documentation(element: ET.Element) -> str:
    documentation = element.find(_q("documentation"))
    return (documentation.text or "").strip() if documentation is not None else ""


def _read_sequence_flows(
    process: ET.Element, model: ProcessModel, diagnostics: Diagnostics
) -> None:
    defaults = {
        element.get("default"): element.get("id")
        for element in process
        if element.get("default")
    }
    for element in process.findall(_q("sequenceFlow")):
        flow_id = element.get("id")
        source = element.get("sourceRef")
        target = element.get("targetRef")
        if not (flow_id and source and target):
            diagnostics.warning("I308", "a sequence flow without endpoints was skipped", flow_id)
            continue
        if not (model.has_node(source) and model.has_node(target)):
            diagnostics.error(
                "E301",
                f"sequence flow {flow_id!r} references an element that is not in the file",
                flow_id,
            )
            continue
        condition = element.find(_q("conditionExpression"))
        condition_text = (condition.text or "").strip() if condition is not None else ""
        is_default = flow_id in defaults
        try:
            model.add_flow(
                Flow(
                    id=sanitize_id(flow_id),
                    source_id=source,
                    target_id=target,
                    name=element.get("name") or "",
                    condition="" if is_default else condition_text,
                    is_default=is_default,
                )
            )
        except ValueError as error:
            diagnostics.warning("I309", str(error), flow_id)


# --------------------------------------------------------------------------- #
# Diagram interchange
# --------------------------------------------------------------------------- #


def _read_layout(
    root: ET.Element, model: ProcessModel, diagnostics: Diagnostics
) -> tuple[Layout, bool]:
    layout = Layout()
    lane_ids = {lane.id for lane in model.lanes}

    for shape in root.iter(_q("BPMNShape", BPMNDI_NS)):
        element_id = shape.get("bpmnElement")
        bounds = _bounds(shape.find(_q("Bounds", DC_NS)))
        if element_id is None or bounds is None:
            continue
        if model.has_node(element_id):
            layout.shapes[element_id] = bounds
            label = shape.find(f"{_q('BPMNLabel', BPMNDI_NS)}/{_q('Bounds', DC_NS)}")
            label_bounds = _bounds(label)
            if label_bounds is not None:
                layout.node_labels[element_id] = label_bounds
        elif element_id in lane_ids:
            layout.lanes[element_id] = bounds
        elif layout.pool is None:
            layout.pool = bounds

    for edge in root.iter(_q("BPMNEdge", BPMNDI_NS)):
        flow_id = edge.get("bpmnElement")
        if flow_id is None:
            continue
        points = [
            Point(float(point.get("x", 0)), float(point.get("y", 0)))
            for point in edge.findall(_q("waypoint", DI_NS))
        ]
        if len(points) >= 2:
            layout.waypoints[flow_id] = points
        label = edge.find(f"{_q('BPMNLabel', BPMNDI_NS)}/{_q('Bounds', DC_NS)}")
        label_bounds = _bounds(label)
        if label_bounds is not None:
            layout.edge_labels[flow_id] = label_bounds

    missing = [node.id for node in model.nodes if node.id not in layout.shapes]
    if missing:
        if layout.shapes:
            diagnostics.warning(
                "I310",
                f"{len(missing)} element(s) had no position in the file; "
                f"the whole diagram was laid out again",
            )
        return layout_process(model), True
    return layout, False


def _bounds(element: ET.Element | None) -> Bounds | None:
    if element is None:
        return None
    try:
        return Bounds(
            x=float(element.get("x", 0)),
            y=float(element.get("y", 0)),
            width=float(element.get("width", 0)),
            height=float(element.get("height", 0)),
        )
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _q(tag: str, namespace: str = BPMN_NS) -> str:
    return f"{{{namespace}}}{tag}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
