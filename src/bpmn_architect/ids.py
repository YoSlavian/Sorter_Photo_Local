"""Deterministic, XML-safe identifier generation.

BPMN identifiers are XSD ``ID`` values, i.e. NCNames: they may not start with
a digit and may not contain whitespace or colons.  On top of that, identifiers
must be *stable* — regenerating a diagram from the same description has to
produce the same file, otherwise version control turns into noise.

:class:`IdFactory` therefore hands out sequential, category-prefixed ids in the
style used by bpmn.io and Camunda Modeler (``Activity_1``, ``Gateway_2``), and
guarantees that explicitly reserved ids are never handed out twice.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["IdFactory", "sanitize_id", "slugify"]

_INVALID_ID_CHARS = re.compile(r"[^A-Za-z0-9_.\-]")
_MULTI_UNDERSCORE = re.compile(r"_{2,}")

#: Practical transliteration table (GOST 7.79 System B, simplified) so that
#: Cyrillic labels can still produce readable ASCII slugs.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text: str, *, max_length: int = 40) -> str:
    """Turn arbitrary text into an ASCII slug suitable for an identifier."""
    lowered = unicodedata.normalize("NFC", text).strip().lower()
    transliterated = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    ascii_only = (
        unicodedata.normalize("NFKD", transliterated).encode("ascii", "ignore").decode("ascii")
    )
    slug = _INVALID_ID_CHARS.sub("_", ascii_only)
    slug = _MULTI_UNDERSCORE.sub("_", slug).strip("_.-")
    return slug[:max_length].rstrip("_.-")


def sanitize_id(raw: str, *, fallback: str = "Element") -> str:
    """Coerce ``raw`` into a valid NCName, falling back to ``fallback``."""
    candidate = _MULTI_UNDERSCORE.sub("_", _INVALID_ID_CHARS.sub("_", raw.strip())).strip("_")
    if not candidate:
        return fallback
    if not (candidate[0].isalpha() or candidate[0] == "_"):
        candidate = f"_{candidate}"
    return candidate


class IdFactory:
    """Hands out unique, stable identifiers grouped by category prefix."""

    __slots__ = ("_counters", "_used")

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._used: set[str] = set()

    def next(self, prefix: str) -> str:
        """Return the next free id for ``prefix`` (``Activity_1``, ``Activity_2``, ...)."""
        while True:
            self._counters[prefix] = self._counters.get(prefix, 0) + 1
            candidate = f"{prefix}_{self._counters[prefix]}"
            if candidate not in self._used:
                self._used.add(candidate)
                return candidate

    def reserve(self, identifier: str) -> str:
        """Register an externally supplied id, de-duplicating if necessary."""
        clean = sanitize_id(identifier)
        if clean not in self._used:
            self._used.add(clean)
            return clean
        suffix = 2
        while f"{clean}_{suffix}" in self._used:
            suffix += 1
        unique = f"{clean}_{suffix}"
        self._used.add(unique)
        return unique

    def is_used(self, identifier: str) -> bool:
        return identifier in self._used
