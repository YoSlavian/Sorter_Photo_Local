"""Deterministic first, model only where the rules fell short.

The rule parser is reproducible but has a vocabulary; a model has no
vocabulary limit but no reproducibility.  Hybrid mode keeps the first property
where it can and spends the second only where it must:

1. parse deterministically;
2. look for what the description left open (:mod:`bpmn_architect.analysis`);
3. if nothing is open, return the deterministic result **unchanged** — same
   input, same diagram, no model call, no cost;
4. otherwise show the model the text, the deterministic reading, and the open
   questions, and ask for a corrected version.

Step 3 is the point: on well-written descriptions hybrid mode behaves exactly
like deterministic mode.
"""

from __future__ import annotations

from bpmn_architect.interpreters.base import (
    InterpretationResult,
    InterpreterError,
    InterpreterMode,
)
from bpmn_architect.interpreters.llm import SYSTEM_PROMPT, LLMInterpreter, extract_dsl
from bpmn_architect.interpreters.providers.base import LLMConfig, LLMProvider
from bpmn_architect.interpreters.rule_based import RuleBasedInterpreter
from bpmn_architect.parsing import ParserOptions
from bpmn_architect.parsing.dsl import parse_dsl, render_dsl

__all__ = ["HybridInterpreter"]

_REVISION_TEMPLATE = """\
Here is a business process description:

{text}

A rule-based parser produced this DSL from it:

{dsl}

These points are unclear in the description, and the parser could not resolve \
them:

{questions}

Produce a corrected DSL. Keep everything the parser got right, change only \
what the listed points concern, and do not invent steps the description does \
not contain. Answer with the DSL only, inside one ``` fenced block.
"""


class HybridInterpreter:
    """Rule-based interpretation, refined by a model only where it is unclear."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        config: LLMConfig | None = None,
        *,
        syntax: str = "auto",
        options: ParserOptions | None = None,
    ) -> None:
        self.rule_based = RuleBasedInterpreter(syntax=syntax, options=options)
        self._provider = provider
        self._config = config

    def interpret(self, text: str) -> InterpretationResult:
        base = self.rule_based.interpret(text)
        questions = self._open_questions(base)
        if not questions:
            base.mode = InterpreterMode.HYBRID
            base.note("the description was unambiguous; no model call was made")
            return base

        try:
            llm = LLMInterpreter(self._provider, self._config)
            provider = llm.provider
            if not provider.available():
                raise InterpreterError("no provider")
            prompt = _REVISION_TEMPLATE.format(
                text=text.strip(),
                dsl=render_dsl(base.ir),
                questions="\n".join(f"- {question}" for question in questions),
            )
            answer = provider.complete(SYSTEM_PROMPT, prompt)
            ir = parse_dsl(extract_dsl(answer))
        except Exception as error:  # noqa: BLE001 - any failure falls back
            base.mode = InterpreterMode.HYBRID
            base.note(
                f"{len(questions)} unclear point(s) were left as parsed: "
                f"the model was not used ({error})"
            )
            return base

        result = InterpretationResult(
            ir=ir,
            mode=InterpreterMode.HYBRID,
            provider=llm.provider.name,
            deterministic=False,
        )
        result.note(f"the model resolved {len(questions)} unclear point(s)")
        return result

    def _open_questions(self, base: InterpretationResult) -> list[str]:
        from bpmn_architect.analysis import analyse_ambiguity
        from bpmn_architect.building import build_model

        model = build_model(base.ir).model
        return [
            clarification.question
            for clarification in analyse_ambiguity(model, language=base.ir.language)
        ]
