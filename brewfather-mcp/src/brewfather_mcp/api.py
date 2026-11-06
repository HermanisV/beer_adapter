from enum import StrEnum
import json
import logging
import math
import os
import re
import httpx
import urllib.parse

logger = logging.getLogger(__name__)
from .types import (
    FermentableDetail,
    FermentableList,
    HopDetail,
    HopList,
    InventoryCategory,
    MiscDetail,
    MiscList,
    RecipeDetail,
    RecipeList,
    YeastDetail,
    YeastList,
    BatchDetail,
    BatchList,
)
from .types.brewtracker import BrewTrackerStatus, BatchReadingsList, LastReading

BASE_URL: str = "https://api.brewfather.app/v2"

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_id(value: str) -> str:
    """Reject IDs that could alter the request path, query or fragment."""
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError("Invalid ID: expected 1-64 characters from A-Z, a-z, 0-9, '_' or '-'.")
    return value


def validate_inventory_amount(amount: float) -> float:
    """Inventory amounts must be finite and non-negative."""
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("Inventory amount must be a finite number that is zero or greater.")
    return amount


class BrewfatherApiError(RuntimeError):
    """A Brewfather API error with a short, safe-to-show explanation."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Brewfather API {status}: {detail}")
        self.status = status
        self.detail = detail


class OrderByDirection(StrEnum):
    ASCENDING = "asc"
    DESCENDING = "desc"

class ListQueryParams:
    inventory_negative: bool | None = None
    complete: bool | None = None
    inventory_exists: bool | None = None
    limit: int | None = None
    start_after: str | None = None
    order_by: str | None = None
    order_by_direction: OrderByDirection | None = None

    def as_query_param_str(self) -> str | None:
        params = []

        if self.inventory_negative is not None:
            params.append(f"inventory_negative={'true' if self.inventory_negative else 'false'}")

        if self.complete is not None:
            params.append(f"complete={'true' if self.complete else 'false'}")

        if self.inventory_exists is not None:
            params.append(f"inventory_exists={'true' if self.inventory_exists else 'false'}")

        if self.limit:
            params.append(f"limit={self.limit}")

        if self.start_after:
            params.append(f"start_after={urllib.parse.quote_plus(self.start_after)}")

        if self.order_by:
            params.append(f"order_by={urllib.parse.quote_plus(self.order_by)}")

        if self.order_by_direction:
            params.append(f"order_by_direction={self.order_by_direction}")

        if params:
            return "&".join(params)
        else:
            return None

class BrewfatherClient:
    """Client for interacting with the Brewfather API."""

    def __init__(self):
        user_id = os.getenv("BREWFATHER_API_USER_ID")
        if not user_id or user_id.startswith("${"):
            user_id = os.getenv("BF_USER_ID")
        api_key = os.getenv("BREWFATHER_API_KEY")
        if not api_key or api_key.startswith("${"):
            api_key = os.getenv("BF_USER_KEY")

        if not user_id or not api_key:
            raise ValueError(
                "Missing Brewfather credentials in the environment variables: BREWFATHER_API_USER_ID or BREWFATHER_API_KEY"
            )

        self.auth = httpx.BasicAuth(user_id, api_key)
        self.max_pages = 10  # Safety limit to prevent infinite loops

    async def _make_request(self, url: str) -> str:
        async with httpx.AsyncClient(auth=self.auth) as client:
            response = await client.get(url)
            response.raise_for_status()
            # Write response to a file for debugging when debug mode is enabled
            if os.getenv("BREWFATHER_MCP_DEBUG"):
                debug_dir = os.path.join(os.path.dirname(__file__), "..", "..", "debug")
                os.makedirs(debug_dir, exist_ok=True)
                debug_filename = re.sub(
                    r"[^A-Za-z0-9_.-]", "_", url[len(BASE_URL) + 1:].split('?')[0]
                ) + ".json"
                debug_path = os.path.join(debug_dir, debug_filename)
                with open(debug_path, "w", encoding="utf-8") as debug_file:
                    debug_file.write(response.text)
            return response.text

    async def _make_patch_request(self, url: str, data: dict) -> None:
        async with httpx.AsyncClient(auth=self.auth) as client:
            response = await client.patch(url, json=data)
            response.raise_for_status()

    async def _make_post_request(self, url: str, data: dict) -> str:
        async with httpx.AsyncClient(auth=self.auth) as client:
            response = await client.post(url, json=data)
            response.raise_for_status()
            return response.text

    def _build_url(
        self,
        endpoint: str,
        id: str | None = None,
        query_params: ListQueryParams | None = None,
        suffix: str | None = None,
    ) -> str:
        """Build a URL for the Brewfather API.

        Args:
            endpoint: The API endpoint (e.g., 'recipes', 'batches', 'inventory/fermentables')
            id: Optional ID for detail endpoints
            query_params: Optional query parameters
            suffix: Optional fixed sub-resource path (e.g., 'readings/last') appended after the ID
        """
        url = f"{BASE_URL}/{endpoint}"
        if id:
            url = f"{url}/{validate_id(id)}"
            if suffix:
                url = f"{url}/{suffix}"
        if query_params:
            url += f"?{query_params.as_query_param_str()}"
        return url

    async def _get_paginated_list(
        self,
        endpoint: str,
        model_class,
        query_params: ListQueryParams | None = None,
    ):
        """Fetch all pages of a list endpoint using cursor pagination.

        Args:
            endpoint: The API endpoint to query
            model_class: The Pydantic model class to validate responses
            query_params: Query parameters including filters and limit

        Returns:
            A model instance with all results from all pages
        """
        all_items = []
        current_params = query_params or ListQueryParams()

        # Set a reasonable limit per page if not specified
        if not current_params.limit:
            current_params.limit = 50

        page_count = 0
        while page_count < self.max_pages:
            url = self._build_url(endpoint, query_params=current_params)
            json_response = await self._make_request(url)
            page_result = model_class.model_validate_json(json_response)

            # Add items from this page
            all_items.extend(page_result.root)

            # Check if there are more pages
            # If we got fewer items than the limit, we've reached the end
            if len(page_result.root) < current_params.limit:
                break

            # Set start_after to the ID of the last item for next page
            if page_result.root:
                current_params.start_after = page_result.root[-1].id
            else:
                break

            page_count += 1

        if page_count >= self.max_pages:
            logger.warning(
                f"Reached max page limit ({self.max_pages}) for endpoint '{endpoint}'. "
                f"Total items fetched: {len(all_items)}. There may be more items available."
            )

        logger.info(f"Fetched {len(all_items)} total items from '{endpoint}' across {page_count + 1} page(s)")

        # Return a new model instance with all collected items
        return model_class(root=all_items)

    # Inventory endpoints
    async def get_fermentables_list(
        self, query_params: ListQueryParams | None = None
    ) -> FermentableList:
        return await self._get_paginated_list(
            f"inventory/{InventoryCategory.FERMENTABLES}",
            FermentableList,
            query_params
        )

    async def get_fermentable_detail(self, id: str) -> FermentableDetail:
        url = self._build_url(
            f"inventory/{InventoryCategory.FERMENTABLES}", id=id
        )
        json_response = await self._make_request(url)
        return FermentableDetail.model_validate_json(json_response)

    async def update_fermentable_inventory(self, id: str, inventory: float) -> None:
        url = self._build_url(
            f"inventory/{InventoryCategory.FERMENTABLES}", id=id
        )
        await self._make_patch_request(url, {"inventory": validate_inventory_amount(inventory)})

    # Batch endpoints
    async def get_batches_list(
        self, query_params: ListQueryParams | None = None
    ) -> BatchList:
        return await self._get_paginated_list("batches", BatchList, query_params)

    async def get_batch_detail(self, id: str) -> BatchDetail:
        url = self._build_url("batches", id=id)
        json_response = await self._make_request(url)
        return BatchDetail.model_validate_json(json_response)

    async def update_batch_detail(self, id: str, data: dict) -> None:
        url = self._build_url("batches", id=id)
        await self._make_patch_request(url, data)

    # Recipe endpoints
    async def get_recipes_list(
        self, query_params: ListQueryParams | None = None
    ) -> RecipeList:
        return await self._get_paginated_list("recipes", RecipeList, query_params)

    async def get_recipe_detail(self, id: str) -> RecipeDetail:
        url = self._build_url("recipes", id=id)
        json_response = await self._make_request(url)
        return RecipeDetail.model_validate_json(json_response)

    async def get_recipe_raw(self, id: str) -> dict:
        """The recipe exactly as Brewfather returns it, for cloning."""
        url = self._build_url("recipes", id=id)
        return json.loads(await self._make_request(url))

    async def get_inventory_raw(self, category: str, id: str) -> dict:
        """One inventory item exactly as Brewfather returns it."""
        if category not in {c.value for c in InventoryCategory}:
            raise ValueError("Invalid inventory category.")
        url = self._build_url(f"inventory/{category}", id=id)
        return json.loads(await self._make_request(url))

    async def create_inventory_item(self, category: str, body: dict) -> str:
        """POST /inventory/{category}. Creates a new inventory item and returns its id."""
        if category not in {c.value for c in InventoryCategory}:
            raise ValueError("Invalid inventory category.")
        payload = dict(body)
        if "inventory" in payload and payload["inventory"] is not None:
            payload["inventory"] = validate_inventory_amount(float(payload["inventory"]))
        url = self._build_url(f"inventory/{category}")
        async with httpx.AsyncClient(auth=self.auth) as client:
            response = await client.post(url, json=payload)
        if response.status_code == 403:
            raise BrewfatherApiError(403, "the API key lacks the inventory.write scope")
        if response.status_code >= 400:
            raise BrewfatherApiError(response.status_code, response.text[:600])
        new_id = response.json().get("id")
        if not isinstance(new_id, str):
            raise BrewfatherApiError(response.status_code, "response did not contain the new inventory item id")
        return validate_id(new_id)

    async def create_recipe(self, body: dict) -> str:
        """POST /recipes. Always creates a separate recipe; returns its new id."""
        url = self._build_url("recipes")
        async with httpx.AsyncClient(auth=self.auth) as client:
            response = await client.post(url, json=body)
        if response.status_code == 403:
            raise BrewfatherApiError(403, "the API key lacks the recipes.write scope")
        if response.status_code >= 400:
            raise BrewfatherApiError(response.status_code, response.text[:600])
        new_id = response.json().get("id")
        if not isinstance(new_id, str):
            raise BrewfatherApiError(response.status_code, "response did not contain the new recipe id")
        return validate_id(new_id)

    # Add similar patterns for other inventory types (hops, yeasts, miscs)...
    async def get_hops_list(
        self, query_params: ListQueryParams | None = None
    ) -> HopList:
        return await self._get_paginated_list(
            f"inventory/{InventoryCategory.HOPS}",
            HopList,
            query_params
        )
    
    async def get_hop_detail(self, id: str) -> HopDetail:
        url = self._build_url(
            f"inventory/{InventoryCategory.HOPS}", id=id
        )
        json_response = await self._make_request(url)
        return HopDetail.model_validate_json(json_response)
    
    async def update_hop_inventory(self, id: str, inventory: float) -> None:
        url = self._build_url(
            f"inventory/{InventoryCategory.HOPS}", id=id
        )
        await self._make_patch_request(url, {"inventory": validate_inventory_amount(inventory)})

    async def get_yeasts_list(
        self, query_params: ListQueryParams | None = None
    ) -> YeastList:
        return await self._get_paginated_list(
            f"inventory/{InventoryCategory.YEASTS}",
            YeastList,
            query_params
        )
    
    async def get_yeast_detail(self, id: str) -> YeastDetail:
        url = self._build_url(
            f"inventory/{InventoryCategory.YEASTS}", id=id
        )
        json_response = await self._make_request(url)
        return YeastDetail.model_validate_json(json_response)
    
    async def update_yeast_inventory(self, id: str, inventory: float) -> None:
        url = self._build_url(
            f"inventory/{InventoryCategory.YEASTS}", id=id
        )
        await self._make_patch_request(url, {"inventory": validate_inventory_amount(inventory)})

    async def get_miscs_list(
        self, query_params: ListQueryParams | None = None
    ) -> MiscList:
        return await self._get_paginated_list(
            f"inventory/{InventoryCategory.MISCS}",
            MiscList,
            query_params
        )

    async def get_misc_detail(self, id: str) -> MiscDetail:
        url = self._build_url(
            f"inventory/{InventoryCategory.MISCS}", id=id
        )
        json_response = await self._make_request(url)
        return MiscDetail.model_validate_json(json_response)
    
    async def update_misc_inventory(self, id: str, inventory: float) -> None:
        url = self._build_url(
            f"inventory/{InventoryCategory.MISCS}", id=id
        )
        await self._make_patch_request(url, {"inventory": validate_inventory_amount(inventory)})

    # Brewtracker endpoints
    async def get_batch_brewtracker(self, batch_id: str) -> BrewTrackerStatus:
        """Get brewtracker status for a batch"""
        url = self._build_url("batches", id=batch_id, suffix="brewtracker")
        json_response = await self._make_request(url)
        return BrewTrackerStatus.model_validate_json(json_response)
    
    async def get_batch_readings(self, batch_id: str) -> BatchReadingsList:
        """Get all readings for a batch"""
        url = self._build_url("batches", id=batch_id, suffix="readings")
        json_response = await self._make_request(url)
        return BatchReadingsList.model_validate_json(json_response)
    
    async def get_batch_last_reading(self, batch_id: str) -> LastReading:
        """Get last reading for a batch"""
        url = self._build_url("batches", id=batch_id, suffix="readings/last")
        json_response = await self._make_request(url)
        return LastReading.model_validate_json(json_response)
