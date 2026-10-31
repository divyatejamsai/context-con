"""Alerts: when an AI employee needs a person, tell the person who's responsible, by email, Slack and the console bell.

What raises an alert (from the runtime store and the ledger, as they happen in the API process):
    approval   an agent is holding a message or an offer letter for approval      (runtime store: new approval)
    approval   a two-approver item got its first approval and needs a second person (ledger: runtime.approval)
    block      Send Guard blocked a draft, a task or an offer was refused,           (ledger: guard.verdict block,
               or a rule blocked something                                             task.refused, offer.refused, rule.enforced)
    stop       an agent was suspended (payroll check, sponsor, admin) or an emergency stop froze agents
                                                                                     (ledger: passport.revoked, freeze.started)
Who: the agent's assigned recruiters who can act (member or above), then its company's admins and owners. The
first of them whose preferences allow the channel gets the email / Slack alert, with Approve / Reject links bound to
them (app/alerts/links.py). Everyone who can see the agent sees it on the bell.

Email goes to OUTBOUND_TEST_TO only, never to a real person's address (user decision: no emails to real people).
The alert says whose alert it is. Slack posts to SLACK_WEBHOOK_URL (an incoming webhook) when it's set.
Nothing here can fail the action that raised the alert: delivery runs in the background and errors are recorded on
the alert, never raised.
"""
from __future__ import annotations

import asyncio
import copy
import html
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import links
from .links import LinkError

log = logging.getLogger(__name__)

MAX_ALERTS = 400
DEDUPE_SECONDS = 600            # the same block for the same agent and person: one alert per 10 minutes
EMAILS_PER_HOUR = int(os.getenv("ALERT_EMAILS_PER_HOUR", "30"))
DEFAULT_PREFS = {"email": True, "slack": True, "approval": True, "block": True, "stop": True}
TOPIC = {"approval": "approval", "block": "block", "rule": "block", "stop": "stop", "test": None}
PREF_LABELS = {"approval": "Approvals waiting on you", "block": "Blocked messages and refused work",
               "stop": "Suspensions and emergency stops"}

_lock = threading.RLock()
_cache: dict | None = None
_cache_path: Path | None = None
_pending: set = set()
_main_loop: asyncio.AbstractEventLoop | None = None
_installed = False


# ---- storage (one JSON file next to runtime.json; ALERTS_PATH overrides) ------------------------------------------

def path() -> Path:
    if os.getenv("ALERTS_PATH"):
        return Path(os.environ["ALERTS_PATH"])
    from ..runtime.store import path as runtime_path
    return runtime_path().parent / "alerts.json"


def _empty() -> dict:
    return {"alerts": [], "used": {}, "prefs": {}, "email_log": []}


def _load() -> dict:
    global _cache, _cache_path
    p = path()
    if _cache is None or _cache_path != p:
        _cache_path = p
        try:
            _cache = {**_empty(), **json.loads(p.read_text())}
        except (OSError, json.JSONDecodeError):
            _cache = _empty()
    return _cache


def _save() -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    s = _load()
    s["alerts"] = s["alerts"][-MAX_ALERTS:]
    cutoff = time.time() - 7 * 86400
    s["used"] = {k: v for k, v in s["used"].items() if v.get("t", 0) > cutoff}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, default=str))
    tmp.replace(p)


def reset_cache() -> None:
    global _cache, _cache_path
    with _lock:
        _cache, _cache_path = None, None


def _now() -> str:
    from ..runtime.store import now
    return now()


def _when(t: float) -> str:
    return time.strftime("%d %b, %H:%M UTC", time.gmtime(t))


def get(alert_id: str) -> dict | None:
    with _lock:
        a = next((x for x in _load()["alerts"] if x["alert_id"] == alert_id), None)
        return copy.deepcopy(a) if a else None


def all_alerts() -> list[dict]:
    with _lock:
        return copy.deepcopy(_load()["alerts"])


def _update(alert_id: str, fn) -> None:
    with _lock:
        a = next((x for x in _load()["alerts"] if x["alert_id"] == alert_id), None)
        if a:
            fn(a)
            _save()


# ---- preferences ---------------------------------------------------------------------------------------------------

def prefs(key: str | None) -> dict:
    with _lock:
        return {**DEFAULT_PREFS, **(_load()["prefs"].get(key or "_open") or {})}


def set_prefs(key: str | None, changes: dict) -> dict:
    with _lock:
        cur = _load()["prefs"].setdefault(key or "_open", {})
        cur.update({k: bool(v) for k, v in changes.items() if k in DEFAULT_PREFS and v is not None})
        _save()
    return prefs(key)


def _wants(person: dict | None, channel: str, kind: str) -> bool:
    p = prefs((person or {}).get("id"))
    topic = TOPIC.get(kind)
    return bool(p.get(channel)) and (topic is None or bool(p.get(topic)))


# ---- who is responsible --------------------------------------------------------------------------------------------

def _agent(agent_id: str | None) -> dict:
    if not agent_id:
        return {}
    try:
        from ..agents import registry
        return registry.get_agent(agent_id)
    except Exception:  # noqa: BLE001
        return {"agent_id": agent_id, "name": agent_id}


def responsible(agent: dict) -> list[dict]:
    """People to alert about this agent, most responsible first: assigned recruiters who can act, then admins/owners."""
    try:
        from ..accounts import authz
        from ..accounts.api import store as accounts
        s = accounts()
        ws = agent.get("workspace_id")
        cids = [ws] if ws else sorted(authz._default_workspace_ids())
        users = [u for c in cids for u in s.members(c)]
    except Exception:  # noqa: BLE001 - no accounts yet: the employer, at the test inbox
        log.debug("alerts: no accounts to resolve", exc_info=True)
        return []
    ops = authz.operator_emails()
    users = [u for u in users if u["email"].lower() not in ops]
    member = authz.RANK["member"]
    assigned = set(agent.get("assignees") or [])
    first = [u for u in users if u["id"] in assigned and authz.RANK.get(u["workspace_role"], -1) >= member]
    admins = [u for u in users if u["workspace_role"] in ("admin", "owner")]
    out, seen = [], set()
    for u in first + admins:
        if u["id"] not in seen:
            seen.add(u["id"])
            out.append({"id": u["id"], "email": u["email"], "name": u["full_name"], "role": u["workspace_role"]})
    return out


# ---- raising alerts ------------------------------------------------------------------------------------------------

def _console(path_: str) -> str:
    from ..agents.seal import base_url
    return f"{base_url()}{path_}"


def raise_alert(kind: str, title: str, detail: str, *, agent_id: str | None = None, agent_ids: list[str] | None = None,
                approval_id: str | None = None, source: str | None = None, facts: list[tuple[str, str]] | None = None,
                dedupe: str | None = None, exclude: set[str] | None = None, recipients: list[dict] | None = None) -> dict | None:
    """Record an alert and deliver it in the background. Returns the alert (None if deduplicated)."""
    ids = list(dict.fromkeys([x for x in ([agent_id] if agent_id else []) + list(agent_ids or []) if x]))
    agent = _agent(ids[0] if ids else None)
    people = recipients if recipients is not None else responsible(agent)
    if exclude:
        people = [p for p in people if p["id"] not in exclude and p["email"] not in exclude]
    with _lock:
        st = _load()
        if dedupe:
            cutoff = time.time() - DEDUPE_SECONDS
            if any(a.get("dedupe") == dedupe and a.get("t", 0) > cutoff for a in st["alerts"]):
                return None
        alert = {"alert_id": f"alr_{os.urandom(5).hex()}", "kind": kind, "title": title, "detail": detail[:1500],
                 "facts": [list(f) for f in (facts or [])], "agent_id": ids[0] if ids else None, "agent_ids": ids,
                 "agent_name": agent.get("name"), "workspace_id": agent.get("workspace_id"), "approval_id": approval_id,
                 "created_at": _now(), "t": time.time(), "source": source, "dedupe": dedupe,
                 "recipients": people, "read_by": [], "channels": {},
                 "console_path": "/console?view=work" if approval_id else (f"/console?agent={ids[0]}" if ids else "/console")}
        st["alerts"].append(alert)
        _save()
    _schedule(deliver, alert["alert_id"])
    return copy.deepcopy(alert)


def _schedule(fn, *args) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        t = loop.create_task(fn(*args))
        _pending.add(t)
        t.add_done_callback(_pending.discard)
    elif _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(fn(*args), _main_loop)
    else:
        threading.Thread(target=lambda: asyncio.run(fn(*args)), daemon=True).start()


async def drain() -> None:
    """Wait for deliveries in flight (tests, shutdown)."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


# ---- delivery ------------------------------------------------------------------------------------------------------

def _pick(alert: dict, channel: str) -> tuple[bool, dict | None]:
    """(send?, the person it's for). With no accounts at all, it's for the employer (prefs under "_open")."""
    people = alert["recipients"]
    if not people:
        return _wants(None, channel, alert["kind"]), None
    for p in people:
        if _wants(p, channel, alert["kind"]):
            return True, p
    return False, None


def _links(alert: dict, person: dict | None, channel: str) -> dict:
    out = {"open": _console(alert["console_path"])}
    if alert.get("approval_id") and alert["kind"] == "approval":
        lid = f"{alert['alert_id']}.{(person or {}).get('id') or 'employer'}"
        for d in links.ACTIONS:
            out[d] = _console(f"/act/{links.make(alert['approval_id'], d, person, lid)}")
    return out


async def deliver(alert_id: str) -> None:
    alert = get(alert_id)
    if not alert:
        return
    for channel, send in (("email", _send_email), ("slack", _send_slack)):
        ok, person = _pick(alert, channel)
        if not ok:
            res = {"status": "off", "why": "turned off in alert preferences"}
        else:
            try:
                res = await send(alert, person, _links(alert, person, channel))
            except Exception as e:  # noqa: BLE001
                log.warning("alert %s %s failed: %s", alert_id, channel, e)
                res = {"status": "failed", "why": f"{type(e).__name__}: {e}"[:300]}
            if person:
                res["for"] = person["email"]
        res["at"] = _now()
        _update(alert_id, lambda a, c=channel, r=res: a["channels"].__setitem__(c, r))


def _rate_ok() -> bool:
    with _lock:
        st = _load()
        now = time.time()
        st["email_log"] = [t for t in st["email_log"] if t > now - 3600]
        if len(st["email_log"]) >= EMAILS_PER_HOUR:
            return False
        st["email_log"].append(now)
        _save()
        return True


def email_status() -> dict:
    from ..outbound import mailer
    c = mailer.config()
    return {"ready": c["ready"], "to": c["test_to"], "why": c["reason"] or None, "provider": c["provider"]}


async def _send_email(alert: dict, person: dict | None, lk: dict) -> dict:
    from ..outbound import mailer
    st = email_status()
    if not st["ready"]:
        return {"status": "skipped", "why": st["why"]}
    if not _rate_ok():
        return {"status": "skipped", "why": f"more than {EMAILS_PER_HOUR} alert emails this hour; see the console"}
    subject, text, body = render_email(alert, person, lk, st["to"])
    d = await mailer.send_transactional(st["to"], subject, text, html=body, from_name="Agaxes alerts")
    return {"status": "sent", "to": d.delivered_to, "provider": d.provider}


def slack_url() -> str | None:
    return os.getenv("SLACK_WEBHOOK_URL") or os.getenv("ALERT_SLACK_WEBHOOK_URL") or None


async def _send_slack(alert: dict, person: dict | None, lk: dict) -> dict:
    url = slack_url()
    if not url:
        return {"status": "skipped", "why": "Slack isn't set up: add SLACK_WEBHOOK_URL (an incoming webhook) to backend/.env"}
    import httpx
    who = f" for {person['name']}" if person else ""
    lines = [f"*{alert['title']}*{who}"]
    if alert["detail"]:
        lines.append("> " + alert["detail"][:600].replace("\n", "\n> "))
    lines += [f"*{k}:* {v}" for k, v in alert["facts"][:6]]
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]}}]
    buttons = []
    if "approve" in lk:
        buttons += [{"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Approve"}, "url": lk["approve"]},
                    {"type": "button", "style": "danger", "text": {"type": "plain_text", "text": "Reject"}, "url": lk["reject"]}]
    buttons.append({"type": "button", "text": {"type": "plain_text", "text": "Open in Agaxes"}, "url": lk["open"]})
    blocks.append({"type": "actions", "elements": buttons})
    if "approve" in lk:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                       f"Links work once, for {person['email'] if person else 'you'}, for {links.LINK_HOURS:g} hours."}]})
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.post(url, json={"text": alert["title"], "blocks": blocks})
    if r.status_code >= 300:
        return {"status": "failed", "why": f"Slack answered {r.status_code}: {r.text[:200]}"}
    return {"status": "sent"}


def render_email(alert: dict, person: dict | None, lk: dict, inbox: str) -> tuple[str, str, str]:
    """(subject, plain text, HTML). The HTML has real buttons; the text part has the same links."""
    who = person["email"] if person else "the employer"
    subject = f"[Agaxes] {alert['title']}"
    note = (f"Test inbox: this alert is for {who}. Agaxes sends every alert to {inbox}, never to anyone else."
            if (person and person["email"] != inbox) else "")
    t = [alert["title"], ""]
    if alert["detail"]:
        t += [alert["detail"], ""]
    t += [f"{k}: {v}" for k, v in alert["facts"]]
    if "approve" in lk:
        t += ["", f"Approve: {lk['approve']}", f"Reject:  {lk['reject']}",
              f"(Each link works once, only for {who}, for {links.LINK_HOURS:g} hours. Opening it shows what you're "
              "deciding before anything happens.)"]
    t += ["", f"Open in Agaxes: {lk['open']}"]
    if note:
        t += ["", note]
    e = html.escape
    btn = ("display:inline-block;padding:10px 18px;border-radius:8px;font:600 14px -apple-system,Segoe UI,sans-serif;"
           "text-decoration:none;margin:0 8px 8px 0;")
    buttons = ""
    if "approve" in lk:
        buttons = (f'<a href="{e(lk["approve"])}" style="{btn}background:#16a34a;color:#fff">Approve</a>'
                   f'<a href="{e(lk["reject"])}" style="{btn}background:#fff;color:#b91c1c;border:1px solid #fca5a5">Reject</a>')
    buttons += f'<a href="{e(lk["open"])}" style="{btn}background:#fff;color:#111;border:1px solid #d4d4d8">Open in Agaxes</a>'
    facts = "".join(f'<tr><td style="padding:2px 12px 2px 0;color:#71717a">{e(k)}</td><td style="padding:2px 0">{e(str(v))}</td></tr>'
                    for k, v in alert["facts"])
    detail = (f'<div style="white-space:pre-wrap;border-left:3px solid #e4e4e7;padding:8px 12px;margin:12px 0;color:#27272a">'
              f'{e(alert["detail"])}</div>') if alert["detail"] else ""
    fine = (f'<p style="color:#71717a;font-size:12px">Each button works once, only for {e(who)}, for '
            f'{links.LINK_HOURS:g} hours. Opening it shows what you\'re deciding before anything happens.</p>') if "approve" in lk else ""
    body = (f'<div style="font:14px/1.5 -apple-system,Segoe UI,sans-serif;color:#18181b;max-width:560px">'
            f'<p style="font-size:12px;color:#71717a;margin:0 0 4px">Agaxes · needs you</p>'
            f'<h2 style="font-size:17px;margin:0 0 8px">{e(alert["title"])}</h2>{detail}'
            f'<table style="font-size:13px;margin:8px 0 16px">{facts}</table>{buttons}{fine}'
            + (f'<p style="color:#a1a1aa;font-size:11.5px;margin-top:16px">{e(note)}</p>' if note else "") + "</div>")
    return subject, "\n".join(t), body


# ---- event handlers (installed at API startup) ---------------------------------------------------------------------

def install() -> None:
    """Listen to new approvals and ledger entries in this process. ALERTS_ENABLED=0 turns alerts off."""
    global _installed, _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    if _installed or os.getenv("ALERTS_ENABLED", "1") == "0":
        return
    from ..agents import ledger
    from ..runtime import store
    store.APPROVAL_LISTENERS.append(on_approval)
    ledger.LISTENERS.append(on_ledger)
    _installed = True


def uninstall() -> None:
    global _installed
    from ..agents import ledger
    from ..runtime import store
    for lst, fn in ((store.APPROVAL_LISTENERS, on_approval), (ledger.LISTENERS, on_ledger)):
        while fn in lst:
            lst.remove(fn)
    _installed = False


def _who(to: dict | None) -> str:
    to = to or {}
    return to.get("name") or to.get("email") or "someone"


def _approval_facts(a: dict, agent: dict) -> list[tuple[str, str]]:
    f: list[tuple[str, str]] = [("Agent", agent.get("name") or a.get("agent_name") or a["agent_id"])]
    sp = ((agent.get("passport") or {}).get("sponsor") or {})
    if sp.get("name"):
        f.append(("Vouched for by", f"{sp['name']}{', ' + sp['company'] if sp.get('company') else ''}"))
    to = a.get("to") or {}
    f.append(("To", _who(to) + (f", {to['company']}" if to.get("company") else "")))
    checks = (a.get("preview") or {}).get("checks") or []
    if checks:
        passed = sum(c.get("status") == "pass" for c in checks)
        f.append(("Send Guard", f"cleared ({passed} of {len(checks)} checks passed)"))
    need = int(a.get("approvals_needed") or 1)
    if need > 1:
        f.append(("Approvals", f"{len(a.get('approvals') or [])} of {need}: needs {need} different people"))
    for r in (a.get("rules") or [])[:3]:
        f.append(("Rule", r.get("sentence") or r.get("name") or r.get("rule_id") or "a workspace rule"))
    return f


def on_approval(a: dict) -> None:
    agent = _agent(a.get("agent_id"))
    name = agent.get("name") or a.get("agent_name") or "An agent"
    what = "sign an offer letter for" if a.get("action") == "sign_offer" else "send a message to"
    raise_alert("approval", f"{name} wants to {what} {_who(a.get('to'))}", a.get("body") or "",
                agent_id=a["agent_id"], approval_id=a["approval_id"], facts=_approval_facts(a, agent))


def _failed(checks: list[dict]) -> list[str]:
    return [c.get("detail") or c.get("name") or "" for c in checks or [] if c.get("status") != "pass"]


def on_ledger(e: dict) -> None:
    kind, p = e.get("kind") or "", e.get("payload") or {}
    src = e.get("hash")
    if kind.startswith("alert."):
        return
    aid = p.get("agent_id") or p.get("subject")
    if kind == "guard.verdict" and p.get("decision") not in (None, "allow"):
        agent = _agent(aid)
        reasons = _failed(p.get("checks") or [])
        to = p.get("to") or {}
        raise_alert("block", f"Send Guard blocked {agent.get('name') or 'an agent'}'s message to {_who(to)}",
                    "\n".join(f"• {r}" for r in reasons[:4]) or "Blocked before it left.",
                    agent_id=aid, source=src, facts=[("Agent", agent.get("name") or aid), ("To", _who(to))],
                    dedupe=f"guard:{aid}:{to.get('profile_url') or to.get('name')}")
    elif kind in ("task.refused", "offer.refused"):
        agent = _agent(aid)
        if kind == "task.refused":
            title, why = f"{agent.get('name') or 'An agent'} was refused work: {p.get('title') or p.get('kind')}", p.get("error") or ""
        else:
            title, why = f"{agent.get('name') or 'An agent'} wasn't allowed to sign an offer", "; ".join(p.get("why") or [])
        raise_alert("block", title, why, agent_id=aid, source=src, facts=[("Agent", agent.get("name") or aid)],
                    dedupe=f"{kind}:{aid}:{p.get('task_id')}")
    elif kind == "rule.enforced" and _blocking(p):
        agent = _agent(aid)
        rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
        name = p.get("name") or rule.get("name") or p.get("sentence") or rule.get("sentence") or "A rule"
        raise_alert("rule", f"Rule blocked {agent.get('name') or 'an agent'}: {name}",
                    p.get("detail") or p.get("sentence") or rule.get("sentence") or "", agent_id=aid, source=src,
                    facts=[("Agent", agent.get("name") or aid), ("Rule", p.get("sentence") or rule.get("sentence") or name)],
                    dedupe=f"rule:{aid}:{p.get('rule_id') or name}:{p.get('task_id') or p.get('approval_id')}")
    elif kind == "passport.revoked":
        reason = p.get("reason") or ""
        if "emergency stop frz_" in reason:  # one alert per stop, from freeze.started
            return
        agent = _agent(aid)
        raise_alert("stop", f"{agent.get('name') or 'An agent'} was suspended", reason, agent_id=aid, source=src,
                    facts=[("Agent", agent.get("name") or aid)])
    elif kind == "freeze.started":
        ids = list(p.get("agent_ids") or [])
        names = p.get("agent_names") or [_agent(x).get("name") or x for x in ids]
        n = len(ids)
        title = (f"Emergency stop: {names[0]} frozen" if n == 1 else f"Emergency stop: {n} agents frozen")
        facts = [("Agents", ", ".join(names[:8]) + (" …" if n > 8 else "")), ("Stopped by", str(p.get("by") or "someone"))]
        if p.get("stopped_tasks") is not None:
            facts.append(("Tasks stopped", str(p["stopped_tasks"] if not isinstance(p["stopped_tasks"], list) else len(p["stopped_tasks"]))))
        if p.get("cancelled_approvals") is not None:
            c = p["cancelled_approvals"]
            facts.append(("Approvals cancelled", str(len(c) if isinstance(c, list) else c)))
        raise_alert("stop", title, p.get("reason") or "", agent_ids=ids, source=src, facts=facts)
    elif kind == "runtime.approval" and p.get("decision") == "approved":
        _maybe_second(p, e)


def _blocking(p: dict) -> bool:
    rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
    eff = str(p.get("effect") or rule.get("effect") or "").lower()
    return any(w in eff for w in ("block", "deny", "refuse", "forbid", "never"))


def _maybe_second(p: dict, e: dict) -> None:
    from ..runtime import store
    a = store.get_approval(p.get("approval_id") or "")
    if not a or a.get("status") != "pending":
        return
    need, got = int(a.get("approvals_needed") or 1), list(a.get("approvals") or [])
    if len(got) >= need:
        return
    done = set()
    for g in got:
        act = g.get("actor") or {}
        done |= {x for x in (act.get("user_id"), act.get("email"), g.get("by")) if x}
    actor = e.get("actor") or {}
    done |= {x for x in (actor.get("user_id"), actor.get("email"), p.get("by")) if x}
    agent = _agent(a["agent_id"])
    first = got[0].get("by") if got else p.get("by")
    what = "an offer letter for" if a.get("action") == "sign_offer" else "a message to"
    raise_alert("approval", f"{len(got)} of {need} approved: {what} {_who(a.get('to'))} needs a second person",
                a.get("body") or "", agent_id=a["agent_id"], approval_id=a["approval_id"], source=e.get("hash"),
                facts=[("Approved by", str(first))] + _approval_facts(a, agent), exclude=done)


# ---- the one-click links -------------------------------------------------------------------------------------------

def _public_approval(a: dict) -> dict:
    to = {k: v for k, v in (a.get("to") or {}).items() if k in ("name", "company", "profile_url")}
    checks = [{k: c.get(k) for k in ("name", "status", "detail")} for c in ((a.get("preview") or {}).get("checks") or [])]
    agent = _agent(a["agent_id"])
    return {"approval_id": a["approval_id"], "action": a.get("action"), "agent_id": a["agent_id"],
            "agent_name": agent.get("name") or a.get("agent_name"), "agent_status": agent.get("status"),
            "sponsor": ((agent.get("passport") or {}).get("sponsor") or {}).get("name"), "to": to,
            "body": a.get("body"), "scope": a.get("scope"), "status": a["status"], "created_at": a.get("created_at"),
            "decided_by": a.get("decided_by"), "decided_at": a.get("decided_at"), "checks": checks,
            "approvals_needed": int(a.get("approvals_needed") or 1),
            "approvals": [{"by": g.get("by"), "at": g.get("at")} for g in (a.get("approvals") or [])],
            "rules": [{k: r.get(k) for k in ("name", "sentence", "effect", "detail")} for r in (a.get("rules") or [])],
            "result": {k: (a.get("result") or {}).get(k) for k in ("sent", "signed", "error", "verify_url")}}


def _claims(token: str) -> tuple[dict, dict]:
    from ..runtime import store
    c = links.read(token)
    a = store.get_approval(c["a"])
    if not a:
        raise LinkError("gone", "What this link was for no longer exists.")
    return c, a


def _person(c: dict) -> tuple[Any, dict]:
    """The Principal the action runs as, and a display dict. Refuses people who've lost access since the alert."""
    from ..accounts import authz
    if not c.get("u"):
        if authz.enforced():
            raise LinkError("login", "This link was made before anyone had an account. Log in to decide.")
        who = {"email": c.get("e") or "employer", "name": "the employer"}
        return authz.Principal(via="alert_link", role="operator", extra={"email": who["email"], "label": "employer"}), who
    from ..accounts.api import store as accounts
    s = accounts()
    try:
        user = s.user(c["u"])
        company = s.company(user["company_id"])
    except Exception:  # noqa: BLE001
        raise LinkError("no_access", "The person this link was for no longer has an account here.") from None
    role = user.get("workspace_role") or "viewer"
    sess = authz.Principal(via="session", role=role if role in authz.RANK else "viewer", user=user, company=company)
    if not sess.can("operate"):
        raise LinkError("no_access", f"{user['email']} is a {role} now and can't approve or reject.")
    return sess, {"email": user["email"], "name": user["full_name"], "id": user["id"], "role": role}


def preview(token: str) -> dict:
    """What a link would do. Never acts (mail scanners open links)."""
    c, a = _claims(token)
    used = _load()["used"].get(c["j"])
    who = {"email": c.get("e"), "name": None}
    state, message = "ready", None
    try:
        _p, who = _person(c)
    except LinkError as e:
        state, message = e.code, e.message
    if used:
        state, message = "used", f"This link was already used to {used.get('action')} ({used.get('by')}, {_when(used.get('t', 0))})."
    elif a["status"] != "pending":
        state, message = "decided", f"Already {a['status'].replace('_', ' ')}{' by ' + a['decided_by'] if a.get('decided_by') else ''}."
    return {"action": c["d"], "state": state, "message": message, "for": who,
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(c["x"])), "approval": _public_approval(a)}


async def act(token: str, note: str | None = None) -> dict:
    """Do what the link says, as the person it was made for. Single use; refused if they've lost access."""
    from ..accounts import authz
    c, a = _claims(token)
    if a["status"] != "pending":
        raise LinkError("decided", f"Already {a['status'].replace('_', ' ')}{' by ' + a['decided_by'] if a.get('decided_by') else ''}.")
    principal, who = _person(c)
    if principal.via == "session":
        if not authz.sees_agent(principal, _agent(a["agent_id"])):
            raise LinkError("no_access", f"{who['email']} can't see this agent any more.")
        principal = authz.Principal(via="alert_link", role=principal.role, user=principal.user, company=principal.company,
                                    extra={"user_id": who["id"], "email": who["email"], "role": who["role"],
                                           "workspace_id": principal.workspace_id})
    principal.extra["link"] = c["j"]
    with _lock:
        st = _load()
        if c["j"] in st["used"]:
            u = st["used"][c["j"]]
            raise LinkError("used", f"This link was already used to {u.get('action')} ({u.get('by')}, {_when(u.get('t', 0))}).")
        st["used"][c["j"]] = {"action": c["d"], "at": _now(), "by": who["email"], "t": time.time()}
        _save()
    by = who["email"]
    tok = authz.CURRENT.set(principal)
    try:
        from ..runtime import api as rapi
        from ..runtime.worker import execute_approval, reject_approval
        if c["d"] == "approve":
            out = await (rapi.RUNTIME.approve(a["approval_id"], by) if rapi.RUNTIME else execute_approval(a["approval_id"], by))
        else:
            out = (rapi.RUNTIME.reject(a["approval_id"], by, note) if rapi.RUNTIME else reject_approval(a["approval_id"], by, note))
    except ValueError as e:  # refused (already decided, a rule holds it): the link stays usable if it's still pending
        with _lock:
            _load()["used"].pop(c["j"], None)
            _save()
        raise LinkError("refused", str(e)) from None
    finally:
        authz.CURRENT.reset(tok)
    return {"action": c["d"], "state": "done", "for": who, "approval": _public_approval(out)}


# ---- the bell ------------------------------------------------------------------------------------------------------

def _reader_key(principal) -> str:
    return ((principal.user or {}).get("id") if principal is not None and principal.user else None) or "_open"


def _sees(a: dict, ids: set | None, me: str) -> bool:
    if ids is None:
        return True
    if a.get("agent_ids"):
        return bool(set(a["agent_ids"]) & ids)
    return any(p.get("id") == me for p in a.get("recipients") or [])  # e.g. a test alert: its own person only


def feed(principal, limit: int = 40) -> dict:
    from ..accounts import authz
    from ..runtime import store
    ids = authz.visible_agent_ids(principal)
    me = _reader_key(principal)
    rows = [a for a in all_alerts() if _sees(a, ids, me)]
    rows = rows[::-1][:limit]
    apv = {a["approval_id"]: a for a in store.approvals()} if any(r.get("approval_id") for r in rows) else {}
    items = []
    for r in rows:
        live = apv.get(r.get("approval_id") or "")
        items.append({k: r.get(k) for k in ("alert_id", "kind", "title", "detail", "facts", "agent_id", "agent_name",
                                            "approval_id", "created_at", "console_path", "channels")}
                     | {"read": me in r.get("read_by", []),
                        "for": [p["email"] for p in r.get("recipients") or []][:3],
                        "approval_status": live["status"] if live else None,
                        "decided_by": live.get("decided_by") if live else None})
    unread = sum(1 for a in all_alerts() if _sees(a, ids, me) and me not in a.get("read_by", []))
    return {"items": items, "unread": unread}


def mark_read(principal, alert_ids: list[str] | None) -> int:
    from ..accounts import authz
    ids = authz.visible_agent_ids(principal)
    me = _reader_key(principal)
    n = 0
    with _lock:
        for a in _load()["alerts"]:
            if (alert_ids is None or a["alert_id"] in alert_ids) and _sees(a, ids, me):
                if me not in a["read_by"]:
                    a["read_by"].append(me)
                    n += 1
        _save()
    return n
