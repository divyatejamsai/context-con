"""FastAPI app. Run from backend/:  uvicorn app.main:app --reload --port 8000

POST /api/run            {"brief": "..."}  -> text/event-stream of events (CONTEXT.md section 6)
GET  /api/run?brief=...                     -> same, for browser EventSource (GET only)
GET  /api/replay?delay=0.6                  -> streams fixtures/run.jsonl (demo safety net)
GET  /api/health
GET/POST /api/agents/{agent_id}/run          -> same stream, run as a Agaxes AI employee (app/sourced_agent.py)
POST /api/verify_resume                     -> check a resume's claims against Crustdata
POST /api/auth/{lookup,signup,login,demo,logout}, GET /api/auth/me -> company accounts (app/accounts/)
/api/workspace, /api/workspace/members      -> roles (viewer/member/admin/owner) that gate every Agaxes route (authz.py)
GET  /api/demo/beats, /api/demo/run         -> the guided fleet demo as an event stream (app/fleet/demo.py)
/api/runtime/*                              -> the agent runtime: tasks, approvals, budgets, schedules (app/runtime/)
/api/runtime/freeze/*                       -> emergency stop: freeze an agent, a sponsor's agents or all, then restore
/api/campaigns/*                            -> brief to signed offer, ~100 conversations over weeks (app/talent/api.py)
/api/staffing/*                             -> staff 1000 shifts from applications seeded with fakes (app/talent/api.py)
POST /api/agents/{agent_id}/email            -> find the email on Crustdata, Send Guard, send for real (app/outbound/)
GET  /api/messages, POST /api/messages/refresh -> sent emails with delivery status and replies
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env")

from . import llm  # noqa: E402  (after dotenv so LLM_MODE is set)
from .orchestrator import run  # noqa: E402
from .schemas import RunRequest  # noqa: E402
from .agents.api import router as agents_router  # noqa: E402  (Agaxes, docs/COUNTERSIGN.md)
from .sourced_agent import router as sourced_router  # noqa: E402  (Sourced run under a passport + Send Guard)
from .fleet.api import router as demo_router  # noqa: E402  (guided fleet demo, app/fleet/demo.py)
from .crustdata import OUT_OF_CREDITS, OutOfCredits, provider_status  # noqa: E402
from .runtime import api as runtime_api  # noqa: E402  (agent runtime, docs/RUNTIME.md)
from .runtime.freeze_api import router as freeze_router  # noqa: E402  (emergency stop: app/runtime/freeze.py)
from .outbound.api import router as outbound_router  # noqa: E402  (find emails, send through Send Guard, track replies)
from .accounts.api import router as auth_router  # noqa: E402  (company sign-up, login and sessions)
from .accounts.members_api import platform as platform_router  # noqa: E402  (operator: every company)
from .accounts.members_api import router as members_router  # noqa: E402  (workspace roles: app/accounts/authz.py)
from .talent.api import router as talent_router  # noqa: E402  (brief -> signed offer, shift staffing: app/talent)
from .rules.api import router as rules_router  # noqa: E402  (company rules set without code: app/rules, docs/RULES.md)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="Brief-to-Shortlist hiring agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(agents_router)
app.include_router(sourced_router)
app.include_router(demo_router)
app.include_router(freeze_router)
app.include_router(runtime_api.router)
app.include_router(outbound_router)
app.include_router(auth_router)
app.include_router(members_router)
app.include_router(platform_router)
app.include_router(talent_router)
app.include_router(rules_router)


@app.exception_handler(OutOfCredits)
async def _out_of_credits(_request, exc: OutOfCredits):
    """Anywhere a Crustdata 402 escapes a route, the console gets one clear message instead of a 500."""
    return JSONResponse({"detail": OUT_OF_CREDITS, "code": "out_of_credits"}, status_code=402)


@app.on_event("startup")
async def start_runtime():
    """The agent runtime runs inside the API server (RUNTIME_ENABLED=0 turns it off)."""
    if os.getenv("RUNTIME_ENABLED", "1") == "0":
        return
    from .agents.api import crustdata
    from .runtime.supervisor import Runtime
    runtime_api.RUNTIME = Runtime(crustdata())
    await runtime_api.RUNTIME.start()


@app.on_event("shutdown")
async def stop_runtime():
    if runtime_api.RUNTIME is not None:
        await runtime_api.RUNTIME.stop()
        runtime_api.RUNTIME = None

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def _sse(payload: str) -> str:
    return f"data: {payload}\n\n"


async def _stream(brief: str):
    async for ev in run(brief):
        yield _sse(ev.model_dump_json())


class VerifyBody(BaseModel):
    seal_id: str | None = None
    text: str | None = None


@app.get("/api/verify/{seal_id}")
async def verify_seal(seal_id: str):
    """Public, no login: is the message behind this seal genuine, from an agent in good standing, within its scope?"""
    from .agents import seal
    from .agents.api import crustdata
    return await seal.verify(seal_id, None, crustdata())


@app.post("/api/verify")
async def verify_text(body: VerifyBody):
    """Public, no login: paste the message you received (with its footer), or send seal_id + text, for a verdict.
    Receiving agents call this before trusting another company's agent."""
    from .agents import seal
    from .agents.api import crustdata
    return await seal.verify(body.seal_id, body.text, crustdata())


@app.get("/api/health")
async def health():
    from .accounts.authz import mode as auth_mode
    return {"ok": True, "llm_mode": llm.mode(), "crustdata_mode": os.getenv("CRUSTDATA_MODE", "live"),
            "crustdata_key": bool(os.getenv("CRUSTDATA_API_KEY")), "auth_mode": auth_mode(),
            "crustdata": provider_status()}


@app.post("/api/run")
async def run_post(req: RunRequest):
    return StreamingResponse(_stream(req.brief), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/api/run")
async def run_get(brief: str = Query(..., min_length=1)):
    return StreamingResponse(_stream(brief), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/api/replay")
async def replay(delay: float = 0.6, file: str = "run.jsonl"):
    path = (ROOT / "fixtures" / Path(file).name)

    async def gen():
        for line in path.read_text().splitlines():
            if line.strip():
                yield _sse(json.dumps(json.loads(line)))
                await asyncio.sleep(delay)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)
