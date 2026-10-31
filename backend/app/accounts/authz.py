"""Who is calling, what they may do, and which workspace they see. One place for every Agaxes route.

The hierarchy, top to bottom:

  PLATFORM  operator   Runs Agaxes itself. Sees every company, its people and its AI employees (GET /api/platform/*).
                       Signed in as an email in AGAXES_OPERATOR_EMAILS (or the demo operator), or by
                       COUNTERSIGN_ADMIN_TOKEN (x-admin-token, or ?token= on EventSource GETs).
  COMPANY   owner      Everything inside their own company, plus changing people's roles.
            admin      Their company's AI employees, ledger, audit export, members, enrollments, payroll.
  OWN WORK  member     A recruiter: only the AI employees assigned to them (agent.assignees), those agents' tasks and
                       approvals, running them and sending through them. No company-wide registry, ledger or members.
            viewer     The same view as a member, read-only.

A caller with no session is allowed everything while auth is open (local dev and the demo: no admin token,
AGAXES_REQUIRE_LOGIN unset), and reads only when just the admin token is set (the behaviour before accounts existed).

Every ledger entry written while a request is being served carries the caller (`actor`), taken from the session,
so "who approved this" can't be typed in by the client. The free-text `by` fields stay as display labels.

Workspaces: an agent onboarded by a signed-in user belongs to that user's company. Agents onboarded before accounts
existed (scripts, the seeded fleet) have no workspace: only the operator sees them, plus the workspace whose domain is
AGAXES_DEFAULT_WORKSPACE if set. The demo company is given its Sourced at demo sign-in (accounts/api.py).
"""
from __future__ import annotations

import hmac
import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import Header, HTTPException, Query, Request

log = logging.getLogger(__name__)

ROLES = ("viewer", "member", "admin", "owner")          # roles inside one company's workspace
RANK = {r: i for i, r in enumerate((*ROLES, "operator"))}  # operator: the platform, above every company
# audit = the company-wide ledger, export and member list: admins and owners, not recruiters.
NEEDS = {"read": "viewer", "operate": "member", "audit": "admin", "admin": "admin", "owner": "owner",
         "operator": "operator"}
OPERATOR_DEMO_EMAIL = "operator@agaxes-demo.dev"


def operator_emails() -> set[str]:
    """Platform operators: AGAXES_OPERATOR_EMAILS (comma-separated) plus the demo operator when demo accounts are on."""
    out = {e.strip().lower() for e in (os.getenv("AGAXES_OPERATOR_EMAILS") or "").split(",") if e.strip()}
    if os.getenv("DEMO_ACCOUNT", "1") != "0":
        out.add(OPERATOR_DEMO_EMAIL)
    return out


@dataclass
class Principal:
    via: str                      # "session" | "admin_token" | "open" | "agent" | "enrollment"
    role: str = "operator"
    user: dict | None = None
    company: dict | None = None
    extra: dict = field(default_factory=dict)

    @property
    def workspace_id(self) -> str | None:
        return (self.company or {}).get("id")

    @property
    def operator(self) -> bool:
        return self.role == "operator"

    @property
    def scoped(self) -> bool:
        """True when this caller must only see one workspace (every company user; not the platform operator)."""
        return self.via == "session" and not self.operator

    @property
    def own_work_only(self) -> bool:
        """Recruiters (member) and viewers see only the agents assigned to them, not the whole company."""
        return self.scoped and self.role in ("viewer", "member")

    def access(self) -> dict:
        """What the console should show this person (the backend enforces the same lines)."""
        level = "platform" if not self.scoped else "own_work" if self.own_work_only else "company"
        views = {"platform": ["companies", "agents", "work", "approvals", "ledger", "members", "enrollments", "sourced"],
                 "company": ["agents", "work", "approvals", "ledger", "members", "enrollments", "sourced"],
                 "own_work": ["my_agents", "work", "approvals", "sourced"]}[level]
        return {"level": level, "role": self.role, "views": views,
                "summary": {"platform": "Platform operator: every company, its people and its AI employees.",
                            "company": f"{(self.company or {}).get('name', 'Your company')}: every AI employee, "
                                       "member and ledger entry in this company only.",
                            "own_work": "Your own work: the AI employees assigned to you, their tasks and approvals."}[level]}

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
        return Principal(via="admin_token", role="operator")
    tok = _bearer(authorization)
    if tok:
        from .api import store
        found = store().session_user(tok)
        if found:
            user, company, _ = found
            role = user.get("workspace_role") or "member"
            if user["email"].lower() in operator_emails():
                role = "operator"
            return Principal(via="session", role=role if role in RANK else "viewer", user=user, company=company)
        if enforced():
            raise HTTPException(401, "your session has ended: log in again")
    if not enforced() or (perm in ("read", "audit") and not login_required()):
        return Principal(via="open", role="operator")
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
require_audit = need("audit")
require_operator = need("operator")
require_operate = need("operate")
require_admin = need("admin")
require_owner = need("owner")


# ---- workspaces ----------------------------------------------------------------------------------------------

def _default_workspace_ids() -> set[str]:
    """Workspaces that also see agents onboarded before accounts existed (set AGAXES_DEFAULT_WORKSPACE to a domain).
    Otherwise those agents (the seeded fleet) are the platform operator's alone."""
    from .api import store
    s = store()
    out = set()
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
    if not (ws == p.workspace_id if ws else p.workspace_id in _default_workspace_ids()):
        return False
    if p.own_work_only:
        return p.user["id"] in (agent.get("assignees") or [])
    return True


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
    """Ledger rows for a company: anything its people did, or anything about its agents."""
    if ids is None:
        return True
    actor = row.get("actor") or {}
    if workspace_id and actor.get("workspace_id") == workspace_id:
        return True
    pl = row.get("payload") or {}
    refs = {pl.get("agent_id"), pl.get("subject"), (pl.get("passport") or {}).get("agent_id")} - {None}
    return bool(refs & ids)
