"""HTTP layer: the API and the served single-page application.

Importing this package pulls in FastAPI, which is an optional extra
(``pip install "bpmn-architect[studio]"``). The engine and the CLI do not
import it, so a plain install stays dependency-free.
"""

from bpmn_architect.server.app import create_app
from bpmn_architect.server.service import BuildRequestOptions, DiagramPayload, DiagramService

__all__ = ["BuildRequestOptions", "DiagramPayload", "DiagramService", "create_app"]
