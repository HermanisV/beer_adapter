"""Input validation for tool arguments."""

import math
import re
from collections.abc import Iterable

KINDS = (
    "malt",
    "extract",
    "adjunct_grain",
    "hop",
    "yeast",
    "nutrient",
    "fining",
    "acid",
    "enzyme",
    "sugar",
    "water_treatment",
    "additive",
    "kit",
)
SORTS = ("relevance", "price", "name", "ebc", "alpha")
YEAST_USES = ("beer", "wine", "other")

MAX_IDS = 25
MAX_QUERIES = 25
MAX_QUERY_LEN = 80
MAX_LIMIT = 25
_ID = re.compile(r"^\d{1,12}$")


def clean_ids(values: Iterable[int | str], *, max_items: int = MAX_IDS) -> list[int]:
    items = list(values)
    if not items:
        raise ValueError("Provide at least one id.")
    if len(items) > max_items:
        raise ValueError(f"At most {max_items} ids per call.")
    out: list[int] = []
    for value in items:
        text = str(value).strip()
        if not _ID.fullmatch(text):
            raise ValueError(f"Invalid id {text[:20]!r}: ids are positive integers.")
        number = int(text)
        if number not in out:
            out.append(number)
    return out


def clean_query(text: str) -> str:
    cleaned = " ".join(str(text).split())
    if not cleaned:
        raise ValueError("Query must not be empty.")
    return cleaned[:MAX_QUERY_LEN]


def clean_queries(values: Iterable[str]) -> list[str]:
    items = list(values)
    if not items:
        raise ValueError("Provide at least one query.")
    if len(items) > MAX_QUERIES:
        raise ValueError(f"At most {MAX_QUERIES} queries per call.")
    return [clean_query(v) for v in items]


def clean_choice(value: str | None, allowed: tuple[str, ...], name: str) -> str | None:
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower()
    if lowered not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}.")
    return lowered


def clean_number(value: float | None, name: str, *, minimum: float = 0.0, maximum: float = 1e6) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ValueError(f"{name} must be a finite number between {minimum} and {maximum}.")
    return float(value)


def clean_limit(value: int | None, default: int = 10) -> int:
    if value is None:
        return default
    if value < 1:
        raise ValueError("limit must be at least 1.")
    return min(int(value), MAX_LIMIT)


def clean_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    text = str(cursor).strip()
    if not re.fullmatch(r"o\d{1,6}", text):
        raise ValueError("Invalid cursor; use the cursor returned by the previous call.")
    return int(text[1:])
