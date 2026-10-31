import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.brief import broaden_ladder, heuristic_parse
from app.fallbacks import DevCrustdataClient
from app.orchestrator import run
from app.schemas import Candidate, Criteria


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.setenv("CRUSTDATA_MODE", "dev")


def collect(brief, client=None):
    async def go():
        return [e async for e in run(brief, client=client)]
    return asyncio.run(go())


def test_mock_generate_json_is_schema_valid():
    c = asyncio.run(llm.generate_json("x", Criteria))
    assert isinstance(c, Criteria)
    cand = asyncio.run(llm.generate_json("x", Candidate))
    assert cand.claims and cand.claims[0].status == "verified"


def test_heuristic_parse_messy_brief():
    c = heuristic_parse("need a sr backend eng, payments exp, blr, ex-startup, can start soon")
    assert c.role == "Senior Backend Engineer"
    assert "Bangalore" in c.locations and "payments" in c.skills
    assert c.title_variants[0] == "Senior Backend Engineer"


def test_broaden_ladder_drops_location():
    c = heuristic_parse("senior backend engineer in bangalore, payments")
    steps = [d for d, _ in broaden_ladder(c)]
    assert steps[0] == "exact titles + location" and "dropped location" in steps


def test_end_to_end_events():
    evs = collect("need a senior backend eng, payments exp, Bangalore, ex-startup")
    types = [e.type for e in evs]
    assert types[0] == "step" and types[-1] == "done"
    cands = [e.candidate for e in evs if e.type == "candidate"]
    assert cands
    for c in cands:
        ids = {k.id for k in c.claims}
        assert all(k.source.endpoint for k in c.claims)
        assert all(i in ids for r in c.reasons for i in r.claim_ids)
        assert c.outreach_draft
    assert evs[-1].summary.shortlisted == len(cands)
    assert any("Changed jobs" in f for c in cands for f in c.flags)


def test_auto_broaden_when_location_has_no_hits():
    evs = collect("senior backend engineer in Berlin, payments")
    msgs = [e.message for e in evs if e.type == "step" and e.step == "search"]
    assert any(m.startswith("Broadening") for m in msgs)
    assert any(e.type == "candidate" for e in evs)


def test_empty_brief_and_no_results_finish_cleanly():
    evs = collect("   ")
    assert evs[-1].type == "done" and any(e.type == "error" for e in evs)

    class Empty(DevCrustdataClient):
        async def person_search(self, filters, limit=25):
            return []
    evs = collect("backend engineer", client=Empty())
    assert evs[-1].type == "done" and evs[-1].summary.searched == 0


def test_flaky_client_marks_errors_not_crash():
    class Flaky(DevCrustdataClient):
        async def person_enrich(self, url):
            raise TimeoutError("boom")
    evs = collect("senior backend engineer bangalore payments", client=Flaky())
    assert any(e.type == "error" and e.step == "enrich" for e in evs)
    assert any(e.type == "candidate" for e in evs) and evs[-1].type == "done"


def test_sse_endpoint():
    from app.main import app
    with TestClient(app) as tc:
        r = tc.post("/api/run", json={"brief": "senior backend engineer bangalore payments"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
        assert events[-1]["type"] == "done"
        assert any(e["type"] == "candidate" for e in events)
        r = tc.get("/api/replay?delay=0")
        assert r.text.count("data: ") == 10


def test_run_fixture_matches_schemas():
    from pathlib import Path
    from pydantic import TypeAdapter
    from app.schemas import Event
    ta = TypeAdapter(Event)
    lines = (Path(__file__).parents[2] / "fixtures" / "run.jsonl").read_text().splitlines()
    for l in lines:
        ta.validate_json(l)
