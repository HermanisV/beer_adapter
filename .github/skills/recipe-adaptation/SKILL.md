---
name: recipe-adaptation
description: Adapt an existing Brewfather recipe to use ingredients from the user's Brewfather inventory and in-stock bruve.lv items, preview changes with a dry run, create a new derived recipe version in Brewfather on user approval, report OG/FG/ABV/IBU/SRM deltas, and output the bruve.lv shopping list. Triggers: "adapt recipe X", "create a new version of recipe X from my inventory", "modify recipe X to what I have and what bruve sells".
---

# Recipe Adaptation Workflow (Scenario 2)

Use this workflow when the user wants to adapt a Brewfather recipe to their available inventory and bruve.lv stock, creating a **new derived recipe** in Brewfather (never overwriting the original) plus a shopping list. Follow `ingredient-substitution`, `bruve-shop-explorer`, and `bruve-shopping-list`.

## Step-by-Step Workflow

### Step 1: Inspect Recipe, Inventory & bruve.lv (Shared Steps 1–4)
1. Call `list_recipes` to find the base recipe ID (case- and diacritic-insensitive), then call `get_recipe_ingredients(recipe_id)` **once** to get the compact `#n` numbered ingredient table and original metrics (`OG`, `FG`, `ABV`, `IBU`, `SRM`).
2. Normalize needs (summing duplicate additions for stock comparison while preserving `#n` targets for individual recipe edits).
3. Call `list_fermentables`, `list_hops`, `list_yeasts`, and `list_misc_items` (plus `get_fermentable_detail` / `get_yeast_detail` on matched inventory IDs when colour or attenuation is needed).
4. Call one batched `bruve_lookup(queries=[...])` for all missing/partial items and multi-option Tier 1 categories, followed by knowledge-table `search` (grep in `.github/skills/ingredient-substitution/knowledge/*.md`) and `bruve_search` for any misses.
5. Call `bruve_availability(ids=[...])` on candidate shop products to confirm live stock and pricing.

### Step 2: Build the Substitution Plan & Dry-Run Preview
1. Construct the proposed `edits` list for `create_recipe_version`:
   - Target each ingredient by its `#n` position from `get_recipe_ingredients` (e.g., `#1`, `#2`) so multi-addition hops or partial name matches are unambiguous.
   - **Inventory replacements**: Set `op="replace"`, `kind=...`, `target="#n"`, and `inventory_id="<BF inventory ID>"`. The server automatically copies `name`, `supplier`, `origin`, `color`, `potential`, `alpha`, etc. from the user's Brewfather inventory item.
   - **Shop replacements**: Set `op="replace"`, `kind=...`, `target="#n"`, and `fields={...}`. Convert bruve.lv malt colour from EBC to SRM (`round(ebc * 0.508, 1)`). Include `name`, `supplier` (brand), `color` (SRM), `alpha` (for hops), or `laboratory`/`productId` (for yeast) where known.
   - **Bittering hop alpha rescale**: For bittering hops (`Boil`, `>= 15 min`), keep `keep_ibu=true` (default) so `create_recipe_version` rescales grams by `old_alpha / new_alpha`. For late/aroma hops (`< 15 min`), grams remain unchanged.
   - **Out-of-scope / Unsold items** (e.g., `Raspberry (Fruit)`, `Irish Moss`): Propose keeping grocery/fruit items unchanged (to be bought elsewhere) and ask whether to remove or replace unavailable finings/miscs.
2. If `create_recipe_version` is available, you may run it with `dry_run=true` (default) to verify the diff lines and warnings. **Never pass `dry_run=false` before the user confirms.**

### Step 3: Present Plan & Ask One Grouped Confirmation Question
Present the availability table, all candidate options (Tier 1 multi-option choices like Pilsner), Tier 2 adjustments (like Centennial AA rescale), Tier 3/4 curated substitutions (with group ID, `close/fair/distant` tag, `draft` notice, and `what changes`), and out-of-scope items.

Ask **one grouped confirmation question** covering:
1. Any Tier 1 multi-candidate choice (e.g., "Use inventory Latmalt Pilsner (recommended) or buy BestMalz Pilsen / Latmalt Pilsner from bruve.lv?"),
2. Every Tier 2, Tier 3, or Tier 4 substitution and any out-of-scope item handling (keep vs remove),
3. Approval to create the new derived recipe in Brewfather (showing the proposed new recipe name, e.g., `<Base Name> (adapted)`).

### Step 4: Create the Derived Recipe Version (Only After Approval)
1. Once the user confirms their choices:
   - Adjust the `edits` list if the user picked a different option.
   - Compose `notes_append` with a concise adaptation log listing each changed ingredient, its tier tag, and the reason/source.
   - Call `create_recipe_version(base_recipe_id=..., name=..., edits=..., notes_append=..., dry_run=false)`.
2. Read the tool output:
   - Report the new recipe name, new recipe ID, and the before → after metric deltas (`OG`, `FG`, `ABV`, `IBU`, `SRM`).
   - If Brewfather returns the recipe without calculated metrics (`new recipe is not calculated yet`), tell the user to open the new recipe in the Brewfather app so Brewfather computes OG/IBU/colour.
3. **Fallback if `create_recipe_version` is not registered or lacks `recipes.write` scope**:
   - Explain clearly that recipe write mode is disabled (`BREWFATHER_ENABLE_RECIPE_WRITES=1` and a key with `recipes.write` are required) and print a clean, copy-ready adapted recipe sheet (ingredients with adjusted weights, SRM/EBC, AA%, and notes) so the user can apply it manually in Brewfather.

### Step 5: Final Shopping List
Call `bruve_get(ids=[...], detail="full")` to get direct product page URLs (`url:`) and `bruve_shopping_list(lines=[...], links=False)` for the confirmed bruve.lv items (after subtracting Brewfather inventory). Present the purchase table with EUR totals (incl. VAT), pack/stock notes, and **direct product page URLs** (`https://bruve.lv/veikals/...`) — never output `?add-to-cart=` links.

## Required Output Format

Always **start your response with the Verdict Line and the Recommended bruve.lv Shopping List**, followed by the deeper review below:
1. **Verdict Line**: Summary of what inventory covers, what is adapted, and how many items to buy at bruve.lv.
2. **Recommended bruve.lv Shopping List (Top of Answer)**: Purchase table from `bruve_shopping_list` (`ID | Product | Needed | Buy | EUR (incl. VAT) | Product Link & Notes`) with direct product page URLs (`https://bruve.lv/veikals/...` from `bruve_get(..., detail="full")`) so the user can adjust quantities on their own. Never output `?add-to-cart=` links.
3. **Ingredient Table (Deeper Review)**: `# | Ingredient | Needed | Have (BF) | Adapted Plan & Tier`.
4. **Substitutions & Confirmation / Dry-Run Diff**: Tier tags, predicted effects (colour, bitterness, flavour), dry-run diff lines, and grouped confirmation question(s).
5. **Created Recipe Summary (after confirmation)**: New recipe name, ID, and `OG | FG | ABV | IBU | SRM` deltas vs the original recipe.

