"""Workspace members and roles (roles are defined in authz.py). Mounted in app/main.py.

GET    /api/workspace                    the caller's workspace, their role, what each role can do, and the auth mode
GET    /api/workspace/members            everyone in the caller's workspace (viewer+)
PUT    /api/workspace/members/{user_id}  {role}: owner only; a workspace always keeps one owner
DELETE /api/workspace/members/{user_id}  admin+ (only an owner can remove an owner); signs them out everywhere

These need a company session (Bearer token): the admin token has no workspace of its own.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..agents import ledger
from . import authz
from .api import store
from .authz import ROLES, Principal, require_admin, require_owner, require_read
from .store import AuthError

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

CAN = {
    "viewer": "See agents, the ledger, tasks and receipts; export the audit log.",
    "member": "Also assign work, approve or reject sends, pause and resume agents, run an agent.",
    "admin": "Also onboard, change scopes, suspend, reinstate, offboard, enroll outside agents, run payroll.",
    "owner": "Also change anyone's role.",
}


class RoleBody(BaseModel):
    role: str


def _session(p: Principal) -> Principal:
    if not p.scoped:
        raise HTTPException(400, "log in as a workspace user: the admin token isn't tied to a workspace")
    return p


@router.get("")
async def workspace(p: Principal = Depends(require_read)):
    return {"auth_mode": authz.mode(), "via": p.via, "role": p.role, "company": p.company,
            "roles": [{"role": r, "can": CAN[r]} for r in ROLES]}


@router.get("/members")
async def members(p: Principal = Depends(require_read)):
    _session(p)
    return {"members": store().members(p.workspace_id)}


@router.put("/members/{user_id}")
async def set_role(user_id: str, body: RoleBody, p: Principal = Depends(require_owner)):
    _session(p)
    if body.role not in ROLES:
        raise HTTPException(400, f"role is one of {', '.join(ROLES)}")
    try:
        before = next((m for m in store().members(p.workspace_id) if m["id"] == user_id), None)
        user = store().set_role(p.workspace_id, user_id, body.role)
    except AuthError as e:
        raise HTTPException(e.status, e.message)
    ledger.append("workspace.role_changed", {"workspace_id": p.workspace_id, "user_id": user_id, "email": user["email"],
                                             "from": (before or {}).get("workspace_role"), "to": body.role})
    return user


@router.delete("/members/{user_id}")
async def remove(user_id: str, p: Principal = Depends(require_admin)):
    _session(p)
    target = next((m for m in store().members(p.workspace_id) if m["id"] == user_id), None)
    if target is None:
        raise HTTPException(404, "No such member in this workspace.")
    if target["workspace_role"] == "owner" and p.role != "owner":
        raise HTTPException(403, "only an owner can remove an owner")
    try:
        gone = store().remove_member(p.workspace_id, user_id)
    except AuthError as e:
        raise HTTPException(e.status, e.message)
    ledger.append("workspace.member_removed", {"workspace_id": p.workspace_id, "user_id": user_id, "email": gone["email"]})
    return {"removed": gone}
