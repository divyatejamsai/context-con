"""FastAPI app. Run from backend/:  uvicorn app.main:app --reload --port 8000

POST /api/run            {"brief": "..."}  -> text/event-stream of events (CONTEXT.md section 6)
GET  /api/run?brief=...                     -> same, for browser EventSource (GET only)
GET  /api/replay?delay=0.6                  -> streams fixtures/run.jsonl (demo safety net)
GET  /api/health
GET/POST /api/agents/{agent_id}/run          -> same stream, run as a Countersign AI employee (app/sourced_agent.py)
POST /api/verify_resume                     -> check a resume's claims against Crustdata
GET  /api/demo/beats, /api/demo/run         -> the guided fleet demo as an event stream (app/fleet/demo.py)
/api/runtime/*                              -> the agent runtime: tasks, approvals, budgets, schedules (app/runtime/)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env")

from . import llm  # noqa: E402  (after dotenv so LLM_MODE is set)
from .orchestrator import run  # noqa: E402
from .schemas import RunRequest  # noqa: E402
from .agents.api import router as agents_router  # noqa: E402  (Countersign, docs/COUNTERSIGN.md)
from .sourced_agent import router as sourced_router  # noqa: E402  (Sourced run under a passport + Send Guard)
from .fleet.api import router as demo_router  # noqa: E402  (guided fleet demo, app/fleet/demo.py)
from .runtime import api as runtime_api  # noqa: E402  (agent runtime, docs/RUNTIME.md)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="Brief-to-Shortlist hiring agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(agents_router)
app.include_router(sourced_router)
app.include_router(demo_router)
app.include_router(runtime_api.router)


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


@app.get("/api/health")
async def health():
    return {"ok": True, "llm_mode": llm.mode(), "crustdata_mode": os.getenv("CRUSTDATA_MODE", "live"),
            "crustdata_key": bool(os.getenv("CRUSTDATA_API_KEY"))}


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
