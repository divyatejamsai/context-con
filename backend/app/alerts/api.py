"""/api/alerts: the console bell, alert preferences, and the public one-click Approve / Reject links.

    GET  /api/alerts                     {items, unread} for the caller (only alerts about agents they can see)
    POST /api/alerts/read                {alert_ids?}  marks them (or everything) read for the caller
    GET  /api/alerts/prefs               the caller's preferences, plus whether email and Slack are set up
    PUT  /api/alerts/prefs               {email?, slack?, approval?, block?, stop?}
    POST /api/alerts/test                send the caller a test alert on every channel they have on
    GET  /api/alerts/action/{token}      public: what this link would approve or reject (never acts)
    POST /api/alerts/action/{token}      public: {note?} do it, as the person the link was made for, once
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..accounts import authz
from ..agents.api import require_operate, require_read
from . import core
from .links import LinkError

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
STATUS = {"invalid": 404, "gone": 404, "expired": 410, "used": 409, "decided": 409, "refused": 409, "no_access": 403,
          "login": 403}


class ReadBody(BaseModel):
    alert_ids: list[str] | None = None


class Prefs(BaseModel):
    email: bool | None = None
    slack: bool | None = None
    approval: bool | None = None
    block: bool | None = None
    stop: bool | None = None


class ActBody(BaseModel):
    note: str | None = None


def _key() -> str | None:
    p = authz.current()
    return (p.user or {}).get("id") if p is not None and p.user else None


def _channels() -> dict:
    return {"email": core.email_status(), "slack": {"ready": bool(core.slack_url()),
                                                    "why": None if core.slack_url() else "Add SLACK_WEBHOOK_URL to backend/.env"}}


@router.get("", dependencies=[Depends(require_read)])
async def list_alerts(limit: int = 40):
    return core.feed(authz.current(), max(1, min(limit, 100)))


@router.post("/read", dependencies=[Depends(require_read)])
async def read(body: ReadBody | None = None):
    return {"marked": core.mark_read(authz.current(), (body or ReadBody()).alert_ids)}


@router.get("/prefs", dependencies=[Depends(require_read)])
async def get_prefs():
    return {"prefs": core.prefs(_key()), "labels": core.PREF_LABELS, "channels": _channels()}


@router.put("/prefs", dependencies=[Depends(require_read)])
async def put_prefs(body: Prefs):
    return {"prefs": core.set_prefs(_key(), body.model_dump()), "labels": core.PREF_LABELS, "channels": _channels()}


@router.post("/test", dependencies=[Depends(require_operate)])
async def test_alert():
    p = authz.current()
    me = [{"id": p.user["id"], "email": p.user["email"], "name": p.user["full_name"], "role": p.role}] if p and p.user else []
    a = core.raise_alert("test", "Test alert: this is how Agaxes reaches you",
                         "When an agent needs your approval, or something is blocked or stopped, it looks like this.",
                         recipients=me)
    await core.drain()
    return core.get(a["alert_id"]) if a else None


@router.get("/action/{token}")
async def preview(token: str):
    try:
        return core.preview(token)
    except LinkError as e:
        raise HTTPException(STATUS.get(e.code, 400), {"code": e.code, "message": e.message})


@router.post("/action/{token}")
async def act(token: str, body: ActBody | None = None):
    try:
        return await core.act(token, (body or ActBody()).note)
    except LinkError as e:
        raise HTTPException(STATUS.get(e.code, 400), {"code": e.code, "message": e.message})
