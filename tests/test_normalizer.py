from bpmn_architect.parsing.normalizer import (
    clean_label,
    normalize_text,
    read_lines,
    split_sentences,
)


class TestReadLines:
    def test_strips_bullets_and_ordinals(self):
        lines = read_lines("1. Первый шаг\n- Второй шаг\n")
        assert [line.text for line in lines] == ["Первый шаг", "Второй шаг"]
        assert lines[0].ordinal == "1"
        assert lines[1].bullet == "-"

    def test_nested_ordinals_imply_indentation(self):
        lines = read_lines("2. Шаг\n2.1. Подшаг\n")
        assert lines[0].indent == 0
        assert lines[1].indent == 2

    def test_skips_comments_and_blank_lines(self):
        assert [line.text for line in read_lines("# заметка\n\nШаг\n")] == ["Шаг"]

    def test_normalizes_typography(self):
        normalized = normalize_text("«Заявка» получена")
        assert normalized == '"Заявка" получена'


class TestSplitSentences:
    def test_splits_on_terminators(self):
        assert split_sentences("Первое. Второе! Третье?") == ["Первое.", "Второе!", "Третье?"]

    def test_respects_abbreviations(self):
        assert split_sentences("Проверяет документы и т.д. Затем подписывает.") == [
            "Проверяет документы и т.д.",
            "Затем подписывает.",
        ]

    def test_keeps_decimals_together(self):
        assert split_sentences("Сумма 100.5 руб. оплачена.") == ["Сумма 100.5 руб. оплачена."]


class TestCleanLabel:
    def test_removes_trailing_punctuation_and_quotes(self):
        assert clean_label(' "Заявка получена".  ') == "Заявка получена"
        assert clean_label("Проверить заявку;") == "Проверить заявку"
