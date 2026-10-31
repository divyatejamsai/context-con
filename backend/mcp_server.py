"""Agaxes MCP server (WS7), stdio transport. Any MCP-capable agent calls Send Guard before it sends.

Run:   cd backend && CRUSTDATA_MODE=replay python mcp_server.py
Claude Code:  claude mcp add countersign -e CRUSTDATA_MODE=replay -- python /abs/path/backend/mcp_server.py

Tools (identify the agent by agent_id; the server loads its passport from the AI employee registry.
A passport JSON is accepted instead for agents that aren't onboarded here. No tool ever takes a private key:
the agent signs the body itself with passport.sign_message, so the key never crosses the wire.)
  verify_agent(agent_id | passport, scope?)                         -> Verdict  (passport + live sponsor checks)
  check_before_send(agent_id | passport, signature, to, body, scope) -> Verdict  (allow / block, every check cited)
  send_message(agent_id | passport, signature, to, body, scope)      -> {verdict, sent}  (allow -> outbox file; never emailed)
  record_work(agent_id, signature, kind, summary, details?, sources?) -> {recorded, ledger_entry}  (agent-signed work log)
  ledger_lookup(agent_id?)                                          -> {chain_ok, first_bad_seq, entries}

Plain JSON-RPC 2.0 over newline-delimited stdin/stdout (the MCP stdio transport), so it needs no MCP SDK.
Logs go to stderr; stdout carries protocol messages only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "WARNING"), stream=sys.stderr)
log = logging.getLogger("countersign.mcp")

from app.agents import ledger  # noqa: E402
from app.agents.graph import Graph  # noqa: E402
from app.agents.guard import UnknownAgent, blocking_reasons, check_send, resolve_agent, send_if_allowed  # noqa: E402
from app.agents.models import SCOPES, Passport  # noqa: E402
from app.agents.passport import signature_valid, verify_message_signature, verify_passport  # noqa: E402
from app.schemas import Source  # noqa: E402

SERVER_INFO = {"name": "countersign", "version": "0.1.0"}
PROTOCOL_VERSION = "2025-06-18"

_AGENT_ID = {"type": "string", "description": "Your Agaxes agent id (agt_...). The server loads your passport."}
_PASSPORT = {"type": "object", "description": "Only for agents not onboarded here: the Agaxes passport JSON."}
_TO = {
    "type": "object", "description": "Recipient.",
    "properties": {"name": {"type": "string"}, "profile_url": {"type": "string", "description": "LinkedIn URL"},
                   "company": {"type": "string", "description": "Company the message assumes they work at"}},
    "required": ["profile_url", "company"],
}
_SCOPE = {"type": "string", "enum": list(SCOPES)}
_SEND_ARGS = {
    "type": "object",
    "properties": {"agent_id": _AGENT_ID, "passport": _PASSPORT,
                   "signature": {"type": "string", "description": "Your Ed25519 signature of this exact body (passport.sign_message, base64)"},
                   "to": _TO, "body": {"type": "string"}, "scope": _SCOPE,
                   "today": {"type": "string", "description": "Optional ISO date override (demos)"}},
    "required": ["signature", "to", "body", "scope"],
}

TOOLS = [
    {"name": "verify_agent",
     "description": "Check an agent's passport: Agaxes signature, expiry, revocation, and live Crustdata checks that the "
                    "human sponsor exists, still works at the company, and holds a title that can grant the scope.",
     "inputSchema": {"type": "object", "properties": {"agent_id": _AGENT_ID, "passport": _PASSPORT, "scope": _SCOPE}}},
    {"name": "check_before_send",
     "description": "Call before sending any outbound message. Returns decision allow/block with every check and its "
                    "Crustdata source: passport, message signature, recipient still at the company, and each factual claim "
                    "the draft makes about the recipient. Do not send when the decision is block.",
     "inputSchema": _SEND_ARGS},
    {"name": "send_message",
     "description": "Guarded send: runs check_before_send and, only on allow, writes the message to the outbox. Never emails.",
     "inputSchema": _SEND_ARGS},
    {"name": "record_work",
     "description": "File a finished piece of work (a research brief, a batch of resume checks, an outreach run) on the "
                    "tamper-evident ledger with the Crustdata sources behind it. Sign work_body(kind, summary, details) with "
                    "your key. Refused unless the passport is genuine, unrevoked and the agent is active.",
     "inputSchema": {"type": "object", "properties": {
         "agent_id": _AGENT_ID,
         "signature": {"type": "string", "description": "Your Ed25519 signature of work_body(kind, summary, details)"},
         "kind": {"type": "string", "description": "Short slug, e.g. report, resume_check, outreach_run"},
         "summary": {"type": "string"}, "details": {"type": "object"},
         "sources": {"type": "array", "items": {"type": "object", "properties": {
             "endpoint": {"type": "string"}, "field": {"type": "string"}, "url": {"type": "string"}}}}},
         "required": ["agent_id", "signature", "kind", "summary"]}},
    {"name": "ledger_lookup",
     "description": "Read the tamper-evident Agaxes ledger (optionally for one agent) and whether the hash chain is intact.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "kind": {"type": "string"},
                                                       "limit": {"type": "integer", "default": 50}}}},
]

_client: Any = None
_client_tried = False


def _graph() -> Graph:
    global _client, _client_tried
    if not _client_tried:
        _client_tried = True
        try:
            from app.crustdata.client import CrustdataClient

            _client = CrustdataClient(mode=os.getenv("CRUSTDATA_MODE", "cache"))
        except Exception as e:  # noqa: BLE001 - no key: replay fixtures only, live checks become unverifiable
            log.warning("no Crustdata client (%s); serving fixtures only", e)
    return Graph(_client, mode=None if _client else "replay")


def _today(args: dict) -> date | None:
    return date.fromisoformat(args["today"]) if args.get("today") else None


def _verdict_text(v, extra: dict | None = None) -> str:
    head = f"{v.decision.upper()}" + ("" if v.decision == "allow" else ": " + "; ".join(blocking_reasons(v)))
    return head + "\n\n" + json.dumps({**v.model_dump(), **(extra or {})}, indent=2)


def _agent(args: dict) -> tuple[Passport, str | None]:
    """agent_id -> (registry passport, status); else the passport given (status unknown)."""
    if args.get("agent_id"):
        p, status = resolve_agent(args["agent_id"])
        if args.get("passport") and Passport.model_validate(args["passport"]).agent_id != p.agent_id:
            raise UnknownAgent("passport and agent_id name different agents")
        return p, status
    if args.get("passport"):
        return Passport.model_validate(args["passport"]), None
    raise UnknownAgent("send agent_id (or, for agents not onboarded here, passport)")


def work_body(kind: str, summary: str, details: dict | None) -> str:
    """What an agent signs to file work: the canonical JSON of kind, summary and details."""
    return ledger.canonical({"kind": kind, "summary": summary, "details": details or {}})


def _record_work(args: dict) -> tuple[str, bool]:
    p, status = _agent(args)
    kind = re.sub(r"[^a-z0-9_]+", "_", str(args.get("kind") or "").lower()).strip("_") or "note"
    refusals = []
    if status != "active":
        refusals.append(f"agent is {status or 'not onboarded here'}")
    if not signature_valid(p):
        refusals.append("passport signature invalid")
    if ledger.is_revoked(p.agent_id):
        refusals.append("passport revoked")
    if not verify_message_signature(p, work_body(args["kind"], args["summary"], args.get("details")), args.get("signature") or ""):
        refusals.append("work signature does not match this agent's key")
    if refusals:
        return json.dumps({"recorded": False, "refused": refusals}), False
    sources = [Source(**s) for s in args.get("sources") or [] if isinstance(s, dict) and s.get("endpoint")]
    entry = ledger.append(f"work.{kind}", {"agent_id": p.agent_id, "summary": args["summary"],
                                           "details": args.get("details") or {}, "signed": True}, sources[:200])
    return json.dumps({"recorded": True, "ledger_entry": entry, "sources": len(sources)}), False


async def call_tool(name: str, args: dict) -> tuple[str, bool]:
    """Returns (text, is_error)."""
    if name == "verify_agent":
        p, status = _agent(args)
        v = await verify_passport(p, scope=args.get("scope"), graph=_graph())
        return _verdict_text(v, {"registry_status": status}), False
    if name in ("check_before_send", "send_message"):
        p, status = _agent(args)
        kw = dict(today=_today(args), graph=_graph(), agent_status=status)
        if name == "check_before_send":
            v = await check_send(p, args["signature"], args["to"], args["body"], args["scope"], **kw)
            return _verdict_text(v), False
        v, sent = await send_if_allowed(p, args["signature"], args["to"], args["body"], args["scope"], **kw)
        return ("SENT to outbox. " if sent else "NOT SENT. ") + _verdict_text(v, {"sent": sent}), False
    if name == "record_work":
        return _record_work(args)
    if name == "ledger_lookup":
        ok, bad = ledger.verify_chain()
        rows = ledger.entries(args.get("agent_id"), args.get("kind"))[-int(args.get("limit") or 50):]
        return json.dumps({"chain_ok": ok, "first_bad_seq": bad, "entries": rows}, indent=2, default=str), False
    return f"unknown tool {name}", True


async def handle(msg: dict) -> dict | None:
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # notification (initialized, cancelled): no response
        return None
    try:
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                      "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                      "instructions": "Call check_before_send before sending any message on someone's behalf; never send on block."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                text, err = await call_tool(params.get("name", ""), params.get("arguments") or {})
            except Exception as e:  # noqa: BLE001 - bad arguments come back as a tool error the agent can read
                log.exception("tool %s failed", params.get("name"))
                text, err = f"{type(e).__name__}: {e}", True
            result = {"content": [{"type": "text", "text": text}], "isError": err}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    except Exception as e:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


async def serve(stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = await handle(msg)
        if resp is not None:
            stdout.write(json.dumps(resp, default=str) + "\n")
            stdout.flush()


if __name__ == "__main__":
    asyncio.run(serve())
