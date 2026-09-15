"""The ``.bpmn-project`` container: text and diagram saved together.

A plain ``.bpmn`` file loses the thing that makes Studio different — the
description the diagram was generated from, and therefore the link between the
two.  The project file keeps both, so reopening a project restores the text,
the diagram with its exact geometry, and the editor state.

The diagram is stored as **BPMN 2.0 XML**, not as a private structure: a
project file can always be unpacked back into a standard file, and a corrupt
or future-version project still yields a usable diagram.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from bpmn_architect import __version__
from bpmn_architect.errors import ParseError

__all__ = ["ProjectFile", "PROJECT_VERSION", "load_project", "dump_project"]

PROJECT_VERSION = 1
_EXTENSION = ".bpmn-project"


@dataclass(slots=True)
class ProjectMetadata:
    name: str = ""
    createdAt: str = ""  # noqa: N815 - the wire format is camelCase
    updatedAt: str = ""  # noqa: N815
    generator: str = f"bpmn-architect {__version__}"


@dataclass(slots=True)
class ProjectFile:
    """Everything needed to restore a working session."""

    bpmn: str = ""
    sourceText: str = ""  # noqa: N815 - camelCase on the wire
    settings: dict[str, Any] = field(default_factory=dict)
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)
    version: int = PROJECT_VERSION

    def touch(self) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.metadata.createdAt:
            self.metadata.createdAt = now
        self.metadata.updatedAt = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sourceText": self.sourceText,
            "bpmn": self.bpmn,
            "settings": dict(self.settings),
            "metadata": asdict(self.metadata),
        }


def dump_project(project: ProjectFile, *, indent: int = 2) -> str:
    """Serialise a project, stamping the modification time."""
    project.touch()
    return json.dumps(project.to_dict(), ensure_ascii=False, indent=indent) + "\n"


def load_project(source: str | bytes) -> ProjectFile:
    """Read a project file, tolerating anything a future version may add."""
    text = source.decode("utf-8") if isinstance(source, bytes) else source
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ParseError(f"the project file is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ParseError("the project file must contain a JSON object")

    version = payload.get("version", PROJECT_VERSION)
    if not isinstance(version, int) or version > PROJECT_VERSION:
        raise ParseError(
            f"project version {version} is newer than this build supports "
            f"(up to {PROJECT_VERSION}); update BPMN Architect to open it"
        )
    bpmn = payload.get("bpmn")
    if not isinstance(bpmn, str) or "<" not in bpmn:
        raise ParseError("the project file contains no BPMN diagram")

    raw_metadata = payload.get("metadata") or {}
    metadata = ProjectMetadata(
        name=str(raw_metadata.get("name", "")),
        createdAt=str(raw_metadata.get("createdAt", "")),
        updatedAt=str(raw_metadata.get("updatedAt", "")),
        generator=str(raw_metadata.get("generator", "")),
    )
    settings = payload.get("settings")
    return ProjectFile(
        bpmn=bpmn,
        sourceText=str(payload.get("sourceText", "")),
        settings=settings if isinstance(settings, dict) else {},
        metadata=metadata,
        version=version,
    )


def project_filename(name: str) -> str:
    """A safe file name for a project called ``name``."""
    from bpmn_architect.ids import slugify

    return f"{slugify(name) or 'process'}{_EXTENSION}"
