"""HTTP routes for the guided demo (app/fleet/demo.py). Mounted in main.py.

    GET /api/demo/beats                                   the seven beats (id, title, narration) for the page outline
    GET /api/demo/run?claude_code=false&today=YYYY-MM-DD  text/event-stream of the story's events (see demo.py)

One run at a time (409 while one is going): the beats share the registry, the ledger and one MCP server.
A run onboards agents and writes to the ledger, so when COUNTERSIGN_ADMIN_TOKEN is set it needs that token
(x-admin-token header, or ?token= for a browser EventSource, which can't send headers).
Uses the same store as the rest of the API, so the console's roster, reviews and ledger fill in as it plays.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
from datetime import date

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..agents.api import crustdata
from .demo import BEATS, DemoOptions, story

router = APIRouter(prefix="/api/demo", tags=["demo"])
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
_running = asyncio.Lock()


@router.get("/beats")
async def beats():
    return [{"n": i + 1, "id": b, "title": t, "narration": d} for i, (b, t, d) in enumerate(BEATS)]


@router.get("/run")
async def run(claude_code: bool = False, today: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
              only: str | None = None, token: str | None = None, x_admin_token: str | None = Header(default=None)):
    want = os.getenv("COUNTERSIGN_ADMIN_TOKEN")
    got = x_admin_token or token
    if want and not (got and hmac.compare_digest(got, want)):
        raise HTTPException(401, "admin token required (x-admin-token or ?token=)")
    if _running.locked():
        raise HTTPException(409, "a demo run is already in progress")
    ids = [b[0] for b in BEATS]
    pick = ["onboard", *[x for x in only.split(",") if x in ids]] if only else ids
    opts = DemoOptions(client=crustdata(), today=date.fromisoformat(today) if today else None,
                       claude_code=claude_code, only=pick)

    async def sse():
        async with _running:
            try:
                async for ev in story(opts):
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
            except Exception as e:  # noqa: BLE001 - the page shows it instead of hanging
                yield f"data: {json.dumps({'type': 'error', 'message': f'{type(e).__name__}: {e}'})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream", headers=SSE_HEADERS)
