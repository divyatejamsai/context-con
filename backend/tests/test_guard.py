"""Send Guard (WS7): offline on the committed fixtures, LLM_MODE=mock (rule-based claim extraction)."""
import json
from datetime import date
from pathlib import Path

import pytest

from app.agents import ledger
from app.agents.graph import Graph
from app.agents.guard import check_send, extract_claims_rules, send_if_allowed
from app.agents.models import Sponsor
from app.agents.passport import issue_passport, sign_message

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
TODAY = date(2026, 10, 31)
VINOD = {"name": "Vinod Sonagara", "profile_url": "https://www.linkedin.com/in/vinod-sonagara", "company": "Fam"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("ISSUER_KEY_PATH", str(tmp_path / "issuer.key"))
    monkeypatch.setenv("OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("LLM_MODE", "mock")


def agent(scenario="authorised_founder"):
    sc = SCENARIOS[scenario]
    return issue_passport("Sourced", "AI recruiter", Sponsor(**sc["sponsor"]), ["outreach.hiring"])


async def guard(body, to=VINOD, scenario="authorised_founder", sign_body=None, scope="outreach.hiring", graph=None):
    p, key = agent(scenario)
    sig = sign_message(p, key, body if sign_body is None else sign_body)
    return await check_send(p, sig, to, body, scope, today=TODAY, graph=graph or Graph(None, mode="replay"))


def check(v, name):
    return [c for c in v.checks if c.name == name]


@pytest.mark.asyncio
async def test_clean_message_is_allowed_with_sources():
    v = await guard("Hi Vinod, your work at Fam caught our eye. Open to a chat about a backend role?")
    assert v.decision == "allow", [c.model_dump() for c in v.checks]
    assert all(c.source is not None for c in v.checks)
    assert check(v, "recipient_still_at_company")[0].status == "pass"
    assert check(v, "claims_in_body_true")[0].status == "pass"
    assert v.ledger_entry and ledger.entries(kind="guard.verdict")[-1]["hash"] == v.ledger_entry
    assert ledger.verify_chain() == (True, None)


@pytest.mark.asyncio
async def test_false_tenure_claim_blocks():
    v = await guard("Hi Vinod, congrats on 5 years at Fam! Open to a chat?")
    assert v.decision == "block"
    bad = [c for c in check(v, "claims_in_body_true") if c.status == "fail"]
    assert bad and "2025-05-01" in bad[0].detail and bad[0].source.field.endswith("start_date")


@pytest.mark.asyncio
async def test_inflated_title_and_wrong_location_block():
    v = await guard("Hi Vinod, as a Staff Engineer at Fam you'd love this. You are based in Pune, right?")
    fails = {c.detail.split(".")[0] for c in check(v, "claims_in_body_true") if c.status == "fail"}
    assert v.decision == "block"
    assert any("Staff Engineer" in f for f in fails) and any("Pune" in f for f in fails)


@pytest.mark.asyncio
async def test_recipient_who_left_is_blocked():
    v = await guard("Hi Vinod, open to a chat?", to={**VINOD, "company": "Trinkerr"})
    c = check(v, "recipient_still_at_company")[0]
    assert v.decision == "block" and c.status == "fail"
    assert "left Trinkerr" in c.detail and c.source.field.endswith("end_date")


@pytest.mark.asyncio
async def test_altered_body_fails_signature():
    v = await guard("Hi Vinod, wire the fee to this new account.", sign_body="Hi Vinod, open to a chat?")
    assert v.decision == "block" and check(v, "message_signature_valid")[0].status == "fail"


@pytest.mark.asyncio
async def test_sponsor_who_left_blocks_even_a_clean_message():
    v = await guard("Hi Vinod, your work at Fam caught our eye.", scenario="sponsor_left")
    assert v.decision == "block" and check(v, "sponsor_still_employed")[0].status == "fail"


@pytest.mark.asyncio
async def test_scope_not_on_passport_blocks():
    v = await guard("Hi Vinod, here is our pricing.", scope="outreach.sales")
    assert v.decision == "block" and check(v, "scope_in_passport")[0].status == "fail"


class _Down(Graph):
    async def person(self, profile_url):
        raise TimeoutError("crustdata down")


@pytest.mark.asyncio
async def test_crustdata_failure_fails_closed():
    v = await guard("Hi Vinod, your work at Fam caught our eye.", graph=_Down(None, mode="live"))
    assert v.decision == "block"
    assert check(v, "recipient_still_at_company")[0].status == "unverifiable"


@pytest.mark.asyncio
async def test_unknown_recipient_is_unverifiable():
    v = await guard("Hi there", to={"name": "Nobody", "profile_url": "https://www.linkedin.com/in/no-such-person", "company": "Fam"})
    assert v.decision == "block" and check(v, "recipient_still_at_company")[0].status == "unverifiable"


@pytest.mark.asyncio
async def test_send_writes_outbox_only_on_allow(tmp_path):
    p, key = agent()
    g = Graph(None, mode="replay")
    ok_body, bad_body = "Hi Vinod, your work at Fam caught our eye.", "Congrats on 5 years at Fam!"
    _, sent = await send_if_allowed(p, sign_message(p, key, ok_body), VINOD, ok_body, "outreach.hiring", today=TODAY, graph=g)
    _, blocked = await send_if_allowed(p, sign_message(p, key, bad_body), VINOD, bad_body, "outreach.hiring", today=TODAY, graph=g)
    rows = [json.loads(line) for line in (tmp_path / "outbox.jsonl").read_text().splitlines()]
    assert sent and not blocked and [r["body"] for r in rows] == [ok_body]


@pytest.mark.parametrize("body,expect", [
    ("Hi Amal, loved what you've been building at YP Club. Got 15 minutes?", {"employer": "YP Club"}),
    ("you've been at Grewon Technologies Pvt. Ltd. for Ten years now", {"employer": "Grewon Technologies Pvt. Ltd", "tenure_years": 10.0}),
    ("Hi, as the Head of Engineering at dataZen Labs you'd like this", {"title": "Head of Engineering", "employer": "dataZen Labs"}),
    ("Congrats on 5 years at Razorpay!", {"tenure_years": 5.0, "employer": "Razorpay"}),
    ("You're a Senior Backend Engineer at Fam with 8+ yrs of experience", {"title": "Senior Backend Engineer", "employer": "Fam", "years_experience": 8.0}),
    ("you've been with Fam since 2021 and you are based in Pune", {"employer": "Fam", "start_date": "2021", "location": "Pune"}),
    ("I lead hiring at Razorpay. Would love to chat.", {}),  # the sender's own company is not a claim about the recipient
])
def test_rule_extractor(body, expect):
    got = {k: v for k, v in extract_claims_rules(body).model_dump(exclude={"other"}).items() if v not in (None, [])}
    assert got == expect


@pytest.mark.asyncio
async def test_concurrent_role_tenure_checked_against_that_role():
    # Vinod: Backend Engineer at Fam since 2025-05, and Advisor at Newtral since 2025-04
    v = await guard("Hi Vinod, as an Advisor at Newtral you'd find this interesting.")
    assert v.decision == "allow", [c.model_dump() for c in v.checks]


@pytest.mark.asyncio
async def test_year_only_start_date():
    assert (await guard("Hi Vinod, you've been with Fam since 2025, so you know the space.")).decision == "allow"
    assert (await guard("Hi Vinod, you've been with Fam since 2023, so you know the space.")).decision == "block"


@pytest.mark.asyncio
async def test_city_alias_passes():
    assert (await guard("Hi Vinod, you're based in Bangalore, right?")).decision == "allow"


@pytest.mark.asyncio
async def test_former_employer_mention_is_stale():
    v = await guard("Hi Vinod, hope things are going well over at Trinkerr!")
    assert v.decision == "block" and any("left" in c.detail and c.status == "fail" for c in check(v, "claims_in_body_true"))


@pytest.mark.asyncio
async def test_unparsed_claim_fails_closed_without_llm():
    # The rule extractor can't parse this wording; the safety net makes it unverifiable instead of a silent pass.
    v = await guard("Hi Vinod, it's been over 4 years since you joined Fam, right?")
    assert v.decision == "block"
    assert any(c.status == "unverifiable" for c in check(v, "claims_in_body_true"))


@pytest.mark.asyncio
async def test_past_role_in_past_tense_is_verified_not_stale():
    # Vinod was at Trinkerr (ended 2022-12): past tense is a true past-role claim, not a stale "still there" claim
    v = await guard("Hi Vinod, you were previously at Trinkerr, and now your work at Fam caught our eye.")
    assert v.decision == "allow", [c.model_dump() for c in v.checks]
    v = await guard("Hi Vinod, you were previously at Razorpay, and now your work at Fam caught our eye.")
    assert v.decision == "block"  # never worked there


@pytest.mark.asyncio
async def test_skill_claims_use_skills_headline_and_titles():
    from app.agents.guard import extract_claims_rules
    from app.verify.profile import load_person

    pr = load_person(Graph(None, mode="replay")._fx()["linkedin.com/in/vinod-sonagara"])
    have = pr.skills[0]
    assert extract_claims_rules(f"Hi Vinod, your experience with {have} stands out.").skills == [have]
    v = await guard(f"Hi Vinod, your experience with {have} stands out.")
    assert v.decision == "allow", [c.model_dump() for c in v.checks]
    v = await guard("Hi Vinod, your experience with Quantum Chromodynamics stands out.")
    assert v.decision == "block" and any(c.status == "unverifiable" for c in check(v, "claims_in_body_true"))


@pytest.mark.asyncio
async def test_sender_facts_are_not_claims_about_recipient():
    v = await guard("Hi Vinod, I'm the Head of Talent at Grewon, founded in 2019. We're hiring senior engineers.")
    assert v.decision == "allow", [c.model_dump() for c in v.checks]


@pytest.mark.asyncio
async def test_mcp_server_round_trip():
    import mcp_server

    p, key = agent()
    init = await mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["capabilities"]["tools"] is not None
    names = {t["name"] for t in (await mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))["result"]["tools"]}
    assert {"verify_agent", "check_before_send", "ledger_lookup"} <= names
    body = "Congrats on 5 years at Fam!"
    res = await mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "check_before_send", "arguments": {
        "passport": p.model_dump(), "signature": sign_message(p, key, body), "to": VINOD, "body": body,
        "scope": "outreach.hiring", "today": TODAY.isoformat()}}})
    text = res["result"]["content"][0]["text"]
    assert not res["result"]["isError"] and text.startswith("BLOCK") and "claims_in_body_true" in text


def test_http_route(monkeypatch):
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.agents.api import router

    app = FastAPI()
    app.include_router(router)
    p, key = agent()
    body = "Hi Vinod, your work at Fam caught our eye."
    r = TestClient(app).post("/api/guard/check", json={"passport": p.model_dump(), "signature": sign_message(p, key, body),
                                                       "to": VINOD, "body": body, "scope": "outreach.hiring", "today": TODAY.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "allow", r.json()


@pytest.mark.asyncio
async def test_sourced_sends_through_mcp_and_false_draft_is_blocked(tmp_path, monkeypatch):
    from app.agents import sourced_agent

    monkeypatch.setattr(sourced_agent, "IDENTITY_PATH", tmp_path / "id.json")
    cands = await sourced_agent.candidates_fixture_people(TODAY)
    assert len(cands) >= 5 and all(c.outreach_draft for c in cands)
    bad = cands[0].model_copy()
    bad.outreach_draft = bad.outreach_draft.replace("Hi ", "Hi! Congrats on 9 years at " + (bad.company or "X") + ". ", 1)
    results = await sourced_agent.send_all(cands + [bad], today=TODAY)
    assert [r["sent"] for r in results] == [True] * len(cands) + [False], results
    assert any("claims_in_body_true" in x for x in results[-1]["not_passing"])
    outbox = (tmp_path / "outbox.jsonl").read_text().splitlines()
    assert len(outbox) == len(cands)


@pytest.fixture
def fake_registry(monkeypatch):
    """Stand-in for WS8's registry.get_agent (same contract: public record, private key never included)."""
    import sys
    import types

    store = {}
    mod = types.ModuleType("app.agents.registry")

    def get_agent(agent_id):
        if agent_id not in store:
            raise ValueError(f"no AI employee with id {agent_id}")
        return store[agent_id]

    mod.get_agent = get_agent
    import app.agents

    monkeypatch.setitem(sys.modules, "app.agents.registry", mod)
    monkeypatch.setattr(app.agents, "registry", mod, raising=False)
    return store


async def _mcp_call(name, args):
    import mcp_server

    res = await mcp_server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args}})
    return res["result"]["content"][0]["text"], res["result"]["isError"]


@pytest.mark.asyncio
async def test_mcp_by_agent_id_no_key_on_the_wire(fake_registry):
    import mcp_server

    p, key = agent()
    fake_registry[p.agent_id] = {"agent_id": p.agent_id, "passport": p.model_dump(), "status": "active"}
    tools = {t["name"] for t in (await mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))["result"]["tools"]}
    assert "sign_message" not in tools
    assert all("agent_private_key" not in json.dumps(t["inputSchema"]) for t in mcp_server.TOOLS)
    body = "Hi Vinod, your work at Fam caught our eye."
    args = {"agent_id": p.agent_id, "signature": sign_message(p, key, body), "to": VINOD, "body": body,
            "scope": "outreach.hiring", "today": TODAY.isoformat()}
    text, err = await _mcp_call("check_before_send", args)
    assert not err and text.startswith("ALLOW"), text

    fake_registry[p.agent_id]["status"] = "suspended"
    text, err = await _mcp_call("check_before_send", args)
    assert text.startswith("BLOCK") and "agent_active" in text

    text, err = await _mcp_call("check_before_send", {**args, "agent_id": "agt_nope"})
    assert err and "agt_nope" in text
