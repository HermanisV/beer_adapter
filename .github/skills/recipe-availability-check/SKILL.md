---
name: recipe-availability-check
description: Check whether the user's Brewfather inventory can brew a recipe and generate a bruve.lv shopping list with live stock, EUR prices, and click links for missing ingredients. Triggers: "can I brew X", "do I have enough for recipe X", "check recipe availability", "what do I need to buy for X".
---

# Recipe Availability Check Workflow (Scenario 1)

Use this workflow when the user asks whether they have the ingredients to brew a Brewfather recipe and what they need to buy at bruve.lv. Follow the matching policy in `ingredient-substitution` and the shop rules in `bruve-shop-explorer` and `bruve-shopping-list`.

## Tool Call Order (Token-Efficient)

1. **Find the recipe**:
   - Call `list_recipes`. Match the recipe name case- and diacritic-insensitively (e.g., `Aveņu skābais` matches `avenu skabais`). If multiple recipes match, ask the user which one they mean.
   - Call `get_recipe_ingredients(recipe_id)` **once**. Do **not** call `get_recipe_detail` unless full process prose is specifically requested (`get_recipe_ingredients` is ~450 tokens vs ~26 KB).
2. **Normalize ingredient needs**:
   - Keep the `#n` row numbers from `get_recipe_ingredients`.
   - Sum duplicate ingredients across additions to get the total required amount per ingredient (e.g., `Centennial` 6 g @ 30 min + 6 g @ 5 min = 12 g total), while noting which additions are bittering (`Boil`, `>= 15 min`) vs aroma (`< 15 min`).
   - If the user requested a custom batch size, scale all ingredient amounts by `target_batch_size / recipe_batch_size`.
3. **Check Brewfather inventory**:
   - Call `list_fermentables`, `list_hops`, `list_yeasts`, and `list_misc_items`.
   - When an inventory item is a candidate match for a recipe fermentable or yeast and you need its colour (`color`), supplier, or temperature/attenuation to verify Tier 1 vs Tier 2 tolerances, call `get_fermentable_detail` or `get_yeast_detail` on that candidate ID only.
   - Match each recipe ingredient against inventory using the **Tier 0–2 ladder** from `ingredient-substitution`:
     - **Covered (`have >= need`)**: Inventory covers the full amount.
     - **Partial (`0 < have < need`)**: Inventory covers part; shortage is `need - have`.
     - **Missing (`have == 0`)**: Full amount needed from bruve.lv.
4. **Check bruve.lv for missing, partial, and multi-option Tier 1 items**:
   - Call `bruve_overview()` at most once per conversation if you need catalogue stats.
   - Call **one batched `bruve_lookup(queries=[...])`** containing all missing/partial ingredient names **plus** any Tier 1 category ingredients where you should check if multiple good options exist across inventory and shop (e.g., `Pilsner`).
   - For any `none` or loose `~` result in `bruve_lookup`:
     - Check `.github/skills/ingredient-substitution/knowledge/{malt,hop,yeast,misc}.md` with `search` (grep) for synonyms and Tier 3 equivalents.
     - Run targeted `bruve_search` calls (using `kind`, `ebc_min`/`ebc_max`, `alpha_min`/`alpha_max`, or Latvian/English keywords).
5. **Verify live stock, fetch product URLs, and build the shopping list**:
   - Call `bruve_availability(ids=[...])` on the final bruve.lv product IDs to verify live stock and prices.
   - Call `bruve_get(ids=[...], detail="full")` on the shopping list product IDs (and any alternative shop candidates you recommend) to obtain their direct product page URLs (`url: https://bruve.lv/veikals/...`).
   - Call `bruve_shopping_list(lines=[...], links=False)` for the net quantities to buy (`need - have`) and EUR totals. **Never output `?add-to-cart=` links** (they do not work); always give direct product page links so the user can adjust the amount to buy on their own.

## Handling Specific Cases in Scenario 1

- **Multiple Tier 1 candidates (e.g., Pilsner malt)**:
  - Even if Brewfather inventory has enough of a Tier 1 match (e.g., `Latmalt Pilsner`, 4.31 kg), if bruve.lv also stocks other direct pilsner malts (e.g., `BestMalz Pilsen`, `Latmalt Pilsner`), **show all candidates as options** with EBC/SRM, stock, price, and **recommend using the inventory malt**.
- **Tier 2 same-ingredient property differences (e.g., Centennial hop alpha)**:
  - If inventory has the same hop variety at a different alpha acid (e.g., `10% AA` in inventory vs `8.5% AA` in recipe), mark it as covered (`[Tier 2]`), state the alpha difference, and show the rescaled bittering weight (`old_g * old_AA / new_AA`).
- **Missing exact item, Tier 3 substitute in stock at bruve.lv (e.g., Acidulated malt, Carapils)**:
  - State clearly that the exact name is not in inventory or under that exact name at bruve.lv, present the Tier 3 substitute(s) from the knowledge table (`[Tier 3 - close/fair/distant, draft table]`) with the `what changes` explanation, include them in the provisional shopping list (or show their cost), and **ask the user to confirm or offer Scenario 2 (recipe adaptation)**.
- **Not sold / Out of scope (e.g., Raspberries, Irish moss)**:
  - After checking `bruve_lookup` and `bruve_search`, state clearly that the item is **not sold at bruve.lv (or outside the shop's ingredient scope)** and ask the user whether they will source it elsewhere or want an adapted recipe without it. Never guess or invent a product ID.

## Required Output Format

Always **start your answer with the Verdict Line and the Recommended bruve.lv Shopping List**, followed by the deeper review below:

1. **Verdict Line**:
   - One clear sentence: whether the recipe can be brewed immediately from inventory, or how many items need to be bought / confirmed.
2. **Recommended bruve.lv Shopping List (Top of Answer)**:
   - Table with columns: `ID | Product | Needed | Buy | EUR (incl. VAT) | Product Link & Notes (overbuy/stock)`
   - Total cost in EUR incl. VAT and **direct product page URLs** (`https://bruve.lv/veikals/...` from `bruve_get(..., detail="full")`) so the user can open each product page and adjust the quantity on their own. **Never output `?add-to-cart=` links** and never fetch or open shop links yourself.
   - Explicitly note any out-of-scope / non-shop items (e.g., fresh/frozen fruit) right beneath the shopping list.
3. **Ingredient Availability Table (Deeper Review)**:
   - Columns: `# | Ingredient | Needed | Have (BF Inventory) | Verdict & Tier`
   - Include `#n` row numbers, amounts with units (`kg`, `g`, `pkg`, `items`), key specs (`SRM`/`EBC`, `AA%`), and the match tier (`Tier 0 exact`, `Tier 1 direct`, `Tier 2 fuzzy`, `Missing -> buy`, `Missing -> Tier 3 option`, `Not sold at bruve.lv`).
4. **Options, Substitutions & Questions**:
   - Multi-candidate Tier 1 option tables (with recommendation and product page URLs for shop alternatives).
   - Tier 2 property rescale notes (e.g., bittering hop grams adjusted for AA%).
   - Tier 3 curated substitutions with group ID, `close/fair/distant` tag, `draft` notice, `what changes`, and product page URLs.
   - Out-of-scope / unsold items and a single grouped question for the user.

