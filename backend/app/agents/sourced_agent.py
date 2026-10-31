"""Sourced, AI employee #1, sending its outreach through Send Guard over MCP.

Sourced (the hiring pipeline) only drafts. This is the step after it: for each shortlisted candidate, Sourced signs
its draft with its own passport key and calls the Countersign MCP server's `send_message` tool, the same way any
third-party agent would. Allowed drafts land in the outbox; blocked ones come back with cited reasons.

    cd backend
    python -m app.agents.sourced_agent "senior backend engineer, payments, bangalore"   # live pipeline, then guarded send
    python -m app.agents.sourced_agent --from-run ../my_run.jsonl                       # a saved /api/run event stream
    python -m app.agents.sourced_agent --fixture-people                                 # offline: drafts for the fixture people

Identity: the registry's active agent named "Sourced" (WS8, registry.py) when it exists; otherwise a local passport
in backend/data/sourced_identity.json, sponsored by SOURCED_SPONSOR_JSON (a Sponsor as JSON) or the demo founder.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from ..schemas import Candidate, Criteria
from .models import Passport, Sponsor
from .passport import issue_passport, sign_message

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
IDENTITY_PATH = Path(os.getenv("SOURCED_IDENTITY_PATH", BACKEND / "data" / "sourced_identity.json"))


# ---- identity ------------------------------------------------------------------------------

def identity() -> tuple[Passport, bytes, str]:
    """(passport, private key, where it came from). The key stays in this process: Sourced signs locally."""
    try:
        from . import registry  # WS8

        for a in registry.list_agents():
            p = a.get("passport") or {}
            if p.get("agent_name", "").lower() == "sourced" and a.get("status") == "active":
                return Passport.model_validate(p), registry.private_key(p["agent_id"]), "registry"
    except ImportError:
        pass
    if IDENTITY_PATH.exists():
        d = json.loads(IDENTITY_PATH.read_text())
        return Passport.model_validate(d["passport"]), base64.b64decode(d["private_key"]), str(IDENTITY_PATH)
    raw = os.getenv("SOURCED_SPONSOR_JSON")
    if raw:
        sponsor = Sponsor.model_validate_json(raw)
    else:
        sc = json.loads((ROOT / "fixtures/countersign/sponsors.json").read_text())["scenarios"]
        sponsor = Sponsor(**next(s for s in sc if s["id"] == "authorised_founder")["sponsor"])
    p, key = issue_passport("Sourced", "AI Recruiter", sponsor, ["outreach.hiring", "data.read"])
    IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_PATH.write_text(json.dumps({"passport": p.model_dump(), "private_key": base64.b64encode(key).decode()}, indent=2))
    return p, key, f"new passport in {IDENTITY_PATH}"


# ---- MCP client (stdio, JSON-RPC 2.0) ------------------------------------------------------

class MCPClient:
    """Spawns an MCP server over stdio and calls its tools. Enough of the protocol for tools/list and tools/call."""

    def __init__(self, cmd: list[str] | None = None, env: dict | None = None):
        self.cmd = cmd or [sys.executable, str(BACKEND / "mcp_server.py")]
        self.env = {**os.environ, **(env or {})}
        self._id = 0
        self.proc: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> "MCPClient":
        self.proc = await asyncio.create_subprocess_exec(*self.cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.DEVNULL, env=self.env, limit=2**24)
        init = await self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "sourced", "version": "0.1.0"}})
        self.server = init.get("serverInfo", {})
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    async def __aexit__(self, *exc) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                self.proc.kill()

    async def _send(self, msg: dict) -> None:
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        mid = self._id
        await self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=float(os.getenv("MCP_CALL_TIMEOUT", "120")))
            if not line:
                raise RuntimeError("MCP server exited")
            msg = json.loads(line)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg["result"]

    async def list_tools(self) -> list[str]:
        return [t["name"] for t in (await self._rpc("tools/list", {}))["tools"]]

    async def call(self, name: str, args: dict) -> tuple[str, bool]:
        r = await self._rpc("tools/call", {"name": name, "arguments": args})
        return "".join(c.get("text", "") for c in r.get("content", [])), bool(r.get("isError"))


def _verdict(text: str) -> dict:
    """The tool text is 'SENT/NOT SENT. ALLOW|BLOCK: reasons' then the verdict JSON."""
    i = text.find("{")
    return json.loads(text[i:]) if i >= 0 else {}


# ---- candidates ----------------------------------------------------------------------------

async def candidates_live(brief: str) -> list[Candidate]:
    from ..orchestrator import run

    out: list[Candidate] = []
    async for ev in run(brief):
        if ev.type == "candidate":
            out.append(ev.candidate)
        elif ev.type == "error":
            print(f"  pipeline: {ev.message}")
    return out


def candidates_from_run(path: str) -> list[Candidate]:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    return [Candidate.model_validate(r["candidate"]) for r in rows if r.get("type") == "candidate"]


async def candidates_fixture_people(today: date | None = None) -> list[Candidate]:
    """Offline: real fixture people through the real verifier and Sourced's own outreach drafter."""
    from ..outreach import draft_outreach
    from ..verify.profile import load_person
    from ..verify.verifier import verify_candidate
    from .graph import Graph

    crit = Criteria(role="Senior Backend Engineer", skills=["Python"], locations=["Bengaluru"])
    out = []
    for url, rec in Graph(None, mode="replay")._fx().items():
        pr = load_person(rec)
        claims, flags = await verify_candidate(rec, None, crit, None, today=today)
        cur = pr.current[0] if pr.current else None
        c = Candidate(id=url.rsplit("/", 1)[-1], name=pr.name or "", title=cur.title if cur else None,
                      company=cur.company if cur else None, location=pr.location, profile_url=pr.profile_url,
                      claims=claims, flags=flags)
        c.outreach_draft = await draft_outreach(c, crit)
        out.append(c)
    return out


# ---- the guarded send ----------------------------------------------------------------------

async def send_all(cands: list[Candidate], *, today: date | None = None, mcp: MCPClient | None = None) -> list[dict]:
    p, key, where = identity()
    results = []
    async with (mcp or MCPClient()) as client:
        tools = await client.list_tools()
        assert "send_message" in tools, f"MCP server has no send_message tool: {tools}"
        for c in cands:
            if not c.outreach_draft:
                continue
            to = {"name": c.name, "profile_url": c.profile_url, "company": c.company}
            who = {"agent_id": p.agent_id} if where == "registry" else {"passport": p.model_dump()}  # never the key
            args = {**who, "signature": sign_message(p, key, c.outreach_draft), "to": to,
                    "body": c.outreach_draft, "scope": "outreach.hiring"}
            if today:
                args["today"] = today.isoformat()
            text, err = await client.call("send_message", args)
            v = _verdict(text) if not err else {}
            results.append({"candidate": c.name, "company": c.company, "sent": text.startswith("SENT"), "error": text if err else None,
                            "decision": v.get("decision"), "ledger_entry": v.get("ledger_entry"),
                            "not_passing": [f"{k['name']}: {k['detail']}" for k in v.get("checks", []) if k["status"] != "pass"]})
    return results


def _print(results: list[dict], where: str) -> None:
    print(f"\nSourced (passport from {where}) sent {sum(r['sent'] for r in results)}/{len(results)} drafts through Send Guard (MCP)")
    for r in results:
        print(f"\n  {'SENT   ' if r['sent'] else 'BLOCKED'}  {r['candidate']} @ {r['company']}   ledger {(r['ledger_entry'] or '')[:12]}")
        for x in r["not_passing"][:4]:
            print(f"           {x}")
        if r["error"]:
            print(f"           error: {r['error'][:200]}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("brief", nargs="?")
    ap.add_argument("--from-run")
    ap.add_argument("--fixture-people", action="store_true")
    ap.add_argument("--today")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else None
    if a.from_run:
        cands = candidates_from_run(a.from_run)
    elif a.fixture_people:
        cands = await candidates_fixture_people(today)
    elif a.brief:
        cands = await candidates_live(a.brief)
    else:
        ap.error("give a brief, --from-run or --fixture-people")
    _, _, where = identity()
    _print(await send_all(cands, today=today), where)


if __name__ == "__main__":
    asyncio.run(main())
