"""Stand-alone SVG preview of a laid-out process.

BPMN XML is the deliverable; this renderer exists so that a human (or a CI job)
can *see* the result without opening a modelling tool.  It draws the same
geometry the BPMN-DI section contains, so anything that looks wrong here looks
wrong in Camunda Modeler too — which makes it an effective regression check for
the layout engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from bpmn_architect.domain.model import EventDefinition, NodeKind, ProcessModel
from bpmn_architect.layout.engine import Layout
from bpmn_architect.layout.geometry import Bounds

__all__ = ["SvgRenderOptions", "render_svg"]

_MARGIN = 24.0


@dataclass(slots=True)
class SvgRenderOptions:
    font_family: str = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
    font_size: float = 11.0
    stroke: str = "#3a3f4b"
    task_fill: str = "#ffffff"
    lane_fill: str = "#fbfbfc"
    accent: str = "#1f6feb"
    background: str = "#ffffff"


def render_svg(model: ProcessModel, layout: Layout, options: SvgRenderOptions | None = None) -> str:
    """Render the diagram as a self-contained SVG document."""
    options = options or SvgRenderOptions()
    extent = layout.extent
    width = extent.width + 2 * _MARGIN
    height = extent.height + 2 * _MARGIN
    offset_x = _MARGIN - extent.x
    offset_y = _MARGIN - extent.y

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(width)}" height="{_n(height)}" '
        f'viewBox="0 0 {_n(width)} {_n(height)}" font-family="{options.font_family}" '
        f'font-size="{_n(options.font_size)}">',
        _defs(options),
        f'<rect width="100%" height="100%" fill="{options.background}"/>',
        f'<g transform="translate({_n(offset_x)},{_n(offset_y)})">',
    ]

    parts.extend(_pool(model, layout, options))
    parts.extend(_edges(model, layout, options))
    parts.extend(_nodes(model, layout, options))

    parts.append("</g></svg>")
    return "\n".join(part for part in parts if part) + "\n"


def _defs(options: SvgRenderOptions) -> str:
    return (
        "<defs>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
        'markerHeight="8" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{options.stroke}"/>'
        "</marker>"
        "</defs>"
    )


def _pool(model: ProcessModel, layout: Layout, options: SvgRenderOptions) -> list[str]:
    if layout.pool is None:
        return []
    parts = [
        f'<rect x="{_n(layout.pool.x)}" y="{_n(layout.pool.y)}" width="{_n(layout.pool.width)}" '
        f'height="{_n(layout.pool.height)}" fill="none" stroke="{options.stroke}" stroke-width="1.6"/>'
    ]
    for lane in model.lanes:
        bounds = layout.lanes.get(lane.id)
        if bounds is None:
            continue
        parts.append(
            f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" width="{_n(bounds.width)}" '
            f'height="{_n(bounds.height)}" fill="{options.lane_fill}" stroke="{options.stroke}" '
            'stroke-width="1"/>'
        )
        header_x = layout.pool.x + (bounds.x - layout.pool.x) / 2
        parts.append(
            f'<text x="{_n(header_x)}" y="{_n(bounds.center_y)}" text-anchor="middle" '
            f'transform="rotate(-90 {_n(header_x)} {_n(bounds.center_y)})" '
            f'fill="{options.stroke}">{escape(lane.name)}</text>'
        )
    return parts


def _edges(model: ProcessModel, layout: Layout, options: SvgRenderOptions) -> list[str]:
    parts: list[str] = []
    for flow in model.flows:
        points = layout.waypoints.get(flow.id)
        if not points:
            continue
        path = " ".join(f"{_n(point.x)},{_n(point.y)}" for point in points)
        dash = ' stroke-dasharray="6 4"' if flow.is_default else ""
        parts.append(
            f'<polyline points="{path}" fill="none" stroke="{options.stroke}" stroke-width="1.4" '
            f'marker-end="url(#arrow)"{dash}/>'
        )
        label = layout.edge_labels.get(flow.id)
        if label is not None and flow.name:
            parts.append(
                f'<text x="{_n(label.center_x)}" y="{_n(label.bottom - 2)}" text-anchor="middle" '
                f'fill="{options.accent}">{escape(flow.name)}</text>'
            )
    return parts


def _nodes(model: ProcessModel, layout: Layout, options: SvgRenderOptions) -> list[str]:
    parts: list[str] = []
    for node in model.nodes:
        bounds = layout.shapes.get(node.id)
        if bounds is None:
            continue
        if node.kind.is_event:
            width = 3.4 if node.kind.is_end else 1.6
            parts.append(
                f'<circle cx="{_n(bounds.center_x)}" cy="{_n(bounds.center_y)}" '
                f'r="{_n(bounds.width / 2)}" fill="{options.task_fill}" stroke="{options.stroke}" '
                f'stroke-width="{width}"/>'
            )
            if node.kind is NodeKind.INTERMEDIATE_CATCH_EVENT:
                parts.append(
                    f'<circle cx="{_n(bounds.center_x)}" cy="{_n(bounds.center_y)}" '
                    f'r="{_n(bounds.width / 2 - 3)}" fill="none" stroke="{options.stroke}"/>'
                )
            parts.append(_event_glyph(node.event_definition, bounds, options))
            parts.extend(_text_below(node.name, bounds, options))
        elif node.kind.is_gateway:
            cx, cy, half = bounds.center_x, bounds.center_y, bounds.width / 2
            parts.append(
                f'<polygon points="{_n(cx)},{_n(cy - half)} {_n(cx + half)},{_n(cy)} '
                f'{_n(cx)},{_n(cy + half)} {_n(cx - half)},{_n(cy)}" fill="{options.task_fill}" '
                f'stroke="{options.stroke}" stroke-width="1.4"/>'
            )
            parts.append(_gateway_glyph(node.kind, bounds, options))
            if node.name:
                parts.extend(_text_above(node.name, bounds, options))
        else:
            parts.append(
                f'<rect x="{_n(bounds.x)}" y="{_n(bounds.y)}" width="{_n(bounds.width)}" '
                f'height="{_n(bounds.height)}" rx="8" fill="{options.task_fill}" '
                f'stroke="{options.stroke}" stroke-width="1.4"/>'
            )
            parts.append(_task_glyph(node.kind, bounds, options))
            parts.extend(_text_inside(node.name, bounds, options))
    return parts


# --------------------------------------------------------------------------- #
# Glyphs
# --------------------------------------------------------------------------- #

_TASK_GLYPHS = {
    NodeKind.USER_TASK: "\U0001f464",
    NodeKind.SERVICE_TASK: "⚙",
    NodeKind.SEND_TASK: "✉",
    NodeKind.RECEIVE_TASK: "✉",
    NodeKind.MANUAL_TASK: "✋",
    NodeKind.SCRIPT_TASK: "≡",
    NodeKind.BUSINESS_RULE_TASK: "☷",
    NodeKind.SUB_PROCESS: "⊞",
    NodeKind.CALL_ACTIVITY: "⊞",
}
_EVENT_GLYPHS = {
    EventDefinition.MESSAGE: "✉",
    EventDefinition.TIMER: "⏱",
    EventDefinition.SIGNAL: "△",
    EventDefinition.ERROR: "⚡",
    EventDefinition.ESCALATION: "⬆",
    EventDefinition.TERMINATE: "●",
    EventDefinition.CONDITIONAL: "≣",
}
_GATEWAY_GLYPHS = {
    NodeKind.EXCLUSIVE_GATEWAY: "✕",
    NodeKind.PARALLEL_GATEWAY: "＋",
    NodeKind.INCLUSIVE_GATEWAY: "○",
    NodeKind.EVENT_BASED_GATEWAY: "◎",
}


def _task_glyph(kind: NodeKind, bounds: Bounds, options: SvgRenderOptions) -> str:
    glyph = _TASK_GLYPHS.get(kind, "")
    if not glyph:
        return ""
    return (
        f'<text x="{_n(bounds.x + 8)}" y="{_n(bounds.y + 16)}" fill="{options.stroke}" '
        f'font-size="{_n(options.font_size)}">{escape(glyph)}</text>'
    )


def _event_glyph(definition: EventDefinition, bounds: Bounds, options: SvgRenderOptions) -> str:
    glyph = _EVENT_GLYPHS.get(definition, "")
    if not glyph:
        return ""
    return (
        f'<text x="{_n(bounds.center_x)}" y="{_n(bounds.center_y + 4)}" text-anchor="middle" '
        f'fill="{options.stroke}" font-size="{_n(options.font_size)}">{escape(glyph)}</text>'
    )


def _gateway_glyph(kind: NodeKind, bounds: Bounds, options: SvgRenderOptions) -> str:
    glyph = _GATEWAY_GLYPHS.get(kind, "")
    if not glyph:
        return ""
    return (
        f'<text x="{_n(bounds.center_x)}" y="{_n(bounds.center_y + 5)}" text-anchor="middle" '
        f'fill="{options.stroke}" font-size="{_n(options.font_size + 3)}">{escape(glyph)}</text>'
    )


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:4]


def _text_block(
    text: str, x: float, y: float, options: SvgRenderOptions, max_chars: int
) -> list[str]:
    lines = _wrap(text, max_chars)
    step = options.font_size + 2
    top = y - (len(lines) - 1) * step / 2
    return [
        f'<text x="{_n(x)}" y="{_n(top + index * step)}" text-anchor="middle" '
        f'fill="{options.stroke}">{escape(line)}</text>'
        for index, line in enumerate(lines)
    ]


def _text_inside(text: str, bounds: Bounds, options: SvgRenderOptions) -> list[str]:
    if not text:
        return []
    return _text_block(text, bounds.center_x, bounds.center_y + 4, options, 16)


def _text_below(text: str, bounds: Bounds, options: SvgRenderOptions) -> list[str]:
    if not text:
        return []
    return _text_block(text, bounds.center_x, bounds.bottom + 14, options, 20)


def _text_above(text: str, bounds: Bounds, options: SvgRenderOptions) -> list[str]:
    if not text:
        return []
    return _text_block(text, bounds.center_x, bounds.y - 8, options, 24)


def _n(value: float) -> str:
    rounded = round(float(value), 2)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)
