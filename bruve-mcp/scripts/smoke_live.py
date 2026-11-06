"""Live smoke test of the tools against bruve.lv with a throwaway cache. Prints sizes and outputs."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ["BRUVE_MCP_CACHE_DIR"] = tempfile.mkdtemp(prefix="bruve-smoke-")

from bruve_mcp import server  # noqa: E402
from bruve_mcp.format import est_tokens  # noqa: E402
from bruve_mcp.server import ShoppingLine  # noqa: E402


def show(title: str, text: str) -> None:
    print(f"\n##### {title}  [{len(text)} chars ~{est_tokens(text)} tokens]")
    print(text)


async def main() -> None:
    show("overview (first call syncs)", await server.bruve_overview())
    show(
        "lookup (BF aveņu skābais + inventory style names)",
        await server.bruve_lookup(
            ["Pilsner", "Wheat Malt", "Acidulated", "Oats, Flaked", "Carapils", "Centennial", "Philly Sour", "Irish Moss", "US-05", "Hallertauer Mittelfrueh", "Cara Pils"]
        ),
    )
    show("search: base malts 2-6 EBC", await server.bruve_search(kind="malt", ebc_min=2, ebc_max=6, sort="ebc", limit=8))
    show("search: hops AA 10-16", await server.bruve_search(kind="hop", alpha_min=10, alpha_max=16, sort="alpha", limit=6))
    show("search: dry beer yeast", await server.bruve_search(q="saison", kind="yeast", role="beer", limit=5))
    show("get full", await server.bruve_get([1002405], detail="full"))
    show("availability", await server.bruve_availability([1002405, 1008088, 1000697]))
    show(
        "shopping list (Aveņu skābais-like recipe + multi-pack hop)",
        await server.bruve_shopping_list(
            [
                ShoppingLine(id=1007998, need=1.67, unit="kg"),
                ShoppingLine(id=1000610, need=0.94, unit="kg"),
                ShoppingLine(id=1002993, need=0.28, unit="kg"),
                ShoppingLine(id=1000604, need=0.23, unit="kg"),
                ShoppingLine(id=1005984, need=0.17, unit="kg"),
                ShoppingLine(id=1002109, need=12, unit="g"),
                ShoppingLine(id=1002534, need=350, unit="g"),
                ShoppingLine(id=1000697, need=1, unit="pk"),
            ]
        ),
    )
    await server.get_runtime().client.aclose()


asyncio.run(main())
