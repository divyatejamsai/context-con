"""WS8 registry tests. Most fake the sponsor check (verify_passport has its own tests in test_countersign.py) to
cover the registry's rules: role ceilings, fail-closed suspension, reinstate only on a pass, scope changes, reviews.
The last ones run the real verify_passport offline on WS6's demo sponsors (fixtures/countersign/sponsors.json).
"""
import json
from pathlib import Path

import pytest

from app.agents import ledger, registry
from app.agents.models import Check, Sponsor, Verdict
from app.schemas import Source

SCENARIOS = {s["id"]: s for s in json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}

PRIYA = Sponsor(name="Priya Rao", profile_url="https://linkedin.com/in/priya", company="Razorpay",
                company_domain="razorpay.com", title="Head of Talent")
SRC = Source(endpoint="person/enrich", field="experience.employment_details.past[0].end_date")


class FakeSponsors:
    """verify_passport stand-in: `left` = sponsor no longer employed; `junior` = can't grant these scopes."""

    def __init__(self):
        self.left, self.junior, self.calls = set(), set(), []

    async def __call__(self, p, client, scope=None, *, today=None):
        self.calls.append((p.agent_id, scope))
        rev = ledger.is_revoked(p.agent_id)
        checks = [Check(id="c1", name="not_revoked", status="fail" if rev else "pass", detail="ledger")]
        if p.sponsor.profile_url in self.left:
            checks.append(Check(id="c2", name="sponsor_still_employed", status="fail",
                                detail=f"{p.sponsor.name} left {p.sponsor.company} on 2026-10-02", source=SRC))
        for s in ([scope] if scope else p.scopes):
            if s in self.junior:
                checks.append(Check(id="c3", name="sponsor_can_grant_scope", status="fail",
                                    detail=f"{p.sponsor.title} can't grant {s}", source=SRC))
        ok = all(c.status == "pass" for c in checks)
        return Verdict(subject=p.agent_id, decision="allow" if ok else "block", checks=checks)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTS_PATH", str(tmp_path / "agents.json"))
    monkeypatch.setenv("LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("ISSUER_KEY_PATH", str(tmp_path / "issuer.key"))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")


@pytest.fixture
def fake(monkeypatch):
    f = FakeSponsors()
    monkeypatch.setattr(registry.pp, "verify_passport", f)
    return f


def test_onboard_uses_role_defaults_and_numbers_employees(fake):
    a = registry.onboard("Sourced", "AI Recruiter", PRIYA)
    b = registry.onboard("Scout", "analyst", PRIYA)
    assert a["passport"]["scopes"] == ["outreach.hiring", "data.read"]
    assert a["role"] == "AI Recruiter" and a["status"] == "active"
    assert [x["employee_no"] for x in registry.list_agents()] == [1, 2]
    assert b["passport"]["scopes"] == ["data.read"]
    assert "private_key" not in a and registry.private_key(a["agent_id"])


def test_role_ceiling_blocks_out_of_role_scopes(fake):
    with pytest.raises(registry.RegistryError, match="role ceiling"):
        registry.onboard("Sourced", "recruiter", PRIYA, ["outreach.hiring", "payment.send"])


@pytest.mark.asyncio
async def test_payroll_run_suspends_agent_whose_sponsor_left(fake):
    a = registry.onboard("Sourced", "recruiter", PRIYA)
    ghost = Sponsor(**{**PRIYA.model_dump(), "name": "Arjun", "profile_url": "https://linkedin.com/in/arjun"})
    b = registry.onboard("Sourced-2", "recruiter", ghost)
    fake.left.add(ghost.profile_url)

    verdicts = await registry.recheck_all(client=None)

    assert [v.decision for v in verdicts] == ["allow", "block"]
    assert all(v.ledger_entry for v in verdicts)
    assert registry.get_agent(a["agent_id"])["status"] == "active"
    gone = registry.get_agent(b["agent_id"])
    assert gone["status"] == "suspended" and gone["suspended_by"] == "payroll"
    assert "sponsor_still_employed" in gone["reason"] and "2026-10-02" in gone["reason"]
    assert gone["last_verdict"]["checks"][1]["source"]["endpoint"] == "person/enrich"
    assert ledger.is_revoked(b["agent_id"]) and not ledger.is_revoked(a["agent_id"])


@pytest.mark.asyncio
async def test_unverifiable_fails_closed(fake, monkeypatch):
    a = registry.onboard("Sourced", "recruiter", PRIYA)

    async def down(p, client, scope=None, *, today=None):
        return Verdict(subject=p.agent_id, decision="block", checks=[
            Check(id="c1", name="sponsor_exists", status="unverifiable", detail="Crustdata timed out")])

    monkeypatch.setattr(registry.pp, "verify_passport", down)
    await registry.recheck(a["agent_id"], None)
    got = registry.get_agent(a["agent_id"])
    assert got["status"] == "suspended" and got["reason"].startswith("couldn't verify sponsor_exists")


@pytest.mark.asyncio
async def test_pass_does_not_lift_suspension_but_reinstate_does(fake):
    a = registry.onboard("Sourced", "recruiter", PRIYA)
    registry.suspend(a["agent_id"], "sent a wrong email")
    await registry.recheck(a["agent_id"], None)
    assert registry.get_agent(a["agent_id"])["status"] == "suspended"

    fake.left.add(PRIYA.profile_url)
    agent, v = await registry.reinstate(a["agent_id"], None)
    assert v.decision == "block" and agent["status"] == "suspended"

    fake.left.clear()
    agent, v = await registry.reinstate(a["agent_id"], None)
    assert v.decision == "block"  # still revoked at check time; everything else passed
    assert agent["status"] == "active" and agent["reason"] is None and not ledger.is_revoked(a["agent_id"])


@pytest.mark.asyncio
async def test_widening_scopes_needs_sponsor_authority(fake):
    a = registry.onboard("Buyer", "procurement", PRIYA)
    fake.junior.add("contract.sign")
    with pytest.raises(registry.ScopeDenied, match="contract.sign") as e:
        await registry.set_scopes(a["agent_id"], ["data.read", "contract.sign"], None)
    assert e.value.verdict.decision == "block"
    assert registry.get_agent(a["agent_id"])["passport"]["scopes"] == ["data.read"]

    fake.junior.clear()
    agent, v = await registry.set_scopes(a["agent_id"], ["data.read", "contract.sign"], None)
    assert v.decision == "allow" and agent["passport"]["scopes"] == ["data.read", "contract.sign"]
    assert agent["agent_id"] == a["agent_id"]
    assert fake.calls[-1] == (a["agent_id"], "contract.sign")


@pytest.mark.asyncio
async def test_narrowing_skips_live_check(fake):
    a = registry.onboard("Sourced", "recruiter", PRIYA)
    agent, v = await registry.set_scopes(a["agent_id"], ["data.read"], None)
    assert v is None and agent["passport"]["scopes"] == ["data.read"] and not fake.calls


@pytest.mark.asyncio
async def test_review_snapshots_scorecard_and_applies_decision(fake):
    a = registry.onboard("Sourced", "recruiter", PRIYA)
    aid = a["agent_id"]
    ledger.append("guard.verdict", {"agent_id": aid, "decision": "allow", "checks": []})
    ledger.append("guard.verdict", {"agent_id": aid, "decision": "block", "checks": [
        {"name": "claims_in_body_true", "status": "fail"}]})

    card = registry.scorecard(aid)
    assert (card["messages_checked"], card["allowed"], card["blocked"]) == (2, 1, 1)
    assert card["block_reasons"] == [("claims_in_body_true", 1)]

    agent = await registry.add_review(aid, "Priya", "restrict", "one false claim", scopes=["data.read"])
    assert agent["passport"]["scopes"] == ["data.read"]
    assert agent["reviews"][0]["scorecard"]["blocked"] == 1

    agent = await registry.add_review(aid, "Priya", "offboard", "replaced")
    assert agent["status"] == "offboarded"
    with pytest.raises(registry.RegistryError):
        await registry.recheck(aid, None)


# ---- real verify_passport, offline on fixtures --------------------------------------------------

def sponsor(sid):
    return Sponsor(**SCENARIOS[sid]["sponsor"])


@pytest.mark.asyncio
async def test_payroll_run_on_fixtures_suspends_departed_sponsor():
    ok = registry.onboard("Sourced", "recruiter", sponsor("authorised_founder"))
    left = registry.onboard("Sourced (old sponsor)", "recruiter", sponsor("sponsor_left"), ["outreach.hiring"])

    verdicts = await registry.recheck_all(client=None)

    assert [v.decision for v in verdicts] == ["allow", "block"], [c.model_dump() for c in verdicts[0].checks]
    gone = registry.get_agent(left["agent_id"])
    assert gone["status"] == "suspended" and gone["reason"].startswith("sponsor_still_employed: Left PulseTrader")
    assert registry.get_agent(ok["agent_id"])["status"] == "active"
    assert ledger.verify_chain() == (True, None)
    assert registry.scorecard(ok["agent_id"])["sponsor_checks"] == 1


@pytest.mark.asyncio
async def test_junior_sponsor_cannot_grant_contract_signing_on_fixtures():
    a = registry.onboard("Buyer", "procurement", sponsor("junior_sponsor"))
    assert (await registry.recheck(a["agent_id"], None)).decision == "allow"
    with pytest.raises(registry.ScopeDenied, match="cannot delegate contract.sign"):
        await registry.set_scopes(a["agent_id"], ["data.read", "contract.sign"], None)
    assert registry.get_agent(a["agent_id"])["passport"]["scopes"] == ["data.read"]
