"""Layout facade: model in, complete diagram geometry out."""

from __future__ import annotations

from dataclasses import dataclass, field

from bpmn_architect.domain.model import ProcessModel
from bpmn_architect.layout.geometry import Bounds, LayoutMetrics, Point
from bpmn_architect.layout.ordering import order_nodes
from bpmn_architect.layout.positioning import Positions, assign_positions
from bpmn_architect.layout.ranking import assign_layers
from bpmn_architect.layout.routing import route_edges

__all__ = ["Layout", "LayoutEngine", "layout_process"]


@dataclass(slots=True)
class Layout:
    """Everything the renderers need in order to draw the diagram."""

    shapes: dict[str, Bounds] = field(default_factory=dict)
    waypoints: dict[str, list[Point]] = field(default_factory=dict)
    node_labels: dict[str, Bounds] = field(default_factory=dict)
    edge_labels: dict[str, Bounds] = field(default_factory=dict)
    lanes: dict[str, Bounds] = field(default_factory=dict)
    pool: Bounds | None = None
    metrics: LayoutMetrics = field(default_factory=LayoutMetrics)

    @property
    def extent(self) -> Bounds:
        """Bounding box of the whole diagram, labels and waypoints included."""
        boxes = [*self.shapes.values(), *self.lanes.values(), *self.node_labels.values()]
        if self.pool is not None:
            boxes.append(self.pool)
        points = [point for path in self.waypoints.values() for point in path]
        if not boxes and not points:
            return Bounds(0, 0, 0, 0)
        left = min([box.x for box in boxes] + [point.x for point in points])
        top = min([box.y for box in boxes] + [point.y for point in points])
        right = max([box.right for box in boxes] + [point.x for point in points])
        bottom = max([box.bottom for box in boxes] + [point.y for point in points])
        return Bounds(left, top, right - left, bottom - top)


class LayoutEngine:
    """Layered ("Sugiyama") layout tuned for BPMN diagrams.

    The four stages are deliberately separate modules: layering decides *when*
    things happen, ordering decides *who sits next to whom*, positioning turns
    that into coordinates, and routing draws the connections.  Each stage can be
    tested — and replaced — on its own.
    """

    def __init__(self, metrics: LayoutMetrics | None = None) -> None:
        self.metrics = metrics or LayoutMetrics()

    def run(self, model: ProcessModel) -> Layout:
        metrics = self.metrics
        if not model.nodes:
            return Layout(metrics=metrics)

        lane_ids = [lane.id for lane in model.lanes]
        lane_index: dict[str | None, int] = {lane_id: i for i, lane_id in enumerate(lane_ids)}
        lane_index[None] = 0
        lane_index[""] = 0

        graph = assign_layers(model)
        ordering = order_nodes(graph, lane_index)
        positions = assign_positions(
            graph, ordering, metrics=metrics, lane_order=lane_ids or [""]
        )
        routes = route_edges(model, graph, positions, metrics)

        layout = Layout(
            shapes={node_id: bounds.rounded() for node_id, bounds in positions.bounds.items()},
            waypoints=routes.waypoints,
            node_labels=routes.node_labels,
            edge_labels=routes.edge_labels,
            metrics=metrics,
        )
        self._apply_pool(model, layout, positions, metrics)
        return layout

    def _apply_pool(
        self,
        model: ProcessModel,
        layout: Layout,
        positions: Positions,
        metrics: LayoutMetrics,
    ) -> None:
        if not model.has_lanes:
            return
        right = max(
            (bounds.right for bounds in layout.shapes.values()),
            default=metrics.pool_origin_x,
        )
        width = right - metrics.pool_origin_x + metrics.lane_padding
        bands = [positions.lane_bands[lane.id] for lane in model.lanes]
        top = min(band.y for band in bands)
        bottom = max(band.bottom for band in bands)
        layout.pool = Bounds(
            metrics.pool_origin_x, top, width, bottom - top
        ).rounded()
        for lane in model.lanes:
            band = positions.lane_bands[lane.id]
            layout.lanes[lane.id] = Bounds(
                x=metrics.pool_origin_x + metrics.lane_header_width,
                y=band.y,
                width=width - metrics.lane_header_width,
                height=band.height,
            ).rounded()


def layout_process(model: ProcessModel, metrics: LayoutMetrics | None = None) -> Layout:
    """Convenience wrapper around :class:`LayoutEngine`."""
    return LayoutEngine(metrics).run(model)
