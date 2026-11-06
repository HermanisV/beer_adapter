"""Hop parsing. Alpha acid comes from the description; the shop's `Alfa Skābe` attribute is unreliable."""

from __future__ import annotations

import re

from .common import DASH, NUM, to_float

_ALPHA = re.compile(
    rf"(?:alfa\s+sk[āa]b\w*|alpha(?:\s+acids?)?|\balfa)\s*:?\s*(?:aptuveni\s*)?"
    rf"({NUM})\s*%?\s*(?:{DASH}\s*({NUM})\s*%?)?(?:\s*\(\s*({NUM})\s*%?\s*\))?",
    re.IGNORECASE,
)
_FORM = re.compile(r"\bT[-\s]?(90|45)\b", re.IGNORECASE)
_ORIGIN = re.compile(r"\bT[-\s]?(?:90|45)\s+([A-Z]{2,3})\b")
_YEAR = re.compile(r"\b(20[12]\d)\b")
ORIGIN_NORMALIZE = {"GER": "DE", "SLO": "SI", "SLV": "SI", "AU": "AUS", "US": "USA", "GB": "UK", "CZE": "CZ"}


def parse_alpha(description: str) -> tuple[float, float, float, str] | None:
    """Return (alpha_min, alpha_max, alpha, source). `alpha` is the quoted typical value, else the midpoint."""
    for match in _ALPHA.finditer(description):
        low = to_float(match.group(1))
        high = to_float(match.group(2)) if match.group(2) else low
        typical = to_float(match.group(3)) if match.group(3) else None
        if low is None or high is None or not (0.5 <= low <= 30) or not (0.5 <= high <= 30):
            continue
        low, high = min(low, high), max(low, high)
        if typical is not None and 0.5 <= typical <= 30:
            low, high = min(low, typical), max(high, typical)
            return low, high, typical, "desc"
        return low, high, round((low + high) / 2, 2), "desc"
    return None


def parse_hop_title(title: str) -> dict[str, object]:
    form = _FORM.search(title)
    origin = _ORIGIN.search(title)
    year = _YEAR.search(title)
    code = origin.group(1) if origin else None
    return {
        "hop_form": f"T{form.group(1)}" if form else None,
        "origin": ORIGIN_NORMALIZE.get(code, code) if code else None,
        "title_year": int(year.group(1)) if year else None,
    }
