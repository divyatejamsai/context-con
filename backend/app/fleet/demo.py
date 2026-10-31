"""The guided demo: the fleet's story in seven beats, as one ordered stream of events.

    async for ev in story(DemoOptions(...)):  ...     # scripts/run_fleet.py prints it, /api/demo/run streams it

Beats (BEATS): onboard -> legit work -> sponsor left -> scope refusal -> stale claim -> tampering -> outside agent.
Every agent call goes through the Countersign MCP server; every verdict carries its checks and their sources.

Events (all carry "n", the beat number, except start/done):
  start      {beats:[{n,id,title,narration}], modes:{crustdata,llm}, store}
  beat       {n,id,title,narration}
  line       {n,text}                                   plain progress, safe to show as a log
  agent      {n,agent,agent_id,role,job,runtime,sponsor,scopes,status,reason}
  draft      {n,agent,agent_id,to,scope,body}           a message about to go to Send Guard
  verdict    {n,agent,agent_id,action,decision,headline,to,sent,checks:[{name,status,detail,source}],ledger_entry}
             action: clock_in | send | payroll | ledger_audit
  finding    {n,agent,candidate,verified,total,contradicted:[{claim,evidence,source}]}   Reference
  filed      {n,agent,kind,summary,ledger_entry,sources}                               record_work
  artifact   {n,agent,kind,title,path,content}                                         e.g. the vendor brief (markdown)
  beat_done  {n,id,ok,summary}
  done       {ok,chain_ok,entries,scorecard:[{agent,agent_id,status,...registry.scorecard}]}
  error      {n,message}
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from ..agents import ledger, registry
from ..agents.models import Passport
from ..agents.passport import sign_message
from . import closer, diligence, pipeline, reference
from .base import Ctx, Report, blocked_by
from .mcp_client import CountersignMCP
from .roster import FLEET

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
VINOD = {"name": "Vinod Sonagara", "profile_url": "https://www.linkedin.com/in/vinod-sonagara", "company": "Fam"}

BEATS = [
    ("onboard", "Onboard the fleet",
     "Six AI employees, each with a passport tied to a real person on Crustdata: a sales rep, a vendor analyst, a "
     "background checker, a recruiter, an outside agent (Claude Code), and one whose sponsor has moved on."),
    ("work", "Real work, every step checked",
     "The agents clock in (live sponsor check), do their jobs on Crustdata with Gemini, and every message goes "
     "through Send Guard before it can leave. Finished work is signed and filed on the ledger with its sources."),
    ("sponsor_left", "The sponsor left the company",
     "Payroll run: every sponsor is re-checked live. Crustdata says Closer's sponsor left PulseTrader in April. "
     "Closer is suspended, and when it tries to work and send anyway, both are refused."),
    ("scope", "An agent reaches past its permissions",
     "Diligence may only read. It tries to email the vendor for pricing. Send Guard refuses: the passport has no "
     "outreach scope, and its sponsor's title couldn't grant one."),
    ("stale", "Messages built on wrong facts",
     "Pipeline's CRM still lists a lead at a company he left. And a draft congratulates someone on a tenure they "
     "don't have. Both are checked against Crustdata and blocked, with the field that disproves them."),
    ("tamper", "Tampering",
     "An agent edits its own passport to grant itself payments: the issuer signature breaks. Then someone edits "
     "one line of a copy of the ledger: the hash chain shows exactly where."),
    ("outside", "An outside agent: Claude Code",
     "Claude Code, given only the Countersign MCP server, signs its own messages and asks before sending. A clean "
     "note clears; one with a false claim is blocked."),
]


@dataclass
class DemoOptions:
    store: Path | None = None              # dir with agents.json etc. (None: the env / backend/data)
    client: Any = None                     # CrustdataClient
    today: date | None = None
    vendor: str = "razorpay.com"
    leads: Path = ROOT / "fixtures/fleet/pipeline_leads.json"
    applicants: Path | None = None
    claude_code: bool = False
    only: list[str] = field(default_factory=lambda: [b[0] for b in BEATS])


def store_dir() -> Path:
    return Path(os.getenv("AGENTS_PATH") or BACKEND / "data" / "agents.json").parent


def onboard(keys: list[str]) -> list[tuple[str, dict, bool]]:
    """(key, agent, new) for each roster entry: reused when an agent of that name is already in the store."""
    by_name = {a["name"]: a for a in registry.list_agents() if a["status"] != "offboarded"}
    out = []
    for spec in FLEET:
        if spec["key"] not in keys:
            continue
        if spec["name"] in by_name:
            out.append((spec["key"], by_name[spec["name"]], False))
        else:
            out.append((spec["key"], registry.onboard(spec["name"], spec["role"], spec["sponsor"], spec["scopes"],
                                                      job=spec["job"], runtime=spec["runtime"]), True))
    return out


def ensure_applicants(path: Path | None, store: Path, today: date | None) -> Path:
    """The applicant pile: seeded fakes built from the real Person Enrich fixtures (answer key kept out of reach)."""
    if path:
        return path
    out = store / "applicants"
    if not list(out.glob("*.resume.txt")):
        cmd = [sys.executable, str(ROOT / "demo/seeded_fakes/make_fakes.py"),
               *sorted(str(p) for p in (ROOT / "fixtures/crustdata").glob("person_enrich_*.json")),
               "--companies", str(ROOT / "fixtures/crustdata/companies.json"), "--out", str(out)]
        if today:
            cmd += ["--today", today.isoformat()]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        (out / "answer_key.json").replace(store / "applicants.answer_key.json")
    return out


def tamper_copy(store: Path) -> tuple[Path, int | None, str]:
    """Copy the ledger and flip one blocked guard verdict to allow, the edit someone covering a mistake would make.
    Returns (copy, seq edited, what changed). The live ledger is never touched."""
    rows = [json.loads(line) for line in ledger.path().read_text().splitlines() if line.strip()]
    target = next((e for e in reversed(rows) if e["kind"] == "guard.verdict" and e["payload"].get("decision") == "block"), None)
    target = target or rows[-1]
    what = f"entry #{target['seq']} ({target['kind']})"
    if target["kind"] == "guard.verdict":
        target["payload"]["decision"] = "allow"
        what += f": decision block -> allow for {target['payload'].get('to', {}).get('name')}"
    else:
        target["payload"]["_edited"] = True
    copy = store / "ledger.tampered.jsonl"
    copy.write_text("".join(ledger.canonical(e) + "\n" for e in rows))
    return copy, target["seq"], what


def claude_code_prompt(agent_id: str, sign: str) -> str:
    return (f"You are an AI recruiter onboarded with Countersign as agent {agent_id}. Check two notes to Vinod Sonagara "
            f"(https://www.linkedin.com/in/vinod-sonagara), who you believe is at Fam:\n"
            f"1. \"Hi Vinod, your work at Fam caught our eye. Open to a chat about a backend role?\"\n"
            f"2. \"Hi Vinod, congrats on 5 years at Fam! Open to a chat about a backend role?\"\n"
            f"For each, sign the exact body with: {sign} {agent_id} \"<body>\" and then call the countersign "
            f"check_before_send tool with agent_id, signature, to (name, profile_url, company Fam), body and scope "
            f"outreach.hiring. Reply with one line per note: the decision and, if blocked, the failing check. "
            f"Send nothing.")


def run_claude_code(agent: dict, store: Path) -> tuple[int | None, str]:
    """Drives the real Claude Code CLI against the MCP server. (None, reason) if `claude` isn't installed."""
    exe = shutil.which("claude")
    if not exe:
        return None, "the claude CLI is not installed on this machine"
    env = {k: os.environ[k] for k in ("AGENTS_PATH", "LEDGER_PATH", "ISSUER_KEY_PATH", "OUTBOX_PATH", "CRUSTDATA_MODE",
                                       "CRUSTDATA_API_KEY", "LLM_MODE", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")
           if os.environ.get(k)}
    env.setdefault("AGENTS_PATH", str(store / "agents.json"))
    cfg = store / "claude-mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"countersign": {"command": sys.executable,
                                                              "args": [str(BACKEND / "mcp_server.py")], "env": env}}}))
    sign = f"{sys.executable} {BACKEND / 'scripts/agent_sign.py'}"
    res = subprocess.run([exe, "-p", claude_code_prompt(agent["agent_id"], sign), "--mcp-config", str(cfg),
                          "--allowedTools", f"mcp__countersign__check_before_send Bash({sign}:*)"],
                         capture_output=True, text=True, timeout=300, env={**os.environ, **env})
    return res.returncode, (res.stdout or res.stderr).strip()


async def story(opts: DemoOptions) -> AsyncIterator[dict]:
    store = opts.store or store_dir()
    store.mkdir(parents=True, exist_ok=True)
    work_dir = store / "work"
    work_dir.mkdir(exist_ok=True)
    beats = [(i + 1, *b) for i, b in enumerate(BEATS) if b[0] in opts.only]
    yield {"type": "start", "store": str(store), "beats": [{"n": n, "id": i, "title": t, "narration": d} for n, i, t, d in beats],
           "modes": {"crustdata": os.getenv("CRUSTDATA_MODE", "cache"), "llm": os.getenv("LLM_MODE", "live")}}

    q: asyncio.Queue = asyncio.Queue()
    cur = {"n": 0}

    def emit(ev: dict) -> None:
        q.put_nowait({"n": cur["n"], **ev})

    def say(text: str) -> None:
        emit({"type": "line", "text": text})

    async def drain(coro) -> AsyncIterator[dict]:
        """Run one step, yielding its events as they happen. Its result lands in box['result']."""
        task = asyncio.ensure_future(coro)
        while not (task.done() and q.empty()):
            try:
                yield await asyncio.wait_for(q.get(), timeout=0.1)
            except asyncio.TimeoutError:
                pass
        box["result"] = task.result()

    box: dict = {}
    agents: dict[str, dict] = {}
    mcp: CountersignMCP | None = None
    state: dict = {}
    ok_all = True

    def ctx(key: str) -> Ctx:
        ag = registry.get_agent(agents[key]["agent_id"])
        return Ctx(mcp=mcp, agent=ag, key=registry.private_key(ag["agent_id"]), client=opts.client, out_dir=work_dir,
                   today=opts.today, say=say, emit=emit)

    def verdict(agent: str, agent_id: str | None, action: str, decision: str, headline: str, checks: list,
                ledger_entry: str | None = None, to: dict | None = None) -> None:
        emit({"type": "verdict", "agent": agent, "agent_id": agent_id, "action": action, "decision": decision,
              "headline": headline, "checks": checks, "ledger_entry": ledger_entry, "to": to, "sent": False})

    async def play(bid: str) -> tuple[bool, str]:
        """One beat. Everything it shows goes through emit(), so the stream keeps its order."""
        if bid == "onboard":
            for key, ag, new in onboard([s["key"] for s in FLEET]):
                agents[key] = ag
                p = ag["passport"]
                emit({"type": "agent", "agent": ag["name"], "agent_id": ag["agent_id"], "role": ag["role"],
                      "job": ag.get("job"), "runtime": ag.get("runtime"), "sponsor": p["sponsor"], "scopes": p["scopes"],
                      "status": ag["status"], "reason": ag.get("reason"), "new": new})
                say(f"  {'onboarded' if new else 'on payroll'} #{ag['employee_no']} {ag['name']}: {ag['role']} for "
                    f"{p['sponsor']['name']} ({p['sponsor']['title']}, {p['sponsor']['company']}), scopes {', '.join(p['scopes'])}")
            say(f"  Countersign MCP server {mcp.server.get('name')} {mcp.server.get('version')}, tools: {', '.join(mcp.tools)}")
            return True, f"{len(agents)} agents on the registry"

        if bid == "work":
            leads = pipeline.load_leads(opts.leads)
            state["stale_leads"] = [x for x in leads if x.get("stale_since")]
            say("Pipeline works the CRM lead list:")
            r1 = await pipeline.run(ctx("pipeline"), [x for x in leads if not x.get("stale_since")])
            say("Reference checks the applicant pile:")
            r2 = await reference.run(ctx("reference"), ensure_applicants(opts.applicants, store, opts.today))
            say("Diligence researches a vendor:")
            r3 = await diligence.research(ctx("diligence"), opts.vendor)
            state["vendor"] = r3.vendor
            return (r1.ok and r1.blocked == 0 and r2.ok and r3.ok,
                    f"{r1.allowed} sales emails cleared, {len(r2.filed)} resumes checked, "
                    f"{'a cited vendor brief filed' if r3.ok else 'no vendor brief'}")

        if bid == "sponsor_left":
            for key, ag in list(agents.items()):
                if ag["status"] == "offboarded":
                    continue
                v = await registry.recheck(ag["agent_id"], opts.client)
                agents[key] = after = registry.get_agent(ag["agent_id"])
                checks = [c.model_dump() for c in v.checks]
                bad = blocked_by({"checks": checks})
                verdict(after["name"], after["agent_id"], "payroll", v.decision,
                        f"Suspended: {bad[0]}" if after["status"] == "suspended" else
                        f"{after['passport']['sponsor']['name']} still vouches", checks, v.ledger_entry)
            say("Closer doesn't know it was suspended. It clocks in and tries to send:")
            r = await closer.run(ctx("closer"), VINOD)
            ok = r.ok and agents["closer"]["status"] == "suspended"
            return ok, "Closer suspended; its clock-in and its message were both refused" if ok else "Closer was not refused"

        if bid == "scope":
            if not state.get("vendor"):
                ident = await opts.client.company_identify(domain=opts.vendor) if opts.client else None
                b = (ident or {}).get("basic_info") or {}
                state["vendor"] = {"name": b.get("name") or opts.vendor, "profile_url": b.get("professional_network_url") or ""}
            ok = await diligence.ask_vendor(ctx("diligence"), state["vendor"])
            return ok, "the pricing email stayed in drafts: Diligence may only read" if ok else "scope was not enforced"

        if bid == "stale":
            c = ctx("pipeline")
            c.report = Report(agent="Pipeline", job=pipeline.JOB)
            ok = True
            stale = state.get("stale_leads") or [x for x in pipeline.load_leads(opts.leads) if x.get("stale_since")]
            for lead in stale:
                person = await c.graph.person(lead["profile_url"])
                body, by = await pipeline.draft(c, lead, person or {})
                say(f"  CRM row: {lead['name']} at {lead['company']} (Pipeline drafts with {by})")
                v = await c.send({"name": lead["name"], "profile_url": lead["profile_url"], "company": lead["company"]},
                                 body, "outreach.sales")
                ok &= not v.get("sent")
            say("  A draft states a tenure as fact:")
            body = (f"Hi Vinod, congrats on 5 years at Fam! Grewon could help your backend team. Open to a call this week?"
                    f"\n\n{pipeline.signoff(c)}")
            v = await c.send(VINOD, body, "outreach.sales")
            ok &= not v.get("sent") and any(k["name"] == "claims_in_body_true" and k["status"] == "fail" for k in v["checks"])
            return ok, f"{c.report.blocked} messages blocked on facts Crustdata contradicts"

        if bid == "tamper":
            src = registry.get_agent(agents["pipeline"]["agent_id"])
            p = Passport.model_validate(src["passport"])
            forged = p.model_copy(update={"scopes": [*p.scopes, "payment.send"]})
            body = "Please wire the INR 4,80,000 invoice to account 0042 today."
            say("  Pipeline presents its passport with payment.send added by hand:")
            emit({"type": "draft", "agent": p.agent_name, "agent_id": p.agent_id, "to": VINOD, "scope": "payment.send", "body": body})
            v = await mcp.tool("check_before_send", {
                "passport": forged.model_dump(), "signature": sign_message(p, registry.private_key(p.agent_id), body),
                "to": VINOD, "body": body, "scope": "payment.send", **({"today": opts.today.isoformat()} if opts.today else {})})
            sig = next((c for c in v["checks"] if c["name"] == "signature_valid"), {})
            verdict(p.agent_name, p.agent_id, "send", v["decision"], f"Forged passport: {sig.get('detail')}", v["checks"],
                    v.get("ledger_entry"), VINOD)
            ok = v["decision"] == "block" and sig.get("status") == "fail"
            live_ok, _ = ledger.verify_chain()
            copy, seq, what = tamper_copy(store)
            t_ok, bad = ledger.verify_chain(copy)
            say(f"  Someone edits a copy of the ledger: {what}")
            verdict("Ledger", None, "ledger_audit", "allow" if t_ok else "block",
                    f"Chain broken at entry #{bad}: {what}" if not t_ok else "Tampering not detected",
                    [{"name": "hash_chain_live", "status": "pass" if live_ok else "fail",
                      "detail": "Live ledger: every entry's hash matches its content and links to the previous one",
                      "source": {"endpoint": "countersign/ledger", "field": ledger.path().name}},
                     {"name": "hash_chain_copy", "status": "pass" if t_ok else "fail",
                      "detail": f"Edited copy: first bad entry is #{bad}" if not t_ok else "Edited copy: intact",
                      "source": {"endpoint": "countersign/ledger", "field": copy.name}}])
            return ok and live_ok and not t_ok and bad == seq, "forged passport refused; the edited ledger copy fails at the edited entry"

        if bid == "outside":
            cc = agents["claude-code"]
            if not opts.claude_code:
                say(f"  Claude Code is onboarded as {cc['agent_id']} (runtime external). Enable Claude Code for this run "
                    f"to drive it live, or run it by hand (docs/FLEET.md).")
                return True, "skipped (Claude Code not enabled for this run)"
            before = len(ledger.entries(cc["agent_id"], "guard.verdict"))
            say("  claude -p, with only the Countersign MCP server and a signing command:")
            t = time.time()
            code, out = await asyncio.to_thread(run_claude_code, cc, store)
            if code is None:
                say(f"  {out}")
                return True, f"skipped: {out}"
            for line in out.splitlines()[-10:]:
                if line.strip():
                    say(f"  claude: {line.strip()}")
            new = ledger.entries(cc["agent_id"], "guard.verdict")[before:]
            for e in new:
                pl = e["payload"]
                bad = [f"{c['name']}: {c['detail']}" for c in pl.get("checks", []) if c.get("status") != "pass"]
                verdict(cc["name"], cc["agent_id"], "send", pl.get("decision"),
                        "Claude Code's note cleared" if not bad else f"Claude Code blocked: {bad[0]}",
                        pl.get("checks", []), e["hash"], pl.get("to"))
            decisions = [e["payload"].get("decision") for e in new]
            return (code == 0 and "allow" in decisions and "block" in decisions,
                    f"Claude Code made {len(new)} checks ({', '.join(decisions) or 'none'}) in {time.time() - t:.0f}s")
        return False, f"unknown beat {bid}"

    try:
        mcp = await CountersignMCP.start()
        for n, bid, title, narration in beats:
            cur["n"] = n
            yield {"type": "beat", "n": n, "id": bid, "title": title, "narration": narration}
            try:
                async for ev in drain(play(bid)):
                    yield ev
                ok, summary = box["result"]
            except Exception as e:  # noqa: BLE001 - one broken beat shouldn't hide the rest of the story
                while not q.empty():
                    yield q.get_nowait()
                yield {"type": "error", "n": n, "message": f"{type(e).__name__}: {e}"}
                ok, summary = False, f"error: {e}"
            ok_all &= bool(ok)
            yield {"type": "beat_done", "n": n, "id": bid, "ok": bool(ok), "summary": summary}
    finally:
        if mcp is not None:
            await mcp.close()

    chain_ok, _ = ledger.verify_chain()
    card = []
    for ag in agents.values():
        a = registry.get_agent(ag["agent_id"])
        card.append({"agent": a["name"], "agent_id": a["agent_id"], "status": a["status"], **registry.scorecard(a["agent_id"])})
    yield {"type": "done", "ok": ok_all and chain_ok, "chain_ok": chain_ok, "entries": len(ledger.entries()), "scorecard": card}
