"""What every fleet agent shares: its identity, its Crustdata access, and its three calls to Countersign over MCP.

    clock_in(scope)            verify_agent: passport + live sponsor checks before the agent does any work
    send(to, body, scope)      signs locally, then send_message: Send Guard decides, allowed mail goes to the outbox
    file(kind, summary, ...)   signs locally, then record_work: the finished work and its sources go on the ledger
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from ..agents.graph import Graph
from ..agents.models import Passport
from ..agents.passport import sign_message
from ..schemas import Source
from .mcp_client import CountersignMCP


def work_body(kind: str, summary: str, details: dict | None) -> str:
    from ..agents.ledger import canonical  # same canonical form mcp_server.work_body uses
    return canonical({"kind": kind, "summary": summary, "details": details or {}})


def blocked_by(v: dict) -> list[str]:
    return [f"{c['name']}: {c['detail']}" for c in v.get("checks", []) if c.get("status") != "pass"]


@dataclass
class Report:
    """What one agent did in one run. expected/ok let the fleet script and the tests check the outcome."""
    agent: str
    job: str
    lines: list[str] = field(default_factory=list)
    allowed: int = 0
    blocked: int = 0
    filed: list[str] = field(default_factory=list)       # ledger entry hashes of filed work
    artifacts: list[str] = field(default_factory=list)   # files written (briefs, reports)
    refused_at_clock_in: bool = False
    ok: bool = True
    expected: str = ""
    vendor: dict | None = None                           # Diligence: the vendor it researched


@dataclass
class Ctx:
    mcp: CountersignMCP
    agent: dict                      # public registry record
    key: bytes                       # the agent's own private key (stays in this process)
    client: Any                      # CrustdataClient, or None
    out_dir: Path
    today: date | None = None
    say: Callable[[str], None] = print
    report: Report | None = None
    emit: Callable[[dict], None] | None = None   # structured events for the demo stream (verdict, filed)

    @property
    def agent_id(self) -> str:
        return self.agent["agent_id"]

    @property
    def passport(self) -> Passport:
        return Passport.model_validate(self.agent["passport"])

    @property
    def graph(self) -> Graph:
        return Graph(self.client)

    def log(self, line: str) -> None:
        self.say(line)
        if self.report is not None:
            self.report.lines.append(line)

    def _emit(self, ev: dict) -> None:
        if self.emit is not None:
            self.emit({"agent": self.agent["name"], "agent_id": self.agent_id, **ev})

    def _verdict(self, action: str, v: dict, headline: str, to: dict | None = None) -> None:
        self._emit({"type": "verdict", "action": action, "decision": v.get("decision"), "headline": headline,
                    "to": to, "sent": v.get("sent"), "checks": v.get("checks", []), "ledger_entry": v.get("ledger_entry")})

    def _today(self) -> dict:
        return {"today": self.today.isoformat()} if self.today else {}

    async def clock_in(self, scope: str = "data.read") -> bool:
        v = await self.mcp.tool("verify_agent", {"agent_id": self.agent_id, "scope": scope})
        if v["decision"] == "allow":
            s = self.passport.sponsor
            self.log(f"  clock-in  ALLOW  passport valid, acting for {s.name} ({s.title}, {s.company})")
            self._verdict("clock_in", v, f"Passport valid: acting for {s.name} ({s.title}, {s.company})")
            return True
        self.log(f"  clock-in  BLOCK  {'; '.join(blocked_by(v))}")
        self._verdict("clock_in", v, f"Refused to start work: {blocked_by(v)[0] if blocked_by(v) else 'blocked'}")
        if self.report is not None:
            self.report.refused_at_clock_in = True
        return False

    async def send(self, to: dict, body: str, scope: str) -> dict:
        sig = sign_message(self.passport, self.key, body)
        self._emit({"type": "draft", "to": to, "scope": scope, "body": body})
        v = await self.mcp.tool("send_message", {"agent_id": self.agent_id, "signature": sig, "to": to, "body": body,
                                                 "scope": scope, **self._today()})
        who = f"{to.get('name')} ({to.get('company')})"
        if v.get("sent"):
            self.log(f"  send      ALLOW  {who}: cleared and written to the outbox (never emailed)")
            self._verdict("send", v, f"Cleared to send to {who}", to)
            if self.report is not None:
                self.report.allowed += 1
        else:
            self.log(f"  send      BLOCK  {who}: {'; '.join(blocked_by(v)) or v['decision']}")
            self._verdict("send", v, f"Blocked message to {who}: {blocked_by(v)[0] if blocked_by(v) else 'blocked'}", to)
            if self.report is not None:
                self.report.blocked += 1
        return v

    async def file(self, kind: str, summary: str, details: dict | None = None,
                   sources: list[Source | dict] | None = None) -> dict:
        details = details or {}
        srcs = [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in sources or []]
        srcs = [{k: v for k, v in s.items() if v is not None} for s in srcs if s.get("endpoint")]
        sig = sign_message(self.passport, self.key, work_body(kind, summary, details))
        res = await self.mcp.tool("record_work", {"agent_id": self.agent_id, "signature": sig, "kind": kind,
                                                  "summary": summary, "details": details, "sources": srcs})
        if res.get("recorded"):
            self.log(f"  file      OK     work.{kind} on the ledger ({res['sources']} sources): {summary}")
            self._emit({"type": "filed", "kind": f"work.{kind}", "summary": summary, "ledger_entry": res["ledger_entry"],
                        "sources": srcs})
            if self.report is not None:
                self.report.filed.append(res["ledger_entry"])
        else:
            self.log(f"  file      REFUSED {', '.join(res.get('refused', []))}")
        return res


def llm_live() -> bool:
    return os.getenv("LLM_MODE", "live").lower() != "mock"


def src_dict(rec: dict | None, field_path: str | None = None) -> dict | None:
    """A Source for a Crustdata record we read, from the record's own _source when it has one."""
    if not rec:
        return None
    s = rec.get("_source") or {}
    return {"endpoint": s.get("endpoint") or "crustdata", "field": field_path, "url": s.get("url")}
