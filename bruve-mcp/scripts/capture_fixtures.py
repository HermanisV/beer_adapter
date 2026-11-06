"""Build tests/fixtures/ from the raw capture in debug/ (run scripts/capture_raw.py first).

Keeps a small, representative slice of the real catalogue: every parser path is exercised by
at least one real product. Descriptions are kept whole because alpha acid and yeast data sit at their end.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bruve_mcp.parse import normalize_product  # noqa: E402

RAW = ROOT / "debug"
OUT = ROOT / "tests" / "fixtures"

WANTED_IDS = {
    # malts: base, caramel, roasted, wheat, specialty, flakes
    1008088, 1008001, 1007945, 1007998, 1000610, 1005984, 1002993, 1000604, 1001124, 1005544, 1001873,
    # extracts
    1007644, 1005379, 1002669,
    # hops: variable with years, no alpha, typical value in brackets, range only
    1002405, 1002534, 1002610, 1002109, 1002455, 1001593, 1003025,
    # yeast: dry beer, lager, sour, wine, liquid-style names, kveik
    1001155, 1001157, 1000697, 1000681, 1006468, 1003000, 1002994, 1002148, 1007741, 1002668, 1003043,
}
PER_KIND_EXTRA = {"nutrient": 1, "fining": 1, "sugar": 1, "additive": 1, "water_treatment": 1, "kit": 1, "acid": 1, "enzyme": 1}


def main() -> None:
    products = json.loads((RAW / "products.json").read_text("utf-8"))
    variations = json.loads((RAW / "variations.json").read_text("utf-8"))
    categories = json.loads((RAW / "categories.json").read_text("utf-8"))

    chosen = [p for p in products if p["id"] in WANTED_IDS]
    seen: dict[str, int] = {}
    for product in products:
        kind = normalize_product(product)["kind"]
        if kind in PER_KIND_EXTRA and seen.get(kind, 0) < PER_KIND_EXTRA[kind] and product not in chosen:
            chosen.append(product)
            seen[kind] = seen.get(kind, 0) + 1
    ids = {p["id"] for p in chosen}
    chosen_variations = [v for v in variations if v.get("parent") in ids]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "categories.json").write_text(json.dumps(categories, ensure_ascii=False), "utf-8")
    (OUT / "products.json").write_text(json.dumps(chosen, ensure_ascii=False), "utf-8")
    (OUT / "variations.json").write_text(json.dumps(chosen_variations, ensure_ascii=False), "utf-8")
    print(f"products={len(chosen)} variations={len(chosen_variations)} categories={len(categories)}")


if __name__ == "__main__":
    main()
