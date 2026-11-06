# Brewfather MCP Server

A Model Context Protocol (MCP) server that integrates with the Brewfather API to provide brewing inventory management and recipe analysis capabilities. This server allows MCP clients like Claude to interact with your Brewfather brewing data.

## Features

- **Inventory Management**: List and manage fermentables, hops, yeasts, and miscellaneous brewing supplies
- **Recipe Analysis**: Access detailed recipe information including ingredients and process details
- **Batch Tracking**: Monitor brewing batches, update measurements, and track progress
- **Brewing Insights**: Get brewing process guidance and sensor readings

## Prerequisites

- Python 3.13 or later
- Brewfather account with API access
- Brewfather API credentials (User ID and API Key)

## Getting Your Brewfather API Credentials

1. Log in to your Brewfather account
2. Navigate to Settings → API keys (older app versions: Settings → Integration)
3. Create an API key and copy the User ID and API Key
4. Select only the scopes you need. Start with the read scopes (`recipes.read`, `inventory.read`, `batches.read`). Add `inventory.write` / `batches.write` only if you enable write tools, and never grant the delete scopes - this server has no delete tools.
5. Keep these credentials secure - you'll need them for configuration

## Installation

Run the server from a local clone and install from the lockfile, so the code and dependencies you reviewed are the ones that run:

```bash
git clone <this-repository-url> brewfather-mcp
cd brewfather-mcp
uv sync --locked
```

Avoid `uvx --from git+...` against a moving branch: it fetches whatever is on the branch at launch time (with your API key in its environment) and resolves dependencies without the lockfile. If you must use it, pin a reviewed commit (`git+https://...@<commit-sha>`).

For debugging, pass `--debug` (saves API responses to a `debug/` folder, see [Debug Mode](#debug-mode)).

## Configuration

### Claude Desktop Configuration

To use this server with Claude Desktop, add the following to your Claude Desktop configuration file:

**Location of config file:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`

**Configuration:**
```json
{
  "mcpServers": {
    "brewfather": {
      "command": "uv",
      "args": [
        "run",
        "--locked",
        "--project",
        "/absolute/path/to/brewfather-mcp",
        "python",
        "/absolute/path/to/brewfather-mcp/src/main.py"
      ],
      "env": {
        "BREWFATHER_API_USER_ID": "your-api-user-id",
        "BREWFATHER_API_KEY": "your-api-key"
      }
    }
  }
}
```

Replace:
- `/absolute/path/to/brewfather-mcp` with the full path to your cloned repository
- `your-api-user-id` with your Brewfather API User ID
- `your-api-key` with your Brewfather API Key

You may also need to provide the full path to the uv command.

#### Other MCP Clients

For other MCP clients that support stdio transport, use:
- **Command**: `uv run --locked --project <path-to-this-repository> python <path-to-this-repository>/src/main.py`
- **Environment Variables**: `BREWFATHER_API_USER_ID` and `BREWFATHER_API_KEY`

### For Local Development & Testing

When developing or testing the server locally, there is the option of providing credentials via a `.env` file instead:
```bash
cp .env.example .env
# Edit .env with your Brewfather API credentials
```

## Security

- **Read-only by default.** The write tools (`update_batch` and the `update_*_inventory` tools) are not registered unless you set `BREWFATHER_ENABLE_WRITES=1`. When enabled they are flagged as non-read-only/destructive so MCP clients can ask for confirmation. Keep per-call approval on for them.
- **Recipe creation has its own switch**, `BREWFATHER_ENABLE_RECIPE_WRITES=1`, which registers only `create_recipe_version`. It creates new recipes and never modifies or deletes existing ones, defaults to a dry run, and needs a key with `recipes.write` (never grant the delete scopes).
- **Validated input.** IDs must match `[A-Za-z0-9_-]{1,64}`, batch status must be a known status, and inventory amounts must be finite and non-negative.
- **Untrusted text.** Free text from Brewfather (notes, descriptions, comments) is returned inside `<untrusted_brewfather_text>` tags and the server instructs the model to treat it as data. This reduces, but does not eliminate, prompt-injection risk.
- **Logging.** Logs go to stderr, not to a file.
- **Network.** The only outbound host is `api.brewfather.app`.
- **HTTP/SSE runner.** Binds to `127.0.0.1` by default, requires a bearer token in `BREWFATHER_MCP_HTTP_TOKEN` (at least 24 characters), and enables Host/Origin (DNS-rebinding) checks. See [HTTP/SSE Server](#httpsse-server).

## Available Tools

The server provides the following MCP tools:

### Inventory Management
- `list_fermentables` - List all fermentables (malts, adjuncts, grains)
- `get_fermentable_detail(identifier)` - Get detailed fermentable information
- `list_hops` - List all hops with properties like alpha acids
- `get_hop_detail(identifier)` - Get detailed hop information
- `list_yeasts` - List all yeasts with attenuation and type
- `get_yeast_detail(identifier)` - Get detailed yeast information
- `list_misc_items` - List miscellaneous brewing supplies
- `get_misc_detail(item_id)` - Get detailed misc item information
- `inventory_summary` - Get comprehensive inventory overview

### Recipe Management
- `list_recipes` - List all recipes
- `get_recipe_detail(recipe_id)` - Get detailed recipe information
- `get_recipe_ingredients(recipe_id)` - Compact numbered table (about 450 tokens instead of the 26 KB raw recipe): header with OG/FG/ABV/IBU/SRM, fermentables, hops, yeasts, miscs, mash and fermentation steps. The `#n` row numbers are the targets for `create_recipe_version`.

### Recipe Creation
Only available when `BREWFATHER_ENABLE_RECIPE_WRITES=1` is set (a separate switch from `BREWFATHER_ENABLE_WRITES`, so recipe creation can be allowed without allowing inventory or batch edits). The API key needs the `recipes.write` scope.

- `create_recipe_version(base_recipe_id, name, edits, notes_append?, dry_run=true)` - Create a **new** recipe derived from an existing one. It never overwrites or deletes: Brewfather's `POST /v2/recipes` always creates a separate recipe.
  - Edits (`op`: `replace` | `resize` | `remove` | `add`; `kind`: `fermentable` | `hop` | `yeast` | `misc`) target an ingredient by name or by `#n` (position in the original list, stable across edits). Replacements copy specs from a Brewfather inventory item (`inventory_id`) and/or explicit `fields`, validated against per-kind whitelists and ranges.
  - Role fields (use, time, temperature, unit) and the amount carry over from the ingredient being replaced. Replacing a **bittering** hop (boil, 15 minutes or more) with a different alpha rescales the grams by the alpha ratio to keep IBU (`keep_ibu`, default on); aroma additions keep their grams.
  - Mash, fermentation, water and equipment profiles are copied unchanged. Server-managed and recalculated fields (`_*`, timestamps, `data`, OG/FG/ABV/IBU/colour, per-ingredient percentages) are stripped from the clone so Brewfather computes them.
  - `dry_run=true` (default) returns the diff and warnings only (large colour or alpha changes, laboratory or form changes). With `dry_run=false` it creates the recipe, reads it back and reports before/after OG, FG, ABV, IBU and SRM, or says honestly that the new recipe is not calculated yet.
  - The model never composes a full recipe: the server clones the original and applies the edits.

### Batch Management
- `list_batches` - List all brewing batches
- `get_batch_detail(batch_id)` - Get detailed batch information
- `update_batch(batch_id, ...)` - Update batch measurements and status
- `get_batch_brewtracker(batch_id)` - Get brewing process guidance
- `get_batch_last_reading(batch_id)` - Get latest sensor readings
- `get_batch_readings_summary(batch_id)` - Get sensor readings summary

### Inventory Updates
These tools are only available when `BREWFATHER_ENABLE_WRITES=1` is set (see [Security](#security)).

- `update_fermentable_inventory(item_id, amount)` - Update fermentable stock
- `update_hop_inventory(item_id, amount)` - Update hop stock  
- `update_yeast_inventory(item_id, amount)` - Update yeast stock
- `update_misc_inventory(item_id, amount)` - Update misc item stock

## Development

### Running Tests
```bash
uv run pytest
```

### Testing the Server Locally

[mcptools](https://github.com/f/mcptools) can be handy for local testing:

```bash
# List available tools
mcpt tools uv run --with 'mcp[cli]' mcp run src/main.py

# Call a specific tool
mcpt call list_inventory_categories uv run --with 'mcp[cli]' mcp run src/main.py
```

### HTTP/SSE Server
Only needed if your MCP client cannot use stdio. It binds to loopback and requires a bearer token:
```bash
export BREWFATHER_MCP_HTTP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
PYTHONPATH=src uv run python src/http_runner.py --port 8000
```
Clients must send `Authorization: Bearer <token>`. To serve other hosts, bind explicitly and list the accepted Host header values, and put TLS in front of it:
```bash
PYTHONPATH=src uv run python src/http_runner.py --host 0.0.0.0 --allowed-host 'mcp.example.com:*'
```

## Troubleshooting

### Common Issues

1. **Import errors**: Make sure you've run `uv sync` to install all dependencies

2. **API authentication errors**: 
   - For MCP clients: Check that credentials are correctly set in your client configuration 
   - For local development: Ensure your `.env` file exists with valid credentials
   - Verify your Brewfather API credentials are correct and have the necessary permissions

3. **Connection timeouts**: Check your internet connection and Brewfather API status

4. **Path issues in Claude Desktop**: Ensure you're using absolute paths in the configuration file

### Debug Mode

Enable debug mode to save API responses into a debug folder for troubleshooting. The files contain your personal Brewfather data, so delete them when done:
```bash
BREWFATHER_MCP_DEBUG=1 mcpt call get_batch_detail --params '{"batch_id": "your-batch-id"}' uv run --with 'mcp[cli]' mcp run src/main.py
```
