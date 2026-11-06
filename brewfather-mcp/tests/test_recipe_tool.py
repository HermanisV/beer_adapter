import json
import os
import subprocess
import sys
from unittest.mock import patch

import httpx
import pytest
import respx

import brewfather_mcp.server as server
from brewfather_mcp.api import BrewfatherApiError, BrewfatherClient
from brewfather_mcp.recipe_edit import RecipeEdit
from test_recipe_edit import make_base


class FakeClient:
    def __init__(self, base, *, inventory=None, created=None, create_error=None):
        self.base = base
        self.inventory = inventory or {}
        self.created = created
        self.create_error = create_error
        self.calls: list[tuple] = []
        self.created_body = None

    async def get_recipe_raw(self, recipe_id):
        self.calls.append(("get_recipe_raw", recipe_id))
        if recipe_id == self.base["_id"]:
            return self.base
        if recipe_id == "NEW456":
            return self.created if self.created is not None else {"_id": "NEW456", "name": "x"}
        raise AssertionError(f"unexpected recipe {recipe_id}")

    async def get_inventory_raw(self, category, item_id):
        self.calls.append(("get_inventory_raw", category, item_id))
        return self.inventory[(category, item_id)]

    async def create_recipe(self, body):
        self.calls.append(("create_recipe",))
        if self.create_error:
            raise self.create_error
        self.created_body = body
        return "NEW456"


def edit(**kwargs):
    return RecipeEdit(**kwargs)


async def run(fake, **kwargs):
    kwargs.setdefault("name", "Raspberry Sour (shop)")
    kwargs.setdefault("edits", [edit(op="resize", kind="misc", target="#1", amount=2)])
    with patch("brewfather_mcp.server.brewfather_client", fake):
        return await server.create_recipe_version("BASE123", **kwargs)


@pytest.mark.asyncio
class TestCreateRecipeVersion:
    async def test_dry_run_is_default_and_creates_nothing(self):
        fake = FakeClient(make_base())
        text = await run(fake)
        assert text.startswith("DRY RUN - nothing created: Raspberry Sour -> Raspberry Sour (shop)")
        assert "~ misc #1 Yeast Nutrients 1items -> 2items" in text and "dry_run=false" in text
        assert ("create_recipe",) not in fake.calls

    async def test_real_run_creates_a_clean_body_and_reports_deltas(self):
        created = {"_id": "NEW456", "og": 1.0436, "fg": 1.009, "abv": 4.6, "ibu": 8.04, "color": 3.2}
        fake = FakeClient(make_base(), created=created)
        text = await run(fake, dry_run=False)
        assert "created id NEW456" in text and "OG 1.042->1.044" in text and "IBU 7.0->8.0" in text
        assert fake.created_body["name"] == "Raspberry Sour (shop)" and fake.created_body["public"] is False
        assert not [k for k in fake.created_body if k.startswith("_")] and "og" not in fake.created_body
        assert fake.calls.count(("create_recipe",)) == 1

    async def test_not_calculated_is_reported_honestly(self):
        fake = FakeClient(make_base(), created={"_id": "NEW456"})
        assert "not calculated yet" in await run(fake, dry_run=False)

    async def test_api_error_is_returned_as_failure_not_raised(self):
        fake = FakeClient(make_base(), create_error=BrewfatherApiError(403, "the API key lacks the recipes.write scope"))
        text = await run(fake, dry_run=False)
        assert text.startswith("FAILED: Brewfather API 403") and "recipes.write" in text

    async def test_validation_errors_stop_before_any_write(self):
        fake = FakeClient(make_base())
        with pytest.raises(ValueError, match="must differ"):
            await run(fake, name="Raspberry Sour", dry_run=False)
        with pytest.raises(ValueError, match="between"):
            await run(fake, edits=[edit(op="replace", kind="hop", target="#1", fields={"name": "X", "alpha": 99})], dry_run=False)
        assert ("create_recipe",) not in fake.calls

    async def test_bad_base_id_never_reaches_the_api(self):
        fake = FakeClient(make_base())
        with patch("brewfather_mcp.server.brewfather_client", fake):
            for bad in ("../batches/x", "a b", "", "x" * 100):
                with pytest.raises(ValueError, match="Invalid ID"):
                    await server.create_recipe_version(bad, "New", [edit(op="resize", kind="misc", target="#1", amount=2)])
        assert fake.calls == []

    async def test_inventory_item_is_fetched_by_kind_and_deduplicated(self):
        inventory = {("fermentables", "inv1"): {"_id": "inv1", "name": "Pilsner", "supplier": "Latmalt", "color": 1.78, "type": "Grain"}}
        fake = FakeClient(make_base(), inventory=inventory)
        edits = [edit(op="replace", kind="fermentable", target="#1", inventory_id="inv1"),
                 edit(op="resize", kind="fermentable", target="#2", amount=1)]
        text = await run(fake, edits=edits)
        assert fake.calls.count(("get_inventory_raw", "fermentables", "inv1")) == 1
        assert "> fermentable #1 Pilsner 1.67kg 1.9SRM -> Pilsner 1.67kg 1.8SRM" in text

    async def test_bad_inventory_id_is_rejected(self):
        fake = FakeClient(make_base())
        with pytest.raises(ValueError, match="Invalid ID"):
            await run(fake, edits=[edit(op="replace", kind="fermentable", target="#1", inventory_id="../x")])
        assert ("create_recipe",) not in fake.calls


@pytest.mark.asyncio
class TestRecipeIngredientsTool:
    async def test_compact_table(self):
        fake = FakeClient(make_base())
        with patch("brewfather_mcp.server.brewfather_client", fake):
            text = await server.read_recipe_ingredients("BASE123")
        assert "#1|Pilsner|Fuglsang|1.67" in text and "id BASE123" in text

    async def test_invalid_id_rejected(self):
        with patch("brewfather_mcp.server.brewfather_client", FakeClient(make_base())):
            with pytest.raises(ValueError, match="Invalid ID"):
                await server.read_recipe_ingredients("../x")


def _tools(env):
    code = (
        "import asyncio, json\n"
        "import brewfather_mcp.server as s\n"
        "tools = asyncio.run(s.mcp.list_tools())\n"
        "print(json.dumps({t.name: [t.annotations.readOnlyHint, t.annotations.destructiveHint] for t in tools}))\n"
    )
    full_env = {**{k: v for k, v in os.environ.items() if not k.startswith("BREWFATHER_ENABLE")}, **env,
                "BREWFATHER_API_USER_ID": "user", "BREWFATHER_API_KEY": "key", "PYTHONPATH": os.pathsep.join(sys.path)}
    out = subprocess.run([sys.executable, "-c", code], env=full_env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


class TestRegistration:
    def test_default_registers_only_read_tools(self):
        tools = _tools({})
        assert "get_recipe_ingredients" in tools and tools["get_recipe_ingredients"][0] is True
        assert "create_recipe_version" not in tools and not any(n.startswith("update_") for n in tools)
        assert all(read_only for read_only, _ in tools.values())

    def test_recipe_switch_enables_only_recipe_creation(self):
        tools = _tools({"BREWFATHER_ENABLE_RECIPE_WRITES": "1"})
        assert tools["create_recipe_version"] == [False, False]
        assert not any(n.startswith("update_") for n in tools)

    def test_general_write_switch_does_not_enable_recipe_creation(self):
        tools = _tools({"BREWFATHER_ENABLE_WRITES": "1"})
        assert "update_batch" in tools and "create_recipe_version" not in tools


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BREWFATHER_API_USER_ID", "user")
    monkeypatch.setenv("BREWFATHER_API_KEY", "key")
    return BrewfatherClient()


@pytest.mark.asyncio
class TestApiClient:
    @respx.mock
    async def test_create_recipe_posts_json_with_basic_auth_and_returns_id(self, client):
        route = respx.post("https://api.brewfather.app/v2/recipes").respond(201, json={"id": "newid_1"})
        assert await client.create_recipe({"name": "x"}) == "newid_1"
        request = route.calls.last.request
        assert json.loads(request.content) == {"name": "x"} and request.headers["authorization"].startswith("Basic ")

    @respx.mock
    async def test_forbidden_means_missing_scope(self, client):
        respx.post("https://api.brewfather.app/v2/recipes").respond(403, text="Forbidden")
        with pytest.raises(BrewfatherApiError, match="recipes.write"):
            await client.create_recipe({"name": "x"})

    @respx.mock
    async def test_validation_errors_are_surfaced_and_truncated(self, client):
        respx.post("https://api.brewfather.app/v2/recipes").respond(400, text="[" + '{"msg":"bad"},' * 200 + "]")
        with pytest.raises(BrewfatherApiError) as info:
            await client.create_recipe({"name": "x"})
        assert info.value.status == 400 and len(info.value.detail) <= 600

    @respx.mock
    async def test_unexpected_success_body_is_rejected(self, client):
        respx.post("https://api.brewfather.app/v2/recipes").respond(201, json={"unexpected": True})
        with pytest.raises(BrewfatherApiError, match="did not contain"):
            await client.create_recipe({"name": "x"})
        respx.post("https://api.brewfather.app/v2/recipes").respond(201, json={"id": "../evil"})
        with pytest.raises(ValueError, match="Invalid ID"):
            await client.create_recipe({"name": "x"})

    @respx.mock
    async def test_raw_reads(self, client):
        respx.get("https://api.brewfather.app/v2/recipes/abc123").respond(200, json={"_id": "abc123"})
        respx.get("https://api.brewfather.app/v2/inventory/hops/h1").respond(200, json={"_id": "h1"})
        assert (await client.get_recipe_raw("abc123"))["_id"] == "abc123"
        assert (await client.get_inventory_raw("hops", "h1"))["_id"] == "h1"

    async def test_raw_reads_validate_input(self, client):
        with pytest.raises(ValueError):
            await client.get_inventory_raw("batches", "h1")
        with pytest.raises(ValueError, match="Invalid ID"):
            await client.get_recipe_raw("../x")
        with pytest.raises(ValueError, match="Invalid ID"):
            await client.get_inventory_raw("hops", "../x")


_ = httpx
