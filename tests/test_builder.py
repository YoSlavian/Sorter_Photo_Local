from bpmn_architect.building import BuildOptions, build_model
from bpmn_architect.domain.model import NodeKind
from bpmn_architect.parsing import parse, parse_dsl
from conftest import find


def build(text: str, options: BuildOptions | None = None):  # type: ignore[no-untyped-def]
    return build_model(parse(text), options)


class TestGraphConstruction:
    def test_linear_flow_is_chained(self):
        model = build(
            "Процесс начинается.\nМенеджер проверяет заявку.\nПроцесс завершается."
        ).model
        assert [node.kind for node in model.nodes] == [
            NodeKind.START_EVENT,
            NodeKind.USER_TASK,
            NodeKind.END_EVENT,
        ]
        assert len(model.flows) == 2

    def test_decision_creates_a_split_and_a_join(self):
        model = build(
            "Менеджер проверяет заявку.\n"
            "Если заявка корректна, то бухгалтер выставляет счёт, иначе менеджер отклоняет заявку.\n"
            "После этого менеджер уведомляет клиента.\n"
        ).model
        gateways = model.nodes_of_kind(NodeKind.EXCLUSIVE_GATEWAY)
        assert len(gateways) == 2
        split, join = gateways
        assert len(model.outgoing(split.id)) == 2
        assert len(model.incoming(join.id)) == 2

    def test_a_terminated_arm_removes_the_need_for_a_join(self):
        model = build(
            "Если заявка корректна, то бухгалтер выставляет счёт, "
            "иначе менеджер отклоняет заявку и процесс завершается.\n"
            "Менеджер уведомляет клиента.\n"
        ).model
        # Only one path survives the decision, so no join gateway is created.
        assert len(model.nodes_of_kind(NodeKind.EXCLUSIVE_GATEWAY)) == 1

    def test_parallel_block_uses_parallel_gateways(self):
        model = build(
            "Параллельно выполняются проверка склада и проверка лимита.\n"
            "Менеджер оформляет заказ.\n"
        ).model
        assert len(model.nodes_of_kind(NodeKind.PARALLEL_GATEWAY)) == 2

    def test_default_flow_is_marked_on_the_gateway(self):
        model = build(
            "Если заявка корректна, то бухгалтер выставляет счёт, иначе менеджер отклоняет заявку."
        ).model
        split = model.nodes_of_kind(NodeKind.EXCLUSIVE_GATEWAY)[0]
        defaults = [flow for flow in model.outgoing(split.id) if flow.is_default]
        assert len(defaults) == 1
        assert defaults[0].name == "Нет"
        assert defaults[0].condition == ""


class TestJumps:
    def test_jump_by_similar_wording(self):
        model = build(
            "Менеджер проверяет заявку.\n"
            "Менеджер отклоняет заявку и заявка возвращается к проверке заявки.\n"
        ).model
        target = find_model(model, "Проверить заявку")
        assert any(flow.target_id == target.id for flow in model.flows if flow.source_id != target.id)

    def test_jump_by_anchor(self):
        result = build_model(
            parse_dsl("task: Проверить @check\ntask: Отклонить\ngoto: @check\n")
        )
        model = result.model
        check = find_model(model, "Проверить")
        reject = find_model(model, "Отклонить")
        assert any(f.source_id == reject.id and f.target_id == check.id for f in model.flows)

    def test_unresolved_jump_is_reported_and_the_path_is_closed(self):
        result = build_model(parse_dsl("task: Проверить\ngoto: @nowhere\n"))
        assert any(d.code == "B201" for d in result.diagnostics)
        assert result.model.end_events, "the open path must still be terminated"


class TestFinalisation:
    def test_missing_start_event_is_added(self):
        result = build("Менеджер проверяет заявку.")
        assert result.model.start_events
        assert any(d.code == "B301" for d in result.diagnostics)

    def test_open_paths_are_terminated(self):
        result = build("Менеджер проверяет заявку.")
        assert result.model.end_events
        assert any(d.code == "B302" for d in result.diagnostics)

    def test_every_node_lands_in_a_lane(self):
        model = build(
            "Процесс начинается.\n"
            "Менеджер проверяет заявку.\n"
            "Бухгалтер выставляет счёт.\n"
            "Процесс завершается."
        ).model
        assert model.has_lanes
        assert all(node.lane_id is not None for node in model.nodes)

    def test_lanes_can_be_switched_off(self):
        model = build("Менеджер проверяет заявку.", BuildOptions(use_lanes=False)).model
        assert not model.has_lanes

    def test_identifiers_are_deterministic(self):
        first = build("Менеджер проверяет заявку.").model
        second = build("Менеджер проверяет заявку.").model
        assert [node.id for node in first.nodes] == [node.id for node in second.nodes]


def find_model(model, name):  # type: ignore[no-untyped-def]
    matches = [node for node in model.nodes if name.casefold() in node.name.casefold()]
    assert matches, f"no node named {name!r}"
    return matches[0]


def test_source_sentences_are_preserved_for_traceability(order_request):
    task = find(order_request, "Проверить заявку")
    assert "проверяет заявку" in task.attrs["source"]
    assert task.attrs["line"].isdigit()
