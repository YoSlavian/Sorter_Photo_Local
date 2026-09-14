import pytest

from bpmn_architect.domain.ir import ActivityType, BranchType, EventTrigger, IRBranch, IRParallel
from bpmn_architect.errors import ParseError
from bpmn_architect.parsing import looks_like_dsl, parse, parse_dsl

SOURCE = """\
process: Согласование счёта
id: InvoiceApproval
lane: Бухгалтер

start: Счёт получен (message)
task[Бухгалтер]: Проверить счёт @check
xor: Счёт корректен?
  case Да (condition=invoice.valid):
    service: Провести оплату
    end: Счёт оплачен
  else Нет:
    send: Запросить исправление
    timer: Ожидание (timer=P3D)
    goto: @check
"""


class TestParsing:
    def test_header_directives(self):
        process = parse_dsl(SOURCE)
        assert process.name == "Согласование счёта"
        assert process.options["id"] == "InvoiceApproval"
        assert "Бухгалтер" in process.lane_names()

    def test_element_types_and_anchors(self):
        process = parse_dsl(SOURCE)
        task = process.root.items[1]
        assert task.activity_type is ActivityType.TASK
        assert task.actor == "Бухгалтер"
        assert task.anchor == "check"

    def test_gateway_arms_and_conditions(self):
        branch = parse_dsl(SOURCE).root.items[2]
        assert isinstance(branch, IRBranch)
        assert branch.branch_type is BranchType.EXCLUSIVE
        assert branch.arms[0].condition == "invoice.valid"
        assert branch.arms[1].is_default is True

    def test_timer_option(self):
        arm = parse_dsl(SOURCE).root.items[2].arms[1]
        timer = arm.body.items[1]
        assert timer.trigger is EventTrigger.TIMER
        assert timer.timer == "P3D"

    def test_inline_arm_without_a_label_is_a_body_not_a_label(self):
        process = parse_dsl(
            "xor: Заявка корректна?\n  case Да: Выставить счёт\n  else: Отклонить заявку\n"
        )
        branch = process.root.items[0]
        yes, no = branch.arms
        assert (yes.label, yes.body.items[0].text) == ("Да", "Выставить счёт")
        assert no.is_default and no.label == ""
        assert [item.text for item in no.body] == ["Отклонить заявку"]

    def test_labelled_arm_with_nested_body(self):
        process = parse_dsl(
            "xor: Вопрос?\n  case Да:\n    task: Первая\n  else Нет:\n    task: Вторая\n"
        )
        branch = process.root.items[0]
        assert [arm.label for arm in branch.arms] == ["Да", "Нет"]
        assert [arm.body.items[0].text for arm in branch.arms] == ["Первая", "Вторая"]

    def test_parallel_block(self):
        process = parse_dsl(
            "and:\n  branch:\n    task: Первая\n  branch:\n    task: Вторая\n"
        )
        parallel = process.root.items[0]
        assert isinstance(parallel, IRParallel)
        assert [branch.items[0].text for branch in parallel.branches] == ["Первая", "Вторая"]

    def test_russian_keywords(self):
        process = parse_dsl("начало: Старт\nзадача[Менеджер]: Проверить\nконец: Готово\n")
        assert [item.text for item in process.root] == ["Старт", "Проверить", "Готово"]


class TestErrors:
    def test_unknown_directive(self):
        with pytest.raises(ParseError, match="unknown directive"):
            parse_dsl("task: ok\nnonsense: bad\n")

    def test_missing_colon(self):
        with pytest.raises(ParseError, match="expected a directive"):
            parse_dsl("task: ok\njust some prose\n")

    def test_gateway_without_cases(self):
        with pytest.raises(ParseError, match="needs at least one 'case'"):
            parse_dsl("xor: Вопрос?\n")

    def test_parallel_needs_two_branches(self):
        with pytest.raises(ParseError, match="at least two 'branch'"):
            parse_dsl("and:\n  branch:\n    task: Одна\n")

    def test_error_reports_the_line(self):
        with pytest.raises(ParseError) as info:
            parse_dsl("task: ok\nnonsense: bad\n")
        assert "line 2" in str(info.value)


class TestDetection:
    def test_dsl_is_detected(self):
        assert looks_like_dsl(SOURCE)

    def test_prose_is_not_mistaken_for_dsl(self):
        prose = (
            "Процесс начинается с получения заявки.\n"
            "Менеджер проверяет заявку: он сверяет данные.\n"
            "Процесс завершается.\n"
        )
        assert not looks_like_dsl(prose)

    def test_auto_dispatch(self):
        assert parse(SOURCE).name == "Согласование счёта"
        assert parse("Менеджер проверяет заявку.").root.items[0].text == "Проверить заявку"

    def test_explicit_syntax_choice(self):
        with pytest.raises(ParseError):
            parse("Просто предложение без директив.", syntax="dsl")

    def test_auto_falls_back_to_prose_when_the_dsl_rejects_the_text(self):
        # "Если:" looks structural enough to be detected as DSL, but the DSL
        # parser rejects it; auto must degrade instead of raising.
        assert parse("Если:", syntax="auto").root is not None

    def test_unknown_syntax_is_rejected(self):
        with pytest.raises(ValueError, match="unknown syntax"):
            parse("что угодно", syntax="yaml")
