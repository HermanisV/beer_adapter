"""Report how much of the live catalogue the parsers understand. Run after parser changes."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bruve_mcp.client import BruveClient  # noqa: E402
from bruve_mcp.parse import normalize_product  # noqa: E402
from bruve_mcp.sync import fetch_catalogue  # noqa: E402

FIELDS = {
    "malt": ["ebc_min", "role"],
    "extract": ["ebc_min", "pack_label", "role"],
    "adjunct_grain": ["ebc_min"],
    "hop": ["alpha", "hop_form", "origin"],
    "yeast": ["lab", "code", "yeast_form", "floc", "temp_min", "att_min", "abv_tol", "pack_label"],
}


async def main() -> None:
    client = BruveClient()
    try:
        categories, products, _ = await fetch_catalogue(client)
    finally:
        await client.aclose()
    by_id = {c["id"]: c for c in categories}
    records = [normalize_product(p, by_id) for p in products]
    kinds: dict[str, list[dict]] = {}
    for record in records:
        kinds.setdefault(record["kind"], []).append(record)
    print(f"{len(records)} products")
    for kind, rows in sorted(kinds.items(), key=lambda item: -len(item[1])):
        line = f"{kind:16s} {len(rows):3d}"
        for field in FIELDS.get(kind, []):
            have = sum(1 for r in rows if r.get(field) not in (None, ""))
            line += f"  {field} {have}/{len(rows)}"
        print(line)
    missing = [r["name"] for r in kinds.get("hop", []) if "alpha" not in r]
    if missing:
        print("hops without parsed alpha:", "; ".join(missing))


if __name__ == "__main__":
    asyncio.run(main())
