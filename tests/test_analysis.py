"""Detecting and resolving what the description left open."""

from bpmn_architect import generate
from bpmn_architect.analysis import analyse_ambiguity, apply_clarifications
from bpmn_architect.analysis.ambiguity import _is_vague
from bpmn_architect.sourcemap import build_source_map

VAGUE = """\
Процесс начинается с поступления заявки.
Менеджер проверяет заявку.
Далее выполняется обработка.
Процесс завершается.
"""


class TestVagueness:
    def test_recognises_empty_statements_of_work(self):
        assert _is_vague("Обработка", "ru")
        assert _is_vague("Выполняется обработка", "ru")
        assert _is_vague("Осуществляется проверка", "ru")
        assert _is_vague("Processing", "en")

    def test_accepts_named_work(self):
        assert not _is_vague("Проверить заявку", "ru")
        assert not _is_vague("Выставить счёт", "ru")
        assert not _is_vague("Create the invoice", "en")


class TestQuestions:
    def test_a_vague_step_raises_a_question(self):
        questions = analyse_ambiguity(generate(VAGUE).model, language="ru")
        assert any(question.kind == "naming" for question in questions)

    def test_questions_carry_their_source_sentence(self):
        result = generate(VAGUE)
        source_map = build_source_map(result.model, VAGUE)
        questions = analyse_ambiguity(result.model, language="ru", source_map=source_map)
        naming = next(q for q in questions if q.kind == "naming")
        assert "обработка" in naming.sentence.casefold()
        assert naming.line > 0

    def test_a_clear_description_raises_nothing(self, order_request):
        assert analyse_ambiguity(order_request.model, language="ru") == []

    def test_actor_question_offers_the_existing_lanes(self):
        result = generate(VAGUE)
        # Detach a step from its lane, as an imported diagram might be.
        activity = next(n for n in result.model.nodes if n.kind.is_activity)
        activity.lane_id = None
        questions = analyse_ambiguity(result.model, language="ru")
        actor = next(q for q in questions if q.kind == "actor")
        labels = [option.label for option in actor.options]
        assert "Менеджер" in labels
        assert "Система" in labels
        assert actor.options[-1].free_text is True

    def test_join_gateways_are_not_asked_about(self):
        result = generate(
            "Если заявка корректна, то менеджер оформляет договор, "
            "иначе менеджер отклоняет заявку.\nМенеджер уведомляет клиента."
        )
        assert not any(
            question.kind == "branch_label" for question in analyse_ambiguity(result.model)
        )

    def test_english_questions(self):
        result = generate("The process starts.\nProcessing.\nThe process ends.")
        questions = analyse_ambiguity(result.model, language="en")
        assert any("What exactly happens" in question.question for question in questions)

    def test_serialisation_shape(self):
        question = analyse_ambiguity(generate(VAGUE).model, language="ru")[0]
        payload = question.to_dict()
        assert set(payload) >= {"id", "kind", "question", "elementId", "options"}


class TestApplyingAnswers:
    def test_naming_answer_renames_the_element(self):
        result = generate(VAGUE)
        questions = analyse_ambiguity(result.model, language="ru")
        naming = next(q for q in questions if q.kind == "naming")
        apply_clarifications(result.model, questions, {naming.id: "Обработать обращение"})
        assert result.model.node(naming.element_id).name == "Обработать обращение"

    def test_actor_answer_creates_a_lane_when_needed(self):
        result = generate(VAGUE)
        activity = next(n for n in result.model.nodes if n.kind.is_activity)
        activity.lane_id = None
        questions = analyse_ambiguity(result.model, language="ru")
        actor = next(q for q in questions if q.kind == "actor")
        diagnostics = apply_clarifications(result.model, questions, {actor.id: "Диспетчер"})
        lane = result.model.lane(result.model.node(actor.element_id).lane_id)
        assert lane.name == "Диспетчер"
        assert any(d.code == "A403" for d in diagnostics)

    def test_existing_lane_is_reused(self):
        result = generate(VAGUE)
        activity = next(n for n in result.model.nodes if n.kind.is_activity)
        activity.lane_id = None
        before = len(result.model.lanes)
        questions = analyse_ambiguity(result.model, language="ru")
        actor = next(q for q in questions if q.kind == "actor")
        apply_clarifications(result.model, questions, {actor.id: "менеджер"})
        assert len(result.model.lanes) == before

    def test_unknown_answer_is_reported(self):
        result = generate(VAGUE)
        diagnostics = apply_clarifications(result.model, [], {"ask_999": "что-то"})
        assert any(d.code == "A401" for d in diagnostics)

    def test_empty_answers_change_nothing(self):
        result = generate(VAGUE)
        questions = analyse_ambiguity(result.model, language="ru")
        names_before = [node.name for node in result.model.nodes]
        apply_clarifications(result.model, questions, {q.id: "  " for q in questions})
        assert [node.name for node in result.model.nodes] == names_before
