import httpx
import pytest

from bruve_mcp.client import BruveClient, BruveHttpError, BruveRequestRefused, check_request
from bruve_mcp.store import Store
from bruve_mcp.sync import CatalogueService, normalize_pack, run_sync
from conftest import STORE_API, no_sleep


class TestAllowlist:
    @pytest.mark.parametrize(
        "path",
        [
            f"{STORE_API}",
            f"{STORE_API}/1008088",
            f"{STORE_API}/categories",
            f"{STORE_API}/attributes",
            f"{STORE_API}/brands",
        ],
    )
    def test_read_endpoints_allowed(self, path):
        check_request(path, {"per_page": 10})

    @pytest.mark.parametrize(
        "path",
        [
            "/cart",
            "/grozs/",
            "/checkout",
            "/my-account",
            "/wp-admin/admin-ajax.php",
            "/wp-json/wc/store/v1/cart",
            "/wp-json/wc/store/v1/cart/add-item",
            "/wp-json/wc/store/v1/checkout",
            "/wp-json/wc/store/v1/products/../cart",
            "/wp-json/wc/store/v1/products/abc",
            "/wp-json/wp/v2/users",
            "//evil.example/wp-json/wc/store/v1/products",
        ],
    )
    def test_everything_else_refused(self, path):
        with pytest.raises(BruveRequestRefused):
            check_request(path, None)

    @pytest.mark.parametrize("param", ["add-to-cart", "ADD-TO-CART", "_wpnonce", "remove_item", "cart_key", "checkout"])
    def test_cart_parameters_refused(self, param):
        with pytest.raises(BruveRequestRefused):
            check_request(STORE_API, {param: "1"})

    async def test_client_never_reaches_network_for_refused_requests(self, shop, make_client):
        client = make_client()
        with pytest.raises(BruveRequestRefused):
            await client.get("/cart")
        with pytest.raises(BruveRequestRefused):
            await client.get(STORE_API, {"add-to-cart": 1})
        assert shop.requests == []

    async def test_only_bruve_host_is_used(self, shop, make_client):
        client = make_client()
        await client.get(f"{STORE_API}/1008088")
        assert {r.url.host for r in shop.requests} == {"bruve.lv"}
        assert {r.url.scheme for r in shop.requests} == {"https"}
        assert shop.requests[0].headers["User-Agent"].startswith("bruve-mcp/")


class TestRetries:
    async def test_retries_server_errors_then_succeeds(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json=[{"id": 1}])

        sleeps: list[float] = []

        async def record(seconds):
            sleeps.append(seconds)

        client = BruveClient(transport=httpx.MockTransport(handler), sleep=record, min_interval_s=0, backoff_base_s=1.0)
        data, _ = await client.get(STORE_API)
        assert data == [{"id": 1}] and calls["n"] == 3
        assert sleeps == [1.0, 2.0]
        await client.aclose()

    async def test_honours_retry_after_but_caps_it(self):
        responses = iter([httpx.Response(429, headers={"Retry-After": "9999"}), httpx.Response(200, json=[])])
        sleeps: list[float] = []

        async def record(seconds):
            sleeps.append(seconds)

        client = BruveClient(transport=httpx.MockTransport(lambda r: next(responses)), sleep=record, min_interval_s=0)
        await client.get(STORE_API)
        assert sleeps == [30.0]
        await client.aclose()

    async def test_gives_up_after_max_attempts(self):
        client = BruveClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(500)), sleep=no_sleep, min_interval_s=0, max_attempts=3
        )
        with pytest.raises(BruveHttpError, match="after 3 attempts"):
            await client.get(STORE_API)
        assert client.request_count == 3
        await client.aclose()

    async def test_client_errors_are_not_retried(self):
        client = BruveClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)), sleep=no_sleep, min_interval_s=0)
        with pytest.raises(BruveHttpError, match="HTTP 404"):
            await client.get(f"{STORE_API}/1")
        assert client.request_count == 1
        await client.aclose()

    async def test_requests_are_paced(self):
        sleeps: list[float] = []

        async def record(seconds):
            sleeps.append(seconds)

        client = BruveClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])), sleep=record, min_interval_s=0.5
        )
        for _ in range(3):
            await client.get(STORE_API)
        assert len(sleeps) >= 2 and all(0 < s <= 0.5 for s in sleeps)
        await client.aclose()

    async def test_pages_follow_total_pages_header(self, make_client):
        client = make_client()
        sizes = []
        async for page in client.pages(STORE_API, {"category": 370}, per_page=7):
            sizes.append(len(page))
        assert len(sizes) > 1 and sizes[0] == 7


class TestSync:
    async def test_sync_loads_catalogue(self, shop, make_client):
        store = Store(":memory:")
        result = await run_sync(make_client(), store)
        assert result.products == len(shop.products) == store.product_count()
        assert result.variations == len(shop.variations)
        assert result.requests <= 10

    async def test_sync_only_requests_store_api_reads(self, shop, make_client):
        await run_sync(make_client(), Store(":memory:"))
        for request in shop.requests:
            assert request.method == "GET" and request.url.path.startswith(STORE_API)
            assert "add-to-cart" not in str(request.url)

    async def test_pack_normalization(self):
        pack = normalize_pack(
            {"id": 1005115, "parent": 1002534, "variation": "Iepakojums: 100g, Gads: 2025", "prices": {"price": "695"},
             "is_in_stock": True, "add_to_cart": {"maximum": 7}}
        )
        assert (pack["size"], pack["unit"], pack["year"], pack["price_cents"], pack["stock_qty"]) == (100, "g", 2025, 695, 7)

    async def test_second_sync_logs_price_and_stock_changes(self, shop, make_client):
        store = Store(":memory:")
        client = make_client()
        assert await run_sync(client, store) is not None
        target = next(p for p in shop.products if p["id"] == 1008088)
        target["prices"]["price"] = "250"
        target["add_to_cart"]["maximum"] = 10.0
        shop.removed.add(1000697)
        result = await run_sync(client, store)
        fields = {(c["product_id"], c["field"]) for c in store.recent_changes(50)}
        assert result.changes >= 3
        assert (1008088, "price_cents") in fields and (1008088, "stock_qty") in fields and (1000697, "removed") in fields

    async def test_service_serves_stale_cache_when_network_fails(self, shop, make_client):
        store = Store(":memory:")
        service = CatalogueService(make_client(), store, ttl_hours=0)
        await service.ensure()
        shop.fail_with = 500
        await service.ensure()
        assert store.product_count() > 0 and service.last_error and service.stale

    async def test_service_raises_without_any_cache(self, shop, make_client):
        shop.fail_with = 500
        service = CatalogueService(make_client(max_attempts=1), Store(":memory:"))
        with pytest.raises(BruveHttpError):
            await service.ensure()

    async def test_fresh_cache_makes_no_requests(self, shop, make_client):
        service = CatalogueService(make_client(), Store(":memory:"), ttl_hours=6)
        await service.ensure()
        before = len(shop.requests)
        await service.ensure()
        assert len(shop.requests) == before
