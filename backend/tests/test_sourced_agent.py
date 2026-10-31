"""Sourced run as a Agaxes AI employee (app/sourced_agent.py): passport gate, Send Guard on drafts, ledger.

Offline: real verify_passport on WS6's fixture sponsors, synthetic people from DevCrustdataClient, LLM_MODE=mock.
"""
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio
from fastapi.testclient import TestClient

from app.agents import ledger, registry
from app.agents.models import Sponsor
from app.fallbacks import DevCrustdataClient
from app.sourced_agent import run_as_agent

SCENARIOS = {s["id"]: s for s in json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
BRIEF = "senior backend engineer, payments, Bangalore"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTS_PATH", str(tmp_path / "agents.json"))
    monkeypatch.setenv("LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("ISSUER_KEY_PATH", str(tmp_path / "issuer.key"))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")


def onboard(scenario: str, scopes=None) -> str:
    return registry.onboard("Sourced", "recruiter", Sponsor(**SCENARIOS[scenario]["sponsor"]), scopes)["agent_id"]


async def collect(agent_id: str) -> list[dict]:
    return [e async for e in run_as_agent(BRIEF, agent_id, client=DevCrustdataClient())]


async def test_departed_sponsor_blocks_the_run_before_any_search():
    events = await collect(onboard("sponsor_left", ["outreach.hiring", "data.read"]))
    assert not any(e.get("step") == "search" for e in events)
    assert events[-1]["type"] == "error" and "passport" in events[-1]["message"]
    blocked = [e for e in events if e.get("step") == "passport" and e.get("data")][0]
    assert blocked["data"]["decision"] == "block"
    assert any(c["name"] == "sponsor_still_employed" and c["status"] == "fail" for c in blocked["data"]["checks"])
    assert "run.started" not in [e["kind"] for e in ledger.entries()]


async def test_unknown_or_suspended_agent_is_refused():
    events = [e async for e in run_as_agent(BRIEF, "agt_nope", client=DevCrustdataClient())]
    assert events == [events[0]] and events[0]["type"] == "error"
    aid = onboard("authorised_founder", ["outreach.hiring", "data.read"])
    registry.suspend(aid, "sponsor asked", by="sponsor")
    events = await collect(aid)
    assert len(events) == 1 and "suspended" in events[0]["message"]


async def test_valid_passport_runs_pipeline_guards_drafts_and_records_ledger():
    aid = onboard("authorised_founder", ["outreach.hiring", "data.read"])
    events = await collect(aid)
    steps = [e.get("step") for e in events if e["type"] == "step"]
    assert steps[0] == "passport" and "search" in steps and "guard" in steps
    guarded = [e["candidate"] for e in events if e["type"] == "candidate" and "guard" in e["candidate"]]
    assert guarded and all(c["guard"]["decision"] in ("allow", "block") for c in guarded)
    assert events[-1]["type"] == "done" and events[-1]["summary"]["ledger_entry"]
    kinds = [e["kind"] for e in ledger.entries()]
    assert kinds.index("run.started") < kinds.index("guard.verdict") < kinds.index("run.finished")
    assert ledger.verify_chain() == (True, None)


async def test_without_outreach_scope_no_draft_is_cleared():
    events = await collect(onboard("authorised_founder", ["data.read"]))
    assert any(e.get("step") == "guard" and "No outreach.hiring scope" in e["message"] for e in events)
    assert "guard.verdict" not in [e["kind"] for e in ledger.entries()]


def test_verify_resume_catches_a_false_employer():
    from app.main import app
    sp = SCENARIOS["authorised_founder"]["sponsor"]
    r = TestClient(app).post("/api/verify_resume", json={
        "name": sp["name"], "profile_url": sp["profile_url"], "claimed": {"employer": "Google"}})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] and body["ledger_entry"]
    assert any(c["status"] == "contradicted" and "Google" in c["claim"] for c in body["claims"])


def test_verify_resume_unknown_profile_is_unverifiable_not_invented():
    from app.main import app
    r = TestClient(app).post("/api/verify_resume", json={
        "profile_url": "https://www.linkedin.com/in/nobody-here-xyz", "claimed": {"employer": "Acme"}})
    body = r.json()
    assert not body["found"] and [c["status"] for c in body["claims"]] == ["unverifiable"]


async def test_sourced_alias_picks_the_active_sourced():
    old = onboard("authorised_founder", ["outreach.hiring", "data.read"])
    registry.suspend(old, "replaced", by="sponsor")
    new = onboard("authorised_founder", ["outreach.hiring", "data.read"])
    events = [e async for e in run_as_agent(BRIEF, "sourced", client=DevCrustdataClient())]
    passport = [e for e in events if e.get("step") == "passport" and e.get("data")][0]
    assert passport["data"]["agent_id"] == new
