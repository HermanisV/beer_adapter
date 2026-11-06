"""Capture the raw in-scope catalogue from bruve.lv into debug/ for parser development."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bruve_mcp.sync import PRODUCT_FIELDS, SCOPE_CATEGORY_IDS, VARIATION_FIELDS  # noqa: E402
from bruve_mcp.client import BruveClient  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "debug"


async def main() -> None:
    OUT.mkdir(exist_ok=True)
    client = BruveClient()
    try:
        categories = []
        async for page in client.pages("/wp-json/wc/store/v1/products/categories"):
            categories.extend(page)
        products: dict[int, dict] = {}
        for cat in SCOPE_CATEGORY_IDS:
            async for page in client.pages(
                "/wp-json/wc/store/v1/products", {"category": cat, "_fields": PRODUCT_FIELDS}
            ):
                for p in page:
                    products[p["id"]] = p
        variations = []
        async for page in client.pages(
            "/wp-json/wc/store/v1/products", {"type": "variation", "_fields": VARIATION_FIELDS}
        ):
            variations.extend(page)
        (OUT / "categories.json").write_text(json.dumps(categories, ensure_ascii=False), "utf-8")
        (OUT / "products.json").write_text(json.dumps(list(products.values()), ensure_ascii=False), "utf-8")
        (OUT / "variations.json").write_text(json.dumps(variations, ensure_ascii=False), "utf-8")
        print(f"categories={len(categories)} products={len(products)} variations={len(variations)} requests={client.request_count}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
