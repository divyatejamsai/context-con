"""HTTP routes for the conversation engine and shift staffing. Mounted in main.py.

Conversation engine (brief -> signed offer)
    POST /api/campaigns                        {brief, agent_id="sourced", size=100, mode="sim"|"live", seed, start}
                                               sources and ranks real candidates, opens every conversation (outreach
                                               through Send Guard) -> campaign summary
    GET  /api/campaigns                        summaries, newest last
    GET  /api/campaigns/{id}                   summary + one row per conversation (stage, last message, timer)
    GET  /api/campaigns/{id}/conversations/{cid}   full transcript with the guard verdict on each outbound message
    POST /api/campaigns/{id}/advance           {days} sim: moves the clock, timers fire and candidates reply;
                                               live: catches up to the real clock (call it on a schedule)
    GET  /api/campaigns/{id}/stream?days=28    text/event-stream: the same, one day at a time, with every event and a
                                               daily {"type":"day"} funnel snapshot; stops early once filled
    POST /api/campaigns/{id}/conversations/{cid}/reply     {text}  a real candidate's reply (live mode)
    POST /api/campaigns/{id}/conversations/{cid}/feedback  {passed, notes}  the interview panel's verdict

Shift staffing
    GET  /api/staffing/run?shifts=1000&fake_rate=0.15&seed=7&source=fixture|live   text/event-stream; ends with the report
    POST /api/staffing/run                     same, JSON {report, roster (first 200), flagged}
    GET  /api/staffing/last                    the last report

Mutating routes need COUNTERSIGN_ADMIN_TOKEN when it is set (x-admin-token header, or ?token= for EventSource).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agents.api import crustdata
from ..agents.registry import RegistryError
from . import campaign as C
from .conversations import TERMINAL
from .pool import PoolGraph, load_pool, save_pool
from .staffing import make_shifts, run_staffing, seed_applications

router = APIRouter(prefix="/api", tags=["talent"])
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
_locks: dict[str, asyncio.Lock] = {}
_staffing_lock = asyncio.Lock()
_last_staffing: dict | None = None


def _admin(token: str | None) -> None:
    want = os.getenv("COUNTERSIGN_ADMIN_TOKEN")
    if want and not (token and hmac.compare_digest(token, want)):
        raise HTTPException(401, "admin token required (x-admin-token or ?token=)")


def _lock(cid: str) -> asyncio.Lock:
    return _locks.setdefault(cid, asyncio.Lock())


def _load(cid: str) -> dict:
    try:
        return C.load(cid)
    except KeyError:
        raise HTTPException(404, f"no campaign {cid}")


def _row(c: dict) -> dict:
    last = c["messages"][-1] if c["messages"] else None
    return {"id": c["id"], "name": c["name"], "title": c.get("title"), "company": c.get("company"), "score": c.get("score"),
            "profile_url": c["profile_url"], "stage": c["stage"], "open": c["stage"] not in TERMINAL,
            "messages": len(c["messages"]), "timer": c.get("timer"),
            "last": {"dir": last["dir"], "at": last["at"], "kind": last.get("kind"), "body": last["body"][:160]} if last else None}


def _view(camp: dict) -> dict:
    eng = C.engine_for(camp, sender=_never)
    return {**eng.summary(), "brief": camp["brief"], "agent_id": camp.get("agent_id"),
            "conversations_list": [_row(c) for c in camp["conversations"].values()]}


async def _never(*_a, **_k) -> dict:  # read-only views never send
    return {"decision": "block", "checks": []}


class CampaignRequest(BaseModel):
    brief: str = Field(..., min_length=3)
    agent_id: str = "sourced"
    size: int = Field(100, ge=1, le=300)
    mode: Literal["sim", "live"] = "sim"
    seed: int = 7
    start: datetime | None = None


@router.post("/campaigns")
async def create_campaign(req: CampaignRequest, x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    try:
        camp, _ = await C.create(req.brief, req.agent_id, crustdata(), size=req.size, mode=req.mode, seed=req.seed, start=req.start)
    except (RegistryError, KeyError) as e:
        raise HTTPException(404, f"unknown agent {req.agent_id}: onboard it first ({e})")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    if not camp["conversations"]:
        raise HTTPException(422, "no candidates found for this brief")
    return _view(camp)


@router.get("/campaigns")
async def list_campaigns():
    out = []
    for cid in C.list_ids():
        camp = C.load(cid)
        out.append({k: v for k, v in C.engine_for(camp, sender=_never).summary().items() if k != "job"} | {"brief": camp["brief"]})
    return out


@router.get("/campaigns/{cid}")
async def get_campaign(cid: str):
    return _view(_load(cid))


@router.get("/campaigns/{cid}/conversations/{conv_id}")
async def get_conversation(cid: str, conv_id: str):
    camp = _load(cid)
    conv = camp["conversations"].get(conv_id)
    if not conv:
        raise HTTPException(404, f"no conversation {conv_id}")
    return conv


class AdvanceRequest(BaseModel):
    days: float = Field(1, gt=0, le=120)


@router.post("/campaigns/{cid}/advance")
async def advance(cid: str, req: AdvanceRequest, x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    if _load(cid).get("mode") == "live":
        try:  # pull new email replies first (they land in their conversations via the reply handler)
            from ..outbound import tracking
            C.register_replies()
            await tracking.refresh()
        except ImportError:
            pass
    async with _lock(cid):
        camp = _load(cid)
        events: list[dict] = []

        async def keep(ev: dict) -> None:
            events.append(ev)
        eng = C.engine_for(camp, crustdata(), keep)
        # sim: move the simulated clock; live: catch up to the real clock (fires due follow-ups, nudges, expiries)
        await eng.advance(eng.now + timedelta(days=req.days) if camp.get("mode") == "sim" else max(eng.now, datetime.now()))
        C.save(camp)
        return {"summary": eng.summary(), "events": events[-500:]}


@router.get("/campaigns/{cid}/stream")
async def stream(cid: str, days: int = Query(28, ge=1, le=120), token: str | None = None,
                 x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token or token)
    camp0 = _load(cid)
    if camp0.get("mode") != "sim":
        raise HTTPException(409, "only sim campaigns can be streamed forward")

    async def sse():
        async with _lock(cid):
            camp = _load(cid)
            q: asyncio.Queue = asyncio.Queue()

            async def put(ev: dict) -> None:
                await q.put(ev)
            eng = C.engine_for(camp, crustdata(), put)
            for _ in range(days):
                await eng.advance(eng.now + timedelta(days=1))
                while not q.empty():
                    yield f"data: {json.dumps(q.get_nowait(), default=str)}\n\n"
                s = eng.summary()
                yield f"data: {json.dumps({'type': 'day', 'day': s['day'], 'clock': s['clock'], 'stages': s['stages'], 'funnel': s['funnel'], 'status': s['status'], 'stats': s['stats']})}\n\n"
                C.save(camp)
                if s["status"] == "filled":
                    break
                await asyncio.sleep(0)
            yield f"data: {json.dumps({'type': 'done', 'summary': eng.summary()}, default=str)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream", headers=SSE_HEADERS)


class ReplyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


@router.post("/campaigns/{cid}/conversations/{conv_id}/reply")
async def reply(cid: str, conv_id: str, req: ReplyRequest, x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    async with _lock(cid):
        camp = _load(cid)
        if conv_id not in camp["conversations"]:
            raise HTTPException(404, f"no conversation {conv_id}")
        eng = C.engine_for(camp, crustdata())
        if camp.get("mode") == "live":
            eng.now = max(eng.now, datetime.now())
        read = await eng.receive(conv_id, req.text)
        C.save(camp)
        return {"read_as": read, "conversation": _row(camp["conversations"][conv_id])}


class FeedbackRequest(BaseModel):
    passed: bool
    notes: str = ""


@router.post("/campaigns/{cid}/conversations/{conv_id}/feedback")
async def feedback(cid: str, conv_id: str, req: FeedbackRequest, x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    async with _lock(cid):
        camp = _load(cid)
        conv = camp["conversations"].get(conv_id)
        if not conv:
            raise HTTPException(404, f"no conversation {conv_id}")
        if conv["stage"] != "interview":
            raise HTTPException(409, f"{conv['name']} is at {conv['stage']}, not interview")
        eng = C.engine_for(camp, crustdata())
        await eng.feedback(conv_id, req.passed, req.notes)
        C.save(camp)
        return _row(conv)


# ---- shift staffing ----------------------------------------------------------------------------

async def _staffing_pool(source: str) -> list[dict]:
    if source == "live":
        from .staffing import fetch_shift_pool
        client = crustdata()
        if client is None or getattr(client, "mode", "replay") == "replay":
            raise HTTPException(409, "live source needs CRUSTDATA_API_KEY and CRUSTDATA_MODE=cache or live")
        pool = await fetch_shift_pool(client)
        if pool:
            save_pool("staffing", pool, {"source": "crustdata person/search", "fetched": datetime.now().isoformat()})
        return pool
    pool, _ = load_pool("staffing")
    if not pool:
        raise HTTPException(409, "no recorded applicant pool yet: run with source=live (or scripts/run_talent.py --live)")
    return pool


async def _staffing(shifts: int, fake_rate: float, seed: int, source: str, today: date | None, emit) -> dict:
    global _last_staffing
    pool = await _staffing_pool(source)
    today = today or date.today()
    apps, key = seed_applications(pool, fake_rate=fake_rate, seed=seed, today=today)
    sh = make_shifts(shifts, start=today + timedelta(days=1), seed=seed)
    out = await run_staffing(apps, sh, PoolGraph(pool, crustdata()), today=today, answer_key=key, emit=emit)
    out["report"]["pool"] = {"records": len(pool), "source": source}
    _last_staffing = out
    return out


@router.get("/staffing/run")
async def staffing_stream(shifts: int = Query(1000, ge=1, le=10000), fake_rate: float = Query(0.15, ge=0, le=0.9),
                          seed: int = 7, source: Literal["fixture", "live"] = "fixture",
                          today: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), token: str | None = None,
                          x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token or token)
    if _staffing_lock.locked():
        raise HTTPException(409, "a staffing run is already in progress")

    async def sse():
        async with _staffing_lock:
            q: asyncio.Queue = asyncio.Queue()

            async def put(ev: dict) -> None:
                await q.put(ev)
            task = asyncio.create_task(_staffing(shifts, fake_rate, seed, source, date.fromisoformat(today) if today else None, put))
            while not task.done() or not q.empty():
                try:
                    ev = await asyncio.wait_for(q.get(), 0.5)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except asyncio.TimeoutError:
                    continue
            try:
                task.result()
            except HTTPException as e:
                yield f"data: {json.dumps({'type': 'error', 'message': e.detail})}\n\n"
            except Exception as e:  # noqa: BLE001 - the page shows it instead of hanging
                yield f"data: {json.dumps({'type': 'error', 'message': f'{type(e).__name__}: {e}'})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream", headers=SSE_HEADERS)


class StaffingRequest(BaseModel):
    shifts: int = Field(1000, ge=1, le=10000)
    fake_rate: float = Field(0.15, ge=0, le=0.9)
    seed: int = 7
    source: Literal["fixture", "live"] = "fixture"
    today: date | None = None


@router.post("/staffing/run")
async def staffing_json(req: StaffingRequest, x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    async with _staffing_lock:
        out = await _staffing(req.shifts, req.fake_rate, req.seed, req.source, req.today, C_noop)
    return {"report": out["report"], "roster": out["roster"][:200],
            "flagged": [s for s in out["screenings"] if s["outcome"] == "flagged"]}


async def C_noop(_: dict) -> None:
    return None


@router.get("/staffing/last")
async def staffing_last():
    if not _last_staffing:
        raise HTTPException(404, "no staffing run yet")
    return {"report": _last_staffing["report"], "roster": _last_staffing["roster"][:200]}
