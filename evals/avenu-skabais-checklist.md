# Acceptance Evaluation Checklist: *Aveņu skābais*

Use this checklist to verify `@homebrew-orchestrator` (and the underlying skills and MCP tools) in chat against the real Brewfather library recipe **Aveņu skābais** (`L2lcDx2lvJYbhj2iTEvxtdhmrD56iq`) and the user's Brewfather inventory + bruve.lv catalogue.

---

## Test Prompts

### Scenario 1 — Availability Check
> `@homebrew-orchestrator Confirm my Brewfather inventory can make a new batch of Aveņu skābais; if something is missing, give me a bruve.lv purchase list.`

### Scenario 2 — Recipe Adaptation
> `@homebrew-orchestrator Check Aveņu skābais and create a new adapted version using ingredients available in my inventory and at bruve.lv, with a shopping list.`

---

## Tool Call Discipline & Token Efficiency Checks

Measured baseline across the full 14-call workflow is **~3,250 tokens** (~10.4 KB total tool output, vs ~26 KB for a single raw recipe payload):

| Tool Call | Measured Output |
|---|---|
| `bruve_overview()` | ~242 tokens (772 chars) |
| `brewfather/list_recipes` | ~611 tokens (1,954 chars) |
| `brewfather/get_recipe_ingredients` | ~443 tokens (1,415 chars) |
| `brewfather/list_fermentables` | ~277 tokens (886 chars) |
| `brewfather/list_hops` | ~421 tokens (1,346 chars) |
| `brewfather/list_yeasts` | ~71 tokens (225 chars) |
| `brewfather/list_misc_items` | ~37 tokens (117 chars) |
| `bruve_lookup` (batched, 8 queries) | ~416 tokens (1,331 chars) |
| `bruve_search` (3 targeted calls: `sauer`, `dextrin`, `fining`) | ~257 tokens (816 chars) |
| `bruve_availability` (final shortlist) | ~125 tokens (400 chars) |
| `bruve_shopping_list` (`links=true`) | ~94 tokens (298 chars) |
| `brewfather/create_recipe_version` (`dry_run=true`) | ~260 tokens (832 chars) |
| **Total (14 calls)** | **~3,254 tokens (10,392 chars)** |

### Checklist
- [ ] **Recipe lookup**: Calls `list_recipes` once, matches `Aveņu skābais` (diacritic-insensitive), and calls `get_recipe_ingredients` **once** (~443 tokens). Does **not** call `get_recipe_detail` (~26 KB).
- [ ] **Normalized needs**: Combines the two `Centennial` additions (`#1` 6 g @ 30 min Boil + `#2` 6 g @ 5 min Boil = **12 g total** needed) when checking inventory/shop stock, while keeping `#1` and `#2` distinct for recipe edits.
- [ ] **BF inventory check**: Calls `list_fermentables`, `list_hops`, `list_yeasts`, and `list_misc_items` (plus targeted `get_fermentable_detail` only where colour/supplier verification is needed).
- [ ] **Batched bruve lookup**: Calls `bruve_lookup` **once** with a batched list of queries rather than looping one call per ingredient.
- [ ] **Targeted bruve search**: Uses `bruve_search` and `search` on `.github/skills/ingredient-substitution/knowledge/*.md` only for misses (`Acidulated`, `Carapils/Carafoam`, `Irish Moss`, `Raspberry`) or option discovery.
- [ ] **Live verification & cart safety**: Calls `bruve_availability` on final shop IDs, then `bruve_shopping_list(links=true)`. Never attempts to fetch or open any `add-to-cart` or checkout URL.

---

## Ingredient-by-Ingredient Acceptance Criteria

| # | Recipe Ingredient (`get_recipe_ingredients`) | Needed | Expected Match Tier & Source | Required Agent Behaviour |
|---|---|---|---|---|
| **F#1** | **Pilsner** (Fuglsang, 1.9 SRM / ~3.8 EBC) | 1.67 kg | **Tier 1 (Direct category)** — multiple candidates | Finds **Latmalt Pilsner** in BF inventory (4.31 kg) **and** bruve.lv options (**BestMalz Pilsen**, **Latmalt Pilsner**). **Shows all options** with colour, stock, and EUR/kg price; **recommends using the BF inventory Latmalt Pilsner**; asks the user to confirm/pick rather than silently picking. |
| **F#2** | **Raspberry (Fruit) - Added to fermenter late** | 1.21 kg | **Out of scope / Not sold at bruve.lv** | After `bruve_lookup` + `bruve_search`, states clearly that fresh/frozen raspberries are **not sold at bruve.lv (out of homebrew shop ingredient scope)** and asks the user (keep in recipe and buy at a grocery store, or adjust). Never guesses an unrelated shop product. |
| **F#3** | **Wheat Malt** (BestMalz, 2.4 SRM / ~4.8 EBC) | 0.94 kg | **Tier 1 (Direct category)** — BF inventory | Matches **Latmalt Wheat** in BF inventory (13.5 kg on hand, within colour tolerance). Lists as covered `[Tier 1]`. (If shop options like BestMalz Heidelberg Kvieši / Graudzēts Kviešu are mentioned, recommends inventory). |
| **F#4** | **Acidulated** (BestMalz, 3.0 SRM / ~6 EBC) | 0.28 kg | **Tier 3 (`M-ACID`, `close`, draft table)** — bruve.lv | Not in BF inventory. Finds **Platinum Swaen© Sauer-skābais (14 EBC / 7.1 SRM)** at bruve.lv via curated group `M-ACID`. Flags `[Tier 3 - close, draft table]`, notes colour difference (`3.0 -> 7.1 SRM` / 14 EBC, small 0.28 kg mash pH addition), and **asks for confirmation**. |
| **F#5** | **Oats, Flaked** (Briess, 1.4 SRM) | 0.23 kg | **Tier 0 (Exact)** — BF inventory | Matches **Oats, Flaked** in BF inventory (`have >= 0.23 kg`). Applied silently and listed in the summary table. |
| **F#6** | **Carapils/Carafoam** (Weyermann, 2.0 SRM / ~4 EBC) | 0.17 kg | **Tier 3 (`M-CARAPILS`, `close`, draft table)** — bruve.lv | Not in BF inventory. Finds bruve.lv dextrin/carapils equivalents from `M-CARAPILS`: **Platinum Swaen© Dextrin (EBC 3-5)** and/or **BestMalz Caramel Pils (EBC 5)** / **The Swaen© Chit (EBC 2-3)**. Flags `[Tier 3 - close, draft table]`, explains `what changes` (body & foam with minimal colour), and **asks for confirmation**. |
| **H#1, H#2** | **Centennial** (8.5% AA, 6 g @ 30m Boil + 6 g @ 5m Boil) | 12 g total | **Tier 2 (Fuzzy same-ingredient)** — BF inventory | Matches **Centennial** in BF inventory (278 g @ **10.0% AA**). Flags `[Tier 2]` alpha difference (`8.5% -> 10.0% AA`). Rescales the 30 min bittering addition `#1` from **6 g → 5.1 g** (`6 * 8.5 / 10.0`) to keep IBU, while keeping the 5 min aroma addition `#2` at **6 g** (total **11.1 g** used). Includes in grouped confirmation. |
| **Y#1** | **Philly Sour - Lallemand** (Dry, 1 pkg) | 1 pkg | **Tier 0 (Exact)** — bruve.lv purchase | Not in BF inventory (inventory only has Heritage American Ale and Munich Classic, which cannot substitute for a Lachancea sour). Matches **Lallemand WildBrew™ Philly Sour** at bruve.lv as an **exact purchase** (`1x11g`). |
| **M#1** | **Yeast Nutrients** (1 items @ 15m Boil) | 1 unit | **Tier 0 / Tier 1** — BF inventory or bruve.lv | Uses BF inventory if present, or offers bruve.lv yeast nutrient (`X-YEAST-NUTRIENT`, e.g., Mangrove Jack's Yeast Nutrient) with dose note. |
| **M#2** | **Irish Moss** (1 items @ 10m Boil) | 1 unit | **Not sold / Out of stock at bruve.lv** | After `bruve_lookup` + `bruve_search` (and checking `X-KETTLE-FINING`), states that neither Irish Moss nor Whirlfloc/Protafloc is currently listed in stock at bruve.lv. **Asks the user** whether to keep it (if on hand elsewhere) or remove `#2` from the adapted recipe. |

---

## Scenario 2 Adaptation & Safety Checks

- [ ] **Single grouped confirmation**: All decisions (Pilsner option pick, Centennial Tier 2 rescale, Acidulated → Sauer-skābais Tier 3, Carapils → Dextrin/Caramel Pils Tier 3, Raspberry keep/external, Irish Moss keep/remove) are asked in **one grouped prompt**.
- [ ] **Dry run before write**: `create_recipe_version` is called with `dry_run=true` first and **never** called with `dry_run=false` before explicit user approval.
- [ ] **Never overwrites**: The new recipe has a distinct name (e.g., `Aveņu skābais (adapted)`) and `public=false`, created via `POST /v2/recipes`.
- [ ] **Metric deltas reported**: After creation (or in the readback report), shows `OG | FG | ABV | IBU | SRM` before/after values (or honestly notes if Brewfather requires opening the recipe in the UI to trigger calculation).
- [ ] **Shopping list accuracy**: `bruve_shopping_list` includes only what must be bought from bruve.lv (`0.3kg` Sauer-skābais rounded up from 0.28 kg, `0.2kg` Dextrin/Caramel Pils rounded up from 0.17 kg, `1x11g` Philly Sour, plus any user-selected shop items), with EUR incl. VAT total and clickable links.
