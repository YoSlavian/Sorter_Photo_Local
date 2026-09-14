"""Intermediate representation of a parsed process description.

Parsers (natural language or DSL) never build a BPMN graph directly.  They
produce this *block tree* instead, and a single builder turns the tree into a
graph.  The indirection buys three things:

* **Structural correctness by construction.**  Branches are nested blocks, so
  every split gateway gets its matching join gateway automatically; a parser
  cannot emit an unbalanced diagram.
* **One place to test parsing.**  Parser tests assert on the tree, which is
  far more readable than assertions over XML.
* **Multiple front ends, one back end.**  Adding a new input syntax means
  adding a parser that emits :class:`IRProcess`; nothing downstream changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "ActivityType",
    "EventTrigger",
    "EventPosition",
    "BranchType",
    "IRElement",
    "IRActivity",
    "IREvent",
    "IRArm",
    "IRBranch",
    "IRParallel",
    "IRGoto",
    "IRSequence",
    "IRLane",
    "IRProcess",
    "walk",
]


class ActivityType(Enum):
    """Kind of work performed by an activity block."""

    TASK = "task"
    USER = "user"
    SERVICE = "service"
    MANUAL = "manual"
    SCRIPT = "script"
    SEND = "send"
    RECEIVE = "receive"
    BUSINESS_RULE = "rule"
    SUB_PROCESS = "subprocess"
    CALL = "call"


class EventTrigger(Enum):
    NONE = "none"
    MESSAGE = "message"
    TIMER = "timer"
    SIGNAL = "signal"
    ERROR = "error"
    ESCALATION = "escalation"
    CONDITIONAL = "conditional"
    TERMINATE = "terminate"


class EventPosition(Enum):
    START = "start"
    INTERMEDIATE_CATCH = "catch"
    INTERMEDIATE_THROW = "throw"
    END = "end"


class BranchType(Enum):
    """Semantics of a decision block."""

    EXCLUSIVE = "xor"
    INCLUSIVE = "or"
    EVENT_BASED = "event"


@dataclass(slots=True)
class IRElement:
    """Base class for every block.

    ``anchor`` is the handle a :class:`IRGoto` can jump back to; ``source``
    keeps the original sentence so diagnostics can point at real input.
    """

    text: str = ""
    actor: str | None = None
    anchor: str | None = None
    source: str = ""
    line: int = 0


@dataclass(slots=True)
class IRActivity(IRElement):
    activity_type: ActivityType = ActivityType.TASK


@dataclass(slots=True)
class IREvent(IRElement):
    position: EventPosition = EventPosition.INTERMEDIATE_CATCH
    trigger: EventTrigger = EventTrigger.NONE
    #: Human-readable timer expression ("3 дня", "PT2H", ...) when applicable.
    timer: str = ""


@dataclass(slots=True)
class IRSequence:
    """An ordered list of blocks executed one after another."""

    items: list[IRElement] = field(default_factory=list)

    def append(self, element: IRElement) -> IRElement:
        self.items.append(element)
        return element

    def extend(self, elements: list[IRElement]) -> None:
        self.items.extend(elements)

    @property
    def is_empty(self) -> bool:
        return not self.items

    def __iter__(self) -> Iterator[IRElement]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


@dataclass(slots=True)
class IRArm:
    """One outcome of a decision: a condition label plus the body it guards."""

    label: str = ""
    body: IRSequence = field(default_factory=IRSequence)
    condition: str = ""
    is_default: bool = False


@dataclass(slots=True)
class IRBranch(IRElement):
    """A decision block; ``text`` holds the question asked at the split."""

    branch_type: BranchType = BranchType.EXCLUSIVE
    arms: list[IRArm] = field(default_factory=list)

    def add_arm(self, arm: IRArm) -> IRArm:
        self.arms.append(arm)
        return arm


@dataclass(slots=True)
class IRParallel(IRElement):
    """Concurrently executed branches, joined again at the end of the block."""

    branches: list[IRSequence] = field(default_factory=list)


@dataclass(slots=True)
class IRGoto(IRElement):
    """An explicit jump: rework loops, retries, escalations.

    ``target`` is matched against anchors and activity texts by the builder,
    which keeps authors free to write "вернуться к проверке заявки" instead of
    inventing identifiers.
    """

    target: str = ""


@dataclass(slots=True)
class IRLane:
    name: str
    order: int = 0


@dataclass(slots=True)
class IRProcess:
    """Root of the parsed description."""

    name: str = ""
    root: IRSequence = field(default_factory=IRSequence)
    lanes: list[IRLane] = field(default_factory=list)
    language: str = "ru"
    documentation: str = ""
    #: Front-end supplied overrides, e.g. an explicit process ``id``.
    options: dict[str, str] = field(default_factory=dict)

    def lane_names(self) -> list[str]:
        return [lane.name for lane in sorted(self.lanes, key=lambda x: x.order)]

    def ensure_lane(self, name: str) -> IRLane:
        for lane in self.lanes:
            if lane.name.casefold() == name.casefold():
                return lane
        lane = IRLane(name=name, order=len(self.lanes))
        self.lanes.append(lane)
        return lane


def walk(sequence: IRSequence) -> Iterator[IRElement]:
    """Depth-first traversal over every block of a sequence, nested ones included."""
    for item in sequence.items:
        yield item
        if isinstance(item, IRBranch):
            for arm in item.arms:
                yield from walk(arm.body)
        elif isinstance(item, IRParallel):
            for branch in item.branches:
                yield from walk(branch)
