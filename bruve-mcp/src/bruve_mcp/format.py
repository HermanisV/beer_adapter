"""Compact, token-cheap text output. Header once, pipe-separated rows, no JSON keys or HTML."""

from __future__ import annotations

import math
import sqlite3
from typing import Any

UNTRUSTED_TAG = "untrusted_bruve_text"
EXCERPT_CHARS = 500
NAME_CHARS = 64
MAX_PACK_COLUMNS = 6


def est_tokens(text: str) -> int:
    """Conservative token estimate (Latvian and numbers tokenize poorly)."""
    return math.ceil(len(text) / 3.2)


def untrusted(text: str | None) -> str:
    """Fence merchant-written text so the model treats it as data, not instructions."""
    if not text:
        return ""
    cleaned = text.replace(f"</{UNTRUSTED_TAG}>", "").replace(f"<{UNTRUSTED_TAG}>", "")
    return f"<{UNTRUSTED_TAG}>{cleaned}</{UNTRUSTED_TAG}>"


def excerpt(text: str | None, limit: int = EXCERPT_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def eur(cents: int | None) -> str:
    return "?" if cents is None else f"{cents / 100:.2f}"


def num(value: float | None) -> str:
    return "?" if value is None else f"{value:g}"


def rng(low: float | None, high: float | None) -> str:
    if low is None:
        return "?"
    return num(low) if high is None or high == low else f"{num(low)}-{num(high)}"


def short_name(name: str) -> str:
    return name if len(name) <= NAME_CHARS else name[: NAME_CHARS - 1].rstrip() + "…"


def stock_text(row: sqlite3.Row | dict[str, Any]) -> str:
    if not row["in_stock"]:
        return "N"
    qty = row["stock_qty"]
    if qty is None:
        return "Y"
    unit = "kg" if row["sold_by"] == "kg" else "pk"
    return f"{qty:g}{unit}"


def price_text(row: sqlite3.Row | dict[str, Any], packs: list[sqlite3.Row] | None = None) -> str:
    if row["sold_by"] == "kg":
        return f"{eur(row['price_cents'])}/kg"
    if packs:
        sized = [p for p in packs if p["size"] and p["in_stock"]]
        if sized:
            best: dict[tuple[float, str], int | None] = {}
            for p in sized:
                key = (p["size"], p["unit"])
                if key not in best or (p["price_cents"] or 0) < (best[key] or 10**9):
                    best[key] = p["price_cents"]
            shown = sorted(best.items())[:MAX_PACK_COLUMNS]
            return " ".join(f"{pack_name(size, unit)}:{eur(price)}" for (size, unit), price in shown)
    low, high = row["price_cents"], row["price_max_cents"]
    if high and low is not None and high != low:
        return f"{eur(low)}-{eur(high)}"
    return eur(low)


def pack_name(size: float, unit: str) -> str:
    if unit == "g" and size >= 1000:
        return f"{size / 1000:g}kg"
    if unit == "ml" and size >= 1000:
        return f"{size / 1000:g}L"
    return f"{size:g}{unit}"


def spec_text(row: sqlite3.Row | dict[str, Any]) -> str:
    kind = row["kind"]
    parts: list[str] = []
    if kind in {"malt", "extract", "adjunct_grain"}:
        if row["ebc_min"] is not None:
            parts.append(f"EBC{rng(row['ebc_min'], row['ebc_max'])}")
        elif kind == "malt":
            parts.append("EBC?")
        if row["role"]:
            parts.append(row["role"])
        if kind != "malt" and row["pack_label"]:
            parts.append(row["pack_label"])
    elif kind == "hop":
        if row["alpha"] is not None:
            parts.append(f"AA{rng(row['alpha_min'], row['alpha_max'])}" + (f"({row['alpha']:g})" if row["alpha_min"] != row["alpha_max"] else ""))
        else:
            parts.append("AA?")
        parts.extend(p for p in (row["hop_form"], row["origin"]) if p)
        if row["years"]:
            parts.append(f"y{row['years'].replace(',', '/')}")
    elif kind == "yeast":
        parts.extend(p for p in (row["lab"], row["code"], row["yeast_form"]) if p)
        if row["role"]:
            parts.append(row["role"].replace(",", "/"))
        if row["floc"]:
            parts.append(f"floc:{row['floc']}")
        if row["temp_min"] is not None:
            parts.append(f"{rng(row['temp_min'], row['temp_max'])}C")
        if row["att_min"] is not None:
            parts.append(f"att{rng(row['att_min'], row['att_max'])}%")
        if row["abv_tol"] is not None:
            parts.append(f"abv<={num(row['abv_tol'])}")
        if row["pack_label"]:
            parts.append(row["pack_label"])
    else:
        if row["pack_label"]:
            parts.append(row["pack_label"])
    return " ".join(parts)


ROW_HEADER = "id|name|kind|spec|EUR|stock"


def row_line(row: sqlite3.Row, packs: list[sqlite3.Row] | None = None) -> str:
    return "|".join(
        [
            str(row["id"]),
            short_name(row["name"]),
            row["kind"],
            spec_text(row),
            price_text(row, packs),
            stock_text(row),
        ]
    )


def table(rows: list[sqlite3.Row], packs: dict[int, list[sqlite3.Row]] | None = None) -> str:
    lines = [ROW_HEADER]
    lines.extend(row_line(r, (packs or {}).get(r["id"])) for r in rows)
    return "\n".join(lines)


def detail_block(row: sqlite3.Row, packs: list[sqlite3.Row], *, full: bool) -> str:
    lines = [row_line(row, packs)]
    if packs:
        variants = []
        for p in packs:
            label = pack_name(p["size"], p["unit"]) if p["size"] else (p["label"] or "?")
            year = f" y{p['year']}" if p["year"] else ""
            qty = "" if p["stock_qty"] is None else f" {p['stock_qty']:g}pk"
            flag = "" if p["in_stock"] else " OOS"
            variants.append(f"{label}{year} {eur(p['price_cents'])}{qty}{flag} v{p['variation_id']}")
        lines.append("packs: " + " | ".join(variants))
    if full:
        lines.append(f"url: {row['url']}")
        if row["colour_src"]:
            lines.append(f"colour_src: {row['colour_src']}")
        if row["alpha_src"]:
            lines.append(f"alpha_src: {row['alpha_src']}")
        if row["attr_alpha"]:
            lines.append(f"unverified shop attribute alpha={row['attr_alpha']} (ignore unless AA is known)")
        if row["form_src"] == "inferred":
            lines.append("yeast form inferred, not stated by shop")
        description = excerpt(row["desc"])
        if description:
            lines.append("desc: " + untrusted(description))
    return "\n".join(lines)
