"""Light-weight morphology used to produce BPMN-conformant element names.

Modelling guidelines (BPMN Method & Style, and every corporate modelling
convention that follows it) ask for activities named *verb + object* in the
infinitive — "Проверить заявку", "Check the request" — while people describe
processes in the third person — "Менеджер проверяет заявку".

Full morphological analysis would mean a heavyweight dependency, so this module
takes the pragmatic route used by production text-to-model tools:

1. a curated dictionary of the verbs that actually occur in process
   descriptions (they form a surprisingly small closed set);
2. a handful of suffix rules for everything else;
3. a **confidence gate** — if neither source applies, the original wording is
   kept verbatim rather than guessed at.

That last point is the important one: a wrong verb form in a diagram is worse
than an unconverted one, so the module never converts what it does not know.
"""

from __future__ import annotations

import re

__all__ = [
    "to_infinitive",
    "normalize_actor",
    "capitalize_first",
    "looks_like_verb",
    "looks_like_infinitive",
    "nominalize",
    "from_genitive",
    "to_nominative_object",
]

# --------------------------------------------------------------------------- #
# Russian
# --------------------------------------------------------------------------- #

#: Third person singular -> infinitive, for verbs common in business processes.
_RU_VERBS: dict[str, str] = {
    "проверяет": "проверить",
    "перепроверяет": "перепроверить",
    "согласовывает": "согласовать",
    "согласует": "согласовать",
    "утверждает": "утвердить",
    "отклоняет": "отклонить",
    "отказывает": "отказать",
    "оформляет": "оформить",
    "выставляет": "выставить",
    "направляет": "направить",
    "отправляет": "отправить",
    "высылает": "выслать",
    "получает": "получить",
    "принимает": "принять",
    "регистрирует": "зарегистрировать",
    "создает": "создать",
    "создаёт": "создать",
    "формирует": "сформировать",
    "готовит": "подготовить",
    "подготавливает": "подготовить",
    "рассматривает": "рассмотреть",
    "анализирует": "проанализировать",
    "вносит": "внести",
    "заполняет": "заполнить",
    "передает": "передать",
    "передаёт": "передать",
    "уведомляет": "уведомить",
    "информирует": "проинформировать",
    "подписывает": "подписать",
    "оплачивает": "оплатить",
    "закрывает": "закрыть",
    "открывает": "открыть",
    "назначает": "назначить",
    "выполняет": "выполнить",
    "проводит": "провести",
    "обрабатывает": "обработать",
    "загружает": "загрузить",
    "выгружает": "выгрузить",
    "сохраняет": "сохранить",
    "удаляет": "удалить",
    "публикует": "опубликовать",
    "запрашивает": "запросить",
    "уточняет": "уточнить",
    "корректирует": "скорректировать",
    "исправляет": "исправить",
    "дорабатывает": "доработать",
    "возвращает": "вернуть",
    "выдает": "выдать",
    "выдаёт": "выдать",
    "начисляет": "начислить",
    "списывает": "списать",
    "резервирует": "зарезервировать",
    "бронирует": "забронировать",
    "комплектует": "укомплектовать",
    "упаковывает": "упаковать",
    "доставляет": "доставить",
    "заказывает": "заказать",
    "покупает": "купить",
    "продает": "продать",
    "продаёт": "продать",
    "считает": "посчитать",
    "рассчитывает": "рассчитать",
    "определяет": "определить",
    "устанавливает": "установить",
    "настраивает": "настроить",
    "тестирует": "протестировать",
    "внедряет": "внедрить",
    "запускает": "запустить",
    "останавливает": "остановить",
    "контролирует": "проконтролировать",
    "фиксирует": "зафиксировать",
    "archives": "архивировать",
    "архивирует": "архивировать",
    "эскалирует": "эскалировать",
    "инициирует": "инициировать",
    "уточняется": "уточнить",
    "заводит": "завести",
    "ищет": "найти",
    "выбирает": "выбрать",
    "сравнивает": "сравнить",
    "оценивает": "оценить",
    "измеряет": "измерить",
    "планирует": "запланировать",
    "организует": "организовать",
    "собирает": "собрать",
    "составляет": "составить",
    "описывает": "описать",
    "вычисляет": "вычислить",
    "проверят": "проверить",
    "нанимает": "нанять",
    "увольняет": "уволить",
    "обучает": "обучить",
    "консультирует": "проконсультировать",
    "звонит": "позвонить",
    "связывается": "связаться",
    "договаривается": "договориться",
    "подтверждает": "подтвердить",
    "отменяет": "отменить",
    "переносит": "перенести",
    "копирует": "скопировать",
    "печатает": "напечатать",
    "сканирует": "отсканировать",
    "прикладывает": "приложить",
    "прикрепляет": "прикрепить",
    "маркирует": "промаркировать",
    "блокирует": "заблокировать",
    "разблокирует": "разблокировать",
    "активирует": "активировать",
    "деактивирует": "деактивировать",
    "синхронизирует": "синхронизировать",
    "интегрирует": "интегрировать",
    "импортирует": "импортировать",
    "экспортирует": "экспортировать",
    "конвертирует": "конвертировать",
    "валидирует": "валидировать",
    "верифицирует": "верифицировать",
    "решает": "решить",
    "отвечает": "ответить",
    "помогает": "помочь",
    "начинает": "начать",
    "заканчивает": "закончить",
    "продолжает": "продолжить",
    "обновляет": "обновить",
    "добавляет": "добавить",
    "изменяет": "изменить",
    "исполняет": "исполнить",
    "применяет": "применить",
    "объясняет": "объяснить",
    "представляет": "представить",
    "оставляет": "оставить",
    "предоставляет": "предоставить",
    "устраняет": "устранить",
    "уменьшает": "уменьшить",
    "увеличивает": "увеличить",
    "оповещает": "оповестить",
    "извещает": "известить",
    "приглашает": "пригласить",
    "оценивается": "оценить",
}

#: Plural third person -> singular third person, applied before the lookup above.
_RU_PLURAL_TO_SINGULAR = (
    ("ируют", "ирует"),
    ("уются", "уется"),
    ("ываются", "ывается"),
    ("яются", "яется"),
    ("аются", "ается"),
    ("ируются", "ируется"),
    ("ают", "ает"),
    ("яют", "яет"),
    ("уют", "ует"),
    ("ют", "ет"),
    ("ат", "ит"),
    ("ят", "ит"),
)

#: Suffix fallbacks, ordered from most to least specific.
_RU_SUFFIX_RULES = (
    ("ирует", "ировать"),
    ("зует", "зовать"),
    ("сует", "совать"),
    ("дует", "довать"),
    ("рует", "ровать"),
    ("ует", "овать"),
    ("яет", "ять"),
    ("ает", "ать"),
    ("ывает", "ывать"),
    ("ивает", "ивать"),
)

_RU_VERB_ENDINGS = (
    "ирует", "ует", "яет", "ает", "ивает", "ывает", "ит", "ет", "ёт",
    "ают", "яют", "уют", "ют", "ат", "ят", "ится", "ется", "ются", "ятся",
)

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")

#: Frequent business nouns whose ending coincides with a verb ending
#: ("счёт", "отчёт").  Without this list "бухгалтер выставляет счёт" would be
#: read as a two-word role followed by a verb.
_RU_NOUN_LOOKALIKES = frozenset(
    {
        "счет", "счёт", "отчет", "отчёт", "расчет", "расчёт", "зачет", "зачёт",
        "учет", "учёт", "переучет", "переучёт", "ответ", "совет", "билет",
        "пакет", "макет", "комплект", "предмет", "бюджет", "кабинет",
        "интернет", "момент", "клиент", "документ", "процент", "полет", "полёт",
    }
)


def _is_cyrillic(word: str) -> bool:
    return bool(_CYRILLIC.search(word))


_RU_INFINITIVE_RE = re.compile(r"^\w{4,}(?:ать|ять|ить|еть|уть|ыть|оть|чь|ти)$", re.IGNORECASE)
_RU_INFINITIVE_EXCEPTIONS = re.compile(r"(?:сть|знь|путь|суть)$", re.IGNORECASE)


def looks_like_infinitive(word: str) -> bool:
    """True for Russian infinitives ("проверить"), excluding noun look-alikes.

    Separate from :func:`looks_like_verb` on purpose: many common nouns end in
    "-сть" ("стоимость", "часть"), so this laxer test is only safe where a
    false positive costs nothing.
    """
    lowered = word.casefold()
    if not _is_cyrillic(lowered) or _RU_INFINITIVE_EXCEPTIONS.search(lowered):
        return False
    return bool(_RU_INFINITIVE_RE.match(lowered))


def looks_like_verb(word: str) -> bool:
    """Heuristically decide whether ``word`` is a third-person present verb."""
    lowered = word.casefold()
    if _is_cyrillic(lowered):
        if lowered in _RU_VERBS:
            return True
        if len(lowered) < 4 or lowered in _RU_NOUN_LOOKALIKES:
            return False
        return lowered.endswith(_RU_VERB_ENDINGS)
    return bool(_EN_VERB_3SG.match(lowered)) and lowered not in _EN_NON_VERBS


def _ru_to_infinitive(word: str) -> str | None:
    lowered = word.casefold().replace("ё", "ё")
    if lowered in _RU_VERBS:
        return _RU_VERBS[lowered]
    for plural, singular in _RU_PLURAL_TO_SINGULAR:
        if lowered.endswith(plural):
            candidate = lowered[: -len(plural)] + singular
            if candidate in _RU_VERBS:
                return _RU_VERBS[candidate]
            lowered = candidate
            break
    for suffix, replacement in _RU_SUFFIX_RULES:
        if lowered.endswith(suffix) and len(lowered) > len(suffix) + 1:
            return lowered[: -len(suffix)] + replacement
    # "-ит" is ambiguous ("готовит" -> "готовить", but "летит" -> "лететь"),
    # so it is only applied for words long enough to carry a prefix.
    if lowered.endswith("ит") and len(lowered) >= 6:
        return lowered[:-2] + "ить"
    return None


# --------------------------------------------------------------------------- #
# English
# --------------------------------------------------------------------------- #

_EN_VERB_3SG = re.compile(r"^[a-z][a-z\-]{2,}(s|es|ies)$")
_EN_NON_VERBS = frozenset(
    {
        "process", "business", "address", "status", "access", "analysis", "series",
        "success", "class", "less", "its", "his", "this", "thus", "yes", "gas",
        "news", "goods", "means", "sales", "details", "results", "documents",
        "is", "was", "has", "does", "always", "otherwise", "unless",
    }
)
_EN_IRREGULAR = {
    "has": "have",
    "does": "do",
    "is": "be",
    "goes": "go",
    "sends": "send",
    "pays": "pay",
    "buys": "buy",
    "says": "say",
}


def _en_to_infinitive(word: str) -> str | None:
    lowered = word.casefold()
    if lowered in _EN_IRREGULAR:
        return _EN_IRREGULAR[lowered]
    if lowered in _EN_NON_VERBS or not _EN_VERB_3SG.match(lowered):
        return None
    if lowered.endswith("ies") and len(lowered) > 4:
        return lowered[:-3] + "y"
    if lowered.endswith(("sses", "shes", "ches", "xes", "zes", "oes")):
        return lowered[:-2]
    if lowered.endswith("s"):
        return lowered[:-1]
    return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def to_infinitive(phrase: str) -> str:
    """Rewrite a third-person phrase as an infinitive one.

    Only the leading verb is touched; the object keeps its original wording and
    case.  When the leading word is not recognised as a verb the phrase is
    returned unchanged, so this transformation is always safe to apply.

    >>> to_infinitive("проверяет заявку")
    'проверить заявку'
    >>> to_infinitive("checks the request")
    'check the request'
    >>> to_infinitive("заявка получена")
    'заявка получена'
    """
    stripped = phrase.strip()
    if not stripped:
        return stripped
    head, _, tail = stripped.partition(" ")
    infinitive = _ru_to_infinitive(head) if _is_cyrillic(head) else _en_to_infinitive(head)
    if infinitive is None:
        return stripped
    if head.isupper():
        infinitive = infinitive.upper()
    return f"{infinitive} {tail}".strip()


_ARTICLES = frozenset({"the", "a", "an"})


def normalize_actor(actor: str) -> str:
    """Normalise a role mention into a readable lane name.

    Articles are dropped so that "the recruiter" and "Recruiter" share a single
    lane instead of producing two.
    """
    cleaned = " ".join(actor.split()).strip(" .,:;-\u2014")
    if not cleaned:
        return ""
    words = cleaned.split()
    if len(words) > 1 and words[0].casefold() in _ARTICLES:
        words = words[1:]
    if len(words) > 4:  # a sentence fragment, not a role
        words = words[:4]
    return capitalize_first(" ".join(words))


_GENITIVE_GERUND_RE = re.compile(r"^\w{5,}(?:ния|тия|сия)$", re.IGNORECASE)
_PREPOSITIONAL_GERUND_RE = re.compile(r"^\w{5,}(?:нии|тии|сии)$", re.IGNORECASE)


#: Genitive singular -> nominative, for feminine nouns whose ending is
#: unambiguous *in a genitive position* ("начинается с заявки" -> "заявка").
#: Outside that position "-и"/"-ы" would be a nominative plural, which is why
#: this is a separate function rather than part of :func:`nominalize`.
_GENITIVE_NOUN_RULES = (
    ("ии", "ия"),
    ("жи", "жа"),
    ("чи", "ча"),
    ("ши", "ша"),
    ("щи", "ща"),
    ("ки", "ка"),
    ("ги", "га"),
    ("хи", "ха"),
    ("ты", "та"),
    ("ды", "да"),
    ("ны", "на"),
    ("сы", "са"),
    ("лы", "ла"),
    ("мы", "ма"),
    ("ры", "ра"),
    ("вы", "ва"),
    ("зы", "за"),
    ("бы", "ба"),
    ("пы", "па"),
)


def from_genitive(phrase: str) -> str:
    """Rewrite a phrase that stands in the genitive as a nominative subject.

    Only safe where the grammar already forces the genitive - after "с", "от",
    "из" - which is the one place it is called from.

    >>> from_genitive("заявки от клиента")
    'заявка от клиента'
    """
    stripped = phrase.strip()
    if not stripped:
        return stripped
    nominalized = nominalize(stripped)
    if nominalized != stripped:
        return nominalized  # a gerund: "получения" -> "получение"
    head, _, tail = stripped.partition(" ")
    lowered = head.casefold()
    for ending, replacement in _GENITIVE_NOUN_RULES:
        if lowered.endswith(ending) and len(lowered) > len(ending) + 2:
            head = head[: -len(ending)] + replacement
            break
    return f"{head} {tail}".strip()


def nominalize(phrase: str) -> str:
    """Turn "получения заявки" into "получение заявки".

    Descriptions phrase triggers in the genitive ("начинается с получения
    заявки"); event labels read better in the nominative.
    """
    stripped = phrase.strip()
    if not stripped:
        return stripped
    head, _, tail = stripped.partition(" ")
    if _GENITIVE_GERUND_RE.match(head):
        head = head[:-1] + "е"          # "получения"   -> "получение"
    elif _PREPOSITIONAL_GERUND_RE.match(head):
        head = head[:-1] + "е"          # "поступлении" -> "поступление"
    return f"{head} {tail}".strip()


_ACCUSATIVE_ENDINGS = (("ию", "ия"), ("ью", "ь"), ("у", "а"), ("ю", "я"))


def to_nominative_object(phrase: str) -> str:
    """Rewrite an accusative object as a nominative subject.

    Used for gateway labels: "определяет категорию обращения" yields the
    question "Категория обращения?".  Only the head noun is touched, and only
    for the endings that are unambiguous in this position.
    """
    stripped = phrase.strip()
    if not stripped:
        return stripped
    head, _, tail = stripped.partition(" ")
    lowered = head.casefold()
    for ending, replacement in _ACCUSATIVE_ENDINGS:
        if lowered.endswith(ending) and len(lowered) > len(ending) + 2:
            head = head[: -len(ending)] + replacement
            break
    return f"{head} {tail}".strip()


def capitalize_first(text: str) -> str:
    """Upper-case the first character, leaving the rest of the string intact.

    ``str.capitalize`` would lower-case acronyms ("CRM" -> "Crm"), which is not
    acceptable for element labels.
    """
    stripped = text.strip()
    if not stripped:
        return stripped
    return stripped[0].upper() + stripped[1:]
