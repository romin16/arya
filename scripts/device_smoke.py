"""Manual, opt-in smoke client for the local ARYA device MCP server."""
from __future__ import annotations

import argparse
import asyncio
import json
import os

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--call", help="Optional MCP tool name to invoke (may affect the desktop).")
    parser.add_argument("--args", default="{}", help='JSON object of tool arguments, for example \'{"app":"notepad"}\'.')
    parser.add_argument("--panic", action="store_true", help="Call the protected POST /panic endpoint.")
    return parser.parse_args()


async def main(options: argparse.Namespace) -> None:
    load_dotenv()
    token = os.getenv("DEVICE_TOKEN", "")
    if not token:
        raise SystemExit("DEVICE_TOKEN is required in .env")
    headers = {"Authorization": f"Bearer {token}"}
    base_url = "http://127.0.0.1:5002"

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=10) as http:
        health = await http.get("/health")
        health.raise_for_status()
        print("health:", health.json())
        if options.panic:
            response = await http.post("/panic")
            response.raise_for_status()
            print("panic:", response.json())

    async with streamablehttp_client(f"{base_url}/mcp", headers=headers) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", ", ".join(tool.name for tool in tools.tools))
            if options.call:
                arguments = json.loads(options.args)
                if not isinstance(arguments, dict):
                    raise SystemExit("--args must decode to a JSON object")
                result = await session.call_tool(options.call, arguments)
                print("result:", result)


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
