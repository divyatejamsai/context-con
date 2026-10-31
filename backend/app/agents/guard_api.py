"""Send Guard HTTP routes (WS7). Included by api.py under /api.

POST /api/guard/check  {passport, signature, to, body, scope} -> Verdict
POST /api/guard/send   same body -> {verdict, sent}; on allow the message goes to the outbox file, never to email
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from .graph import Graph
from .guard import check_send, send_if_allowed
from .models import Passport, Scope, Verdict

router = APIRouter(tags=["guard"])


class GuardRequest(BaseModel):
    passport: Passport
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


@router.post("/guard/check", response_model=Verdict)
async def guard_check(req: GuardRequest):
    return await check_send(req.passport, req.signature, req.to, req.body, req.scope, today=req.today, graph=_graph())


@router.post("/guard/send", response_model=SendResponse)
async def guard_send(req: GuardRequest):
    v, sent = await send_if_allowed(req.passport, req.signature, req.to, req.body, req.scope, today=req.today, graph=_graph())
    return SendResponse(verdict=v, sent=sent)
