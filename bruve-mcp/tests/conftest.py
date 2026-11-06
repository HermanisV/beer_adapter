"""Shared test fixtures: a fake bruve.lv Store API served from a slice of the real catalogue."""

import json
from pathlib import Path

import httpx
import pytest

from bruve_mcp import server
from bruve_mcp.client import BruveClient
from bruve_mcp.store import Store
from bruve_mcp.sync import CatalogueService

FIXTURES = Path(__file__).parent / "fixtures"
STORE_API = "/wp-json/wc/store/v1/products"


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))


class FakeShop:
    """Serves the Store API read endpoints and records every request."""

    def __init__(self) -> None:
        self.categories = load("categories")
        self.products = load("products")
        self.variations = load("variations")
        self.requests: list[httpx.Request] = []
        self.fail_with: int | None = None
        self.removed: set[int] = set()
        parents = {c["id"]: c["parent"] for c in self.categories}
        self._roots: dict[int, set[int]] = {}
        for product in self.products:
            roots = set()
            for cat in product["categories"]:
                node = cat["id"]
                while node:
                    roots.add(node)
                    node = parents.get(node, 0)
            self._roots[product["id"]] = roots

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_with:
            return httpx.Response(self.fail_with, json={"error": "boom"})
        path, q = request.url.path, dict(request.url.params)
        if path == f"{STORE_API}/categories":
            return self._page(self.categories, q)
        if path == STORE_API:
            if q.get("type") == "variation":
                rows = [v for v in self.variations if "parent" not in q or v["parent"] == int(q["parent"])]
                return self._page(rows, q)
            rows = [p for p in self.products if p["id"] not in self.removed]
            if "category" in q:
                rows = [p for p in rows if int(q["category"]) in self._roots[p["id"]]]
            return self._page(rows, q)
        tail = path.removeprefix(STORE_API + "/")
        if tail.isdigit():
            for product in self.products:
                if product["id"] == int(tail) and product["id"] not in self.removed:
                    return httpx.Response(200, json=product)
            return httpx.Response(404, json={"code": "woocommerce_rest_product_invalid_id"})
        return httpx.Response(404)

    @staticmethod
    def _page(rows: list, q: dict) -> httpx.Response:
        per_page = int(q.get("per_page", 10))
        page = int(q.get("page", 1))
        total_pages = max(1, -(-len(rows) // per_page))
        chunk = rows[(page - 1) * per_page : page * per_page]
        return httpx.Response(200, json=chunk, headers={"X-WP-Total": str(len(rows)), "X-WP-TotalPages": str(total_pages)})


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def shop() -> FakeShop:
    return FakeShop()


@pytest.fixture
def make_client(shop):
    clients: list[BruveClient] = []

    def factory(**kwargs) -> BruveClient:
        kwargs.setdefault("sleep", no_sleep)
        kwargs.setdefault("min_interval_s", 0)
        client = BruveClient(transport=httpx.MockTransport(shop.handler), **kwargs)
        clients.append(client)
        return client

    yield factory


@pytest.fixture
async def runtime(shop, make_client):
    client = make_client()
    store = Store(":memory:")
    service = CatalogueService(client, store, ttl_hours=6)
    rt = server.Runtime(client, store, service)
    server.set_runtime(rt)
    await service.ensure()
    yield rt
    server.set_runtime(None)
    await client.aclose()
    store.close()
