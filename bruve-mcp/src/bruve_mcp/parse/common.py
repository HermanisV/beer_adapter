"""Shared parsing helpers: text cleaning, number/pack parsing, search folding, kind detection."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
NUM = r"\d+(?:[.,]\d+)?"
DASH = r"[-–—]"


def clean_text(value: str | None) -> str:
    """Decode entities, strip tags and collapse whitespace."""
    if not value:
        return ""
    return _SPACES.sub(" ", html.unescape(_TAGS.sub(" ", html.unescape(value)))).strip()


def to_float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def stock_quantity(add_to_cart: dict[str, Any] | None) -> float | None:
    """WooCommerce exposes managed stock as add_to_cart.maximum; 9999 means unmanaged."""
    if not add_to_cart:
        return None
    try:
        qty = float(add_to_cart.get("maximum"))
    except (TypeError, ValueError):
        return None
    return None if qty >= 9999 else qty


def parse_variation_label(label: str | None) -> dict[str, str]:
    """'Iepakojums: 5kg, Gads: 2026' -> {'Iepakojums': '5kg', 'Gads': '2026'}"""
    out: dict[str, str] = {}
    for part in (label or "").split(","):
        key, sep, value = part.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "ae", "Ö": "oe", "Ü": "ue", "ß": "ss"})
_MARKS = str.maketrans("", "", "™®©")


def fold(text: str) -> str:
    """Lowercase, transliterate umlauts, strip diacritics (ā -> a) and collapse German ae/oe/ue.

    Trademark signs are dropped first: NFKD would otherwise turn '™' into the letters 'TM' and index
    'WildBrew™' as 'wildbrewtm'. Applied identically to indexed text and queries so 'Mittelfrüh',
    'Mittelfrueh' and 'Mittelfruh' all match, and Latvian diacritics are optional.
    """
    text = text.translate(_MARKS).translate(_UMLAUTS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"(?<=[a-z])(?:ae|oe|ue)(?=[a-z]|\b)", lambda m: m.group(0)[0], text)


_PACK = re.compile(rf"(?<![\w.,])({NUM})\s*(kg|g|ml|l|gab)\b", re.IGNORECASE)


def parse_pack(text: str) -> tuple[float, str] | None:
    """First 'quantity unit' in text, normalized to g, ml or pcs. '1,5 kg' -> (1500, 'g')."""
    match = _PACK.search(text)
    if not match:
        return None
    value = to_float(match.group(1))
    unit = match.group(2).lower()
    if value is None:
        return None
    if unit == "kg":
        return value * 1000, "g"
    if unit == "l":
        return value * 1000, "ml"
    if unit == "gab":
        return value, "pcs"
    return value, unit


def pack_label(size: float | None, unit: str | None) -> str | None:
    if size is None or not unit:
        return None
    if unit == "g" and size >= 1000:
        return f"{size / 1000:g}kg"
    if unit == "ml" and size >= 1000:
        return f"{size / 1000:g}L"
    return f"{size:g}{unit}"


# First match wins, so more specific kinds come before generic ones.
KIND_BY_SLUG: tuple[tuple[str, frozenset[str]], ...] = (
    ("kit", frozenset({"alus-bruvesanas-komplekti"})),
    ("hop", frozenset({"apini"})),
    ("extract", frozenset({"iesala-ekstrakts-iesals", "skidrie-iesala-ekstrakti", "sausie-iesala-ekstrakti"})),
    ("adjunct_grain", frozenset({"parslas-un-citi-graudi"})),
    ("nutrient", frozenset({"raugu-baribas-vielas"})),
    ("fining", frozenset({"dzidrinasana"})),
    ("acid", frozenset({"skabes"})),
    ("enzyme", frozenset({"enzimi-un-bakterijas"})),
    ("sugar", frozenset({"cukuri"})),
    ("water_treatment", frozenset({"udens-pielagosana"})),
    ("yeast", frozenset({"alus-raugi", "vina-raugi", "citi-raugi", "raugi"})),
    (
        "malt",
        frozenset(
            {
                "iesali",
                "bazes-iesals",
                "karamelizets-iesals",
                "grauzdets-iesals",
                "kviesu-iesals",
                "rudzu-iesals",
                "specialie-iesali",
                "alus-iesals",
            }
        ),
    ),
    ("additive", frozenset({"citas-piedevas", "esences", "koka-cipsi", "piedevas", "citi", "cits"})),
)

MALT_ROLE_BY_SLUG = {
    "bazes-iesals": "base",
    "karamelizets-iesals": "caramel",
    "grauzdets-iesals": "roasted",
    "kviesu-iesals": "wheat",
    "rudzu-iesals": "rye",
    "specialie-iesali": "specialty",
}

_FLAKES = re.compile(r"pārsl|parsl|sēnal|senal", re.IGNORECASE)


def kind_for(slugs: set[str], title: str = "") -> str:
    for kind, group in KIND_BY_SLUG:
        if slugs & group:
            if kind == "malt" and _FLAKES.search(title):
                return "adjunct_grain"
            return kind
    return "additive"
