"""Application service: the one place that orchestrates the core for Studio.

Deliberately free of any web framework import.  The HTTP layer in
:mod:`bpmn_architect.server.routes` only validates input and serialises what
this module returns, which keeps the whole application logic testable without
starting a server — and makes a different transport (a desktop shell, a queue
worker) a matter of writing a new adapter.

Every operation speaks **BPMN 2.0 XML** on the way in and out.  The browser
editor, the Python core and any external tool then share one canonical
representation, so there is no private interchange format to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bpmn_architect.analysis import analyse_ambiguity, apply_clarifications, narrate
from bpmn_architect.building.builder import BuildOptions, ProcessBuilder
from bpmn_architect.domain.model import ProcessModel
from bpmn_architect.interop import import_bpmn
from bpmn_architect.interpreters import InterpreterMode, LLMConfig, create_interpreter
from bpmn_architect.layout.engine import Layout, LayoutEngine
from bpmn_architect.layout.geometry import LayoutMetrics
from bpmn_architect.parsing import ParserOptions
from bpmn_architect.pipeline import describe
from bpmn_architect.rendering.bpmn_xml import BpmnRenderer, BpmnRenderOptions
from bpmn_architect.rendering.json_export import to_dict
from bpmn_architect.rendering.svg import render_svg
from bpmn_architect.sourcemap import build_source_map
from bpmn_architect.validation.diagnostics import Diagnostics, Severity
from bpmn_architect.validation.validator import Validator

__all__ = ["DiagramService", "BuildRequestOptions", "DiagramPayload"]


@dataclass(slots=True)
class BuildRequestOptions:
    """Everything a caller may vary for one generation."""

    mode: str = "deterministic"
    language: str | None = None
    syntax: str = "auto"
    use_lanes: bool = True
    infinitive_names: bool = True
    executable: bool = False
    process_id: str = ""
    process_name: str = ""
    include_documentation: bool = True
    llm_provider: str | None = None
    llm_model: str = ""


@dataclass(slots=True)
class DiagramPayload:
    """The full state of a diagram, as the editor needs it."""

    bpmn: str
    elements: list[dict[str, Any]] = field(default_factory=list)
    lanes: list[dict[str, Any]] = field(default_factory=list)
    flows: list[dict[str, Any]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    source_map: dict[str, Any] = field(default_factory=dict)
    clarifications: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""
    narrative: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bpmn": self.bpmn,
            "elements": self.elements,
            "lanes": self.lanes,
            "flows": self.flows,
            "validation": self.validation,
            "sourceMap": self.source_map,
            "clarifications": self.clarifications,
            "explanation": self.explanation,
            "narrative": self.narrative,
            "meta": self.meta,
        }


class DiagramService:
    """Generation, validation, layout and description of diagrams."""

    def __init__(self, metrics: LayoutMetrics | None = None) -> None:
        self.metrics = metrics or LayoutMetrics()

    # -- generation ----------------------------------------------------------

    def build_from_text(
        self, text: str, options: BuildRequestOptions | None = None
    ) -> DiagramPayload:
        """The main flow: description in, complete diagram state out."""
        options = options or BuildRequestOptions()
        interpreter = create_interpreter(
            InterpreterMode(options.mode),
            config=self._llm_config(options),
            syntax=options.syntax,
            options=ParserOptions(
                infinitive_names=options.infinitive_names,
                detect_lanes=options.use_lanes,
                language=options.language,
            ),
        )
        interpretation = interpreter.interpret(text)

        build = ProcessBuilder(
            BuildOptions(
                process_id=options.process_id,
                process_name=options.process_name,
                use_lanes=options.use_lanes,
                executable=options.executable,
            )
        ).build(interpretation.ir)
        model = build.model
        diagnostics = build.diagnostics
        Validator().validate(model, diagnostics)
        layout = LayoutEngine(self.metrics).run(model)

        language = interpretation.ir.language
        source_map = build_source_map(model, text)
        payload = self._payload(
            model,
            layout,
            diagnostics,
            options,
            language=language,
            explanation=describe(interpretation.ir),
            source_map=source_map.to_dict(),
            clarifications=[
                clarification.to_dict()
                for clarification in analyse_ambiguity(
                    model, language=language, source_map=source_map
                )
            ],
        )
        payload.meta.update(
            {
                "mode": interpretation.mode.value,
                "provider": interpretation.provider,
                "deterministic": interpretation.deterministic,
                "notes": list(interpretation.notes),
                "language": language,
            }
        )
        return payload

    # -- operations on an existing diagram -----------------------------------

    def load(self, bpmn: str, *, source_text: str = "") -> DiagramPayload:
        """Import a diagram and report everything known about it."""
        imported = import_bpmn(bpmn)
        diagnostics = Diagnostics(list(imported.diagnostics))
        Validator().validate(imported.model, diagnostics)
        language = _guess_language(imported.model)
        source_map = (
            build_source_map(imported.model, source_text).to_dict() if source_text else {}
        )
        payload = self._payload(
            imported.model,
            imported.layout,
            diagnostics,
            BuildRequestOptions(),
            language=language,
            source_map=source_map,
            clarifications=[
                clarification.to_dict()
                for clarification in analyse_ambiguity(imported.model, language=language)
            ],
        )
        payload.meta["layoutWasGenerated"] = imported.layout_was_generated
        return payload

    def relayout(self, bpmn: str) -> DiagramPayload:
        """Re-run the layout engine over a diagram the user has edited."""
        imported = import_bpmn(bpmn)
        layout = LayoutEngine(self.metrics).run(imported.model)
        diagnostics = Diagnostics(list(imported.diagnostics))
        Validator().validate(imported.model, diagnostics)
        language = _guess_language(imported.model)
        payload = self._payload(
            imported.model, layout, diagnostics, BuildRequestOptions(), language=language
        )
        payload.meta["relaidOut"] = True
        return payload

    def validate(self, bpmn: str) -> dict[str, Any]:
        imported = import_bpmn(bpmn)
        diagnostics = Diagnostics(list(imported.diagnostics))
        Validator().validate(imported.model, diagnostics)
        return _validation_dict(diagnostics)

    def clarify(self, bpmn: str, answers: dict[str, str]) -> DiagramPayload:
        """Apply answers to the open questions and re-render the diagram.

        The questions are recomputed from the diagram rather than stored
        server-side: the same model always yields the same question ids, so the
        endpoint stays stateless.
        """
        imported = import_bpmn(bpmn)
        model = imported.model
        language = _guess_language(model)
        questions = analyse_ambiguity(model, language=language)
        diagnostics = Diagnostics(list(imported.diagnostics))
        diagnostics.extend(apply_clarifications(model, questions, answers))
        layout = LayoutEngine(self.metrics).run(model)
        Validator().validate(model, diagnostics)
        return self._payload(
            model,
            layout,
            diagnostics,
            BuildRequestOptions(),
            language=language,
            clarifications=[
                clarification.to_dict()
                for clarification in analyse_ambiguity(model, language=language)
            ],
        )

    def narrate(self, bpmn: str, language: str | None = None) -> str:
        imported = import_bpmn(bpmn)
        return narrate(imported.model, language=language or _guess_language(imported.model))

    def to_svg(self, bpmn: str) -> str:
        imported = import_bpmn(bpmn)
        return render_svg(imported.model, imported.layout)

    def to_json(self, bpmn: str) -> dict[str, Any]:
        imported = import_bpmn(bpmn)
        return to_dict(imported.model, imported.layout)

    # -- assembly ------------------------------------------------------------

    def _payload(
        self,
        model: ProcessModel,
        layout: Layout,
        diagnostics: Diagnostics,
        options: BuildRequestOptions,
        *,
        language: str = "ru",
        explanation: str = "",
        source_map: dict[str, Any] | None = None,
        clarifications: list[dict[str, Any]] | None = None,
    ) -> DiagramPayload:
        renderer = BpmnRenderer(
            BpmnRenderOptions(include_source_documentation=options.include_documentation)
        )
        lane_names = {lane.id: lane.name for lane in model.lanes}
        return DiagramPayload(
            bpmn=renderer.render(model, layout),
            elements=[
                {
                    "id": node.id,
                    "type": node.kind.value,
                    "name": node.name,
                    "category": _category(node.kind),
                    "lane": node.lane_id,
                    "laneName": lane_names.get(node.lane_id or "", ""),
                    "eventDefinition": (
                        None if node.event_definition.is_none else node.event_definition.value
                    ),
                    "documentation": node.documentation or node.attrs.get("source", ""),
                    "incoming": [flow.id for flow in model.incoming(node.id)],
                    "outgoing": [flow.id for flow in model.outgoing(node.id)],
                    "attributes": dict(node.attrs),
                }
                for node in model.nodes
            ],
            lanes=[
                {"id": lane.id, "name": lane.name, "order": lane.order} for lane in model.lanes
            ],
            flows=[
                {
                    "id": flow.id,
                    "source": flow.source_id,
                    "target": flow.target_id,
                    "name": flow.name,
                    "condition": flow.condition,
                    "isDefault": flow.is_default,
                }
                for flow in model.flows
            ],
            validation=_validation_dict(diagnostics),
            source_map=source_map or {},
            clarifications=clarifications or [],
            explanation=explanation,
            narrative=narrate(model, language=language),
            meta={
                "processId": model.id,
                "processName": model.name,
                "elementCount": len(model),
                "flowCount": len(model.flows),
                "laneCount": len(model.lanes),
                "language": language,
            },
        )

    def _llm_config(self, options: BuildRequestOptions) -> LLMConfig | None:
        if not InterpreterMode(options.mode).needs_provider:
            return None
        config = LLMConfig.from_env(options.llm_provider)
        if options.llm_model:
            config.model = options.llm_model
        return config


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _category(kind: Any) -> str:
    if kind.is_event:
        return "event"
    if kind.is_gateway:
        return "gateway"
    if kind.is_activity:
        return "activity"
    return "other"


def _validation_dict(diagnostics: Diagnostics) -> dict[str, Any]:
    items = [
        {
            "code": diagnostic.code,
            "severity": diagnostic.severity.value,
            "message": diagnostic.message,
            "elementId": diagnostic.element_id,
            "line": diagnostic.line,
        }
        for diagnostic in diagnostics.sorted()
    ]
    counts = {
        severity.value: sum(1 for d in diagnostics if d.severity is severity)
        for severity in Severity
    }
    return {"ok": not diagnostics.has_errors, "counts": counts, "diagnostics": items}


def _guess_language(model: ProcessModel) -> str:
    from bpmn_architect.parsing.lexicon import detect_language

    sample = " ".join(
        [model.name, *(node.name for node in model.nodes), *(lane.name for lane in model.lanes)]
    )
    return detect_language(sample) if sample.strip() else "en"
