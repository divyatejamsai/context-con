"""Who is calling, what they may do, and which workspace they see. One place for every Agaxes route.

A caller is one of:
  - a company user, by session token (Authorization: Bearer <token> from /api/auth/login), with a workspace role;
  - the operator, by COUNTERSIGN_ADMIN_TOKEN (x-admin-token, or ?token= on EventSource GETs), which sees everything;
  - nobody: allowed for everything while auth is open (local dev and the demo: no admin token, AGAXES_REQUIRE_LOGIN
    unset), and for reads only when just the admin token is set (the behaviour before accounts existed).

Roles, lowest to highest. Each one can do everything the roles below it can:
  viewer  read the console: agents, ledger, tasks, receipts, audit export
  member  run the work: assign tasks, approve or reject sends, pause and resume, run an agent, send an email
  admin   govern: onboard, change scopes, suspend, reinstate, offboard, enrollment links, policies, payroll
  owner   everything, plus changing other people's roles

Every ledger entry written while a request is being served carries the caller (`actor`), taken from the session,
so "who approved this" can't be typed in by the client. The free-text `by` fields stay as display labels.

Workspaces: an agent onboarded by a signed-in user belongs to that user's company. A signed-in user sees only
their company's agents and ledger entries. Agents onboarded before accounts existed (scripts, the fleet, Sourced)
have no workspace: they show to the operator, to the demo workspace, and to the workspace whose domain is
AGAXES_DEFAULT_WORKSPACE.
"""
from __future__ import annotations

import hmac
import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import Header, HTTPException, Query, Request

log = logging.getLogger(__name__)

ROLES = ("viewer", "member", "admin", "owner")
RANK = {r: i for i, r in enumerate(ROLES)}
NEEDS = {"read": "viewer", "operate": "member", "admin": "admin", "owner": "owner"}


@dataclass
class Principal:
    via: str                      # "session" | "admin_token" | "open" | "agent"
    role: str = "owner"
    user: dict | None = None
    company: dict | None = None
    extra: dict = field(default_factory=dict)

    @property
    def workspace_id(self) -> str | None:
        return (self.company or {}).get("id")

    @property
    def scoped(self) -> bool:
        """True when this caller must only see one workspace."""
        return self.via == "session"

    def can(self, perm: str) -> bool:
        return RANK.get(self.role, -1) >= RANK[NEEDS[perm]]

    def actor(self) -> dict:
        if self.via == "session":
            return {"via": "session", "user_id": self.user["id"], "email": self.user["email"], "role": self.role,
                    "workspace_id": self.workspace_id}
        return {"via": self.via, **self.extra}

    def label(self, fallback: str = "employer") -> str:
        """What to show in a `by` field: the signed-in person's email, else whatever the client sent."""
        return self.user["email"] if self.via == "session" else fallback


CURRENT: ContextVar[Principal | None] = ContextVar("agaxes_principal", default=None)


def current() -> Principal | None:
    return CURRENT.get()


def login_required() -> bool:
    """AGAXES_REQUIRE_LOGIN=1: every console read needs a session or the admin token too, not just the writes."""
    return os.getenv("AGAXES_REQUIRE_LOGIN", "0") == "1"


def enforced() -> bool:
    """Writes need a session or the admin token (an admin token alone keeps reads public, as before accounts)."""
    return bool(os.getenv("COUNTERSIGN_ADMIN_TOKEN")) or login_required()


def mode() -> str:
    return "login_required" if login_required() else "writes_protected" if enforced() else "open"


def _bearer(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def resolve(authorization: str | None, admin_token: str | None, perm: str = "admin") -> Principal | None:
    want = os.getenv("COUNTERSIGN_ADMIN_TOKEN")
    if want and admin_token and hmac.compare_digest(admin_token, want):
        return Principal(via="admin_token")
    tok = _bearer(authorization)
    if tok:
        from .api import store
        found = store().session_user(tok)
        if found:
            user, company, _ = found
            role = user.get("workspace_role") or "member"
            return Principal(via="session", role=role if role in RANK else "viewer", user=user, company=company)
        if enforced():
            raise HTTPException(401, "your session has ended: log in again")
    if not enforced() or (perm == "read" and not login_required()):
        return Principal(via="open")
    return None


def need(perm: str):
    """FastAPI dependency: the caller must hold `perm`. Sets CURRENT for the rest of the request."""
    if perm not in NEEDS:
        raise ValueError(perm)

    async def dep(request: Request, authorization: str | None = Header(default=None),
                  x_admin_token: str | None = Header(default=None), token: str | None = Query(default=None)) -> Principal:
        p = resolve(authorization, x_admin_token or token, perm)
        if p is None:
            raise HTTPException(401, "log in, or send the admin token (x-admin-token)")
        if not p.can(perm):
            raise HTTPException(403, f"your role ({p.role}) can't do this: it needs {NEEDS[perm]} or above")
        CURRENT.set(p)
        request.state.principal = p
        return p

    dep.__name__ = f"need_{perm}"
    return dep


require_read = need("read")
require_operate = need("operate")
require_admin = need("admin")
require_owner = need("owner")


# ---- workspaces ----------------------------------------------------------------------------------------------

def _default_workspace_ids() -> set[str]:
    """Workspaces that also see agents onboarded before accounts existed."""
    from .api import DEMO_EMAIL, store
    s = store()
    out = set()
    row = s.user_by_email(DEMO_EMAIL)
    if row:
        out.add(row["company_id"])
    dom = (os.getenv("AGAXES_DEFAULT_WORKSPACE") or "").strip().lower()
    if dom:
        c = s.company_by_domain(dom)
        if c:
            out.add(c["id"])
    return out


def sees_agent(p: Principal | None, agent: dict) -> bool:
    if p is None or not p.scoped:
        return True
    ws = agent.get("workspace_id")
    if ws:
        return ws == p.workspace_id
    return p.workspace_id in _default_workspace_ids()


def visible_agent_ids(p: Principal | None = None) -> set[str] | None:
    """None = no filter (operator / open mode). Otherwise the agent ids this caller may see."""
    p = p if p is not None else current()
    if p is None or not p.scoped:
        return None
    from ..agents import registry
    return {a["agent_id"] for a in registry.list_agents() if sees_agent(p, a)}


def check_agent(agent_id: str, p: Principal | None = None) -> None:
    """404 (not 403, so ids from other companies don't leak) when the caller can't see this agent."""
    ids = visible_agent_ids(p)
    if ids is not None and agent_id not in ids:
        raise HTTPException(404, f"no AI employee with id {agent_id}")


def entry_visible(row: dict, ids: set[str] | None, workspace_id: str | None) -> bool:
    if ids is None:
        return True
    actor = row.get("actor") or {}
    if workspace_id and actor.get("workspace_id") == workspace_id:
        return True
    pl = row.get("payload") or {}
    refs = {pl.get("agent_id"), pl.get("subject"), (pl.get("passport") or {}).get("agent_id")} - {None}
    return bool(refs & ids)
