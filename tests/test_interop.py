"""Reading BPMN 2.0 XML back into the domain model."""

from pathlib import Path

import pytest

from bpmn_architect import generate
from bpmn_architect.domain.model import EventDefinition, NodeKind
from bpmn_architect.errors import ParseError
from bpmn_architect.interop import import_bpmn
from bpmn_architect.rendering.bpmn_xml import render_bpmn

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

FOREIGN = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:camunda="http://camunda.org/schema/1.0/bpmn"
             id="Defs" targetNamespace="http://example.org">
  <process id="Proc" isExecutable="true">
    <startEvent id="S1" name="Заявка"><messageEventDefinition id="m"/></startEvent>
    <userTask id="T1" name="Проверить" camunda:assignee="manager">
      <documentation>из внешней системы</documentation>
    </userTask>
    <exclusiveGateway id="G1" name="Ок?" default="F3"/>
    <serviceTask id="T2" name="Заказ"/>
    <boundaryEvent id="B1" name="Таймаут" attachedToRef="T1">
      <timerEventDefinition><timeDuration>PT1H</timeDuration></timerEventDefinition>
    </boundaryEvent>
    <endEvent id="E1" name="Готово"/>
    <sequenceFlow id="F1" sourceRef="S1" targetRef="T1"/>
    <sequenceFlow id="F2" sourceRef="T1" targetRef="G1"/>
    <sequenceFlow id="F3" sourceRef="G1" targetRef="T2" name="Да"/>
    <sequenceFlow id="F4" sourceRef="G1" targetRef="E1" name="Нет">
      <conditionExpression>не ок</conditionExpression>
    </sequenceFlow>
    <sequenceFlow id="F5" sourceRef="T2" targetRef="E1"/>
    <sequenceFlow id="F6" sourceRef="B1" targetRef="E1"/>
  </process>
</definitions>
"""


class TestRoundTrip:
    @pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.iterdir()))
    def test_export_import_preserves_everything(self, name):
        result = generate((EXAMPLES / name).read_text(encoding="utf-8"))
        imported = import_bpmn(result.to_bpmn())

        assert [n.id for n in imported.model.nodes] == [n.id for n in result.model.nodes]
        assert [n.kind for n in imported.model.nodes] == [n.kind for n in result.model.nodes]
        assert [f.id for f in imported.model.flows] == [f.id for f in result.model.flows]
        assert [lane.name for lane in imported.model.lanes] == [
            lane.name for lane in result.model.lanes
        ]

    def test_geometry_survives_the_round_trip(self, order_request):
        imported = import_bpmn(order_request.to_bpmn())
        assert not imported.layout_was_generated
        for node in order_request.model.nodes:
            before = order_request.layout.shapes[node.id]
            after = imported.layout.shapes[node.id]
            assert (after.x, after.y, after.width, after.height) == (
                before.x,
                before.y,
                before.width,
                before.height,
            )

    def test_reimported_model_can_be_exported_again(self, order_request):
        once = order_request.to_bpmn()
        imported = import_bpmn(once)
        twice = render_bpmn(imported.model, imported.layout)
        assert import_bpmn(twice).model.nodes


class TestForeignFiles:
    def test_default_namespace_prefix_is_handled(self):
        model = import_bpmn(FOREIGN).model
        assert model.id == "Proc"
        assert model.node("S1").event_definition is EventDefinition.MESSAGE

    def test_vendor_attributes_are_ignored(self):
        assert import_bpmn(FOREIGN).model.node("T1").kind is NodeKind.USER_TASK

    def test_documentation_is_preserved(self):
        assert import_bpmn(FOREIGN).model.node("T1").documentation == "из внешней системы"

    def test_default_flow_and_condition(self):
        model = import_bpmn(FOREIGN).model
        assert model.flow("F3").is_default is True
        assert model.flow("F3").condition == ""
        assert model.flow("F4").condition == "не ок"

    def test_unsupported_elements_are_reported_not_dropped(self):
        result = import_bpmn(FOREIGN)
        assert result.model.has_node("B1")
        assert result.model.node("B1").kind is NodeKind.INTERMEDIATE_CATCH_EVENT
        assert result.model.node("B1").attrs["timer"] == "PT1H"
        assert any(d.code == "I305" for d in result.diagnostics)

    def test_missing_diagram_interchange_is_generated(self):
        result = import_bpmn(FOREIGN)
        assert result.layout_was_generated
        assert set(result.layout.shapes) == {node.id for node in result.model.nodes}

    def test_broken_reference_is_an_error_not_a_crash(self):
        broken = FOREIGN.replace(
            '<sequenceFlow id="F5" sourceRef="T2" targetRef="E1"/>',
            '<sequenceFlow id="F5" sourceRef="GHOST" targetRef="E1"/>',
        )
        result = import_bpmn(broken)
        assert any(d.code == "E301" for d in result.diagnostics)
        assert not result.model.has_node("GHOST")


class TestErrors:
    def test_malformed_xml(self):
        with pytest.raises(ParseError, match="not well-formed"):
            import_bpmn("<definitions>")

    def test_wrong_root_element(self):
        with pytest.raises(ParseError, match="bpmn:definitions"):
            import_bpmn('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>')

    def test_no_process(self):
        with pytest.raises(ParseError, match="no bpmn:process"):
            import_bpmn(
                '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d"/>'
            )
