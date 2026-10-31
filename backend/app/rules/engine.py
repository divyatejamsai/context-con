"""Company rules: written in the console from templates, no code, and enforced by Agaxes at the moment an agent acts.

Four kinds of rule (TYPES), each with a plain sentence the console, the approval inbox and the ledger all show:

    offer_approvers    "Offers over ₹30L need 2 approvers"           the offer is signed only after N different people
                                                                     approve it (checked again at every approval)
    quiet_hours        "No outreach between 20:00 and 08:00 IST"     a send in the window waits in the approval inbox
                                                                     (or is blocked, if the rule says so)
    blocked_companies  "Sourced may never contact people at our      Send Guard blocks the draft, and blocks it again at
                        clients (Acme, Globex)"                      send time if the list changed after the draft
    daily_cap          "Each AI employee may send at most 20         sends, tasks, Crustdata calls or AI model calls, per
                        messages a day"                              agent or for a group of agents together

A rule covers the whole company (agents = []) or named AI employees. Rules belong to the workspace of the admin who
wrote them; one written in open mode or by the platform operator (workspace None) covers every company. Every change
bumps the rule's version and keeps the old one in its history, and goes on the ledger (rule.created / updated /
enabled / disabled / deleted). Every time a rule stops or holds something, a rule.enforced entry names the rule, its
version, the agent and what it touched.

Rules live in runtime.json next to tasks and approvals (same lock, same atomic save).
"""
from __future__ import annotations

import copy
import logging
import re
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..agents import ledger, registry
from ..runtime import store

log = logging.getLogger(__name__)

USD_INR = 84  # offers written in dollars are compared at this rate (the hit says so)
METRICS = {
    "sends": ("send", "messages"),
    "tasks": ("start", "tasks"),
    "crustdata": ("make", "Crustdata calls"),
    "llm": ("make", "AI model calls"),
}
TZ_ABBR = {"Asia/Kolkata": "IST", "UTC": "UTC", "America/New_York": "ET", "America/Los_Angeles": "PT", "Europe/London": "UK time"}

TYPES: dict[str, dict] = {
    "offer_approvers": {
        "label": "Big offers need more approvers",
        "description": "An offer above the amount is signed only after this many different people approve it.",
        "applies_to": "Offer letters",
        "fields": [{"name": "threshold", "label": "Offers over", "type": "money", "placeholder": "₹30L"},
                   {"name": "approvers", "label": "Approvers needed", "type": "number", "min": 2, "max": 5}],
        "example": {"threshold": "₹30L", "approvers": 2},
    },
    "quiet_hours": {
        "label": "No outreach at night",
        "description": "Messages an agent would send in this window wait in the approval inbox until it ends, or are "
                       "blocked outright.",
        "applies_to": "Outbound messages",
        "fields": [{"name": "start", "label": "From", "type": "time", "placeholder": "20:00"},
                   {"name": "end", "label": "Until", "type": "time", "placeholder": "08:00"},
                   {"name": "tz", "label": "Time zone", "type": "select", "options": list(TZ_ABBR)},
                   {"name": "effect", "label": "Then", "type": "select", "options": ["hold", "block"],
                    "option_labels": {"hold": "Hold it until morning", "block": "Block it"}}],
        "example": {"start": "20:00", "end": "08:00", "tz": "Asia/Kolkata", "effect": "hold"},
    },
    "blocked_companies": {
        "label": "Never contact people at these companies",
        "description": "Send Guard blocks any message to someone who works at one of these companies, for example your "
                       "clients or a partner you've agreed not to poach from.",
        "applies_to": "Outbound messages",
        "fields": [{"name": "list_name", "label": "Call this list", "type": "text", "placeholder": "our clients"},
                   {"name": "companies", "label": "Companies", "type": "list", "placeholder": "One per line: Razorpay"}],
        "example": {"list_name": "our clients", "companies": ["Razorpay", "Zepto"]},
    },
    "daily_cap": {
        "label": "Daily cap",
        "description": "A ceiling on how much agents do in a day: messages, tasks, Crustdata calls (spend) or AI calls.",
        "applies_to": "Sends, tasks and data spend",
        "fields": [{"name": "metric", "label": "What", "type": "select", "options": list(METRICS),
                    "option_labels": {k: v[1] for k, v in METRICS.items()}},
                   {"name": "limit", "label": "At most, per day", "type": "number", "min": 0, "max": 100000},
                   {"name": "per", "label": "Counted", "type": "select", "options": ["each", "together"],
                    "option_labels": {"each": "for each agent", "together": "for all of them together"}}],
        "example": {"metric": "sends", "limit": 20, "per": "each"},
    },
}


class RuleError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- money ------------------------------------------------------------------------------------------

_AMOUNT = re.compile(r"(\$|usd|us\$|inr|rs\.?|₹)?\s*(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|lpa|l|k|thousand|mn|million|m)?\b",
                     re.I)
_UNIT = {"cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
         "lacs": 100_000, "lpa": 100_000, "l": 100_000, "k": 1_000, "thousand": 1_000, "mn": 1_000_000, "million": 1_000_000,
         "m": 1_000_000}


def parse_money(text: Any) -> tuple[int | None, str | None]:
    """Rupees in a compensation line: '₹42 LPA fixed + ESOPs' -> 4,200,000. The largest amount wins (a range's top end,
    or the fixed part over a bonus). Dollars are converted at USD_INR. (None, why) when no amount can be read."""
    if isinstance(text, (int, float)):
        return int(text), None
    s = str(text or "").replace(",", "").strip()
    best, note = None, None
    usd_all = bool(re.search(r"\$|usd", s, re.I))
    for m in _AMOUNT.finditer(s):
        cur, num, unit = (m.group(1) or "").lower(), float(m.group(2)), (m.group(3) or "").lower()
        if not unit and num < 1000 and not cur:
            continue  # "+ 0.5% ESOPs", "4 year vest": not money
        val = num * _UNIT.get(unit, 1)
        if cur.startswith(("$", "usd", "us$")) or (usd_all and not cur):
            val, note = val * USD_INR, f"read as US dollars at ₹{USD_INR}/$"
        if val < 1000:
            continue
        best = max(best or 0, int(round(val)))
    return best, note


def fmt_inr(n: int | None) -> str:
    if n is None:
        return "an unknown amount"
    if n >= 10_000_000:
        v = n / 10_000_000
        return f"₹{v:g}Cr" if v == round(v, 2) else f"₹{v:.2f}Cr"
    if n >= 100_000:
        v = n / 100_000
        return f"₹{v:g}L" if v == round(v, 2) else f"₹{v:.2f}L"
    return f"₹{n:,}"


# ---- validation and the plain sentence -----------------------------------------------------------------

def _hhmm(v: Any, field: str) -> str:
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*", str(v or ""), re.I)
    if not m:
        raise RuleError(f"{field}: write a time like 20:00 or 8pm")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        raise RuleError(f"{field}: {v} isn't a time of day")
    return f"{h:02d}:{mi:02d}"


def normalize(rtype: str, params: dict | None) -> dict:
    """Checked, canonical params for a rule type. Raises RuleError with a sentence the console can show."""
    if rtype not in TYPES:
        raise RuleError(f"unknown rule type {rtype!r}; pick one of: {', '.join(TYPES)}")
    p = {**TYPES[rtype]["example"], **{k: v for k, v in (params or {}).items() if v not in (None, "")}}
    if rtype == "offer_approvers":
        amount, _ = parse_money(p["threshold"])
        if not amount:
            raise RuleError("Offers over: write an amount like ₹30L, 30 lakh or 3000000")
        n = int(p["approvers"])
        if not 2 <= n <= 5:
            raise RuleError("Approvers needed: between 2 and 5")
        return {"threshold": fmt_inr(amount), "threshold_inr": amount, "approvers": n}
    if rtype == "quiet_hours":
        start, end = _hhmm(p["start"], "From"), _hhmm(p["end"], "Until")
        if start == end:
            raise RuleError("From and Until can't be the same time")
        tz = str(p.get("tz") or "Asia/Kolkata")
        try:
            ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            raise RuleError(f"unknown time zone {tz}")
        effect = p.get("effect") if p.get("effect") in ("hold", "block") else "hold"
        return {"start": start, "end": end, "tz": tz, "effect": effect}
    if rtype == "blocked_companies":
        raw = p.get("companies") or []
        items = raw.splitlines() if isinstance(raw, str) else list(raw)
        cos, seen = [], set()
        for c in items:
            for part in str(c).split(","):
                part = part.strip()
                if part and part.lower() not in seen:
                    seen.add(part.lower())
                    cos.append(part[:80])
        if not cos:
            raise RuleError("Companies: add at least one company")
        return {"list_name": str(p.get("list_name") or "").strip()[:40], "companies": cos[:200]}
    if rtype == "daily_cap":
        if p["metric"] not in METRICS:
            raise RuleError(f"What: one of {', '.join(METRICS)}")
        n = int(p["limit"])
        if n < 0:
            raise RuleError("At most: 0 or more")
        return {"metric": p["metric"], "limit": n, "per": "together" if p.get("per") == "together" else "each"}
    raise RuleError(rtype)


def _names(agent_ids: list[str]) -> list[str]:
    out = []
    for aid in agent_ids:
        try:
            out.append(registry.get_agent(aid)["name"])
        except Exception:  # noqa: BLE001 - an offboarded or unknown id still shows
            out.append(aid)
    return out


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def sentence(rtype: str, params: dict, agents: list[str] | None = None) -> str:
    """The rule in one plain sentence, exactly as the console, the inbox and the ledger show it."""
    names = _names(agents or [])
    who = _join(names) if names else None
    if rtype == "offer_approvers":
        s = f"Offers over {params['threshold']} need {params['approvers']} approvers"
        return s + (f" (offers from {who})" if who else "")
    if rtype == "quiet_hours":
        tz = TZ_ABBR.get(params["tz"], params["tz"])
        s = (f"{who} may not send outreach" if who else "No outreach") + f" between {params['start']} and {params['end']} {tz}"
        return s + ("; messages wait until then" if params["effect"] == "hold" else "")
    if rtype == "blocked_companies":
        cos = params["companies"]
        shown = _join(cos[:4]) + (f" and {len(cos) - 4} more" if len(cos) > 4 else "")
        target = f"{params['list_name']} ({shown})" if params.get("list_name") else shown
        return f"{who or 'No AI employee'} may {'never' if who else 'ever'} contact people at {target}"
    if rtype == "daily_cap":
        verb, unit = METRICS[params["metric"]]
        if who:
            subj = who if len(names) == 1 else (f"{who} together" if params["per"] == "together" else f"{who} each")
        else:
            subj = "All AI employees together" if params["per"] == "together" else "Each AI employee"
        return f"{subj} may {verb} at most {params['limit']} {unit} a day"
    return rtype


# ---- storage ------------------------------------------------------------------------------------------

def _all() -> dict:
    return store._load().setdefault("rules", {})


def rules(workspace_id: str | None = None, *, include_deleted: bool = False, visible_to=None) -> list[dict]:
    """Rules, oldest first. visible_to=(workspace_id or None for everything): a company sees its own rules and the
    platform-wide ones."""
    with store._lock:
        rows = copy.deepcopy(list(_all().values()))
    if not include_deleted:
        rows = [r for r in rows if not r.get("deleted")]
    if visible_to is not None:
        rows = [r for r in rows if r.get("workspace_id") in (None, visible_to)]
    return sorted(rows, key=lambda r: r["created_at"])


def get(rule_id: str) -> dict | None:
    with store._lock:
        r = _all().get(rule_id)
        return copy.deepcopy(r) if r else None


def _snap(r: dict) -> dict:
    return {k: copy.deepcopy(r.get(k)) for k in ("version", "params", "agents", "enabled", "name", "sentence")}


def _public_hit(r: dict, detail: str, effect: str) -> dict:
    return {"rule_id": r["rule_id"], "version": r["version"], "name": r.get("name") or r["sentence"],
            "sentence": r["sentence"], "type": r["type"], "effect": effect, "detail": detail}


def create(rtype: str, params: dict | None, *, agents: list[str] | None = None, name: str | None = None,
           enabled: bool = True, by: str, workspace_id: str | None) -> dict:
    p = normalize(rtype, params)
    agents = list(dict.fromkeys(agents or []))
    for a in agents:
        registry.get_agent(a)  # unknown id -> RegistryError
    s = sentence(rtype, p, agents)
    r = {"rule_id": store.new_id("rul"), "workspace_id": workspace_id, "type": rtype, "params": p, "agents": agents,
         "name": (name or "").strip()[:120] or None, "sentence": s, "enabled": bool(enabled), "version": 1,
         "created_at": store.now(), "created_by": by, "updated_at": store.now(), "updated_by": by, "deleted": False,
         "history": []}
    r["history"].append({**_snap(r), "at": r["created_at"], "by": by, "change": "created"})
    with store._lock:
        _all()[r["rule_id"]] = r
        store._save()
    ledger.append("rule.created", {"rule_id": r["rule_id"], "version": 1, "type": rtype, "sentence": s, "params": p,
                                   "agents": agents, "enabled": r["enabled"], "by": by, "workspace_id": workspace_id})
    return get(r["rule_id"])


def update(rule_id: str, *, by: str, params: dict | None = None, agents: list[str] | None = None,
           name: str | None = None, enabled: bool | None = None, note: str | None = None) -> dict:
    cur = get(rule_id)
    if not cur or cur.get("deleted"):
        raise KeyError(rule_id)
    new_params = normalize(cur["type"], {**cur["params"], **params}) if params is not None else cur["params"]
    new_agents = list(dict.fromkeys(agents)) if agents is not None else cur["agents"]
    for a in new_agents:
        if a not in cur["agents"]:
            registry.get_agent(a)
    new_enabled = cur["enabled"] if enabled is None else bool(enabled)
    new_name = cur.get("name") if name is None else ((name or "").strip()[:120] or None)
    changes = [k for k, old, new in (("params", cur["params"], new_params), ("agents", cur["agents"], new_agents),
                                     ("enabled", cur["enabled"], new_enabled), ("name", cur.get("name"), new_name))
               if old != new]
    if not changes:
        return cur
    s = sentence(cur["type"], new_params, new_agents)
    kind = ("rule.enabled" if new_enabled else "rule.disabled") if changes == ["enabled"] else "rule.updated"

    def fn(r: dict) -> None:
        r.update(params=new_params, agents=new_agents, enabled=new_enabled, name=new_name, sentence=s,
                 version=r["version"] + 1, updated_at=store.now(), updated_by=by)
        r["history"].append({**_snap(r), "at": r["updated_at"], "by": by, "change": kind.split(".")[1], "note": note})
    with store._lock:
        fn(_all()[rule_id])
        store._save()
    ledger.append(kind, {"rule_id": rule_id, "version": cur["version"] + 1, "type": cur["type"], "sentence": s,
                         "before": cur["sentence"], "changed": changes, "params": new_params, "agents": new_agents,
                         "enabled": new_enabled, "by": by, "note": note, "workspace_id": cur.get("workspace_id")})
    return get(rule_id)


def delete(rule_id: str, *, by: str, note: str | None = None) -> dict:
    """Soft delete: the rule stops applying, its history stays (an audit needs to see what was enforced and when)."""
    cur = get(rule_id)
    if not cur or cur.get("deleted"):
        raise KeyError(rule_id)
    with store._lock:
        r = _all()[rule_id]
        r.update(deleted=True, enabled=False, version=r["version"] + 1, updated_at=store.now(), updated_by=by)
        r["history"].append({**_snap(r), "at": r["updated_at"], "by": by, "change": "deleted", "note": note})
        store._save()
    ledger.append("rule.deleted", {"rule_id": rule_id, "version": cur["version"] + 1, "type": cur["type"],
                                   "sentence": cur["sentence"], "by": by, "note": note,
                                   "workspace_id": cur.get("workspace_id")})
    return get(rule_id)


# ---- which rules cover an agent --------------------------------------------------------------------------

def _default_ws() -> set[str]:
    try:
        from ..accounts.authz import _default_workspace_ids
        return _default_workspace_ids()
    except Exception:  # noqa: BLE001 - no accounts store: only platform-wide rules reach unowned agents
        return set()


def applies_to(r: dict, agent: dict) -> bool:
    if not r.get("enabled") or r.get("deleted"):
        return False
    if r.get("agents") and agent.get("agent_id") not in r["agents"]:
        return False
    ws = r.get("workspace_id")
    if ws is None:
        return True
    aws = agent.get("workspace_id")
    return aws == ws if aws else ws in _default_ws()


def active_for(agent: dict | str, rtype: str | None = None) -> list[dict]:
    if isinstance(agent, str):
        try:
            agent = registry.get_agent(agent)
        except Exception:  # noqa: BLE001
            return []
    with store._lock:
        rows = [r for r in _all().values() if (rtype is None or r["type"] == rtype)]
        rows = copy.deepcopy(rows)
    return [r for r in sorted(rows, key=lambda r: r["created_at"]) if applies_to(r, agent)]


def _agent(agent: dict | str) -> dict | None:
    if isinstance(agent, dict):
        return agent
    try:
        return registry.get_agent(agent)
    except Exception:  # noqa: BLE001
        return None


# ---- the checks ---------------------------------------------------------------------------------------

def _in_window(p: dict, at: datetime) -> tuple[bool, str]:
    local = at.astimezone(ZoneInfo(p["tz"]))
    t = local.time()
    a, b = time.fromisoformat(p["start"]), time.fromisoformat(p["end"])
    inside = (a <= t < b) if a < b else (t >= a or t < b)
    return inside, local.strftime("%H:%M")


def send_hits(agent: dict | str, to: dict | None, scope: str | None = None, *, at: datetime | None = None) -> list[dict]:
    """Rules a message from this agent to `to` breaks right now: effect "block" (never send it) or "hold" (wait in the
    approval inbox until the window ends)."""
    ag = _agent(agent)
    if not ag:
        return []
    to = to or {}
    at = at or _now()
    out = []
    for r in active_for(ag):
        p = r["params"]
        if r["type"] == "blocked_companies":
            from ..verify.profile import same_company
            co = str(to.get("company") or "")
            dom = str(to.get("email") or "").rsplit("@", 1)[-1].lower() if "@" in str(to.get("email") or "") else ""
            hit = next((c for c in p["companies"] if (co and same_company(co, c))
                        or (dom and (c.lower() == dom or c.lower().endswith("." + dom) or dom.endswith("." + c.lower())))), None)
            if hit:
                label = f" ({p['list_name']})" if p.get("list_name") else ""
                out.append(_public_hit(r, f"{to.get('name') or 'The recipient'} works at {co or dom}, which is on the "
                                          f"list{label}", "block"))
        elif r["type"] == "quiet_hours" and (scope or "outreach").startswith("outreach"):
            inside, local = _in_window(p, at)
            if inside:
                tz = TZ_ABBR.get(p["tz"], p["tz"])
                out.append(_public_hit(r, f"it's {local} {tz}; outreach opens at {p['end']} {tz}", p["effect"]))
    return out


def offer_approvers(agent: dict | str, compensation: Any) -> tuple[int, list[dict]]:
    """How many different people must approve this offer, and the rules that say so (the strictest rule wins). An
    amount that can't be read counts as over the threshold: fail closed."""
    ag = _agent(agent)
    if not ag:
        return 1, []
    amount, note = parse_money(compensation)
    need, hits = 1, []
    for r in active_for(ag, "offer_approvers"):
        p = r["params"]
        if amount is None:
            detail = f"couldn't read an amount in “{str(compensation or '')[:60]}”, so the rule applies"
        elif amount > p["threshold_inr"]:
            detail = f"{fmt_inr(amount)} is over {p['threshold']}" + (f" ({note})" if note else "")
        else:
            continue
        hits.append(_public_hit(r, f"{detail}: {p['approvers']} different people must approve", "approvers"))
        need = max(need, p["approvers"])
    return need, hits


def cap_hit(agent: dict | str, metric: str, n: int = 1) -> dict | None:
    """The first daily_cap rule that n more of `metric` would break, or None."""
    ag = _agent(agent)
    if not ag:
        return None
    rows = active_for(ag, "daily_cap")
    rows = [r for r in rows if r["params"]["metric"] == metric]
    if not rows:
        return None
    for r in rows:
        p = r["params"]
        if p["per"] == "together":
            group = [a for a in registry.list_agents() if applies_to(r, a)]
            used = sum(store.usage(a["agent_id"]).get(metric, 0) for a in group)
        else:
            used = store.usage(ag["agent_id"]).get(metric, 0)
        if used + n > p["limit"]:
            unit = METRICS[metric][1]
            who = "together" if p["per"] == "together" else f"by {ag['name']}"
            return _public_hit(r, f"{used} of {p['limit']} {unit} used today {who}", "block")
    return None


def explain(hit: dict) -> str:
    """'Blocked by rule “Offers over ₹30L need 2 approvers” (v2): ₹42L is over ₹30L.'"""
    verb = {"block": "Blocked", "hold": "Held", "approvers": "Needs more approvers"}.get(hit["effect"], "Stopped")
    return f"{verb} by rule “{hit['name']}” (v{hit['version']}): {hit['detail']}"


def enforced(hit: dict, agent: dict | str | None, action: str, outcome: str, *, target: dict | None = None,
             **extra: Any) -> str | None:
    """One rule.enforced ledger entry: which rule (and version) stopped or held what."""
    ag = _agent(agent) if agent else None
    payload = {"rule_id": hit["rule_id"], "version": hit["version"], "name": hit["name"], "sentence": hit["sentence"],
               "type": hit["type"], "effect": hit["effect"], "detail": hit["detail"], "action": action,
               "outcome": outcome, "agent_id": (ag or {}).get("agent_id"), "agent_name": (ag or {}).get("name"),
               **({"to": {k: target.get(k) for k in ("name", "company", "profile_url") if target.get(k)}} if target else {}),
               **extra}
    try:
        return ledger.append("rule.enforced", payload)
    except Exception as e:  # noqa: BLE001 - a ledger failure must not turn a block into an allow
        log.warning("rules: ledger append failed: %s", e)
        return None


# ---- approvals with a quorum ---------------------------------------------------------------------------

def approver_identity(by: str) -> tuple[str, str]:
    """(key, label) for counting distinct approvers: the signed-in user (session or alert link), else the label."""
    try:
        from ..accounts.authz import current
        p = current()
    except Exception:  # noqa: BLE001
        p = None
    if p is not None and p.user:
        return f"user:{p.user.get('id') or p.user.get('email')}", p.user.get("email") or by
    return f"label:{(by or 'employer').strip().lower()}", by or "employer"


def add_approver(approval_id: str, by: str, needed: int, hits: list[dict]) -> tuple[dict, bool]:
    """Record one approval toward the quorum, atomically. Returns (approval, quorum_met). Raises RuleError if this
    person already approved (the same person can't count twice)."""
    key, label = approver_identity(by)
    with store._lock:
        a = store._load()["approvals"].get(approval_id)
        if not a or a["status"] != "pending":
            raise RuleError(f"approval is {a['status'] if a else 'unknown'}")
        prior = a.get("approvals") or []
        if any(x.get("key") == key for x in prior):
            rule = hits[0]["name"] if hits else "A company rule"
            raise RuleError(f"You already approved this. “{rule}” needs {needed} different people: ask someone else "
                            f"to approve it ({len(prior)} of {needed} so far)")
        rec = {"key": key, "by": label, "at": store.now()}
        a["approvals"] = prior + [rec]
        a["approvals_needed"] = needed
        a["rules"] = hits
        met = len(a["approvals"]) >= needed
        store._save()
        return copy.deepcopy(a), met


def reset_approvals(approval_id: str, by: str) -> None:
    """An edit restarts the count: earlier approvals were for different text. The editor counts as the first."""
    key, label = approver_identity(by)
    store.update_approval(approval_id, approvals=[{"key": key, "by": label, "at": store.now(), "edited": True}])


def public(r: dict) -> dict:
    return {**r, "type_label": TYPES.get(r["type"], {}).get("label", r["type"]),
            "applies_to": TYPES.get(r["type"], {}).get("applies_to"), "agent_names": _names(r.get("agents") or [])}


def templates() -> list[dict]:
    return [{"type": k, **v, "example_sentence": sentence(k, normalize(k, v["example"]))} for k, v in TYPES.items()]
