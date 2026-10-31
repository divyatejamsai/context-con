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


def test_to_crustdata_filters_matches_real_grammar():
    from app.orchestrator import to_crustdata_filters
    f = to_crustdata_filters({"titles": ["Senior Backend Engineer"], "locations": ["Bangalore", "India"], "seniority": None})
    assert f["op"] == "and"
    title, loc = f["conditions"]
    assert title == {"field": "experience.employment_details.current.title", "type": "(.)", "value": "senior backend engineer"}
    vals = {(c["field"], c["value"]) for c in loc["conditions"]}
    assert ("basic_profile.location.city", "bengaluru") in vals and ("basic_profile.location.country", "India") in vals


class RealShaped:
    """Mimics WS1's CrustdataClient with records in the real 2025-11-01 shape."""

    def __init__(self):
        self.calls = {"search": [], "enrich_many": 0, "enrich": 0}
        self.rec = {
            "crustdata_person_id": 1,
            "basic_profile": {"name": "Test Person", "headline": "Backend @ Razorpay", "current_title": "Senior Backend Engineer",
                              "location": {"city": "Bengaluru", "country": "India"}},
            "experience": {"employment_details": {"current": [{"title": "Senior Backend Engineer", "name": "Razorpay",
                                                               "crustdata_company_id": 42, "start_date": "2021-03-01"}], "past": []}},
            "social_handles": {"professional_network_identifier": {"profile_url": "https://www.linkedin.com/in/test-person"}},
            "skills": {"professional_network_skills": ["Payments", "Python"]},
            "_source": {"endpoint": "person/search", "request_hash": "x", "fetched_at": "2026-10-31T00:00:00Z"},
        }

    async def person_search(self, filters, limit=25, **extra):
        self.calls["search"].append((filters, extra))
        return [dict(self.rec)]

    async def person_enrich_many(self, urls, fields=None):
        self.calls["enrich_many"] += 1
        return {u: dict(self.rec, _source={"endpoint": "person/enrich", "request_hash": "y", "fetched_at": "2026-10-31T00:00:00Z"}) for u in urls}

    async def person_enrich(self, url, fields=None):
        self.calls["enrich"] += 1
        return None

    async def company_enrich(self, company_id=None, domain=None, fields=None):
        return {"crustdata_company_id": 42, "basic_info": {"name": "Razorpay"}, "headcount": {"total": 3000},
                "_source": {"endpoint": "company/enrich", "request_hash": "z", "fetched_at": "2026-10-31T00:00:00Z"}}

    async def company_identify(self, name=None, domain=None):
        return None

    async def company_search(self, filters, limit=25, **extra):
        return []

    async def job_search(self, filters, limit=25, **extra):
        return []

    async def web_search(self, query, **extra):
        return []

    async def web_fetch(self, url):
        return None


def test_real_shaped_client_end_to_end():
    client = RealShaped()
    evs = collect("senior backend engineer bangalore payments", client=client)
    filters, extra = client.calls["search"][0]
    assert "op" in filters or "field" in filters  # real grammar, not the simple shape
    assert extra.get("fields")
    assert client.calls["enrich_many"] == 1 and client.calls["enrich"] == 0
    cands = [e.candidate for e in evs if e.type == "candidate"]
    assert len(cands) == 1
    c = cands[0]
    assert c.name == "Test Person" and c.company == "Razorpay" and c.profile_url.endswith("test-person")
    assert c.claims and evs[-1].type == "done"
