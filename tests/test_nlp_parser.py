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


class TestProse:
    """Free-running prose: the way process descriptions are actually written.

    Every case here comes from a real description of an exam procedure, which
    states its decisions across sentence boundaries, drops subjects and keeps
    half of its remarks in brackets.
    """

    def test_complementary_sentences_form_one_decision(self):
        process = parse_text(
            "Если студент допущен, преподаватель принимает ответ.\n"
            "Если студент не допущен, преподаватель сообщает об отказе.\n"
        )
        branch = process.root.items[0]
        assert isinstance(branch, IRBranch)
        assert len(process.root) == 1  # one gateway, not two
        assert [arm.label for arm in branch.arms] == ["Да", "Нет"]
        assert branch.arms[1].is_default is True

    def test_negated_sentence_first_still_labels_both_arms(self):
        process = parse_text(
            "Если не допустить студента, преподаватель сообщает об отказе.\n"
            "Если студент допущен, преподаватель принимает ответ.\n"
        )
        branch = process.root.items[0]
        assert isinstance(branch, IRBranch)
        assert [arm.label for arm in branch.arms] == ["Да", "Нет"]

    def test_two_positive_alternatives_keep_their_own_labels(self):
        process = parse_text(
            "Если студент согласен с оценкой, преподаватель выставляет оценку.\n"
            "Если студент хочет апеллировать, преподаватель принимает апелляцию.\n"
        )
        branch = process.root.items[0]
        assert isinstance(branch, IRBranch)
        assert [arm.label for arm in branch.arms] == ["Да", "Студент хочет апеллировать"]

    def test_unrelated_conditions_stay_separate_decisions(self):
        process = parse_text(
            "Если заявка корректна, менеджер регистрирует заявку.\n"
            "Если склад загружен, логист переносит отгрузку.\n"
        )
        assert [type(item).__name__ for item in process.root] == ["IRBranch", "IRBranch"]

    def test_parenthetical_remark_becomes_documentation(self):
        process = parse_text("Преподаватель выставляет оценку (например, по десятибалльной шкале).")
        activity = process.root.items[0]
        assert activity.text == "Выставить оценку"
        assert "десятибалльной" in activity.source

    def test_remark_about_the_end_becomes_an_end_event(self):
        process = parse_text(
            'Бизнес-процесс "Сдача экзамена" начинается с момента входа студента.\n'
            'Преподаватель выставляет оценку (процесс "Сдача экзамена" заканчивается).\n'
        )
        assert process.name == "Сдача экзамена"
        assert process.root.items[0].text == "Вход студента"
        assert process.root.items[-1].position is EventPosition.END

    def test_the_process_ending_may_be_named_by_its_subject(self):
        process = parse_text(
            'Бизнес-процесс "Сдача экзамена" начинается с момента входа студента.\n'
            "Преподаватель сообщает об отказе и для студента этот экзамен заканчивается.\n"
        )
        assert isinstance(process.root.items[-1], IREvent)
        assert process.root.items[-1].position is EventPosition.END

    def test_pronoun_subject_takes_the_role_from_the_condition(self):
        process = parse_text(
            "Преподаватель задаёт вопрос.\n"
            "Если студент не готов отвечать, он берёт дополнительное время.\n"
        )
        branch = process.root.items[1]
        assert isinstance(branch, IRBranch)
        step = branch.arms[0].body.items[0]
        assert step.text == "Взять дополнительное время"
        assert step.actor == "Студент"

    def test_impersonal_announcement_names_the_step_by_its_noun(self):
        process = parse_text("Менеджер получает заявку.\nЗатем происходит проверка документов.")
        assert process.root.items[1].text == "Проверка документов"

    def test_verb_initial_passive_becomes_an_action(self):
        process = parse_text("Преподаватель принимает ответ.\nЕму даётся дополнительное время.")
        assert process.root.items[1].text == "Дать дополнительное время"

    def test_role_after_an_adverbial_preface_is_still_the_actor(self):
        process = parse_text("Исходя из ответа на вопрос преподаватель называет оценку.")
        activity = process.root.items[0]
        assert activity.text == "Назвать оценку"
        assert activity.actor == "Преподаватель"

    def test_comma_separates_two_clauses(self):
        process = parse_text("Студент тянет билет, называет преподавателю его номер.")
        assert [element.text for element in process.root] == [
            "Тянуть билет",
            "Назвать преподавателю его номер",
        ]

    def test_subordinate_clause_stays_part_of_its_step(self):
        process = parse_text("Преподаватель сообщает студенту, что он не допущен к экзамену.")
        assert len(process.root) == 1
        assert process.root.items[0].text == "Сообщить студенту, что он не допущен к экзамену"
