from itertools import combinations
from pathlib import Path

from bpmn_architect.layout import LayoutMetrics, layout_process
from bpmn_architect.layout.ordering import _count_crossings
from bpmn_architect.layout.positioning import place_with_separation
from bpmn_architect.layout.ranking import assign_layers
from bpmn_architect.pipeline import generate
from conftest import on_border, overlaps

TOLERANCE = 1.5


class TestSeparationSolver:
    def test_spreads_boxes_that_want_the_same_place(self):
        centers = place_with_separation([100, 100, 100], [80, 80, 80], 40, 0, 1000)
        gaps = [b - a for a, b in zip(centers, centers[1:], strict=False)]
        assert all(gap >= 120 - 1e-9 for gap in gaps)

    def test_leaves_satisfied_positions_untouched(self):
        desired = [100, 300, 500]
        assert place_with_separation(desired, [80, 80, 80], 40, 0, 1000) == desired

    def test_respects_the_lower_bound(self):
        centers = place_with_separation([0, 0], [36, 36], 20, 100, 1000)
        assert centers[0] - 18 >= 100 - 1e-9

    def test_handles_an_empty_column(self):
        assert place_with_separation([], [], 40, 0, 100) == []


class TestLayoutInvariants:
    def test_no_two_elements_overlap(self, example):
        boxes = list(example.layout.shapes.items())
        for (left_id, left), (right_id, right) in combinations(boxes, 2):
            assert not overlaps(left, right), f"{left_id} overlaps {right_id}"

    def test_flow_runs_left_to_right(self, example):
        model, layout = example.model, example.layout
        graph = assign_layers(model)
        for flow in model.flows:
            if flow.id in graph.back_edges:
                continue
            source = layout.shapes[flow.source_id]
            target = layout.shapes[flow.target_id]
            assert source.right <= target.x + TOLERANCE, f"{flow.id} runs backwards"

    def test_every_segment_is_axis_parallel(self, example):
        for flow_id, points in example.layout.waypoints.items():
            for first, second in zip(points, points[1:], strict=False):
                horizontal = abs(first.y - second.y) < TOLERANCE
                vertical = abs(first.x - second.x) < TOLERANCE
                assert horizontal or vertical, f"{flow_id} has a diagonal segment"

    def test_edges_start_and_end_on_element_borders(self, example):
        for flow in example.model.flows:
            points = example.layout.waypoints[flow.id]
            assert len(points) >= 2
            assert on_border(points[0], example.layout.shapes[flow.source_id]), flow.id
            assert on_border(points[-1], example.layout.shapes[flow.target_id]), flow.id

    def test_elements_stay_inside_their_lane(self, example):
        for node in example.model.nodes:
            if node.lane_id is None:
                continue
            band = example.layout.lanes[node.lane_id]
            box = example.layout.shapes[node.id]
            assert band.y - TOLERANCE <= box.y and box.bottom <= band.bottom + TOLERANCE

    def test_lanes_tile_the_pool_without_gaps(self, example):
        if not example.model.has_lanes:
            return
        bands = [example.layout.lanes[lane.id] for lane in example.model.lanes]
        for upper, lower in zip(bands, bands[1:], strict=False):
            assert abs(upper.bottom - lower.y) < TOLERANCE
        assert abs(bands[0].y - example.layout.pool.y) < TOLERANCE
        assert abs(bands[-1].bottom - example.layout.pool.bottom) < TOLERANCE


class TestLayoutQuality:
    def test_the_happy_path_is_a_straight_line(self):
        result = generate(
            "Процесс начинается.\n"
            "Менеджер проверяет заявку.\n"
            "Менеджер оформляет договор.\n"
            "Процесс завершается."
        )
        centers = {node.id: result.layout.shapes[node.id].center_y for node in result.model.nodes}
        assert len({round(value) for value in centers.values()}) == 1

    def test_branches_are_drawn_apart(self):
        result = generate(
            "Если заявка корректна, то менеджер оформляет договор, "
            "иначе менеджер отклоняет заявку."
        )
        names = {node.name: node.id for node in result.model.nodes}
        approve = result.layout.shapes[names["Оформить договор"]]
        reject = result.layout.shapes[names["Отклонить заявку"]]
        assert abs(approve.center_y - reject.center_y) >= 60

    def test_loop_back_edges_avoid_the_elements(self, order_request):
        result = generate(
            "Менеджер проверяет заявку.\n"
            "Если заявка корректна, то менеджер оформляет договор, "
            "иначе заявка возвращается к проверке заявки.\n"
        )
        graph = assign_layers(result.model)
        assert graph.back_edges, "the description contains a rework loop"
        for flow_id in graph.back_edges:
            loop_y = max(point.y for point in result.layout.waypoints[flow_id])
            for box in result.layout.shapes.values():
                assert loop_y >= box.bottom - 1 or loop_y <= box.y + 1

    def test_layout_is_deterministic(self):
        text = Path("examples/support_ticket.ru.txt").read_text(encoding="utf-8")
        first = generate(text).layout
        second = generate(text).layout
        assert first.shapes == second.shapes
        assert first.waypoints == second.waypoints

    def test_metrics_scale_the_diagram(self):
        text = "Процесс начинается.\nМенеджер проверяет заявку.\nПроцесс завершается."
        default = generate(text).layout.extent
        from bpmn_architect.pipeline import PipelineOptions

        options = PipelineOptions(metrics=LayoutMetrics(rank_gap=200))
        wide = generate(text, options).layout.extent
        assert wide.width > default.width


def test_crossing_counter():
    upper, lower = ["a", "b"], ["x", "y"]
    assert _count_crossings(upper, lower, [("a", "x"), ("b", "y")]) == 0
    assert _count_crossings(upper, lower, [("a", "y"), ("b", "x")]) == 1


def test_empty_model_produces_an_empty_layout():
    from bpmn_architect.domain.model import ProcessModel

    layout = layout_process(ProcessModel())
    assert layout.shapes == {}
    assert layout.extent.width == 0
