"""Parsing layer: text in, :class:`~bpmn_architect.domain.ir.IRProcess` out."""

from __future__ import annotations

from bpmn_architect.domain.ir import IRProcess
from bpmn_architect.errors import ParseError
from bpmn_architect.parsing.dsl import DslParser, looks_like_dsl, parse_dsl
from bpmn_architect.parsing.nlp import NaturalLanguageParser, ParserOptions, parse_text

__all__ = [
    "DslParser",
    "NaturalLanguageParser",
    "ParseError",
    "ParserOptions",
    "looks_like_dsl",
    "parse",
    "parse_dsl",
    "parse_text",
]


def parse(
    raw_text: str,
    *,
    syntax: str = "auto",
    options: ParserOptions | None = None,
) -> IRProcess:
    """Parse ``raw_text`` with the requested front end.

    ``syntax`` is one of ``"auto"`` (detect), ``"text"`` (natural language) or
    ``"dsl"`` (block DSL).

    The two front ends differ in how they fail, and ``"auto"`` is built around
    that: the DSL parser raises on anything it does not understand, while the
    natural-language parser always produces *something*.  So when detection
    picks the DSL and the DSL then rejects the document, detection — not the
    document — was wrong, and the prose parser takes over.  An explicit
    ``syntax="dsl"`` keeps the error, because there the user asked for the
    strict front end.
    """
    normalized = syntax.casefold()
    if normalized not in {"auto", "text", "nl", "dsl"}:
        raise ValueError(f"unknown syntax {syntax!r}; expected 'auto', 'text' or 'dsl'")
    if normalized == "dsl":
        return parse_dsl(raw_text)
    if normalized == "auto" and looks_like_dsl(raw_text):
        try:
            return parse_dsl(raw_text)
        except ParseError:
            pass
    return parse_text(raw_text, options)
