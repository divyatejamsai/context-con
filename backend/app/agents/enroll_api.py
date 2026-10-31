"""Enrollment routes for outside agents (app/agents/enroll.py). Included by api.py under /api, before the registry
routes so /agents/enrollments isn't read as an agent id.

POST /api/agents/enrollments              admin   {name, role, sponsor, scopes?, days?, job?, ttl_minutes?}
                                                   -> {enrollment, token, command}; the token is shown once
GET  /api/agents/enrollments              admin   this workspace's enrollments (pending / used / expired / revoked)
POST /api/agents/enrollments/{id}/revoke  admin
POST /api/agents/enroll                   the agent, with the token: {token, public_key, proof} -> {agent, passport, verdict}
POST /api/agents/{id}/rotate_key          the agent, signed with its current key and the new one
GET  /api/passport/{agent_id}             public: the agent's current passport (a credential it shows to others)
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..accounts import authz
from ..accounts.authz import Principal, require_admin
from . import enroll, ledger, registry
from .models import Scope, Sponsor

router = APIRouter(tags=["enrollment"])


class EnrollmentBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = "researcher"
    sponsor: Sponsor
    scopes: list[Scope] | None = None
    days: int = Field(30, ge=1, le=365)
    job: str | None = Field(default=None, max_length=300)
    ttl_minutes: int = Field(60, ge=1, le=enroll.MAX_TTL_MINUTES)


class EnrollBody(BaseModel):
    token: str = Field(max_length=200)
    public_key: str = Field(max_length=100)
    proof: str = Field(max_length=200)


class RotateBody(BaseModel):
    new_public_key: str = Field(max_length=100)
    ts: int
    signature: str = Field(max_length=200)       # current key, over enroll.rotate_text(...) (passport.sign_message)
    new_key_proof: str = Field(max_length=200)   # new key, over the same text, same framing


def _err(e: enroll.EnrollError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _api_url() -> str:
    return (os.getenv("PUBLIC_API_URL") or "http://localhost:8000").rstrip("/")


@router.post("/agents/enrollments")
async def create_enrollment(body: EnrollmentBody, p: Principal = Depends(require_admin)):
    try:
        row, token = enroll.create(name=body.name, role=body.role, sponsor=body.sponsor, scopes=body.scopes,
                                   days=body.days, job=body.job, ttl_minutes=body.ttl_minutes,
                                   workspace_id=p.workspace_id, created_by=p.label("admin"))
    except enroll.EnrollError as e:
        raise _err(e)
    cmd = f"AGAXES_API_URL={_api_url()} python backend/scripts/agaxes_agent.py enroll {token}"
    return {"enrollment": row, "token": token, "command": cmd,
            "note": "Give this to the agent's operator. It works once, until expires_at. Agaxes never sees the "
                    "agent's private key: the agent makes it and keeps it on its own machine."}


@router.get("/agents/enrollments")
async def list_enrollments(p: Principal = Depends(require_admin)):
    return enroll.list_all(p.workspace_id, scoped=p.scoped)


@router.post("/agents/enrollments/{enrollment_id}/revoke")
async def revoke_enrollment(enrollment_id: str, p: Principal = Depends(require_admin)):
    try:
        return enroll.revoke(enrollment_id, p.label("admin"), p.workspace_id, scoped=p.scoped)
    except enroll.EnrollError as e:
        raise _err(e)


@router.post("/agents/enroll")
async def enroll_agent(body: EnrollBody):
    """No session: the one-time token plus proof of the key is the credential."""
    try:
        row = enroll.claim(body.token, body.public_key, body.proof)
    except enroll.EnrollError as e:
        raise _err(e)
    authz.CURRENT.set(Principal(via="enrollment", role="admin", extra={
        "enrollment_id": row["enrollment_id"], "approved_by": row["created_by"], "workspace_id": row["workspace_id"]}))
    try:
        agent = registry.onboard(row["name"], row["role"], Sponsor(**row["sponsor"]), row["scopes"], days=row["days"],
                                 job=row["job"], runtime="external", workspace_id=row["workspace_id"],
                                 public_key=row["public_key"])
    except registry.RegistryError as e:
        enroll.release(row["enrollment_id"])
        raise HTTPException(400, str(e))
    enroll.finish(row["enrollment_id"], agent["agent_id"])
    ledger.append("agent.enrolled", {"agent_id": agent["agent_id"], "enrollment_id": row["enrollment_id"],
                                     "public_key": row["public_key"], "key_custody": "agent"})
    from .api import crustdata
    verdict = await registry.recheck(agent["agent_id"], crustdata())
    from . import connect
    connect.on_enrolled(row["enrollment_id"], agent["agent_id"], verdict.model_dump())  # tools, owner, budgets
    agent = registry.get_agent(agent["agent_id"])
    return {"agent": agent, "passport": agent["passport"], "verdict": verdict}


@router.post("/agents/{agent_id}/rotate_key")
async def rotate_key(agent_id: str, body: RotateBody):
    from ..runtime.external import AgentAuthError, authenticate
    from .models import Passport
    from .passport import normalise_public_key, verify_message_signature
    try:
        new_pk = normalise_public_key(body.new_public_key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    text = enroll.rotate_text(agent_id, body.ts, new_pk)
    try:
        cur = registry.get_agent(agent_id)
    except registry.RegistryError:
        raise HTTPException(401, f"unknown agent {agent_id}")
    probe = Passport(**{**cur["passport"], "public_key": new_pk})
    if not verify_message_signature(probe, text, body.new_key_proof):  # before the old-key check burns the signature
        raise HTTPException(401, "new_key_proof doesn't match the new key")
    try:
        rec = authenticate("rotate_key", agent_id, None, body.ts, new_pk, body.signature)
    except AgentAuthError as e:
        raise HTTPException(401, str(e))
    authz.CURRENT.set(Principal(via="agent", role="viewer", extra={"agent_id": agent_id,
                                                                    "workspace_id": rec.get("workspace_id")}))
    try:
        agent = registry.rotate_key(agent_id, new_pk, by=f"agent {agent_id} (signed with its old key)")
    except registry.RegistryError as e:
        raise HTTPException(400, str(e))
    return {"agent": agent, "passport": agent["passport"]}


@router.get("/passport/{agent_id}")
async def current_passport(agent_id: str):
    try:
        a = registry.get_agent(agent_id)
    except registry.RegistryError as e:
        raise HTTPException(404, str(e))
    return {"passport": a["passport"], "status": a["status"], "key_custody": a.get("key_custody", "agaxes")}
