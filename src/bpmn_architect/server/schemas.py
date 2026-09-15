"""Request and response shapes for the HTTP API.

These models are the contract the frontend codes against, and they are
deliberately *not* mirrors of the domain classes: the web layer is free to
evolve without dragging the engine with it, and the engine is free to change
internals without breaking a published API.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = [
    "BuildOptionsIn",
    "BuildRequest",
    "ParseRequest",
    "DiagramRequest",
    "ClarifyRequest",
    "DescribeRequest",
    "ProjectExportRequest",
    "ProjectImportRequest",
    "DiagramResponse",
    "ValidationResponse",
    "ParseResponse",
    "TextResponse",
    "InfoResponse",
    "HealthResponse",
]

Mode = Literal["deterministic", "ai", "hybrid"]
Syntax = Literal["auto", "text", "dsl"]
Language = Literal["ru", "en"]


class BuildOptionsIn(BaseModel):
    """Generation options; every field has a working default."""

    mode: Mode = Field("deterministic", description="Interpretation mode")
    syntax: Syntax = Field("auto", description="Input front end")
    language: Language | None = Field(None, description="Force the input language")
    useLanes: bool = Field(True, description="Derive swimlanes from the detected actors")
    infinitiveNames: bool = Field(True, description="Rewrite activities in the infinitive")
    executable: bool = Field(False, description="Mark the process as executable")
    includeDocumentation: bool = Field(
        True, description="Copy source sentences into bpmn:documentation"
    )
    processId: str = Field("", description="Identifier of the generated bpmn:process")
    processName: str = Field("", description="Name of the generated process")
    llmProvider: str | None = Field(None, description="anthropic | openai | local")
    llmModel: str = Field("", description="Override the provider's default model")


class BuildRequest(BaseModel):
    text: str = Field(..., description="The process description")
    # Pydantic deep-copies model defaults, so this is not shared state.
    options: BuildOptionsIn = BuildOptionsIn()


class ParseRequest(BaseModel):
    text: str
    options: BuildOptionsIn = BuildOptionsIn()


class DiagramRequest(BaseModel):
    bpmn: str = Field(..., description="BPMN 2.0 XML")
    sourceText: str = Field("", description="Original description, if the caller still has it")


class ClarifyRequest(BaseModel):
    bpmn: str
    answers: dict[str, str] = Field(
        default_factory=dict, description="Question id -> the user's answer"
    )


class DescribeRequest(BaseModel):
    bpmn: str
    language: Language | None = None


class ProjectExportRequest(BaseModel):
    bpmn: str
    sourceText: str = ""
    name: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectImportRequest(BaseModel):
    project: str = Field(..., description="Contents of a .bpmn-project file")


class ValidationResponse(BaseModel):
    ok: bool
    counts: dict[str, int]
    diagnostics: list[dict[str, Any]]


class DiagramResponse(BaseModel):
    """The complete state of a diagram, as the editor consumes it."""

    bpmn: str
    elements: list[dict[str, Any]]
    lanes: list[dict[str, Any]]
    flows: list[dict[str, Any]]
    validation: ValidationResponse
    sourceMap: dict[str, Any]
    clarifications: list[dict[str, Any]]
    explanation: str
    narrative: str
    meta: dict[str, Any]


class ParseResponse(BaseModel):
    explanation: str
    language: str
    mode: str
    deterministic: bool
    notes: list[str]


class TextResponse(BaseModel):
    text: str


class ProjectResponse(BaseModel):
    project: str
    filename: str


class ProjectLoadResponse(BaseModel):
    diagram: DiagramResponse
    sourceText: str
    settings: dict[str, Any]
    metadata: dict[str, Any]


class InfoResponse(BaseModel):
    version: str
    modes: list[str]
    providers: dict[str, bool]
    languages: list[str]
    elementTypes: list[dict[str, str]]


class HealthResponse(BaseModel):
    status: str
    version: str
