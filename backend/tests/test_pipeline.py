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


def test_domain_terms_shape_search_from_first_step():
    from app.orchestrator import domain_terms, to_crustdata_filters
    c = heuristic_parse("senior backend engineer, payments experience, Bangalore")
    c.must_haves = ["payments experience"]
    assert domain_terms(c)[0] == "payments"
    client = RealShaped()
    collect("senior backend engineer, payments experience, Bangalore", client=client)
    first_level = [f for f, _ in client.calls["search"]]
    flat = json.dumps(first_level)
    assert "skills.professional_network_skills" in flat and "basic_profile.headline" in flat
    f = to_crustdata_filters({"titles": ["Backend Engineer"], "locations": [], "domain": ["payments"]})
    assert f["op"] == "and" and f["conditions"][1]["op"] == "or"


def test_domain_match_is_prescored_first():
    from app.orchestrator import prescore
    c = heuristic_parse("backend engineer payments")
    a = {"title": "Backend Engineer"}
    b = {"title": "Backend Engineer", "_domain_match": True}
    assert prescore(b, c) > prescore(a, c)


def test_non_hiring_text_stops_cleanly():
    evs = collect("what's the weather in Mumbai")
    assert not any(e.type == "candidate" for e in evs)
    assert any(e.type == "error" and "hiring brief" in e.message for e in evs)
    assert evs[-1].type == "done" and evs[-1].summary.shortlisted == 0


def test_vague_brief_shows_assumptions():
    evs = collect("someone good at ML for our team")
    msgs = [e.message for e in evs if e.type == "step" and e.step == "parse"]
    assert any(m.startswith("Assumptions:") and "No location given" in m for m in msgs)


def test_broaden_widens_city_to_country_before_dropping():
    c = heuristic_parse("staff rust engineer in pune")
    steps = [d for d, _ in broaden_ladder(c)]
    i = next(i for i, d in enumerate(steps) if d.startswith("widened"))
    assert "India" in steps[i] and i < steps.index("dropped location")


def test_shortlist_threshold_and_timings(monkeypatch):
    import app.orchestrator as o
    monkeypatch.setattr(o, "SHORTLIST_MIN", 101)
    evs = collect("senior backend engineer bangalore payments")
    cands = [e.candidate for e in evs if e.type == "candidate"]
    assert cands and all(c.outreach_draft is None for c in cands)
    s = evs[-1].summary
    assert s.shortlisted == 0 and s.elapsed_ms >= 0 and "search" in s.timings_ms


def test_series_stage_heuristic():
    c = heuristic_parse("lookin for a foundng AE, sereis A-B stage companies ideally")
    assert any("Series A-B" in p for p in c.company_preferences)


def test_enforce_seniority_and_normalise_terms():
    from app.brief import enforce_seniority, normalise_terms
    c = Criteria(role="Backend Engineer", seniority="senior",
                 title_variants=["Backend Engineer", "SDE II", "SDE III", "API Engineer", "Staff Engineer"],
                 skills=["Payments", "Python"], must_haves=["Payments experience", "knowledge of Kafka"])
    c = enforce_seniority(normalise_terms(c))
    assert c.role == "Senior Backend Engineer"
    assert "SDE II" not in c.title_variants and "SDE III" in c.title_variants
    assert "Senior API Engineer" in c.title_variants and "Staff Engineer" in c.title_variants
    assert c.must_haves == ["kafka"]


def test_outreach_template_signs_with_placeholder():
    from app.outreach import template_draft
    c = Candidate(id="c1", name="Ananya Rao", title="Engineer", company="X")
    assert template_draft(c, Criteria(role="Engineer")).endswith("[Your name]")


def test_template_profile_fills_criteria_and_is_excluded():
    evs = collect("find me someone like https://www.linkedin.com/in/dev-karthik-menon/")
    tmpl = [e for e in evs if e.type == "step" and e.data and "template" in e.data]
    assert tmpl and "Karthik Menon" in tmpl[0].message
    cands = [e.candidate for e in evs if e.type == "candidate"]
    assert all("karthik" not in (c.profile_url or "") for c in cands)
    assert evs[-1].type == "done"


def test_qa_review_items():
    from app.orchestrator import domain_terms
    from app.outreach import template_draft
    from app.schemas import Claim, Reason, Source
    # 3: languages are not domain terms
    c = Criteria(role="Backend Engineer", skills=["Payments", "Python", "Go"], must_haves=[])
    assert domain_terms(c) == ["payments"]
    # 2: seniority-only differences don't produce duplicate ladder steps
    steps = broaden_ladder(Criteria(role="Staff Engineer", title_variants=["Staff Engineer"], seniority="staff", locations=["Pune"]))
    keys = [json.dumps({k: v for k, v in f.items() if k != "seniority"}, sort_keys=True) for _, f in steps]
    assert len(keys) == len(set(keys))
    # 5: template hook never uses scoring text
    cand = Candidate(id="c1", name="A B", title="Eng", company="X",
                     reasons=[Reason(text="6 of 6 claims verified against Crustdata", claim_ids=["k1"])],
                     claims=[Claim(id="k1", claim="Works at X since 2021", status="verified", evidence="e",
                                   source=Source(endpoint="person/enrich"))])
    d = template_draft(cand, Criteria(role="Eng"))
    assert "claims verified" not in d and "works at X since 2021" in d


def test_identify_fallback_uses_real_keys():
    from app.orchestrator import enrich

    class C(RealShaped):
        def __init__(self):
            super().__init__()
            self.enriched_with = None

        async def company_identify(self, name=None, domain=None):
            return {"crustdata_company_id": 77, "basic_info": {"name": "Acme", "primary_domain": "acme.com"}}

        async def company_enrich(self, company_id=None, domain=None, fields=None):
            self.enriched_with = (company_id, domain)
            return {"basic_info": {"name": "Acme"}}

    client = C()
    p = {"basic_profile": {"name": "X"}, "experience": {"employment_details": {"current": [{"title": "Eng", "name": "Acme"}]}}}
    asyncio.run(enrich(client, p, pre={}))
    assert client.enriched_with == (77, "acme.com")


def test_heuristic_remote_country_and_new_roles():
    c = heuristic_parse("need a senior backend eng, blr or remote india, payments, upi")
    assert "Bangalore" in c.locations and "India" in c.locations and "upi" in c.skills
    assert heuristic_parse("Staff Rust engineer in Pune").role.endswith("Rust Engineer")


def test_live_eval_round_fixes():
    from app.brief import brief_domain_words, keep_function, years_asked
    from app.orchestrator import domain_terms
    b1 = "need a senior backend eng asap, payments exp (UPI/cards), blr. python or go. 5+ yrs"
    # domain terms come from the brief text even if the LLM loses them
    c = Criteria(role="Senior Backend Engineer", skills=["Python"], must_haves=[], raw_brief=b1)
    assert "payments" in domain_terms(c) and "payments" in brief_domain_words(b1)
    assert years_asked(b1) == 5 and heuristic_parse(b1).min_years == 5
    # generic variants are dropped when the role names a function
    c = keep_function(Criteria(role="Senior Backend Engineer",
                               title_variants=["Senior Backend Engineer", "Staff Software Engineer", "Senior SDE",
                                               "Senior Platform Engineer", "Senior Software Engineer, Backend"]))
    assert c.title_variants == ["Senior Backend Engineer", "Senior Platform Engineer", "Senior Software Engineer, Backend"]
    # a generic role keeps its generic variants
    c = keep_function(Criteria(role="Software Engineer", title_variants=["Software Engineer", "Software Developer"]))
    assert len(c.title_variants) == 2


def test_company_lookup_shared_and_capped(monkeypatch):
    import app.orchestrator as o

    class Slow(RealShaped):
        calls = 0

        async def company_enrich(self, company_id=None, domain=None, fields=None):
            Slow.calls += 1
            await asyncio.sleep(5)

    monkeypatch.setattr(o, "COMPANY_TIMEOUT", 0.2)
    client = Slow()
    companies = {}

    async def go():
        return await asyncio.gather(*(o.enrich(client, dict(client.rec), pre={}, companies=companies) for _ in range(3)))
    res = asyncio.run(go())
    assert Slow.calls == 1
    assert all(not company and any("timed out" in x for x in probs) for _, company, probs in res)


def test_round3_hirer_context_and_fit_terms():
    from app.brief import brief_domain_words
    from app.orchestrator import fit_terms, prescore
    assert "devtools" not in brief_domain_words("first sales hire for our devtools co. sold to engg teams")
    assert "payments" in brief_domain_words("senior backend eng, payments exp")
    c = Criteria(role="Rust Engineer", skills=["Rust", "Go"], raw_brief="staff rust engineer")
    assert "rust" in fit_terms(c)
    assert prescore({"headline": "Engineer at Google"}, c) == prescore({"headline": "Engineer at Acme"}, c)
    assert prescore({"headline": "Go and Rust engineer"}, c) > prescore({"headline": "Engineer at Acme"}, c)


def test_company_batch_prefetch(monkeypatch):
    import app.orchestrator as o

    class Batch(RealShaped):
        def __init__(self):
            super().__init__()
            self.batch_calls = []
            self.single = 0

        async def request(self, name, payload):
            self.batch_calls.append(payload["crustdata_company_ids"])
            body = [{"matched_on": str(i), "matches": [{"confidence_score": 1, "company_data": {"basic_info": {"name": "Razorpay"}}}]}
                    for i in payload["crustdata_company_ids"]]
            return body, {"endpoint": "company/enrich", "request_hash": "b", "fetched_at": "t"}

        async def company_enrich(self, company_id=None, domain=None, fields=None):
            self.single += 1
            return None

    client = Batch()
    evs = collect("senior backend engineer bangalore payments", client=client)
    assert client.batch_calls == [[42]] and client.single == 0
    assert evs[-1].type == "done"


def test_near_miss_flag_and_rank_data(monkeypatch):
    import app.orchestrator as o
    monkeypatch.setattr(o, "SHORTLIST_MIN", 101)
    monkeypatch.setattr(o, "NEAR_MISS_MIN", 0)
    evs = collect("senior backend engineer bangalore payments")
    cands = [e.candidate for e in evs if e.type == "candidate"]
    assert all(any(f.startswith("Near miss") for f in c.flags) for c in cands)
    final = [e for e in evs if e.type == "step" and e.step == "rank" and e.data and "near_miss" in e.data][-1]
    assert set(final.data["near_miss"]) == {c.id for c in cands} and "near miss" in final.message
