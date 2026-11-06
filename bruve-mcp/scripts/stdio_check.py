"""Exercise the server over real stdio with the MCP client SDK (same path VS Code uses)."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def main() -> None:
    env = {**os.environ, "BRUVE_MCP_CACHE_DIR": tempfile.mkdtemp(prefix="bruve-stdio-")}
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "src" / "main.py")], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            total = 0
            for tool in tools:
                size = len(json.dumps({"name": tool.name, "description": tool.description, "schema": tool.inputSchema}, ensure_ascii=False))
                total += size
                print(f"{tool.name:22s} {size:5d} chars  readOnly={tool.annotations.readOnlyHint}")
            instructions = init.instructions or ""
            print(f"tool definitions {total} chars (~{total // 3} tokens), instructions {len(instructions)} chars")
            for name, args in (
                ("bruve_overview", {}),
                ("bruve_lookup", {"queries": ["Philly Sour", "Centennial", "Pilsner"], "kind": None}),
            ):
                result = await session.call_tool(name, args)
                print(f"\n## {name} isError={result.isError}")
                print(result.content[0].text)


asyncio.run(main())
