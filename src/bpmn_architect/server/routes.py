"""HTTP endpoints.

Thin by design: validate, delegate to :class:`DiagramService`, serialise.  All
the behaviour worth testing lives in the service, so these functions stay
readable and the OpenAPI document stays an accurate description of the product
rather than of the engine.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from bpmn_architect import __version__
from bpmn_architect.domain.model import NodeKind
from bpmn_architect.errors import BpmnArchitectError, ParseError
from bpmn_architect.interpreters import InterpreterMode, LLMConfig, create_interpreter
from bpmn_architect.interpreters.base import InterpreterError
from bpmn_architect.interpreters.providers import resolve_provider
from bpmn_architect.pipeline import describe
from bpmn_architect.server import schemas
from bpmn_architect.server.project import ProjectFile, dump_project, load_project, project_filename
from bpmn_architect.server.service import BuildRequestOptions, DiagramService

__all__ = ["router", "service"]

router = APIRouter(prefix="/api", tags=["bpmn"])
service = DiagramService()


def _options(payload: schemas.BuildOptionsIn) -> BuildRequestOptions:
    return BuildRequestOptions(
        mode=payload.mode,
        language=payload.language,
        syntax=payload.syntax,
        use_lanes=payload.useLanes,
        infinitive_names=payload.infinitiveNames,
        executable=payload.executable,
        process_id=payload.processId,
        process_name=payload.processName,
        include_documentation=payload.includeDocumentation,
        llm_provider=payload.llmProvider,
        llm_model=payload.llmModel,
    )


@contextmanager
def _guard(operation: str) -> Iterator[None]:
    """Translate engine errors into HTTP answers that say what to do.

    The distinction matters to the client: a malformed file is the caller's
    problem (400), an unconfigured model backend is a server-side gap the user
    can fix (422), and anything else is not swallowed at all.
    """
    try:
        yield
    except ParseError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except InterpreterError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except BpmnArchitectError as error:
        raise HTTPException(status_code=400, detail=f"{operation} failed: {error}") from error


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


@router.get("/health", response_model=schemas.HealthResponse, summary="Liveness probe")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/info", response_model=schemas.InfoResponse, summary="Server capabilities")
def info() -> dict[str, Any]:
    providers: dict[str, bool] = {}
    for name in ("anthropic", "openai", "local"):
        try:
            providers[name] = resolve_provider(LLMConfig(provider=name)).available()
        except BpmnArchitectError:
            providers[name] = False
    return {
        "version": __version__,
        "modes": [mode.value for mode in InterpreterMode],
        "providers": providers,
        "languages": ["ru", "en"],
        "elementTypes": [
            {
                "type": kind.value,
                "category": (
                    "event"
                    if kind.is_event
                    else "gateway"
                    if kind.is_gateway
                    else "activity"
                ),
            }
            for kind in NodeKind
        ],
    }


# --------------------------------------------------------------------------- #
# Text to diagram
# --------------------------------------------------------------------------- #


@router.post(
    "/parse",
    response_model=schemas.ParseResponse,
    summary="Read a description without building a diagram",
)
def parse_text(request: schemas.ParseRequest) -> dict[str, Any]:
    from bpmn_architect.parsing import ParserOptions

    with _guard("parsing"):
        interpreter = create_interpreter(
            InterpreterMode(request.options.mode),
            syntax=request.options.syntax,
            options=ParserOptions(
                infinitive_names=request.options.infinitiveNames,
                detect_lanes=request.options.useLanes,
                language=request.options.language,
            ),
        )
        result = interpreter.interpret(request.text)
    return {
        "explanation": describe(result.ir),
        "language": result.ir.language,
        "mode": result.mode.value,
        "deterministic": result.deterministic,
        "notes": list(result.notes),
    }


@router.post(
    "/build",
    response_model=schemas.DiagramResponse,
    summary="Build a BPMN diagram from a description",
)
def build(request: schemas.BuildRequest) -> dict[str, Any]:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="the description is empty")
    with _guard("building"):
        payload = service.build_from_text(request.text, _options(request.options))
    return payload.to_dict()


# --------------------------------------------------------------------------- #
# Operations on a diagram
# --------------------------------------------------------------------------- #


@router.post(
    "/validate", response_model=schemas.ValidationResponse, summary="Check a diagram"
)
def validate(request: schemas.DiagramRequest) -> dict[str, Any]:
    with _guard("validation"):
        return service.validate(request.bpmn)


@router.post(
    "/layout", response_model=schemas.DiagramResponse, summary="Re-run the auto layout"
)
def layout(request: schemas.DiagramRequest) -> dict[str, Any]:
    with _guard("layout"):
        return service.relayout(request.bpmn).to_dict()


@router.post(
    "/clarify",
    response_model=schemas.DiagramResponse,
    summary="Answer the open questions about a diagram",
)
def clarify(request: schemas.ClarifyRequest) -> dict[str, Any]:
    with _guard("clarification"):
        return service.clarify(request.bpmn, request.answers).to_dict()


@router.post(
    "/describe", response_model=schemas.TextResponse, summary="Describe a diagram in words"
)
def describe_diagram(request: schemas.DescribeRequest) -> dict[str, str]:
    with _guard("description"):
        return {"text": service.narrate(request.bpmn, request.language)}


# --------------------------------------------------------------------------- #
# Import and export
# --------------------------------------------------------------------------- #


@router.post(
    "/bpmn/import", response_model=schemas.DiagramResponse, summary="Open a BPMN 2.0 file"
)
def import_diagram(request: schemas.DiagramRequest) -> dict[str, Any]:
    with _guard("import"):
        return service.load(request.bpmn, source_text=request.sourceText).to_dict()


@router.post("/bpmn/export", summary="Download the diagram as BPMN 2.0 XML")
def export_bpmn(request: schemas.DiagramRequest) -> Response:
    with _guard("export"):
        service.validate(request.bpmn)  # refuse to hand out an unreadable file
    return Response(
        content=request.bpmn,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="process.bpmn"'},
    )


@router.post("/export/svg", summary="Download the diagram as SVG")
def export_svg(request: schemas.DiagramRequest) -> Response:
    with _guard("export"):
        svg = service.to_svg(request.bpmn)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition": 'attachment; filename="process.svg"'},
    )


@router.post("/export/json", summary="Download the diagram as JSON")
def export_json(request: schemas.DiagramRequest) -> Response:
    with _guard("export"):
        payload = service.to_json(request.bpmn)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="process.json"'},
    )


@router.post(
    "/project/export", response_model=schemas.ProjectResponse, summary="Save a project"
)
def export_project(request: schemas.ProjectExportRequest) -> dict[str, str]:
    with _guard("project export"):
        service.validate(request.bpmn)
    project = ProjectFile(
        bpmn=request.bpmn, sourceText=request.sourceText, settings=request.settings
    )
    project.metadata.name = request.name
    return {
        "project": dump_project(project),
        "filename": project_filename(request.name or "process"),
    }


@router.post(
    "/project/import",
    response_model=schemas.ProjectLoadResponse,
    summary="Open a saved project",
)
def import_project(request: schemas.ProjectImportRequest) -> dict[str, Any]:
    with _guard("project import"):
        project = load_project(request.project)
        diagram = service.load(project.bpmn, source_text=project.sourceText)
    return {
        "diagram": diagram.to_dict(),
        "sourceText": project.sourceText,
        "settings": project.settings,
        "metadata": {
            "name": project.metadata.name,
            "createdAt": project.metadata.createdAt,
            "updatedAt": project.metadata.updatedAt,
            "generator": project.metadata.generator,
        },
    }
