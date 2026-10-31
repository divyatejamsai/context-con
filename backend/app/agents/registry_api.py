"""HTTP routes for the AI Employee registry (WS8). WS6's api.py includes `router` under /api automatically.
Demo sponsors for the onboarding form come from WS6's GET /api/passport/scenarios.

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
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import registry
from .models import Scope, Sponsor

router = APIRouter(prefix="/agents", tags=["agents"])


class OnboardBody(BaseModel):
    name: str
    role: str = "recruiter"
    sponsor: Sponsor
    scopes: list[Scope] | None = None
    days: int = Field(30, ge=1, le=365)


class ReasonBody(BaseModel):
    reason: str = ""
    by: str = "sponsor"


class ScopesBody(BaseModel):
    scopes: list[Scope]
    by: str = "sponsor"


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


@router.post("")
async def onboard(body: OnboardBody):
    try:
        agent = registry.onboard(body.name, body.role, body.sponsor, body.scopes, days=body.days)
    except registry.RegistryError as e:
        raise _bad(e)
    verdict = await registry.recheck(agent["agent_id"], _client())
    agent = registry.get_agent(agent["agent_id"])
    return {"agent": agent, "passport": agent["passport"], "verdict": verdict}


@router.get("")
async def list_agents():
    return registry.list_agents()


@router.post("/recheck")
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


@router.post("/{agent_id}/recheck")
async def recheck(agent_id: str):
    try:
        c = _client()
        v = await registry.recheck(agent_id, c)
        return {"agent": registry.get_agent(agent_id), "verdict": v}
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/suspend")
async def suspend(agent_id: str, body: ReasonBody):
    try:
        return registry.suspend(agent_id, body.reason, by=body.by)
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/reinstate")
async def reinstate(agent_id: str):
    try:
        c = _client()
        agent, v = await registry.reinstate(agent_id, c)
        return {"agent": agent, "verdict": v}
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/offboard")
async def offboard(agent_id: str, body: ReasonBody):
    try:
        return registry.offboard(agent_id, body.reason, by=body.by)
    except registry.RegistryError as e:
        raise _bad(e)


@router.put("/{agent_id}/scopes")
async def set_scopes(agent_id: str, body: ScopesBody):
    try:
        c = _client()
        agent, v = await registry.set_scopes(agent_id, body.scopes, c, by=body.by)
        return {"agent": agent, "verdict": v}
    except registry.ScopeDenied as e:
        return JSONResponse(status_code=403, content={"detail": str(e), "verdict": e.verdict.model_dump()})
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/reviews")
async def review(agent_id: str, body: ReviewBody):
    try:
        c = _client()
        return await registry.add_review(agent_id, body.reviewer, body.decision, body.notes, body.scopes, c)
    except registry.RegistryError as e:
        raise _bad(e)
