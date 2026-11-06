"""Polite, locked-down HTTP client for the public bruve.lv WooCommerce Store API.

Only read-only Store API product endpoints on bruve.lv are reachable. Cart, checkout, account
and add-to-cart URLs are refused here so no tool can ever trigger them.
"""

import asyncio
import re
import time
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

import httpx

BASE_URL = "https://bruve.lv"
USER_AGENT = "bruve-mcp/0.1 (read-only personal homebrew assistant)"

_ALLOWED_PATH = re.compile(
    r"^/wp-json/wc/store/v1/products(?:/(?:\d{1,12}|categories|attributes|brands))?$"
)
_FORBIDDEN_PARAM = re.compile(r"add-to-cart|nonce|cart|checkout|remove_item", re.IGNORECASE)
_RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_S = 30.0


class BruveRequestRefused(ValueError):
    """Raised when a request would leave the read-only Store API allowlist."""


class BruveHttpError(RuntimeError):
    """Raised when bruve.lv keeps failing after retries."""


def check_request(path: str, params: Mapping[str, Any] | None) -> None:
    if not _ALLOWED_PATH.fullmatch(path):
        raise BruveRequestRefused(f"Path not allowed: {path!r}")
    for key in params or {}:
        if _FORBIDDEN_PARAM.search(str(key)):
            raise BruveRequestRefused(f"Parameter not allowed: {key!r}")


class BruveClient:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        min_interval_s: float = 0.5,
        concurrency: int = 2,
        max_attempts: int = 4,
        backoff_base_s: float = 1.0,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=httpx.Timeout(20.0),
            follow_redirects=False,
        )
        self._min_interval = min_interval_s
        self._slots = asyncio.Semaphore(concurrency)
        self._pace = asyncio.Lock()
        self._next_at = 0.0
        self._max_attempts = max_attempts
        self._backoff = backoff_base_s
        self._sleep = sleep
        self.request_count = 0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _pace_request(self) -> None:
        async with self._pace:
            wait = self._next_at - time.monotonic()
            if wait > 0:
                await self._sleep(wait)
            self._next_at = time.monotonic() + self._min_interval

    async def get(
        self, path: str, params: Mapping[str, Any] | None = None
    ) -> tuple[Any, httpx.Headers]:
        check_request(path, params)
        last_error = "unknown error"
        for attempt in range(self._max_attempts):
            async with self._slots:
                await self._pace_request()
                self.request_count += 1
                try:
                    response = await self._http.get(path, params=dict(params or {}))
                except httpx.TransportError as exc:
                    last_error = f"{type(exc).__name__}"
                    response = None
            if response is not None:
                if response.status_code == 200:
                    return response.json(), response.headers
                if response.status_code not in _RETRY_STATUS:
                    raise BruveHttpError(f"HTTP {response.status_code} for {path}")
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    await self._sleep(min(float(retry_after), MAX_RETRY_AFTER_S))
                    continue
            await self._sleep(self._backoff * (2**attempt))
        raise BruveHttpError(f"{last_error} for {path} after {self._max_attempts} attempts")

    async def pages(
        self, path: str, params: Mapping[str, Any] | None = None, *, per_page: int = 100, max_pages: int = 20
    ) -> AsyncIterator[list[dict[str, Any]]]:
        page = 1
        while page <= max_pages:
            query = {**(params or {}), "per_page": per_page, "page": page}
            data, headers = await self.get(path, query)
            if not isinstance(data, list):
                raise BruveHttpError(f"Unexpected payload for {path}")
            yield data
            total_pages = int(headers.get("X-WP-TotalPages", "1") or 1)
            if page >= total_pages or not data:
                return
            page += 1
