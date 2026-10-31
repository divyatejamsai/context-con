"""Sourced as a Agaxes AI employee: the hiring pipeline run under a passport, with ledger entries and Send Guard.

    GET/POST /api/agents/{agent_id}/run?brief=...   same SSE stream as /api/run, plus:
        step "passport"  live verify_passport(data.read) before any Crustdata search; a block ends the run
        step "guard"     Send Guard verdict on each shortlisted outreach draft (signed with the agent's key)
        step "send"      with ?autosend=1: the email that went out (or why not) for each cleared draft
        candidate        re-sent with a "guard" field {decision, checks, ledger_entry} once its draft is checked
    POST /api/verify_resume                        check a resume's claims against Crustdata (seeded-fakes beat)

The run is recorded on the hash-chained ledger: run.started, run.finished (with every candidate's claim sources)
and one guard.verdict per draft. Shortlisted candidates get their email from Crustdata (contact field), and with
autosend=1 (or AUTO_SEND=1) every cleared draft is emailed through app/outbound (test mode redirects to your inbox).
The agent must be onboarded first (console, POST /api/agents, scripts/onboard_sourced.py or scripts/run_fleet.py).
agent_id "sourced" means the newest active agent named Sourced (else the newest Sourced, so a suspension still shows),
so the UI can use NEXT_PUBLIC_AGENT_ID=sourced without copying ids around.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .accounts import authz
from .accounts.authz import require_operate
from .agents import ledger, registry
from .agents.api import crustdata
from .crustdata import OUT_OF_CREDITS, out_of_credits_since
from .agents.graph import Graph
from .agents.guard import check_send
from .agents.models import Passport, Verdict
from .agents.passport import sign_message, verify_passport
from .orchestrator import run
from .outbound.contacts import find_emails
from .outbound.send import finalize_body, guarded_send
from .schemas import Claim, Criteria, RunRequest

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["sourced"])

GUARD_MAX = int(os.getenv("GUARD_MAX", "5"))            # drafts checked per run (each check costs a Person Enrich)
GUARD_TIMEOUT = float(os.getenv("GUARD_TIMEOUT", "30"))
AUTO_SEND = os.getenv("AUTO_SEND", "").lower() in ("1", "true", "yes")
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


class AgentStep(BaseModel):
    """StepEvent with Agaxes step names (passport, guard). Same wire shape as schemas.StepEvent."""
    type: str = "step"
    step: str
    message: str
    data: dict[str, Any] | None = None
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _err(step: str, message: str) -> dict:
    return {"type": "error", "step": step, "message": message, "ts": datetime.now(timezone.utc).isoformat()}


def _failures(v: Verdict) -> str:
    bad = [f"{c.name} ({c.status}): {c.detail}" for c in v.checks if c.status != "pass"]
    return "; ".join(bad) or "no checks ran"


def _dedupe(sources: list[dict]) -> list[dict]:
    """Many candidates cite the same field; keep one of each (endpoint, field, url)."""
    seen, out = set(), []
    for x in sources:
        k = (x.get("endpoint"), x.get("field"), x.get("url"))
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _guard_reason(g: dict) -> str | None:
    bad = [c for c in g.get("checks") or [] if c.get("status") != "pass"]
    return (bad[0].get("detail") or bad[0].get("name")) if bad else None


class RunStory:
    """Collects the parts of a run a reader of the ledger needs: the reading of the brief, each search and its count,
    and the final tiers. Kept small: names, scores and short reasons, never whole profiles."""

    CRITERIA_KEYS = ("role", "title_variants", "seniority", "skills", "locations", "company_preferences", "must_haves",
                     "nice_to_haves", "min_years", "schools", "degrees", "education_note")

    def __init__(self) -> None:
        self.criteria: dict = {}
        self.assumptions: list[str] = []
        self.searches: list[dict] = []
        self.tiers: dict = {}
        self.notes: list[str] = []

    def see(self, d: dict) -> None:
        data = d.get("data") or {}
        if d.get("type") == "error":
            self.notes.append(str(d.get("message") or "")[:200])
        if d.get("type") != "step":
            return
        step = d.get("step")
        if step == "parse" and data.get("criteria"):
            c = data["criteria"]
            self.criteria = {k: c[k] for k in self.CRITERIA_KEYS if c.get(k) not in (None, "", [])}
        elif step == "parse" and data.get("assumptions"):
            self.assumptions += [str(a) for a in data["assumptions"]][:8]
        elif step == "search" and "filters" in data:
            self.searches.append({"level": data.get("level"), "strategy": data.get("strategy"), "filters": data.get("filters"),
                                  "count": None})
        elif step == "search" and "count" in data:
            for s in reversed(self.searches):
                if s.get("level") == data.get("level"):
                    s["count"] = data["count"]
                    break
        elif step == "rank" and ("shortlist" in data or "order" in data):
            self.tiers = {k: data.get(k) for k in ("order", "shortlist", "near_miss", "threshold") if data.get(k) is not None}

    def payload(self, brief: str, candidates: dict, guarded: dict, guard_why: dict, sent: dict, elapsed_ms: int) -> dict:
        short, near = set(self.tiers.get("shortlist") or []), set(self.tiers.get("near_miss") or [])
        order = self.tiers.get("order") or sorted(candidates, key=lambda i: -(candidates[i].get("score") or 0))
        people = []
        for i in [*order, *[i for i in candidates if i not in order]]:
            c = candidates.get(i)
            if not c:
                continue
            claims = c.get("claims") or []
            people.append({
                "id": i, "name": c.get("name"), "title": c.get("title"), "company": c.get("company"),
                "score": c.get("score"),
                "tier": "shortlist" if i in short else "near_miss" if i in near else "below" if self.tiers else "shortlist",
                "reasons": [r.get("text") for r in (c.get("reasons") or [])[:3] if r.get("text")],
                "flags": [str(f) for f in (c.get("flags") or [])[:3]],
                "claims": {k: sum(1 for x in claims if x.get("status") == k) for k in ("verified", "contradicted", "unverifiable")},
                **({"guard": guarded[i]} if i in guarded else {}),
                **({"guard_reason": guard_why[i]} if guard_why.get(i) else {}),
                **({"sent": sent[i]} if i in sent else {}),
            })
        return {"brief": brief[:1000], "understood": self.criteria, "assumptions": self.assumptions,
                "searches": self.searches, "threshold": self.tiers.get("threshold"), "candidates": people[:25],
                "notes": self.notes[:5], "elapsed_ms": elapsed_ms}


def _subject(c: dict, passport: Passport, role: str | None) -> str:
    first = (c.get("name") or "").split(" ")[0]
    what = role or "a role"
    return f"{first + ', ' if first else ''}{what} at {passport.sponsor.company}"


def resolve_agent_id(agent_id: str) -> str:
    if agent_id.lower() != "sourced":
        return agent_id
    mine = [a for a in registry.list_agents() if a.get("name") == "Sourced" and a.get("status") != "offboarded"]
    active = [a for a in mine if a.get("status") == "active"]
    pick = (active or mine or [None])[-1]
    return pick["agent_id"] if pick else agent_id


async def run_as_agent(brief: str, agent_id: str, client: Any = None, autosend: bool | None = None) -> AsyncIterator[dict]:
    """Yields event dicts. Never raises: problems come back as error events.
    autosend: email every draft Send Guard clears, with no one at the keyboard (default AUTO_SEND env, else off)."""
    autosend = AUTO_SEND if autosend is None else autosend
    agent_id = resolve_agent_id(agent_id)
    try:
        rec = registry.get_agent(agent_id)
    except Exception:  # noqa: BLE001 - RegistryError or a bad store
        yield _err("passport", f"Unknown agent {agent_id}: onboard it in the console first")
        return
    if rec.get("status") != "active":
        yield _err("passport", f"{rec.get('name')} is {rec.get('status')}: {rec.get('reason') or 'no reason given'}")
        return

    passport = Passport.model_validate(rec["passport"])
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    client = client if client is not None else crustdata()
    graph = Graph(client)
    yield AgentStep(step="passport", message=f"Checking {passport.agent_name}'s passport live against Crustdata...").model_dump()
    pv = await verify_passport(passport, client, "data.read", graph=graph)
    pv_data = {"agent_id": agent_id, "decision": pv.decision, "checks": [c.model_dump() for c in pv.checks],
               "ledger_entry": pv.ledger_entry}
    if pv.decision != "allow":
        yield AgentStep(step="passport", message=f"Blocked: {_failures(pv)}", data=pv_data).model_dump()
        if out_of_credits_since(started):
            yield _err("passport", OUT_OF_CREDITS)
            return
        yield _err("passport", "Run refused: the passport did not pass. Nothing was searched.")
        return
    s = passport.sponsor
    yield AgentStep(step="passport", message=f"Passport valid: acting for {s.name}, {s.title or 'sponsor'} at {s.company}",
                    data=pv_data).model_dump()

    brief_sha = hashlib.sha256(brief.encode()).hexdigest()
    ledger.append("run.started", {"agent_id": agent_id, "brief": brief, "brief_sha256": brief_sha,
                                  "passport_check": pv.ledger_entry})

    candidates: dict[str, dict] = {}
    shortlist: list[str] = []
    summary: dict = {}
    done_ev: dict | None = None
    brief_role: dict = {}
    story = RunStory()
    t0 = time.monotonic()
    async for ev in run(brief, client=client):
        d = ev.model_dump(mode="json")
        story.see(d)
        if d["type"] == "step" and d.get("step") == "parse" and (d.get("data") or {}).get("criteria"):
            brief_role = d["data"]["criteria"]
        if d["type"] == "candidate":
            candidates[d["candidate"]["id"]] = d["candidate"]
        elif d["type"] == "step" and d.get("step") == "rank" and d.get("data"):
            shortlist = d["data"].get("shortlist") or d["data"].get("order", [])[:3]
        if d["type"] == "done":
            done_ev, summary = d, d.get("summary") or {}
            continue  # sent after the guard step
        yield d

    guarded: dict[str, str] = {}
    sent: dict[str, str] = {}
    todo = [candidates[i] for i in shortlist if i in candidates and candidates[i].get("outreach_draft")][:GUARD_MAX]
    for c in todo:  # the email says who is hiring and who signs it
        c["outreach_draft"] = finalize_body(c["outreach_draft"], passport)
        c["outreach_subject"] = _subject(c, passport, brief_role.get("role"))
    contacts_task = asyncio.create_task(find_emails(client, [c.get("profile_url") for c in todo])) if todo else None
    if "outreach.hiring" not in passport.scopes:
        yield AgentStep(step="guard", message="No outreach.hiring scope: drafts kept, none cleared to send").model_dump()
    elif todo:
        yield AgentStep(step="guard", message=f"Send Guard checking {len(todo)} shortlisted draft(s) and finding their emails on Crustdata...").model_dump()
        key = registry.private_key(agent_id)

        async def one(c: dict) -> tuple[dict, Verdict | None]:
            body = c["outreach_draft"]
            to = {"name": c.get("name"), "profile_url": c.get("profile_url"), "company": c.get("company")}
            try:
                v = await asyncio.wait_for(
                    check_send(passport, sign_message(passport, key, body), to, body, "outreach.hiring", client, graph=graph),
                    timeout=GUARD_TIMEOUT)
                return c, v
            except Exception as e:  # noqa: BLE001 - a guard failure blocks, it never allows
                log.warning("guard failed for %s: %s", c.get("id"), e)
                return c, None

        found = await contacts_task if contacts_task else {}
        for c in todo:
            info = found.get(c.get("profile_url"))
            if info is not None:
                c["contact"] = info.model_dump(mode="json")
        n_email = sum(1 for c in todo if (c.get("contact") or {}).get("email"))
        yield AgentStep(step="guard", message=f"Crustdata has an email for {n_email} of {len(todo)} shortlisted candidates",
                        data={"emails_found": n_email, "checked": len(todo)}).model_dump()

        for fut in asyncio.as_completed([one(c) for c in todo]):
            c, v = await fut
            if v is None:
                guarded[c["id"]] = "block"
                c["guard"] = {"decision": "block", "checks": [], "ledger_entry": None, "error": "guard timed out"}
                msg = f"{c.get('name')}: blocked (guard could not finish, fail closed)"
            else:
                guarded[c["id"]] = v.decision
                c["guard"] = {"decision": v.decision, "checks": [k.model_dump() for k in v.checks], "ledger_entry": v.ledger_entry}
                msg = (f"{c.get('name')}: cleared to send" if v.decision == "allow"
                       else f"{c.get('name')}: blocked, {_failures(v)}")
            yield AgentStep(step="guard", message=msg, data={"candidate_id": c["id"], **c["guard"]}).model_dump()
            if autosend and v is not None and v.decision == "allow":
                to = {"name": c.get("name"), "profile_url": c.get("profile_url"), "company": c.get("company")}
                res = await guarded_send(agent_id, to, c["outreach_subject"], c["outreach_draft"], email=c.get("contact"),
                                         verdict=v, verdict_body=c["outreach_draft"], client=client, graph=graph)
                sent[c["id"]] = res.status
                c["outreach"] = {"status": res.status, "detail": res.detail, "message": res.message}
                yield AgentStep(step="send", message=f"{c.get('name')}: {res.detail}",
                                data={"candidate_id": c["id"], "status": res.status}).model_dump()
            yield {"type": "candidate", "candidate": c, "ts": datetime.now(timezone.utc).isoformat()}
    if contacts_task and not contacts_task.done():
        contacts_task.cancel()

    sources = [cl.get("source") for c in candidates.values() for cl in c.get("claims") or [] if cl.get("source")]
    guard_why = {c["id"]: (c.get("guard") or {}).get("error") or _guard_reason(c.get("guard") or {}) for c in todo
                 if guarded.get(c["id"]) == "block"}
    entry = ledger.append("run.finished", {
        "agent_id": agent_id, "brief_sha256": brief_sha, "summary": summary,
        "shortlist": [{"id": i, "name": candidates[i].get("name"), "score": candidates[i].get("score")} for i in shortlist if i in candidates],
        "guard": guarded, "sent": sent,
        # The run in plain terms, so the ledger can tell its story without the event stream: what was asked, how it was
        # read, what was searched, and every decision with its reason.
        **story.payload(brief, candidates, guarded, guard_why, sent, elapsed_ms=int((time.monotonic() - t0) * 1000)),
    }, _dedupe(sources)[:200])
    if out_of_credits_since(started):  # lookups failed part-way: the shortlist and checks are incomplete
        yield _err("crustdata", OUT_OF_CREDITS)
    if done_ev:
        done_ev.setdefault("summary", {})["ledger_entry"] = entry
        done_ev["summary"]["agent_id"] = agent_id
        yield done_ev


async def _sse(brief: str, agent_id: str, autosend: bool | None = None):
    import json
    async for d in run_as_agent(brief, agent_id, autosend=autosend):
        yield f"data: {json.dumps(d, default=str)}\n\n"


@router.post("/agents/{agent_id}/run", dependencies=[Depends(require_operate)])
async def run_post(agent_id: str, req: RunRequest, autosend: bool | None = None):
    authz.check_agent(agent_id)
    return StreamingResponse(_sse(req.brief, agent_id, autosend), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/agents/{agent_id}/run", dependencies=[Depends(require_operate)])  # EventSource: ?token=<admin token>
async def run_get(agent_id: str, brief: str = Query(..., min_length=1), autosend: bool | None = None):
    authz.check_agent(agent_id)
    return StreamingResponse(_sse(brief, agent_id, autosend), media_type="text/event-stream", headers=SSE_HEADERS)


# ---- resume verification (seeded fakes) ---------------------------------------------------------

class ResumeRequest(BaseModel):
    """What a candidate claims. Keys of `claimed` match the verifier: employer, title, start_date, tenure_years,
    years_experience, location, company_stage, skills."""
    name: str | None = None
    profile_url: str
    claimed: dict[str, Any] = Field(default_factory=dict)


class ResumeResponse(BaseModel):
    name: str | None
    profile_url: str
    found: bool
    claims: list[Claim]
    flags: list[str]
    ledger_entry: str | None = None


@router.post("/verify_resume", response_model=ResumeResponse, dependencies=[Depends(require_operate)])
async def verify_resume(req: ResumeRequest):
    from .verify.verifier import verify_candidate

    client = crustdata()
    person = await Graph(client).person(req.profile_url)
    if not person:
        return ResumeResponse(name=req.name, profile_url=req.profile_url, found=False, flags=[], claims=[
            Claim(id=f"r{i + 1}", claim=f"{k}: {v}", status="unverifiable", evidence="No Crustdata record for this profile",
                  source={"endpoint": "person/enrich", "url": req.profile_url})
            for i, (k, v) in enumerate(req.claimed.items())])
    person = {**person, "claimed": req.claimed}
    crit = Criteria(role="Resume check", raw_brief="resume verification")
    try:
        claims, flags = await verify_candidate(person, None, crit, client)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"verifier failed: {e}")
    entry = ledger.append("resume.verified", {
        "profile_url": req.profile_url, "name": req.name,
        "contradicted": [c.claim for c in claims if c.status == "contradicted"],
        "verified": sum(c.status == "verified" for c in claims), "total": len(claims),
    }, [c.source for c in claims])
    return ResumeResponse(name=req.name, profile_url=req.profile_url, found=True, claims=claims, flags=flags, ledger_entry=entry)
