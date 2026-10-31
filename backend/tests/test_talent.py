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
    # live run: a small-caps profile name was flagged as someone else's
    assert names_match("ꜱɴᴇʜᴀʟ ᴛᴇᴋᴀʟᴇ", "ꜱɴᴇʜᴀʟ ᴛᴇᴋᴀʟᴇ") and names_match("Snehal Tekale", "ꜱɴᴇʜᴀʟ ᴛᴇᴋᴀʟᴇ")
    assert names_match("José Pérez", "Jose Perez") and not names_match("ꜱɴᴇʜᴀʟ ᴛᴇᴋᴀʟᴇ", "Asha Rao")


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


@pytest.mark.asyncio
async def test_live_campaign_sends_real_mail_through_outbound_and_routes_replies(monkeypatch):
    import sys
    import types
    sent, handlers = [], []

    class Res:
        def __init__(self, ok, status):
            self.ok, self.status, self.detail = ok, status, None if ok else "no email on record"
            self.verdict = {"decision": "allow", "checks": [], "ledger_entry": "led1"}

    async def guarded_send(agent_id, to, subject, body, *, scope="outreach.hiring", thread_key=None):
        sent.append((to["name"], subject, scope, thread_key))
        return Res(to["name"] != "Asha Rao 1", "sent" if to["name"] != "Asha Rao 1" else "no_email")
    send_mod = types.ModuleType("app.outbound.send")
    send_mod.guarded_send = guarded_send
    track_mod = types.ModuleType("app.outbound.tracking")
    track_mod.register_reply_handler = handlers.append
    monkeypatch.setitem(sys.modules, "app.outbound", types.ModuleType("app.outbound"))
    monkeypatch.setitem(sys.modules, "app.outbound.send", send_mod)
    monkeypatch.setitem(sys.modules, "app.outbound.tracking", track_mod)
    monkeypatch.setattr(C, "_registered", False)

    camp, ranked = bare_campaign(2)
    eng = C.engine_for(camp)
    await eng.open(ranked)
    C.save(camp)
    assert [s[3] for s in sent] == [f"{camp['id']}:c001", f"{camp['id']}:c002", f"{camp['id']}:c002"]
    assert camp["conversations"]["c002"]["stage"] == "blocked"   # no email found: never "sent"
    assert handlers, "reply handler registered"
    await handlers[0]({"thread_key": f"{camp['id']}:c001"}, {"text": "yes, interested"})
    again = C.load(camp["id"])
    assert again["conversations"]["c001"]["stage"] == "screening"


# ---- shift staffing for any mass-hiring role: roles, CSV, duplicates, no double-booking, bench ---------------------

from app.talent.staffing import (Role, Rota, build_shifts, find_duplicates, parse_csv, parse_days, resolve_role, template,
                                 to_csv, TEMPLATES)

NURSE = Role(title="Staff nurse", cities=["Kochi", "bengaluru"], slots=[{"start": "07:00", "end": "14:00"}, {"start": "21:00", "end": "07:00"}],
             headcount=2, city_headcount={"Kochi": 3}, min_years=1, keywords=["nurse", "nursing"],
             certifications=["Registered nurse"], languages=["English", "Malayalam"])


def test_role_requirements_and_shifts():
    assert NURSE.id == "staff-nurse" and NURSE.cities == ["Kochi", "Bangalore"]
    shifts = build_shifts([NURSE], start=date(2026, 11, 2), days=7)
    assert len(shifts) == 7 * 2 * (3 + 2)
    night = next(s for s in shifts if s["slot"] == "21:00-07:00")
    assert night["start"].endswith("21:00") and night["end"] > night["start"] and night["hours"] == 10
    assert "Registered nurse" in NURSE.needs() and "speaks Malayalam" in NURSE.needs()
    # every template builds; together they cover the kinds of mass hiring companies do
    assert {t["id"] for t in TEMPLATES} >= {"quick-commerce", "bpo", "retail-seasonal", "hospital", "events", "campus"}
    for t in TEMPLATES:
        assert build_shifts(template(t["id"]), start=date(2026, 11, 2))
    roles = template("bpo")
    assert resolve_role("Customer service voice agent", roles).id == "voice-agent" and resolve_role("chat-agent", roles).id == "chat-agent"
    assert resolve_role("brain surgeon", roles) is None


def test_parse_csv_loose_columns_and_days():
    text = ("Full Name,LinkedIn,Mobile,E-mail,Applied For,City,Company,Designation,Experience,Languages,Certifications,Days,Max Shifts\n"
            "Asha Rao,https://linkedin.com/in/asha,+91 98450 12345,asha@x.in,Staff nurse,Bengaluru,Manipal,Staff Nurse,3 yrs,English; Kannada,Registered nurse,Mon-Fri,4\n"
            ",https://linkedin.com/in/nobody,,,,,,,,,,,\n"
            "Ravi K,,,,Ward assistant,Kochi,,,,,,weekends,\n")
    apps, errors = parse_csv(text)
    assert [a["name"] for a in apps] == ["Asha Rao", "Ravi K"] and errors == [{"row": 3, "error": "no name"}]
    a = apps[0]
    assert (a["city"], a["claimed"]["years_experience"], a["languages"], a["availability"], a["max_shifts_per_week"]) == \
        ("Bangalore", 3.0, ["English", "Kannada"], [0, 1, 2, 3, 4], 4)
    assert apps[1]["availability"] == [5, 6] and apps[1]["profile_url"] == ""
    assert parse_days("Sat to Mon") == [0, 5, 6] and parse_days("") == list(range(7))
    assert parse_csv("foo,bar\n1,2\n")[0] == []


def _apps_for(recs, role="delivery", **kw):
    from app.verify.profile import load_person
    out = []
    for i, r in enumerate(recs):
        pr = load_person(r)
        out.append({"id": f"a{i + 1}", "name": pr.name, "profile_url": pr.profile_url, "role": role, "city": "Pune",
                    "email": f"p{i}@example.com", "phone": f"98000000{i:02d}", "claimed": {"employer": pr.current[0].company},
                    "certifications": ["Two-wheeler driving licence"], "languages": ["English", "Hindi"],
                    "availability": list(range(7)), "max_shifts_per_week": 5, **kw})
    return out


def test_duplicates_are_merged_before_screening():
    from tests.talent_factory import person
    import random as _r
    rng = _r.Random(1)
    recs = [person(i, "delivery", "Pune", rng) for i in range(3)]
    apps = _apps_for(recs)
    again = {**apps[0], "id": "a9", "profile_url": apps[0]["profile_url"].replace("https://www.", "http://") + "/?utm=x",
             "email": "", "phone": "+91 " + apps[0]["phone"]}
    other_role = {**apps[1], "id": "a10", "role": "warehouse", "email": "", "phone": ""}
    shared = {**apps[2], "id": "a11", "name": "Rohit Kumar", "profile_url": "https://www.linkedin.com/in/rohit-k", "email": apps[2]["email"]}
    person_of, skip = find_duplicates(apps + [again, other_role, shared])
    assert skip["a9"][:2] == ("duplicate", "repeat_application") and "a1" in skip["a9"][2]
    assert "a10" not in skip and person_of["a10"] == person_of["a2"]          # same person, another role: kept, linked
    assert skip["a11"][1] == "shared_contact" and skip["a3"][1] == "shared_contact"
    assert "a1" not in skip and "a2" not in skip


def test_one_person_never_on_overlapping_shifts_across_roles():
    roles = [Role(id="delivery", title="Delivery", cities=["Pune"], slots=[{"start": "07:00", "end": "13:00"}], headcount=1),
             Role(id="warehouse", title="Warehouse", cities=["Pune"], slots=[{"start": "10:00", "end": "18:00"}], headcount=1)]
    shifts = build_shifts(roles, start=date(2026, 11, 2), days=3)
    workers = [{"id": "w1", "person": "p1", "role": "delivery", "city": "Pune", "availability": list(range(7)), "max_shifts_per_week": 7},
               {"id": "w2", "person": "p1", "role": "warehouse", "city": "Pune", "availability": list(range(7)), "max_shifts_per_week": 7}]
    r = Rota(shifts, workers, rest_hours=0)
    r.assign()
    assert len(r.filled) == 3 and r.double_bookings() == []                  # one of the two each day, never both
    assert all("booked" in w for w in r.why.values())
    # without the person link the same two applications would double-book
    loose = Rota(shifts, [{**w, "person": w["id"]} for w in workers], rest_hours=0)
    loose.assign()
    assert len(loose.filled) == 6


def test_bench_backfills_no_shows():
    role = Role(id="security", title="Security", cities=["Pune"], slots=[{"start": "08:00", "end": "20:00"}], headcount=2)
    shifts = build_shifts([role], start=date(2026, 11, 2), days=2)
    workers = [{"id": f"w{i}", "role": "security", "city": "Pune", "availability": list(range(7)), "max_shifts_per_week": 3, "name": f"W{i}"} for i in range(6)]
    r = Rota(shifts, workers)
    r.assign()
    b = r.fill_bench(0.5)
    assert len(r.filled) == 4 and b["standby_found"] == b["standby_wanted"] == 2 and b["shift_times_covered"] == 2
    on_bench = set(r.bench[Rota.group(shifts[0])])
    assert on_bench.isdisjoint({r.filled[s["id"]] for s in shifts[:2]})
    out = r.no_show(shifts[0]["id"])
    assert out["from"] == "bench" and out["backup"] in on_bench and r.filled[shifts[0]["id"]] == out["backup"]
    assert r.no_shows[shifts[0]["id"]] == out["no_show"] and r.double_bookings() == []
    row = next(x for x in r.roster() if x["id"] == shifts[0]["id"])
    assert row["no_show"] == out["no_show"] and row["worker"] == out["backup"]


@pytest.mark.asyncio
async def test_requirements_decide_fit():
    from tests.talent_factory import person
    import random as _r
    rec = person(1, "delivery", "Pune", _r.Random(2))
    graph = PoolGraph([rec])
    roles = template("quick-commerce")
    base = _apps_for([rec])[0]
    s = await screen(base, graph, TODAY, roles[0])
    assert s.outcome == "cleared" and any("licence" in c for c in s.checks)
    s = await screen({**base, "certifications": []}, graph, TODAY, roles[0])
    assert (s.outcome, s.kind) == ("not_qualified", "missing_requirement") and "licence" in s.reason
    s = await screen(base, graph, TODAY, roles[0].model_copy(update={"min_years": 30}))
    assert s.kind == "under_experience"
    s = await screen({**base, "city": "Jaipur"}, graph, TODAY, roles[0])
    assert s.outcome in ("flagged", "not_qualified")                          # lives in Pune: never staffed in Jaipur
    s = await screen(base, graph, TODAY, NURSE)
    assert s.kind in ("role_not_open", "role_mismatch")


@pytest.mark.asyncio
async def test_template_run_in_test_mode_catches_fakes_and_repeats():
    pool = shift_pool(1200)
    roles = template("quick-commerce")
    apps, key = seed_applications(pool, roles=roles, fake_rate=0.15, seed=7, today=TODAY, duplicate_rate=0.03)
    shifts = build_shifts(roles, start=TODAY + timedelta(days=1))
    out = await run_staffing(apps, shifts, PoolGraph(pool), roles=roles, today=TODAY, answer_key=key, no_show_rate=0.08)
    r, fc = out["report"], out["report"]["fake_catch"]
    assert fc["precision"] >= 0.95 and fc["recall"] >= 0.95 and fc["fakes_staffed"] == []
    assert fc["duplicates_planted"] > 20 and fc["duplicates_caught"] == fc["duplicates_planted"]
    assert r["double_bookings"] == 0 and r["fill_rate"] >= 0.9 and r["bench"]["standby_found"] > 0
    assert r["no_show_drill"]["no_shows"] > 0 and r["no_show_drill"]["double_bookings_after"] == 0
    assert r["no_show_drill"]["from_bench"] >= r["no_show_drill"]["no_shows"] * 0.5
    assert set(r["roles"]) == {x.id for x in roles} and all(v["needs"] for v in r["roles"].values())
    # nobody staffed is a fake, a duplicate, or outside their role, city or days
    by_app = {a["id"]: a for a in apps}
    scr = {s["app_id"]: s for s in out["screenings"]}
    for row in out["roster"]:
        if row["worker"]:
            s = scr[row["worker"]]
            assert s["outcome"] == "cleared" and (s["role"], s["city"]) == (row["role"], row["city"])
            assert date.fromisoformat(row["date"]).weekday() in by_app[row["worker"]]["availability"]
    # test mode off: the same pool, honest applications, no answer key
    apps2, _ = seed_applications(pool, roles=roles, fake_rate=0.0, seed=7, today=TODAY)
    out2 = await run_staffing(apps2, shifts, PoolGraph(pool), roles=roles, today=TODAY)
    assert "fake_catch" not in out2["report"] and out2["report"]["screening"]["flagged"] == 0


def test_staffing_api_csv_upload_holds_unknown_profiles(monkeypatch, tmp_path):
    from app.main import app
    import app.talent.api as api
    pool = shift_pool(300)
    monkeypatch.setattr(api, "load_pool", lambda name: (pool, {}))
    monkeypatch.setenv("STAFFING_DIR", str(tmp_path / "staffing"))
    monkeypatch.setattr(api, "crustdata", lambda: (_ for _ in ()).throw(AssertionError("no live Crustdata calls")))
    cl = TestClient(app)
    t = cl.get("/api/staffing/templates").json()
    assert t["default"] == "quick-commerce" and len(t["templates"]) >= 6 and "name" in t["csv_columns"]
    sample = cl.get("/api/staffing/sample.csv?n=120&lies=0.1").text
    apps, errors = parse_csv(sample)
    assert len(apps) >= 120 and not errors
    sample += "Ghost Person,https://www.linkedin.com/in/not-recorded-123,,,delivery,Pune,,,,,,,,,,\n"
    up = cl.post("/api/staffing/applications", json={"csv": sample, "name": "apps.csv"}).json()
    assert up["applications"] == len(apps) + 1 and up["in_recorded_data"] >= len(apps) - 15
    with cl.stream("POST", "/api/staffing/run/stream", json={"source": "upload", "upload_id": up["upload_id"], "today": "2026-10-31"}) as s:
        evs = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    done = evs[-1]
    assert done["type"] == "done", evs[-1]
    r = done["report"]
    assert r["screening"]["held"] >= 1 and r["lookups"]["live"] == 0 and r["filled"] > 0 and "fake_catch" not in r
    held = cl.get("/api/staffing/screenings?outcome=held").json()["rows"]
    assert any(h["name"] == "Ghost Person" and h["kind"] == "needs_lookup" for h in held)
    assert r["screening"]["flagged"] > 0                                   # the sample's planted lies are still caught
    roster = cl.get("/api/staffing/roster?status=filled&limit=5").json()
    sid = roster["rows"][0]["id"]
    ns = cl.post("/api/staffing/no-show", json={"shift_id": sid}).json()
    assert ns["no_show"] and ns["double_bookings"] == 0
    assert cl.get("/api/staffing/roster.csv").text.startswith("shift,role,city")
    # custom roles in the body, test mode on
    nurse = NURSE.model_dump()
    j = cl.post("/api/staffing/run", json={"roles": [template("quick-commerce")[0].model_dump(), nurse], "test_mode": True,
                                           "today": "2026-10-31"}).json()
    assert j["report"]["test_mode"] and j["report"]["roles"]["staff-nurse"]["applied"] == 0
    assert any("staff nurse" in k for k in j["report"]["open_reasons"])
    assert (tmp_path / "staffing" / "uploads" / f"{up['upload_id']}.json").exists()
