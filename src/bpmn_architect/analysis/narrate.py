"""Describing a diagram in words — the reverse of the parser.

Two features rest on this: "explain this diagram", which lets a reviewer read
back what a schema actually says, and "generate description", which turns a
diagram imported from elsewhere into text the rest of the pipeline can work
with.

The walk is structural rather than positional: it follows sequence flows from
the start events, recurses into each branch of a gateway, and stops at a node
it has already described — so loops are reported as returns instead of being
followed forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bpmn_architect.domain.model import NodeKind, ProcessModel

__all__ = ["narrate"]


_PHRASES: dict[str, dict[str, str]] = {
    "ru": {
        "title": "Процесс «{name}»",
        "start": "Процесс начинается с события «{name}».",
        "start_plain": "Процесс начинается.",
        "task": "{actor} выполняет шаг «{name}».",
        "task_no_actor": "Выполняется шаг «{name}».",
        "service": "{actor} автоматически выполняет «{name}».",
        "wait": "Процесс ожидает события «{name}».",
        "throw": "Процесс сообщает о событии «{name}».",
        "xor": "Далее принимается решение: {question}",
        "xor_plain": "Далее поток разветвляется.",
        "arm": "Если «{label}» — ",
        "arm_default": "В остальных случаях — ",
        "parallel": "Далее параллельно выполняются несколько ветвей.",
        "branch": "Ветвь {index}:",
        "join": "После этого ветви объединяются.",
        "loop": "Далее происходит возврат к шагу «{name}».",
        "loop_plain": "Далее происходит возврат к предыдущему шагу.",
        "merge": "Эта ветвь соединяется с основным потоком.",
        "end": "Процесс завершается событием «{name}».",
        "end_plain": "Процесс завершается.",
        "lanes": "Участники: {lanes}.",
    },
    "en": {
        "title": "Process “{name}”",
        "start": "The process starts with “{name}”.",
        "start_plain": "The process starts.",
        "task": "{actor} performs “{name}”.",
        "task_no_actor": "“{name}” is performed.",
        "service": "{actor} performs “{name}” automatically.",
        "wait": "The process waits for “{name}”.",
        "throw": "The process signals “{name}”.",
        "xor": "A decision follows: {question}",
        "xor_plain": "The flow branches.",
        "arm": "If “{label}” — ",
        "arm_default": "Otherwise — ",
        "parallel": "Several branches run in parallel.",
        "branch": "Branch {index}:",
        "join": "The branches are then merged.",
        "loop": "The flow returns to “{name}”.",
        "loop_plain": "The flow returns to an earlier step.",
        "merge": "This branch rejoins the main flow.",
        "end": "The process ends with “{name}”.",
        "end_plain": "The process ends.",
        "lanes": "Participants: {lanes}.",
    },
}


@dataclass(slots=True)
class _Walk:
    model: ProcessModel
    language: str
    lines: list[str] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)

    def phrase(self, key: str, **values: str) -> str:
        return _PHRASES[self.language][key].format(**values)

    def actor_of(self, node_id: str) -> str:
        lane_id = self.model.node(node_id).lane_id
        return self.model.lane(lane_id).name if lane_id else ""


def narrate(model: ProcessModel, *, language: str = "ru") -> str:
    """Render the process as readable prose."""
    language = language if language in _PHRASES else "en"
    walk = _Walk(model=model, language=language)

    if model.name:
        walk.lines.append(walk.phrase("title", name=model.name))
    if model.has_lanes:
        walk.lines.append(
            walk.phrase("lanes", lanes=", ".join(lane.name for lane in model.lanes))
        )
    if walk.lines:
        walk.lines.append("")

    starts = model.start_events or [
        node for node in model.nodes if not model.incoming(node.id)
    ]
    if not starts:
        return "\n".join(walk.lines).strip() + "\n"
    for start in starts:
        _describe(walk, start.id, indent=0)
    return "\n".join(line for line in walk.lines).strip() + "\n"


def _describe(walk: _Walk, node_id: str, indent: int) -> None:
    model = walk.model
    pad = "  " * indent
    while True:
        if node_id in walk.visited:
            # Reaching a node twice means one of two very different things:
            # a branch arriving at a join that was already described, or a
            # genuine rework loop. Only the second is a "return".
            seen = model.node(node_id)
            if seen.kind.is_gateway and len(model.incoming(node_id)) > 1:
                walk.lines.append(pad + walk.phrase("merge"))
            elif seen.name:
                walk.lines.append(pad + walk.phrase("loop", name=seen.name))
            else:
                walk.lines.append(pad + walk.phrase("loop_plain"))
            return
        walk.visited.add(node_id)
        node = model.node(node_id)

        if node.kind.is_start:
            walk.lines.append(
                pad + (walk.phrase("start", name=node.name) if node.name else walk.phrase("start_plain"))
            )
        elif node.kind.is_end:
            walk.lines.append(
                pad + (walk.phrase("end", name=node.name) if node.name else walk.phrase("end_plain"))
            )
            return
        elif node.kind is NodeKind.INTERMEDIATE_CATCH_EVENT:
            walk.lines.append(pad + walk.phrase("wait", name=node.label))
        elif node.kind is NodeKind.INTERMEDIATE_THROW_EVENT:
            walk.lines.append(pad + walk.phrase("throw", name=node.label))
        elif node.kind.is_activity:
            actor = walk.actor_of(node_id)
            key = "service" if node.kind is NodeKind.SERVICE_TASK and actor else "task"
            walk.lines.append(
                pad
                + (
                    walk.phrase(key, actor=actor, name=node.label)
                    if actor
                    else walk.phrase("task_no_actor", name=node.label)
                )
            )
        elif node.kind.is_gateway:
            _describe_gateway(walk, node_id, indent)
            return

        outgoing = model.outgoing(node_id)
        if not outgoing:
            return
        if len(outgoing) > 1:  # an implicit split on a non-gateway
            for flow in outgoing:
                _describe(walk, flow.target_id, indent + 1)
            return
        node_id = outgoing[0].target_id


def _describe_gateway(walk: _Walk, node_id: str, indent: int) -> None:
    model = walk.model
    pad = "  " * indent
    node = model.node(node_id)
    outgoing = model.outgoing(node_id)

    if len(outgoing) <= 1:
        walk.lines.append(pad + walk.phrase("join"))
        if outgoing:
            _describe(walk, outgoing[0].target_id, indent)
        return

    if node.kind is NodeKind.PARALLEL_GATEWAY:
        walk.lines.append(pad + walk.phrase("parallel"))
        for index, flow in enumerate(outgoing, start=1):
            walk.lines.append(pad + "  " + walk.phrase("branch", index=str(index)))
            _describe(walk, flow.target_id, indent + 2)
        return

    walk.lines.append(
        pad
        + (walk.phrase("xor", question=node.name) if node.name else walk.phrase("xor_plain"))
    )
    for flow in outgoing:
        label = flow.name or flow.condition
        lead = (
            walk.phrase("arm_default")
            if flow.is_default and not label
            else walk.phrase("arm", label=label or "?")
        )
        walk.lines.append(pad + "  " + lead.strip())
        _describe(walk, flow.target_id, indent + 2)
