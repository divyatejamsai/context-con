"""Countersign WS6: passport + ledger. Runs offline on the committed fixtures."""
import json
from datetime import date
from pathlib import Path

import pytest

from app.agents import ledger
from app.agents.graph import Graph
from app.agents.models import Sponsor
from app.agents.passport import (can_grant, issue_passport, revoke, sign_message, verify_message_signature,
                                 verify_passport)

SCENARIOS = json.loads((Path(__file__).resolve().parents[2] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]
TODAY = date(2026, 10, 31)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("ISSUER_KEY_PATH", str(tmp_path / "issuer.key"))


def offline():
    return Graph(None, mode="replay")


@pytest.mark.asyncio
@pytest.mark.parametrize("sc", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
async def test_scenarios(sc):
    p, _ = issue_passport("Sourced", "AI recruiter", Sponsor(**sc["sponsor"]), sc["scopes"])
    v = await verify_passport(p, graph=offline(), today=TODAY)
    assert v.decision == sc["expect"], [c.model_dump() for c in v.checks]
    assert all(c.source is not None for c in v.checks)
    if sc.get("failing_check"):
        assert any(c.name == sc["failing_check"] and c.status == "fail" for c in v.checks)
    assert v.ledger_entry


@pytest.mark.asyncio
async def test_edited_passport_fails_signature():
    sc = SCENARIOS[0]
    p, _ = issue_passport("Sourced", "AI recruiter", Sponsor(**sc["sponsor"]), ["outreach.hiring"])
    p.scopes.append("payment.send")  # agent tries to grant itself more power
    v = await verify_passport(p, graph=offline(), today=TODAY)
    assert v.decision == "block"
    assert next(c for c in v.checks if c.name == "signature_valid").status == "fail"


@pytest.mark.asyncio
async def test_scope_not_in_passport_and_revocation():
    sc = SCENARIOS[0]
    p, _ = issue_passport("Sourced", "AI recruiter", Sponsor(**sc["sponsor"]), ["outreach.hiring"])
    v = await verify_passport(p, scope="payment.send", graph=offline(), today=TODAY)
    assert next(c for c in v.checks if c.name == "scope_in_passport").status == "fail"
    assert (await verify_passport(p, scope="outreach.hiring", graph=offline(), today=TODAY)).decision == "allow"
    revoke(p.agent_id, "sponsor asked")
    v = await verify_passport(p, scope="outreach.hiring", graph=offline(), today=TODAY)
    assert v.decision == "block" and next(c for c in v.checks if c.name == "not_revoked").status == "fail"


@pytest.mark.asyncio
async def test_unknown_sponsor_and_lookup_error_fail_closed():
    s = Sponsor(name="Nobody", profile_url="https://www.linkedin.com/in/does-not-exist", company="Acme")
    p, _ = issue_passport("X", "bot", s, ["data.read"])
    v = await verify_passport(p, graph=offline(), today=TODAY)
    assert v.decision == "block"

    class Boom:
        mode = "live"
        async def person_enrich(self, url):
            raise TimeoutError
    v = await verify_passport(p, graph=Graph(Boom()), today=TODAY)
    assert v.decision == "block" and next(c for c in v.checks if c.name == "sponsor_exists").status == "unverifiable"


def test_message_signature():
    p, key = issue_passport("X", "bot", Sponsor(**SCENARIOS[0]["sponsor"]), ["outreach.hiring"])
    sig = sign_message(p, key, "hello")
    assert verify_message_signature(p, "hello", sig)
    assert not verify_message_signature(p, "hello!", sig)


def test_authority_rules():
    assert can_grant("Head of Talent Acquisition", "outreach.hiring")
    assert can_grant("Senior Technical Recruiter", "outreach.hiring")
    assert not can_grant("Backend Engineer", "outreach.hiring")
    assert can_grant("VP Engineering", "contract.sign")
    assert not can_grant("Advisor", "contract.sign")
    assert can_grant("Chief Financial Officer", "payment.send")
    assert can_grant("Intern", "data.read")


def test_ledger_chain_detects_tampering():
    for i in range(4):
        ledger.append("test", {"i": i})
    assert ledger.verify_chain() == (True, None)
    path = ledger.path()
    lines = path.read_text().splitlines()
    row = json.loads(lines[2]); row["payload"]["i"] = 99
    lines[2] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n")
    assert ledger.verify_chain() == (False, 2)


def test_ledger_detects_deleted_line():
    for i in range(3):
        ledger.append("test", {"i": i})
    lines = ledger.path().read_text().splitlines()
    ledger.path().write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert ledger.verify_chain() == (False, 1)


def test_title_matching_regressions_from_live_eval():
    from app.agents.passport import title_matches
    assert not title_matches("Chief Executive Officer", "Chief Technology Officer")
    assert not title_matches("CEO", "CFO")
    assert not title_matches("Chief Operating Officer", "Chief Executive Officer")
    assert not title_matches("Senior Engineer", "Engineer")
    assert title_matches("Finance controller", "Financial Controller")
    assert title_matches("VP Engineering", "Vice President, Engineering")
    assert title_matches("Director of Engineering", "Senior Director of Engineering")  # understating is allowed


@pytest.mark.asyncio
async def test_multiple_roles_at_one_company_and_loose_company_names():
    rec = {"basic_profile": {"name": "Asha Rao"},
           "social_handles": {"professional_network_identifier": {"profile_url": "https://www.linkedin.com/in/asha-rao-x"}},
           "experience": {"employment_details": {"current": [
               {"title": "Data Engineer", "name": "Tata Technologies", "employer_company_website_domain": "tatatechnologies.com", "start_date": "2025-06-01"},
               {"title": "Chief Technology Officer", "name": "Acme", "employer_company_website_domain": "acme.com", "start_date": "2020-01-01"},
               {"title": "VP & Head of Engineering", "name": "Acme", "employer_company_website_domain": "acme.com", "start_date": "2019-01-01"},
               {"title": "Data Analyst", "name": "Tata Motors", "employer_company_website_domain": "tatamotors.com", "start_date": "2024-01-01"}],
               "past": []}}}

    class G(Graph):
        async def person(self, url):
            return rec
    g = G(None, mode="replay")
    url = "https://www.linkedin.com/in/asha-rao-x"
    ok = Sponsor(name="Asha Rao", profile_url=url, company="Acme", company_domain="acme.com", title="VP & Head of Engineering")
    p, _ = issue_passport("X", "bot", ok, ["outreach.hiring"])
    assert (await verify_passport(p, graph=g, today=TODAY)).decision == "allow"
    ceo = ok.model_copy(update={"title": "Chief Executive Officer"})
    p, _ = issue_passport("X", "bot", ceo, ["outreach.hiring"])
    assert (await verify_passport(p, graph=g, today=TODAY)).decision == "block"
    tata = Sponsor(name="Asha Rao", profile_url=url, company="Tata Motors", company_domain="tatamotors.com", title="Data Analyst")
    p, _ = issue_passport("X", "bot", tata, ["data.read"])
    assert (await verify_passport(p, graph=g, today=TODAY)).decision == "allow"


def test_title_roles_dont_mix_round2():
    from app.agents.passport import can_grant, title_matches
    assert not title_matches("Chief Executive Officer", "COO and Account Executive")
    assert not title_matches("CFO", "Head of Finance and COO")
    assert not title_matches("CTO", "Chief Product and Technology Officer")
    assert title_matches("COO", "COO, Account Executive")
    assert title_matches("Co-Founder and Finance Controller", "Co-Founder & Finance Controller")
    assert can_grant("Chief Product and Technology Officer", "outreach.hiring")
    assert can_grant("Manager - IT - Engineering", "outreach.hiring")
    assert not can_grant("Software Engineer", "outreach.hiring")


def test_admin_token_guards_mutating_routes(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("COUNTERSIGN_ADMIN_TOKEN", "s3cret")
    c = TestClient(app)
    body = {"agent_name": "X", "role": "bot", "sponsor": SCENARIOS[0]["sponsor"], "scopes": ["data.read"]}
    assert c.post("/api/passport/issue", json=body).status_code == 401
    assert c.post("/api/passport/revoke", json={"agent_id": "a", "reason": "r"}, headers={"x-admin-token": "nope"}).status_code == 401
    r = c.post("/api/passport/issue", json=body, headers={"x-admin-token": "s3cret"})
    assert r.status_code == 200
    assert c.post("/api/passport/verify", json={"passport": r.json()["passport"]}).status_code == 200  # verify stays public


def test_assistants_interns_and_former_execs_carry_no_authority_round3():
    from app.agents.passport import can_grant, title_matches
    for t, sc in [("Executive Assistant to Chief Financial Officer (CFO)", "payment.send"),
                  ("Executive Assistant to the Chief Financial and Operating Officer", "payment.send"),
                  ("Intern, Office of the CEO", "contract.sign"), ("Founder's Office Associate", "contract.sign"),
                  ("Chief of Staff to CFO", "payment.send"), ("Finance Intern", "payment.send"), ("Ex-CFO", "payment.send")]:
        assert not can_grant(t, sc), t
    assert can_grant("Cofounder - Data Analyst", "contract.sign")
    for claimed, real in [("President", "Vice President"), ("CFO", "Former CFO"), ("CEO", "CEO Office Intern"),
                          ("VP Sales", "AVP Sales"), ("Director of Engineering", "Associate Director of Engineering"),
                          ("Head of Sales", "Assistant to Head of Sales")]:
        assert not title_matches(claimed, real), (claimed, real)
    assert title_matches("Engineer", "Staff Engineer")
