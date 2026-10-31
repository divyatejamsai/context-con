"""Hiring flows: one brief, four AI employees handing real work to each other, every handoff gated by a passport.

    shortlist  (data.read)        Sourced searches, verifies and ranks candidates
    verify     (data.read)        another agent re-checks every shortlisted record and gives each a verdict
                                  (separation of duties: the agent that built the shortlist can't verify it)
    schedule   (outreach.hiring)  Scheduler proposes real interview slots (.ics with times) and drafts invites
    offer      (contract.sign)    the offer letter is drafted, and signed only after the employer approves it

At each handoff Agaxes routes the next stage: it asks the agent that holds the work first, then the others, and runs
a live passport check (verify_agent with the stage's scope) on each until one is allowed. Every check, allowed or
denied, is shown on the flow and written to the ledger. So the Scheduler, which holds the candidates after
scheduling, is asked to make the offer first and is refused: its passport has no contract.sign.

The supervisor advances flows on every tick, so a flow survives a restart. A stage that fails, is refused or is
cancelled stops the flow with the reason.
"""
from __future__ import annotations

import copy
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from ..agents import ledger, registry
from . import store

log = logging.getLogger(__name__)

STAGES = [
    {"key": "shortlist", "kind": "sourcing", "scope": "data.read", "label": "Shortlist", "prefer": ["Sourced"]},
    {"key": "verify", "kind": "candidate_verification", "scope": "data.read", "label": "Verify records",
     "prefer": ["Diligence", "Reference"], "independent": True},
    {"key": "schedule", "kind": "interview_scheduling", "scope": "outreach.hiring", "label": "Schedule interviews",
     "prefer": ["Scheduler", "Sourced"]},
    {"key": "offer", "kind": "offer_letter", "scope": "contract.sign", "label": "Offer letter", "prefer": ["Offer"]},
]
NEEDS = ["Scheduler", "Offer"]  # hired from templates if the workspace doesn't have them yet
IST = timezone(timedelta(hours=5, minutes=30))


# ---- storage (inside runtime.json) ----------------------------------------------------------------

def _all() -> dict:
    return store._load().setdefault("flows", {})


def get(flow_id: str) -> dict | None:
    with store._lock:
        f = _all().get(flow_id)
        return copy.deepcopy(f) if f else None


def flows() -> list[dict]:
    with store._lock:
        return copy.deepcopy(sorted(_all().values(), key=lambda f: f["created_at"]))


def _mutate(flow_id: str, fn) -> dict:
    with store._lock:
        f = _all()[flow_id]
        fn(f)
        store._save()
        return copy.deepcopy(f)


def default_slots(n: int = 6, start: datetime | None = None) -> list[str]:
    """The next working days at 11:00 and 15:00 IST, written so the Scheduler's .ics gets real times."""
    d = (start or datetime.now(IST)).date() + timedelta(days=1)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            for h in (11, 15):
                out.append(f"{d.strftime('%a')} {d.day} {d.strftime('%b %Y')}, {h}:00 IST")
        d += timedelta(days=1)
    return out[:n]


# ---- start -----------------------------------------------------------------------------------------

async def start(rt, inp: dict, by: str, workspace_id: str | None = None) -> dict:
    brief = (inp.get("brief") or "").strip()
    if not brief:
        raise ValueError("a hiring brief is required")
    from .kinds import hire_template
    hired = []
    for name in NEEDS:
        if not any(a["name"] == name and a["status"] != "offboarded" for a in registry.list_agents()):
            key = name.lower()
            rec, _v = await hire_template(key, rt.client, workspace_id)
            hired.append(rec["name"])
    f = {"flow_id": store.new_id("flw"), "status": "running", "created_at": store.now(), "by": by,
         "input": {"brief": brief, "role": (inp.get("role") or brief.splitlines()[0].split(",")[0])[:80].strip(),
                   "compensation": (inp.get("compensation") or "").strip(),
                   "start_date": (inp.get("start_date") or "").strip(),
                   "interviewer": (inp.get("interviewer") or "").strip(),
                   "slots": inp.get("slots") or "\n".join(default_slots())},
         "stage": 0, "stages": [{"key": s["key"], "label": s["label"], "scope": s["scope"], "status": "waiting",
                                 "task_id": None, "agent": None, "checks": []} for s in STAGES],
         "hired": hired, "error": None, "finished_at": None}
    with store._lock:
        _all()[f["flow_id"]] = f
        store._save()
    ledger.append("flow.started", {"flow_id": f["flow_id"], "brief": brief, "by": by, "hired": hired})
    await _route(rt, f["flow_id"], 0, holder=None)
    rt.wake()
    return get(f["flow_id"])


# ---- routing: who may do the next stage? ----------------------------------------------------------

async def _route(rt, flow_id: str, i: int, holder: dict | None) -> None:
    from .kinds import can_do
    spec, f = STAGES[i], get(flow_id)
    agents = [a for a in registry.list_agents() if a["status"] != "offboarded"]
    order = ([holder] if holder else []) + [a for n in spec["prefer"] for a in agents if a["name"] == n]
    order += [a for a in agents if a not in order and can_do(a, spec["kind"]) is None]
    seen, checks, chosen = set(), [], None
    for a in order:
        if a["agent_id"] in seen:
            continue
        seen.add(a["agent_id"])
        if spec.get("independent") and holder and a["agent_id"] == holder["agent_id"]:
            checks.append({"agent": a["name"], "scope": spec["scope"], "decision": "deny",
                           "why": f"{a['name']} built this work, so it can't check it (separation of duties)"})
            continue
        why = can_do(a, spec["kind"])
        v = await rt.mcp.tool("verify_agent", {"agent_id": a["agent_id"], "scope": spec["scope"]})
        failed = [f"{c['name']}: {c['detail']}" for c in v.get("checks", []) if c.get("status") != "pass"]
        ok = v.get("decision") == "allow" and why is None
        checks.append({"agent": a["name"], "scope": spec["scope"], "decision": "allow" if ok else "deny",
                       "why": ("passport valid for " + spec["scope"]) if ok else (failed[0] if failed else why),
                       "ledger_entry": v.get("ledger_entry")})
        if ok:
            chosen = a
            break
    if chosen is None:
        def stop(x):
            x["stages"][i].update(status="blocked", checks=checks)
            x.update(status="stopped", error=f"No agent's passport allows {spec['label'].lower()} ({spec['scope']})",
                     finished_at=store.now())
        _mutate(flow_id, stop)
        ledger.append("flow.stopped", {"flow_id": flow_id, "stage": spec["key"], "checks": checks})
        return
    inp = _input_for(i, f)
    t = rt.assign(chosen["agent_id"], spec["kind"], inp, by=f"Agaxes hiring flow ({f['by']})",
                  ref={"flow_id": flow_id, "stage": spec["key"]})
    for c in checks:
        store.task_step(t["task_id"], f"Passport check: {c['agent']} for {c['scope']}: {c['decision'].upper()} "
                                      f"({c['why']})", "control")
    _mutate(flow_id, lambda x: (x["stages"][i].update(status="running", task_id=t["task_id"], agent=chosen["name"],
                                                     checks=checks), x.update(stage=i)))
    ledger.append("flow.handoff", {"flow_id": flow_id, "stage": spec["key"], "to": chosen["agent_id"],
                                   "task_id": t["task_id"], "checks": [{k: v for k, v in c.items() if k != "ledger_entry"}
                                                                       for c in checks]})


def _prev_output(f: dict, key: str) -> dict:
    st = next(s for s in f["stages"] if s["key"] == key)
    t = store.get_task(st["task_id"]) if st.get("task_id") else None
    return (t or {}).get("output") or {}


def _line(c: dict) -> str:
    return f"{c['name']} | {c['profile_url']} | {c.get('company') or ''}"


def _input_for(i: int, f: dict) -> dict:
    fi, key = f["input"], STAGES[i]["key"]
    if key == "shortlist":
        return {"brief": fi["brief"]}
    if key == "verify":
        short = [c for c in _prev_output(f, "shortlist").get("shortlist", []) if c.get("profile_url")][:5]
        return {"candidates": "\n".join(_line(c) for c in short), "from_task": f["stages"][0]["task_id"]}
    if key == "schedule":
        cleared = [v for v in _prev_output(f, "verify").get("verdicts", []) if v["verdict"] == "clear"][:3]
        return {"candidates": "\n".join(_line(v) for v in cleared), "slots": fi["slots"], "role": fi["role"],
                "interviewer": fi["interviewer"], "minutes": "45"}
    # offer: the top cleared candidate who got an invite
    plan = _prev_output(f, "schedule").get("schedule", [])
    verdicts = {v["name"]: v for v in _prev_output(f, "verify").get("verdicts", [])}
    pick = next((p for p in plan if p["invite"] != "blocked"), None) or (plan[0] if plan else None)
    v = verdicts.get(pick["candidate"]) if pick else None
    return {"candidate": _line(v) if v else "", "role": fi["role"], "compensation": fi["compensation"],
            "start_date": fi["start_date"], "slot": (pick or {}).get("slots", [""])[0]}


# ---- advancing (called by the supervisor every tick) ----------------------------------------------

async def tick(rt) -> None:
    for f in flows():
        if f["status"] != "running":
            continue
        i = f["stage"]
        st = f["stages"][i]
        t = store.get_task(st["task_id"]) if st.get("task_id") else None
        if not t or t["status"] in ("queued", "running"):
            continue
        if t["status"] != "done" or (STAGES[i]["key"] != "offer" and not _has_work(i, t)):
            why = t.get("error") or t.get("result") or t["status"]
            if t["status"] == "done":
                why = {"shortlist": "no one was shortlisted", "verify": "no candidate cleared verification",
                       "schedule": "no interview could be scheduled"}[STAGES[i]["key"]]
            _mutate(f["flow_id"], lambda x: (x["stages"][i].update(status=t["status"] if t["status"] != "done" else "empty"),
                                             x.update(status="stopped", error=f"{st['label']}: {why}", finished_at=store.now())))
            ledger.append("flow.stopped", {"flow_id": f["flow_id"], "stage": st["key"], "why": why})
            continue
        _mutate(f["flow_id"], lambda x: x["stages"][i].update(status="done"))
        if i + 1 < len(STAGES):
            holder = next((a for a in registry.list_agents() if a["agent_id"] == t["agent_id"]), None)
            await _route(rt, f["flow_id"], i + 1, holder)
        else:
            _mutate(f["flow_id"], lambda x: x.update(status="done", finished_at=store.now()))
            ledger.append("flow.finished", {"flow_id": f["flow_id"], "packet_sha256": hashlib.sha256(
                packet(get(f["flow_id"])).encode()).hexdigest()})


def _has_work(i: int, t: dict) -> bool:
    out = t.get("output") or {}
    key = STAGES[i]["key"]
    if key == "shortlist":
        return any(c.get("profile_url") for c in out.get("shortlist", []))
    if key == "verify":
        return any(v["verdict"] == "clear" for v in out.get("verdicts", []))
    if key == "schedule":
        return bool(out.get("schedule"))
    return True


# ---- the hiring-committee packet ------------------------------------------------------------------

def packet(f: dict) -> str:
    fi = f["input"]
    out = {s["key"]: ((store.get_task(s["task_id"]) or {}).get("output") or {}) if s.get("task_id") else {} for s in f["stages"]}
    L = [f"# Hiring-committee packet: {fi['role']}", "", f"Flow {f['flow_id']}, started {f['created_at']} by {f['by']}.",
         f"Status: {f['status']}" + (f" ({f['error']})" if f.get("error") else ""), "", "## Brief", "", fi["brief"], ""]
    L += ["## Who did what, and the passport check at each handoff", ""]
    for s in f["stages"]:
        L.append(f"- **{s['label']}** ({s['scope']}): {s.get('agent') or 'nobody'}, {s['status']}")
        for c in s.get("checks", []):
            L.append(f"  - {c['agent']}: {c['decision'].upper()} ({c['why']})")
    L += ["", "## Shortlist", ""]
    for c in out["shortlist"].get("shortlist", []):
        L.append(f"- {c.get('name')}, {c.get('title') or ''} at {c.get('company') or ''} (score {c.get('score')})")
    L += ["", "## Record verification", ""]
    for v in out["verify"].get("verdicts", []):
        L.append(f"- **{v['name']}: {v['verdict'].upper()}** ({v['why']})")
    L += ["", "## Interviews", ""]
    for p in out["schedule"].get("schedule", []):
        L.append(f"- {p['candidate']}: {' or '.join(p['slots'])} with {p['interviewer']}, invite {p['invite']}")
    L += ["", "## Offer", ""]
    o = out["offer"].get("offer")
    if o:
        L.append(f"- {o['candidate']}, {o['role']}: {o['state']}" + (f" by {o.get('signed_by')} at {o.get('signed_at')}"
                                                                      if o.get("state") == "signed" else ""))
        L.append(f"- Document sha256 {o['sha256']}")
    else:
        L.append("- Not drafted yet")
    return "\n".join(L) + "\n"


def public(f: dict) -> dict:
    return {**f, "packet": packet(f)}
