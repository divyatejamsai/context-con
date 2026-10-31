"""Send Guard HTTP routes (WS7). Included by api.py under /api.

POST /api/guard/check  {agent_id | passport, signature, to, body, scope} -> Verdict
POST /api/guard/send   same body -> {verdict, sent}; on allow the message goes to the outbox file, never to email
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .graph import Graph
from .guard import UnknownAgent, check_send, resolve_agent, send_if_allowed
from .models import Passport, Scope, Verdict

router = APIRouter(tags=["guard"])


class GuardRequest(BaseModel):
    agent_id: str | None = None      # onboarded agents: the passport is loaded from the registry
    passport: Passport | None = None  # agents not onboarded here
    signature: str
    to: dict  # {name, profile_url, company}
    body: str
    scope: Scope
    today: date | None = None  # demo/test override


class SendResponse(BaseModel):
    verdict: Verdict
    sent: bool


def _graph() -> Graph:
    from .api import crustdata  # lazy: api.py imports this module

    return Graph(crustdata())


def _agent(req: GuardRequest) -> tuple[Passport, str | None]:
    try:
        if req.agent_id:
            p, status = resolve_agent(req.agent_id)
            if req.passport and req.passport.agent_id != p.agent_id:
                raise UnknownAgent("passport and agent_id name different agents")
            return p, status
    except UnknownAgent as e:
        raise HTTPException(404, str(e)) from e
    if req.passport is None:
        raise HTTPException(422, "send agent_id (or passport for agents not onboarded here)")
    return req.passport, None


@router.post("/guard/check", response_model=Verdict)
async def guard_check(req: GuardRequest):
    p, status = _agent(req)
    return await check_send(p, req.signature, req.to, req.body, req.scope, today=req.today, graph=_graph(), agent_status=status)


@router.post("/guard/send", response_model=SendResponse)
async def guard_send(req: GuardRequest):
    p, status = _agent(req)
    v, sent = await send_if_allowed(p, req.signature, req.to, req.body, req.scope, today=req.today, graph=_graph(),
                                    agent_status=status)
    return SendResponse(verdict=v, sent=sent)
