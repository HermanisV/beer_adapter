"""Links for the human to click. The MCP never requests these URLs itself.

WooCommerce add-to-cart URLs add one product per click. Variation attribute keys were verified on
live product pages: pack size is the taxonomy attribute `attribute_pa_iepakojums`, crop year is the
custom attribute `attribute_gads`. Variations with any other attribute fall back to the product page.
"""

from __future__ import annotations

import re
import sqlite3
from urllib.parse import urlencode

from .parse.common import parse_variation_label

SHOP_HOME = "https://bruve.lv/"
ATTRIBUTE_KEYS = {"Iepakojums": "attribute_pa_iepakojums", "Gads": "attribute_gads"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def variation_params(pack: sqlite3.Row) -> dict[str, str] | None:
    attrs = parse_variation_label(pack["label"])
    if not attrs or any(name not in ATTRIBUTE_KEYS for name in attrs):
        return None
    return {ATTRIBUTE_KEYS[name]: _slug(value) for name, value in attrs.items()}


def product_link(url: str, pack: sqlite3.Row | None = None) -> str:
    params = variation_params(pack) if pack is not None else None
    return f"{url}?{urlencode(params)}" if params else url


def cart_link(product_id: int, quantity: float, pack: sqlite3.Row | None = None) -> str | None:
    """Add-to-cart URL for one product (or one variation), or None when it cannot be built reliably."""
    query: dict[str, str | float] = {"add-to-cart": product_id, "quantity": f"{quantity:g}"}
    if pack is not None:
        params = variation_params(pack)
        if params is None:
            return None
        query["variation_id"] = pack["variation_id"]
        query.update(params)
    return f"{SHOP_HOME}?{urlencode(query)}"
