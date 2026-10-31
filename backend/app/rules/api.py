"""/api/rules: company rules written in the console without code (app/rules/engine.py, docs/RULES.md).

    GET    /api/rules                    this company's rules, the templates, recent enforcement, can_edit
    GET    /api/rules/templates          the rule types the builder offers, with their fields and an example
    POST   /api/rules/preview            {type, params, agents} -> the plain sentence (or the error), nothing saved
    POST   /api/rules                    {type, params, agents?, name?, enabled?}           admin or owner
    PUT    /api/rules/{id}               {params?, agents?, name?, enabled?, note?}         admin or owner
    DELETE /api/rules/{id}               {note?}  stops applying; history stays             admin or owner
    GET    /api/rules/{id}               one rule with its version history and the times it was enforced

Reads need viewer. Every write is versioned and on the ledger, with the signed-in admin as the actor.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..accounts import authz
from ..accounts.authz import require_admin, require_read
from ..agents import ledger
from ..agents.registry import RegistryError
from . import engine

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleIn(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)
    agents: list[str] = Field(default_factory=list)
    name: str | None = None
    enabled: bool = True
    by: str = "employer"


class RulePatch(BaseModel):
    params: dict | None = None
    agents: list[str] | None = None
    name: str | None = None
    enabled: bool | None = None
    note: str | None = None
    by: str = "employer"


class Note(BaseModel):
    note: str | None = None
    by: str = "employer"


def _ws() -> str | None:
    """The workspace a rule written now belongs to: the admin's company. Open mode / operator: every company."""
    p = authz.current()
    return p.workspace_id if p and p.scoped else None


def _who(by: str) -> str:
    p = authz.current()
    return p.label(by) if p else by


def _visible(r: dict) -> bool:
    p = authz.current()
    return not (p and p.scoped) or r.get("workspace_id") in (None, p.workspace_id)


def _editable(r: dict) -> bool:
    """A company admin can't edit a platform-wide rule (workspace None) set by the operator."""
    p = authz.current()
    return not (p and p.scoped) or r.get("workspace_id") == p.workspace_id


def _check_agents(ids: list[str]) -> None:
    for a in ids:
        authz.check_agent(a)


def _recent(rule_id: str | None = None, limit: int = 30) -> list[dict]:
    ids = authz.visible_agent_ids()
    p = authz.current()
    ws = p.workspace_id if p and p.scoped else None
    rows = [r for r in ledger.entries(kind="rule.enforced") if authz.entry_visible(r, ids, ws)]
    if rule_id:
        rows = [r for r in rows if (r.get("payload") or {}).get("rule_id") == rule_id]
    return [{"ts": r["ts"], "hash": r["hash"], "seq": r["seq"], **(r.get("payload") or {})} for r in rows[-limit:]][::-1]


def _bad(e: Exception) -> HTTPException:
    if isinstance(e, KeyError):
        return HTTPException(404, "no such rule")
    return HTTPException(400, str(e))


@router.get("", dependencies=[Depends(require_read)])
async def list_rules():
    p = authz.current()
    rows = [engine.public(r) | {"editable": _editable(r)} for r in engine.rules() if _visible(r)]
    counts: dict[str, int] = {}
    for e in _recent(limit=10_000):
        counts[e["rule_id"]] = counts.get(e["rule_id"], 0) + 1
    for r in rows:
        r["enforced_count"] = counts.get(r["rule_id"], 0)
        r.pop("history", None)
    return {"rules": rows, "templates": engine.templates(), "recent": _recent(limit=30),
            "can_edit": bool(p is None or p.can("admin"))}


@router.get("/templates")
async def templates():
    return engine.templates()


@router.post("/preview", dependencies=[Depends(require_read)])
async def preview(req: RuleIn):
    try:
        params = engine.normalize(req.type, req.params)
        return {"ok": True, "sentence": engine.sentence(req.type, params, req.agents), "params": params}
    except (engine.RuleError, ValueError, TypeError) as e:
        return {"ok": False, "error": str(e)}


@router.post("", dependencies=[Depends(require_admin)])
async def create(req: RuleIn):
    _check_agents(req.agents)
    try:
        r = engine.create(req.type, req.params, agents=req.agents, name=req.name, enabled=req.enabled,
                          by=_who(req.by), workspace_id=_ws())
    except (engine.RuleError, RegistryError, ValueError, TypeError) as e:
        raise _bad(e)
    return engine.public(r) | {"editable": True}


def _own(rule_id: str) -> dict:
    r = engine.get(rule_id)
    if not r or r.get("deleted") or not _visible(r):
        raise HTTPException(404, "no such rule")
    if not _editable(r):
        raise HTTPException(403, "this rule is set for every company by the platform operator")
    return r


@router.get("/{rule_id}", dependencies=[Depends(require_read)])
async def get_rule(rule_id: str):
    r = engine.get(rule_id)
    if not r or not _visible(r):
        raise HTTPException(404, "no such rule")
    return engine.public(r) | {"editable": _editable(r), "recent": _recent(rule_id)}


@router.put("/{rule_id}", dependencies=[Depends(require_admin)])
async def update(rule_id: str, req: RulePatch):
    _own(rule_id)
    if req.agents is not None:
        _check_agents(req.agents)
    try:
        r = engine.update(rule_id, by=_who(req.by), params=req.params, agents=req.agents, name=req.name,
                          enabled=req.enabled, note=req.note)
    except (engine.RuleError, RegistryError, KeyError, ValueError, TypeError) as e:
        raise _bad(e)
    return engine.public(r) | {"editable": True}


@router.delete("/{rule_id}", dependencies=[Depends(require_admin)])
async def delete(rule_id: str, req: Note | None = None):
    _own(rule_id)
    req = req or Note()
    try:
        return engine.public(engine.delete(rule_id, by=_who(req.by), note=req.note))
    except KeyError as e:
        raise _bad(e)
