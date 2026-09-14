"""Bilingual (RU/EN) cue lexicon for the natural-language parser.

Everything language-specific lives here, on purpose.  The parser in
:mod:`bpmn_architect.parsing.nlp` only asks questions like "does this sentence
open a decision?" and never contains a Russian or English word itself.  Adding
a third language therefore means extending this module, not rewriting the
parser.

Patterns are intentionally written against *surface forms* with permissive
stems (``\\w*`` tails) rather than against lemmas: process descriptions are
written in a narrow, formulaic register where this is both sufficient and far
more predictable than statistical tagging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bpmn_architect.domain.ir import ActivityType, EventTrigger

__all__ = [
    "Cue",
    "detect_language",
    "match_start",
    "match_end",
    "match_condition",
    "match_else",
    "match_parallel",
    "match_merge",
    "match_goto",
    "match_wait",
    "match_timer_prefix",
    "match_case_label",
    "classify_activity",
    "classify_event_trigger",
    "is_role_word",
    "strip_leading_connective",
    "arm_polarity",
    "QUESTION_MARK_RE",
    "LIST_SPLIT_RE",
]

_I = re.IGNORECASE | re.UNICODE


@dataclass(frozen=True, slots=True)
class Cue:
    """A cue match: the regexp hit plus the payload text that follows it."""

    keyword: str
    payload: str
    span: tuple[int, int]


def _cue(match: re.Match[str] | None, group: int = 0) -> Cue | None:
    if match is None:
        return None
    payload = ""
    if match.re.groups >= group and group > 0:
        payload = match.group(group) or ""
    elif match.re.groupindex.get("payload"):
        payload = match.group("payload") or ""
    return Cue(keyword=match.group(0).strip(), payload=payload.strip(), span=match.span())


# --------------------------------------------------------------------------- #
# Language detection
# --------------------------------------------------------------------------- #

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    """Return ``"ru"`` or ``"en"`` based on which alphabet dominates."""
    cyrillic = len(_CYRILLIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    return "ru" if cyrillic >= latin else "en"


# --------------------------------------------------------------------------- #
# Structural cues
# --------------------------------------------------------------------------- #

START_RE = re.compile(
    r"""(?:
        (?:процесс|процедура|сценарий)\s+(?:начинается|стартует|запускается|инициируется)
        (?:\s+(?:с|со|когда|после|при)\b)?
      | (?:начало|старт|запуск|инициация)\s+процесса
      | (?:процесс\s+)?(?:триггер|точка\s+входа)
      | начинается\s+(?:с|со|когда|после)\b
      | (?:the\s+)?process\s+(?:starts|begins|is\s+started|is\s+triggered|is\s+initiated)
        (?:\s+(?:with|when|by|after|upon))?
      | start\s+of\s+the\s+process
      | (?:is\s+)?triggered\s+by
      | begins\s+(?:with|when)
    )\s*[:,\-—–]?\s*(?P<payload>.*)$""",
    _I | re.VERBOSE,
)

END_RE = re.compile(
    r"""(?:
        (?:процесс|процедура|сценарий)\s+(?:завершается|заканчивается|окончен|завершен|завершён|закрывается|прерывается)
      | (?:конец|завершение|окончание)\s+процесса
      | на\s+этом\s+процесс\w*\s*\w*
      | (?:the\s+)?process\s+(?:ends|is\s+complete|is\s+completed|completes|finishes|terminates)
      | end\s+of\s+the\s+process
    )\s*[:,\-—–]?\s*(?P<payload>.*)$""",
    _I | re.VERBOSE,
)

CONDITION_RE = re.compile(
    r"""^\s*(?:
        если\s+(?!нет\b)
      | в\s+случае(?:,)?\s+(?:если|когда)\s+
      | в\s+случае\s+
      | при\s+условии(?:,)?\s+что\s+
      | когда\s+
      | в\s+зависимости\s+от\s+(?:того,?\s+)?
      | if\s+(?!not\b)
      | in\s+case\s+(?:of\s+)?
      | when\s+
      | depending\s+on\s+(?:whether\s+)?
      | should\s+
    )(?P<payload>.+)$""",
    _I | re.VERBOSE,
)

#: "то" / "then" separating the condition from its consequence.
THEN_RE = re.compile(r"(?:,\s*(?:то|тогда)\s+|\s+then\s+|\s+—\s+|\s+-\s+|\s*→\s*)", _I)

ELSE_RE = re.compile(
    r"""^\s*(?:
        иначе
      | в\s+противном\s+случае
      | если\s+нет
      | если\s+же\s+нет
      | в\s+остальных\s+случаях
      | во\s+всех\s+остальных\s+случаях
      | otherwise
      | else
      | if\s+not
      | in\s+all\s+other\s+cases
    )\b\s*[:,\-—–]?\s*(?P<payload>.*)$""",
    _I | re.VERBOSE,
)

PARALLEL_RE = re.compile(
    r"""(?:
        параллельно(?:\s+(?:выполняются|запускаются|идут|происходят))?
      | одновременно(?:\s+(?:выполняются|запускаются))?
      | в\s+то\s+же\s+время
      | синхронно
      | in\s+parallel
      | simultaneously
      | concurrently
      | at\s+the\s+same\s+time
    )\s*[:,\-—–]?\s*(?P<payload>.*)$""",
    _I | re.VERBOSE,
)

MERGE_RE = re.compile(
    r"""^\s*(?:
        после\s+(?:этого|чего|завершения\s+(?:обеих|всех|обоих)\w*(?:\s+\w+)?)
      | по\s+завершени[ию]\s+(?:обеих|всех|обоих)\w*(?:\s+\w+)?
      | (?:оба\s+|все\s+)?потоки?\s+объединяются
      | ветви\s+объединяются
      | в\s+любом\s+случае
      | в\s+обоих\s+случаях
      | независимо\s+от\s+(?:результата|исхода|выбора)
      | далее\s+в\s+любом\s+случае
      | after\s+(?:that|both|all)(?:\s+\w+)?
      | once\s+(?:both|all)(?:\s+\w+)?\s+(?:are\s+)?(?:complete|completed|done|finish|finished)
      | (?:the\s+)?(?:branches|flows)\s+(?:are\s+)?(?:merged|join|joined)
      | in\s+(?:both|all)\s+cases
      | regardless\s+of\s+(?:the\s+)?(?:result|outcome|choice)
    )\b\s*[:,\-—–]?\s*(?P<payload>.*)$""",
    _I | re.VERBOSE,
)

GOTO_RE = re.compile(
    r"""(?:
        (?:возвраща\w+|возврат|вернуть\w*|верн[уё]тся|направляется\s+обратно)\s+(?:к|на|в)\s+
      | повтор\w*\s+(?:шаг|этап|проверк\w+|процедур\w+)?\s*
      | (?:go\s+back|return|loop\s+back)\s+to\s+
      | repeat\s+
    )(?P<payload>.+)$""",
    _I | re.VERBOSE,
)

WAIT_RE = re.compile(
    r"""^\s*(?:\w+\s+){0,2}?(?:
        ожида\w+ | жд[её]т | жд[уа]т | в\s+ожидании
      | waits? | awaits? | is\s+waiting | pending
    )(?:\s+for)?\s*[:,\-—–]?\s*(?P<payload>.*)$""",
    _I | re.VERBOSE,
)

#: Explicit decision arm: "Да — ...", "Нет: ...", "Yes -> ...".
CASE_LABEL_RE = re.compile(
    r"^\s*(?P<label>[^:—–\-]{1,60}?)\s*(?::|—|–|->|→|\s-\s)\s*(?P<payload>.+)$",
    _I,
)

QUESTION_MARK_RE = re.compile(r"\?\s*$")

#: Splits enumerations inside one sentence: "A, B и C" / "A, B and C".
LIST_SPLIT_RE = re.compile(r"\s*(?:;|,\s*(?:а\s+также|и|and)\s+|\s+и\s+|\s+and\s+|,)\s*", _I)

LEADING_CONNECTIVE_RE = re.compile(
    r"""^\s*(?:
        затем | далее | потом | после\s+этого | после\s+чего | вслед\s+за\s+этим
      | сначала | сперва | в\s+первую\s+очередь | наконец | в\s+итоге | в\s+результате
      | then | next | afterwards | after\s+that | first(?:ly)? | finally | subsequently
    )\b\s*[,:\-—–]?\s*""",
    _I | re.VERBOSE,
)


def strip_leading_connective(text: str) -> str:
    """Drop discourse connectives ("затем", "next") that carry no BPMN meaning."""
    return LEADING_CONNECTIVE_RE.sub("", text, count=1).strip()


def match_start(text: str) -> Cue | None:
    return _cue(START_RE.search(text))


def match_end(text: str) -> Cue | None:
    return _cue(END_RE.search(text))


def match_condition(text: str) -> Cue | None:
    return _cue(CONDITION_RE.match(text))


def match_else(text: str) -> Cue | None:
    return _cue(ELSE_RE.match(text))


def match_parallel(text: str) -> Cue | None:
    return _cue(PARALLEL_RE.search(text))


def match_merge(text: str) -> Cue | None:
    return _cue(MERGE_RE.match(text))


def match_goto(text: str) -> Cue | None:
    return _cue(GOTO_RE.search(text))


def match_wait(text: str) -> Cue | None:
    return _cue(WAIT_RE.match(text))


def match_case_label(text: str) -> Cue | None:
    return _cue(CASE_LABEL_RE.match(text))


def match_timer_prefix(text: str) -> Cue | None:
    """Recognise a sentence that *opens* with a delay ("Через 3 дня ...").

    A leading delay describes waiting before the step, which is an intermediate
    timer event followed by the activity - not an activity whose name happens to
    mention a duration.  A delay anywhere else in the sentence is just wording.
    """
    match = TIMER_RE.match(text.strip())
    if match is None:
        return None
    remainder = text.strip()[match.end() :].lstrip(" ,:;-\u2014\u2013")
    return Cue(keyword=match.group(0).strip(), payload=remainder, span=match.span())


# --------------------------------------------------------------------------- #
# Decision arm polarity
# --------------------------------------------------------------------------- #

_POSITIVE_RE = re.compile(
    r"^(?:да|yes|true|успешно|успешн\w+|корректн\w+|положительн\w+|одобрен\w+|"
    r"подтвержден\w+|подтверждён\w+|достаточно|есть|ok|approved|valid|success\w*)\b",
    _I,
)
_NEGATIVE_RE = re.compile(
    r"^(?:нет|no|false|неуспешно|неуспешн\w+|некорректн\w+|отрицательн\w+|отклонен\w+|"
    r"отказ\w*|не\s+\w+|недостаточно|ошибк\w+|rejected|invalid|fail\w*|not\s+\w+)\b",
    _I,
)


def arm_polarity(label: str) -> bool | None:
    """``True`` for affirmative arms, ``False`` for negative ones, ``None`` if unclear."""
    stripped = label.strip()
    if _POSITIVE_RE.match(stripped):
        return True
    if _NEGATIVE_RE.match(stripped):
        return False
    return None


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #

ROLE_STEMS: tuple[str, ...] = (
    "менеджер", "бухгалтер", "бухгалтери", "юрист", "сотрудник", "специалист",
    "руководител", "директор", "начальник", "оператор", "администратор", "админ",
    "клиент", "заказчик", "покупател", "поставщик", "подрядчик", "партнер", "партнёр",
    "кладовщик", "курьер", "логист", "аналитик", "разработчик", "тестировщик",
    "инженер", "отдел", "департамент", "служба", "система", "сервис", "банк",
    "рекрутер", "кандидат", "склад", "кассир", "продавец", "консультант",
    "секретар", "ассистент", "владелец", "координатор", "диспетчер", "контролер",
    "контролёр", "аудитор", "приемщик", "приёмщик", "модератор", "редактор",
    "маркетолог", "закупщик", "снабжен", "казначей", "финансист", "экономист",
    "hr", "it", "crm", "erp", "ops",
    "manager", "accountant", "lawyer", "employee", "specialist", "supervisor",
    "director", "operator", "administrator", "customer", "client", "supplier",
    "contractor", "courier", "analyst", "developer", "tester", "engineer",
    "department", "team", "service", "system", "bank", "recruiter", "candidate",
    "warehouse", "cashier", "salesperson", "consultant", "secretary", "assistant",
    "owner", "coordinator", "dispatcher", "controller", "auditor", "reviewer",
    "approver", "applicant", "requester",
)

_ROLE_STEM_SET = frozenset(ROLE_STEMS)


def is_role_word(word: str) -> bool:
    """True when ``word`` names a participant (and therefore deserves a lane)."""
    lowered = word.casefold().strip(" .,:;«»\"'()")
    if not lowered:
        return False
    if lowered in _ROLE_STEM_SET:
        return True
    return any(lowered.startswith(stem) and len(lowered) - len(stem) <= 4 for stem in ROLE_STEMS)


_AUTOMATED_ACTOR_RE = re.compile(
    r"^(?:систем\w*|сервис\w*|робот\w*|бот|скрипт\w*|интеграц\w*|crm|erp|api|"
    r"system|service|robot|bot|script|integration|platform)\b",
    _I,
)


def is_automated_actor(actor: str | None) -> bool:
    return bool(actor) and bool(_AUTOMATED_ACTOR_RE.match(actor or ""))


# --------------------------------------------------------------------------- #
# Activity typing
# --------------------------------------------------------------------------- #

_ACTIVITY_PATTERNS: tuple[tuple[re.Pattern[str], ActivityType], ...] = (
    (re.compile(r"\b(?:подпроцесс|субпроцесс|sub-?process)\b", _I), ActivityType.SUB_PROCESS),
    (
        re.compile(r"\b(?:вызыва\w+\s+процесс|call\s+activity|вызов\s+процесса)\b", _I),
        ActivityType.CALL,
    ),
    (
        re.compile(
            r"\b(?:отправля\w+|направля\w+|высыла\w+|посыла\w+|уведомля\w+|"
            r"sends?|notifies|forwards?|dispatch\w*)\b",
            _I,
        ),
        ActivityType.SEND,
    ),
    (
        re.compile(r"\b(?:получа\w+|принима\w+|receives?|accepts?)\b", _I),
        ActivityType.RECEIVE,
    ),
    (
        re.compile(
            r"\b(?:по\s+правилам|бизнес-правил\w*|скоринг\w*|регламент\w*|"
            r"таблиц\w+\s+решений|business\s+rules?|decision\s+table|scoring)\b",
            _I,
        ),
        ActivityType.BUSINESS_RULE,
    ),
    (re.compile(r"\b(?:скрипт\w*|script)\b", _I), ActivityType.SCRIPT),
    (re.compile(r"\b(?:вручную|manually|by\s+hand)\b", _I), ActivityType.MANUAL),
    (
        re.compile(
            r"\b(?:автоматическ\w+|систем\w+|сервис\w*|интеграц\w+|api|робот\w*|"
            r"automatically|automated|the\s+system|integration)\b",
            _I,
        ),
        ActivityType.SERVICE,
    ),
)


def classify_activity(text: str, actor: str | None = None) -> ActivityType:
    """Infer the BPMN task type from the wording and the acting role."""
    for pattern, activity_type in _ACTIVITY_PATTERNS:
        if pattern.search(text):
            if activity_type is ActivityType.SERVICE and not is_automated_actor(actor) and actor:
                continue
            return activity_type
    if is_automated_actor(actor):
        return ActivityType.SERVICE
    if actor:
        return ActivityType.USER
    return ActivityType.TASK


# --------------------------------------------------------------------------- #
# Event triggers
# --------------------------------------------------------------------------- #

TIMER_RE = re.compile(
    r"(?:(?:через|спустя|в\s+течение|по\s+истечении|не\s+позднее\s+чем\s+через)\s+"
    r"(?P<ru_amount>\d+)\s*(?P<ru_unit>минут\w*|час\w*|дн\w*|дней|сут\w*|недел\w*|месяц\w*|лет|год\w*)"
    r"|(?:after|within|in)\s+(?P<en_amount>\d+)\s*(?P<en_unit>minutes?|hours?|days?|weeks?|months?|years?)"
    r"|(?P<recurring>ежедневно|еженедельно|ежемесячно|ежегодно|каждый\s+\w+|каждую\s+\w+|"
    r"daily|weekly|monthly|yearly|every\s+\w+))",
    _I,
)

_MESSAGE_RE = re.compile(
    r"\b(?:уведомлен\w+|сообщен\w+|письм\w+|email|e-mail|запрос\w*|обращени\w+|"
    r"заявк\w+|ответ\w*|message|notification|mail|request|reply|response)\b",
    _I,
)
_ERROR_RE = re.compile(r"\b(?:ошибк\w+|сбо[йя]\w*|исключени\w+|error|failure|exception)\b", _I)
_SIGNAL_RE = re.compile(r"\b(?:сигнал\w*|оповещени\w+|signal|broadcast)\b", _I)
_ESCALATION_RE = re.compile(r"\b(?:эскалац\w+|эскалир\w+|escalat\w+)\b", _I)
_TERMINATE_RE = re.compile(
    r"\b(?:аварийн\w+\s+заверш\w+|процесс\s+прерывается|немедленно\s+прекращается|"
    r"terminate[sd]?|aborted?)\b",
    _I,
)
_CONDITIONAL_RE = re.compile(
    r"\b(?:при\s+наступлении\s+услови\w+|условн\w+\s+событи\w+|conditional\s+event)\b", _I
)

_TIMER_UNITS = {
    "минут": "M", "час": "H", "дн": "D", "дней": "D", "сут": "D", "недел": "W",
    "месяц": "M", "год": "Y", "лет": "Y",
    "minute": "M", "hour": "H", "day": "D", "week": "W", "month": "M", "year": "Y",
}


def _iso_duration(amount: str, unit: str) -> str:
    """Best-effort ISO-8601 duration for a timer definition."""
    lowered = unit.casefold()
    code = next((c for stem, c in _TIMER_UNITS.items() if lowered.startswith(stem)), "D")
    if code in {"M", "H"} and lowered.startswith(("минут", "minute", "час", "hour")):
        return f"PT{amount}{'M' if lowered.startswith(('минут', 'minute')) else 'H'}"
    if code == "W":
        return f"P{amount}W"
    if code == "M":
        return f"P{amount}M"
    if code == "Y":
        return f"P{amount}Y"
    return f"P{amount}D"


def classify_event_trigger(text: str) -> tuple[EventTrigger, str]:
    """Return the event trigger implied by ``text`` and its timer expression."""
    timer = TIMER_RE.search(text)
    if timer:
        if timer.group("recurring"):
            return EventTrigger.TIMER, timer.group("recurring")
        amount = timer.group("ru_amount") or timer.group("en_amount") or ""
        unit = timer.group("ru_unit") or timer.group("en_unit") or ""
        return EventTrigger.TIMER, _iso_duration(amount, unit) if amount else timer.group(0)
    if _TERMINATE_RE.search(text):
        return EventTrigger.TERMINATE, ""
    if _ESCALATION_RE.search(text):
        return EventTrigger.ESCALATION, ""
    if _ERROR_RE.search(text):
        return EventTrigger.ERROR, ""
    if _SIGNAL_RE.search(text):
        return EventTrigger.SIGNAL, ""
    if _CONDITIONAL_RE.search(text):
        return EventTrigger.CONDITIONAL, ""
    if _MESSAGE_RE.search(text):
        return EventTrigger.MESSAGE, ""
    return EventTrigger.NONE, ""
