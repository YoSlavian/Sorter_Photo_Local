"""Mapping between the source text and the elements generated from it.

This is what makes the two-way highlight in Studio possible: click an element,
see the sentence it came from; click a sentence, see the element it produced.

The builder already records the originating sentence on every node
(``attrs["source"]``) and its line number, so the map is reconstructed rather
than threaded through the whole pipeline.  Locating a sentence proceeds in
three steps, each one a fallback for the previous:

1. find the exact sentence, starting from a cursor that advances with the
   document — this keeps repeated sentences apart;
2. find it anywhere in the text, for elements emitted out of reading order;
3. fall back to the recorded line, which is always known.

Step 3 guarantees every element gets a span, so the UI never has a dead link.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bpmn_architect.domain.model import ProcessModel

__all__ = ["SourceSpan", "SourceMap", "build_source_map"]


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """The fragment of the description an element was generated from."""

    element_id: str
    sentence: str
    line: int
    start: int
    end: int
    #: False when only the line could be located, not the exact sentence.
    exact: bool = True

    def contains(self, offset: int) -> bool:
        return self.start <= offset < self.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "elementId": self.element_id,
            "sentence": self.sentence,
            "line": self.line,
            "start": self.start,
            "end": self.end,
            "exact": self.exact,
        }


@dataclass(slots=True)
class SourceMap:
    """Element id -> source span, with reverse lookup by character offset."""

    text: str = ""
    spans: dict[str, SourceSpan] = field(default_factory=dict)

    def for_element(self, element_id: str) -> SourceSpan | None:
        return self.spans.get(element_id)

    def at_offset(self, offset: int) -> list[str]:
        """Element ids whose span covers ``offset``, innermost (shortest) first."""
        hits = [span for span in self.spans.values() if span.contains(offset)]
        hits.sort(key=lambda span: span.end - span.start)
        return [span.element_id for span in hits]

    def at_line(self, line: int) -> list[str]:
        return [span.element_id for span in self.spans.values() if span.line == line]

    def to_dict(self) -> dict[str, Any]:
        return {element_id: span.to_dict() for element_id, span in self.spans.items()}

    def __len__(self) -> int:
        return len(self.spans)


def build_source_map(model: ProcessModel, text: str) -> SourceMap:
    """Locate every element of ``model`` inside ``text``."""
    source_map = SourceMap(text=text)
    line_spans = _line_spans(text)
    cursor = 0

    ordered = sorted(
        (node for node in model.nodes if node.attrs.get("source")),
        key=lambda node: (int(node.attrs.get("line", "0") or 0), node.id),
    )
    for node in ordered:
        sentence = node.attrs["source"].strip()
        line = int(node.attrs.get("line", "0") or 0)
        start, end, exact = _locate(text, sentence, cursor, line, line_spans)
        source_map.spans[node.id] = SourceSpan(
            element_id=node.id,
            sentence=sentence,
            line=line,
            start=start,
            end=end,
            exact=exact,
        )
        if exact:
            cursor = start + 1
    return source_map


def _locate(
    text: str,
    sentence: str,
    cursor: int,
    line: int,
    line_spans: list[tuple[int, int]],
) -> tuple[int, int, bool]:
    for probe in _probes(sentence):
        position = text.find(probe, cursor)
        if position < 0:
            position = text.find(probe)
        if position >= 0:
            return position, position + len(probe), True
    if 1 <= line <= len(line_spans):
        start, end = line_spans[line - 1]
        return start, end, False
    return 0, 0, False


def _probes(sentence: str) -> list[str]:
    """Search strings to try, from the most to the least specific.

    The builder may annotate a sentence (an end event records *how* the process
    ends), so the bracketed suffix is stripped before falling back to a prefix
    long enough to stay unambiguous.
    """
    probes = [sentence]
    if sentence.endswith("]") and "[" in sentence:
        probes.append(sentence[: sentence.rindex("[")].strip())
    head = probes[-1]
    if len(head) > 24:
        probes.append(head[:24])
    return probes


def _line_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        spans.append((offset, offset + len(stripped)))
        offset += len(line)
    return spans
