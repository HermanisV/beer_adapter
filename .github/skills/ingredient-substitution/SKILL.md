---
name: ingredient-substitution
description: Apply the homebrew ingredient matching and substitution policy (Tier 0-4 ladder, parameter tolerances, role guardrails, curated knowledge lookup, confidence disclosure, and option presentation) across Brewfather inventory and the bruve.lv shop catalogue. Use whenever matching recipe ingredients to inventory or shop items, evaluating substitutes, or preparing user confirmation questions.
---

# Ingredient Matching and Substitution Policy

Match every recipe ingredient against **Brewfather inventory first**, then **bruve.lv stock**, following a strict 5-tier ladder. **The less certain a match, the more you disclose and the more you ask.**

## 1. The Matching Ladder (Tiers 0–4)

| Tier | Name | Meaning | Confidence | Required Handling |
|---|---|---|---|---|
| **0** | **Exact** | Same product, variety, or strain code (e.g., `Centennial` pellets at matching AA, `Fermentis US-05`, `Oats, Flaked`, `WildBrew Philly Sour`). | High | Use silently; list in the summary table. |
| **1** | **Direct category** | Same ingredient category and role, parameters within tolerance (e.g., `Pilsner (Fuglsang)` → `Latmalt Pilsner` or `BestMalz Pilsen`; `Wheat Malt (BestMalz)` → `Latmalt Wheat`). | High | **1 candidate**: apply and list with specs. **2+ good candidates**: show **all** options with specs (EBC/SRM, AA%, lab), source (BF inventory vs bruve.lv), price, stock, and a clear recommendation (preferring inventory when `have >= need`); let the user pick. Never silently pick one. |
| **2** | **Fuzzy same-ingredient** | Same ingredient variety/type, but a key property differs beyond Tier 1 tolerance (e.g., inventory `Centennial` at `10% AA` vs recipe `8.5% AA`; same malt type in a shifted colour band). | Medium | Flag `[Tier 2]`, state the property difference and the adjustment (e.g., bittering hop weight rescaled by `old_AA / new_AA`, or colour shift), and include in the grouped confirmation prompt. |
| **3** | **Curated table** | Equivalence from `knowledge/{malt,hop,yeast,misc}.md` (e.g., `Acidulated` ↔ `Platinum Swaen Sauer-skābais`; `Carapils` ↔ `Platinum Swaen Dextrin` / `BestMalz Caramel Pils`; `US-05` ↔ `WLP001` / `M44`). | Medium (`close`/`fair`) or Low (`distant`) | Flag `[Tier 3 - close/fair/distant, draft table]`, quote the group ID and explain the `what changes` note. Always require user confirmation before writing. |
| **4** | **LLM best guess** | Reasoned from brewing specs when no Tier 0–3 match exists. | Low | Flag `[Tier 4 - best guess]`, explain the reasoning, present 2–3 candidates with trade-offs, and **require explicit confirmation**. Never auto-include. |

## 2. Parameter Tolerances

Convert units before comparing:
- **Colour**: Brewfather recipes report **SRM**; bruve.lv reports **EBC**. Convert via $\text{EBC} = \text{SRM} / 0.508 \approx \text{SRM} \times 1.97$ (and $\text{SRM} = \text{EBC} \times 0.508$).

### Malt & Fermentables
- **Tier 1 colour tolerance**: Within **±20% or ±2 EBC** (whichever is larger, i.e. about ±1 SRM) **and** the **same functional role** (`base`, `caramel`, `roasted`, `wheat`, `rye`, `acidulated`, `flaked`).
- Outside this window for the same malt family is **Tier 2** (or **Tier 3** when crossing sub-families via the knowledge table).

### Hops
- **Bittering additions** (`use = Boil` and `time >= 15 min`):
  - **Tier 1 alpha tolerance**: Within **±2 percentage points AA** for the same variety (or clean bittering family in Tier 3).
  - **Alpha rescaling**: Whenever alpha differs on a bittering addition, rescale weight to preserve IBU:
    $$\text{new\_grams} = \text{old\_grams} \times \frac{\text{old\_alpha}}{\text{new\_alpha}}$$
  - Note: `create_recipe_version` performs this rescale automatically for boil additions $\ge 15\text{ min}$ when `keep_ibu=true` (default).
- **Late, Whirlpool / Aroma, and Dry Hop additions** (`time < 15 min`, `Aroma`, `Whirlpool`, `Dry Hop`):
  - Variety and aroma/oil character matter more than alpha. Keep the same grams unless oil intensity differs markedly, and flag alpha differences as Tier 2 informational notes.

### Yeast
- **Tier 1 / 3 checks**:
  - Must share the same fermentation family (`beer` ale/lager/wheat/sour/kveik vs `wine`/`cider`/`mead`).
  - **Temperature range** must overlap the recipe's fermentation step temperature.
  - **Attenuation** within **±5 percentage points** where known (bruve.lv often omits attenuation; check Brewfather `get_yeast_detail` or recipe specs, and state `att?` if unknown).

## 3. Role & Form Guardrails (Never Cross)

Never cross functional roles, and never propose items in a `never` group as substitutes:
- **Base vs Caramel vs Roasted malts** (`M-GRAIN-NEVER`): Never substitute base malt for caramel or roasted malt even if diluted.
- **Malted vs Unmalted grains** (`M-WHEAT-UNMALTED`, `M-OATMALT`, `M-RYE-FLAKED`): Unmalted flakes lack diastatic enzymes; treat as `distant` (Tier 3) only if the mash has ample base malt.
- **Rice hulls vs Flaked rice** (`M-RICEHULLS`): Rice hulls are an inert lauter aid, never a fermentable adjunct.
- **Lactose vs Fermentable sugars** (`M-LACTOSE`): Lactose is unfermentable milk sugar for sweetness/body; never swap with dextrose/sucrose/honey (`M-HONEY`).
- **DME vs LME** (`M-LME-DME`): Liquid extract is ~80% solids vs ~98% for dry extract; scale weight (`LME ≈ 1.2 × DME`) and confirm.
- **Hop forms** (`H-FORMS`): Never swap T90 pellets, Cryo/lupulin powder (~2× potency), and whole-cone leaf (~10% lower utilization) 1:1 gram-for-gram.
- **Yeast boundaries** (`Y-LOWALC`, `Y-DISTILLERS`, `Y-WINE-BEER-NEVER`): Maltose-negative low-alcohol strains (`LA-01`), turbo/distillers yeast, and wine yeast are never normal substitutes for beer yeast.
- **Water salts & Enzymes** (`X-SALT-CALCIUM`, `X-SALT-MG`, `X-CHALK`, `X-ENZYME`): Gypsum ($\text{SO}_4^{2-}$) and calcium chloride ($\text{Cl}^-$) set opposite flavour profiles; each enzyme targets a different substrate. Never swap.

## 4. Searching the Curated Knowledge Files

The curated equivalence tables live in `.github/skills/ingredient-substitution/knowledge/`:
- `malt.md` (`M-*` groups: malts, adjunct grains, extracts, sugars)
- `hop.md` (`H-*` groups: hop varieties, bittering families, form rules)
- `yeast.md` (`Y-*` groups: ale, lager, wheat, Belgian, saison, kveik, sour, cider, wine, mead strains)
- `misc.md` (`X-*` groups: kettle finings, yeast nutrients, acids, water salts, wood, peel/spices, enzymes, stabilisers)

### How to Search (Token-Efficient)
1. **Never load all four files into context.** Use `search` (grep) case-insensitively for the ingredient name, strain code (`US-05`, `W-34/70`, `WLP001`), or Latvian term (`iesals`, `kviešu`, `skābais`, `apiņi`, `raugs`) in the relevant file.
2. Each line has 5 pipe-separated fields:
   `id | members (; separated) | tier (close/fair/distant/never) | what changes | review (draft/reviewed)`
3. If a line has `tier = never`, treat it as a hard block and cite its explanation.
4. If a line has `tier = close`, `fair`, or `distant`, use its other members as search terms for Brewfather inventory and `bruve_lookup` / `bruve_search`.
5. Because lines are marked `draft`, always tell the user that the match comes from the draft substitution table and include the `what changes` note.

## 5. Handling Out-of-Scope or Unsold Ingredients

- Do **not** claim an ingredient is unavailable at bruve.lv until you have run `bruve_lookup` **and** at least one `bruve_search` (including Latvian/English synonyms or category filters).
- For non-shop or grocery adjuncts (e.g., fresh/frozen fruit like `Raspberry (Fruit)`) or items not currently carried by bruve.lv (e.g., `Irish Moss` when `lookup` and `search` return no kettle fining in stock):
  - State clearly: **"Not sold at bruve.lv (or out of scope for the homebrew ingredient catalogue)."**
  - Ask the user whether to:
    1. Keep the ingredient unchanged in the recipe and buy/source it elsewhere (e.g., grocery store for fruit),
    2. Substitute a Tier 3 equivalent if one is available, or
    3. Omit/remove it from the adapted recipe (e.g., skipping Irish moss).

## 6. Disclosure and Confirmation Rules

- **Unknown specs**: In bruve output, `?` means **unknown**, not zero (`EBC?`, `AA?`, `att?`). State unknowns explicitly; if needed on a finalist, call `bruve_get(ids=[...], detail="full")` to inspect the description excerpt.
- **Single grouped confirmation**: Batch all user choices (multi-option Tier 1 picks, Tier 2 property adjustments, Tier 3/4 substitutions, and out-of-scope item decisions) into **one concise, structured set of questions** before creating or modifying any recipe version.

