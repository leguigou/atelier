#!/usr/bin/env python3
"""Test client MCP : parle à atelier_mcp.py comme le ferait un agent.

Run : python3 test_mcp_client.py [outil] ['{"param": "valeur"}']

Il faut un interpréteur qui possède le paquet `mcp` (pip install mcp).
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atelier_mcp.py")


async def main():
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print("initialize ->", info.serverInfo.name, info.serverInfo.version,
                  "| protocole", info.protocolVersion)
            tools = await session.list_tools()
            print("tools/list ->", len(tools.tools), "outils")
            for tool in tools.tools:
                print("   -", tool.name)
            if len(sys.argv) > 1:
                name = sys.argv[1]
                args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
                result = await session.call_tool(name, args)
                print("\ncall_tool(%s, %s) isError=%s" % (name, args, result.isError))
                for block in result.content:
                    print(block.text[:2000])


asyncio.run(main())
