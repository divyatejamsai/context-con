"""HTTP routes for the AI Employee registry (WS8). WS6's api.py includes `router` under /api automatically.
Demo sponsors for the onboarding form come from WS6's GET /api/passport/scenarios.
Who may call what (app/accounts/authz.py): reads need viewer, /send needs member, every other POST/PUT needs admin,
once auth is on. A signed-in user only sees and touches their own workspace's agents (others 404).

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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import registry
from .models import Scope, Sponsor

from ..accounts import authz
from ..accounts.authz import require_admin, require_operate, require_read

router = APIRouter(prefix="/agents", tags=["agents"])
admin = [Depends(require_admin)]
operate = [Depends(require_operate)]


class OnboardBody(BaseModel):
    name: str
    role: str = "recruiter"
    sponsor: Sponsor
    scopes: list[Scope] | None = None
    days: int = Field(30, ge=1, le=365)
    job: str | None = None
    runtime: str = "in-house"
    assignees: list[str] = Field(default_factory=list)  # user ids of the recruiters who work with it


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


def _by(sent: str) -> str:
    """The signed-in person's email when there is one; the client's free-text label otherwise (open mode)."""
    p = authz.current()
    return p.label(sent) if p else sent


class AssigneesBody(BaseModel):
    user_ids: list[str]


def _members_only(p, user_ids: list[str]) -> list[str]:
    """Only people in the caller's company can be assigned (the operator may assign anyone)."""
    if not user_ids or p is None or not p.scoped:
        return list(user_ids)
    from ..accounts.api import store
    ok = {m["id"] for m in store().members(p.workspace_id)}
    bad = [u for u in user_ids if u not in ok]
    if bad:
        raise HTTPException(400, f"not in your company: {', '.join(bad)}")
    return list(user_ids)


def _client():
    from .api import crustdata  # WS6's shared client; None offline, where checks fall back to fixtures
    return crustdata()


def _bad(e: registry.RegistryError):
    return HTTPException(404 if str(e).startswith("no AI employee") else 400, str(e))


@router.post("", dependencies=admin)
async def onboard(body: OnboardBody):
    p = authz.current()
    try:
        agent = registry.onboard(body.name, body.role, body.sponsor, body.scopes, days=body.days, job=body.job,
                                 runtime=body.runtime, workspace_id=p.workspace_id if p else None,
                                 assignees=_members_only(p, body.assignees))
    except registry.RegistryError as e:
        raise _bad(e)
    verdict = await registry.recheck(agent["agent_id"], _client())
    agent = registry.get_agent(agent["agent_id"])
    return {"agent": agent, "passport": agent["passport"], "verdict": verdict}


@router.get("")
async def list_agents(p=Depends(require_read)):
    return [{**a, "frozen_by": registry.frozen_by(a["agent_id"]) if a["status"] == "suspended" else []}
            for a in registry.list_agents() if authz.sees_agent(p, a)]


@router.post("/recheck", dependencies=admin)
async def recheck_all():
    ids = authz.visible_agent_ids()
    return await registry.recheck_all(_client(), only=ids)


@router.get("/roles")
async def roles():  # public: the role templates and scope names hold no customer data
    return {"roles": registry.roles(), "scopes": registry.ALL_SCOPES}


@router.get("/{agent_id}")
async def get_agent(agent_id: str, p=Depends(require_read)):
    authz.check_agent(agent_id, p)
    try:
        return {**registry.get_agent(agent_id), "scorecard": registry.scorecard(agent_id),
                "frozen_by": registry.frozen_by(agent_id)}
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/recheck", dependencies=admin)
async def recheck(agent_id: str):
    authz.check_agent(agent_id)
    try:
        c = _client()
        v = await registry.recheck(agent_id, c)
        return {"agent": registry.get_agent(agent_id), "verdict": v}
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/suspend", dependencies=admin)
async def suspend(agent_id: str, body: ReasonBody):
    authz.check_agent(agent_id)
    try:
        return registry.suspend(agent_id, body.reason, by=_by(body.by))
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/reinstate", dependencies=admin)
async def reinstate(agent_id: str):
    authz.check_agent(agent_id)
    try:
        c = _client()
        agent, v = await registry.reinstate(agent_id, c)
        return {"agent": agent, "verdict": v}
    except registry.Frozen as e:
        raise HTTPException(409, str(e))
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/offboard", dependencies=admin)
async def offboard(agent_id: str, body: ReasonBody):
    authz.check_agent(agent_id)
    try:
        return registry.offboard(agent_id, body.reason, by=_by(body.by))
    except registry.RegistryError as e:
        raise _bad(e)


@router.put("/{agent_id}/scopes", dependencies=admin)
async def set_scopes(agent_id: str, body: ScopesBody):
    authz.check_agent(agent_id)
    try:
        c = _client()
        agent, v = await registry.set_scopes(agent_id, body.scopes, c, by=_by(body.by))
        return {"agent": agent, "verdict": v}
    except registry.ScopeDenied as e:
        return JSONResponse(status_code=403, content={"detail": str(e), "verdict": e.verdict.model_dump()})
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/reviews", dependencies=admin)
async def review(agent_id: str, body: ReviewBody):
    authz.check_agent(agent_id)
    try:
        c = _client()
        return await registry.add_review(agent_id, _by(body.reviewer), body.decision, body.notes, body.scopes, c)
    except registry.RegistryError as e:
        raise _bad(e)


@router.put("/{agent_id}/assignees", dependencies=admin)
async def set_assignees(agent_id: str, body: AssigneesBody):
    authz.check_agent(agent_id)
    try:
        return registry.set_assignees(agent_id, _members_only(authz.current(), body.user_ids), by=_by("admin"))
    except registry.RegistryError as e:
        raise _bad(e)


@router.post("/{agent_id}/send", dependencies=operate)
async def send(agent_id: str, body: SendBody):
    authz.check_agent(agent_id)
    try:
        v, sent = await registry.send(agent_id, body.to, body.body, body.scope, _client(), signed_body=body.signed_body)
        return {"verdict": v, "sent": sent}
    except registry.RegistryError as e:
        raise _bad(e)
