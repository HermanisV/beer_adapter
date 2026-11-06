# bruve-mcp: contributor and agent notes

Read-only MCP server for the bruve.lv homebrew shop. It navigates; an orchestrating agent decides. Keep it
that way: no substitution or scoring logic here.

## Commands

- `uv sync --locked --dev` install
- `uv run pytest` all tests (no network; fake shop from `tests/fixtures`)
- `uv run python src/main.py` run the stdio server
- `uv run python scripts/parse_report.py` parse coverage on the live shop
- `uv run python scripts/smoke_live.py` every tool against the live shop (throwaway cache)
- `uv run python scripts/capture_raw.py` then `scripts/capture_fixtures.py` refresh fixtures

## Layout

- `client.py` locked-down HTTP client: allowlisted Store API read paths only, rate limit, backoff
- `sync.py` fetch + normalize the ingredient scope, `CatalogueService` TTL/stale handling
- `store.py` SQLite + FTS5 cache, filters, change log
- `parse/` title and description parsers (`malt.py`, `hop.py`, `yeast.py`, `common.py`), `normalize_product`
- `query.py` FTS match builder and the LV/EN `SYNONYM_GROUPS`
- `format.py` compact output and the `untrusted()` fence, `est_tokens()`
- `shopping.py` pack arithmetic, `links.py` click links (never fetched by the server)
- `server.py` the seven tools; instructions text is itself part of the token budget

## Rules

- **Never** request cart, checkout, account, admin or `add-to-cart` URLs. `client.check_request` enforces it and
  `tests/test_tools.py::TestSecurity` asserts it for every tool.
- Shop attributes (`Ebc`, `Alfa Skābe`) are unreliable. Parse from titles and descriptions, store provenance, and use
  `None` when unknown. Never guess a value.
- Merchant descriptions are returned only through `format.untrusted()`.
- Output is a token budget. Add a budget test in `tests/test_tools.py::TestTokenBudgets` for any new tool or
  new output column, and keep rows pipe-separated with the header once.
- Validate every tool argument in `validate.py` before touching the cache or the network.
- Prices are euro cents in the cache; display EUR including VAT.
- Stock: `add_to_cart.maximum` is managed stock, 9999 means unmanaged (`None`). The shop hides out-of-stock products.
- Variation attribute keys are verified: pack size `attribute_pa_iepakojums`, crop year `attribute_gads`. Any other
  attribute makes `links.py` fall back to the product page.
- When parsers change, run `scripts/parse_report.py` and update the coverage table in the README.
