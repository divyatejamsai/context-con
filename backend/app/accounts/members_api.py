"""Workspace members and roles (roles are defined in authz.py). Mounted in app/main.py.

GET    /api/workspace                    the caller's workspace, their role, what each role can do, and the auth mode
GET    /api/workspace/members            everyone in the caller's workspace (admin+)
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
from .authz import ROLES, Principal, require_admin, require_audit, require_owner, require_read
from .store import AuthError

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

CAN = {
    "viewer": "See the AI employees assigned to you, their tasks and approvals. Read-only.",
    "member": "A recruiter: work with the AI employees assigned to you: assign tasks, approve or reject their sends, "
              "pause and resume them, run Sourced.",
    "admin": "Everything in your company: every AI employee, the ledger and audit export, members, onboarding, "
             "scopes, suspensions, outside-agent enrollment, payroll.",
    "owner": "Also change anyone's role in your company.",
    "operator": "Runs the Agaxes platform: sees every company, its people and its AI employees.",
}


class RoleBody(BaseModel):
    role: str


def _session(p: Principal) -> Principal:
    # Any signed-in user with a workspace, including the platform operator in its own company. The admin token and
    # open access have no workspace.
    if p.via != "session" or not p.workspace_id:
        raise HTTPException(400, "log in as a workspace user: the admin token isn't tied to a workspace")
    return p


@router.get("")
async def workspace(p: Principal = Depends(require_read)):
    return {"auth_mode": authz.mode(), "via": p.via, "role": p.role, "company": p.company, "access": p.access(),
            "roles": [{"role": r, "can": CAN[r]} for r in (*ROLES, "operator")]}


@router.get("/members")
async def members(p: Principal = Depends(require_audit)):
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


# ---- the platform operator's view: every company ------------------------------------------------------------------

platform = APIRouter(prefix="/api/platform", tags=["platform"])


class WorkspaceBody(BaseModel):
    workspace_id: str | None


@platform.get("/companies")
async def companies(p: Principal = Depends(authz.require_operator)):
    """Every company on the platform, its people and its AI employees. Operator only."""
    from ..agents import registry
    s = store()
    agents = registry.list_agents()
    rows = s._db.execute("SELECT * FROM companies ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        c = dict(r)
        mine = [a for a in agents if a.get("workspace_id") == c["id"]]
        out.append({"id": c["id"], "name": c["name"], "domain": c["domain"], "verified_via": c["verified_via"],
                    "created_at": c["created_at"], "members": s.members(c["id"]),
                    "agents": [{"agent_id": a["agent_id"], "name": a["name"], "status": a["status"]} for a in mine]})
    unowned = [{"agent_id": a["agent_id"], "name": a["name"], "status": a["status"]}
               for a in agents if not a.get("workspace_id")]
    return {"companies": out, "unassigned_agents": unowned}


@platform.put("/agents/{agent_id}/workspace")
async def move_agent(agent_id: str, body: WorkspaceBody, p: Principal = Depends(authz.require_operator)):
    """Place an agent in a company (or back on the platform with null). Operator only."""
    from ..agents import registry
    if body.workspace_id and not s_company(body.workspace_id):
        raise HTTPException(404, "no such company")
    try:
        return registry.set_workspace(agent_id, body.workspace_id, by=p.label("operator"))
    except registry.RegistryError as e:
        raise HTTPException(404, str(e))


def s_company(cid: str) -> dict | None:
    row = store()._db.execute("SELECT id FROM companies WHERE id = ?", (cid,)).fetchone()
    return dict(row) if row else None
