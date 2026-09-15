"""Mapping elements back to the sentences that produced them."""

from bpmn_architect import generate
from bpmn_architect.sourcemap import build_source_map
from conftest import ORDER_REQUEST, find


class TestSourceMap:
    def test_every_generated_element_is_mapped(self, order_request):
        source_map = build_source_map(order_request.model, ORDER_REQUEST)
        mapped = set(source_map.spans)
        from_text = {
            node.id for node in order_request.model.nodes if node.attrs.get("source")
        }
        assert from_text <= mapped

    def test_spans_point_at_the_real_sentence(self, order_request):
        source_map = build_source_map(order_request.model, ORDER_REQUEST)
        span = source_map.for_element(find(order_request, "Проверить заявку").id)
        assert span is not None and span.exact
        assert ORDER_REQUEST[span.start : span.end] == "Менеджер проверяет заявку."

    def test_reverse_lookup_returns_the_innermost_element_first(self, order_request):
        source_map = build_source_map(order_request.model, ORDER_REQUEST)
        offset = ORDER_REQUEST.index("бухгалтер выставляет")
        hits = source_map.at_offset(offset)
        assert hits, "the offset is inside a mapped sentence"
        assert hits[0] == find(order_request, "Выставить счёт").id
        assert find(order_request, "Заявка корректна?").id in hits

    def test_lookup_by_line(self, order_request):
        source_map = build_source_map(order_request.model, ORDER_REQUEST)
        line = source_map.for_element(find(order_request, "Проверить заявку").id).line
        assert find(order_request, "Проверить заявку").id in source_map.at_line(line)

    def test_repeated_sentences_get_distinct_spans(self):
        text = (
            "Менеджер проверяет заявку.\n"
            "Менеджер оформляет договор.\n"
            "Менеджер проверяет заявку.\n"
        )
        result = generate(text)
        source_map = build_source_map(result.model, text)
        starts = [
            span.start for span in source_map.spans.values() if "проверяет" in span.sentence
        ]
        assert len(set(starts)) == len(starts), "identical sentences must not share a span"

    def test_serialisation_shape(self, order_request):
        payload = build_source_map(order_request.model, ORDER_REQUEST).to_dict()
        entry = next(iter(payload.values()))
        assert set(entry) == {"elementId", "sentence", "line", "start", "end", "exact"}
