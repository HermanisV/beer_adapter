"""Read-only check of the recipe tools against the live Brewfather account. Never POSTs."""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("BREWFATHER_API_USER_ID", os.environ.get("BF_USER_ID", ""))
os.environ.setdefault("BREWFATHER_API_KEY", os.environ.get("BF_USER_KEY", ""))

from brewfather_mcp import server  # noqa: E402
from brewfather_mcp.recipe_edit import RecipeEdit, apply_edits  # noqa: E402

RECIPE_ID = sys.argv[1] if len(sys.argv) > 1 else "L2lcDx2lvJYbhj2iTEvxtdhmrD56iq"


async def main() -> None:
    client = server.brewfather_client
    table = await server.read_recipe_ingredients(RECIPE_ID)
    print(f"## get_recipe_ingredients ({len(table)} chars, ~{int(len(table) / 3.2)} tokens)\n{table}\n")

    base = await client.get_recipe_raw(RECIPE_ID)
    edits = [
        RecipeEdit(op="replace", kind="fermentable", target="Pilsner", fields={"name": "Pilsner", "supplier": "BestMalz", "origin": "DE", "color": 1.9}),
        RecipeEdit(op="replace", kind="fermentable", target="Acidulated",
                   fields={"name": "Sauer-skabais", "supplier": "The Swaen", "origin": "NL", "color": 7.1, "grainCategory": "Acidulated"}),
        RecipeEdit(op="replace", kind="hop", target="Centennial", fields={"name": "Centennial", "alpha": 10}),
        RecipeEdit(op="resize", kind="misc", target="Irish Moss", scale=0),
    ]
    edits[-1] = RecipeEdit(op="remove", kind="misc", target="Irish Moss")
    outcome = apply_edits(base, edits, new_name="Aveņu skābais (test, not created)", notes_append="Dry run only.")
    print("## apply_edits dry run")
    print("\n".join(outcome.lines))
    print("warnings:", "; ".join(outcome.warnings) or "none")
    keys = sorted(outcome.body)
    print(f"\nbody keys ({len(keys)}): {', '.join(keys)}")
    print("underscore keys left:", [k for k in outcome.body if k.startswith('_')])


asyncio.run(main())
