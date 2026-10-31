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

Shift staffing (app/talent/staffing.py)
    GET  /api/staffing/templates               role templates (quick-commerce, BPO, retail seasonal, nursing, events, campus)
    POST /api/staffing/applications            {csv, name}: a CSV of applications -> {upload_id, row errors, roles, cities}
    GET  /api/staffing/sample.csv              a sample applications CSV from the recorded pool, to try the upload
    POST /api/staffing/run/stream              {roles | template, start, days, source=recorded|upload|live, upload_id,
                                               test_mode, fake_rate, duplicate_rate, no_show_rate, seed, bench_rate,
                                               rest_hours, live_lookups} -> text/event-stream; ends with the report
    POST /api/staffing/run                     same body, JSON {report, roster (first 200), flagged}
    GET  /api/staffing/run?shifts=1000&fake_rate=0.15&seed=7   the original demo: test mode, default roles, N shifts
    POST /api/staffing/pool/grow               {template | roles, per_role}: search Crustdata live for more applicants
                                               (credits) and add them to the recording -> text/event-stream
    POST /api/staffing/no-show                 {shift_id}: backfill a no-show from the bench in the last run
    GET  /api/staffing/last | roster | roster.csv | screenings     the last run

Mutating routes need COUNTERSIGN_ADMIN_TOKEN when it is set (x-admin-token header, or ?token= for EventSource).
"""
from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from ..agents.api import crustdata
from ..agents.registry import RegistryError
from . import campaign as C
from .conversations import TERMINAL
from .pool import PoolGraph, load_pool, pool_path, profile_url, save_pool
from .staffing import (ALL_CITIES, CSV_COLUMNS, DEFAULT_TEMPLATE, TEMPLATES, Role, build_shifts, fetch_shift_pool, make_shifts,
                       norm_url, parse_csv, run_staffing, seed_applications, template, to_csv)

router = APIRouter(prefix="/api", tags=["talent"])
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
_locks: dict[str, asyncio.Lock] = {}
_staffing_lock = asyncio.Lock()
_last_staffing: dict | None = None
_uploads: dict[str, dict] = {}
_grow_lock = asyncio.Lock()
log = logging.getLogger(__name__)


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

def _staffing_dir() -> Path:
    return Path(os.getenv("STAFFING_DIR") or Path(__file__).resolve().parents[2] / "data" / "staffing")


def _pool_names() -> list[str]:
    """The recorded pools: fixtures/staffing (quick-commerce) plus one fixtures/staffing-<template> per searched template."""
    root = pool_path("staffing").parents[1]
    return ["staffing", *sorted(p.parent.name for p in root.glob("staffing-*/pool.json"))]


def recorded_pool() -> list[dict]:
    """Every recorded applicant, once each (by profile URL)."""
    seen: dict[str, dict] = {}
    for name in _pool_names():
        for r in load_pool(name)[0]:
            u = norm_url(profile_url(r))
            if u and u not in seen:
                seen[u] = r
    return list(seen.values())


async def grow_pool(roles: list[Role], per_role: int, name: str, progress=None) -> dict:
    """Search Crustdata live for these roles (uses credits; pages already in the Crustdata cache are free) and add the
    new people to the recording `name`."""
    client = crustdata()
    if client is None or getattr(client, "mode", "replay") == "replay":
        raise HTTPException(409, "searching Crustdata needs CRUSTDATA_API_KEY and CRUSTDATA_MODE=cache or live on the backend")
    known = {norm_url(profile_url(r)) for r in recorded_pool()}
    fresh = await fetch_shift_pool(client, per_role=per_role, roles=roles, progress=progress)
    old, meta = load_pool(name)
    merged = {norm_url(profile_url(r)): r for r in old}
    for r in fresh:
        merged.setdefault(norm_url(profile_url(r)), r)
    new = [r for r in fresh if norm_url(profile_url(r)) not in known]
    if fresh:
        save_pool(name, list(merged.values()), {**meta, "source": "crustdata person/search", "fetched": datetime.now().isoformat(),
                                                "per_role": max(per_role, meta.get("per_role") or 0),
                                                "roles": sorted({*(meta.get("roles") or []), *(r.id for r in roles)})}, compact=True)
    return {"found": len(fresh), "new": len(new), "by_role": dict(Counter(r["_family"] for r in fresh)),
            "new_by_role": dict(Counter(r["_family"] for r in new)), "pool": name, "total": len(recorded_pool())}


async def _staffing_pool(source: str, roles: list[Role] | None = None) -> list[dict]:
    """The recorded Crustdata pool. source=live searches Crustdata first (costs credits) and adds to the recording."""
    if source == "live":
        await grow_pool(roles or template(DEFAULT_TEMPLATE), 250, "staffing")
    pool = recorded_pool()
    if not pool:
        raise HTTPException(409, "no recorded applicant pool yet: run with source=live (or scripts/run_talent.py --live)")
    return pool


class StaffingRun(BaseModel):
    """One staffing run. Without roles, the quick-commerce template; without an upload, the recorded pool."""
    roles: list[Role] | None = Field(None, max_length=40)
    template: str | None = None
    start: date | None = None                       # first day of shifts (default: tomorrow)
    days: int = Field(7, ge=1, le=28)
    shifts: int | None = Field(None, ge=1, le=10000)  # old order book: N random shifts from the roles instead
    source: Literal["recorded", "fixture", "upload", "live"] = "recorded"
    upload_id: str | None = None
    test_mode: bool = False                         # plant lies and repeats in the recorded pool, score against the key
    fake_rate: float = Field(0.15, ge=0, le=0.9)
    duplicate_rate: float = Field(0.03, ge=0, le=0.3)
    no_show_rate: float = Field(0.08, ge=0, le=0.5)
    seed: int = 7
    bench_rate: float = Field(0.1, ge=0, le=1)
    rest_hours: float = Field(10, ge=0, le=24)
    live_lookups: int = Field(0, ge=0, le=1000)     # uploads: profiles not in the recorded data to look up live (credits)
    today: date | None = None


def _upload(uid: str) -> dict:
    if uid in _uploads:
        return _uploads[uid]
    p = _staffing_dir() / "uploads" / f"{re.sub(r'[^a-z0-9]', '', uid)}.json"
    if not p.exists():
        raise HTTPException(404, f"no upload {uid}: upload the CSV again")
    _uploads[uid] = json.loads(p.read_text())
    return _uploads[uid]


async def _staffing(req: StaffingRun, emit) -> dict:
    global _last_staffing
    today = req.today or date.today()
    try:
        roles = req.roles or template(req.template or DEFAULT_TEMPLATE)
    except KeyError:
        raise HTTPException(404, f"no template {req.template}")
    ids = [r.id for r in roles]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "two roles have the same name; give each role its own title")
    start = req.start or today + timedelta(days=1)
    shifts = make_shifts(req.shifts, start=start, days=req.days, seed=req.seed, roles=roles) if req.shifts else build_shifts(roles, start=start, days=req.days)
    if not shifts:
        raise HTTPException(422, "these roles have no shifts: check headcount, days and dates")
    key = None
    if req.source == "upload":
        if not req.upload_id:
            raise HTTPException(422, "upload a CSV of applications first")
        up = _upload(req.upload_id)
        apps = copy.deepcopy(up["applications"])
        pool = recorded_pool()
        closed, n_live = False, req.live_lookups
        src = {"source": "upload", "file": up.get("name"), "rows": len(apps), "records": len(pool)}
    else:
        pool = await _staffing_pool("live" if req.source == "live" else "recorded", roles)
        test = req.test_mode
        apps, key = seed_applications(pool, roles=roles, fake_rate=req.fake_rate if test else 0.0, seed=req.seed, today=today,
                                      duplicate_rate=req.duplicate_rate if test else 0.0)
        key = key if test else None
        closed, n_live = True, 0
        src = {"source": "live" if req.source == "live" else "fixture", "records": len(pool)}
    if not apps:
        raise HTTPException(422, "no applications for these roles in the recorded pool: upload a CSV, or search Crustdata live")
    out = await run_staffing(apps, shifts, PoolGraph(pool), roles=roles, today=today, answer_key=key, emit=emit,
                             closed_world=closed, client=crustdata() if n_live else None, max_live_lookups=n_live,
                             bench_rate=req.bench_rate, rest_hours=req.rest_hours,
                             no_show_rate=req.no_show_rate if (req.test_mode and key is not None) else None, seed=req.seed)
    out["report"]["pool"] = src
    out["report"]["test_mode"] = key is not None
    out["report"]["horizon"] = {"start": start.isoformat(), "days": req.days}
    out["apps"] = {a["id"]: a for a in apps}
    _last_staffing = out
    return out


def _sse(req: StaffingRun):
    if _staffing_lock.locked():
        raise HTTPException(409, "a staffing run is already in progress")

    async def gen():
        async with _staffing_lock:
            q: asyncio.Queue = asyncio.Queue()

            async def put(ev: dict) -> None:
                await q.put(ev)
            task = asyncio.create_task(_staffing(req, put))
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

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/staffing/templates")
async def staffing_templates():
    counts = Counter(r.get("_family") for r in recorded_pool() if r.get("_family"))
    return {"templates": [{**{k: v for k, v in t.items() if k != "roles"}, "roles": [r.model_dump() for r in template(t["id"])]} for t in TEMPLATES],
            "default": DEFAULT_TEMPLATE, "cities": list(ALL_CITIES), "csv_columns": CSV_COLUMNS,
            "recorded_roles": sorted(counts), "pool_by_role": dict(counts), "pool_total": sum(counts.values())}


class GrowRequest(BaseModel):
    roles: list[Role] | None = Field(None, max_length=40)
    template: str | None = None
    per_role: int = Field(300, ge=10, le=2000)


@router.post("/staffing/pool/grow")
async def staffing_grow(req: GrowRequest, x_admin_token: str | None = Header(default=None)):
    """Search Crustdata live for more applicants for these roles (uses credits) and add them to the recorded pool.
    text/event-stream: one {"type":"role"} per role searched, then {"type":"done", ...counts}."""
    _admin(x_admin_token)
    try:
        roles = req.roles or template(req.template or DEFAULT_TEMPLATE)
    except KeyError:
        raise HTTPException(404, f"no template {req.template}")
    tid = req.template or "custom"
    name = "staffing" if tid == DEFAULT_TEMPLATE else f"staffing-{re.sub(r'[^a-z0-9-]', '', tid)}"
    if _grow_lock.locked():
        raise HTTPException(409, "a Crustdata search is already running")

    async def gen():
        async with _grow_lock:
            q: asyncio.Queue = asyncio.Queue()

            async def prog(role_id: str, n: int) -> None:
                await q.put({"type": "role", "role": role_id, "found": n})
            task = asyncio.create_task(grow_pool(roles, req.per_role, name, prog))
            while not task.done() or not q.empty():
                try:
                    yield f"data: {json.dumps(await asyncio.wait_for(q.get(), 0.5))}\n\n"
                except asyncio.TimeoutError:
                    continue
            try:
                yield f"data: {json.dumps({'type': 'done', **task.result()})}\n\n"
            except HTTPException as e:
                yield f"data: {json.dumps({'type': 'error', 'message': e.detail})}\n\n"
            except Exception as e:  # noqa: BLE001
                yield f"data: {json.dumps({'type': 'error', 'message': f'{type(e).__name__}: {e}'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/staffing/run/stream")
async def staffing_run_stream(req: StaffingRun, x_admin_token: str | None = Header(default=None)):
    """text/event-stream of the run (POST so the roles travel in the body); ends with the report."""
    _admin(x_admin_token)
    return _sse(req)


@router.get("/staffing/run")
async def staffing_stream(shifts: int = Query(1000, ge=1, le=10000), fake_rate: float = Query(0.15, ge=0, le=0.9),
                          seed: int = 7, source: Literal["fixture", "recorded", "live"] = "fixture",
                          today: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), token: str | None = None,
                          x_admin_token: str | None = Header(default=None)):
    """The original demo: N random shifts from the default roles, in test mode with `fake_rate` planted lies."""
    _admin(x_admin_token or token)
    return _sse(StaffingRun(shifts=shifts, fake_rate=fake_rate, seed=seed, source=source, test_mode=True,
                            duplicate_rate=0, no_show_rate=0.08, today=date.fromisoformat(today) if today else None))


@router.post("/staffing/run")
async def staffing_json(req: StaffingRun, x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    if req.source in ("recorded", "fixture") and req.roles is None and req.template is None and "test_mode" not in req.model_fields_set:
        req.test_mode = True  # the old JSON call meant the demo
        req.shifts = req.shifts or 1000
    async with _staffing_lock:
        out = await _staffing(req, C_noop)
    return {"report": out["report"], "roster": out["roster"][:200],
            "flagged": [s for s in out["screenings"] if s["outcome"] == "flagged"]}


class UploadRequest(BaseModel):
    csv: str = Field(..., min_length=1, max_length=8_000_000)
    name: str | None = None


@router.post("/staffing/applications")
async def staffing_upload(req: UploadRequest, x_admin_token: str | None = Header(default=None)):
    """A CSV of applications (sent as text). Returns an upload_id for /staffing/run with source=upload."""
    _admin(x_admin_token)
    apps, errors = parse_csv(req.csv)
    if not apps:
        raise HTTPException(422, errors[0]["error"] if errors else "the CSV has no applications")
    uid = hashlib.sha256(req.csv.encode()).hexdigest()[:12]
    known = {norm_url(profile_url(r)) for r in recorded_pool()}
    rec = {"id": uid, "name": req.name, "at": datetime.now().isoformat(timespec="seconds"), "applications": apps, "errors": errors}
    _uploads[uid] = rec
    try:
        d = _staffing_dir() / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{uid}.json").write_text(json.dumps(rec))
    except OSError as e:
        log.warning("staffing: upload not saved to disk: %s", e)
    return {"upload_id": uid, "name": req.name, "applications": len(apps), "errors": errors[:50], "error_count": len(errors),
            "roles": dict(Counter(a["role"] or "(none)" for a in apps).most_common()),
            "cities": dict(Counter(a["city"] or "(none)" for a in apps).most_common()),
            "in_recorded_data": sum(1 for a in apps if norm_url(a["profile_url"]) in known),
            "no_profile_url": sum(1 for a in apps if not a["profile_url"])}


@router.get("/staffing/sample.csv")
async def staffing_sample(n: int = Query(300, ge=1, le=5000), lies: float = Query(0.1, ge=0, le=0.9), seed: int = 11,
                          template_id: str = Query(DEFAULT_TEMPLATE, alias="template")):
    """A sample applications CSV built from the recorded pool (real people, a few planted lies), to try the upload."""
    pool = recorded_pool()
    if not pool:
        raise HTTPException(409, "no recorded applicant pool yet")
    try:
        roles = template(template_id)
    except KeyError:
        raise HTTPException(404, f"no template {template_id}")
    apps, _key = seed_applications(pool, roles=roles, fake_rate=lies, seed=seed, limit=n, duplicate_rate=0.02)
    return Response(to_csv(apps), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="applications-sample.csv"'})


class NoShowRequest(BaseModel):
    shift_id: str


@router.post("/staffing/no-show")
async def staffing_no_show(req: NoShowRequest, x_admin_token: str | None = Header(default=None)):
    """The worker booked on this shift didn't turn up: backfill from the bench (or anyone free) in the last run."""
    _admin(x_admin_token)
    if not _last_staffing:
        raise HTTPException(404, "no staffing run yet")
    rota = _last_staffing["rota"]
    if req.shift_id not in rota.shifts:
        raise HTTPException(404, f"no shift {req.shift_id}")
    if req.shift_id not in rota.filled:
        raise HTTPException(409, f"{req.shift_id} has nobody booked")
    out = rota.no_show(req.shift_id)
    _last_staffing["roster"] = rota.roster()
    row = next(r for r in _last_staffing["roster"] if r["id"] == req.shift_id)
    return {**out, "shift": row, "double_bookings": len(rota.double_bookings())}


@router.get("/staffing/last")
async def staffing_last():
    if not _last_staffing:
        raise HTTPException(404, "no staffing run yet")
    return {"report": _last_staffing["report"], "roster": _last_staffing["roster"][:200]}


@router.get("/staffing/roster")
async def staffing_roster(q: str = "", role: str = "", city: str = "", status: Literal["all", "filled", "open", "no_show"] = "all",
                          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    if not _last_staffing:
        raise HTTPException(404, "no staffing run yet")
    rows = _last_staffing["roster"]
    t = q.strip().lower()
    rows = [r for r in rows if (not role or r["role"] == role) and (not city or r["city"] == city)
            and (status == "all" or (status == "filled" and r["worker"]) or (status == "open" and not r["worker"]) or (status == "no_show" and r.get("no_show")))
            and (not t or t in (r.get("worker_name") or "").lower() or t in r["id"] or t in (r.get("worker") or ""))]
    return {"total": len(rows), "rows": rows[offset:offset + limit]}


@router.get("/staffing/roster.csv")
async def staffing_roster_csv():
    if not _last_staffing:
        raise HTTPException(404, "no staffing run yet")
    apps = _last_staffing.get("apps") or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["shift", "role", "city", "date", "start", "end", "worker_application", "worker_name", "phone", "email", "status", "standby"])
    for r in _last_staffing["roster"]:
        a = apps.get(r["worker"] or "", {})
        w.writerow([r["id"], r["role_label"], r["city"], r["date"], r.get("start", ""), r.get("end", ""), r["worker"] or "", r["worker_name"] or "",
                    a.get("phone", ""), a.get("email", ""), "filled" if r["worker"] else (r.get("open_reason") or "open"),
                    "; ".join(b["name"] or b["worker"] for b in r.get("bench") or [])])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="roster.csv"'})


@router.get("/staffing/screenings")
async def staffing_screenings(outcome: str = "", offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000)):
    if not _last_staffing:
        raise HTTPException(404, "no staffing run yet")
    rows = [s for s in _last_staffing["screenings"] if not outcome or s["outcome"] == outcome]
    return {"total": len(rows), "rows": rows[offset:offset + limit]}


async def C_noop(_: dict) -> None:
    return None
