"""JSON projection of the model and its layout.

Useful as an integration boundary: web front ends, diffing tools and test
fixtures all prefer JSON to XML, and the structure mirrors the domain model
one-to-one so it needs no documentation of its own.
"""

from __future__ import annotations

import json
from typing import Any

from bpmn_architect.domain.model import ProcessModel
from bpmn_architect.layout.engine import Layout

__all__ = ["to_dict", "render_json"]


def to_dict(model: ProcessModel, layout: Layout | None = None) -> dict[str, Any]:
    """Project the process (and optionally its geometry) into plain data."""
    payload: dict[str, Any] = {
        "process": {
            "id": model.id,
            "name": model.name,
            "isExecutable": model.is_executable,
        },
        "lanes": [{"id": lane.id, "name": lane.name, "order": lane.order} for lane in model.lanes],
        "nodes": [
            {
                "id": node.id,
                "type": node.kind.value,
                "name": node.name,
                "lane": node.lane_id,
                "eventDefinition": (
                    None if node.event_definition.is_none else node.event_definition.value
                ),
                "attributes": dict(node.attrs),
            }
            for node in model.nodes
        ],
        "flows": [
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
    }
    if layout is not None:
        payload["layout"] = {
            "shapes": {
                node_id: {
                    "x": bounds.x,
                    "y": bounds.y,
                    "width": bounds.width,
                    "height": bounds.height,
                }
                for node_id, bounds in layout.shapes.items()
            },
            "edges": {
                flow_id: [{"x": point.x, "y": point.y} for point in points]
                for flow_id, points in layout.waypoints.items()
            },
            "lanes": {
                lane_id: {
                    "x": bounds.x,
                    "y": bounds.y,
                    "width": bounds.width,
                    "height": bounds.height,
                }
                for lane_id, bounds in layout.lanes.items()
            },
        }
    return payload


def render_json(model: ProcessModel, layout: Layout | None = None, *, indent: int = 2) -> str:
    return json.dumps(to_dict(model, layout), ensure_ascii=False, indent=indent) + "\n"
