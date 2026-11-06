"""Turn a raw Store API product into the normalized record the cache and tools use."""

from __future__ import annotations

from typing import Any

from .common import (
    MALT_ROLE_BY_SLUG,
    clean_text,
    kind_for,
    pack_label,
    parse_pack,
    stock_quantity,
)
from .hop import parse_alpha, parse_hop_title
from .malt import ebc_to_srm, parse_colour
from .yeast import detect_code, detect_form, detect_lab, parse_performance

DESCRIPTION_LIMIT = 1500

# English words indexed for search so "base malt", "hops" or "wine yeast" match Latvian titles.
_KIND_TAGS = {
    "malt": "malt",
    "extract": "malt extract ekstrakts",
    "adjunct_grain": "adjunct grain flakes",
    "hop": "hop hops apini",
    "yeast": "yeast raugs",
    "nutrient": "yeast nutrient",
    "fining": "fining clarifier",
    "acid": "acid",
    "enzyme": "enzyme bacteria",
    "sugar": "sugar",
    "water_treatment": "water salt treatment",
    "additive": "additive",
    "kit": "kit",
}
_ROLE_TAGS = {
    "base": "base pale",
    "caramel": "caramel crystal",
    "roasted": "roasted dark",
    "wheat": "wheat",
    "rye": "rye",
    "specialty": "specialty",
}


def _price(prices: dict[str, Any] | None, key: str = "price") -> int | None:
    try:
        return int((prices or {}).get(key))
    except (TypeError, ValueError):
        return None


def _price_max(prices: dict[str, Any] | None) -> int | None:
    try:
        return int(((prices or {}).get("price_range") or {}).get("max_amount"))
    except (TypeError, ValueError):
        return None


def normalize_product(product: dict[str, Any], categories: dict[int, dict] | None = None) -> dict[str, Any]:
    title = clean_text(product.get("name"))
    description = clean_text(product.get("description"))
    slugs = {c.get("slug", "") for c in product.get("categories", [])}
    kind = kind_for(slugs, title)
    brands = product.get("brands") or []
    brand = clean_text(brands[0].get("name")) if brands else None
    cart = product.get("add_to_cart") or {}
    try:
        step = float(cart.get("multiple_of") or 1)
    except (TypeError, ValueError):
        step = 1.0

    record: dict[str, Any] = {
        "id": int(product["id"]),
        "name": title,
        "url": product.get("permalink") or "",
        "kind": kind,
        "brand": brand,
        "type": product.get("type") or "simple",
        "in_stock": bool(product.get("is_in_stock")),
        "price_cents": _price(product.get("prices")),
        "price_max_cents": _price_max(product.get("prices")),
        # Items sold in 0.1 steps are priced per kg; everything else is priced per pack.
        "sold_by": "kg" if step < 1 else "unit",
        "stock_qty": stock_quantity(cart),
        "cats": ",".join(sorted(slugs)),
        "desc": description[:DESCRIPTION_LIMIT],
    }

    pack = parse_pack(title)
    record["pack_size"], record["pack_unit"] = pack if pack else (None, None)
    record["pack_label"] = pack_label(*pack) if pack else None

    role = None
    if kind == "malt":
        roles = [MALT_ROLE_BY_SLUG[s] for s in sorted(slugs) if s in MALT_ROLE_BY_SLUG]
        role = ",".join(dict.fromkeys(roles)) or None
    elif kind == "extract":
        role = "liquid" if "skidrie-iesala-ekstrakti" in slugs else "dry" if "sausie-iesala-ekstrakti" in slugs else None
    elif kind == "yeast":
        uses = [
            use
            for slug, use in (("alus-raugi", "beer"), ("vina-raugi", "wine"), ("citi-raugi", "other"))
            if slug in slugs
        ]
        role = ",".join(uses) or None
    record["role"] = role

    if kind in {"malt", "extract", "adjunct_grain"}:
        colour = parse_colour(title, description)
        if colour:
            record["ebc_min"], record["ebc_max"], record["colour_src"] = colour
            record["srm_min"], record["srm_max"] = ebc_to_srm(colour[0]), ebc_to_srm(colour[1])

    if kind == "hop":
        record.update(parse_hop_title(title))
        alpha = parse_alpha(description)
        if alpha:
            record["alpha_min"], record["alpha_max"], record["alpha"], record["alpha_src"] = alpha
        for attribute in product.get("attributes") or []:
            if attribute.get("name") == "Alfa Skābe" and attribute.get("terms"):
                record["attr_alpha"] = attribute["terms"][0].get("name")

    if kind == "yeast":
        lab = detect_lab(brand, title)
        record["lab"] = lab
        record["code"] = detect_code(title, lab)
        record["yeast_form"], record["form_src"] = detect_form(title, lab)
        record.update(parse_performance(description))

    tags = [_KIND_TAGS.get(kind, "")]
    if role:
        tags.extend(_ROLE_TAGS.get(r, r) for r in role.split(","))
    record["tags"] = " ".join(t for t in tags if t)
    return record


__all__ = ["normalize_product"]
