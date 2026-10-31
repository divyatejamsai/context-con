"""An agent calling Agaxes's Send Guard over MCP, end to end (no shortcuts into the Python API).

1. Onboards an AI employee in the registry (same store the backend and console use).
2. Starts backend/mcp_server.py as a subprocess and speaks MCP JSON-RPC to it over stdio:
   initialize -> tools/list -> check_before_send by agent_id (clean draft, false claim) -> ledger_lookup.
   The agent signs each body locally with its own key; the key never crosses the wire.
3. Exits 1 if the guard doesn't allow the clean draft and block the false one.

    cd backend && CRUSTDATA_MODE=replay LLM_MODE=mock python scripts/mcp_agent_demo.py        # offline, fixtures
    cd backend && CRUSTDATA_MODE=cache python scripts/mcp_agent_demo.py                       # live Crustdata + Gemini

By default it uses a throwaway store; pass --store backend/data to use the real one (the console then shows the agent).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

VINOD = {"name": "Vinod Sonagara", "profile_url": "https://www.linkedin.com/in/vinod-sonagara", "company": "Fam"}
DRAFTS = [("clean", "Hi Vinod, your work at Fam caught our eye. Open to a chat about a backend role?", "allow"),
          ("false claim", "Hi Vinod, congrats on 5 years at Fam! Open to a chat?", "block")]


class Mcp:
    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc, self.n = proc, 0

    async def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        self.proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n").encode())
        await self.proc.stdin.drain()
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=90)
            if not line:
                raise RuntimeError("MCP server exited")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    async def tool(self, name: str, args: dict) -> dict:
        res = await self.call("tools/call", {"name": name, "arguments": args})
        text = res["content"][0]["text"]
        if res.get("isError"):
            raise RuntimeError(f"{name}: {text}")
        return json.loads(text[text.index("{"):])  # verdicts start with a one-line summary


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", help="directory for agents.json / ledger.jsonl / issuer key (default: temp dir)")
    args = ap.parse_args()
    store = Path(args.store) if args.store else Path(tempfile.mkdtemp())
    store.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("AGENTS_PATH", str(store / "agents.json"))
    os.environ.setdefault("LEDGER_PATH", str(store / "ledger.jsonl"))
    os.environ.setdefault("ISSUER_KEY_PATH", str(store / "issuer_ed25519.key"))
    os.environ.setdefault("OUTBOX_PATH", str(store / "outbox.jsonl"))
    os.environ.setdefault("CRUSTDATA_MODE", "replay")

    from app.agents import registry
    from app.agents.models import Sponsor

    sc = {s["id"]: s for s in json.loads((BACKEND.parent / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
    agent = registry.onboard("Sourced (MCP)", "recruiter", Sponsor(**sc["authorised_founder"]["sponsor"]))
    from app.agents.models import Passport
    from app.agents.passport import sign_message
    passport, key = Passport.model_validate(agent["passport"]), registry.private_key(agent["agent_id"])
    print(f"onboarded {agent['name']} {agent['agent_id']} under {agent['passport']['sponsor']['name']}")

    proc = await asyncio.create_subprocess_exec(sys.executable, str(BACKEND / "mcp_server.py"), cwd=str(BACKEND),
                                                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                env=os.environ.copy())
    mcp, ok = Mcp(proc), True
    try:
        init = await mcp.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "mcp_agent_demo", "version": "0"}})
        tools = [t["name"] for t in (await mcp.call("tools/list"))["tools"]]
        print(f"MCP server {init['serverInfo']['name']} {init['serverInfo']['version']}: tools {tools}")
        ok &= "sign_message" not in tools
        for label, body, expect in DRAFTS:
            sig = sign_message(passport, key, body)  # local: only the signature goes to the server
            v = await mcp.tool("check_before_send", {"agent_id": agent["agent_id"], "signature": sig, "to": VINOD,
                                                      "body": body, "scope": "outreach.hiring", "today": "2026-10-31"})
            print(f"\n[{label}] \"{body}\"\n  -> {v['decision'].upper()} (expected {expect.upper()})")
            for c in v["checks"]:
                if c["status"] != "pass" or c["name"] in ("recipient_still_at_company", "claims_in_body_true"):
                    print(f"     {c['status']:>12}  {c['name']}: {c['detail']}")
            ok &= v["decision"] == expect
        led = await mcp.tool("ledger_lookup", {"agent_id": agent["agent_id"]})
        print(f"\nledger: chain_ok={led['chain_ok']}, {len(led['entries'])} entries for this agent: "
              f"{[e['kind'] for e in led['entries']]}")
        ok &= bool(led["chain_ok"])
    finally:
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
