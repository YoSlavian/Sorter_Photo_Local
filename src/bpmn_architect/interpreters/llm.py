"""Interpreting a description with a language model.

The model is not asked for JSON, and certainly not for BPMN XML.  It is asked
for **the project's own DSL**, which is then parsed by the existing, tested
:class:`~bpmn_architect.parsing.dsl.DslParser`.

That choice is deliberate.  A model that emits a nested JSON tree can produce
structurally valid JSON that is nonsense as a process; a model that emits DSL
runs into a real grammar with real error messages, and anything it invents is
rejected at the door.  The parser — not the prompt — is what guarantees the
result is a well-formed process, and a malformed answer becomes a retry with
the parser's own error rather than a corrupt diagram.
"""

from __future__ import annotations

import re

from bpmn_architect.errors import ParseError
from bpmn_architect.interpreters.base import (
    InterpretationResult,
    InterpreterError,
    InterpreterMode,
    LLMUnavailable,
)
from bpmn_architect.interpreters.providers.base import LLMConfig, LLMProvider, resolve_provider
from bpmn_architect.parsing.dsl import parse_dsl

__all__ = ["LLMInterpreter", "SYSTEM_PROMPT", "extract_dsl"]

_FENCE_RE = re.compile(r"```[a-zA-Z-]*\s*\n(?P<body>.*?)```", re.DOTALL)

SYSTEM_PROMPT = """\
You convert business process descriptions into a small block DSL. Answer with \
the DSL only, inside one ``` fenced block, and nothing else.

Grammar (indentation is two spaces per level):

  process: <process name>
  lane: <role>                    one per participating role, in top-down order

  start: <event name> (message)   process start; triggers: message, timer, signal
  end: <event name>               process end
  task[<role>]: <name>            generic activity
  user[<role>]: <name>            performed by a person
  service[<role>]: <name>         performed by a system automatically
  send[<role>]: <name>            sends a message
  receive[<role>]: <name>         waits for and receives a message
  rule[<role>]: <name>            decided by business rules
  subprocess[<role>]: <name>      collapsed sub-process
  message[<role>]: <name>         intermediate event, waiting for a message
  timer[<role>]: <name> (timer=P3D)   intermediate event, waiting for a delay
  xor[<role>]: <question>?        exclusive decision; children are case/else
    case <label>:                 one outcome, body indented below
    else <label>:                 the default outcome
  and:                            parallel split and join
    branch:                       one concurrent path, body indented below
  goto: <@anchor or step name>    loop back to an earlier step

  Any element may end with @anchor to become a jump target.

Rules:
- Name activities as a verb in the infinitive plus its object: "Проверить \
заявку", "Create the invoice". Keep the language of the input.
- Every role mentioned in the text becomes a lane, and every activity names \
the role performing it in square brackets.
- A decision is xor with at least two cases; label the outcomes the way the \
text does ("Да"/"Нет", "Yes"/"No", or the named outcomes).
- Rework ("returns for correction", "возвращается на доработку") is goto, not \
a duplicate task.
- Do not invent steps the description does not contain. If something is \
unclear, model it as written rather than guessing details.
"""

_USER_TEMPLATE = """\
Convert this business process description into the DSL:

{text}
"""

_RETRY_TEMPLATE = """\
The DSL you produced could not be parsed:

{error}

Here is what you produced:

{answer}

Fix it and answer with the corrected DSL only.
"""


def extract_dsl(answer: str) -> str:
    """Pull the DSL out of a model answer, fenced or bare."""
    match = _FENCE_RE.search(answer)
    if match:
        return match.group("body").strip()
    return answer.strip()


class LLMInterpreter:
    """Reads a description with a language model, validated by the DSL parser."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        config: LLMConfig | None = None,
        *,
        max_attempts: int = 2,
    ) -> None:
        self.provider = provider or resolve_provider(config)
        self.max_attempts = max(1, max_attempts)

    def interpret(self, text: str) -> InterpretationResult:
        if not text.strip():
            raise InterpreterError("the description is empty")
        if not self.provider.available():
            raise LLMUnavailable(
                f"the {self.provider.name!r} provider is not configured; "
                f"use deterministic mode or set the provider's API key"
            )

        prompt = _USER_TEMPLATE.format(text=text.strip())
        last_error: ParseError | None = None
        answer = ""
        for attempt in range(self.max_attempts):
            answer = self.provider.complete(SYSTEM_PROMPT, prompt)
            dsl = extract_dsl(answer)
            try:
                ir = parse_dsl(dsl)
            except ParseError as error:
                last_error = error
                prompt = _RETRY_TEMPLATE.format(error=error, answer=dsl)
                continue
            result = InterpretationResult(
                ir=ir,
                mode=InterpreterMode.AI,
                provider=self.provider.name,
                deterministic=False,
            )
            if attempt:
                result.note(f"the model needed {attempt + 1} attempts to produce valid DSL")
            return result

        raise InterpreterError(
            f"the model did not produce valid DSL in {self.max_attempts} attempts: {last_error}"
        )
