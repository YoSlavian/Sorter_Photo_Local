from bpmn_architect.parsing.morphology import (
    capitalize_first,
    looks_like_verb,
    nominalize,
    normalize_actor,
    to_infinitive,
    to_nominative_object,
)


class TestToInfinitive:
    def test_rewrites_dictionary_verbs(self):
        assert to_infinitive("проверяет заявку") == "проверить заявку"
        assert to_infinitive("формирует счёт на оплату") == "сформировать счёт на оплату"

    def test_handles_plural_forms(self):
        assert to_infinitive("согласовывают договор") == "согласовать договор"
        assert to_infinitive("проверяют документы") == "проверить документы"

    def test_falls_back_to_suffix_rules(self):
        assert to_infinitive("модифицирует запись") == "модифицировать запись"

    def test_leaves_unknown_wording_untouched(self):
        # Nothing is guessed: a phrase that does not start with a verb survives
        # exactly as written, which is what makes the rewrite safe to apply.
        assert to_infinitive("заявка получена") == "заявка получена"
        assert to_infinitive("") == ""

    def test_handles_english(self):
        assert to_infinitive("checks the request") == "check the request"
        assert to_infinitive("verifies the documents") == "verify the documents"
        assert to_infinitive("process starts") == "process starts"


class TestLooksLikeVerb:
    def test_recognises_verbs(self):
        assert looks_like_verb("проверяет")
        assert looks_like_verb("отправляют")
        assert looks_like_verb("checks")

    def test_rejects_nouns_that_end_like_verbs(self):
        assert not looks_like_verb("счёт")
        assert not looks_like_verb("отчёт")
        assert not looks_like_verb("процесс")
        assert not looks_like_verb("process")


class TestActorsAndLabels:
    def test_drops_english_articles(self):
        assert normalize_actor("the recruiter") == "Recruiter"
        assert normalize_actor("The IT department") == "IT department"

    def test_keeps_acronyms_intact(self):
        assert capitalize_first("CRM обновляется") == "CRM обновляется"

    def test_nominalizes_trigger_phrases(self):
        assert nominalize("получения заявки") == "получение заявки"
        assert nominalize("поступлении обращения") == "поступление обращения"

    def test_turns_objects_into_subjects(self):
        assert to_nominative_object("категорию обращения") == "категория обращения"
        assert to_nominative_object("заявку клиента") == "заявка клиента"
        assert to_nominative_object("результат проверки") == "результат проверки"
