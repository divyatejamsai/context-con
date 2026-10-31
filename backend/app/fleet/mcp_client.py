"""A minimal MCP stdio client for Countersign: spawns backend/mcp_server.py and speaks JSON-RPC 2.0 to it.

The fleet agents use this, and only this, to reach Countersign, the same way an outside agent (Claude Code,
another company's bot) would. Agents sign locally; only signatures cross the wire.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


class McpError(RuntimeError):
    pass


class CountersignMCP:
    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc, self.n = proc, 0
        self.server: dict = {}
        self.tools: list[str] = []

    @classmethod
    async def start(cls, env: dict | None = None) -> "CountersignMCP":
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(BACKEND / "mcp_server.py"), cwd=str(BACKEND),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, env=env or os.environ.copy(), limit=2**24)
        mcp = cls(proc)
        init = await mcp.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "countersign-fleet", "version": "0.1.0"}})
        mcp.server = init.get("serverInfo") or {}
        mcp.tools = [t["name"] for t in (await mcp.call("tools/list"))["tools"]]
        return mcp

    async def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=120)
            if not line:
                raise McpError("Countersign MCP server exited")
            res = json.loads(line)
            if res.get("id") == self.n:
                if "error" in res:
                    raise McpError(str(res["error"]))
                return res["result"]

    async def tool(self, name: str, args: dict) -> dict:
        """Calls a tool and returns its JSON payload (verdict tools lead with a one-line summary)."""
        res = await self.call("tools/call", {"name": name, "arguments": args})
        text = res["content"][0]["text"]
        if res.get("isError"):
            raise McpError(f"{name}: {text}")
        start = text.find("\n\n{")
        start = start + 2 if start >= 0 else text.index("{")
        return json.loads(text[start:])

    async def close(self) -> None:
        if self.proc.stdin and not self.proc.stdin.is_closing():
            self.proc.stdin.close()
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            self.proc.kill()
