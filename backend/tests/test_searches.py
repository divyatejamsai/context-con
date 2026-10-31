"""Past searches (app/talent/searches.py): shortlist runs and campaigns listed newest first, each candidate's stage,
and stage changes by hand. Offline: DevCrustdataClient, LLM_MODE=mock, a test-only engineer pool for campaigns."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import ledger, registry
from app.agents.models import Sponsor
from app.fallbacks import DevCrustdataClient
from app.sourced_agent import run_as_agent
from app.talent import campaign as C
from app.talent import searches as S
from tests.talent_factory import engineer_pool

SCEN = {s["id"]: s for s in json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
START = datetime(2026, 11, 2, 9)
CAMP_BRIEF = "Senior backend engineer, payments, Bangalore\nBudget 40-55 LPA, notice under 60 days\nOne hire"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    for k, v in {"AGENTS_PATH": "agents.json", "LEDGER_PATH": "ledger.jsonl", "ISSUER_KEY_PATH": "issuer.key",
                 "CAMPAIGNS_DIR": "campaigns", "OUTBOX_PATH": "outbox.jsonl", "PIPELINE_PATH": "pipeline.json"}.items():
        monkeypatch.setenv(k, str(tmp_path / v))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.delenv("COUNTERSIGN_ADMIN_TOKEN", raising=False)


def onboard() -> str:
    return registry.onboard("Sourced", "recruiter", Sponsor(**SCEN["authorised_founder"]["sponsor"]),
                            ["outreach.hiring", "data.read", "contract.sign"])["agent_id"]


async def shortlist_run(aid: str) -> None:
    async for _ in run_as_agent("senior backend engineer, payments, Bangalore", aid, client=DevCrustdataClient()):
        pass


async def campaign(aid: str, days: int = 0) -> dict:
    camp, eng = await C.create(CAMP_BRIEF, aid, None, size=20, start=START, pool=engineer_pool(30))
    if days:
        await eng.advance(START + timedelta(days=days))
        C.save(camp)
    return camp


@pytest.mark.asyncio
async def test_lists_runs_and_campaigns_newest_first_with_stage_counts():
    aid = onboard()
    await shortlist_run(aid)
    camp = await campaign(aid, days=20)
    cl = TestClient(__import__("app.main", fromlist=["app"]).app)
    rows = cl.get("/api/searches").json()
    assert [r["kind"] for r in rows] == ["campaign", "shortlist"]  # the campaign was started last
    run, cmp_ = rows[1], rows[0]
    assert run["id"].startswith("run_") and run["counts"]["shortlisted"] + run["counts"]["contacted"] > 0
    assert cmp_["id"] == camp["id"] and cmp_["simulated"] is True and sum(cmp_["counts"].values()) == 20
    assert set(run["counts"]) == set(S.STAGES)


@pytest.mark.asyncio
async def test_campaign_stages_are_translated_with_reasons():
    aid = onboard()
    camp = await campaign(aid, days=20)
    cl = TestClient(__import__("app.main", fromlist=["app"]).app)
    d = cl.get(f"/api/searches/{camp['id']}").json()
    assert d["title"] and d["brief"] == CAMP_BRIEF and len(d["candidates"]) == 20
    for r in d["candidates"]:
        engine = camp["conversations"][r["key"]]["stage"]
        assert r["stage"] == S.ENGINE[engine][0]
        if r["stage"] in ("dropped", "rejected"):
            assert r["reason"], r
        assert r["history"] and r["history"][0]["stage"] == "contacted"
    assert any(r["stage"] != "contacted" for r in d["candidates"])  # twenty days in, people have moved


@pytest.mark.asyncio
async def test_stage_change_by_hand_on_a_shortlist_run():
    aid = onboard()
    await shortlist_run(aid)
    cl = TestClient(__import__("app.main", fromlist=["app"]).app)
    sid = cl.get("/api/searches").json()[0]["id"]
    d = cl.get(f"/api/searches/{sid}").json()
    key = next(r["key"] for r in d["candidates"] if r["stage"])
    assert cl.post(f"/api/searches/{sid}/candidates/{key}/stage", json={"stage": "dropped"}).status_code == 422
    r = cl.post(f"/api/searches/{sid}/candidates/{key}/stage", json={"stage": "interviewing"})
    assert r.status_code == 200 and r.json()["stage"] == "interviewing" and r.json()["set_by"] == "you"
    r = cl.post(f"/api/searches/{sid}/candidates/{key}/stage", json={"stage": "dropped", "reason": "Took another offer"})
    assert r.json()["reason"] == "Took another offer"
    assert [h["stage"] for h in r.json()["history"] if h["by"] != "Sourced"] == ["interviewing", "dropped"]
    again = next(x for x in cl.get(f"/api/searches/{sid}").json()["candidates"] if x["key"] == key)
    assert again["stage"] == "dropped"
    assert cl.get("/api/searches").json()[0]["counts"]["dropped"] == 1
    assert [e["payload"]["to"] for e in ledger.entries(kind="candidate.stage")] == ["interviewing", "dropped"]
    assert cl.post(f"/api/searches/{sid}/candidates/nobody/stage", json={"stage": "hired"}).status_code == 404
    assert cl.get("/api/searches/run_000000000000").status_code == 404


@pytest.mark.asyncio
async def test_dropping_a_campaign_candidate_ends_the_conversation():
    aid = onboard()
    camp = await campaign(aid)
    cl = TestClient(__import__("app.main", fromlist=["app"]).app)
    key = next(iter(camp["conversations"]))
    r = cl.post(f"/api/searches/{camp['id']}/candidates/{key}/stage", json={"stage": "dropped", "reason": "Hired elsewhere"})
    assert r.status_code == 200 and r.json()["stage"] == "dropped"
    conv = C.load(camp["id"])["conversations"][key]
    assert conv["stage"] == "closed" and conv["timer"] is None and "Hired elsewhere" in conv["history"][-1]["why"]
    hist = [h["stage"] for h in r.json()["history"]]
    assert hist.count("dropped") == 1 and r.json()["reason"] == "Hired elsewhere"


def test_engine_reasons_read_plainly():
    assert S._plain("notice 90d > 60d") == "Notice period is 90 days, the brief allows 60"
    assert S._plain("expects 62 LPA, band tops at 55") == "Expects 62 LPA, the band tops out at 55"
    assert S._plain("interview: panel score 0.40 (pass at 0.50)").startswith("Didn't pass the interview")
