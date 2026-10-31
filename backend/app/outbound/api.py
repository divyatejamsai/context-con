"""Outbound HTTP routes (mounted in main.py).

GET  /api/outbound/config                      provider, test/live mode, whether sending and replies are set up (no secrets)
GET  /api/contacts?profile_url=...             the candidate's email from Crustdata (Person Enrich, fields ["contact"])
POST /api/agents/{agent_id}/email              {to:{name,profile_url,company}, subject, body, email?, scope?, thread_key?}
                                               -> Send Guard, then a real email; returns SendResult
GET  /api/messages?agent_id=&profile_url=      sent / blocked / failed messages with status history and replies
POST /api/messages/refresh                     poll delivery status and replies now
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..accounts import authz
from ..accounts.authz import require_operate, require_read
from pydantic import BaseModel

from . import mailer, messages, tracking
from .contacts import find_email
from .send import SendResult, guarded_send

router = APIRouter(prefix="/api", tags=["outbound"])


class SendRequest(BaseModel):
    to: dict[str, Any]
    subject: str = ""
    body: str
    email: dict | None = None     # a ContactInfo the UI already got from /api/contacts or the run
    scope: str = "outreach.hiring"
    thread_key: str | None = None


@router.get("/outbound/config")
async def outbound_config():
    return {**mailer.config(), "replies": bool(tracking.imap_settings())}


@router.get("/contacts", dependencies=[Depends(require_operate)])  # spends Crustdata credits
async def contacts(profile_url: str = Query(..., min_length=5)):
    from ..agents.api import crustdata

    return (await find_email(crustdata(), profile_url)).model_dump(mode="json")


@router.post("/agents/{agent_id}/email", response_model=SendResult, dependencies=[Depends(require_operate)])
async def send(agent_id: str, req: SendRequest):
    authz.check_agent(agent_id)  # a real email: never on behalf of another workspace's agent
    return await guarded_send(agent_id, req.to, req.subject, req.body, scope=req.scope, thread_key=req.thread_key,
                              email=req.email)


def _visible(rows: list[dict]) -> list[dict]:
    ids = authz.visible_agent_ids()
    return rows if ids is None else [r for r in rows if r.get("agent_id") in ids]


@router.get("/messages", dependencies=[Depends(require_read)])
async def list_messages(agent_id: str | None = None, profile_url: str | None = None, thread_key: str | None = None):
    return {"messages": [messages.public(r) for r in _visible(messages.list_all(agent_id, profile_url, thread_key))]}


@router.post("/messages/refresh", dependencies=[Depends(require_operate)])
async def refresh():
    res = await tracking.refresh()
    return {**res, "messages": _visible(messages.list_all())}

