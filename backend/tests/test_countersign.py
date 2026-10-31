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
