"""Text pre-processing: typography, line structure and sentence segmentation.

Real process descriptions arrive as a mix of prose, numbered lists, bullet
points and indented sub-steps, pasted from Word or Confluence with non-breaking
spaces and typographic dashes.  Normalising all of that in one place keeps the
parsers free of defensive string handling.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["Line", "normalize_text", "read_lines", "split_sentences", "clean_label"]

_TRANSLATIONS = str.maketrans(
    {
        "\u00a0": " ",  # non-breaking space
        " ": " ",  # narrow no-break space
        " ": " ",  # thin space
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "«": '"',
        "»": '"',
        "−": "-",  # minus sign
        "‐": "-",
        "‑": "-",
        "\t": "    ",
    }
)

_TRAILING_PUNCT = " \t.;,:—–-·*"
_BULLET_RE = re.compile(r"^\s*(?P<bullet>[-*•‣◦·]|–|—)\s+")
_NUMBER_RE = re.compile(r"^\s*(?P<number>\d+(?:\.\d+)*)[.)]\s+")
_COMMENT_RE = re.compile(r"^\s*(?://|#)\s?")

#: Abbreviations after which a period does not end a sentence.
_ABBREVIATIONS = (
    "т.д.", "т.п.", "т.е.", "т.к.", "др.", "пр.", "рис.", "стр.", "руб.", "коп.",
    "г.", "гг.", "мин.", "ч.", "шт.", "им.", "напр.", "см.", "ср.",
    "e.g.", "i.e.", "etc.", "vs.", "fig.", "no.", "approx.", "dept.",
)

#: A sentence boundary is a terminator followed by something that *starts* a
#: sentence.  Requiring an upper-case (or numeric) opener is what lets
#: "и т.д. Затем ..." split correctly while "100.5 руб." does not.
_SENTENCE_END_RE = re.compile(r'(?<=[.!?;])\s+(?=["\u00abA-ZА-ЯЁ0-9])')


def normalize_text(raw: str) -> str:
    """Normalise unicode, whitespace and typography without losing line structure."""
    text = unicodedata.normalize("NFC", raw).translate(_TRANSLATIONS)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse runs of spaces but keep indentation, which is structural.
    return "\n".join(_collapse_inner_spaces(line) for line in text.split("\n"))


def _collapse_inner_spaces(line: str) -> str:
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    return " " * indent + re.sub(r" {2,}", " ", stripped.rstrip())


@dataclass(frozen=True, slots=True)
class Line:
    """One logical input line with its structural decoration removed."""

    number: int
    """1-based physical line number, used in diagnostics."""
    indent: int
    text: str
    bullet: str = ""
    ordinal: str = ""

    @property
    def is_listed(self) -> bool:
        """True when the line was a bullet or a numbered item."""
        return bool(self.bullet or self.ordinal)

    @property
    def depth(self) -> int:
        """Nesting depth derived from indentation (one level per two spaces)."""
        return self.indent // 2


def read_lines(raw: str, *, keep_blank: bool = False) -> list[Line]:
    """Split normalised text into :class:`Line` records.

    Bullets and ordinals are stripped from the text but remembered, because
    ``1.1.`` style ordinals also encode nesting for people who do not indent.
    """
    lines: list[Line] = []
    for index, physical in enumerate(normalize_text(raw).split("\n"), start=1):
        if _COMMENT_RE.match(physical):
            continue
        if not physical.strip():
            if keep_blank:
                lines.append(Line(number=index, indent=0, text=""))
            continue
        stripped = physical.lstrip(" ")
        indent = len(physical) - len(stripped)
        bullet = ""
        ordinal = ""
        if match := _BULLET_RE.match(physical):
            bullet = match.group("bullet")
            stripped = physical[match.end() :]
        elif match := _NUMBER_RE.match(physical):
            ordinal = match.group("number")
            stripped = physical[match.end() :]
            # "2.1." is one level deeper than "2." even without indentation.
            indent = max(indent, (ordinal.count(".")) * 2)
        lines.append(
            Line(number=index, indent=indent, text=stripped.strip(), bullet=bullet, ordinal=ordinal)
        )
    return lines


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences, honouring common abbreviations.

    Only the *internal* dots of an abbreviation are shielded; its final dot is
    still a candidate boundary, because "... и т.д. Затем ..." genuinely ends a
    sentence there.  The upper-case look-ahead in :data:`_SENTENCE_END_RE`
    resolves that ambiguity the way a reader does.
    """
    if not text.strip():
        return []
    protected = text
    for abbreviation in _ABBREVIATIONS:
        if abbreviation.casefold() in protected.casefold():
            shielded = abbreviation[:-1].replace(".", "\x01") + abbreviation[-1]
            protected = re.sub(re.escape(abbreviation), shielded, protected, flags=re.IGNORECASE)
    # Protect decimals: "3.5 дня" must not split.
    protected = re.sub(r"(?<=\d)\.(?=\d)", "\x01", protected)

    parts = (part.strip().replace("\x01", ".") for part in _SENTENCE_END_RE.split(protected))
    return [part for part in parts if part]


def clean_label(text: str) -> str:
    """Trim a fragment into an element label: no trailing punctuation, no quotes."""
    label = re.sub(r"\s+", " ", text).strip()
    previous = None
    while label and label != previous:
        previous = label
        label = label.rstrip(_TRAILING_PUNCT).strip()
        if len(label) > 1 and label[0] == label[-1] == '"':
            label = label[1:-1].strip()
        elif label.startswith('"') and '"' not in label[1:]:
            label = label[1:].strip()
        elif label.endswith('"') and '"' not in label[:-1]:
            label = label[:-1].strip()
    return label
