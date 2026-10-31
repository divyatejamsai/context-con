import json
from datetime import date
from pathlib import Path

import pytest

from app.schemas import Criteria
from app.verify.ranker import rank_candidate
from app.verify.verifier import verify_candidate

FX = Path(__file__).parent / "verify_fixtures"
PEOPLE = json.loads((FX / "people.json").read_text())
COMPANIES = json.loads((FX / "companies.json").read_text())
TODAY = date(2026, 10, 31)

CRIT = Criteria(
    role="Senior Backend Engineer", title_variants=["Backend Engineer", "Software Engineer", "SDE"],
    seniority="senior", skills=["Payments", "Go"], locations=["Bangalore"],
    company_preferences=["ex-startup"], must_haves=[], nice_to_haves=[], raw_brief="need a senior backend eng, payments, blr, ex-startup",
)


class CrustdataError(Exception):
    pass


class FakeClient:
    def __init__(self, web=None, fail=False):
        self.web, self.fail, self.calls = web or [], fail, []

    async def company_enrich(self, company_id=None, domain=None):
        self.calls.append(("company_enrich", company_id))
        if self.fail:
            raise CrustdataError("boom")
        return COMPANIES.get(str(company_id))

    async def company_identify(self, name=None, domain=None):
        self.calls.append(("company_identify", name))
        return None

    async def web_search(self, query):
        self.calls.append(("web_search", query))
        if self.fail:
            raise CrustdataError("boom")
        return self.web


def by_status(claims, s):
    return [c for c in claims if c.status == s]


async def run(key, client=None, company="auto"):
    p = PEOPLE[key]
    client = client or FakeClient()
    claims, flags = await verify_candidate(p, None if company == "auto" else company, CRIT, client, today=TODAY)
    score, reasons = await rank_candidate(p, claims, CRIT)
    return claims, flags, score, reasons


def assert_contract(claims, reasons):
    ids = {c.id for c in claims}
    assert len(ids) == len(claims)
    for c in claims:
        assert c.source.endpoint
    for r in reasons:
        assert r.claim_ids and set(r.claim_ids) <= ids


@pytest.mark.asyncio
async def test_clean_candidate_all_verified_and_high_score():
    claims, flags, score, reasons = await run("clean")
    assert_contract(claims, reasons)
    assert not by_status(claims, "contradicted")
    assert any("Razorpay" in c.claim and c.status == "verified" for c in claims)
    assert any(c.source.endpoint == "company/enrich" for c in claims)
    assert flags == []
    assert score >= 70


@pytest.mark.asyncio
async def test_recent_job_change_flagged_and_stale_headline_contradicted():
    claims, flags, score, reasons = await run("moved")
    assert_contract(claims, reasons)
    assert flags[0].startswith("Changed jobs 3 weeks ago")
    emp = [c for c in claims if c.claim == "Works at Paytm"][0]
    assert emp.status == "contradicted" and "CRED" in emp.evidence
    assert any("out of date" in f for f in flags)


@pytest.mark.asyncio
async def test_seeded_fake_is_caught_and_ranked_low():
    claims, flags, score, reasons = await run("fake")
    assert_contract(claims, reasons)
    bad = {c.claim for c in by_status(claims, "contradicted")}
    assert "Works at Stripe" in bad
    assert "Title: Staff Engineer" in bad
    assert "12 yrs of experience" in bad
    assert "Based in Bangalore" in bad
    assert reasons[0].text.startswith("Red flag")
    clean_score = (await run("clean"))[2]
    assert score < clean_score - 30


@pytest.mark.asyncio
async def test_sparse_profile_unverifiable_not_invented():
    web_hit = [{"title": "Unknown Person - Engineer at Zeta", "url": "https://zeta.tech/team", "snippet": "Unknown Person, Zeta"}]
    claims, flags, score, reasons = await run("sparse", FakeClient(web=web_hit))
    assert_contract(claims, reasons)
    emp = claims[0]
    assert emp.status == "verified" and emp.source.endpoint == "web/search" and emp.source.url == "https://zeta.tech/team"
    claims, _, _, _ = await run("sparse", FakeClient(web=[]))
    assert claims[0].status == "unverifiable"
    assert not by_status(claims, "contradicted")


@pytest.mark.asyncio
async def test_api_failures_degrade_to_unverifiable():
    claims, flags, score, reasons = await run("clean", FakeClient(fail=True))
    assert_contract(claims, reasons)
    stage = [c for c in claims if "stage/size" in c.claim][0]
    assert stage.status == "unverifiable"


@pytest.mark.asyncio
async def test_nested_shape_parsed():
    claims, flags, score, reasons = await run("nested")
    assert_contract(claims, reasons)
    texts = " | ".join(c.claim for c in claims)
    assert "Works at Jupiter" in texts and "Bengaluru" in texts and "Skill: Payments" in texts
    assert any("startup" in r.text for r in reasons)


@pytest.mark.asyncio
async def test_garbage_input_never_raises():
    for person in ({}, {"current_employers": "oops", "skills": None}, {"current_employers": [None, {"start_date": "n/a"}]}):
        claims, flags = await verify_candidate(person, None, CRIT, None, today=TODAY)
        score, reasons = await rank_candidate(person, claims, CRIT)
        assert 0 <= score <= 100
        assert_contract(claims, reasons)


@pytest.mark.asyncio
async def test_live_crustdata_shape():
    claims, flags, score, reasons = await run("live_shape")
    assert_contract(claims, reasons)
    t = {c.claim: c for c in claims}
    assert t["Works at Setu"].source.field == "experience.employment_details.current[0]"
    # seniority_level "Senior" backs the claimed senior title, so it is not an inflation
    assert not by_status(claims, "contradicted")
    stage = [c for c in claims if c.claim.startswith("Setu:")][0]
    assert "Series A" in stage.claim and "~180 employees" in stage.claim and "early stage" in stage.claim
    assert stage.source.field == "funding.last_round_type"
    assert flags[0].startswith("Changed jobs 6 weeks ago")


def test_google_redirect_unwrapped():
    from app.verify.profile import unwrap_url
    assert unwrap_url("https://www.google.com/url?q=https://zeta.tech/team%3Fa%3D1&sa=U&ved=x") == "https://zeta.tech/team?a=1"
    assert unwrap_url("https://zeta.tech/team") == "https://zeta.tech/team"
    assert unwrap_url(None) is None


@pytest.mark.asyncio
async def test_web_citation_uses_unwrapped_url():
    hit = [{"title": "Unknown Person at Zeta", "url": "https://www.google.com/url?q=https://zeta.tech/team&sa=U", "snippet": ""}]
    claims, *_ = await run("sparse", FakeClient(web=hit))
    assert claims[0].source.url == "https://zeta.tech/team"


@pytest.mark.asyncio
async def test_real_company_enrich_fixture():
    """WS1's live Razorpay response: last_round_type is secondary_market, so stage comes from milestones."""
    company = json.loads((FX / "company_enrich_live.json").read_text())
    claims, flags = await verify_candidate(PEOPLE["clean"], company, CRIT, FakeClient(), today=TODAY)
    stage = [c for c in claims if c.claim.startswith("Razorpay:")][0]
    assert stage.status == "verified"
    assert "Series F" in stage.claim and "~4,027 employees" in stage.claim and "founded 2014" in stage.claim
    assert stage.source.field == "funding.milestones[1].round_type"


@pytest.mark.asyncio
async def test_real_person_shape_details():
    """Shapes seen in WS1's real Person Enrich data: '(Programming Language)' skills, job-level company size, seniority_level."""
    claims, flags, score, reasons = await run("live_job_facts")
    assert_contract(claims, reasons)
    t = {c.claim: c for c in claims}
    assert t["Skill: Go"].status == "verified" and "Go (Programming Language)" in t["Skill: Go"].evidence
    pay = t["Skill: Payments"]  # a domain, evidenced by the employer's industry
    assert pay.status == "verified" and "Financial Services" in pay.evidence
    assert pay.source.field == "experience.employment_details.current[0].company_professional_network_industry"
    assert t["Title: Backend Engineer (Senior)"].status == "verified"
    co = [c for c in claims if c.claim.startswith("Acme Pay:")][0]
    assert "~120 employees" in co.claim and co.source.field.endswith("company_headcount_latest")
    exp = [c for c in claims if c.claim.endswith("of experience")][0]
    assert exp.source.field == "experience.employment_details.past[0].start_date"
    assert not any("below the senior level" in r.text for r in reasons)


@pytest.mark.asyncio
async def test_raw_cached_response_is_unwrapped():
    raw = {"endpoint": "person/enrich", "response": [{"matched_on": "x", "matches": [{"confidence_score": 1, "person_data": PEOPLE["live_job_facts"]}]}]}
    claims, _ = await verify_candidate(raw, None, CRIT, FakeClient(), today=TODAY)
    assert claims[0].claim == "Works at Acme Pay"


@pytest.mark.asyncio
async def test_domain_skill_not_invented_and_concurrent_roles_deduped():
    p = json.loads(json.dumps(PEOPLE["live_job_facts"]))
    cur = p["experience"]["employment_details"]["current"]
    cur[0].update(name="Wipro", company_professional_network_industry="IT Services and IT Consulting", company_description="IT services")
    cur.append(dict(cur[0], title="Tech Lead"))
    claims, flags = await verify_candidate(p, None, CRIT, FakeClient(), today=TODAY)
    assert not any("concurrent" in f for f in flags)
    assert any(c.claim.startswith("Skills not evidenced") and "Payments" in c.claim for c in claims)
    cur.append(dict(cur[0], name="Razorpay", crustdata_company_id=1, company_professional_network_industry="Financial Services"))
    claims, flags = await verify_candidate(p, None, CRIT, FakeClient(), today=TODAY)
    assert any(f.startswith("Holds 2 concurrent roles: Wipro, Razorpay") for f in flags)
    assert [c for c in claims if c.claim == "Skill: Payments"][0].evidence == "current employer Razorpay is in Financial Services"
