"""/api/runtime: the employer's control plane over running AI employees (the console's Work view).

    GET  /api/runtime/state                       everything the Work view shows (agents live, tasks, approvals, ...)
    GET  /api/runtime/kinds                       the jobs agents can be given, with their input fields
    GET  /api/runtime/tasks/{id}                  one task with every step and its full output
    POST /api/runtime/tasks                       {agent_id, kind, input, by?, ref?} assign work
    POST /api/runtime/tasks/{id}/cancel|retry     {by?}
    POST /api/runtime/approvals/{id}/approve      {by?}  re-runs Send Guard, then writes the outbox
    POST /api/runtime/approvals/{id}/reject       {by?, note?}
    POST /api/runtime/agents/{id}/pause|resume    {by?, reason?}  pause interrupts the running task
    POST /api/runtime/agents/{id}/suspend         {by?, reason}   registry suspension + immediate stop
    PUT  /api/runtime/agents/{id}/policy          {require_approval?, budget?: {tasks_per_day, sends_per_day, ...}}
    POST /api/runtime/schedules                   {agent_id, kind, input, every_minutes}
    POST /api/runtime/schedules/{id}/toggle, DELETE /api/runtime/schedules/{id}
    PUT  /api/runtime/payroll                     {enabled?, every_minutes?};  POST /api/runtime/payroll/run

Who may call what (app/accounts/authz.py), once auth is on: reads need viewer; assigning, cancelling, retrying,
approving, rejecting, pausing and resuming need member; suspend, policy, schedules and payroll need admin. A signed-in
user only sees and touches their own workspace's agents, tasks and approvals.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..agents import ledger
from ..accounts import authz
from ..agents.api import require_admin, require_operate, require_read
from ..agents.registry import RegistryError
from . import receipts, store
from .kinds import public_kinds
from .supervisor import Runtime, state

router = APIRouter(prefix="/api/runtime", tags=["runtime"])
admin = [Depends(require_admin)]
operate = [Depends(require_operate)]


def _scoped_state(st: dict) -> dict:
    """Drops other workspaces' agents, tasks and approvals from the Work view for a signed-in user."""
    ids = authz.visible_agent_ids()
    if ids is None:
        return st
    out = {}
    for k, v in st.items():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "agent_id" in v[0]:
            v = [x for x in v if x.get("agent_id") in ids]
        out[k] = v
    return out


def _own_task(task_id: str) -> None:
    t = store.get_task(task_id)
    if t:
        authz.check_agent(t["agent_id"])


def _own_approval(approval_id: str) -> None:
    a = next((x for x in store.approvals() if x.get("approval_id") == approval_id), None)
    if a:
        authz.check_agent(a["agent_id"])
RUNTIME: Runtime | None = None


def rt() -> Runtime:
    if RUNTIME is None:
        raise HTTPException(503, "the agent runtime is not running (RUNTIME_ENABLED=0?)")
    return RUNTIME


class By(BaseModel):
    by: str = "employer"
    reason: str | None = None
    note: str | None = None
    body: str | None = None  # approve: the draft as the person edited it


class AssignRequest(BaseModel):
    agent_id: str
    kind: str
    input: dict = Field(default_factory=dict)
    by: str = "employer"
    ref: dict | None = None


class PolicyRequest(BaseModel):
    by: str = "employer"
    require_approval: bool | None = None
    budget: dict[str, int] | None = None


class ScheduleRequest(BaseModel):
    agent_id: str
    kind: str
    input: dict = Field(default_factory=dict)
    every_minutes: float = 60
    by: str = "employer"


class PayrollRequest(BaseModel):
    enabled: bool | None = None
    every_minutes: float | None = None


def _bad(e: Exception) -> HTTPException:
    if isinstance(e, KeyError):
        return HTTPException(404, f"not found: {e}")
    return HTTPException(400, str(e))


@router.get("/state", dependencies=[Depends(require_read)])
async def get_state():
    return _scoped_state(state(RUNTIME))


@router.get("/kinds")
async def kinds():
    return public_kinds()


@router.get("/tasks/{task_id}", dependencies=[Depends(require_read)])
async def get_task(task_id: str):
    _own_task(task_id)
    t = store.get_task(task_id)
    if not t:
        raise HTTPException(404, "no such task")
    t["approvals"] = [a for a in store.approvals() if a["task_id"] == task_id]
    return t


@router.post("/tasks", dependencies=operate)
async def assign(req: AssignRequest):
    authz.check_agent(req.agent_id)
    try:
        return rt().assign(req.agent_id, req.kind, req.input, by=req.by, ref=req.ref)
    except (ValueError, KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/tasks/{task_id}/cancel", dependencies=operate)
async def cancel(task_id: str, req: By | None = None):
    _own_task(task_id)
    try:
        return rt().cancel(task_id, (req or By()).by)
    except (ValueError, KeyError) as e:
        raise _bad(e)


@router.post("/tasks/{task_id}/retry", dependencies=operate)
async def retry(task_id: str, req: By | None = None):
    _own_task(task_id)
    try:
        return rt().retry(task_id, (req or By()).by)
    except (ValueError, KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/approvals/{approval_id}/approve", dependencies=operate)
async def approve(approval_id: str, req: By | None = None):
    _own_approval(approval_id)
    try:
        req = req or By()
        return await rt().approve(approval_id, req.by, req.body)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/approvals/{approval_id}/reject", dependencies=operate)
async def reject(approval_id: str, req: By | None = None):
    _own_approval(approval_id)
    req = req or By()
    try:
        return rt().reject(approval_id, req.by, req.note or req.reason)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/agents/{agent_id}/pause", dependencies=operate)
async def pause(agent_id: str, req: By | None = None):
    authz.check_agent(agent_id)
    req = req or By()
    try:
        return rt().pause(agent_id, req.by, req.reason)
    except (KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/agents/{agent_id}/resume", dependencies=operate)
async def resume(agent_id: str, req: By | None = None):
    authz.check_agent(agent_id)
    try:
        return rt().resume(agent_id, (req or By()).by)
    except (KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/agents/{agent_id}/suspend", dependencies=admin)
async def suspend(agent_id: str, req: By):
    authz.check_agent(agent_id)
    try:
        return rt().suspend(agent_id, req.by, req.reason or "suspended by the employer")
    except (KeyError, RegistryError) as e:
        raise _bad(e)


@router.put("/agents/{agent_id}/policy", dependencies=admin)
async def policy(agent_id: str, req: PolicyRequest):
    authz.check_agent(agent_id)
    try:
        return rt().set_policy(agent_id, req.by, require_approval=req.require_approval, budget=req.budget)
    except (KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/schedules", dependencies=admin)
async def add_schedule(req: ScheduleRequest):
    authz.check_agent(req.agent_id)
    try:
        return rt().add_schedule(req.agent_id, req.kind, req.input, req.every_minutes, req.by)
    except (ValueError, KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/schedules/{schedule_id}/toggle", dependencies=admin)
async def toggle_schedule(schedule_id: str):
    s = next((x for x in store.schedules() if x["schedule_id"] == schedule_id), None)
    if not s:
        raise HTTPException(404, "no such schedule")
    authz.check_agent(s["agent_id"])
    out = store.update_schedule(schedule_id, enabled=not s["enabled"],
                                next_run_at=store.now() if not s["enabled"] else s["next_run_at"])
    ledger.append("runtime.schedule", {"agent_id": s["agent_id"], "schedule_id": schedule_id,
                                       "action": "enabled" if out["enabled"] else "disabled"})
    rt().wake()
    return out


@router.delete("/schedules/{schedule_id}", dependencies=admin)
async def delete_schedule(schedule_id: str):
    s = next((x for x in store.schedules() if x["schedule_id"] == schedule_id), None)
    if s:
        authz.check_agent(s["agent_id"])
    if not s or not store.delete_schedule(schedule_id):
        raise HTTPException(404, "no such schedule")
    ledger.append("runtime.schedule", {"agent_id": s["agent_id"], "schedule_id": schedule_id, "action": "deleted"})
    return {"deleted": schedule_id}


@router.put("/payroll", dependencies=admin)
async def payroll(req: PayrollRequest):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if "every_minutes" in fields:
        if fields["every_minutes"] < 1:
            raise HTTPException(400, "every_minutes must be at least 1")
        fields["next_run_at"] = (datetime.now(timezone.utc) + timedelta(minutes=fields["every_minutes"])).isoformat(timespec="seconds")
    out = store.set_payroll(**fields)
    rt().wake()
    return out


@router.post("/payroll/run", dependencies=admin)
async def payroll_run():
    return await rt().run_payroll("employer")


@router.get("/receipts/{entry_hash}")
async def receipt(entry_hash: str):
    if len(entry_hash) < 8:
        raise HTTPException(400, "give at least 8 characters of the entry hash")
    try:
        return receipts.issue(entry_hash)
    except KeyError:
        raise HTTPException(404, "no ledger entry with that hash")


@router.post("/receipts/verify")
async def verify_receipt(r: dict):
    return receipts.verify_receipt(r.get("receipt") or r)


# ---- outside agents (signed with the agent's own key; see runtime/external.py) ------------------

class AgentCall(BaseModel):
    agent_id: str
    ts: int
    signature: str
    task_id: str | None = None
    text: str = ""
    done: int | None = None
    total: int | None = None
    ok: bool = True


class AgentSend(BaseModel):
    agent_id: str
    task_id: str
    to: dict
    body: str
    scope: str
    signature: str  # the agent's signature of the exact body (passport.sign_message), as for Send Guard


def _auth(action: str, c: AgentCall) -> dict:
    from .external import AgentAuthError, authenticate
    try:
        return authenticate(action, c.agent_id, c.task_id, c.ts, c.text, c.signature)
    except AgentAuthError as e:
        raise HTTPException(401, str(e))


@router.post("/agent/claim")
async def agent_claim(c: AgentCall):
    from .external import claim
    return claim(_auth("claim", c), c.task_id)


@router.post("/agent/progress")
async def agent_progress(c: AgentCall):
    from .external import progress
    if not c.task_id:
        raise HTTPException(400, "task_id is required")
    return progress(_auth("progress", c), c.task_id, c.text, c.done, c.total)


@router.post("/agent/complete")
async def agent_complete(c: AgentCall):
    from .external import complete
    if not c.task_id:
        raise HTTPException(400, "task_id is required")
    return complete(rt(), _auth("complete", c), c.task_id, c.text, c.ok)


@router.post("/agent/send")
async def agent_send(s: AgentSend):
    from .external import send
    from ..agents import registry
    try:
        rec = registry.get_agent(s.agent_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(401, f"unknown agent {s.agent_id}")
    # authentication here is the message signature itself: Send Guard's message_signature_valid check fails on a forgery
    return await send(rt(), rec, s.task_id, s.to, s.body, s.scope, s.signature)


# ---- hiring more AI employees from templates ---------------------------------------------------

@router.get("/templates")
async def templates():
    from ..agents import registry
    from .kinds import KINDS, TEMPLATES
    names = {a["name"] for a in registry.list_agents() if a["status"] != "offboarded"}
    return [{**t, "hired": t["name"] in names,
             "jobs": [KINDS[k]["label"] for k in KINDS if KINDS[k].get("agent_hint") == t["name"]]} for t in TEMPLATES]


class HireRequest(BaseModel):
    key: str
    by: str = "employer"


@router.post("/hire", dependencies=admin)
async def hire(req: HireRequest):
    from ..agents import registry
    from ..agents.api import crustdata
    from ..agents.models import Sponsor
    from .kinds import TEMPLATES
    t = next((x for x in TEMPLATES if x["key"] == req.key), None)
    if not t:
        raise HTTPException(404, "no such template")
    if any(a["name"] == t["name"] and a["status"] != "offboarded" for a in registry.list_agents()):
        raise HTTPException(409, f"{t['name']} is already on the payroll")
    peer = next((a for a in registry.list_agents() if a["name"] == t["sponsor_from"] and a["status"] == "active"), None)
    if peer:
        sponsor = Sponsor.model_validate(peer["passport"]["sponsor"])
    else:
        from ..fleet.roster import PANKAJ as sponsor
    try:
        rec = registry.onboard(t["name"], t["role"], sponsor, t["scopes"], job=t["job"], runtime="in-house")
        v = await registry.recheck(rec["agent_id"], crustdata())  # live sponsor check right away
    except RegistryError as e:
        raise HTTPException(400, str(e))
    rt().wake()
    return {"agent": registry.get_agent(rec["agent_id"]) | {"private_key": None}, "decision": v.decision,
            "failed": [c.model_dump() for c in v.checks if c.status != "pass"]}
