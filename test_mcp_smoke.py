"""Smoke test: connect to mcp-anydesk via MCP stdio, list tools, call safe read-only tools."""
import asyncio
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = r"C:\Users\juanp_8h8f07l\dev\mcp-anydesk"
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")


async def call(session, name, args=None):
    try:
        res = await session.call_tool(name, args or {})
        texts = [c.text for c in res.content if getattr(c, "text", None)]
        return {"isError": res.isError, "text": "\n".join(texts)}
    except Exception as e:
        return {"exception": repr(e)[:300]}


async def main():
    params = StdioServerParameters(command=PY, args=["-m", "mcp_anydesk_server"], cwd=REPO)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("SERVER:", init.serverInfo.name, "| protocol:", init.protocolVersion)
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"TOOLS({len(names)}):", ", ".join(names))

            for n in ["get_version", "get_system_status", "list_recipes",
                      "list_sessions", "check_health", "select_anydesk_window"]:
                r = await call(session, n)
                print(f"\n--- {n} ---")
                print(json.dumps(r, ensure_ascii=False)[:700])

            rr = await call(session, "list_recipes")
            try:
                data = json.loads(rr.get("text", "{}"))
                recipes = data.get("recipes") or data.get("result", {}).get("recipes") or []
                if recipes:
                    first = recipes[0] if isinstance(recipes[0], str) else (recipes[0].get("name") or "")
                    if first:
                        gr = await call(session, "get_recipe", {"name": first})
                        print(f"\n--- get_recipe({first}) ---")
                        print(json.dumps(gr, ensure_ascii=False)[:700])
            except Exception as e:
                print("recipe parse skipped:", repr(e))


asyncio.run(main())
