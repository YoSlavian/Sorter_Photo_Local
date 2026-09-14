"""BPMN 2.0 XML serialisation, including BPMN-DI diagram interchange.

The output is a complete ``bpmn:definitions`` document: the *semantic* model
(what the process means) plus the *diagram interchange* section (where every
shape and waypoint sits).  Both halves matter — a file without DI opens as an
empty canvas in every modeller, which is exactly the "not editable afterwards"
failure mode this tool exists to avoid.

Two details are easy to get wrong and are handled explicitly here:

* **child order.**  The BPMN XSD prescribes sequences, e.g. ``incoming`` and
  ``outgoing`` before any ``eventDefinition``.  Tools are forgiving, validators
  are not.
* **lanes.**  As soon as a process has roles it must be wrapped in a
  collaboration with a participant, and the diagram plane then references the
  collaboration rather than the process.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from xml.dom import minidom

from bpmn_architect.domain.model import EventDefinition, Flow, Node, NodeKind, ProcessModel
from bpmn_architect.layout.engine import Layout
from bpmn_architect.layout.geometry import Bounds

__all__ = ["BpmnRenderOptions", "BpmnRenderer", "render_bpmn"]

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

_NAMESPACES = {
    "bpmn": BPMN_NS,
    "bpmndi": BPMNDI_NS,
    "dc": DC_NS,
    "di": DI_NS,
    "xsi": XSI_NS,
}

EXPORTER_NAME = "bpmn-architect"
EXPORTER_VERSION = "1.0.0"

#: Events whose trigger is thrown rather than caught.
_THROWING_KINDS = frozenset({NodeKind.END_EVENT, NodeKind.INTERMEDIATE_THROW_EVENT})
_RECURRING_HINTS = ("кажд", "ежед", "ежене", "ежемес", "ежегод", "every", "daily", "weekly", "monthly")


@dataclass(slots=True)
class BpmnRenderOptions:
    target_namespace: str = "http://bpmn.io/schema/bpmn"
    definitions_id: str = "Definitions_1"
    collaboration_id: str = "Collaboration_1"
    participant_id: str = "Participant_1"
    diagram_id: str = "BPMNDiagram_1"
    plane_id: str = "BPMNPlane_1"
    #: Copy the originating sentence into ``bpmn:documentation`` for traceability.
    include_source_documentation: bool = True
    pretty: bool = True


class BpmnRenderer:
    """Serialises a model plus its layout into BPMN 2.0 XML."""

    def __init__(self, options: BpmnRenderOptions | None = None) -> None:
        self.options = options or BpmnRenderOptions()

    def render(self, model: ProcessModel, layout: Layout) -> str:
        for prefix, uri in _NAMESPACES.items():
            ET.register_namespace(prefix, uri)

        definitions = ET.Element(
            _q(BPMN_NS, "definitions"),
            {
                "id": self.options.definitions_id,
                "targetNamespace": self.options.target_namespace,
                "exporter": EXPORTER_NAME,
                "exporterVersion": EXPORTER_VERSION,
            },
        )
        if model.has_lanes:
            self._collaboration(definitions, model)
        self._process(definitions, model)
        self._diagram(definitions, model, layout)

        xml = ET.tostring(definitions, encoding="unicode")
        if not self.options.pretty:
            return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n'
        pretty = minidom.parseString(xml).toprettyxml(indent="  ", encoding="UTF-8")
        return _tidy(pretty.decode("utf-8"))

    # -- semantic model ------------------------------------------------------

    def _collaboration(self, parent: ET.Element, model: ProcessModel) -> None:
        collaboration = ET.SubElement(
            parent, _q(BPMN_NS, "collaboration"), {"id": self.options.collaboration_id}
        )
        ET.SubElement(
            collaboration,
            _q(BPMN_NS, "participant"),
            {
                "id": self.options.participant_id,
                "name": model.name or model.id,
                "processRef": model.id,
            },
        )

    def _process(self, parent: ET.Element, model: ProcessModel) -> None:
        attributes = {"id": model.id, "isExecutable": _bool(model.is_executable)}
        if model.name:
            attributes["name"] = model.name
        process = ET.SubElement(parent, _q(BPMN_NS, "process"), attributes)

        if model.has_lanes:
            lane_set = ET.SubElement(process, _q(BPMN_NS, "laneSet"), {"id": f"LaneSet_{model.id}"})
            for lane in model.lanes:
                element = ET.SubElement(
                    lane_set, _q(BPMN_NS, "lane"), {"id": lane.id, "name": lane.name}
                )
                for node in model.nodes_in_lane(lane.id):
                    reference = ET.SubElement(element, _q(BPMN_NS, "flowNodeRef"))
                    reference.text = node.id

        for node in model.nodes:
            self._flow_node(process, model, node)
        for flow in model.flows:
            self._sequence_flow(process, flow)

    def _flow_node(self, parent: ET.Element, model: ProcessModel, node: Node) -> None:
        attributes: dict[str, str] = {"id": node.id}
        if node.name:
            attributes["name"] = node.name
        if node.kind.is_gateway:
            default = next((f for f in model.outgoing(node.id) if f.is_default), None)
            if default is not None:
                attributes["default"] = default.id
        element = ET.SubElement(parent, _q(BPMN_NS, node.kind.value), attributes)

        documentation = node.documentation or (
            node.attrs.get("source", "") if self.options.include_source_documentation else ""
        )
        if documentation:
            ET.SubElement(element, _q(BPMN_NS, "documentation")).text = documentation

        # The XSD sequence is documentation, incoming, outgoing, eventDefinition.
        for flow in model.incoming(node.id):
            ET.SubElement(element, _q(BPMN_NS, "incoming")).text = flow.id
        for flow in model.outgoing(node.id):
            ET.SubElement(element, _q(BPMN_NS, "outgoing")).text = flow.id

        if not node.event_definition.is_none:
            self._event_definition(element, node)

    def _event_definition(self, parent: ET.Element, node: Node) -> None:
        definition = ET.SubElement(
            parent,
            _q(BPMN_NS, node.event_definition.value),
            {"id": f"{node.id}_def"},
        )
        if node.event_definition is EventDefinition.TIMER:
            expression = node.attrs.get("timer", "")
            if not expression:
                return
            tag = "timeCycle" if _is_recurring(expression) else "timeDuration"
            child = ET.SubElement(definition, _q(BPMN_NS, tag))
            child.set(_q(XSI_NS, "type"), "bpmn:tFormalExpression")
            child.text = expression

    def _sequence_flow(self, parent: ET.Element, flow: Flow) -> None:
        attributes = {"id": flow.id, "sourceRef": flow.source_id, "targetRef": flow.target_id}
        if flow.name:
            attributes["name"] = flow.name
        element = ET.SubElement(parent, _q(BPMN_NS, "sequenceFlow"), attributes)
        if flow.condition:
            condition = ET.SubElement(element, _q(BPMN_NS, "conditionExpression"))
            condition.set(_q(XSI_NS, "type"), "bpmn:tFormalExpression")
            condition.text = flow.condition

    # -- diagram interchange -------------------------------------------------

    def _diagram(self, parent: ET.Element, model: ProcessModel, layout: Layout) -> None:
        diagram = ET.SubElement(
            parent, _q(BPMNDI_NS, "BPMNDiagram"), {"id": self.options.diagram_id}
        )
        plane = ET.SubElement(
            diagram,
            _q(BPMNDI_NS, "BPMNPlane"),
            {
                "id": self.options.plane_id,
                "bpmnElement": self.options.collaboration_id if model.has_lanes else model.id,
            },
        )

        if model.has_lanes and layout.pool is not None:
            self._shape(plane, self.options.participant_id, layout.pool, horizontal=True)
            for lane in model.lanes:
                bounds = layout.lanes.get(lane.id)
                if bounds is not None:
                    self._shape(plane, lane.id, bounds, horizontal=True)

        for node in model.nodes:
            bounds = layout.shapes.get(node.id)
            if bounds is None:
                continue
            shape = self._shape(
                plane,
                node.id,
                bounds,
                marker_visible=node.kind is NodeKind.EXCLUSIVE_GATEWAY,
            )
            label = layout.node_labels.get(node.id)
            if label is not None:
                self._label(shape, label)

        for flow in model.flows:
            points = layout.waypoints.get(flow.id)
            if not points:
                continue
            edge = ET.SubElement(
                plane,
                _q(BPMNDI_NS, "BPMNEdge"),
                {"id": f"{flow.id}_di", "bpmnElement": flow.id},
            )
            for point in points:
                ET.SubElement(
                    edge, _q(DI_NS, "waypoint"), {"x": _num(point.x), "y": _num(point.y)}
                )
            label = layout.edge_labels.get(flow.id)
            if label is not None:
                self._label(edge, label)

    def _shape(
        self,
        plane: ET.Element,
        element_id: str,
        bounds: Bounds,
        *,
        horizontal: bool | None = None,
        marker_visible: bool = False,
    ) -> ET.Element:
        attributes = {"id": f"{element_id}_di", "bpmnElement": element_id}
        if horizontal is not None:
            attributes["isHorizontal"] = _bool(horizontal)
        if marker_visible:
            attributes["isMarkerVisible"] = "true"
        shape = ET.SubElement(plane, _q(BPMNDI_NS, "BPMNShape"), attributes)
        ET.SubElement(shape, _q(DC_NS, "Bounds"), _bounds_attributes(bounds))
        return shape

    def _label(self, parent: ET.Element, bounds: Bounds) -> None:
        label = ET.SubElement(parent, _q(BPMNDI_NS, "BPMNLabel"))
        ET.SubElement(label, _q(DC_NS, "Bounds"), _bounds_attributes(bounds))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _q(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _num(value: float) -> str:
    rounded = round(float(value), 2)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def _bounds_attributes(bounds: Bounds) -> dict[str, str]:
    return {
        "x": _num(bounds.x),
        "y": _num(bounds.y),
        "width": _num(bounds.width),
        "height": _num(bounds.height),
    }


def _is_recurring(expression: str) -> bool:
    lowered = expression.casefold()
    return any(hint in lowered for hint in _RECURRING_HINTS)


def _tidy(xml: str) -> str:
    """minidom leaves blank lines behind; strip them for a diffable file."""
    lines = [line for line in xml.split("\n") if line.strip()]
    return "\n".join(lines) + "\n"


def render_bpmn(
    model: ProcessModel, layout: Layout, options: BpmnRenderOptions | None = None
) -> str:
    """Convenience wrapper around :class:`BpmnRenderer`."""
    return BpmnRenderer(options).render(model, layout)
