import pytest

from bpmn_architect import ValidationFailed, generate
from bpmn_architect.pipeline import PipelineOptions, describe


class TestPipeline:
    def test_produces_a_complete_result(self, order_request):
        assert order_request.model.name == "Обработка заявки клиента"
        assert order_request.is_valid
        assert order_request.layout.shapes
        assert order_request.to_bpmn().startswith("<?xml")

    def test_explanation_mirrors_the_parsed_structure(self, order_request):
        explanation = order_request.explain()
        assert "process: Обработка заявки клиента" in explanation
        assert "<xor> Заявка корректна?" in explanation
        assert "case 'Нет' (default)" in explanation

    def test_strict_mode_rejects_broken_models(self):
        options = PipelineOptions(strict=True)
        options.build.auto_close_open_ends = False
        with pytest.raises(ValidationFailed):
            generate("Менеджер проверяет заявку.", options)

    def test_validation_can_be_skipped(self):
        options = PipelineOptions(run_validation=False)
        options.build.auto_close_open_ends = False
        result = generate("Менеджер проверяет заявку.", options)
        assert not result.diagnostics.errors

    def test_dsl_and_prose_reach_the_same_pipeline(self):
        prose = generate("Менеджер проверяет заявку.")
        dsl = generate("task[Менеджер]: Проверить заявку\n")
        assert [node.name for node in prose.model.nodes] == [
            node.name for node in dsl.model.nodes
        ]

    def test_process_identity_can_be_overridden(self):
        options = PipelineOptions()
        options.build.process_id = "OrderHandling"
        options.build.process_name = "Order handling"
        result = generate("Менеджер проверяет заявку.", options)
        assert result.model.id == "OrderHandling"
        assert result.model.name == "Order handling"

    def test_executable_flag_reaches_the_xml(self):
        options = PipelineOptions()
        options.build.executable = True
        assert 'isExecutable="true"' in generate("task: Шаг\n", options).to_bpmn()


class TestRobustness:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   \n\n\t",
            "Одно предложение без структуры",
            "???",
            "1.\n2.\n3.\n",
            "Если:\n",
            "Процесс завершается.",
            "Иначе менеджер отклоняет заявку.",
        ],
        ids=[
            "empty",
            "whitespace",
            "single-sentence",
            "punctuation",
            "empty-list",
            "dangling-condition",
            "end-only",
            "orphan-else",
        ],
    )
    def test_degenerate_input_never_crashes(self, text):
        result = generate(text)
        assert result.to_bpmn().startswith("<?xml")

    def test_every_generated_model_has_a_start_and_an_end(self, example):
        assert example.model.start_events
        assert example.model.end_events


def test_describe_handles_an_empty_process():
    from bpmn_architect.domain.ir import IRProcess

    assert "process: (unnamed)" in describe(IRProcess())
