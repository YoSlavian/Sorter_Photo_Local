from bpmn_architect.domain.model import Flow, Lane, Node, NodeKind, ProcessModel
from bpmn_architect.validation import Severity, validate


def model_with(*nodes: Node) -> ProcessModel:
    model = ProcessModel()
    for node in nodes:
        model.add_node(node)
    return model


def codes(model: ProcessModel) -> set[str]:
    return {diagnostic.code for diagnostic in validate(model)}


class TestErrors:
    def test_missing_start_and_end(self):
        model = model_with(Node("Activity_1", NodeKind.TASK, "Шаг"))
        assert {"E001", "E002"} <= codes(model)

    def test_unreachable_element(self):
        model = model_with(
            Node("StartEvent_1", NodeKind.START_EVENT),
            Node("Activity_1", NodeKind.TASK, "Достижимый"),
            Node("Activity_2", NodeKind.TASK, "Оторванный"),
            Node("EndEvent_1", NodeKind.END_EVENT),
        )
        model.add_flow(Flow("Flow_1", "StartEvent_1", "Activity_1"))
        model.add_flow(Flow("Flow_2", "Activity_1", "EndEvent_1"))
        model.add_flow(Flow("Flow_3", "Activity_2", "EndEvent_1"))
        assert "E003" in codes(model)

    def test_dead_end(self):
        model = model_with(
            Node("StartEvent_1", NodeKind.START_EVENT),
            Node("Activity_1", NodeKind.TASK, "Тупик"),
            Node("EndEvent_1", NodeKind.END_EVENT),
        )
        model.add_flow(Flow("Flow_1", "StartEvent_1", "Activity_1"))
        assert {"E004", "E005", "E006"} <= codes(model)

    def test_start_event_must_not_have_inbound_flow(self):
        model = model_with(
            Node("StartEvent_1", NodeKind.START_EVENT),
            Node("Activity_1", NodeKind.TASK, "Шаг"),
            Node("EndEvent_1", NodeKind.END_EVENT),
        )
        model.add_flow(Flow("Flow_1", "StartEvent_1", "Activity_1"))
        model.add_flow(Flow("Flow_2", "Activity_1", "StartEvent_1"))
        model.add_flow(Flow("Flow_3", "Activity_1", "EndEvent_1"))
        assert "E007" in codes(model)

    def test_default_flow_only_on_gateways(self):
        model = model_with(
            Node("StartEvent_1", NodeKind.START_EVENT),
            Node("Activity_1", NodeKind.TASK, "Шаг"),
            Node("EndEvent_1", NodeKind.END_EVENT),
        )
        model.add_flow(Flow("Flow_1", "StartEvent_1", "Activity_1"))
        model.add_flow(Flow("Flow_2", "Activity_1", "EndEvent_1", is_default=True))
        assert "E010" in codes(model)


class TestWarnings:
    def test_unlabelled_alternatives(self):
        model = model_with(
            Node("StartEvent_1", NodeKind.START_EVENT),
            Node("Gateway_1", NodeKind.EXCLUSIVE_GATEWAY, "Решение?"),
            Node("Activity_1", NodeKind.TASK, "A"),
            Node("Activity_2", NodeKind.TASK, "B"),
            Node("EndEvent_1", NodeKind.END_EVENT),
        )
        model.add_flow(Flow("Flow_1", "StartEvent_1", "Gateway_1"))
        model.add_flow(Flow("Flow_2", "Gateway_1", "Activity_1"))
        model.add_flow(Flow("Flow_3", "Gateway_1", "Activity_2"))
        model.add_flow(Flow("Flow_4", "Activity_1", "EndEvent_1"))
        model.add_flow(Flow("Flow_5", "Activity_2", "EndEvent_1"))
        assert "W103" in codes(model)

    def test_implicit_split_from_an_activity(self):
        model = model_with(
            Node("StartEvent_1", NodeKind.START_EVENT),
            Node("Activity_1", NodeKind.TASK, "Шаг"),
            Node("EndEvent_1", NodeKind.END_EVENT),
            Node("EndEvent_2", NodeKind.END_EVENT),
        )
        model.add_flow(Flow("Flow_1", "StartEvent_1", "Activity_1"))
        model.add_flow(Flow("Flow_2", "Activity_1", "EndEvent_1"))
        model.add_flow(Flow("Flow_3", "Activity_1", "EndEvent_2"))
        assert "W106" in codes(model)

    def test_node_outside_any_lane(self):
        model = ProcessModel()
        model.add_lane(Lane("Lane_1", "Менеджер"))
        model.add_node(Node("StartEvent_1", NodeKind.START_EVENT, lane_id="Lane_1"))
        model.add_node(Node("Activity_1", NodeKind.TASK, "Шаг"))
        model.add_node(Node("EndEvent_1", NodeKind.END_EVENT, lane_id="Lane_1"))
        model.add_flow(Flow("Flow_1", "StartEvent_1", "Activity_1"))
        model.add_flow(Flow("Flow_2", "Activity_1", "EndEvent_1"))
        assert "W109" in codes(model)


def test_generated_examples_are_structurally_valid(example):
    errors = [str(diagnostic) for diagnostic in example.diagnostics.errors]
    assert errors == [], f"{example.model.name}: {errors}"


def test_diagnostics_are_sorted_by_severity(order_request):
    severities = [d.severity for d in order_request.diagnostics.sorted()]
    assert severities == sorted(severities, key=lambda s: s.rank)
    assert Severity.ERROR.rank < Severity.WARNING.rank < Severity.INFO.rank
