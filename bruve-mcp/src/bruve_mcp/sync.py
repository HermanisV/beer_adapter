"""Catalogue sync: fetch the ingredient scope from the Store API into the local cache."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from .client import BruveClient
from .parse import normalize_product
from .parse.common import clean_text, parse_pack, parse_variation_label, stock_quantity
from .store import Store

# izejvielas (ingredients: malt, hops, yeast, kits) and piedevas (adjuncts, nutrients, fining ...)
SCOPE_CATEGORY_IDS = (370, 225)
PRODUCT_FIELDS = (
    "id,name,slug,type,permalink,description,prices,categories,brands,attributes,"
    "variations,is_in_stock,add_to_cart"
)
VARIATION_FIELDS = "id,parent,name,variation,prices,is_in_stock,add_to_cart"
PRODUCTS_PATH = "/wp-json/wc/store/v1/products"
CATEGORIES_PATH = "/wp-json/wc/store/v1/products/categories"
DEFAULT_TTL_HOURS = 6.0


@dataclass
class SyncResult:
    products: int
    variations: int
    requests: int
    changes: int
    seconds: float


def normalize_pack(variation: dict[str, Any]) -> dict[str, Any]:
    label = clean_text(variation.get("variation"))
    attrs = parse_variation_label(label)
    size_text = attrs.get("Iepakojums") or attrs.get("Tilpums") or ""
    pack = parse_pack(size_text)
    year = attrs.get("Gads", "")
    try:
        price = int((variation.get("prices") or {}).get("price"))
    except (TypeError, ValueError):
        price = None
    return {
        "variation_id": int(variation["id"]),
        "product_id": int(variation["parent"]),
        "label": label,
        "year": int(year) if year.isdigit() else None,
        "size": pack[0] if pack else None,
        "unit": pack[1] if pack else None,
        "price_cents": price,
        "in_stock": bool(variation.get("is_in_stock")),
        "stock_qty": stock_quantity(variation.get("add_to_cart")),
    }


async def fetch_catalogue(client: BruveClient) -> tuple[list[dict], list[dict], list[dict]]:
    categories: list[dict] = []
    async for page in client.pages(CATEGORIES_PATH):
        categories.extend(page)

    products: dict[int, dict] = {}
    for category_id in SCOPE_CATEGORY_IDS:
        async for page in client.pages(PRODUCTS_PATH, {"category": category_id, "_fields": PRODUCT_FIELDS}):
            for product in page:
                products[product["id"]] = product

    variations: list[dict] = []
    if any(p.get("variations") for p in products.values()):
        async for page in client.pages(PRODUCTS_PATH, {"type": "variation", "_fields": VARIATION_FIELDS}):
            variations.extend(v for v in page if v.get("parent") in products)
    return categories, list(products.values()), variations


async def run_sync(client: BruveClient, store: Store) -> SyncResult:
    started = time.monotonic()
    requests_before = client.request_count
    categories, products, variations = await fetch_catalogue(client)
    by_id = {c["id"]: c for c in categories}
    normalized = [normalize_product(p, by_id) for p in products]
    packs = [normalize_pack(v) for v in variations]
    changes = store.replace_catalogue(normalized, packs)
    return SyncResult(
        products=len(normalized),
        variations=len(packs),
        requests=client.request_count - requests_before,
        changes=changes,
        seconds=round(time.monotonic() - started, 1),
    )


class CatalogueService:
    """Keeps the local cache fresh. One sync at a time; a stale cache is served if the network fails."""

    def __init__(self, client: BruveClient, store: Store, ttl_hours: float = DEFAULT_TTL_HOURS) -> None:
        self.client = client
        self.store = store
        self.ttl_seconds = ttl_hours * 3600
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    def is_fresh(self) -> bool:
        synced = self.store.synced_at()
        return synced is not None and (time.time() - synced) < self.ttl_seconds

    async def ensure(self) -> None:
        if self.is_fresh():
            return
        async with self._lock:
            if self.is_fresh():
                return
            try:
                await run_sync(self.client, self.store)
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - serve stale data rather than fail the tool
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
                if self.store.synced_at() is None:
                    raise

    async def refresh(self) -> SyncResult:
        async with self._lock:
            result = await run_sync(self.client, self.store)
            self.last_error = None
            return result

    @property
    def stale(self) -> bool:
        return not self.is_fresh()
