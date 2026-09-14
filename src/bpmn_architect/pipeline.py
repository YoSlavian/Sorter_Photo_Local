"""End-to-end facade: text in, diagram out.

    text ──parse──▶ IR ──build──▶ ProcessModel ──validate──▶ diagnostics
                                        │
                                        └──layout──▶ Layout ──render──▶ BPMN / SVG / JSON

Every stage is usable on its own; this module just wires the default pipeline
together so that the common case is a single call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bpmn_architect.building.builder import BuildOptions, ProcessBuilder
from bpmn_architect.domain.ir import (
    IRBranch,
    IRElement,
    IREvent,
    IRGoto,
    IRParallel,
    IRProcess,
    IRSequence,
)
from bpmn_architect.domain.model import ProcessModel
from bpmn_architect.errors import ValidationFailed
from bpmn_architect.layout.engine import Layout, LayoutEngine
from bpmn_architect.layout.geometry import LayoutMetrics
from bpmn_architect.parsing import ParserOptions, parse
from bpmn_architect.rendering.bpmn_xml import BpmnRenderer, BpmnRenderOptions
from bpmn_architect.rendering.json_export import render_json
from bpmn_architect.rendering.svg import SvgRenderOptions, render_svg
from bpmn_architect.validation.diagnostics import Diagnostics
from bpmn_architect.validation.validator import Validator

__all__ = ["PipelineOptions", "DiagramResult", "generate", "describe"]


@dataclass(slots=True)
class PipelineOptions:
    syntax: str = "auto"
    parser: ParserOptions = field(default_factory=ParserOptions)
    build: BuildOptions = field(default_factory=BuildOptions)
    metrics: LayoutMetrics = field(default_factory=LayoutMetrics)
    render: BpmnRenderOptions = field(default_factory=BpmnRenderOptions)
    svg: SvgRenderOptions = field(default_factory=SvgRenderOptions)
    run_validation: bool = True
    #: Raise instead of returning a model when validation reports errors.
    strict: bool = False


@dataclass(slots=True)
class DiagramResult:
    """The artefacts of one run, plus everything needed to explain them."""

    source: str
    ir: IRProcess
    model: ProcessModel
    layout: Layout
    diagnostics: Diagnostics
    options: PipelineOptions

    def to_bpmn(self) -> str:
        return BpmnRenderer(self.options.render).render(self.model, self.layout)

    def to_svg(self) -> str:
        return render_svg(self.model, self.layout, self.options.svg)

    def to_json(self) -> str:
        return render_json(self.model, self.layout)

    def explain(self) -> str:
        return describe(self.ir)

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics.has_errors


def generate(text: str, options: PipelineOptions | None = None) -> DiagramResult:
    """Run the full pipeline over a process description."""
    options = options or PipelineOptions()

    process_ir = parse(text, syntax=options.syntax, options=options.parser)
    build = ProcessBuilder(options.build).build(process_ir)
    diagnostics = build.diagnostics
    if options.run_validation:
        Validator().validate(build.model, diagnostics)
    if options.strict and diagnostics.has_errors:
        raise ValidationFailed(
            f"the generated diagram violates {len(diagnostics.errors)} structural rule(s)",
            list(diagnostics.errors),
        )
    layout = LayoutEngine(options.metrics).run(build.model)
    return DiagramResult(
        source=text,
        ir=process_ir,
        model=build.model,
        layout=layout,
        diagnostics=diagnostics,
        options=options,
    )


# --------------------------------------------------------------------------- #
# Explanation
# --------------------------------------------------------------------------- #


def describe(process_ir: IRProcess) -> str:
    """Render the parsed structure as an indented tree.

    This is the tool's "show your work" view: when a description produces an
    unexpected diagram, the tree shows exactly which sentence became which
    element, which is far easier to reason about than the resulting XML.
    """
    lines: list[str] = [
        f"process: {process_ir.name or '(unnamed)'}  [{process_ir.language}]",
    ]
    if process_ir.lanes:
        lines.append(f"lanes:   {', '.join(process_ir.lane_names())}")
    lines.append("")
    lines.extend(_describe_sequence(process_ir.root, 0))
    return "\n".join(lines) + "\n"


def _describe_sequence(sequence: IRSequence, depth: int) -> list[str]:
    indent = "  " * depth
    lines: list[str] = []
    for element in sequence:
        if isinstance(element, IRBranch):
            lines.append(f"{indent}<{element.branch_type.value}> {element.text}{_actor(element)}")
            for arm in element.arms:
                marker = " (default)" if arm.is_default else ""
                lines.append(f"{indent}  case {arm.label!r}{marker}")
                lines.extend(_describe_sequence(arm.body, depth + 2))
        elif isinstance(element, IRParallel):
            lines.append(f"{indent}<parallel>")
            for index, branch in enumerate(element.branches, start=1):
                lines.append(f"{indent}  branch {index}")
                lines.extend(_describe_sequence(branch, depth + 2))
        elif isinstance(element, IRGoto):
            lines.append(f"{indent}<goto> -> {element.target!r}")
        elif isinstance(element, IREvent):
            trigger = "" if element.trigger.value == "none" else f" ({element.trigger.value})"
            lines.append(f"{indent}<{element.position.value}> {element.text}{trigger}{_actor(element)}")
        else:
            kind = getattr(element, "activity_type", None)
            label = kind.value if kind is not None else "task"
            lines.append(f"{indent}<{label}> {element.text}{_actor(element)}")
    return lines


def _actor(element: IRElement) -> str:
    return f"   [{element.actor}]" if element.actor else ""
