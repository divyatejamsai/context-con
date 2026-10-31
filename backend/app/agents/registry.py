"""AI Employee registry (WS8): onboard agents under a human sponsor, manage roles, scopes and reviews.

Contract (docs/COUNTERSIGN.md):
    onboard(agent_name, role, sponsor, scopes) -> dict        issues a passport, stores it, writes a ledger entry
    list_agents() -> list[dict]                               {passport, status, reason, last_checked, ...}
    async recheck_all(client) -> list[Verdict]                "payroll run": verify_passport for each, suspend on fail

Permissions are two gates: the role's ceiling (static, e.g. an AI Recruiter can never get payment.send) and the
sponsor's live authority (verify_passport's sponsor_can_grant_scope, checked against Crustdata). Widening scopes runs
the live check before the new passport replaces the old one; narrowing never needs it.

Suspension is fail closed: a payroll run that can't verify the sponsor suspends the agent, and only a human
reinstate that passes a fresh check brings it back. Suspending revokes the passport on the ledger (passport.revoke),
so every verifier, not just this registry, refuses a suspended agent. Store: backend/data/agents.json (AGENTS_PATH overrides).
Agent private keys live in the store and never leave it through public().
"""
from __future__ import annotations

import base64
import json
import os
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from . import guard, ledger, passport as pp
from .graph import Graph
from .models import SCOPES, Passport, Scope, Sponsor, Verdict

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = ROOT / "backend" / "data" / "agents.json"

Status = Literal["active", "suspended", "offboarded"]
ReviewDecision = Literal["keep", "restrict", "offboard"]

ALL_SCOPES: list[str] = list(SCOPES)

# Role templates: default scopes on onboarding, ceiling = the most a sponsor can ever grant this role.
ROLES: dict[str, dict[str, Any]] = {
    "recruiter": {
        "title": "AI Recruiter",
        "summary": "Sources candidates, runs hiring conversations and, with a senior sponsor, sends offers. Sourced is the first one.",
        "default_scopes": ["outreach.hiring", "data.read"],
        "ceiling": ["outreach.hiring", "data.read", "contract.sign"],  # contract.sign = offer letters (needs an authority title)
    },
    "sdr": {
        "title": "AI Sales Rep",
        "summary": "Researches accounts and drafts sales outreach.",
        "default_scopes": ["outreach.sales", "data.read"],
        "ceiling": ["outreach.sales", "data.read"],
    },
    "analyst": {
        "title": "AI Research Analyst",
        "summary": "Reads company and people data, never contacts anyone.",
        "default_scopes": ["data.read"],
        "ceiling": ["data.read"],
    },
    "procurement": {
        "title": "AI Procurement Agent",
        "summary": "Negotiates vendor terms. Signing and paying need a senior sponsor.",
        "default_scopes": ["data.read"],
        "ceiling": ["data.read", "contract.sign", "payment.send"],
    },
}

_lock = threading.RLock()


class RegistryError(ValueError):
    """Bad request against the registry (unknown agent, scope outside the role, wrong state)."""


class ScopeDenied(RegistryError):
    """The sponsor's live authority check refused a scope change. Carries the verdict that refused it."""

    def __init__(self, message: str, verdict: Verdict):
        super().__init__(message)
        self.verdict = verdict


# ---- store -----------------------------------------------------------------------------------

def _path() -> Path:
    return Path(os.getenv("AGENTS_PATH") or DEFAULT_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict[str, dict]:
    p = _path()
    if not p.exists():
        return {}
    return json.loads(p.read_text() or "{}")


def _save(agents: dict[str, dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(agents, indent=2))
    tmp.replace(p)


def _get(agents: dict[str, dict], agent_id: str) -> dict:
    rec = agents.get(agent_id)
    if not rec:
        raise RegistryError(f"no AI employee with id {agent_id}")
    return rec


def _dump(m: Any) -> dict:
    return m.model_dump() if hasattr(m, "model_dump") else dict(m)


def public(rec: dict) -> dict:
    """The record as the API and console see it: everything except the private key."""
    return {k: v for k, v in rec.items() if k != "private_key"}


# ---- roles and scopes ------------------------------------------------------------------------

def role_key(role: str) -> str | None:
    r = role.strip().lower()
    for k, v in ROLES.items():
        if r in (k, v["title"].lower()):
            return k
    return None


def roles() -> list[dict]:
    return [{"key": k, **v} for k, v in ROLES.items()]


def check_ceiling(role: str, scopes: list[str]) -> None:
    unknown = [s for s in scopes if s not in ALL_SCOPES]
    if unknown:
        raise RegistryError(f"unknown scope(s): {', '.join(unknown)}")
    key = role_key(role)
    if key is None:
        return  # custom role: only the sponsor's live authority applies
    over = [s for s in scopes if s not in ROLES[key]["ceiling"]]
    if over:
        raise RegistryError(f"{ROLES[key]['title']} can't hold {', '.join(over)} (role ceiling)")


# ---- passports -------------------------------------------------------------------------------

def _sources(v: Verdict) -> list:
    return [c.source for c in v.checks if c.source is not None]


def _first_failure(v: Verdict) -> str:
    for c in v.checks:
        if c.status != "pass":
            prefix = "couldn't verify " if c.status == "unverifiable" else ""
            return f"{prefix}{c.name}: {c.detail}"
    return "verdict was block"


def _passes_but_revoked(v: Verdict) -> bool:
    """A suspended agent's passport is revoked, so its verdict always blocks on not_revoked. Reinstating asks
    whether everything else passes."""
    return all(c.status == "pass" for c in v.checks if c.name != "not_revoked") and bool(v.checks)


def _record_check(rec: dict, v: Verdict, kind: str = "agent.checked") -> Verdict:
    """verify_passport already writes its own ledger entry; composite verdicts (scope changes) get one here."""
    if not v.ledger_entry:
        v.ledger_entry = ledger.append(kind, {"agent_id": rec["agent_id"], "decision": v.decision,
                                              "checks": [c.model_dump(exclude={"source"}) for c in v.checks]},
                                       _sources(v))
    rec["ledger_entries"].append(v.ledger_entry)
    rec["last_checked"] = _now()
    rec["last_verdict"] = _dump(v)
    return v


# ---- lifecycle -------------------------------------------------------------------------------

def onboard(agent_name: str, role: str, sponsor: Sponsor, scopes: list[Scope] | None = None, days: int = 30, *,
            job: str | None = None, runtime: str = "in-house", workspace_id: str | None = None,
            public_key: str | None = None) -> dict:
    """Issues a passport and adds the agent as active. The API runs recheck() right after, so an agent with a
    sponsor who can't vouch for it shows up suspended instead of silently active. job is a one-line description of
    the work; runtime says where the agent runs ("in-house", or "external" for agents that only reach us over MCP)."""
    if not agent_name.strip():
        raise RegistryError("agent name is required")
    key = role_key(role)
    role_title = ROLES[key]["title"] if key else role.strip()
    scopes = list(scopes) if scopes else list(ROLES[key]["default_scopes"] if key else ["data.read"])
    check_ceiling(role_title, scopes)
    try:
        passport, private_key = pp.issue_passport(agent_name.strip(), role_title, sponsor, scopes, days,
                                                  public_key=public_key)
    except ValueError as e:
        raise RegistryError(str(e))
    custody = "agent" if public_key is not None else "agaxes"
    entry = ledger.append("agent.onboarded", {"agent_id": passport.agent_id, "agent_name": passport.agent_name,
                                               "role": role_title, "sponsor": _dump(sponsor), "scopes": scopes,
                                               "expires_at": passport.expires_at, "runtime": runtime,
                                               "workspace_id": workspace_id, "key_custody": custody})
    rec = {
        "agent_id": passport.agent_id,
        "employee_no": 0,
        "name": passport.agent_name,
        "role": role_title,
        "job": (job or "").strip() or None,
        "runtime": runtime,
        "status": "active",
        "reason": None,
        "suspended_by": None,
        "onboarded_at": _now(),
        "last_checked": None,
        "last_verdict": None,
        "passport": _dump(passport),
        # key_custody "agent": the agent made its own key and Agaxes only holds the public half (enrollment).
        "private_key": base64.b64encode(private_key).decode() if private_key else None,
        "key_custody": custody,
        "workspace_id": workspace_id,
        "reviews": [],
        "ledger_entries": [entry],
    }
    with _lock:
        agents = _load()
        rec["employee_no"] = max((a.get("employee_no", 0) for a in agents.values()), default=0) + 1
        agents[rec["agent_id"]] = rec
        _save(agents)
    return public(rec)


def list_agents() -> list[dict]:
    with _lock:
        agents = _load()
    return sorted((public(a) for a in agents.values()), key=lambda a: a.get("employee_no", 0))


def get_agent(agent_id: str) -> dict:
    with _lock:
        return public(_get(_load(), agent_id))


def private_key(agent_id: str) -> bytes:
    """For the agent runtime (e.g. Sourced signing its outreach before the guard). Not exposed over HTTP.
    Agents that hold their own key (enrolled) have none here: they sign on their own machine."""
    with _lock:
        rec = _get(_load(), agent_id)
    if not rec.get("private_key"):
        raise RegistryError(f"{rec['name']} holds its own key: Agaxes can't sign for it")
    return base64.b64decode(rec["private_key"])


async def recheck(agent_id: str, client) -> Verdict:
    """Live check of one agent. Fail suspends it; a pass never lifts a suspension (that's reinstate's job)."""
    with _lock:
        rec = _get(_load(), agent_id)
    if rec["status"] == "offboarded":
        raise RegistryError(f"{rec['name']} is offboarded")
    v = await pp.verify_passport(Passport(**rec["passport"]), client)
    with _lock:
        agents = _load()
        rec = _get(agents, agent_id)
        _record_check(rec, v)
        if v.decision == "block" and rec["status"] == "active":
            _suspend(rec, _first_failure(v), by="payroll", sources=_sources(v))
        _save(agents)
    return v


async def recheck_all(client, only: set[str] | None = None) -> list[Verdict]:
    """The payroll run: every agent that isn't offboarded gets a live sponsor check (only: limit to these ids)."""
    out = []
    for a in list_agents():
        if a["status"] != "offboarded" and (only is None or a["agent_id"] in only):
            out.append(await recheck(a["agent_id"], client))
    return out


def _suspend(rec: dict, reason: str, by: str, sources: list | None = None) -> None:
    rec["status"], rec["reason"], rec["suspended_by"] = "suspended", reason, by
    rec["ledger_entries"].append(pp.revoke(rec["agent_id"], f"suspended by {by}: {reason}", sources or []))


def suspend(agent_id: str, reason: str, by: str = "sponsor") -> dict:
    with _lock:
        agents = _load()
        rec = _get(agents, agent_id)
        if rec["status"] != "active":
            raise RegistryError(f"{rec['name']} is {rec['status']}, not active")
        _suspend(rec, reason.strip() or "suspended by sponsor", by)
        _save(agents)
        return public(rec)


async def reinstate(agent_id: str, client, by: str = "sponsor") -> tuple[dict, Verdict]:
    """Back to active only if a fresh live check passes (ignoring the suspension's own revocation). Returns
    (agent, verdict); the agent stays suspended, with the new reason, when anything else fails."""
    with _lock:
        rec = _get(_load(), agent_id)
    if rec["status"] != "suspended":
        raise RegistryError(f"{rec['name']} is {rec['status']}, not suspended")
    v = await pp.verify_passport(Passport(**rec["passport"]), client)
    with _lock:
        agents = _load()
        rec = _get(agents, agent_id)
        _record_check(rec, v)
        if _passes_but_revoked(v):
            rec["status"], rec["reason"], rec["suspended_by"] = "active", None, None
            rec["ledger_entries"].append(pp.reinstate(agent_id, f"reinstated by {by} after a passing check"))
        else:
            rec["reason"] = _first_failure(v)
        _save(agents)
        return public(rec), v


def offboard(agent_id: str, reason: str, by: str = "sponsor") -> dict:
    """Permanent: the passport is revoked and the agent can't be rechecked or reinstated."""
    with _lock:
        agents = _load()
        rec = _get(agents, agent_id)
        if rec["status"] == "offboarded":
            raise RegistryError(f"{rec['name']} is already offboarded")
        rec["status"], rec["reason"], rec["suspended_by"] = "offboarded", reason.strip() or "offboarded", by
        rec["offboarded_at"] = _now()
        if not ledger.is_revoked(agent_id):
            rec["ledger_entries"].append(pp.revoke(agent_id, f"offboarded by {by}: {rec['reason']}"))
        rec["ledger_entries"].append(ledger.append("agent.offboarded", {"agent_id": agent_id, "reason": rec["reason"],
                                                                         "by": by}))
        _save(agents)
        return public(rec)


async def set_scopes(agent_id: str, scopes: list[Scope], client, by: str = "sponsor") -> tuple[dict, Verdict | None]:
    """Change an agent's permissions by re-issuing its passport. Widening runs the sponsor's live authority check
    first and raises ScopeDenied (old passport kept) if it fails. Returns (agent, verdict or None if narrowing)."""
    scopes = list(dict.fromkeys(scopes))
    with _lock:
        rec = _get(_load(), agent_id)
    if rec["status"] == "offboarded":
        raise RegistryError(f"{rec['name']} is offboarded")
    check_ceiling(rec["role"], scopes)
    old = Passport(**rec["passport"])
    if set(scopes) == set(old.scopes):
        return public(rec), None
    added = [s for s in scopes if s not in old.scopes]
    if added and rec["status"] != "active":
        raise RegistryError(f"{rec['name']} is suspended; reinstate it before granting more scopes")
    # record=False: a passport the sponsor can't back is never issued, so it stays off the ledger
    own_key = rec.get("key_custody") == "agent"
    new, key = pp.issue_passport(old.agent_name, old.role, old.sponsor, scopes, _days_left(old), agent_id=agent_id,
                                 record=False, public_key=old.public_key if own_key else None)

    v = None
    if added:
        checks = [await pp.verify_passport(new, client, scope=s) for s in added]
        v = Verdict(subject=old.agent_id, decision="allow" if all(c.decision == "allow" for c in checks) else "block",
                    checks=[c for vv in checks for c in vv.checks])
        if v.decision == "block":
            with _lock:
                agents = _load()
                r = _get(agents, agent_id)
                _record_check(r, v, "agent.scope_denied")
                _save(agents)
            raise ScopeDenied(f"can't grant {', '.join(added)}: {_first_failure(v)}", v)

    with _lock:
        agents = _load()
        rec = _get(agents, agent_id)
        if v is not None:
            _record_check(rec, v, "agent.scopes_checked")
        rec["passport"], rec["private_key"] = _dump(new), (base64.b64encode(key).decode() if key else None)
        rec["ledger_entries"].append(ledger.append("passport.issued", {
            "agent_id": agent_id, "passport": new.model_dump(exclude={"issuer_signature"})}))
        rec["ledger_entries"].append(ledger.append("agent.scopes_changed", {
            "agent_id": agent_id, "from": list(old.scopes), "to": scopes, "by": by}, _sources(v) if v else []))
        _save(agents)
        return public(rec), v


def rotate_key(agent_id: str, new_public_key: str, by: str = "agent") -> dict:
    """Re-issue the passport bound to a new agent-held key, same scopes and expiry. After this Agaxes holds no
    private key for the agent, and anything signed with the old key stops verifying."""
    with _lock:
        agents = _load()
        rec = _get(agents, agent_id)
        if rec["status"] == "offboarded":
            raise RegistryError(f"{rec['name']} is offboarded")
        old = Passport(**rec["passport"])
        try:
            new, _ = pp.issue_passport(old.agent_name, old.role, old.sponsor, list(old.scopes), _days_left(old),
                                       agent_id=agent_id, record=False, public_key=new_public_key)
        except ValueError as e:
            raise RegistryError(str(e))
        if new.public_key == old.public_key:
            raise RegistryError("the new key is the same as the current one")
        rec["passport"], rec["private_key"], rec["key_custody"] = _dump(new), None, "agent"
        rec["ledger_entries"].append(ledger.append("passport.issued", {
            "agent_id": agent_id, "passport": new.model_dump(exclude={"issuer_signature"})}))
        rec["ledger_entries"].append(ledger.append("passport.key_rotated", {
            "agent_id": agent_id, "old_key": old.public_key, "new_key": new.public_key, "by": by}))
        _save(agents)
        return public(rec)


def _days_left(p: Passport) -> int:
    try:
        exp = datetime.fromisoformat(p.expires_at.replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return max(1, (exp - datetime.now(timezone.utc)).days)
    except ValueError:
        return 30


# ---- reviews ---------------------------------------------------------------------------------

def scorecard(agent_id: str) -> dict:
    """What the agent actually did, read from the ledger: guard verdicts, what got blocked and why, and the work
    it filed (work.* entries)."""
    get_agent(agent_id)
    rows = ledger.entries(agent_id)
    sends = [e for e in rows if "guard" in e.get("kind", "") or "send" in e.get("kind", "")]
    blocked = [e for e in sends if (e.get("payload") or {}).get("decision") == "block"]
    reasons: Counter[str] = Counter()
    for e in blocked:
        for c in (e.get("payload") or {}).get("checks", []):
            if c.get("status") != "pass":
                reasons[c.get("name", "unknown")] += 1
    checks = [e for e in rows if e.get("kind") == "passport.verified"]
    work = [e for e in rows if e.get("kind", "").startswith("work.")]  # filed by agents via MCP record_work
    return {
        "messages_checked": len(sends),
        "allowed": len(sends) - len(blocked),
        "blocked": len(blocked),
        "block_reasons": reasons.most_common(),
        "sponsor_checks": len(checks),
        "sponsor_checks_failed": sum(1 for e in checks if (e.get("payload") or {}).get("decision") == "block"),
        "work_filed": len(work),
        "work_by_kind": Counter(e["kind"].removeprefix("work.") for e in work).most_common(),
        "recent_work": [{"seq": e.get("seq"), "ts": e.get("ts"), "kind": e["kind"].removeprefix("work."),
                         "summary": (e.get("payload") or {}).get("summary"), "sources": len(e.get("sources") or [])}
                        for e in work[-5:][::-1]],
        "ledger_entries": len(rows),
        "last_activity": max((e.get("ts", "") for e in rows), default=None),
    }


async def add_review(agent_id: str, reviewer: str, decision: ReviewDecision, notes: str = "",
                     scopes: list[Scope] | None = None, client=None) -> dict:
    """A human review of an AI employee, with the scorecard frozen at review time. keep = no change,
    restrict = narrow to `scopes`, offboard = end its employment."""
    if decision not in ("keep", "restrict", "offboard"):
        raise RegistryError(f"unknown review decision {decision!r}")
    card = scorecard(agent_id)
    agent = get_agent(agent_id)
    if decision == "restrict":
        if scopes is None:
            raise RegistryError("restrict needs the scopes to keep")
        if not set(scopes) < set(agent["passport"]["scopes"]):
            raise RegistryError("restrict can only remove scopes")
        await set_scopes(agent_id, scopes, client, by=f"review:{reviewer}")
    elif decision == "offboard":
        offboard(agent_id, notes or "offboarded at review", by=f"review:{reviewer}")
    review = {"id": uuid.uuid4().hex[:10], "at": _now(), "reviewer": reviewer.strip() or "sponsor",
              "decision": decision, "notes": notes.strip(), "scopes": scopes, "scorecard": card}
    with _lock:
        agents = _load()
        rec = _get(agents, agent_id)
        review["ledger_entry"] = ledger.append("agent.reviewed", {"agent_id": agent_id, **review})
        rec["reviews"].append(review)
        rec["ledger_entries"].append(review["ledger_entry"])
        _save(agents)
        return public(rec)


# ---- sending (through the Send Guard) --------------------------------------------------------

async def send(agent_id: str, to: dict, body: str, scope: Scope, client, *, signed_body: str | None = None,
               today=None) -> tuple[Verdict, bool]:
    """The agent signs its draft with its own key and hands it to the Send Guard. `signed_body` lets the demo sign
    one text and send another (a message altered after signing). Returns (verdict, written to outbox)."""
    with _lock:
        rec = _get(_load(), agent_id)
    p = Passport(**rec["passport"])
    sig = pp.sign_message(p, base64.b64decode(rec["private_key"]), signed_body if signed_body is not None else body)
    return await guard.send_if_allowed(p, sig, to, body, scope, today=today, graph=Graph(client))
