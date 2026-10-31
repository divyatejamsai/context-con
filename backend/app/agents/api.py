"""Agaxes HTTP routes (docs/COUNTERSIGN.md). Mounted in main.py with app.include_router(router).

WS6 owns /api/passport/* and /api/ledger. WS7 adds /api/guard/*, WS8 adds /api/agents* (in their own modules,
included below when present so this file never blocks them).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from . import ledger
from .graph import Graph
from .models import Passport, Scope, Sponsor, Verdict
from .passport import issue_passport, issuer_key_id, issuer_public_key, reinstate, revoke, verify_passport

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["countersign"])
SCENARIOS = Path(__file__).resolve().parents[3] / "fixtures" / "countersign" / "sponsors.json"

_client = None


def crustdata():
    """Shared client, created lazily. None if the Crustdata package or key is missing (checks become unverifiable)."""
    global _client
    if _client is None:
        try:
            from ..crustdata.client import CrustdataClient
            _client = CrustdataClient(mode=os.getenv("CRUSTDATA_MODE", "cache"))
        except Exception as e:  # noqa: BLE001
            log.warning("Agaxes running without Crustdata client: %s", e)
    return _client


class IssueRequest(BaseModel):
    agent_name: str
    role: str
    sponsor: Sponsor
    scopes: list[Scope]
    days: int = 30


class IssueResponse(BaseModel):
    passport: Passport
    agent_private_key: str  # base64; shown once


class VerifyRequest(BaseModel):
    passport: Passport
    scope: Scope | None = None


class RevokeRequest(BaseModel):
    agent_id: str
    reason: str


# Issuing and revoking passports needs an admin (workspace admin/owner session, or COUNTERSIGN_ADMIN_TOKEN) once
# auth is on; see app/accounts/authz.py. Verify stays public: anyone may check an agent.
from ..accounts.authz import require_admin, require_operate, require_read  # noqa: E402,F401  (re-exported)
from ..accounts import authz  # noqa: E402


@router.get("/passport/issuer")
async def issuer():
    return {"key_id": issuer_key_id(), "public_key": issuer_public_key(), "alg": "Ed25519"}


@router.post("/passport/issue", response_model=IssueResponse, dependencies=[Depends(require_admin)])
async def issue(req: IssueRequest):
    import base64
    p, key = issue_passport(req.agent_name, req.role, req.sponsor, req.scopes, req.days)
    return IssueResponse(passport=p, agent_private_key=base64.b64encode(key).decode())


@router.post("/passport/verify", response_model=Verdict)
async def verify(req: VerifyRequest):
    return await verify_passport(req.passport, scope=req.scope, graph=Graph(crustdata()))


@router.post("/passport/revoke", dependencies=[Depends(require_admin)])
async def revoke_route(req: RevokeRequest):
    return {"ledger_entry": revoke(req.agent_id, req.reason)}


@router.post("/passport/reinstate", dependencies=[Depends(require_admin)])
async def reinstate_route(req: RevokeRequest):
    return {"ledger_entry": reinstate(req.agent_id, req.reason)}


@router.get("/passport/scenarios")
async def scenarios():
    """Demo sponsors (fixtures/countersign/sponsors.json) for the console's quick-fill."""
    if not SCENARIOS.exists():
        raise HTTPException(404, "no scenarios fixture")
    return json.loads(SCENARIOS.read_text())


@router.get("/ledger")
async def ledger_view(agent_id: str | None = None, kind: str | None = None, p=Depends(require_read)):
    """A signed-in user sees only their workspace's entries; chain_ok is always for the whole file."""
    ok, bad = ledger.verify_chain()
    ids = authz.visible_agent_ids(p)
    rows = [r for r in ledger.entries(agent_id, kind) if authz.entry_visible(r, ids, p.workspace_id)]
    return {"chain_ok": ok, "first_bad_seq": bad, "entries": rows}


# Other workstreams' routers, included when their modules exist.
for _mod in ("guard_api", "enroll_api", "registry_api"):  # enroll_api first: /agents/enrollments is not an id
    try:
        _m = __import__(f"{__package__}.{_mod}", fromlist=["router"])
        router.include_router(_m.router)
    except ImportError:
        pass
