"""Brief -> signed offer (app/talent/conversations.py) and shift staffing (app/talent/staffing.py).

Offline: real Send Guard + passports on the WS6 fixture sponsor, LLM_MODE=mock, CRUSTDATA_MODE=replay, and test-only
synthetic people in Crustdata's shape (tests/talent_factory.py) at the real scale (100 conversations, 1200 applicants).
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import ledger, registry
from app.agents.models import Sponsor
from app.talent import campaign as C
from app.talent.conversations import Engine, TERMINAL
from app.talent.pool import PoolGraph
from app.talent.replies import classify_rules
from app.talent.staffing import assign, make_shifts, names_match, run_staffing, screen, seed_applications
from tests.talent_factory import engineer_pool, shift_pool

SCEN = {s["id"]: s for s in json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
BRIEF = "Senior backend engineer, payments, Bangalore\nBudget 40-55 LPA, notice under 60 days\nOne hire"
START = datetime(2026, 11, 2, 9)
TODAY = date(2026, 10, 31)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    for k, v in {"AGENTS_PATH": "agents.json", "LEDGER_PATH": "ledger.jsonl", "ISSUER_KEY_PATH": "issuer.key",
                 "CAMPAIGNS_DIR": "campaigns", "OUTBOX_PATH": "outbox.jsonl"}.items():
        monkeypatch.setenv(k, str(tmp_path / v))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.delenv("COUNTERSIGN_ADMIN_TOKEN", raising=False)


def onboard(scopes=("outreach.hiring", "data.read", "contract.sign"), scenario="authorised_founder") -> str:
    return registry.onboard("Sourced", "recruiter", Sponsor(**SCEN[scenario]["sponsor"]), list(scopes))["agent_id"]


# ---- replies -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,stage,intent", [
    ("Sounds good, let's talk.", "contacted", "interested"),
    ("Thanks, but I'm not looking right now.", "contacted", "decline"),
    ("Please stop messaging me.", "contacted", "unsubscribe"),
    ("Ping me in a month? Wrapping up a big launch.", "contacted", "later"),
    ("Is this remote or in-office?", "contacted", "question"),
    ("My notice period is 60 days. Expected CTC 40 LPA", "screening", "info"),
    ("Let's do slot 2", "scheduling", "slot"),
    ("None of these work for me, sorry.", "scheduling", "reschedule"),
    ("I accept the offer. Signed: Asha Rao", "offer", "accept"),
    ("Could you stretch to 52 LPA?", "offer", "counter"),
    ("I have to say no, the number doesn't work for me.", "offer", "decline"),
])
def test_reply_intents(text, stage, intent):
    assert classify_rules(text, stage).intent == intent


def test_reply_facts():
    r = classify_rules("Notice is 2 month(s). Looking for 47.5 lakhs.", "screening")
    assert (r.notice_days, r.expected_lpa) == (60, 47.5)
    assert classify_rules("I can join immediately. Expecting 41 LPA", "screening").notice_days == 0
    assert classify_rules("Signed: Asha Rao", "offer").signature == "Asha Rao"
    r = classify_rules("Hi, yes I'm open. Before that, what's the budget for this role?", "contacted")
    assert r.intent == "interested" and r.question.startswith("Before that")


def test_parse_job():
    j = C.parse_job(BRIEF)
    assert (j["band_low"], j["band_high"], j["notice_max_days"], j["openings"]) == (40, 55, 60, 1)
    assert C.parse_job("SRE, Pune\nup to 30 LPA, join within 2 months\ntwo hires")["openings"] == 2
    assert C.parse_job("SRE, Pune\nup to 30 LPA, join within 2 months")["notice_max_days"] == 60


# ---- the engine with a scripted sender and candidate ----------------------------------------------------------------

class Recorder:
    def __init__(self, block_scopes=()):
        self.sent, self.block = [], set(block_scopes)

    async def __call__(self, conv, body, scope, now):
        self.sent.append((conv["id"], scope, body))
        if scope in self.block:
            return {"decision": "block", "checks": [{"name": "scope_granted", "status": "fail", "detail": f"no {scope} scope"}]}
        return {"decision": "allow", "checks": [], "ledger_entry": "e" * 8}


def bare_campaign(n=1, **job):
    crit = C.Criteria(role="Senior Backend Engineer", locations=["Bangalore"])
    camp = C.new(BRIEF, {**C.parse_job(BRIEF, crit), "company": "Grewon", **job}, crit, "agt_x", mode="live", start=START)
    ranked = [{"name": f"Asha Rao{'' if i == 0 else ' ' + str(i)}", "profile_url": f"https://linkedin.com/in/x{i}",
               "company": "Razorpay", "title": "Backend Engineer", "score": 80 - i, "hook": "Your time at Razorpay since 2021 stood out."}
              for i in range(n)]
    return camp, ranked


@pytest.mark.asyncio
async def test_silence_gets_two_followups_then_ghosted():
    camp, ranked = bare_campaign()
    rec = Recorder()
    eng = Engine(camp, rec)
    await eng.open(ranked)
    await eng.advance(START + timedelta(days=20))
    c = camp["conversations"]["c001"]
    assert [m["kind"] for m in c["messages"]] == ["outreach", "followup", "followup"]
    assert c["stage"] == "ghosted" and c["history"][-1]["at"].startswith("2026-11-16")


@pytest.mark.asyncio
async def test_full_path_to_signed_offer_with_counter_and_signature_check():
    camp, ranked = bare_campaign()
    rec = Recorder()
    eng = Engine(camp, rec, panel=lambda conv: (True, "strong"))
    await eng.open(ranked)
    say = lambda t: eng.receive("c001", t)  # noqa: E731
    await say("yes, interested! what's the budget?")
    c = camp["conversations"]["c001"]
    assert c["stage"] == "screening" and any("40-55 LPA" in m["body"] for m in c["messages"] if m["dir"] == "out")
    await say("Notice 30 days")
    assert c["stage"] == "screening" and c["messages"][-1]["kind"] == "screening_nudge"
    await say("expecting 50 LPA")
    assert c["stage"] == "scheduling"
    await say("None of these work for me, sorry.")
    await say("option 3")
    assert c["stage"] == "interview"
    await eng.advance(datetime.fromisoformat(c["interview"]["slot"]) + timedelta(hours=3))
    assert c["stage"] == "offer" and c["offer"]["ctc_lpa"] == 50
    assert rec.sent[-1][1] == "contract.sign"
    await say("Could you stretch to 54 LPA?")
    assert c["offer"]["ctc_lpa"] == 54 and c["offer"]["version"] == 2
    await say("I accept. Signed: Someone Else")
    assert c["stage"] == "offer" and c["messages"][-1]["kind"] == "sign_request"
    await say("Signed: Asha Rao")
    assert c["stage"] == "signed" and camp["status"] == "filled"
    sig = c["signature"]
    assert sig["ctc_lpa"] == 54 and sig["ledger_entry"]
    row = [e for e in ledger.entries() if e["kind"] == "offer.signed"][-1]
    assert row["payload"]["doc_sha256"] == sig["doc_sha256"] and row["payload"]["signed_as"] == "Asha Rao"


@pytest.mark.asyncio
async def test_screening_rejects_long_notice_and_out_of_band_pay():
    camp, ranked = bare_campaign(2)
    eng = Engine(camp, Recorder())
    await eng.open(ranked)
    for cid in ("c001", "c002"):
        await eng.receive(cid, "sure, tell me more")
    await eng.receive("c001", "Notice period 90 days, expecting 45 LPA")
    await eng.receive("c002", "Notice 30 days, expecting 80 LPA")
    assert camp["conversations"]["c001"]["stage"] == "rejected"
    assert camp["conversations"]["c002"]["stage"] == "rejected"


@pytest.mark.asyncio
async def test_unsubscribe_stops_everything():
    camp, ranked = bare_campaign()
    rec = Recorder()
    eng = Engine(camp, rec)
    await eng.open(ranked)
    await eng.receive("c001", "unsubscribe")
    await eng.advance(START + timedelta(days=30))
    assert camp["conversations"]["c001"]["stage"] == "unsubscribed" and len(rec.sent) == 1


@pytest.mark.asyncio
async def test_offer_without_contract_scope_is_held_not_sent():
    camp, ranked = bare_campaign()
    eng = Engine(camp, Recorder(block_scopes={"contract.sign"}), panel=lambda conv: (True, ""))
    await eng.open(ranked)
    for t in ("yes", "Notice 30 days, expecting 45 LPA", "1"):
        await eng.receive("c001", t)
    await eng.advance(START + timedelta(days=5))
    c = camp["conversations"]["c001"]
    assert c["stage"] == "offer_held" and c["messages"][-1]["guard"]["decision"] == "block"


@pytest.mark.asyncio
async def test_blocked_outreach_retries_without_facts_then_gives_up():
    camp, ranked = bare_campaign()

    async def sender(conv, body, scope, now):
        return {"decision": "block", "checks": [{"name": "claims_in_body_true", "status": "fail", "detail": "stale"}]}
    eng = Engine(camp, sender)
    await eng.open(ranked)
    c = camp["conversations"]["c001"]
    assert len(c["messages"]) == 2 and "stood out" not in c["messages"][1]["body"] and c["stage"] == "blocked"


# ---- 100 conversations, real Send Guard, simulated weeks ------------------------------------------------------------

@pytest.mark.asyncio
async def test_hundred_conversations_reach_a_signed_offer_through_send_guard():
    aid = onboard()
    camp, eng = await C.create(BRIEF, aid, None, size=100, pool=engineer_pool(120), start=START, seed=7)
    assert len(camp["conversations"]) == 100
    assert all(c["stage"] == "contacted" for c in camp["conversations"].values())
    for _ in range(8):
        await eng.advance(eng.now + timedelta(days=7))
        if camp["status"] == "filled":
            break
    s = eng.summary()
    assert s["status"] == "filled" and len(s["hires"]) == 1
    assert s["stats"]["guard_allowed"] >= 300 and s["stats"]["replies"] >= 100
    assert all(c["stage"] in TERMINAL for c in camp["conversations"].values())
    hire = camp["conversations"][camp["hires"][0]]
    assert hire["signature"]["ledger_entry"] and 40 <= hire["signature"]["ctc_lpa"] <= 55
    # every outbound message carries a Send Guard verdict that is on the ledger
    outs = [m for c in camp["conversations"].values() for m in c["messages"] if m["dir"] == "out"]
    assert all(m["guard"]["ledger_entry"] for m in outs)
    assert sum(e["kind"] == "guard.verdict" for e in ledger.entries()) >= len(outs)
    assert ledger.verify_chain() == (True, None)
    # persisted and resumable
    C.save(camp)
    again = C.load(camp["id"])
    assert again["status"] == "filled" and again["hires"] == camp["hires"]


@pytest.mark.asyncio
async def test_suspended_agent_cannot_start_a_campaign():
    aid = onboard()
    registry.suspend(aid, "sponsor asked", by="sponsor")
    with pytest.raises(PermissionError):
        await C.create(BRIEF, aid, None, size=5, pool=engineer_pool(10), start=START)


def test_campaign_api_create_stream_and_transcript():
    from app.main import app
    aid = onboard()
    import app.talent.campaign as camp_mod
    orig = camp_mod.source

    async def fake_source(criteria, client, want=100, today=None, pool=None):
        return await orig(criteria, client, want, today, pool=engineer_pool(40))
    camp_mod.source = fake_source
    try:
        cl = TestClient(app)
        r = cl.post("/api/campaigns", json={"brief": BRIEF, "agent_id": aid, "size": 30, "start": START.isoformat()})
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        assert r.json()["conversations"] == 30
        with cl.stream("GET", f"/api/campaigns/{cid}/stream?days=30") as s:
            evs = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
        assert evs[-1]["type"] == "done" and any(e["type"] == "day" for e in evs)
        conv = cl.get(f"/api/campaigns/{cid}").json()["conversations_list"][0]
        t = cl.get(f"/api/campaigns/{cid}/conversations/{conv['id']}").json()
        assert t["messages"][0]["guard"]["decision"] == "allow"
        assert cl.get("/api/campaigns").json()[-1]["id"] == cid
        assert cl.post(f"/api/campaigns/{cid}/advance", json={"days": 1}).status_code == 200
    finally:
        camp_mod.source = orig


# ---- shift staffing -------------------------------------------------------------------------------------------------

def test_names_match():
    assert names_match("Asha Rao", "Asha K. Rao") and names_match("asha rao", "Asha Rao")
    assert not names_match("Rohit Kumar", "Asha Rao") and not names_match("Asha Shetty", "Asha Rao")


@pytest.mark.asyncio
async def test_thousand_shifts_from_applications_seeded_with_fakes():
    pool = shift_pool(1200)
    apps, key = seed_applications(pool, fake_rate=0.15, seed=7, today=TODAY)
    assert len(apps) == 1200 and sum(k["fake"] for k in key.values()) == 180
    assert {k["lie"] for k in key.values() if k["fake"]} == {
        "stale_current_job", "fake_employer", "inflated_title", "stretched_tenure", "inflated_experience",
        "wrong_location", "identity_mismatch", "ghost_profile"}
    shifts = make_shifts(1000, start=TODAY + timedelta(days=1), seed=7)
    events = []

    async def emit(e):
        events.append(e)
    out = await run_staffing(apps, shifts, PoolGraph(pool), today=TODAY, answer_key=key, emit=emit)
    r, fc = out["report"], out["report"]["fake_catch"]
    assert fc["precision"] >= 0.95 and fc["recall"] >= 0.95 and fc["fakes_staffed"] == []
    assert r["fill_rate"] >= 0.95 and r["shifts"] == 1000
    # nobody is double-booked or over their weekly cap, and every worker is a cleared applicant in the right city/role
    by_app = {a["id"]: a for a in apps}
    cleared = {s["app_id"]: s for s in out["screenings"] if s["outcome"] == "cleared"}
    seen = set()
    for row in out["roster"]:
        if row["worker"]:
            w = cleared[row["worker"]]
            assert (w["role"], w["home_city"]) == (row["role"], row["city"])
            assert date.fromisoformat(row["date"]).weekday() in by_app[row["worker"]]["availability"]
            assert (row["worker"], row["date"]) not in seen
            seen.add((row["worker"], row["date"]))
    assert events[-1]["type"] == "done" and any(e["type"] == "flagged" for e in events)
    # every flagged application says why, with a cited source
    for s in out["screenings"]:
        if s["outcome"] == "flagged":
            assert s["reason"] and all(c["source"]["endpoint"] for c in s["claims"])


@pytest.mark.asyncio
async def test_screen_explains_each_lie():
    pool = shift_pool(60)
    graph = PoolGraph(pool)
    apps, key = seed_applications(pool, fake_rate=1.0, seed=3, today=TODAY)
    kinds = {}
    for a in apps:
        s = await screen(a, graph, TODAY)
        kinds.setdefault(key[a["id"]]["lie"], s.kind)
    assert kinds["ghost_profile"] == "identity_unverifiable"
    assert kinds["identity_mismatch"] == "identity_mismatch"
    assert kinds["wrong_location"] == "false_claim" and kinds["stretched_tenure"] == "false_claim"


def test_assign_respects_capacity_and_explains_open_shifts():
    shifts = make_shifts(50, start=date(2026, 11, 2), days=7, seed=1, cities=["Pune"], demand={"security": 1.0})
    workers = [{"id": "w1", "role": "security", "city": "Pune", "availability": list(range(7)), "max_shifts_per_week": 2}]
    filled, why = assign(shifts, workers)
    assert len(filled) <= 2 and len(filled) + len(why) == 50
    assert all("cap" in w or "booked" in w for w in why.values())
    filled, why = assign(shifts, [])
    assert not filled and all("no cleared" in w for w in why.values())


def test_staffing_api_uses_recorded_pool(monkeypatch):
    from app.main import app
    import app.talent.api as api
    monkeypatch.setattr(api, "load_pool", lambda name: (shift_pool(300), {}))
    cl = TestClient(app)
    with cl.stream("GET", "/api/staffing/run?shifts=200&today=2026-10-31") as s:
        evs = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    assert evs[-1]["type"] == "done" and evs[-1]["report"]["fake_catch"]["recall"] >= 0.9
    assert cl.get("/api/staffing/last").json()["report"]["shifts"] == 200
    j = cl.post("/api/staffing/run", json={"shifts": 100, "today": "2026-10-31"}).json()
    assert j["report"]["filled"] > 0 and all(f["outcome"] == "flagged" for f in j["flagged"])
