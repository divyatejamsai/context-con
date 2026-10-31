"""Routes for connecting an agent (app/agents/connect.py). Included by api.py under /api.

GET  /api/connect/catalog                   public   agent types, templates, scopes with risk, tools, budget defaults
GET  /api/connect/people                    admin    company members who can own an agent (role checked)
POST /api/connect/sponsor/find              admin    {name, company, scopes?} -> Crustdata Person Search matches
POST /api/connect/sponsor/check             admin    {profile_url, company, scopes?} -> Person Enrich: works there? can grant?
POST /api/connect/requests                  admin    the whole form -> a connection request (pending_review | approved)
GET  /api/connect/requests                  admin    this company's requests, newest first
GET  /api/connect/requests/{id}             admin
POST /api/connect/requests/{id}/approve     admin    {note?}: not the requester while another admin exists
POST /api/connect/requests/{id}/reject      admin    {note?}
POST /api/connect/requests/{id}/issue       admin    passport (template) or one-time enrollment command (outside agent)
POST /api/connect/requests/{id}/test        admin    live connection test: the agent's first signed call
POST /api/connect/requests/{id}/cancel      admin
POST /api/agents/heartbeat                  the agent, signed with its own key: {agent_id, ts, text, signature}
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..accounts import authz
from ..accounts.authz import Principal, require_admin
from . import connect, enroll
from .models import Scope

router = APIRouter(tags=["connect"])
OWNER_ROLES = ("member", "admin", "owner")


def _client():
    from .api import crustdata
    return crustdata()


def _err(e: connect.ConnectError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _api_url() -> str:
    return (os.getenv("PUBLIC_API_URL") or "http://localhost:8000").rstrip("/")


def _members(p: Principal | None) -> list[dict] | None:
    """The caller's company members, or None when there are no accounts (open mode, admin token)."""
    if p is None or p.via != "session" or not p.workspace_id:
        return None
    from ..accounts.api import store
    return store().members(p.workspace_id)


def _ws(p: Principal | None) -> tuple[str | None, bool]:
    return (p.workspace_id if p else None), bool(p and p.scoped)


@router.get("/connect/catalog")
async def catalog():
    return connect.catalog()


@router.get("/connect/people")
async def people(p: Principal = Depends(require_admin)):
    ms = _members(p)
    me = p.user["id"] if p and p.user else None
    if ms is None:
        return {"members": [], "me": None, "company": None,
                "note": "No company accounts in this mode: name the sponsor directly."}
    out = [{"user_id": m["id"], "name": m.get("full_name") or m["email"], "email": m["email"],
            "job_role": m.get("job_role"), "workspace_role": m["workspace_role"],
            "can_own": m["workspace_role"] in OWNER_ROLES,
            "why_not": None if m["workspace_role"] in OWNER_ROLES else "Viewers can't own an agent"} for m in ms]
    return {"members": out, "me": me, "company": p.company}


class FindBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    company: str = Field(min_length=1, max_length=160)
    scopes: list[Scope] | None = None


class CheckBody(BaseModel):
    profile_url: str = Field(min_length=8, max_length=300)
    company: str = Field(min_length=1, max_length=160)
    scopes: list[Scope] | None = None


@router.post("/connect/sponsor/find", dependencies=[Depends(require_admin)])
async def sponsor_find(body: FindBody):
    return await connect.find_sponsor(_client(), body.name, body.company, body.scopes)


@router.post("/connect/sponsor/check", dependencies=[Depends(require_admin)])
async def sponsor_check(body: CheckBody):
    return await connect.check_sponsor(_client(), body.profile_url, body.company, body.scopes)


class SponsorIn(BaseModel):
    name: str
    profile_url: str
    company: str
    company_domain: str | None = None
    title: str | None = None


class RequestBody(BaseModel):
    agent_type: str
    template: str | None = None
    name: str = Field(min_length=1, max_length=80)
    job: str | None = Field(default=None, max_length=300)
    role: str | None = None
    scopes: list[Scope]
    tools: list[str] = Field(default_factory=list)
    budget: dict[str, int] | None = None
    require_approval: bool = True
    days: int = Field(30, ge=1, le=365)
    ttl_minutes: int = Field(60, ge=1, le=enroll.MAX_TTL_MINUTES)
    owner_user_id: str | None = None
    sponsor: SponsorIn
    sponsor_check: dict | None = None


class NoteBody(BaseModel):
    note: str = Field("", max_length=500)


@router.post("/connect/requests")
async def create_request(body: RequestBody, p: Principal = Depends(require_admin)):
    ms = _members(p)
    owner = None
    if ms is not None:
        if not body.owner_user_id:
            raise HTTPException(400, "pick the person in your company who owns this agent")
        m = next((x for x in ms if x["id"] == body.owner_user_id), None)
        if m is None:
            raise HTTPException(400, "the owner has to be a member of your company")
        if m["workspace_role"] not in OWNER_ROLES:
            raise HTTPException(400, f"{m.get('full_name') or m['email']} is a viewer: viewers can't own an agent")
        owner = {"user_id": m["id"], "name": m.get("full_name") or m["email"], "email": m["email"],
                 "workspace_role": m["workspace_role"], "job_role": m.get("job_role")}
    ws, _ = _ws(p)
    try:
        return connect.create(
            agent_type=body.agent_type, template=body.template, name=body.name, job=body.job, role=body.role,
            scopes=list(body.scopes), tools=body.tools, budget=body.budget, require_approval=body.require_approval,
            days=body.days, sponsor=body.sponsor.model_dump(), sponsor_check=body.sponsor_check, owner=owner,
            workspace_id=ws, requested_by=p.label("admin") if p else "admin",
            requested_by_id=p.user["id"] if p and p.user else None, ttl_minutes=body.ttl_minutes)
    except connect.ConnectError as e:
        raise _err(e)


@router.get("/connect/requests")
async def list_requests(p: Principal = Depends(require_admin)):
    return connect.list_all(*_ws(p))


@router.get("/connect/requests/{request_id}")
async def get_request(request_id: str, p: Principal = Depends(require_admin)):
    try:
        return connect.get(request_id, *_ws(p))
    except connect.ConnectError as e:
        raise _err(e)


async def _decide(request_id: str, decision: str, body: NoteBody | None, p: Principal | None):
    ms = _members(p)
    admins = [m for m in ms if m["workspace_role"] in ("admin", "owner")] if ms is not None else None
    try:
        return connect.decide(request_id, decision, by=p.label("admin") if p else "admin",
                              by_id=p.user["id"] if p and p.user else None, admins=admins,
                              note=(body.note if body else ""), workspace_id=_ws(p)[0], scoped=_ws(p)[1])
    except connect.ConnectError as e:
        raise _err(e)


@router.post("/connect/requests/{request_id}/approve")
async def approve(request_id: str, body: NoteBody | None = None, p: Principal = Depends(require_admin)):
    return await _decide(request_id, "approve", body, p)


@router.post("/connect/requests/{request_id}/reject")
async def reject(request_id: str, body: NoteBody | None = None, p: Principal = Depends(require_admin)):
    return await _decide(request_id, "reject", body, p)


@router.post("/connect/requests/{request_id}/issue")
async def issue(request_id: str, p: Principal = Depends(require_admin)):
    try:
        return await connect.issue(request_id, _client(), by=p.label("admin") if p else "admin", api_url=_api_url(),
                                   workspace_id=_ws(p)[0], scoped=_ws(p)[1])
    except connect.ConnectError as e:
        raise _err(e)


@router.post("/connect/requests/{request_id}/test")
async def test(request_id: str, p: Principal = Depends(require_admin)):
    try:
        return await connect.test(request_id, *_ws(p))
    except connect.ConnectError as e:
        raise _err(e)


@router.post("/connect/requests/{request_id}/cancel")
async def cancel(request_id: str, p: Principal = Depends(require_admin)):
    try:
        return connect.cancel(request_id, p.label("admin") if p else "admin", *_ws(p))
    except connect.ConnectError as e:
        raise _err(e)


class HeartbeatBody(BaseModel):
    agent_id: str
    ts: int
    text: str = Field("", max_length=500)
    signature: str = Field(max_length=200)


@router.post("/agents/heartbeat")
async def heartbeat(body: HeartbeatBody):
    """No session: the signature with the agent's own key is the credential (runtime/external.py framing)."""
    from ..runtime.external import AgentAuthError, authenticate
    try:
        rec = authenticate("heartbeat", body.agent_id, None, body.ts, body.text, body.signature)
    except AgentAuthError as e:
        raise HTTPException(401, str(e))
    authz.CURRENT.set(Principal(via="agent", role="viewer", extra={"agent_id": body.agent_id,
                                                                    "workspace_id": rec.get("workspace_id")}))
    return connect.record_heartbeat(rec, body.text, via="agent")
