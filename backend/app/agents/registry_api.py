"""HTTP routes for the AI Employee registry (WS8). WS6's api.py includes `router` under /api automatically.
Demo sponsors for the onboarding form come from WS6's GET /api/passport/scenarios.
Every POST/PUT needs x-admin-token when COUNTERSIGN_ADMIN_TOKEN is set; GETs are public.

POST /api/agents                        onboard  {name, role, sponsor, scopes?, days?} -> {agent, passport, verdict}
GET  /api/agents                        list
POST /api/agents/recheck                payroll run -> list[Verdict]
GET  /api/agents/roles                  role templates + every scope
GET  /api/agents/{id}                   one agent + its scorecard
POST /api/agents/{id}/recheck           live check of one agent -> {agent, verdict}
POST /api/agents/{id}/suspend           {reason}
POST /api/agents/{id}/reinstate         -> {agent, verdict}; stays suspended if the check fails
POST /api/agents/{id}/offboard          {reason}
PUT  /api/agents/{id}/scopes            {scopes} -> {agent, verdict}; 403 + verdict when the sponsor can't grant them
POST /api/agents/{id}/reviews           {reviewer, decision, notes?, scopes?}
POST /api/agents/{id}/send              {to, body, scope, signed_body?} -> {verdict, sent}; signs with the agent's key, runs the Send Guard
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import registry
from .models import Scope, Sponsor

def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Changing the registry needs COUNTERSIGN_ADMIN_TOKEN (header x-admin-token) when it is set, the same rule as
    passport issue/revoke. Unset = local dev, open. Reads stay public."""
    want = os.getenv("COUNTERSIGN_ADMIN_TOKEN")
    if want and not (x_admin_token and hmac.compare_digest(x_admin_token, want)):
        raise HTTPException(401, "admin token required (x-admin-token)")


router = APIRouter(prefix="/agents", tags=["agents"])
admin = [Depends(require_admin)]


class OnboardBody(BaseModel):
    name: str
    role: str = "recruiter"
    sponsor: Sponsor
    scopes: list[Scope] | None = None
    days: int = Field(30, ge=1, le=365)
    job: str | None = None
    runtime: str = "in-house"


class ReasonBody(BaseModel):
    reason: str = ""
    by: str = "sponsor"


class ScopesBody(BaseModel):
    scopes: list[Scope]
    by: str = "sponsor"


class SendBody(BaseModel):
    to: dict  # {name, profile_url, company}
    body: str
    scope: Scope = "outreach.hiring"
    signed_body: str | None = None  # demo: sign this text but send `body`


class ReviewBody(BaseModel):
    reviewer: str = "sponsor"
    decision: registry.ReviewDecision
    notes: str = ""
    scopes: list[Scope] | None = None


def _client():
    from .api import crustdata  # WS6's shared client; None offline, where checks fall back to fixtures
    return crustdata()


def _bad(e: registry.RegistryError):
    return HTTPException(404 if str(e).startswith("no AI employee") else 400, str(e))


@router.post("", dependencies=admin)
async def onboard(body: OnboardBody):
    try:
        agent = registry.onboard(body.name, body.role, body.sponsor, body.scopes, days=body.days, job=body.job,
                                 runtime=body.runtime)
    except registry.RegistryError as e:
        raise _bad(e)
    verdict = await registry.recheck(agent["agent_id"], _client())
    agent = registry.get_agent(agent["agent_id"])
    return {"agent": agent, "passport": agent["passport"], "verdict": verdict}


@router.get("")
async def list_agents():
    return registry.list_agents()


@router.post("/recheck", dependencies=admin)
async def recheck_all():
    return await registry.recheck_all(_client())


@router.get("/roles")
async def roles():
    return {"roles": registry.roles(), "scopes": registry.ALL_SCOPES}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    try:
        return {**registry.get_agent(agent_id), "scorecard": registry.scorecard(agent_id)}
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/recheck", dependencies=admin)
async def recheck(agent_id: str):
    try:
        c = _client()
        v = await registry.recheck(agent_id, c)
        return {"agent": registry.get_agent(agent_id), "verdict": v}
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/suspend", dependencies=admin)
async def suspend(agent_id: str, body: ReasonBody):
    try:
        return registry.suspend(agent_id, body.reason, by=body.by)
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/reinstate", dependencies=admin)
async def reinstate(agent_id: str):
    try:
        c = _client()
        agent, v = await registry.reinstate(agent_id, c)
        return {"agent": agent, "verdict": v}
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/offboard", dependencies=admin)
async def offboard(agent_id: str, body: ReasonBody):
    try:
        return registry.offboard(agent_id, body.reason, by=body.by)
    except registry.RegistryError as e:
        raise _bad(e)


@router.put("/{agent_id}/scopes", dependencies=admin)
async def set_scopes(agent_id: str, body: ScopesBody):
    try:
        c = _client()
        agent, v = await registry.set_scopes(agent_id, body.scopes, c, by=body.by)
        return {"agent": agent, "verdict": v}
    except registry.ScopeDenied as e:
        return JSONResponse(status_code=403, content={"detail": str(e), "verdict": e.verdict.model_dump()})
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/reviews", dependencies=admin)
async def review(agent_id: str, body: ReviewBody):
    try:
        c = _client()
        return await registry.add_review(agent_id, body.reviewer, body.decision, body.notes, body.scopes, c)
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/send", dependencies=admin)
async def send(agent_id: str, body: SendBody):
    try:
        v, sent = await registry.send(agent_id, body.to, body.body, body.scope, _client(), signed_body=body.signed_body)
        return {"verdict": v, "sent": sent}
    except registry.RegistryError as e:
        raise _bad(e)
