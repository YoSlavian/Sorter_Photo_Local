"""The FastAPI application.

Studio is served as a single origin: the API under ``/api`` and the built
single-page app at the root.  That removes CORS, cookie and port mismatches
from the user's machine entirely — ``bpmn-architect studio`` starts one process
and opens one URL.  A separate dev server is still supported, which is why CORS
is configured rather than absent.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from bpmn_architect import __version__
from bpmn_architect.server.routes import router

__all__ = ["create_app", "static_directory"]

_DESCRIPTION = """\
BPMN Architect Studio — build BPMN 2.0 diagrams from a textual description of a
business process, then edit them visually.

The pipeline is text → interpretation → process graph → validation → layout →
BPMN 2.0 XML with diagram interchange. Every endpoint speaks standard BPMN XML,
so the diagram can leave for any other modelling tool at any point.
"""

#: Dev servers that may talk to a separately started backend.
_DEFAULT_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
)


def static_directory() -> Path:
    """Where the built frontend is expected to live."""
    override = os.getenv("BPMN_ARCHITECT_STATIC_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "static"


def create_app(
    *,
    static_dir: Path | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Build the application; the frontend is optional."""
    app = FastAPI(
        title="BPMN Architect Studio",
        description=_DESCRIPTION,
        version=__version__,
        openapi_tags=[{"name": "bpmn", "description": "Diagram generation and editing"}],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else list(_DEFAULT_ORIGINS),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    root = static_dir or static_directory()
    index = root / "index.html"
    if index.is_file():
        # Hashed build assets are safe to cache hard; index.html must not be.
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def spa_root() -> FileResponse:
            return FileResponse(index)

        # response_model=None: the return type is a union of responses, which
        # FastAPI would otherwise try to turn into a response schema.
        @app.get("/{path:path}", include_in_schema=False, response_model=None)
        def spa_fallback(path: str) -> Response:
            # Client-side routes must fall back to the shell; a missing API
            # path must still look like a missing API path.
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (root / path).resolve()
            if candidate.is_file() and root.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
