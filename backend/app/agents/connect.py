"""Connecting an agent: the onboarding flow a company runs before an AI agent can do anything.

Modelled on how identity platforms onboard non-human identities (Entra Agent ID, Okta for AI agents, OAuth app
installs): pick what kind of agent it is, name an accountable owner and a sponsor whose authority is checked live,
grant scopes from a catalog with risk levels, connect the tools it may call, set budgets, get a second admin's sign-off
for high-risk scopes, then enroll it and watch for its first signed call.

A connection request moves through:

    pending_review  a high-risk scope was asked for: another admin must approve (separation of duties)
    approved        ready to issue
    rejected        an admin said no; nothing was issued
    awaiting_agent  outside agent: a one-time enrollment command was made; waiting for the agent to run it
    enrolled        the agent made its own key and got its passport; waiting for its first signed call
    connected       the first signed call (heartbeat) arrived and verified
    failed          the passport was issued but the sponsor check refused it (the agent starts suspended)

Every step writes a ledger entry. Store: connections.json next to the registry.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import enroll, ledger, registry
from .passport import SCOPE_RULES, can_grant

_lock = threading.RLock()

# ---- the catalog ----------------------------------------------------------------------------------------------------

RISK_ORDER = ["low", "medium", "high", "critical"]

SCOPES: list[dict] = [
    {"key": "data.read", "label": "Read people and company data", "risk": "low",
     "allows": "Look people and companies up in Crustdata and on the web, and file what it finds on the ledger.",
     "never": "Contact anyone, sign anything or spend money."},
    {"key": "outreach.hiring", "label": "Contact candidates", "risk": "medium",
     "allows": "Write to candidates about open roles. Every message is signed and passes Send Guard first.",
     "never": "Write to anyone about sales, sign offers or pay anyone."},
    {"key": "outreach.sales", "label": "Contact prospects", "risk": "medium",
     "allows": "Write to prospects and customers. Every message is signed and passes Send Guard first.",
     "never": "Write to candidates, sign contracts or pay anyone."},
    {"key": "contract.sign", "label": "Sign offers and contracts", "risk": "high",
     "allows": "Put the company's signature on offer letters and contracts, each one only after a person approves it.",
     "never": "Move money."},
    {"key": "payment.send", "label": "Send payments", "risk": "critical",
     "allows": "Pay vendors and people on the company's behalf.",
     "never": "Exceed its daily budget or pay without an approval when approvals are on."},
]
SCOPE_BY_KEY = {s["key"]: s for s in SCOPES}
for _s in SCOPES:
    _s["who_can_grant"] = SCOPE_RULES[_s["key"]][1]
    _s["needs_review"] = _s["risk"] in ("high", "critical")

# Tools: what the agent may call. Data tools are enforced on every metered call (runtime/worker.py MeteredClient).
TOOLS: list[dict] = [
    {"key": "crustdata.people", "label": "Crustdata People", "kind": "data", "needs": ["data.read"],
     "detail": "Person Search and Person Enrich: profiles, current jobs, work history.",
     "calls": ["person_search", "person_enrich", "person_enrich_many"]},
    {"key": "crustdata.companies", "label": "Crustdata Companies", "kind": "data", "needs": ["data.read"],
     "detail": "Company Identify, Enrich, Search and Job Search: firmographics, headcount, funding, hiring.",
     "calls": ["company_search", "company_identify", "company_enrich", "job_search"]},
    {"key": "web", "label": "Web search and fetch", "kind": "data", "needs": ["data.read"],
     "detail": "Crustdata Web Search and Web Fetch, for news and pages that back up a claim.",
     "calls": ["web_search", "web_fetch"]},
    {"key": "email", "label": "Email, through Send Guard", "kind": "action", "needs": ["outreach.hiring", "outreach.sales"],
     "detail": "Sends from the company's mailer. Each message is signed by the agent and checked by Send Guard.",
     "calls": []},
    {"key": "esign", "label": "Offer letters", "kind": "action", "needs": ["contract.sign"],
     "detail": "Drafts and signs offer letters, each one only after a person approves it.", "calls": []},
]
TOOL_BY_KEY = {t["key"]: t for t in TOOLS}
CALL_TOOL = {c: t["key"] for t in TOOLS for c in t["calls"]}

# Templates: agents whose code runs inside Agaxes. The jobs come from app/runtime/kinds.py.
TEMPLATES: list[dict] = [
    {"key": "sourced", "name": "Sourced", "role": "recruiter", "scopes": ["outreach.hiring", "data.read"],
     "tools": ["crustdata.people", "crustdata.companies", "web", "email"],
     "job": "Sources candidates from a hiring brief and drafts verified outreach"},
    {"key": "scheduler", "name": "Scheduler", "role": "recruiter", "scopes": ["outreach.hiring", "data.read"],
     "tools": ["crustdata.people", "email"],
     "job": "Schedules interviews: checks candidates on Crustdata, proposes slots, drafts invites for approval"},
    {"key": "offer", "name": "Offer", "role": "recruiter", "scopes": ["contract.sign", "data.read"],
     "tools": ["crustdata.people", "crustdata.companies", "esign"],
     "job": "Drafts offer letters and signs them under contract.sign, only after the employer approves each one"},
    {"key": "diligence", "name": "Diligence", "role": "analyst", "scopes": ["data.read"],
     "tools": ["crustdata.people", "crustdata.companies", "web"],
     "job": "Vendor and candidate diligence: cited briefs from Company Enrich and Web Fetch"},
    {"key": "reference", "name": "Reference", "role": "analyst", "scopes": ["data.read"],
     "tools": ["crustdata.people", "crustdata.companies"],
     "job": "Checks every claim on a resume against Crustdata and flags the false ones"},
    {"key": "pipeline", "name": "Pipeline", "role": "sdr", "scopes": ["outreach.sales", "data.read"],
     "tools": ["crustdata.people", "crustdata.companies", "email"],
     "job": "Works the lead list: grounded sales emails, stale CRM rows blocked"},
]
TEMPLATE_BY_KEY = {t["key"]: t for t in TEMPLATES}

AGENT_TYPES: list[dict] = [
    {"key": "template", "label": "From a template", "runtime": "in-house",
     "detail": "Agaxes runs it for you and holds its signing key. Ready-made jobs, nothing to install."},
    {"key": "claude_code", "label": "Claude Code", "runtime": "own",
     "detail": "Runs on a laptop or server. Makes its own key and works through the Agaxes MCP server."},
    {"key": "mcp", "label": "MCP agent", "runtime": "own",
     "detail": "Any MCP client (Cursor, an Agent SDK app, your own). Makes its own key, connects over MCP."},
    {"key": "http", "label": "HTTP or SDK agent", "runtime": "own",
     "detail": "Your own code calling the Agaxes API. Makes its own key and signs every call."},
]
TYPE_BY_KEY = {t["key"]: t for t in AGENT_TYPES}

BUDGET_LIMITS = {"tasks_per_day": 500, "sends_per_day": 500, "crustdata_calls_per_day": 5000, "llm_calls_per_day": 5000}


def catalog() -> dict:
    from ..runtime.kinds import KINDS
    from ..runtime.store import DEFAULT_BUDGET
    tpls = [{**t, "jobs": [k["label"] for k in KINDS.values() if k.get("agent_hint") == t["name"]]} for t in TEMPLATES]
    return {"agent_types": AGENT_TYPES, "templates": tpls, "scopes": SCOPES, "tools": [
        {k: v for k, v in t.items() if k != "calls"} for t in TOOLS], "roles": registry.roles(),
        "budget_defaults": DEFAULT_BUDGET, "budget_limits": BUDGET_LIMITS}


def high_risk(scopes: list[str]) -> list[str]:
    return [s for s in scopes if SCOPE_BY_KEY.get(s, {}).get("needs_review")]


def tool_allowed(agent: dict, call: str) -> str | None:
    """None if the agent may make this metered call. Agents connected before tools existed have no list: anything."""
    tools = agent.get("tools")
    tool = CALL_TOOL.get(call)
    if tools is None or tool is None or tool in tools:
        return None
    return f"{agent['name']} isn't connected to {TOOL_BY_KEY[tool]['label']} ({call})"


# ---- sponsor: who vouches for it, checked live ----------------------------------------------------------------------

def _person_row(p: Any, company: str | None, scopes: list[str]) -> dict:
    from ..people import profile_url
    from ..verify.profile import load_person, same_company
    pr = load_person(p)
    url = pr.profile_url or profile_url(p)
    jobs = [j for j in pr.current if company and same_company(j.company, company)] or pr.current
    job = jobs[0] if jobs else None
    at = bool(job and company and same_company(job.company, company))
    title = job.title if job else None
    return {"name": pr.name, "profile_url": url, "title": title, "company": job.company if job else None,
            "domain": getattr(job, "domain", None) if job else None, "works_there": at,
            "grants": {s: (at and can_grant(title, s, job.company if job else None)) for s in scopes}}


async def find_sponsor(client: Any, name: str, company: str, scopes: list[str] | None = None) -> dict:
    """Crustdata Person Search for a named person at a company (the owner, usually). Up to 5 matches, best first."""
    scopes = scopes or [s["key"] for s in SCOPES]
    if client is None:
        return {"matches": [], "error": "Crustdata isn't connected, so people can't be looked up. Paste a profile URL."}
    from ..verify.profile import same_company
    name, company = name.strip(), company.strip()
    both = {"op": "and", "conditions": [{"field": "basic_profile.name", "type": "(.)", "value": name},
                                        {"field": "experience.employment_details.current.name", "type": "(.)",
                                         "value": company}]}
    rows: list = []
    err = None
    for f in (both, {"field": "basic_profile.name", "type": "(.)", "value": name}):
        try:
            rows = await client.person_search(f, limit=10)
        except Exception as e:  # noqa: BLE001
            err = str(e)
            rows = []
        if rows:
            break
    out = [_person_row(r, company, scopes) for r in rows]
    out = [r for r in out if r["profile_url"]]
    out.sort(key=lambda r: (not r["works_there"], not (r["name"] or "").lower().startswith(name.lower()[:3])))
    if not out:
        return {"matches": [], "error": err and f"Crustdata search failed: {err[:160]}"}
    return {"matches": out[:5], "source": {"endpoint": "person/search", "field": "basic_profile.name"},
            "any_at_company": any(r["works_there"] for r in out) if company else None,
            "note": None if any(same_company(r["company"], company) for r in out) else
            f"No one by that name currently works at {company} according to Crustdata."}


async def check_sponsor(client: Any, profile_url: str, company: str, scopes: list[str] | None = None) -> dict:
    """Person Enrich on a profile: do they exist, do they work at the company now, which scopes can their title grant."""
    scopes = scopes or [s["key"] for s in SCOPES]
    if client is None:
        return {"found": False, "error": "Crustdata isn't connected: the sponsor will be checked when it is."}
    try:
        p = await client.person_enrich(profile_url.strip())
    except Exception as e:  # noqa: BLE001
        return {"found": False, "error": f"Crustdata lookup failed: {str(e)[:160]}"}
    if not p:
        return {"found": False, "error": "Crustdata has no record for that profile."}
    row = _person_row(p, company, scopes)
    row["profile_url"] = row["profile_url"] or profile_url.strip()
    return {"found": True, **row, "source": {"endpoint": "person/enrich", "field": "experience.employment_details.current",
                                             "url": profile_url.strip()}}


# ---- store ----------------------------------------------------------------------------------------------------------

def _path() -> Path:
    return registry._path().parent / "connections.json"


def _load() -> dict[str, dict]:
    p = _path()
    return json.loads(p.read_text() or "{}") if p.exists() else {}


def _save(rows: dict[str, dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2))
    tmp.replace(p)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConnectError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _mutate(request_id: str, fn) -> dict:
    with _lock:
        rows = _load()
        row = rows.get(request_id)
        if not row:
            raise ConnectError("no such connection request", 404)
        fn(row)
        row["updated_at"] = _now()
        _save(rows)
        return dict(row)


def get(request_id: str, workspace_id: str | None = None, scoped: bool = False) -> dict:
    with _lock:
        row = _load().get(request_id)
    if not row or (scoped and row.get("workspace_id") != workspace_id):
        raise ConnectError("no such connection request", 404)
    return _refresh(row)


def list_all(workspace_id: str | None = None, scoped: bool = False) -> list[dict]:
    with _lock:
        rows = list(_load().values())
    if scoped:
        rows = [r for r in rows if r.get("workspace_id") == workspace_id]
    return [_refresh(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]


def _refresh(row: dict) -> dict:
    """Fold in live state the request doesn't own: the enrollment's status and the agent's first call."""
    row = dict(row)
    if row.get("enrollment_id") and row["status"] == "awaiting_agent":
        e = next((x for x in enroll.list_all() if x["enrollment_id"] == row["enrollment_id"]), None)
        row["enrollment_status"] = e["status"] if e else None
    if row.get("agent_id"):
        try:
            a = registry.get_agent(row["agent_id"])
            row["agent_status"] = a["status"]
            row["first_seen_at"] = a.get("first_seen_at")
            row["last_seen_at"] = a.get("last_seen_at")
        except registry.RegistryError:
            pass
    return row


# ---- the request ----------------------------------------------------------------------------------------------------

def create(*, agent_type: str, template: str | None, name: str, job: str | None, role: str | None,
           scopes: list[str], tools: list[str], budget: dict | None, require_approval: bool, days: int,
           sponsor: dict, sponsor_check: dict | None, owner: dict | None, workspace_id: str | None,
           requested_by: str, requested_by_id: str | None, ttl_minutes: int = 60) -> dict:
    t = TYPE_BY_KEY.get(agent_type)
    if not t:
        raise ConnectError(f"unknown agent type {agent_type}")
    tpl = TEMPLATE_BY_KEY.get(template or "") if agent_type == "template" else None
    if agent_type == "template" and not tpl:
        raise ConnectError("pick a template")
    if not name.strip():
        raise ConnectError("the agent needs a name")
    role = tpl["role"] if tpl else (role or "researcher")
    scopes = list(dict.fromkeys(scopes))
    if not scopes:
        raise ConnectError("grant at least one permission")
    try:
        registry.check_ceiling(role, scopes)
    except registry.RegistryError as e:
        raise ConnectError(str(e))
    unknown = [x for x in tools if x not in TOOL_BY_KEY]
    if unknown:
        raise ConnectError(f"unknown tool(s): {', '.join(unknown)}")
    for x in tools:
        if not set(TOOL_BY_KEY[x]["needs"]) & set(scopes):
            need = " or ".join(TOOL_BY_KEY[x]["needs"])
            raise ConnectError(f"{TOOL_BY_KEY[x]['label']} needs the {need} permission")
    clean_budget = {}
    for k, v in (budget or {}).items():
        if k not in BUDGET_LIMITS:
            raise ConnectError(f"unknown budget {k}")
        if not 0 <= int(v) <= BUDGET_LIMITS[k]:
            raise ConnectError(f"{k} must be between 0 and {BUDGET_LIMITS[k]}")
        clean_budget[k] = int(v)
    for f in ("name", "profile_url", "company"):
        if not (sponsor.get(f) or "").strip():
            raise ConnectError(f"the sponsor's {f.replace('_', ' ')} is required")
    risky = high_risk(scopes)
    now = _now()
    row = {
        "request_id": f"con_{uuid.uuid4().hex[:12]}", "workspace_id": workspace_id,
        "agent_type": agent_type, "template": tpl["key"] if tpl else None, "runtime": t["runtime"],
        "name": name.strip(), "job": (job or "").strip() or (tpl["job"] if tpl else None), "role": role,
        "scopes": scopes, "tools": list(dict.fromkeys(tools)), "budget": clean_budget, "require_approval": require_approval,
        "days": days, "ttl_minutes": ttl_minutes, "sponsor": sponsor, "sponsor_check": sponsor_check, "owner": owner,
        "risk": max((SCOPE_BY_KEY[s]["risk"] for s in scopes), key=RISK_ORDER.index),
        "review": {"required": bool(risky), "scopes": risky, "decision": None, "by": None, "at": None, "note": None,
                   "sole_admin": False},
        "status": "pending_review" if risky else "approved",
        "requested_by": requested_by, "requested_by_id": requested_by_id, "created_at": now, "updated_at": now,
        "enrollment_id": None, "agent_id": None, "test": None, "verdict": None, "ledger": [],
    }
    entry = ledger.append("connect.requested", {k: row[k] for k in (
        "request_id", "workspace_id", "agent_type", "template", "name", "role", "scopes", "tools", "budget",
        "require_approval", "risk", "requested_by", "status")} | {"owner": (owner or {}).get("email"),
                                                                 "sponsor": sponsor.get("name"),
                                                                 "needs_review": risky})
    row["ledger"].append(entry)
    with _lock:
        rows = _load()
        rows[row["request_id"]] = row
        _save(rows)
    return row


def decide(request_id: str, decision: str, *, by: str, by_id: str | None, admins: list[dict] | None,
           note: str = "", workspace_id: str | None = None, scoped: bool = False) -> dict:
    """An admin approves or rejects a request that needs review. The requester can't approve their own request while
    another admin or owner exists in the company (admins = the workspace's admins and owners; None = no accounts)."""
    row = get(request_id, workspace_id, scoped)
    if row["status"] != "pending_review":
        raise ConnectError(f"this request is {row['status'].replace('_', ' ')}, not waiting for review")
    sole = False
    if by_id and by_id == row.get("requested_by_id"):
        others = [a for a in (admins or []) if a["id"] != by_id]
        if others and decision == "approve":
            names = ", ".join((a.get("full_name") or a["email"]) for a in others[:3])
            raise ConnectError(f"someone other than the requester must approve high-risk permissions: ask {names}", 403)
        sole = not others
    status = "approved" if decision == "approve" else "rejected"
    entry = ledger.append(f"connect.{status}", {"request_id": request_id, "name": row["name"], "by": by,
                                                "scopes": row["review"]["scopes"], "note": note, "sole_admin": sole})

    def fn(r):
        r["status"] = status
        r["review"].update(decision=decision, by=by, at=_now(), note=note or None, sole_admin=sole)
        r["ledger"].append(entry)
    return _mutate(request_id, fn)


def enroll_command(token: str, api_url: str, agent_type: str) -> dict:
    cmd = f"AGAXES_API_URL={api_url} python backend/scripts/agaxes_agent.py enroll {token}"
    out = {"command": cmd}
    if agent_type in ("claude_code", "mcp"):
        server = {"command": "python", "args": ["backend/mcp_server.py"], "env": {"AGAXES_API_URL": api_url}}
        out["mcp_config"] = json.dumps({"mcpServers": {"agaxes": server}}, indent=2)
        if agent_type == "claude_code":
            out["mcp_command"] = f"claude mcp add agaxes --env AGAXES_API_URL={api_url} -- python backend/mcp_server.py"
    return out


async def issue(request_id: str, client: Any, *, by: str, api_url: str, workspace_id: str | None = None,
                scoped: bool = False) -> dict:
    """Issue the passport (template agents) or the one-time enrollment command (outside agents)."""
    row = get(request_id, workspace_id, scoped)
    if row["status"] == "pending_review":
        raise ConnectError("an admin has to approve the high-risk permissions first", 409)
    if row["status"] != "approved":
        raise ConnectError(f"this request is already {row['status'].replace('_', ' ')}", 409)
    sponsor = registry.Sponsor(**{k: row["sponsor"].get(k) for k in ("name", "profile_url", "company",
                                                                     "company_domain", "title")})
    owner_ids = [row["owner"]["user_id"]] if (row.get("owner") or {}).get("user_id") else []
    if row["runtime"] == "own":
        try:
            enr, token = enroll.create(name=row["name"], role=row["role"], sponsor=sponsor, scopes=row["scopes"],
                                       days=row["days"], job=row["job"], ttl_minutes=row["ttl_minutes"],
                                       workspace_id=row["workspace_id"], created_by=by)
        except enroll.EnrollError as e:
            raise ConnectError(str(e), e.status)

        def fn(r):
            r["status"] = "awaiting_agent"
            r["enrollment_id"] = enr["enrollment_id"]
            r["expires_at"] = enr["expires_at"]
        out = _mutate(request_id, fn)
        return {"request": out, "enrollment": enr, "token": token, **enroll_command(token, api_url, row["agent_type"])}

    try:
        agent = registry.onboard(row["name"], row["role"], sponsor, row["scopes"], days=row["days"], job=row["job"],
                                 runtime="in-house", workspace_id=row["workspace_id"], assignees=owner_ids)
    except registry.RegistryError as e:
        raise ConnectError(str(e))
    _apply(row, agent["agent_id"])
    verdict = await registry.recheck(agent["agent_id"], client)
    agent = registry.get_agent(agent["agent_id"])
    entry = ledger.append("connect.issued", {"request_id": request_id, "agent_id": agent["agent_id"], "name": row["name"],
                                             "decision": verdict.decision, "key_custody": "agaxes"})

    def fn2(r):
        r["agent_id"] = agent["agent_id"]
        r["verdict"] = verdict.model_dump()
        r["status"] = "enrolled" if agent["status"] == "active" else "failed"
        r["ledger"].append(entry)
    out = _mutate(request_id, fn2)
    return {"request": _refresh(out), "agent": agent, "verdict": verdict.model_dump()}


def _apply(row: dict, agent_id: str) -> None:
    """Tools, owner, budgets and the approval rule from the request onto the new agent."""
    from ..runtime import store
    registry.annotate(agent_id, tools=row["tools"], owner=row.get("owner"), connection_id=row["request_id"],
                      agent_type=row["agent_type"])
    if (row.get("owner") or {}).get("user_id"):
        cur = registry.get_agent(agent_id).get("assignees") or []
        if row["owner"]["user_id"] not in cur:
            registry.set_assignees(agent_id, [*cur, row["owner"]["user_id"]], by=row["requested_by"])
    pol = store.set_policy(agent_id, require_approval=row["require_approval"], budget=row["budget"] or None)
    ledger.append("connect.policy", {"agent_id": agent_id, "request_id": row["request_id"], "tools": row["tools"],
                                     "require_approval": pol["require_approval"], "budget": pol["budget"]})


def on_enrolled(enrollment_id: str, agent_id: str, verdict: dict | None = None) -> dict | None:
    """Called by the enrollment route once an outside agent has claimed its token and been onboarded."""
    with _lock:
        row = next((r for r in _load().values() if r.get("enrollment_id") == enrollment_id), None)
    if not row:
        return None
    _apply(row, agent_id)
    status = registry.get_agent(agent_id)["status"]

    def fn(r):
        r["agent_id"] = agent_id
        r["verdict"] = verdict
        r["status"] = "enrolled" if status == "active" else "failed"
    return _mutate(row["request_id"], fn)


# ---- the first signed call ------------------------------------------------------------------------------------------

def record_heartbeat(agent: dict, text: str, via: str) -> dict:
    """A signed call from the agent arrived and verified. The first one completes its connection."""
    now = _now()
    first = not agent.get("first_seen_at")
    registry.annotate(agent["agent_id"], last_seen_at=now, heartbeats=int(agent.get("heartbeats") or 0) + 1,
                      **({"first_seen_at": now} if first else {}))
    entry = None
    if first:
        entry = ledger.append("agent.first_heartbeat", {"agent_id": agent["agent_id"], "name": agent["name"],
                                                        "via": via, "text": text[:200],
                                                        "public_key": agent["passport"]["public_key"]})
        cid = agent.get("connection_id")
        if cid:
            def fn(r):
                if r["status"] in ("enrolled", "awaiting_agent"):
                    r["status"] = "connected"
                r["test"] = {"at": now, "via": via, "ledger_entry": entry}
                r["ledger"].append(entry)
            try:
                _mutate(cid, fn)
            except ConnectError:
                pass
    active = agent["status"] == "active"
    return {"ok": True, "first": first, "at": now, "ledger_entry": entry, "status": agent["status"],
            "stop": not active, "reason": None if active else f"{agent['name']} is {agent['status']}"}


async def test(request_id: str, workspace_id: str | None = None, scoped: bool = False) -> dict:
    """Live connection test. Template agents: Agaxes signs a heartbeat with the agent's key and sends it through the
    same authenticate() path outside agents use. Outside agents: report whether their own heartbeat has arrived."""
    from ..runtime.external import AgentAuthError, authenticate, signed_text
    from .models import Passport
    from .passport import sign_message
    row = get(request_id, workspace_id, scoped)
    if not row.get("agent_id"):
        return {"request": row, "connected": False,
                "waiting_for": "the agent to run its enrollment command" if row["status"] == "awaiting_agent"
                else "the passport to be issued"}
    agent = registry.get_agent(row["agent_id"])
    if agent.get("first_seen_at"):
        return {"request": get(request_id), "connected": True, "first_seen_at": agent["first_seen_at"]}
    if agent.get("key_custody") == "agent":
        return {"request": row, "connected": False, "waiting_for": f"{agent['name']}'s first signed call"}
    ts = int(time.time())
    text = f"connection test for {request_id}"
    sig = sign_message(Passport.model_validate(agent["passport"]), registry.private_key(agent["agent_id"]),
                       signed_text("heartbeat", agent["agent_id"], None, ts, text))
    try:
        rec = authenticate("heartbeat", agent["agent_id"], None, ts, text, sig)
    except AgentAuthError as e:
        return {"request": row, "connected": False, "error": str(e)}
    hb = record_heartbeat(rec, text, via="agaxes runtime")
    return {"request": get(request_id), "connected": True, "first_seen_at": hb["at"], "heartbeat": hb}


def cancel(request_id: str, by: str, workspace_id: str | None = None, scoped: bool = False) -> dict:
    row = get(request_id, workspace_id, scoped)
    if row["status"] not in ("pending_review", "approved", "awaiting_agent"):
        raise ConnectError(f"this request is {row['status'].replace('_', ' ')}: nothing to cancel")
    if row.get("enrollment_id") and row["status"] == "awaiting_agent":
        try:
            enroll.revoke(row["enrollment_id"], by)
        except enroll.EnrollError:
            pass
    entry = ledger.append("connect.cancelled", {"request_id": request_id, "name": row["name"], "by": by})

    def fn(r):
        r["status"] = "cancelled"
        r["ledger"].append(entry)
    return _mutate(request_id, fn)
