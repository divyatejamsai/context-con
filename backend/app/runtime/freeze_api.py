"""/api/runtime/freeze: the emergency stop (app/runtime/freeze.py).

    GET  /api/runtime/freeze                      {active, history, sponsors}: stops in force, past stops, who vouches for what
    GET  /api/runtime/freeze/blast?agent_id=&hours=24   what these agents touched (agent_id repeats; none = every agent you see)
    POST /api/runtime/freeze/preview              {scope, target?}  who a stop would hit, with their last 24 hours
    POST /api/runtime/freeze                      {scope: agent|sponsor|all, target?, reason}  stop them now
    POST /api/runtime/freeze/{id}/restore         {bring_back?}  lift it: fresh sponsor check, then back to work

Freezing and restoring need admin (the same as suspend); reads need viewer. A signed-in admin only ever freezes their
own company's agents: "all" means every agent they can see.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..accounts import authz
from ..agents.api import require_admin, require_read
from ..agents.registry import RegistryError
from . import api as runtime_api
from . import freeze as fz

router = APIRouter(prefix="/api/runtime/freeze", tags=["runtime"])


class FreezeRequest(BaseModel):
    scope: fz.Scope = "agent"
    target: str | None = None
    reason: str = ""
    by: str = "employer"


class PreviewRequest(BaseModel):
    scope: fz.Scope = "agent"
    target: str | None = None
    hours: float = 24


class RestoreRequest(BaseModel):
    bring_back: bool = False
    by: str = "employer"


def _by(sent: str) -> str:
    p = authz.current()
    return p.label(sent) if p else sent


def _mine(f: dict, ids: set[str] | None) -> bool:
    return ids is None or any(a["agent_id"] in ids for a in f["agents"])


def _scoped(f: dict, ids: set[str] | None) -> dict:
    """A company sees only its own agents inside a stop (an operator's "all" can span companies)."""
    if ids is None:
        return f
    keep = lambda rows: [r for r in rows if r.get("agent_id") in ids]  # noqa: E731
    out = {**f, "agents": keep(f["agents"]), "stopped_tasks": keep(f["stopped_tasks"]),
           "pulled_approvals": keep(f["pulled_approvals"])}
    if f.get("blast"):
        out["blast"] = {**f["blast"], "agents": keep(f["blast"]["agents"])}
    return out


def _bad(e: Exception) -> HTTPException:
    if isinstance(e, KeyError):
        return HTTPException(404, f"not found: {e}")
    return HTTPException(400, str(e))


@router.get("", dependencies=[Depends(require_read)])
async def overview():
    ids = authz.visible_agent_ids()
    rows = [_scoped(f, ids) for f in fz.freezes() if _mine(f, ids)]
    return {"active": [f for f in rows if f["status"] == "active"],
            "history": [f for f in rows if f["status"] != "active"][:20],
            "sponsors": fz.sponsors(ids)}


@router.get("/blast", dependencies=[Depends(require_read)])
async def blast(agent_id: list[str] = Query(default=[]), hours: float = Query(24, gt=0, le=24 * 14)):
    ids = authz.visible_agent_ids()
    from ..agents import registry
    want = agent_id or [a["agent_id"] for a in registry.list_agents() if a["status"] != "offboarded"]
    if ids is not None:
        want = [a for a in want if a in ids]
    return fz.blast_radius(want, hours)


@router.post("/preview", dependencies=[Depends(require_read)])
async def preview(req: PreviewRequest):
    try:
        return fz.preview(req.scope, req.target, authz.visible_agent_ids(), req.hours)
    except (KeyError, ValueError) as e:
        raise _bad(e)


@router.post("", dependencies=[Depends(require_admin)])
async def freeze(req: FreezeRequest):
    try:
        return fz.freeze(runtime_api.RUNTIME, req.scope, req.target, req.reason, _by(req.by), authz.visible_agent_ids())
    except (KeyError, ValueError, RegistryError) as e:
        raise _bad(e)


@router.post("/{freeze_id}/restore", dependencies=[Depends(require_admin)])
async def restore(freeze_id: str, req: RestoreRequest | None = None):
    req = req or RestoreRequest()
    ids = authz.visible_agent_ids()
    f = fz.get(freeze_id)
    if not f or not _mine(f, ids):
        raise HTTPException(404, f"no emergency stop {freeze_id}")
    if ids is not None and any(a["agent_id"] not in ids for a in f["agents"]):
        raise HTTPException(403, "this stop covers other companies' agents too: the platform operator lifts it")
    from ..agents.registry_api import _client
    try:
        return await fz.restore(runtime_api.RUNTIME, freeze_id, _by(req.by), _client(), bring_back=req.bring_back)
    except (KeyError, ValueError, RegistryError) as e:
        raise _bad(e)
