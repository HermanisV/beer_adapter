"""Yeast parsing: lab and strain code from the title, performance data from Latvian descriptions."""

from __future__ import annotations

import re

from .common import DASH, NUM, parse_pack, to_float

_LABS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), name)
    for pattern, name in (
        (r"fermentis|\bsaf(?:ale|lager|brew|cider)\b", "Fermentis"),
        (r"lalvin", "Lalvin"),
        (r"lallemand|lalbrew|wildbrew", "Lallemand"),
        (r"white\s+labs|\bwlp\s?\d", "White Labs"),
        (r"wyeast|\bwy\d{4}", "Wyeast"),
        (r"mangrove", "Mangrove Jack's"),
        (r"cellarscience", "CellarScience"),
        (r"pinnacle", "Pinnacle"),
        (r"kveik\s+yeastery", "Kveik Yeastery"),
        (r"vinoferm", "Vinoferm"),
        (r"browin", "Browin"),
        (r"imperial\s+organic", "Imperial"),
        (r"omega\s+yeast", "Omega"),
    )
)

_CODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(WLP)\s?-?(\d{3})\b"),
    re.compile(r"\b(WY)\s?-?(\d{4})\b"),
    re.compile(r"\b([A-Z]\d)-([A-Z]\d{3,4})\b"),
    re.compile(r"\b([A-Z]{1,3})-([A-Z]?\d{1,4}(?:/\d{2})?)\b"),
)
_MANGROVE_CODE = re.compile(r"\b(M)(\d{2})\b")
_WINE_CODE = re.compile(r"\b([A-Z]{1,3}\d{1,4})\b")

_LIQUID = re.compile(r"šķidr|liquid|\bvial\b|\btube\b", re.IGNORECASE)
_DRY = re.compile(r"sausais|sauss|\bdry\b", re.IGNORECASE)

_ATTENUATION = re.compile(
    rf"(?:vājinājum\w*|atšķaidīšan\w*|attenuation|norūgšanas\s+pakāp\w*|fermentācijas\s+pakāp\w*)"
    rf"\s*:?\s*(\d{{2,3}})(?:\s*{DASH}\s*(\d{{2,3}}))?\s*%",
    re.IGNORECASE,
)
_ABV_LABELLED = re.compile(
    rf"toleranc\w*\s*:?\s*(?:līdz\s*)?({NUM})(?:\s*{DASH}\s*({NUM}))?\s*%", re.IGNORECASE
)
_ABV_UPTO = re.compile(rf"līdz\s*({NUM})\s*%\s*(?:ABV|alk)", re.IGNORECASE)
_TEMP_RANGE = re.compile(rf"(\d{{1,2}})\s*{DASH}\s*(\d{{1,2}})\s*°\s*C?", re.IGNORECASE)
_TEMP_FROM_TO = re.compile(r"no\s*(\d{1,2})\s*°\s*C?\s*līdz\s*(\d{1,2})\s*°", re.IGNORECASE)
_FLOC_AFTER = re.compile(
    r"flokul\w*\s*:?\s*(ļoti\s+zema|ļoti\s+augsta|zema\s*/\s*vidēja|vidēja\s*/\s*augsta|zema|vidēja|augsta|augstu|liela|lielu"
    r"|very\s+high|very\s+low|low|medium|high)",
    re.IGNORECASE,
)
_FLOC_BEFORE = re.compile(
    r"(ļoti\s+augsta|ļoti\s+zema|augsta|vidēja|zema|liela|lielu|augstu)\s+flokul", re.IGNORECASE
)

_FLOC_NORMAL = {
    "ļoti zema": "very low",
    "very low": "very low",
    "zema": "low",
    "low": "low",
    "zema/vidēja": "low-medium",
    "vidēja": "medium",
    "medium": "medium",
    "vidēja/augsta": "medium-high",
    "augsta": "high",
    "augstu": "high",
    "liela": "high",
    "lielu": "high",
    "high": "high",
    "ļoti augsta": "very high",
    "very high": "very high",
}


def detect_lab(brand: str | None, title: str) -> str | None:
    for text in (title, brand or ""):
        for pattern, name in _LABS:
            if pattern.search(text):
                return name
    return brand or None


def detect_code(title: str, lab: str | None) -> str | None:
    for pattern in _CODE_PATTERNS:
        match = pattern.search(title)
        if match:
            prefix, rest = match.group(1), match.group(2)
            return f"{prefix}{rest}" if prefix in {"WLP", "WY"} else f"{prefix}-{rest}"
    if lab == "Mangrove Jack's":
        match = _MANGROVE_CODE.search(title)
        if match:
            return f"{match.group(1)}{match.group(2)}"
    if lab == "Lalvin":
        match = _WINE_CODE.search(title)
        if match:
            return match.group(1)
    return None


def detect_form(title: str, lab: str | None) -> tuple[str | None, str | None]:
    if _LIQUID.search(title):
        return "liquid", "title"
    if _DRY.search(title):
        return "dry", "title"
    pack = parse_pack(title)
    if pack and pack[1] == "g":
        return "dry", "inferred"
    if lab in {
        "Fermentis",
        "Lalvin",
        "Lallemand",
        "Mangrove Jack's",
        "CellarScience",
        "Kveik Yeastery",
        "Vinoferm",
        "Browin",
        "Pinnacle",
        "White Labs",
    }:
        return "dry", "inferred"
    return None, None


def _normalize_floc(raw: str) -> str | None:
    key = re.sub(r"\s*/\s*", "/", re.sub(r"\s+", " ", raw.strip().lower()))
    return _FLOC_NORMAL.get(key)


def parse_performance(description: str) -> dict[str, object]:
    """Attenuation %, flocculation, fermentation temperature range and alcohol tolerance."""
    out: dict[str, object] = {}

    match = _ATTENUATION.search(description)
    if match:
        low = to_float(match.group(1))
        high = to_float(match.group(2)) if match.group(2) else low
        if low is not None and high is not None and 30 <= min(low, high) and max(low, high) <= 100:
            out["att_min"], out["att_max"] = min(low, high), max(low, high)

    match = _FLOC_AFTER.search(description) or _FLOC_BEFORE.search(description)
    if match:
        floc = _normalize_floc(match.group(1))
        if floc:
            out["floc"] = floc

    for temp_match in _TEMP_RANGE.finditer(description):
        low, high = float(temp_match.group(1)), float(temp_match.group(2))
        context = description[max(0, temp_match.start() - 70) : temp_match.start()].lower()
        if 5 <= low < high <= 45 and ("ferment" in context or "temperat" in context):
            out["temp_min"], out["temp_max"] = low, high
            break
    if "temp_min" not in out:
        match = _TEMP_FROM_TO.search(description)
        if match and 5 <= float(match.group(1)) < float(match.group(2)) <= 45:
            out["temp_min"], out["temp_max"] = float(match.group(1)), float(match.group(2))

    match = _ABV_LABELLED.search(description) or _ABV_UPTO.search(description)
    if match:
        values = [to_float(g) for g in match.groups() if g]
        values = [v for v in values if v is not None and 1 <= v <= 25]
        if values:
            out["abv_tol"] = max(values)
    return out
