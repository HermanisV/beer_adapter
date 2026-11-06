"""Deterministic purchase arithmetic. No substitution logic: the caller decides *what* to buy,
this only works out *how much* of which pack to buy."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from functools import reduce
from typing import Any

from .format import eur, pack_name
from .links import cart_link, product_link

UNITS = ("kg", "g", "pk", "ml", "l")
KG_STEP = 0.1


@dataclass
class BuyItem:
    label: str
    quantity: float
    pack: sqlite3.Row | None = None


@dataclass
class LineResult:
    product_id: int
    name: str
    buy: str
    cost_cents: int | None
    url: str
    note: str = ""
    items: list[BuyItem] = field(default_factory=list)


def _to_base(need: float, unit: str) -> tuple[float, str]:
    if unit == "kg":
        return need * 1000, "g"
    if unit == "l":
        return need * 1000, "ml"
    return need, unit


def cover(need: float, packs: list[dict[str, Any]]) -> tuple[list[tuple[dict[str, Any], int]], int, float] | None:
    """Cheapest combination of packs covering `need` (same unit as pack size). Ties prefer less overshoot.

    Each pack dict needs: size (int), price (int cents), limit (int | None). Returns
    ([(pack, count)], cost, total_size) or None when stock cannot cover the need.
    """
    if need <= 0 or not packs:
        return None
    divisor = reduce(math.gcd, (int(p["size"]) for p in packs))
    target = math.ceil(need / divisor - 1e-9)
    states: dict[int, tuple[int, int, tuple[int, ...]]] = {0: (0, 0, ())}
    for pack in packs:
        units = int(pack["size"]) // divisor
        most = math.ceil(target / units)
        if pack["limit"] is not None:
            most = min(most, int(pack["limit"]))
        merged: dict[int, tuple[int, int, tuple[int, ...]]] = {}
        for covered, (cost, total, counts) in states.items():
            for k in range(most + 1):
                nxt = min(target, covered + k * units)
                candidate = (cost + k * pack["price"], total + k * units, counts + (k,))
                best = merged.get(nxt)
                if best is None or candidate[:2] < best[:2]:
                    merged[nxt] = candidate
        states = merged
    if target not in states:
        return None
    cost, total, counts = states[target]
    chosen = [(p, c) for p, c in zip(packs, counts) if c]
    return chosen, cost, total * divisor


def _label(pack: sqlite3.Row) -> str:
    text = pack_name(pack["size"], pack["unit"]) if pack["size"] else (pack["label"] or "pack")
    return text + (f" y{pack['year']}" if pack["year"] else "")


def _find_pack(packs: list[sqlite3.Row], wanted: str) -> sqlite3.Row | None:
    text = wanted.strip().lower().replace(" ", "")
    digits = text.lstrip("v")
    if digits.isdigit():
        for p in packs:
            if str(p["variation_id"]) == digits and p["in_stock"]:
                return p
    for p in packs:
        if p["size"] and p["in_stock"] and pack_name(p["size"], p["unit"]).lower() == text:
            return p
    return None


def _cheapest_per_size(packs: list[sqlite3.Row], unit: str) -> list[dict[str, Any]]:
    best: dict[int, sqlite3.Row] = {}
    for p in packs:
        if not p["in_stock"] or p["unit"] != unit or not p["size"] or p["price_cents"] is None:
            continue
        size = int(p["size"])
        current = best.get(size)
        if current is None or (p["price_cents"], -(p["year"] or 0)) < (current["price_cents"], -(current["year"] or 0)):
            best[size] = p
    return [
        {
            "size": size,
            "price": p["price_cents"],
            "limit": None if p["stock_qty"] is None else int(p["stock_qty"]),
            "label": _label(p),
            "row": p,
        }
        for size, p in sorted(best.items())
    ]


def _single_pack(packs: list[sqlite3.Row]) -> sqlite3.Row | None:
    """The only in-stock pack, when a variable product has exactly one."""
    available = [p for p in packs if p["in_stock"]]
    return available[0] if len(available) == 1 else None


def plan_line(row: sqlite3.Row, packs: list[sqlite3.Row], need: float, unit: str, pack: str | None) -> LineResult:
    result = LineResult(row["id"], row["name"], "", None, row["url"])
    if unit not in UNITS:
        result.note = f"unit must be one of {', '.join(UNITS)}"
        return result
    if need <= 0 or not math.isfinite(need):
        result.note = "need must be greater than zero"
        return result

    if row["sold_by"] == "kg":
        if unit not in {"kg", "g"}:
            result.note = "sold by weight: give need in kg or g"
            return result
        kilos = need / 1000 if unit == "g" else need
        qty = round(math.ceil(kilos / KG_STEP - 1e-9) * KG_STEP, 1)
        result.buy = f"{qty:.1f}kg"
        result.items.append(BuyItem(f"{qty:.1f}kg", qty))
        result.cost_cents = round(qty * (row["price_cents"] or 0))
        if row["stock_qty"] is not None and qty > row["stock_qty"] + 1e-9:
            result.note = f"short: only {row['stock_qty']:g}kg in stock"
        return result

    if packs:
        chosen = _find_pack(packs, pack) if pack else (_single_pack(packs) if unit == "pk" else None)
        if pack and chosen is None:
            result.note = f"pack {pack!r} not found or out of stock; see bruve_get"
            return result
        if chosen is not None:
            if unit != "pk":
                result.note = "when pack is given, need must be a count with unit pk"
                return result
            count = math.ceil(need - 1e-9)
            result.buy = f"{count}x{_label(chosen)}"
            result.items.append(BuyItem(f"{count}x{_label(chosen)}", count, chosen))
            result.cost_cents = count * (chosen["price_cents"] or 0)
            if chosen["stock_qty"] is not None and count > chosen["stock_qty"]:
                result.note = f"short: only {chosen['stock_qty']:g} in stock"
            return result
        base_need, base_unit = _to_base(need, unit)
        if base_unit not in {"g", "ml"}:
            result.note = "several packs exist: give need in g/kg (or ml/l), or set pack and need in pk"
            return result
        options = _cheapest_per_size(packs, base_unit)
        plan = cover(base_need, options)
        if plan is None:
            have = sum(o["size"] * (o["limit"] if o["limit"] is not None else 0) for o in options)
            result.note = "cannot cover need from stock" + (f" (known stock {have:g}{base_unit})" if have else "")
            return result
        chosen_packs, cost, total = plan
        result.buy = " + ".join(f"{count}x{p['label']}" for p, count in chosen_packs)
        result.items = [BuyItem(f"{count}x{p['label']}", count, p["row"]) for p, count in chosen_packs]
        result.cost_cents = cost
        extra = total - base_need
        if extra > 1e-9:
            result.note = f"{total:g}{base_unit} total, {extra:g}{base_unit} over need"
        return result

    # Simple product sold per pack (for example yeast sachets).
    if unit == "pk":
        count = math.ceil(need - 1e-9)
    elif unit in {"g", "kg", "ml", "l"} and row["pack_size"] and row["pack_unit"] == _to_base(need, unit)[1]:
        count = math.ceil(_to_base(need, unit)[0] / row["pack_size"] - 1e-9)
    else:
        result.note = "pack size unknown: give need as a count with unit pk"
        return result
    label = f"{count}x" + (row["pack_label"] or "pack")
    result.buy = label
    result.items.append(BuyItem(label, count))
    result.cost_cents = count * (row["price_cents"] or 0)
    if row["stock_qty"] is not None and count > row["stock_qty"]:
        result.note = f"short: only {row['stock_qty']:g} in stock"
    return result


def render(results: list[LineResult], *, links: bool = True) -> str:
    lines = ["id|name|buy|EUR|note"]
    total = 0
    for r in results:
        if r.cost_cents is not None:
            total += r.cost_cents
        lines.append("|".join([str(r.product_id), r.name[:48], r.buy or "-", eur(r.cost_cents) if r.cost_cents is not None else "-", r.note]))
    lines.append(
        f"total: {eur(total)} EUR incl. VAT for {sum(1 for r in results if r.cost_cents is not None)}/{len(results)} lines"
    )
    if links:
        lines.append("links to click (adds to your cart on bruve.lv; this server orders nothing):")
        for r in results:
            for item in r.items:
                link = cart_link(r.product_id, item.quantity, item.pack) or product_link(r.url, item.pack)
                lines.append(f"{r.product_id} {item.label}: {link}")
    return "\n".join(lines)
