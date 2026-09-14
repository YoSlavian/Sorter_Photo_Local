from bpmn_architect.domain.ir import (
    ActivityType,
    EventPosition,
    EventTrigger,
    IRActivity,
    IRBranch,
    IREvent,
    IRGoto,
    IRParallel,
)
from bpmn_architect.parsing import ParserOptions, parse_text


def kinds(sequence):
    return [type(element).__name__ for element in sequence]


class TestStructure:
    def test_recognises_the_process_title(self):
        process = parse_text("Обработка заявки\n\nМенеджер проверяет заявку.")
        assert process.name == "Обработка заявки"

    def test_start_and_end_events(self):
        process = parse_text(
            "Процесс начинается с получения заявки.\n"
            "Менеджер проверяет заявку.\n"
            "Процесс завершается."
        )
        assert isinstance(process.root.items[0], IREvent)
        assert process.root.items[0].position is EventPosition.START
        assert process.root.items[-1].position is EventPosition.END

    def test_inline_condition_becomes_a_two_armed_decision(self):
        process = parse_text(
            "Если заявка корректна, то бухгалтер выставляет счёт, иначе менеджер отклоняет заявку."
        )
        branch = process.root.items[0]
        assert isinstance(branch, IRBranch)
        assert branch.text == "Заявка корректна?"
        assert [arm.label for arm in branch.arms] == ["Да", "Нет"]
        assert branch.arms[1].is_default is True
        assert branch.arms[0].body.items[0].text == "Выставить счёт"

    def test_block_condition_uses_indentation(self):
        process = parse_text(
            "Если договор согласован:\n"
            "    Руководитель подписывает договор.\n"
            "    Бухгалтер регистрирует договор.\n"
            "Иначе:\n"
            "    Юрист дорабатывает договор.\n"
            "Менеджер отправляет договор.\n"
        )
        branch = process.root.items[0]
        assert isinstance(branch, IRBranch)
        assert len(branch.arms) == 2
        assert len(branch.arms[0].body) == 2
        assert len(branch.arms[1].body) == 1
        # The unindented sentence closes the decision and continues the flow.
        assert isinstance(process.root.items[1], IRActivity)

    def test_multi_case_decision_from_a_labelled_list(self):
        process = parse_text(
            "Оператор определяет категорию обращения:\n"
            "  - Техническая: инженер устраняет неисправность.\n"
            "  - Финансовая: бухгалтер проверяет платежи.\n"
            "  - Прочая: оператор отвечает клиенту.\n"
        )
        # The header performs an action *and* opens a decision.
        assert isinstance(process.root.items[0], IRActivity)
        branch = process.root.items[1]
        assert isinstance(branch, IRBranch)
        assert [arm.label for arm in branch.arms] == ["Техническая", "Финансовая", "Прочая"]

    def test_inline_parallel_split(self):
        process = parse_text(
            "Параллельно выполняются проверка склада и проверка кредитного лимита."
        )
        parallel = process.root.items[0]
        assert isinstance(parallel, IRParallel)
        assert len(parallel.branches) == 2

    def test_merge_cue_closes_the_decision(self):
        process = parse_text(
            "Если заявка корректна, бухгалтер выставляет счёт.\n"
            "Иначе менеджер отклоняет заявку.\n"
            "После этого менеджер уведомляет клиента.\n"
        )
        assert kinds(process.root) == ["IRBranch", "IRActivity"]

    def test_rework_loop_becomes_a_jump(self):
        process = parse_text(
            "Менеджер проверяет заявку.\n"
            "Менеджер отклоняет заявку и заявка возвращается к проверке заявки.\n"
        )
        assert kinds(process.root) == ["IRActivity", "IRActivity", "IRGoto"]
        goto = process.root.items[2]
        assert isinstance(goto, IRGoto)
        assert "проверке заявки" in goto.target


class TestSemantics:
    def test_detects_actors_and_lanes(self):
        process = parse_text(
            "Менеджер проверяет заявку.\nБухгалтер выставляет счёт.\nМенеджер уведомляет клиента."
        )
        assert process.lane_names() == ["Менеджер", "Бухгалтер"]
        assert [element.actor for element in process.root] == ["Менеджер", "Бухгалтер", "Менеджер"]

    def test_inherits_the_actor_of_the_previous_step(self):
        process = parse_text("Менеджер проверяет заявку.\nЗатем готовит договор.")
        assert process.root.items[1].actor == "Менеджер"

    def test_classifies_task_types(self):
        process = parse_text(
            "Система автоматически резервирует товар.\n"
            "Менеджер отправляет уведомление клиенту.\n"
            "Бухгалтер проверяет счёт по бизнес-правилам.\n"
        )
        assert [element.activity_type for element in process.root] == [
            ActivityType.SERVICE,
            ActivityType.SEND,
            ActivityType.BUSINESS_RULE,
        ]

    def test_detects_timer_and_message_events(self):
        process = parse_text("Менеджер ожидает подтверждения от клиента.")
        event = process.root.items[0]
        assert isinstance(event, IREvent)
        assert event.trigger is EventTrigger.MESSAGE

    def test_leading_delay_becomes_a_timer_event(self):
        process = parse_text("Через 3 дня заявка закрывается автоматически.")
        event = process.root.items[0]
        assert isinstance(event, IREvent)
        assert event.trigger is EventTrigger.TIMER
        assert event.timer == "P3D"
        # the action itself survives as a separate step
        assert isinstance(process.root.items[1], IRActivity)

    def test_recurring_delay_is_a_cycle(self):
        event = parse_text("Ежедневно формируется отчёт.").root.items[0]
        assert event.trigger is EventTrigger.TIMER
        assert event.timer == "Ежедневно"

    def test_duration_inside_a_sentence_stays_part_of_the_step(self):
        process = parse_text("Менеджер проверяет заявку в течение 2 часов.")
        assert len(process.root) == 1
        assert isinstance(process.root.items[0], IRActivity)

    def test_english_descriptions(self):
        process = parse_text(
            "The process starts when an offer is received.\n"
            "The recruiter creates the employee record.\n"
            "If the workplace is ready, then the manager schedules the first day, "
            "otherwise the IT department orders the equipment.\n"
            "The process ends."
        )
        assert process.language == "en"
        assert process.lane_names() == ["Recruiter", "Manager", "IT department"]
        branch = next(item for item in process.root if isinstance(item, IRBranch))
        assert [arm.label for arm in branch.arms] == ["Yes", "No"]


class TestOptions:
    def test_verbatim_naming_keeps_the_original_wording(self):
        process = parse_text(
            "Менеджер проверяет заявку.", ParserOptions(infinitive_names=False)
        )
        assert process.root.items[0].text == "Проверяет заявку"

    def test_lane_detection_can_be_disabled(self):
        process = parse_text("Менеджер проверяет заявку.", ParserOptions(detect_lanes=False))
        assert process.lane_names() == []
        assert process.root.items[0].actor is None

    def test_conjoined_actions_can_be_kept_together(self):
        process = parse_text(
            "Менеджер проверяет заявку и отправляет уведомление.",
            ParserOptions(split_conjoined_actions=False),
        )
        assert len(process.root) == 1


def test_empty_input_produces_an_empty_process():
    process = parse_text("   \n\n")
    assert len(process.root) == 0
