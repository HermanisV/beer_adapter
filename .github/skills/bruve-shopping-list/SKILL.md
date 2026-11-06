---
name: bruve-shopping-list
description: Turn decided ingredient needs into a bruve.lv purchase list with quantities, pack choices, cost, stock warnings and click links, using the bruve MCP shopping tool. Use after choosing which shop products to buy for one or several recipes, when asked "what do I need to buy at bruve", "how much will it cost", or to combine several recipes into one order.
---

# Building a bruve.lv shopping list

`bruve_shopping_list` does **arithmetic only**: it never chooses products or substitutes. Decide the products
first (see `bruve-shop-explorer`), then pass needs in.

## Prepare the lines

Each line is `{id, need, unit, pack?}` where `id` is the bruve product id.

| Product | How to give the need | What the tool does |
|---|---|---|
| Malt, flakes, anything priced per kg | `need` in `kg` or `g` | Rounds **up** to 0.1 kg; flags a shortfall if the shop's known stock is lower |
| Hops (several pack sizes) | `need` in `g` or `kg` | Picks the cheapest combination of in-stock packs that covers the need (stock limits respected) |
| Yeast, nutrients, one sachet type | `need` with `unit="pk"` | Counts packs; `unit="g"` works when the pack size is in the name |
| A specific pack or crop year | `pack="500g"` (or a variation id like `v1005115`) with `unit="pk"` | Buys exactly that pack |

Combine recipes first: **sum needs per product id across all recipes** before calling, so pack rounding happens
once. Convert recipe units to these units (Brewfather: fermentables kg, hops g, yeasts packages).

Subtract what the user already has in Brewfather inventory **before** adding it to the list, and add a safety margin
only if the user asks for one.

## Read the result

```
id|name|buy|EUR|note
total: 42.72 EUR incl. VAT for 8/8 lines
links to click ...
```

- `buy` shows exactly what to purchase (`1.7kg`, `4x100g y2025`, `1x11g`).
- `note` explains overbuy (`400g total, 50g over need`), shortfalls (`short: only 6kg in stock`), or why a line could
  not be planned (`several packs exist: give need in g/kg ...`). Fix the line and call again; do not guess.
- A line with `-` cost was not planned. The total says how many lines were.
- Prices are EUR **including VAT**. Stock quantities are only known where the shop manages stock.

## Confirm before ordering

1. Run `bruve_availability` on the ids in the final list. Prices and stock can change; the list reads the cache.
2. If a line is short, either lower the amount, buy a larger pack, or go back to exploring substitutes for that
   ingredient only.
3. Present the list with the total and the notes. Mention any hop pack overbuy, because small recipes often need
   less than the smallest pack.

## Product Page Links (Do Not Use Add-to-Cart Links)

- **Always start your answer with the recommended shopping list** at the top, followed by the deeper ingredient review below.
- **Do NOT output `?add-to-cart=` links** — WooCommerce add-to-cart URLs do not work reliably for the user, and the user prefers to open each product page and adjust the quantity to buy on their own.
- Call `bruve_shopping_list(lines=[...], links=False)` for the quantity arithmetic and EUR totals, and call `bruve_get(ids=[...], detail="full")` on the shopping list product IDs to retrieve each item's direct product page URL (`url: https://bruve.lv/veikals/...`).
- Present the direct product page URL for every item (plus any recommended alternative products) so the user can click through and build their cart manually.

## Do not

- Do not output `?add-to-cart=` links; always provide direct product page URLs (`https://bruve.lv/veikals/...`).
- Do not invent product ids, URLs, sizes or prices; take them from `lookup`/`search`/`get` output.
- Do not re-run the whole list repeatedly while iterating; adjust only the lines that changed.
- Do not try to open or fetch the links yourself.

