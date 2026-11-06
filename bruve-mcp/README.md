# bruve-mcp

A read-only, token-efficient [MCP](https://modelcontextprotocol.io) server for exploring the
[bruve.lv](https://bruve.lv) homebrew shop: malts, extracts, hops, yeasts and additives, with stock
quantities, prices and ready-to-click links. It is the shop half of a homebrewing assistant; the
Brewfather half is [brewfather-mcp](../brewfather-mcp).

**The server only navigates. It never decides.** An orchestrating agent reads a recipe from Brewfather,
decides what is missing and what could substitute, and uses these tools to look things up, compare and
turn decisions into quantities. No substitution or scoring logic lives here.

## How it works

bruve.lv runs WooCommerce, whose public Store API (`/wp-json/wc/store/v1/products`) needs no login. The
server syncs the ingredient categories (about 255 products, roughly 8 requests) into a local SQLite + FTS5
cache and answers searches from it, so searching costs no network calls and cannot hit rate limits. Only
`bruve_availability` talks to the shop live.

The shop's structured attributes are unreliable (every BestMalz malt claims `Ebc=30`, many hops claim
the same alpha acid). Real values come from **titles and Latvian descriptions** and every parsed value
is a null when unknown, never a guess.

## Tools

All tools are read-only (`readOnlyHint`) except `bruve_refresh`, which only rewrites the local cache.

| Tool | Purpose | Typical output |
|---|---|---|
| `bruve_overview()` | Map of the shop: kinds, labels, EBC/alpha ranges, cache age. Call once first. | about 250 tokens |
| `bruve_lookup(queries[], limit=3, kind?)` | Look up a whole ingredient list at once (Latvian or English; handles `US-05`, `Mittelfrueh`, `wheat malt`). Top matches per name, or `none`. | about 30 tokens per match |
| `bruve_search(q?, kind?, brand?, role?, ebc_min/max?, alpha_min/max?, in_stock, sort, limit, cursor)` | Faceted exploration, for example malts overlapping 2-6 EBC or hops with 10-16% alpha. Unknown values are excluded and counted. | about 25 tokens per row, max 25 rows |
| `bruve_get(ids[], detail=basic\|full)` | Shortlist details. `basic` adds per-pack price and stock; `full` adds url, parse provenance, a 500-char fenced description excerpt. | about 70 / 260 tokens each |
| `bruve_availability(ids[])` | **Live** price and stock (bypasses the cache) and refreshes the cache entry. | about 30 tokens per item |
| `bruve_shopping_list(lines[], links=true)` | Pack arithmetic and cost: malt rounded up to 0.1 kg, cheapest hop pack combination covering the need, yeast sachets, stock shortfall flags, click links. | about 50 tokens per line |
| `bruve_refresh()` | Force a re-sync (automatic every 6 hours). | one line |

Typical flow: `overview` once, `lookup` with every recipe ingredient, `search` to explore substitutes for the
`none` results, `get` on a shortlist, `availability` to confirm, `shopping_list` for quantities.

Output is a compact pipe table with the header printed once: `id|name|kind|spec|EUR|stock`.
`spec` is kind-specific, for example `EBC41-60 caramel`, `AA10-15.4(15.4) T90 USA y2025`,
`Fermentis US-05 dry beer floc:low-medium 15-24C`. `?` means unknown. Prices are EUR including VAT.
Malts are priced per kg, hops per pack (`100g:4.50 500g:20.00`), yeast per sachet.
`stock` is the quantity when the shop manages it (`61.2kg`, `8pk`), otherwise `Y`.

### Things to know

- **The shop lists only in-stock items.** `none` means not sold or currently out of stock.
- **Stock quantities are real** where the shop manages stock (WooCommerce exposes them as
  `add_to_cart.maximum`; 9999 means unmanaged). The shopping list flags shortfalls when it knows them.
- **Merchant text is untrusted.** Descriptions are returned only inside
  `<untrusted_bruve_text>` tags, and the server instructions tell the model never to follow
  instructions found in them. Product names appear unfenced (short, catalogue-constrained).
- **Links are for you to click.** Add-to-cart links add one product per click; WooCommerce has no
  multi-item cart link. The server itself never requests them.

## Install and run

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). Run from a local clone with the lockfile:

```bash
uv sync --locked
uv run --locked python src/main.py     # stdio server
```

VS Code (`.vscode/mcp.json`), without needing `uv` on PATH once the environment is synced:

```json
{
  "servers": {
    "bruve": {
      "type": "stdio",
      "command": "${workspaceFolder}/bruve-mcp/.venv/Scripts/python.exe",
      "args": ["${workspaceFolder}/bruve-mcp/src/main.py"]
    }
  }
}
```

No credentials are needed. Optional environment variables (see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `BRUVE_MCP_CACHE_DIR` | `%LOCALAPPDATA%\bruve-mcp` | Where the SQLite cache lives |
| `BRUVE_MCP_TTL_HOURS` | `6` | Hours before the catalogue is re-synced |

The first tool call after the cache is missing or stale syncs (a few seconds). If a refresh fails the stale
cache is still served and the output starts with a `NOTE:` line.

## Contract with the Brewfather side

| Brewfather | bruve-mcp | Notes |
|---|---|---|
| Fermentable `color` (SRM) | `EBCa-b` | SRM = EBC x 0.508 (EBC = SRM / 0.508). Compare ranges, not points. |
| Fermentable amount (kg) | malt/flake price per kg | Shopping list rounds up to 0.1 kg. |
| Hop `alpha` (%) | `AAa-b(typical)` | Quoted crop value is the typical value; unknown hops show `AA?`. |
| Hop amount (g) | pack sizes `100g:`, `500g:` | Packs vary in crop year (`y2025`); the list picks the cheapest combination. |
| Yeast `laboratory`, `productId` | `lab`, `code` | Search by code (`US-05`, `WLP001`) or name. |
| Yeast `form`, `attenuation`, `flocculation`, `minTemp`/`maxTemp` | `dry/liquid`, `att`, `floc`, `C` range | Many descriptions lack attenuation (see coverage). |
| Yeast amount (packages) | `pk` | Pack grams are in the name or `bruve_get`. |
| Misc (nutrient, finings, acids, sugars) | kinds `nutrient`, `fining`, `acid`, `sugar`, `additive`, ... | Search by English or Latvian name. |

## Parse coverage on the live catalogue

Measured with `uv run python scripts/parse_report.py` (255 products, in-stock catalogue):

| Kind | Count | Parsed |
|---|---|---|
| malt | 60 | EBC 60/60, role 60/60 |
| hop | 45 | alpha 42/45, form 45/45, origin 45/45 |
| yeast | 71 | lab 70/71, form 71/71 (partly inferred), code 29/71, flocculation 35/71, temperature 55/71, alcohol tolerance 39/71, attenuation 5/71 |
| extract | 13 | pack 12/13, colour 1/13 |

Yeast strain codes only exist for products that have them in the title (Fermentis, White Labs, Mangrove
Jack's, Lalvin); `lalbrew`-style strains are found by name. Prefer Brewfather's own yeast data for
attenuation and use bruve data for availability, form and temperature.

## Safety

- Only `https://bruve.lv` Store API product read endpoints are reachable (`client.check_request`).
  Cart, checkout, account, admin and any `add-to-cart`/nonce parameters are refused before a request is made.
- Rate limited (about 2 requests per second, 2 concurrent), exponential backoff, honours `Retry-After`.
- Inputs are validated (numeric ids, enums, finite ranges, capped limits, cursor format); FTS queries are
  built from sanitized words only.
- Logs go to stderr; no credentials exist.

## Development

```bash
uv sync --locked --dev
uv run pytest                              # 171 tests, no network (fake shop from tests/fixtures)
uv run python scripts/capture_raw.py       # fetch the live catalogue into debug/ (git-ignored)
uv run python scripts/capture_fixtures.py  # rebuild tests/fixtures from debug/
uv run python scripts/parse_report.py      # parse coverage on the live shop
uv run python scripts/smoke_live.py        # run every tool against the live shop with a throwaway cache
uv run python scripts/stdio_check.py       # real MCP stdio session: tool list sizes and two live calls
```

Tests include golden **token budgets** per tool so output bloat fails CI. When a real ingredient name fails to
match, add a word group to `SYNONYM_GROUPS` in `src/bruve_mcp/query.py`.

The fixtures are a slice of the public bruve.lv catalogue used for testing only. The shop's API is public but
unofficial; keep usage light and consider asking the shop for a sanctioned feed if you depend on this.

## Skills

`.github/skills/bruve-shop-explorer` teaches an agent how to explore efficiently, and
`.github/skills/bruve-shopping-list` how to turn decisions into an order.
