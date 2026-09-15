"""Interoperability layer: reading foreign BPMN files and project archives.

The existing ``rendering`` package is output-only.  Studio also needs the
opposite direction — a diagram edited in the browser, or a file produced by
Camunda Modeler or Bizagi, has to come back into :class:`ProcessModel` so the
same validation and layout engines can be applied to it.  That round trip is
what makes the web editor a view onto the real model instead of a detached
drawing surface.
"""

from bpmn_architect.interop.bpmn_import import (
    BpmnImportResult,
    import_bpmn,
    read_bpmn,
)

__all__ = ["BpmnImportResult", "import_bpmn", "read_bpmn"]
