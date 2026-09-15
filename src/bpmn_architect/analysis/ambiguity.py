"""Detecting what the description did not say, and asking about it.

A text-to-model tool has two ways to handle an under-specified sentence: guess
quietly, or ask.  Guessing produces a diagram that looks authoritative and is
wrong in a way nobody notices until the process is reviewed — the worst
possible failure mode for a modelling tool.

So the analyser reports gaps as **questions with concrete options**, drawn from
what the rest of the description already established: if three lanes exist, the
"who performs this?" question offers those three first.  Answers are applied to
the model, not to the text, which keeps the original description intact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bpmn_architect.domain.model import GatewayDirection, Node, NodeKind, ProcessModel
from bpmn_architect.ids import IdFactory
from bpmn_architect.sourcemap import SourceMap
from bpmn_architect.validation.diagnostics import Diagnostics

__all__ = [
    "ClarificationOption",
    "Clarification",
    "analyse_ambiguity",
    "apply_clarifications",
]

#: Stems of words that name an action without saying what it is.  Stems rather
#: than full forms, so "обработка", "обработать" and "выполняется обработка"
#: are all recognised without enumerating every inflection.
_VAGUE_RU = (
    "обработ", "выполн", "действи", "работ", "процедур", "операци", "шаг", "этап",
    "проверк", "рассмотр", "оформлен", "согласован", "подготовк", "анализ", "решени",
    "производ", "осуществл", "происход",
)
_VAGUE_EN = (
    "process", "handl", "action", "work", "step", "stage", "operation", "procedure",
    "review", "check", "analys", "analyz", "decision", "perform", "execut",
)

_AUTOMATION_LABEL = {"ru": "Система", "en": "System"}
_OTHER_LABEL = {"ru": "Другое", "en": "Other"}

_QUESTIONS: dict[str, dict[str, str]] = {
    "actor": {
        "ru": "Кто выполняет действие «{name}»?",
        "en": "Who performs “{name}”?",
    },
    "naming": {
        "ru": "Что именно происходит на шаге «{name}»? Уточните формулировку.",
        "en": "What exactly happens in “{name}”? Please be more specific.",
    },
    "condition": {
        "ru": "По какому условию расходятся ветки этого шлюза?",
        "en": "Which condition does this gateway branch on?",
    },
    "branch_label": {
        "ru": "Как назвать ветку №{index}, выходящую из «{name}»?",
        "en": "How should branch #{index} leaving “{name}” be labelled?",
    },
    "branch_label_unnamed": {
        "ru": "Как назвать ветку №{index} этого шлюза?",
        "en": "How should branch #{index} of this gateway be labelled?",
    },
}


@dataclass(frozen=True, slots=True)
class ClarificationOption:
    value: str
    label: str
    #: True for the free-text option, which the UI turns into an input field.
    free_text: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "label": self.label, "freeText": self.free_text}


@dataclass(slots=True)
class Clarification:
    """One open question about the model, addressed at a specific element."""

    id: str
    kind: str
    question: str
    element_id: str | None = None
    flow_id: str | None = None
    options: list[ClarificationOption] = field(default_factory=list)
    #: The sentence that produced the element, for context in the UI.
    sentence: str = ""
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "question": self.question,
            "elementId": self.element_id,
            "flowId": self.flow_id,
            "options": [option.to_dict() for option in self.options],
            "sentence": self.sentence,
            "line": self.line,
        }


def analyse_ambiguity(
    model: ProcessModel,
    *,
    language: str = "ru",
    source_map: SourceMap | None = None,
) -> list[Clarification]:
    """Collect everything the description left open, as answerable questions."""
    language = language if language in {"ru", "en"} else "en"
    clarifications: list[Clarification] = []
    counter = 0

    def next_id(kind: str) -> str:
        nonlocal counter
        counter += 1
        return f"ask_{counter}_{kind}"

    lane_options = [
        ClarificationOption(value=lane.name, label=lane.name) for lane in model.lanes
    ]
    automation = _AUTOMATION_LABEL[language]
    if all(option.value.casefold() != automation.casefold() for option in lane_options):
        lane_options.append(ClarificationOption(value=automation, label=automation))
    lane_options.append(
        ClarificationOption(value="", label=_OTHER_LABEL[language], free_text=True)
    )

    for node in model.nodes:
        span = source_map.for_element(node.id) if source_map else None
        sentence = span.sentence if span else ""
        line = span.line if span else 0

        if node.kind.is_activity and node.lane_id is None and model.has_lanes:
            clarifications.append(
                Clarification(
                    id=next_id("actor"),
                    kind="actor",
                    question=_QUESTIONS["actor"][language].format(name=node.label),
                    element_id=node.id,
                    options=list(lane_options),
                    sentence=sentence,
                    line=line,
                )
            )

        if node.kind.is_activity and _is_vague(node.name, language):
            clarifications.append(
                Clarification(
                    id=next_id("naming"),
                    kind="naming",
                    question=_QUESTIONS["naming"][language].format(name=node.label),
                    element_id=node.id,
                    options=[ClarificationOption(value="", label=node.name, free_text=True)],
                    sentence=sentence,
                    line=line,
                )
            )

        if (
            node.kind.is_gateway
            and node.kind is not NodeKind.PARALLEL_GATEWAY
            and not node.name
            and model.gateway_direction(node.id) is GatewayDirection.DIVERGING
        ):
            clarifications.append(
                Clarification(
                    id=next_id("condition"),
                    kind="condition",
                    question=_QUESTIONS["condition"][language],
                    element_id=node.id,
                    options=[ClarificationOption(value="", label="", free_text=True)],
                    sentence=sentence,
                    line=line,
                )
            )

        # Only a *diverging* gateway has branches to name; the single outgoing
        # flow of a join needs no label.
        if (
            node.kind.is_gateway
            and node.kind is not NodeKind.PARALLEL_GATEWAY
            and model.gateway_direction(node.id) is GatewayDirection.DIVERGING
        ):
            for index, flow in enumerate(model.outgoing(node.id), start=1):
                if flow.name or flow.condition or flow.is_default:
                    continue
                template = "branch_label" if node.name else "branch_label_unnamed"
                clarifications.append(
                    Clarification(
                        id=next_id("branch"),
                        kind="branch_label",
                        question=_QUESTIONS[template][language].format(
                            name=node.name, index=index
                        ),
                        element_id=node.id,
                        flow_id=flow.id,
                        options=[ClarificationOption(value="", label="", free_text=True)],
                        sentence=sentence,
                        line=line,
                    )
                )
    return clarifications


def apply_clarifications(
    model: ProcessModel,
    clarifications: list[Clarification],
    answers: dict[str, str],
) -> Diagnostics:
    """Write the user's answers into the model.

    Answers change the model rather than the text: the description stays the
    authored record, while the diagram carries the corrections.
    """
    diagnostics = Diagnostics()
    by_id = {clarification.id: clarification for clarification in clarifications}
    ids = IdFactory()
    for lane in model.lanes:
        ids.reserve(lane.id)

    for answer_id, raw_value in answers.items():
        clarification = by_id.get(answer_id)
        value = raw_value.strip()
        if clarification is None:
            diagnostics.warning("A401", f"answer {answer_id!r} does not match any question")
            continue
        if not value:
            continue

        if clarification.kind == "actor" and clarification.element_id:
            _assign_lane(model, clarification.element_id, value, ids, diagnostics)
        elif clarification.kind in {"naming", "condition"} and clarification.element_id:
            model.node(clarification.element_id).name = value
        elif clarification.kind == "branch_label" and clarification.flow_id:
            model.flow(clarification.flow_id).name = value
        else:
            diagnostics.warning(
                "A402", f"question {answer_id!r} of kind {clarification.kind!r} was not applied"
            )
    return diagnostics


def _assign_lane(
    model: ProcessModel,
    element_id: str,
    lane_name: str,
    ids: IdFactory,
    diagnostics: Diagnostics,
) -> None:
    existing = next(
        (lane for lane in model.lanes if lane.name.casefold() == lane_name.casefold()), None
    )
    if existing is None:
        from bpmn_architect.domain.model import Lane

        existing = model.add_lane(
            Lane(id=ids.next("Lane"), name=lane_name, order=len(model.lanes))
        )
        diagnostics.info("A403", f"lane {lane_name!r} was created", existing.id)
    model.node(element_id).lane_id = existing.id


def _is_vague(name: str, language: str) -> bool:
    """True when a name states that something happens but not what."""
    words = [word.strip(".,:;!?«»\"'()").casefold() for word in name.split()]
    words = [word for word in words if word]
    if not words:
        return True
    stems = _VAGUE_RU if language == "ru" else _VAGUE_EN
    generic = [word.startswith(stems) for word in words]
    if len(words) == 1:
        return generic[0]
    # "Выполняется обработка" - a generic verb with a generic object says
    # nothing; "Проверить заявку" names a real object and is fine.
    return len(words) == 2 and all(generic)


def _node_label(node: Node) -> str:  # pragma: no cover - convenience for callers
    return node.label
