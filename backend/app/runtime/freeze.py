"""Emergency stop: freeze one agent, every agent a person vouched for, or every agent, in one call.

    preview(scope, target)                 who a freeze would hit, and what each of them touched in the last 24 hours
    freeze(rt, scope, target, reason, by)  stops them now (see below) and records the stop on the ledger
    restore(rt, freeze_id, by, client)     brings them back after a fresh sponsor check, optionally with their work
    blast_radius(agent_ids, hours=24)      messages sent, people contacted, data read, approvals, spend, rule blocks

A freeze reuses the controls Agaxes already has, so every check that refuses a suspended agent refuses a frozen one:
  1. registry.suspend for each active agent: the passport is revoked on the ledger, so Send Guard, MCP calls and the
     public /verify links all turn red straight away;
  2. its running task is stopped mid-flight (in-house tasks are cancelled, outside agents are refused on their next
     call) and its queued tasks are cancelled;
  3. drafts waiting for approval are pulled ("expired", nothing can send them) and its schedules are switched off.
Agents that were already suspended stay suspended and are listed; offboarded agents are left out.

Restore reinstates only the agents this freeze suspended, and only if their sponsor check passes again (the same rule
as a manual reinstate). With bring_back it also re-queues the tasks the freeze stopped and puts the pulled drafts back
in front of a person; schedules come back on for every agent that was restored. Ledger kinds: freeze.started,
freeze.restored. Freezes are kept in the runtime store under "freezes".
"""
from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from ..agents import ledger, registry
from . import store

Scope = Literal["agent", "sponsor", "all"]
STOP = "emergency stop"


def _parse(s: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(s) if s else None
    except ValueError:
        return None
    if d is not None and d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


# ---- store ----------------------------------------------------------------------------------------

def _freezes() -> dict[str, dict]:
    return store._load().setdefault("freezes", {})


def _put(rec: dict) -> dict:
    with store._lock:
        _freezes()[rec["freeze_id"]] = rec
        store._save()
    return copy.deepcopy(rec)


def get(freeze_id: str) -> dict | None:
    with store._lock:
        f = _freezes().get(freeze_id)
        return copy.deepcopy(f) if f else None


def freezes() -> list[dict]:
    with store._lock:
        return copy.deepcopy(sorted(_freezes().values(), key=lambda f: f["at"], reverse=True))


def active_for(agent_id: str) -> dict | None:
    """The freeze currently holding this agent, if any."""
    for f in freezes():
        if f["status"] == "active" and any(a["agent_id"] == agent_id for a in f["agents"]):
            return f
    return None


# ---- who gets frozen ------------------------------------------------------------------------------

def sponsor_key(s: dict) -> str:
    return (s.get("profile_url") or s.get("name") or "").strip().lower()


def sponsors(visible: set[str] | None = None) -> list[dict]:
    """Every person who vouches for at least one agent that isn't offboarded, with their agents."""
    out: dict[str, dict] = {}
    for a in registry.list_agents():
        if a["status"] == "offboarded" or (visible is not None and a["agent_id"] not in visible):
            continue
        s = a["passport"]["sponsor"]
        k = sponsor_key(s)
        row = out.setdefault(k, {"key": k, "name": s.get("name"), "title": s.get("title"), "company": s.get("company"),
                                 "profile_url": s.get("profile_url"), "agents": []})
        row["agents"].append({"agent_id": a["agent_id"], "name": a["name"], "status": a["status"]})
    return sorted(out.values(), key=lambda r: (-len(r["agents"]), r["name"] or ""))


def targets(scope: Scope, target: str | None, visible: set[str] | None = None) -> list[dict]:
    agents = [a for a in registry.list_agents()
              if a["status"] != "offboarded" and (visible is None or a["agent_id"] in visible)]
    if scope == "agent":
        if not target:
            raise ValueError("say which agent to freeze")
        hit = [a for a in agents if a["agent_id"] == target or a["name"].lower() == target.strip().lower()]
        if not hit:
            raise KeyError(target)
        return hit[:1]
    if scope == "sponsor":
        if not target:
            raise ValueError("say whose agents to freeze")
        t = target.strip().lower()
        hit = [a for a in agents if t in (sponsor_key(a["passport"]["sponsor"]),
                                         (a["passport"]["sponsor"].get("name") or "").strip().lower())]
        if not hit:
            raise ValueError(f"nobody called {target} vouches for an agent you can see")
        return hit
    if scope == "all":
        if not agents:
            raise ValueError("there are no agents to freeze")
        return agents
    raise ValueError(f"unknown scope {scope!r}: use agent, sponsor or all")


def _label(scope: Scope, target: str | None, hit: list[dict]) -> str:
    if scope == "agent":
        return hit[0]["name"]
    if scope == "sponsor":
        s = hit[0]["passport"]["sponsor"]
        return f"every agent {s.get('name')} vouches for"
    return "every agent"


# ---- what each agent touched ----------------------------------------------------------------------

def _person(to: Any) -> tuple[str, dict] | None:
    if isinstance(to, str):
        return (to.lower(), {"name": to}) if to else None
    if not isinstance(to, dict):
        return None
    name = to.get("name") or to.get("email")
    key = (to.get("profile_url") or to.get("email") or name or "").lower()
    if not key:
        return None
    return key, {"name": name, "company": to.get("company"), "profile_url": to.get("profile_url"), "email": to.get("email")}


def blast_radius(agent_ids: list[str], hours: float = 24, now: datetime | None = None) -> dict:
    """Everything these agents did in the window, from the ledger and the runtime store. Each agent's numbers stand
    on their own; totals add them up (people are de-duplicated across agents)."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    ids = list(dict.fromkeys(agent_ids))
    want = set(ids)
    rows: dict[str, list[dict]] = {a: [] for a in ids}
    for r in ledger._read_raw():
        ts = _parse(r.get("ts"))
        if not ts or ts < since:
            continue
        p = r.get("payload") or {}
        for aid in {p.get("agent_id"), p.get("subject"), (p.get("passport") or {}).get("agent_id")} & want:
            rows[aid].append(r)
    snap = store.snapshot()
    names = {a["agent_id"]: a for a in registry.list_agents()}

    def recent(*stamps: str | None) -> bool:
        return any((d := _parse(s)) and d >= since for s in stamps)

    out, everyone = [], {}
    for aid in ids:
        ag = names.get(aid) or {}
        rs = rows[aid]
        sent: list[dict] = []
        for r in rs:
            p = r.get("payload") or {}
            k = r.get("kind")
            if k == "message.sent":
                sent.append({"ts": r["ts"], "to": p.get("to"), "what": p.get("subject") or "Email",
                             "how": f"email ({p.get('mode')})" if p.get("mode") else "email", "hash": r.get("hash")})
            elif k == "runtime.approval" and p.get("outcome") == "sent":
                sent.append({"ts": r["ts"], "to": p.get("to"), "what": "Approved draft", "how": f"approved by {p.get('by')}",
                             "hash": r.get("hash")})
            elif k == "offer.signed":
                to = p.get("to") or {"name": p.get("candidate"), "profile_url": p.get("profile_url")}
                sent.append({"ts": r["ts"], "to": to, "how": f"approved by {p.get('approved_by')}" if p.get("approved_by") else "signed",
                             "what": "Signed offer letter" + (f" (₹{p['ctc_lpa']}L)" if p.get("ctc_lpa") else ""), "hash": r.get("hash")})
        tasks = [t for t in snap["tasks"].values() if t["agent_id"] == aid and recent(t.get("created_at"), t.get("started_at"), t.get("finished_at"))]
        for t in tasks:  # sent without a person in the loop (approvals switched off for this agent)
            for x in (t.get("output") or {}).get("sends", []):
                if x.get("state") == "sent" and not x.get("approval_id"):
                    sent.append({"ts": t.get("finished_at") or t.get("started_at"), "to": x.get("to"), "what": "Draft",
                                 "how": "sent without approval", "hash": None})
        people: dict[str, dict] = {}
        for m in sent + [{"ts": r["ts"], "to": (r.get("payload") or {}).get("from")} for r in rs if r.get("kind") == "message.reply"]:
            hit = _person(m.get("to"))
            if hit:
                row = people.setdefault(hit[0], {**hit[1], "events": 0, "last": None})
                row["events"] += 1
                row["last"] = max(row["last"] or "", m.get("ts") or "")
        apv = [a for a in snap["approvals"].values() if a["agent_id"] == aid and recent(a.get("created_at"), a.get("decided_at"))]
        crust = sum((t.get("usage") or {}).get("crustdata", 0) for t in tasks)
        llm = sum((t.get("usage") or {}).get("llm", 0) for t in tasks)
        out_sends = sum((t.get("usage") or {}).get("sends", 0) for t in tasks)
        records = sum(len((t.get("output") or {}).get(k, []) or []) for t in tasks for k in ("shortlist", "findings"))
        work = [r for r in rs if (r.get("kind") or "").startswith("work.")]
        reads = [{"ts": r["ts"], "what": (r.get("payload") or {}).get("summary") or r["kind"].removeprefix("work."),
                  "sources": len(r.get("sources") or [])} for r in work]
        reads += [{"ts": t.get("started_at") or t["created_at"], "what": t["title"], "kind": t["kind"], "status": t["status"],
                   "crustdata": (t.get("usage") or {}).get("crustdata", 0)} for t in tasks]
        guard = [r for r in rs if r.get("kind") == "guard.verdict"]
        rules = [r for r in rs if r.get("kind") == "rule.enforced"]
        offers = [r for r in rs if r.get("kind") == "offer.signed"]
        commit = sum(float((r.get("payload") or {}).get("ctc_lpa") or 0) for r in offers)
        approvals = [{"approval_id": a["approval_id"], "action": a.get("action", "send"), "status": a["status"],
                      "to": a.get("to"), "created_at": a.get("created_at"), "decided_at": a.get("decided_at"),
                      "decided_by": a.get("decided_by")} for a in sorted(apv, key=lambda a: a.get("created_at") or "")]
        for p in people.values():
            k = (p.get("profile_url") or p.get("email") or p.get("name") or "").lower()
            everyone.setdefault(k, p)
        out.append({
            "agent_id": aid, "name": ag.get("name", aid), "status": ag.get("status"),
            "sponsor": (ag.get("passport") or {}).get("sponsor"),
            "messages_sent": sorted(sent, key=lambda s: s.get("ts") or "", reverse=True),
            "people": sorted(people.values(), key=lambda p: p.get("last") or "", reverse=True),
            "data": {"crustdata_calls": crust, "llm_calls": llm, "records": records, "reads": sorted(reads, key=lambda r: r.get("ts") or "", reverse=True)[:30]},
            "approvals": approvals,
            "guard": {"checked": len(guard), "blocked": sum((r.get("payload") or {}).get("decision") == "block" for r in guard)},
            "rules_blocked": len(rules),
            "spend": {"crustdata_calls": crust, "llm_calls": llm, "sends": max(out_sends, len(sent)), "offers_signed": len(offers),
                      "offer_ctc_lpa": round(commit, 2) if commit else 0},
            "tasks": {"total": len(tasks), **Counter(t["status"] for t in tasks)},
            "ledger": {"entries": len(rs), "kinds": Counter(r.get("kind") for r in rs).most_common(8),
                       "first_seq": rs[0].get("seq") if rs else None, "last_seq": rs[-1].get("seq") if rs else None},
        })
    totals = {
        "agents": len(out),
        "messages_sent": sum(len(a["messages_sent"]) for a in out),
        "people": len(everyone),
        "crustdata_calls": sum(a["data"]["crustdata_calls"] for a in out),
        "llm_calls": sum(a["data"]["llm_calls"] for a in out),
        "records": sum(a["data"]["records"] for a in out),
        "approvals": sum(len(a["approvals"]) for a in out),
        "pending_approvals": sum(x["status"] == "pending" for a in out for x in a["approvals"]),
        "tasks": sum(a["tasks"]["total"] for a in out),
        "running": sum(a["tasks"].get("running", 0) for a in out),
        "guard_blocked": sum(a["guard"]["blocked"] for a in out),
        "rules_blocked": sum(a["rules_blocked"] for a in out),
        "offers_signed": sum(a["spend"]["offers_signed"] for a in out),
        "ledger_entries": sum(a["ledger"]["entries"] for a in out),
    }
    return {"since": since.isoformat(timespec="seconds"), "until": now.isoformat(timespec="seconds"), "hours": hours,
            "totals": totals, "agents": out}


# ---- freeze and restore ---------------------------------------------------------------------------

def preview(scope: Scope, target: str | None, visible: set[str] | None = None, hours: float = 24) -> dict:
    hit = targets(scope, target, visible)
    ids = [a["agent_id"] for a in hit]
    snap = store.snapshot()
    will = {
        "suspend": [a["name"] for a in hit if a["status"] == "active"],
        "already_suspended": [a["name"] for a in hit if a["status"] == "suspended"],
        "running_tasks": sum(t["status"] == "running" and t["agent_id"] in ids for t in snap["tasks"].values()),
        "queued_tasks": sum(t["status"] == "queued" and t["agent_id"] in ids for t in snap["tasks"].values()),
        "pending_approvals": sum(a["status"] == "pending" and a["agent_id"] in ids for a in snap["approvals"].values()),
        "schedules": sum(s.get("enabled") and s["agent_id"] in ids for s in snap["schedules"].values()),
    }
    return {"scope": scope, "target": target, "label": _label(scope, target, hit),
            "agents": [{"agent_id": a["agent_id"], "name": a["name"], "status": a["status"], "sponsor": a["passport"]["sponsor"]}
                       for a in hit],
            "will": will, "blast": blast_radius(ids, hours)}


def freeze(rt: Any, scope: Scope, target: str | None, reason: str, by: str, visible: set[str] | None = None) -> dict:
    """Stop every targeted agent now. rt is the running supervisor (None when the runtime is off: the passports are
    still revoked and the store updated, there is just no in-process task to cancel)."""
    hit = targets(scope, target, visible)
    reason = (reason or "").strip() or "emergency stop"
    fid = store.new_id("frz")
    who = f"{STOP} {fid} ({by})"
    blast = blast_radius([a["agent_id"] for a in hit])
    agents, stopped, pulled, paused_sched = [], [], [], []
    for a in hit:
        aid = a["agent_id"]
        prior = a["status"]
        if prior == "active":
            registry.suspend(aid, reason, by=who)
        agents.append({"agent_id": aid, "name": a["name"], "prior_status": prior, "prior_reason": a.get("reason"),
                       "sponsor": a["passport"]["sponsor"], "outcome": None})
        why = f"{STOP}: {reason}"
        for t in store.tasks(aid, status=("running", "queued")):
            stopped.append({"task_id": t["task_id"], "agent_id": aid, "kind": t["kind"], "title": t["title"],
                            "input": t.get("input") or {}, "ref": t.get("ref"), "was": t["status"]})
            if t["status"] == "queued":
                _finish(rt, t["task_id"], why)
            elif rt is not None and t["task_id"] in rt.running:
                rt._stop(t["task_id"], why, requeue=False)
            else:  # an outside agent's claimed task (or no runtime): the agent is refused on its next call
                store.task_step(t["task_id"], f"Stopped by Agaxes: {why}. The agent is refused on its next call.", "control")
                _finish(rt, t["task_id"], why)
                if rt is not None:
                    rt._kill_launch(t["task_id"])
        for ap in store.approvals("pending", aid):
            store.update_approval(ap["approval_id"], status="expired", decided_at=store.now(), decided_by=f"{STOP} {fid}",
                                  note=f"pulled by the {STOP}: {reason}")
            _sync(ap, "expired")
            pulled.append({"approval_id": ap["approval_id"], "agent_id": aid, "to": ap.get("to"), "action": ap.get("action", "send")})
        for s in store.schedules():
            if s["agent_id"] == aid and s.get("enabled"):
                store.update_schedule(s["schedule_id"], enabled=False, last_skip=f"switched off by the {STOP}")
                paused_sched.append(s["schedule_id"])
    entry = ledger.append("freeze.started", {
        "freeze_id": fid, "scope": scope, "target": target, "label": _label(scope, target, hit), "reason": reason, "by": by,
        "agent_ids": [a["agent_id"] for a in agents], "agent_names": [a["name"] for a in agents],
        "suspended": [a["name"] for a in agents if a["prior_status"] == "active"],
        "stopped_tasks": [t["task_id"] for t in stopped], "cancelled_approvals": [p["approval_id"] for p in pulled],
        "schedules_off": paused_sched, "blast_totals": blast["totals"],
    })
    rec = {"freeze_id": fid, "scope": scope, "target": target, "label": _label(scope, target, hit), "reason": reason,
           "by": by, "at": store.now(), "status": "active", "agents": agents, "stopped_tasks": stopped,
           "pulled_approvals": pulled, "schedules_off": paused_sched, "blast": blast, "ledger_entry": entry,
           "restored_at": None, "restored_by": None, "restore_entry": None}
    out = _put(rec)
    if rt is not None:
        rt.enforce()
        rt.wake()
    return out


def _finish(rt: Any, task_id: str, why: str) -> None:
    if rt is not None:
        rt._finish(task_id, "cancelled", error=why)
        return
    t = store.get_task(task_id)
    if not t:
        return
    entry = ledger.append("task.cancelled", {"agent_id": t["agent_id"], "task_id": task_id, "kind": t["kind"],
                                             "title": t["title"], "error": why})
    store.task_mutate(task_id, lambda x: (x.update(status="cancelled", finished_at=store.now(), error=why, waiting_on=None),
                                          x["ledger"].append(entry)))


def _sync(ap: dict, state: str) -> None:
    from .worker import _sync_send
    if ap.get("task_id"):
        _sync_send(ap["task_id"], ap["approval_id"], state)


async def restore(rt: Any, freeze_id: str, by: str, client: Any, *, bring_back: bool = False) -> dict:
    """Lift a freeze. Only agents this freeze suspended come back, and only if a fresh sponsor check passes; the rest
    stay suspended with the reason. bring_back re-queues the stopped tasks and returns pulled drafts to pending."""
    rec = get(freeze_id)
    if not rec:
        raise KeyError(freeze_id)
    if rec["status"] != "active":
        raise ValueError(f"this stop was already lifted {rec.get('restored_at') or ''}".strip())
    restored, still, kept = [], [], []
    for a in rec["agents"]:
        aid = a["agent_id"]
        try:
            cur = registry.get_agent(aid)
        except registry.RegistryError:
            a["outcome"] = "gone"
            continue
        if a["prior_status"] != "active":
            a["outcome"] = "was_suspended_before"
            kept.append(a["name"])
            continue
        other = next((f for f in freezes() if f["status"] == "active" and f["freeze_id"] != freeze_id
                      and any(x["agent_id"] == aid and x["prior_status"] == "active" for x in f["agents"])), None)
        if other and cur["status"] == "suspended":
            a["outcome"] = "held_elsewhere"  # another stop that is still on holds it; lifting that one brings it back
            a["held_by"] = other["freeze_id"]
            kept.append(a["name"])
            continue
        if cur["status"] == "active":
            a["outcome"] = "restored"  # someone reinstated it by hand in the meantime
            restored.append(a["name"])
            continue
        if cur["status"] != "suspended":
            a["outcome"] = cur["status"]
            continue
        agent, v = await registry.reinstate(aid, client, by=f"{by} (lifting {STOP} {freeze_id})")
        if agent["status"] == "active":
            a["outcome"] = "restored"
            restored.append(a["name"])
        else:
            a["outcome"] = "still_suspended"
            a["still_reason"] = agent.get("reason")
            still.append(a["name"])
    back = {a["agent_id"] for a in rec["agents"] if a["outcome"] == "restored"}
    requeued, returned = [], []
    for sid in rec["schedules_off"]:
        s = next((x for x in store.schedules() if x["schedule_id"] == sid), None)
        if s and s["agent_id"] in back:
            store.update_schedule(sid, enabled=True, last_skip=None)
    if bring_back:
        for t in rec["stopped_tasks"]:
            if t["agent_id"] not in back:
                continue
            try:
                if rt is not None:
                    n = rt.assign(t["agent_id"], t["kind"], t["input"], by=f"{by} (brought back after {STOP} {freeze_id})",
                                  title=t["title"], ref=t.get("ref"))
                else:
                    n = store.add_task(registry.get_agent(t["agent_id"]), t["kind"], t["title"], t["input"],
                                       by=f"{by} (brought back after {STOP} {freeze_id})", ref=t.get("ref"))
                requeued.append(n["task_id"])
            except (ValueError, KeyError, registry.RegistryError):
                pass
        for p in rec["pulled_approvals"]:
            ap = store.get_approval(p["approval_id"])
            if p["agent_id"] in back and ap and ap["status"] == "expired" and (ap.get("decided_by") or "").startswith(f"{STOP} {freeze_id}"):
                store.update_approval(p["approval_id"], status="pending", decided_at=None, decided_by=None, note=None)
                _sync(ap, "pending_approval")
                returned.append(p["approval_id"])
    entry = ledger.append("freeze.restored", {
        "freeze_id": freeze_id, "by": by, "agent_ids": [a["agent_id"] for a in rec["agents"]],
        "restored": restored, "still_suspended": still, "kept_suspended": kept, "bring_back": bring_back,
        "requeued_tasks": requeued, "returned_approvals": returned})
    rec.update(status="lifted", restored_at=store.now(), restored_by=by, restore_entry=entry, bring_back=bring_back,
               requeued_tasks=requeued, returned_approvals=returned,
               restored=restored, still_suspended=still, kept_suspended=kept)
    out = _put(rec)
    if rt is not None:
        rt.wake()
    return out
