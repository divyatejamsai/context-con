"""Countersign MCP server (WS7), stdio transport. Any MCP-capable agent calls Send Guard before it sends.

Run:   cd backend && CRUSTDATA_MODE=replay python mcp_server.py
Claude Code:  claude mcp add countersign -e CRUSTDATA_MODE=replay -- python /abs/path/backend/mcp_server.py

Tools
  verify_agent(passport, scope?)                              -> Verdict  (passport + live sponsor checks)
  check_before_send(passport, signature, to, body, scope)     -> Verdict  (allow / block, every check cited)
  send_message(passport, signature, to, body, scope)          -> {verdict, sent}  (allow -> outbox file; nothing is emailed)
  sign_message(passport, agent_private_key, body)             -> {signature}  (for agents holding their own key)
  ledger_lookup(agent_id?)                                    -> {chain_ok, first_bad_seq, entries}

Plain JSON-RPC 2.0 over newline-delimited stdin/stdout (the MCP stdio transport), so it needs no MCP SDK.
Logs go to stderr; stdout carries protocol messages only.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
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
from app.agents.guard import blocking_reasons, check_send, send_if_allowed  # noqa: E402
from app.agents.models import SCOPES, Passport  # noqa: E402
from app.agents.passport import sign_message, verify_passport  # noqa: E402

SERVER_INFO = {"name": "countersign", "version": "0.1.0"}
PROTOCOL_VERSION = "2025-06-18"

_PASSPORT = {"type": "object", "description": "The agent's Countersign passport (JSON as issued)."}
_TO = {
    "type": "object", "description": "Recipient.",
    "properties": {"name": {"type": "string"}, "profile_url": {"type": "string", "description": "LinkedIn URL"},
                   "company": {"type": "string", "description": "Company the message assumes they work at"}},
    "required": ["profile_url", "company"],
}
_SCOPE = {"type": "string", "enum": list(SCOPES)}
_SEND_ARGS = {
    "type": "object",
    "properties": {"passport": _PASSPORT, "signature": {"type": "string", "description": "sign_message output for this exact body"},
                   "to": _TO, "body": {"type": "string"}, "scope": _SCOPE,
                   "today": {"type": "string", "description": "Optional ISO date override (demos)"}},
    "required": ["passport", "signature", "to", "body", "scope"],
}

TOOLS = [
    {"name": "verify_agent",
     "description": "Check an agent's passport: Countersign signature, expiry, revocation, and live Crustdata checks that the "
                    "human sponsor exists, still works at the company, and holds a title that can grant the scope.",
     "inputSchema": {"type": "object", "properties": {"passport": _PASSPORT, "scope": _SCOPE}, "required": ["passport"]}},
    {"name": "check_before_send",
     "description": "Call before sending any outbound message. Returns decision allow/block with every check and its "
                    "Crustdata source: passport, message signature, recipient still at the company, and each factual claim "
                    "the draft makes about the recipient. Do not send when the decision is block.",
     "inputSchema": _SEND_ARGS},
    {"name": "send_message",
     "description": "Guarded send: runs check_before_send and, only on allow, writes the message to the outbox. Never emails.",
     "inputSchema": _SEND_ARGS},
    {"name": "sign_message",
     "description": "Sign a message body with the agent's private key (base64), binding it to the passport.",
     "inputSchema": {"type": "object", "properties": {"passport": _PASSPORT, "agent_private_key": {"type": "string"},
                                                       "body": {"type": "string"}},
                     "required": ["passport", "agent_private_key", "body"]}},
    {"name": "ledger_lookup",
     "description": "Read the tamper-evident Countersign ledger (optionally for one agent) and whether the hash chain is intact.",
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


async def call_tool(name: str, args: dict) -> tuple[str, bool]:
    """Returns (text, is_error)."""
    if name == "verify_agent":
        v = await verify_passport(Passport.model_validate(args["passport"]), scope=args.get("scope"), graph=_graph())
        return _verdict_text(v), False
    if name in ("check_before_send", "send_message"):
        p = Passport.model_validate(args["passport"])
        kw = dict(today=_today(args), graph=_graph())
        if name == "check_before_send":
            v = await check_send(p, args["signature"], args["to"], args["body"], args["scope"], **kw)
            return _verdict_text(v), False
        v, sent = await send_if_allowed(p, args["signature"], args["to"], args["body"], args["scope"], **kw)
        return ("SENT to outbox. " if sent else "NOT SENT. ") + _verdict_text(v, {"sent": sent}), False
    if name == "sign_message":
        sig = sign_message(Passport.model_validate(args["passport"]), base64.b64decode(args["agent_private_key"]), args["body"])
        return json.dumps({"signature": sig}), False
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
