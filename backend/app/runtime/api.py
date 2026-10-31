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

Writes need COUNTERSIGN_ADMIN_TOKEN (x-admin-token) when it is set, like the rest of Countersign's admin routes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..agents import ledger
from ..agents.api import require_admin
from ..agents.registry import RegistryError
from . import receipts, store
from .kinds import public_kinds
from .supervisor import Runtime, state

router = APIRouter(prefix="/api/runtime", tags=["runtime"])
admin = [Depends(require_admin)]
RUNTIME: Runtime | None = None


def rt() -> Runtime:
    if RUNTIME is None:
        raise HTTPException(503, "the agent runtime is not running (RUNTIME_ENABLED=0?)")
    return RUNTIME


class By(BaseModel):
    by: str = "employer"
    reason: str | None = None
    note: str | None = None


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


@router.get("/state")
async def get_state():
    return state(RUNTIME)


@router.get("/kinds")
async def kinds():
    return public_kinds()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    t = store.get_task(task_id)
    if not t:
        raise HTTPException(404, "no such task")
    t["approvals"] = [a for a in store.approvals() if a["task_id"] == task_id]
    return t


@router.post("/tasks", dependencies=admin)
async def assign(req: AssignRequest):
    try:
        return rt().assign(req.agent_id, req.kind, req.input, by=req.by, ref=req.ref)
    except (ValueError, KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/tasks/{task_id}/cancel", dependencies=admin)
async def cancel(task_id: str, req: By | None = None):
    try:
        return rt().cancel(task_id, (req or By()).by)
    except (ValueError, KeyError) as e:
        raise _bad(e)


@router.post("/tasks/{task_id}/retry", dependencies=admin)
async def retry(task_id: str, req: By | None = None):
    try:
        return rt().retry(task_id, (req or By()).by)
    except (ValueError, KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/approvals/{approval_id}/approve", dependencies=admin)
async def approve(approval_id: str, req: By | None = None):
    try:
        return await rt().approve(approval_id, (req or By()).by)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/approvals/{approval_id}/reject", dependencies=admin)
async def reject(approval_id: str, req: By | None = None):
    req = req or By()
    try:
        return rt().reject(approval_id, req.by, req.note or req.reason)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/agents/{agent_id}/pause", dependencies=admin)
async def pause(agent_id: str, req: By | None = None):
    req = req or By()
    try:
        return rt().pause(agent_id, req.by, req.reason)
    except (KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/agents/{agent_id}/resume", dependencies=admin)
async def resume(agent_id: str, req: By | None = None):
    try:
        return rt().resume(agent_id, (req or By()).by)
    except (KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/agents/{agent_id}/suspend", dependencies=admin)
async def suspend(agent_id: str, req: By):
    try:
        return rt().suspend(agent_id, req.by, req.reason or "suspended by the employer")
    except (KeyError, RegistryError) as e:
        raise _bad(e)


@router.put("/agents/{agent_id}/policy", dependencies=admin)
async def policy(agent_id: str, req: PolicyRequest):
    try:
        return rt().set_policy(agent_id, req.by, require_approval=req.require_approval, budget=req.budget)
    except (KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/schedules", dependencies=admin)
async def add_schedule(req: ScheduleRequest):
    try:
        return rt().add_schedule(req.agent_id, req.kind, req.input, req.every_minutes, req.by)
    except (ValueError, KeyError, RegistryError) as e:
        raise _bad(e)


@router.post("/schedules/{schedule_id}/toggle", dependencies=admin)
async def toggle_schedule(schedule_id: str):
    s = next((x for x in store.schedules() if x["schedule_id"] == schedule_id), None)
    if not s:
        raise HTTPException(404, "no such schedule")
    out = store.update_schedule(schedule_id, enabled=not s["enabled"],
                                next_run_at=store.now() if not s["enabled"] else s["next_run_at"])
    ledger.append("runtime.schedule", {"agent_id": s["agent_id"], "schedule_id": schedule_id,
                                       "action": "enabled" if out["enabled"] else "disabled"})
    rt().wake()
    return out


@router.delete("/schedules/{schedule_id}", dependencies=admin)
async def delete_schedule(schedule_id: str):
    s = next((x for x in store.schedules() if x["schedule_id"] == schedule_id), None)
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
