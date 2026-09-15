"""Deterministic, AI and hybrid interpretation modes."""

import pytest

from bpmn_architect.domain.ir import IRProcess
from bpmn_architect.interpreters import (
    HybridInterpreter,
    InterpreterMode,
    LLMInterpreter,
    LLMUnavailable,
    RuleBasedInterpreter,
    create_interpreter,
)
from bpmn_architect.interpreters.llm import extract_dsl
from bpmn_architect.interpreters.providers import LLMConfig, resolve_provider

CLEAR = """\
Процесс начинается с заявки.
Менеджер проверяет заявку.
Менеджер оформляет договор.
Процесс завершается.
"""
VAGUE = """\
Процесс начинается с заявки.
Менеджер проверяет заявку.
Далее выполняется обработка.
Процесс завершается.
"""

DSL_ANSWER = """\
Here is the diagram:

```dsl
process: Обработка заявки
lane: Менеджер

start: Заявка получена
user[Менеджер]: Проверить заявку
end: Готово
```
"""


class FakeProvider:
    """A provider that returns a canned answer, for testing the plumbing."""

    name = "fake"

    def __init__(self, answers: list[str], available: bool = True):
        self.answers = list(answers)
        self._available = available
        self.calls: list[tuple[str, str]] = []

    def available(self) -> bool:
        return self._available

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.answers.pop(0) if self.answers else ""


class TestFactory:
    def test_deterministic_is_the_default(self):
        assert isinstance(create_interpreter(), RuleBasedInterpreter)

    def test_modes_map_to_implementations(self):
        assert isinstance(create_interpreter("ai"), LLMInterpreter)
        assert isinstance(create_interpreter("hybrid"), HybridInterpreter)

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError):
            create_interpreter("magic")

    def test_deterministic_mode_needs_no_provider(self):
        result = create_interpreter(InterpreterMode.DETERMINISTIC).interpret(CLEAR)
        assert result.deterministic
        assert isinstance(result.ir, IRProcess)
        assert result.provider == ""


class TestRuleBased:
    def test_matches_the_plain_parser(self):
        result = RuleBasedInterpreter().interpret(CLEAR)
        assert [element.text for element in result.ir.root] == [
            "Заявка",
            "Проверить заявку",
            "Оформить договор",
            "Конец процесса",
        ]

    def test_is_reproducible(self):
        first = RuleBasedInterpreter().interpret(CLEAR)
        second = RuleBasedInterpreter().interpret(CLEAR)
        assert [e.text for e in first.ir.root] == [e.text for e in second.ir.root]


class TestLLMInterpreter:
    def test_parses_a_fenced_answer(self):
        provider = FakeProvider([DSL_ANSWER])
        result = LLMInterpreter(provider).interpret(CLEAR)
        assert result.mode is InterpreterMode.AI
        assert result.deterministic is False
        assert result.ir.name == "Обработка заявки"
        assert [element.text for element in result.ir.root] == [
            "Заявка получена",
            "Проверить заявку",
            "Готово",
        ]

    def test_retries_once_on_invalid_dsl(self):
        provider = FakeProvider(["```\nнепонятно что\n```", DSL_ANSWER])
        result = LLMInterpreter(provider).interpret(CLEAR)
        assert len(provider.calls) == 2
        assert any("attempts" in note for note in result.notes)
        # The retry prompt must carry the parser's own error back to the model.
        assert "could not be parsed" in provider.calls[1][1]

    def test_gives_up_after_the_attempt_budget(self):
        provider = FakeProvider(["nonsense", "nonsense"])
        with pytest.raises(Exception, match="did not produce valid DSL"):
            LLMInterpreter(provider).interpret(CLEAR)

    def test_unconfigured_provider_is_reported_clearly(self):
        with pytest.raises(LLMUnavailable, match="not configured"):
            LLMInterpreter(FakeProvider([], available=False)).interpret(CLEAR)

    def test_empty_text_is_rejected(self):
        with pytest.raises(Exception, match="empty"):
            LLMInterpreter(FakeProvider([DSL_ANSWER])).interpret("   ")

    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            ("```dsl\ntask: A\n```", "task: A"),
            ("```\ntask: A\n```", "task: A"),
            ("task: A", "task: A"),
            ("Вот:\n```bpmn\ntask: A\n```\nготово", "task: A"),
        ],
    )
    def test_dsl_extraction(self, answer, expected):
        assert extract_dsl(answer) == expected


class TestHybrid:
    def test_clear_text_never_calls_the_model(self):
        provider = FakeProvider([DSL_ANSWER])
        result = HybridInterpreter(provider).interpret(CLEAR)
        assert provider.calls == []
        assert result.deterministic is True
        assert "unambiguous" in result.notes[0]

    def test_vague_text_asks_the_model(self):
        provider = FakeProvider([DSL_ANSWER])
        result = HybridInterpreter(provider).interpret(VAGUE)
        assert len(provider.calls) == 1
        assert result.deterministic is False
        assert result.ir.name == "Обработка заявки"

    def test_the_prompt_carries_the_deterministic_reading_and_the_questions(self):
        provider = FakeProvider([DSL_ANSWER])
        HybridInterpreter(provider).interpret(VAGUE)
        prompt = provider.calls[0][1]
        assert "user[Менеджер]: Проверить заявку" in prompt
        assert "unclear" in prompt

    def test_falls_back_when_the_provider_is_missing(self):
        result = HybridInterpreter(FakeProvider([], available=False)).interpret(VAGUE)
        assert result.deterministic is True
        assert any("was not used" in note for note in result.notes)

    def test_falls_back_when_the_model_answer_is_unusable(self):
        result = HybridInterpreter(FakeProvider(["ерунда"])).interpret(VAGUE)
        assert result.deterministic is True
        assert any("was not used" in note for note in result.notes)


class TestProviders:
    @pytest.mark.parametrize("name", ["anthropic", "openai", "local"])
    def test_every_provider_resolves(self, name):
        provider = resolve_provider(LLMConfig(provider=name))
        assert provider.name in {name, "local"}

    def test_unknown_provider_is_rejected(self):
        with pytest.raises(LLMUnavailable, match="unknown LLM provider"):
            resolve_provider(LLMConfig(provider="telepathy"))

    def test_providers_report_unavailable_without_credentials(self):
        assert resolve_provider(LLMConfig(provider="openai")).available() is False

    def test_config_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("BPMN_ARCHITECT_LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        config = LLMConfig.from_env()
        assert config.provider == "openai"
        assert config.api_key == "test-key"
