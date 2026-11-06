"""Malt and malt-extract colour parsing. The shop's `Ebc` attribute is unreliable and ignored."""

from __future__ import annotations

import re

from .common import DASH, NUM, to_float

SRM_PER_EBC = 0.508

_TITLE_RANGE = re.compile(rf"({NUM})\s*(?:{DASH}\s*({NUM})\s*)?EBC", re.IGNORECASE)
_TITLE_PREFIX = re.compile(rf"EBC\s*:?\s*({NUM})(?:\s*{DASH}\s*({NUM}))?", re.IGNORECASE)
_DESC_LABELLED = re.compile(rf"EBC\s*:\s*({NUM})(?:\s*{DASH}\s*({NUM}))?", re.IGNORECASE)
_DESC_PREFIXED = re.compile(rf"(?<![\w.,])({NUM})\s*(?:{DASH}\s*({NUM})\s*)?EBC", re.IGNORECASE)


def _ordered(a: str, b: str | None) -> tuple[float, float] | None:
    low = to_float(a)
    high = to_float(b) if b else low
    if low is None or high is None:
        return None
    low, high = min(low, high), max(low, high)
    # Colour above 2500 EBC is not a malt colour, so it is a different number.
    return (low, high) if 0 < high <= 2500 else None


def parse_colour(title: str, description: str) -> tuple[float, float, str] | None:
    """Return (ebc_min, ebc_max, source) from the title, falling back to the description."""
    for pattern, text, source in (
        (_TITLE_RANGE, title, "title"),
        (_TITLE_PREFIX, title, "title"),
        (_DESC_LABELLED, description, "desc"),
        (_DESC_PREFIXED, description, "desc"),
    ):
        match = pattern.search(text)
        if match:
            parsed = _ordered(match.group(1), match.group(2))
            if parsed:
                return parsed[0], parsed[1], source
    return None


def ebc_to_srm(ebc: float | None) -> float | None:
    return None if ebc is None else round(ebc * SRM_PER_EBC, 1)
