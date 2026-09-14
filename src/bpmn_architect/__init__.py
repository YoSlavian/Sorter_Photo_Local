"""BPMN Architect - automatic BPMN 2.0 diagram synthesis from process descriptions.

Typical use::

    from bpmn_architect import generate

    result = generate("Процесс начинается с получения заявки. ...")
    Path("process.bpmn").write_text(result.to_bpmn(), encoding="utf-8")

The package is layered; each layer is independently usable and independently
testable:

``bpmn_architect.parsing``     text        -> IR block tree
``bpmn_architect.building``    IR          -> BPMN process graph
``bpmn_architect.validation``  graph       -> diagnostics
``bpmn_architect.layout``      graph       -> geometry
``bpmn_architect.rendering``   graph + geometry -> BPMN XML / SVG / JSON
"""

from __future__ import annotations

__version__ = "1.0.0"

from bpmn_architect.domain.model import Flow, Lane, Node, NodeKind, ProcessModel
from bpmn_architect.errors import (
    BpmnArchitectError,
    BuildError,
    LayoutError,
    ParseError,
    RenderError,
    ValidationFailed,
)
from bpmn_architect.pipeline import DiagramResult, PipelineOptions, describe, generate

__all__ = [
    "BpmnArchitectError",
    "BuildError",
    "DiagramResult",
    "Flow",
    "Lane",
    "LayoutError",
    "Node",
    "NodeKind",
    "ParseError",
    "PipelineOptions",
    "ProcessModel",
    "RenderError",
    "ValidationFailed",
    "__version__",
    "describe",
    "generate",
]
