"""Sourced as a Countersign AI employee: the hiring pipeline run under a passport, with ledger entries and Send Guard.

    GET/POST /api/agents/{agent_id}/run?brief=...   same SSE stream as /api/run, plus:
        step "passport"  live verify_passport(data.read) before any Crustdata search; a block ends the run
        step "guard"     Send Guard verdict on each shortlisted outreach draft (signed with the agent's key)
        candidate        re-sent with a "guard" field {decision, checks, ledger_entry} once its draft is checked
    POST /api/verify_resume                        check a resume's claims against Crustdata (seeded-fakes beat)

The run is recorded on the hash-chained ledger: run.started, run.finished (with every candidate's claim sources)
and one guard.verdict per draft. Drafts are never sent (event rule); "allow" means cleared to send.
The agent must be onboarded first (console, POST /api/agents, scripts/onboard_sourced.py or scripts/run_fleet.py).
agent_id "sourced" means the newest active agent named Sourced (else the newest Sourced, so a suspension still shows),
so the UI can use NEXT_PUBLIC_AGENT_ID=sourced without copying ids around.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agents import ledger, registry
from .agents.api import crustdata
from .agents.graph import Graph
from .agents.guard import check_send
from .agents.models import Passport, Verdict
from .agents.passport import sign_message, verify_passport
from .orchestrator import run
from .schemas import Claim, Criteria, RunRequest

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["sourced"])

GUARD_MAX = int(os.getenv("GUARD_MAX", "5"))            # drafts checked per run (each check costs a Person Enrich)
GUARD_TIMEOUT = float(os.getenv("GUARD_TIMEOUT", "30"))
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


class AgentStep(BaseModel):
    """StepEvent with Countersign step names (passport, guard). Same wire shape as schemas.StepEvent."""
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


def resolve_agent_id(agent_id: str) -> str:
    if agent_id.lower() != "sourced":
        return agent_id
    mine = [a for a in registry.list_agents() if a.get("name") == "Sourced" and a.get("status") != "offboarded"]
    active = [a for a in mine if a.get("status") == "active"]
    pick = (active or mine or [None])[-1]
    return pick["agent_id"] if pick else agent_id


async def run_as_agent(brief: str, agent_id: str, client: Any = None) -> AsyncIterator[dict]:
    """Yields event dicts. Never raises: problems come back as error events."""
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
    client = client if client is not None else crustdata()
    graph = Graph(client)
    yield AgentStep(step="passport", message=f"Checking {passport.agent_name}'s passport live against Crustdata...").model_dump()
    pv = await verify_passport(passport, client, "data.read", graph=graph)
    pv_data = {"agent_id": agent_id, "decision": pv.decision, "checks": [c.model_dump() for c in pv.checks],
               "ledger_entry": pv.ledger_entry}
    if pv.decision != "allow":
        yield AgentStep(step="passport", message=f"Blocked: {_failures(pv)}", data=pv_data).model_dump()
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
    async for ev in run(brief, client=client):
        d = ev.model_dump(mode="json")
        if d["type"] == "candidate":
            candidates[d["candidate"]["id"]] = d["candidate"]
        elif d["type"] == "step" and d.get("step") == "rank" and d.get("data"):
            shortlist = d["data"].get("shortlist") or d["data"].get("order", [])[:3]
        if d["type"] == "done":
            done_ev, summary = d, d.get("summary") or {}
            continue  # sent after the guard step
        yield d

    guarded: dict[str, str] = {}
    if "outreach.hiring" not in passport.scopes:
        yield AgentStep(step="guard", message="No outreach.hiring scope: drafts kept, none cleared to send").model_dump()
    else:
        todo = [candidates[i] for i in shortlist if i in candidates and candidates[i].get("outreach_draft")][:GUARD_MAX]
        if todo:
            yield AgentStep(step="guard", message=f"Send Guard checking {len(todo)} shortlisted draft(s) before anything could leave...").model_dump()
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

            for fut in asyncio.as_completed([one(c) for c in todo]):
                c, v = await fut
                if v is None:
                    guarded[c["id"]] = "block"
                    c["guard"] = {"decision": "block", "checks": [], "ledger_entry": None, "error": "guard timed out"}
                    msg = f"{c.get('name')}: blocked (guard could not finish, fail closed)"
                else:
                    guarded[c["id"]] = v.decision
                    c["guard"] = {"decision": v.decision, "checks": [k.model_dump() for k in v.checks], "ledger_entry": v.ledger_entry}
                    msg = (f"{c.get('name')}: cleared to send (not sent: event rule)" if v.decision == "allow"
                           else f"{c.get('name')}: blocked, {_failures(v)}")
                yield AgentStep(step="guard", message=msg, data={"candidate_id": c["id"], **c["guard"]}).model_dump()
                yield {"type": "candidate", "candidate": c, "ts": datetime.now(timezone.utc).isoformat()}

    sources = [cl.get("source") for c in candidates.values() for cl in c.get("claims") or [] if cl.get("source")]
    entry = ledger.append("run.finished", {
        "agent_id": agent_id, "brief_sha256": brief_sha, "summary": summary,
        "shortlist": [{"id": i, "name": candidates[i].get("name"), "score": candidates[i].get("score")} for i in shortlist if i in candidates],
        "guard": guarded,
    }, sources[:200])
    if done_ev:
        done_ev.setdefault("summary", {})["ledger_entry"] = entry
        done_ev["summary"]["agent_id"] = agent_id
        yield done_ev


async def _sse(brief: str, agent_id: str):
    import json
    async for d in run_as_agent(brief, agent_id):
        yield f"data: {json.dumps(d, default=str)}\n\n"


@router.post("/agents/{agent_id}/run")
async def run_post(agent_id: str, req: RunRequest):
    return StreamingResponse(_sse(req.brief, agent_id), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/agents/{agent_id}/run")
async def run_get(agent_id: str, brief: str = Query(..., min_length=1)):
    return StreamingResponse(_sse(brief, agent_id), media_type="text/event-stream", headers=SSE_HEADERS)


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


@router.post("/verify_resume", response_model=ResumeResponse)
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
