"""Deterministic block DSL for process descriptions.

Natural language is convenient but inherently lossy.  When an author needs a
diagram to come out *exactly* a certain way — a specific task type, an explicit
condition expression, a named anchor to loop back to — they write the DSL
instead.  Both front ends emit the same :class:`~bpmn_architect.domain.ir.IRProcess`,
so everything downstream is shared.

Grammar (indentation defines nesting, two spaces per level)::

    process: Обработка заявки
    lane: Менеджер

    start: Заявка получена (message)
    task[Менеджер]: Проверить заявку @check
    xor: Заявка корректна?
      case Да (condition=valid == true):
        service: Выставить счёт
      else Нет:
        task: Отклонить заявку
        goto: @check
    and:
      branch:
        task: Зарезервировать товар
      branch:
        task: Проверить кредитный лимит
    end: Заявка обработана

Every line is ``keyword[actor] argument: text (options) @anchor``; only the
keyword and the colon are mandatory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bpmn_architect.domain.ir import (
    ActivityType,
    BranchType,
    EventPosition,
    EventTrigger,
    IRActivity,
    IRArm,
    IRBranch,
    IRElement,
    IREvent,
    IRGoto,
    IRParallel,
    IRProcess,
    IRSequence,
)
from bpmn_architect.errors import ParseError
from bpmn_architect.parsing.lexicon import detect_language
from bpmn_architect.parsing.morphology import capitalize_first
from bpmn_architect.parsing.normalizer import Line, clean_label, read_lines

__all__ = ["DslParser", "parse_dsl", "looks_like_dsl"]

_LINE_RE = re.compile(
    r"""^(?P<keyword>[\wЀ-ӿ-]+)
         (?:\[(?P<actor>[^\]]*)\])?
         (?:\s+(?P<argument>[^:\[\]]*?))?
         \s*:\s*
         (?P<text>.*)$""",
    re.VERBOSE,
)
_ANCHOR_RE = re.compile(r"\s*@(?P<anchor>[\w.-]+)\s*$")
_OPTIONS_RE = re.compile(r"\s*\((?P<options>[^()]*)\)\s*$")

_ACTIVITY_KEYWORDS: dict[str, ActivityType] = {
    "task": ActivityType.TASK,
    "задача": ActivityType.TASK,
    "user": ActivityType.USER,
    "usertask": ActivityType.USER,
    "пользователь": ActivityType.USER,
    "service": ActivityType.SERVICE,
    "сервис": ActivityType.SERVICE,
    "система": ActivityType.SERVICE,
    "manual": ActivityType.MANUAL,
    "вручную": ActivityType.MANUAL,
    "script": ActivityType.SCRIPT,
    "скрипт": ActivityType.SCRIPT,
    "send": ActivityType.SEND,
    "отправить": ActivityType.SEND,
    "receive": ActivityType.RECEIVE,
    "получить": ActivityType.RECEIVE,
    "rule": ActivityType.BUSINESS_RULE,
    "правило": ActivityType.BUSINESS_RULE,
    "subprocess": ActivityType.SUB_PROCESS,
    "подпроцесс": ActivityType.SUB_PROCESS,
    "call": ActivityType.CALL,
    "вызов": ActivityType.CALL,
}

_EVENT_KEYWORDS: dict[str, tuple[EventPosition, EventTrigger]] = {
    "start": (EventPosition.START, EventTrigger.NONE),
    "начало": (EventPosition.START, EventTrigger.NONE),
    "end": (EventPosition.END, EventTrigger.NONE),
    "конец": (EventPosition.END, EventTrigger.NONE),
    "catch": (EventPosition.INTERMEDIATE_CATCH, EventTrigger.NONE),
    "wait": (EventPosition.INTERMEDIATE_CATCH, EventTrigger.MESSAGE),
    "ожидание": (EventPosition.INTERMEDIATE_CATCH, EventTrigger.MESSAGE),
    "message": (EventPosition.INTERMEDIATE_CATCH, EventTrigger.MESSAGE),
    "сообщение": (EventPosition.INTERMEDIATE_CATCH, EventTrigger.MESSAGE),
    "timer": (EventPosition.INTERMEDIATE_CATCH, EventTrigger.TIMER),
    "таймер": (EventPosition.INTERMEDIATE_CATCH, EventTrigger.TIMER),
    "throw": (EventPosition.INTERMEDIATE_THROW, EventTrigger.NONE),
    "signal": (EventPosition.INTERMEDIATE_THROW, EventTrigger.SIGNAL),
    "сигнал": (EventPosition.INTERMEDIATE_THROW, EventTrigger.SIGNAL),
}

_GATEWAY_KEYWORDS: dict[str, BranchType] = {
    "xor": BranchType.EXCLUSIVE,
    "if": BranchType.EXCLUSIVE,
    "если": BranchType.EXCLUSIVE,
    "выбор": BranchType.EXCLUSIVE,
    "or": BranchType.INCLUSIVE,
    "inclusive": BranchType.INCLUSIVE,
    "или": BranchType.INCLUSIVE,
    "event-gateway": BranchType.EVENT_BASED,
    "eventgateway": BranchType.EVENT_BASED,
    "событие-выбор": BranchType.EVENT_BASED,
}

_PARALLEL_KEYWORDS = frozenset({"and", "parallel", "параллельно", "и"})
_BRANCH_KEYWORDS = frozenset({"branch", "ветка", "поток"})
_CASE_KEYWORDS = frozenset({"case", "вариант", "ветвь"})
_ELSE_KEYWORDS = frozenset({"else", "default", "otherwise", "иначе", "поумолчанию"})
_GOTO_KEYWORDS = frozenset({"goto", "loop", "переход", "возврат"})
_HEADER_KEYWORDS = frozenset(
    {"process", "процесс", "lane", "дорожка", "роль", "id", "doc", "описание", "language", "язык"}
)

_TRIGGER_ALIASES: dict[str, EventTrigger] = {
    "message": EventTrigger.MESSAGE,
    "сообщение": EventTrigger.MESSAGE,
    "timer": EventTrigger.TIMER,
    "таймер": EventTrigger.TIMER,
    "signal": EventTrigger.SIGNAL,
    "сигнал": EventTrigger.SIGNAL,
    "error": EventTrigger.ERROR,
    "ошибка": EventTrigger.ERROR,
    "escalation": EventTrigger.ESCALATION,
    "эскалация": EventTrigger.ESCALATION,
    "conditional": EventTrigger.CONDITIONAL,
    "terminate": EventTrigger.TERMINATE,
    "прерывание": EventTrigger.TERMINATE,
}


@dataclass(slots=True)
class _Directive:
    """One parsed DSL line together with its nested lines."""

    keyword: str
    actor: str | None
    argument: str
    text: str
    anchor: str | None
    options: dict[str, str]
    line: int
    indent: int
    raw: str
    children: list[_Directive] = field(default_factory=list)


def looks_like_dsl(raw_text: str) -> bool:
    """Heuristic front-end detection: does this text use the block DSL?

    A document qualifies when a clear majority of its lines are well-formed
    directives *and* at least one of them is structural (not just a header), so
    ordinary prose containing a colon is never mistaken for DSL.
    """
    lines = [line for line in read_lines(raw_text) if line.text]
    if not lines:
        return False
    keywords = 0
    structural = False
    for line in lines:
        match = _LINE_RE.match(line.text)
        if not match:
            continue
        keyword = match.group("keyword").casefold()
        if keyword in _KNOWN_KEYWORDS:
            keywords += 1
            if keyword not in _HEADER_KEYWORDS:
                structural = True
    return structural and keywords >= max(1, round(len(lines) * 0.6))


class DslParser:
    """Parses the block DSL into an :class:`IRProcess`."""

    def parse(self, raw_text: str) -> IRProcess:
        lines = read_lines(raw_text)
        directives = [self._parse_line(line) for line in lines]
        tree = _nest(directives)

        process = IRProcess(language=detect_language(raw_text))
        body: list[_Directive] = []
        for directive in tree:
            if directive.keyword in _HEADER_KEYWORDS:
                self._apply_header(process, directive)
            else:
                body.append(directive)
        process.root = self._sequence(body)
        for element in _collect_actors(process.root):
            process.ensure_lane(element)
        return process

    # -- line level ----------------------------------------------------------

    def _parse_line(self, line: Line) -> _Directive:
        match = _LINE_RE.match(line.text)
        if match is None:
            raise ParseError(
                "expected a directive of the form 'keyword: text'", line.number, line.text
            )
        keyword = match.group("keyword").casefold()
        if keyword not in _KNOWN_KEYWORDS:
            raise ParseError(f"unknown directive {keyword!r}", line.number, line.text)

        text = match.group("text").strip()
        anchor = None
        if anchor_match := _ANCHOR_RE.search(text):
            anchor = anchor_match.group("anchor")
            text = text[: anchor_match.start()].strip()
        options: dict[str, str] = {}
        argument = (match.group("argument") or "").strip()
        if option_match := _OPTIONS_RE.search(text):
            options = _parse_options(option_match.group("options"))
            text = text[: option_match.start()].strip()
        if option_match := _OPTIONS_RE.search(argument):
            options.update(_parse_options(option_match.group("options")))
            argument = argument[: option_match.start()].strip()

        actor = match.group("actor")
        return _Directive(
            keyword=keyword,
            actor=(actor or "").strip() or None,
            argument=argument,
            text=text,
            anchor=anchor,
            options=options,
            line=line.number,
            indent=line.indent,
            raw=line.text,
        )

    # -- headers -------------------------------------------------------------

    def _apply_header(self, process: IRProcess, directive: _Directive) -> None:
        if directive.keyword in {"process", "процесс"}:
            process.name = capitalize_first(clean_label(directive.text))
        elif directive.keyword in {"lane", "дорожка", "роль"}:
            process.ensure_lane(clean_label(directive.text))
        elif directive.keyword == "id":
            process.options["id"] = directive.text.strip()
        elif directive.keyword in {"doc", "описание"}:
            process.documentation = directive.text.strip()
        elif directive.keyword in {"language", "язык"}:
            process.language = directive.text.strip().casefold()[:2] or process.language

    # -- block level ---------------------------------------------------------

    def _sequence(self, directives: list[_Directive]) -> IRSequence:
        sequence = IRSequence()
        for directive in directives:
            sequence.append(self._element(directive))
        return sequence

    def _element(self, directive: _Directive) -> IRElement:
        keyword = directive.keyword
        if keyword in _GATEWAY_KEYWORDS:
            return self._branch(directive)
        if keyword in _PARALLEL_KEYWORDS:
            return self._parallel(directive)
        if keyword in _GOTO_KEYWORDS:
            return IRGoto(
                text=clean_label(directive.text) or "Возврат",
                target=directive.text.strip().lstrip("@") or (directive.anchor or ""),
                anchor=directive.anchor,
                line=directive.line,
                source=directive.raw,
            )
        if keyword in _EVENT_KEYWORDS:
            return self._event(directive)
        if keyword in _ACTIVITY_KEYWORDS:
            return self._activity(directive)
        if keyword in _CASE_KEYWORDS | _ELSE_KEYWORDS | _BRANCH_KEYWORDS:
            raise ParseError(
                f"{keyword!r} is only allowed directly inside a gateway block",
                directive.line,
                directive.raw,
            )
        raise ParseError(f"unsupported directive {keyword!r}", directive.line, directive.raw)

    def _activity(self, directive: _Directive) -> IRActivity:
        return IRActivity(
            text=capitalize_first(clean_label(directive.text)),
            actor=directive.actor,
            activity_type=_ACTIVITY_KEYWORDS[directive.keyword],
            anchor=directive.anchor,
            line=directive.line,
            source=directive.raw,
        )

    def _event(self, directive: _Directive) -> IREvent:
        position, trigger = _EVENT_KEYWORDS[directive.keyword]
        timer = directive.options.get("timer", "")
        for key in directive.options:
            if key in _TRIGGER_ALIASES:
                trigger = _TRIGGER_ALIASES[key]
        if "trigger" in directive.options:
            trigger = _TRIGGER_ALIASES.get(
                directive.options["trigger"].casefold(), EventTrigger.NONE
            )
        if timer:
            trigger = EventTrigger.TIMER
        if trigger is EventTrigger.TIMER and not timer:
            timer = clean_label(directive.text)
        return IREvent(
            text=capitalize_first(clean_label(directive.text)),
            actor=directive.actor,
            position=position,
            trigger=trigger,
            timer=timer,
            anchor=directive.anchor,
            line=directive.line,
            source=directive.raw,
        )

    def _branch(self, directive: _Directive) -> IRBranch:
        branch = IRBranch(
            text=capitalize_first(clean_label(directive.text)) or "?",
            actor=directive.actor,
            branch_type=_GATEWAY_KEYWORDS[directive.keyword],
            anchor=directive.anchor,
            line=directive.line,
            source=directive.raw,
        )
        for child in directive.children:
            if child.keyword in _CASE_KEYWORDS:
                branch.add_arm(self._arm(child, default=False))
            elif child.keyword in _ELSE_KEYWORDS:
                branch.add_arm(self._arm(child, default=True))
            else:
                raise ParseError(
                    f"a {directive.keyword!r} block accepts only 'case' and 'else' children, "
                    f"got {child.keyword!r}",
                    child.line,
                    child.raw,
                )
        if not branch.arms:
            raise ParseError(
                f"{directive.keyword!r} block needs at least one 'case' child",
                directive.line,
                directive.raw,
            )
        return branch

    def _arm(self, directive: _Directive, *, default: bool) -> IRArm:
        """Build one decision arm.

        ``case Да: Выставить счёт`` is unambiguous - the argument is the label
        and the text is a one-line body.  Without an argument the text could be
        either, so the presence of nested lines decides: with children it names
        the arm, without them it *is* the arm.
        """
        argument = clean_label(directive.argument)
        text = directive.text.strip()
        if argument:
            label, inline = argument, text
        elif directive.children:
            label, inline = clean_label(text), ""
        else:
            label, inline = "", text

        arm = IRArm(
            label=capitalize_first(label),
            body=self._sequence(list(directive.children)),
            condition="" if default else directive.options.get("condition", ""),
            is_default=default,
        )
        if inline:
            arm.body.items.insert(
                0,
                IRActivity(
                    text=capitalize_first(clean_label(inline)),
                    actor=directive.actor,
                    activity_type=ActivityType.TASK,
                    line=directive.line,
                    source=directive.raw,
                ),
            )
        return arm

    def _parallel(self, directive: _Directive) -> IRParallel:
        parallel = IRParallel(
            text=clean_label(directive.text),
            actor=directive.actor,
            anchor=directive.anchor,
            line=directive.line,
            source=directive.raw,
        )
        for child in directive.children:
            if child.keyword not in _BRANCH_KEYWORDS:
                raise ParseError(
                    f"a parallel block accepts only 'branch' children, got {child.keyword!r}",
                    child.line,
                    child.raw,
                )
            parallel.branches.append(self._sequence(child.children))
        if len(parallel.branches) < 2:
            raise ParseError(
                "a parallel block needs at least two 'branch' children",
                directive.line,
                directive.raw,
            )
        return parallel


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_KNOWN_KEYWORDS = (
    set(_ACTIVITY_KEYWORDS)
    | set(_EVENT_KEYWORDS)
    | set(_GATEWAY_KEYWORDS)
    | _PARALLEL_KEYWORDS
    | _BRANCH_KEYWORDS
    | _CASE_KEYWORDS
    | _ELSE_KEYWORDS
    | _GOTO_KEYWORDS
    | _HEADER_KEYWORDS
)

def _parse_options(raw: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        key, separator, value = item.partition("=")
        options[key.strip().casefold()] = value.strip() if separator else "true"
    return options


def _nest(directives: list[_Directive]) -> list[_Directive]:
    """Turn a flat, indented directive list into a tree."""
    root: list[_Directive] = []
    stack: list[_Directive] = []
    for directive in directives:
        while stack and directive.indent <= stack[-1].indent:
            stack.pop()
        if stack:
            stack[-1].children.append(directive)
        else:
            root.append(directive)
        stack.append(directive)
    return root


def _collect_actors(sequence: IRSequence) -> list[str]:
    from bpmn_architect.domain.ir import walk

    seen: list[str] = []
    for element in walk(sequence):
        if element.actor and element.actor not in seen:
            seen.append(element.actor)
    return seen


def parse_dsl(raw_text: str) -> IRProcess:
    """Convenience wrapper around :class:`DslParser`."""
    return DslParser().parse(raw_text)
