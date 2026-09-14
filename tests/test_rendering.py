import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bpmn_architect.pipeline import PipelineOptions, generate
from bpmn_architect.rendering.bpmn_xml import BPMN_NS, BPMNDI_NS, DC_NS, DI_NS

NS = {"bpmn": BPMN_NS, "bpmndi": BPMNDI_NS, "dc": DC_NS, "di": DI_NS}
NCNAME = re.compile(r"^[A-Za-z_][\w.\-]*$")


def tree(result):  # type: ignore[no-untyped-def]
    return ET.fromstring(result.to_bpmn())


class TestSemanticSection:
    def test_document_is_well_formed_bpmn(self, example):
        root = tree(example)
        assert root.tag == f"{{{BPMN_NS}}}definitions"
        assert root.get("targetNamespace")
        assert root.get("exporter") == "bpmn-architect"

    def test_every_node_and_flow_is_serialised(self, example):
        root = tree(example)
        process = root.find("bpmn:process", NS)
        serialised = {
            child.get("id")
            for child in process
            if child.tag != f"{{{BPMN_NS}}}laneSet"
        }
        assert {node.id for node in example.model.nodes} <= serialised
        assert {flow.id for flow in example.model.flows} <= serialised

    def test_element_tags_match_the_model(self, example):
        root = tree(example)
        process = root.find("bpmn:process", NS)
        by_id = {child.get("id"): child.tag.split("}")[1] for child in process}
        for node in example.model.nodes:
            assert by_id[node.id] == node.kind.value

    def test_incoming_and_outgoing_match_the_sequence_flows(self, example):
        root = tree(example)
        process = root.find("bpmn:process", NS)
        flows = {
            flow.get("id"): (flow.get("sourceRef"), flow.get("targetRef"))
            for flow in process.findall("bpmn:sequenceFlow", NS)
        }
        for child in process:
            node_id = child.get("id")
            if node_id not in flows:
                for reference in child.findall("bpmn:outgoing", NS):
                    assert flows[reference.text][0] == node_id
                for reference in child.findall("bpmn:incoming", NS):
                    assert flows[reference.text][1] == node_id

    def test_identifiers_are_valid_xml_names(self, example):
        for element in tree(example).iter():
            identifier = element.get("id")
            if identifier:
                assert NCNAME.match(identifier), identifier

    def test_lanes_are_wrapped_in_a_collaboration(self, order_request):
        root = tree(order_request)
        participant = root.find("bpmn:collaboration/bpmn:participant", NS)
        assert participant is not None
        assert participant.get("processRef") == order_request.model.id
        lanes = root.findall("bpmn:process/bpmn:laneSet/bpmn:lane", NS)
        assert [lane.get("name") for lane in lanes] == [
            lane.name for lane in order_request.model.lanes
        ]
        referenced = {
            reference.text
            for lane in lanes
            for reference in lane.findall("bpmn:flowNodeRef", NS)
        }
        assert referenced == {node.id for node in order_request.model.nodes}

    def test_default_flow_carries_no_condition(self, order_request):
        root = tree(order_request)
        for gateway in root.iter(f"{{{BPMN_NS}}}exclusiveGateway"):
            default = gateway.get("default")
            if not default:
                continue
            flow = next(
                f
                for f in root.iter(f"{{{BPMN_NS}}}sequenceFlow")
                if f.get("id") == default
            )
            assert flow.find("bpmn:conditionExpression", NS) is None

    def test_conditions_are_typed_expressions(self, order_request):
        root = tree(order_request)
        conditions = list(root.iter(f"{{{BPMN_NS}}}conditionExpression"))
        assert conditions
        for condition in conditions:
            assert condition.get(
                "{http://www.w3.org/2001/XMLSchema-instance}type"
            ) == "bpmn:tFormalExpression"

    def test_timer_definitions_carry_a_duration(self):
        result = generate("start: Начало\ntimer: Ожидание (timer=P3D)\nend: Готово\n")
        root = tree(result)
        duration = root.find(".//bpmn:timerEventDefinition/bpmn:timeDuration", NS)
        assert duration is not None and duration.text == "P3D"

    def test_source_documentation_can_be_switched_off(self):
        text = "Менеджер проверяет заявку."
        assert "<bpmn:documentation>" in generate(text).to_bpmn()
        options = PipelineOptions()
        options.render.include_source_documentation = False
        assert "<bpmn:documentation>" not in generate(text, options).to_bpmn()


class TestDiagramInterchange:
    def test_a_shape_exists_for_every_element(self, example):
        root = tree(example)
        shapes = {
            shape.get("bpmnElement")
            for shape in root.iter(f"{{{BPMNDI_NS}}}BPMNShape")
        }
        assert {node.id for node in example.model.nodes} <= shapes
        for lane in example.model.lanes:
            assert lane.id in shapes

    def test_every_edge_has_at_least_two_waypoints(self, example):
        root = tree(example)
        edges = {
            edge.get("bpmnElement"): edge.findall("di:waypoint", NS)
            for edge in root.iter(f"{{{BPMNDI_NS}}}BPMNEdge")
        }
        assert set(edges) == {flow.id for flow in example.model.flows}
        for flow_id, waypoints in edges.items():
            assert len(waypoints) >= 2, flow_id

    def test_bounds_are_positive(self, example):
        for bounds in tree(example).iter(f"{{{DC_NS}}}Bounds"):
            assert float(bounds.get("width")) > 0
            assert float(bounds.get("height")) > 0

    def test_plane_references_the_collaboration_when_lanes_exist(self, order_request):
        plane = tree(order_request).find("bpmndi:BPMNDiagram/bpmndi:BPMNPlane", NS)
        assert plane.get("bpmnElement") == "Collaboration_1"

    def test_plane_references_the_process_without_lanes(self):
        options = PipelineOptions()
        options.build.use_lanes = False
        options.parser.detect_lanes = False
        result = generate("Менеджер проверяет заявку.", options)
        plane = tree(result).find("bpmndi:BPMNDiagram/bpmndi:BPMNPlane", NS)
        assert plane.get("bpmnElement") == result.model.id


class TestOtherFormats:
    def test_svg_is_well_formed_and_complete(self, example):
        svg = example.to_svg()
        root = ET.fromstring(svg)
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        text = "".join(node.text or "" for node in root.iter())
        for node in example.model.nodes:
            if node.name:
                assert node.name.split()[0] in text

    def test_json_projection(self, example):
        payload = json.loads(example.to_json())
        assert payload["process"]["id"] == example.model.id
        assert len(payload["nodes"]) == len(example.model.nodes)
        assert len(payload["flows"]) == len(example.model.flows)
        assert set(payload["layout"]["shapes"]) == set(example.layout.shapes)


def test_rendering_is_reproducible():
    text = Path("examples/order_request.ru.txt").read_text(encoding="utf-8")
    assert generate(text).to_bpmn() == generate(text).to_bpmn()


@pytest.mark.parametrize("fmt", ["to_bpmn", "to_svg", "to_json"])
def test_output_is_non_empty(order_request, fmt):
    assert len(getattr(order_request, fmt)()) > 200
