"""Messy briefs -> criteria, for any function (not just engineering), with education asks that drive search and
scoring. No live Crustdata or Gemini calls: the rule pass runs in LLM_MODE=mock, the LLM path uses a stubbed
generate_json, and Crustdata is a fake client (the real key is out of credits)."""
import asyncio
import json

import pytest

from app import brief as brief_mod
from app import llm
from app.brief import ParsedBrief, analyze_brief, heuristic_parse
from app.crustdata.client import CrustdataError
from app.orchestrator import prescore, run, to_crustdata_filters
from app.schemas import Criteria
from app.verify.profile import degree_matches, school_matches
from app.verify.ranker import rank_candidate
from app.verify.verifier import verify_candidate


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.setenv("CRUSTDATA_MODE", "dev")
    brief_mod._PARSE_CACHE.clear()


def analyze(text):
    return asyncio.run(analyze_brief(text))


def collect(text, client=None):
    async def go():
        return [e async for e in run(text, client=client)]
    return asyncio.run(go())


QUANT = "need a junior quant trader ,prestige college in  india,"

# brief -> (role, seniority, locations) the rule pass must get without any LLM
MESSY = [
    (QUANT, "Quantitative Trader", "junior", ["India"]),
    ("need a junior quant trader from a tier 1 college", "Quantitative Trader", "junior", []),
    ("lookin for equity research analyst mumbai 3+ yrs CFA preferred", "Equity Research Analyst", None, ["Mumbai"]),
    ("hiring fresher data analysts from IITs or BITS Pilani, remote in india", "Data Analyst", "junior", ["India"]),
    ("want a growth marketer for our d2c brand, bangalore", "Growth Marketer", None, ["Bangalore"]),
    ("quant researcher phd from ivy league, NYC", "Quantitative Researcher", None, ["New York"]),
    ("IIT Bombay grads only, need a backend dev in pune", "Backend Engineer", None, ["Pune"]),
    ("need a sr backend eng, payments exp, blr, ex-startup, can start soon", "Senior Backend Engineer", "senior", ["Bangalore"]),
    ("lookin for a foundng AE / first sales hire for our devtools co. US east coast pref", "Account Executive", None,
     ["United States"]),
    ("Find me a product designer who has done fintech, IIT Bombay grads only", "Product Designer", None, []),
]


@pytest.mark.parametrize("text,role,seniority,locations", MESSY)
def test_rule_pass_reads_messy_briefs_for_any_function(text, role, seniority, locations):
    a = analyze(text)
    c = a.criteria
    assert a.is_hiring
    assert c.role == role
    assert c.seniority == seniority
    assert c.locations == locations
    assert c.title_variants and c.title_variants[0] == c.role


def test_quant_brief_is_not_software_engineer_and_education_is_shown():
    a = analyze(QUANT)
    c = a.criteria
    assert "software" not in c.role.lower()
    assert "Quant Trader" in c.title_variants
    assert c.education_note == "prestige college in india"
    # "college in india" names the school's country: searched first, and said so (the ladder drops it if thin)
    assert c.locations == ["India"]
    assert any("searching India first" in x for x in a.assumptions)
    # without the AI parser the tier can't be expanded: say so instead of silently ignoring it
    assert any("prestige college in india" in x and "not filtering" in x for x in a.assumptions)


def test_named_schools_are_read_by_rules_and_not_taken_as_locations():
    c = analyze("IIT Bombay grads only, need a backend dev in pune").criteria
    assert c.schools == ["IIT Bombay"]
    assert "Mumbai" not in c.locations  # Bombay is part of the school's name here
    c = analyze("hiring fresher data analysts from IITs or BITS Pilani, remote in india").criteria
    assert c.schools == ["IIT", "BITS Pilani"]
    c = analyze("quant researcher phd from ivy league, NYC").criteria
    assert c.degrees == ["PhD"]


def test_no_role_is_never_defaulted_to_software_engineer():
    a = analyze("what's the weather in Mumbai")
    assert a.criteria.role == "" and not a.is_hiring
    a = analyze("we need someone sharp for the team asap")
    assert a.criteria.role == ""
    assert "Couldn't tell which role this is for" in a.assumptions


def test_unclear_role_stops_before_spending_search_credits():
    evs = collect("we need someone sharp for the team asap")
    errs = [e.message for e in evs if e.type == "error"]
    assert any("Couldn't tell which role" in m for m in errs)
    assert not any(e.type == "step" and e.step == "search" for e in evs)
    assert evs[-1].type == "done"


# ---- LLM path (stubbed Gemini) -----------------------------------------------------------------------------

def _stub_llm(monkeypatch, parsed: ParsedBrief | Exception):
    monkeypatch.setenv("LLM_MODE", "live")
    calls = []

    async def fake(prompt, schema, tier="fast", temperature=0.2):
        calls.append(prompt)
        if isinstance(parsed, Exception):
            raise parsed
        return parsed.model_copy(deep=True)

    monkeypatch.setattr(llm, "generate_json", fake)
    return calls


def test_llm_expands_school_tier_and_keeps_it_out_of_skills(monkeypatch):
    calls = _stub_llm(monkeypatch, ParsedBrief(
        role="Quantitative Trader", title_variants=["Quant Trader", "Junior Trader", "Quantitative Trading Analyst"],
        seniority="junior", skills=["Options", "IIT"], must_haves=["degree from a prestige college"],
        education_note="prestige college in India",
        schools=["IIT", "Indian Institute of Technology", "ISI", "Indian Statistical Institute", "BITS Pilani",
                 "IIM", "IISc", "Indian Institute of Science"],
        assumptions=["No location given, searching globally",
                     "'prestige college in India' read as top IITs, ISI, BITS Pilani and the IIMs"]))
    a = analyze(QUANT)
    c = a.criteria
    assert "prestige college" in calls[0]  # the brief went to the model
    assert c.role == "Quantitative Trader" and c.seniority == "junior"
    assert "ISI" in c.schools and "BITS Pilani" in c.schools
    assert c.skills == ["Options"] and c.must_haves == []  # education lives in schools, not skills/must-haves
    assert any(x.startswith("'prestige college in India' read as: IIT") for x in a.assumptions)
    # the model's own reading of the education ask is dropped so it can't contradict the schools searched,
    # and "no location" is gone because India is searched first
    assert not any("top IITs" in x for x in a.assumptions)
    assert not any("No location given" in x for x in a.assumptions)
    assert c.locations == ["India"]


def test_llm_drifting_to_software_engineer_is_corrected_by_rules(monkeypatch):
    _stub_llm(monkeypatch, ParsedBrief(role="Software Engineer", title_variants=["Software Engineer", "SDE"],
                                       seniority="junior"))
    a = analyze(QUANT)
    assert a.criteria.role == "Quantitative Trader"
    assert any("model said Software Engineer" in x for x in a.assumptions)


def test_llm_failure_falls_back_visibly(monkeypatch):
    _stub_llm(monkeypatch, llm.LLMError("vertex down"))
    a = analyze(QUANT)
    assert a.criteria.role == "Quantitative Trader"
    assert a.assumptions[0] == "Brief parsed with keyword rules (AI parser unavailable)"


def test_llm_parse_is_cached_per_brief(monkeypatch):
    calls = _stub_llm(monkeypatch, ParsedBrief(role="Quantitative Trader", seniority="junior"))
    analyze(QUANT)
    analyze(QUANT)
    assert len(calls) == 1


# ---- search filters, scoring ----------------------------------------------------------------------------

def test_schools_become_a_crustdata_education_filter():
    f = to_crustdata_filters({"titles": ["Quantitative Trader"], "locations": [], "schools": ["IIT", "ISI"]})
    flat = json.dumps(f)
    assert f["op"] == "and"
    assert '"education.schools.school"' in flat and '"iit"' in flat and '"isi"' in flat


class _Fake:
    """Real-shaped client: records search calls, can be told to answer 402."""

    def __init__(self, status: int | None = None):
        self.status, self.searches = status, []

    async def person_search(self, filters, limit=25, **extra):
        self.searches.append((filters, extra))
        if self.status:
            raise CrustdataError(f"POST /person/search -> {self.status}: no credits", status=self.status,
                                 endpoint="person/search")
        return []

    async def person_enrich_many(self, urls, fields=None):
        return {}


def test_school_query_runs_with_education_fields(monkeypatch):
    async def fake(prompt, schema, tier="fast", temperature=0.2):
        return ParsedBrief(role="Quantitative Trader", title_variants=["Quant Trader"], seniority="junior",
                           schools=["IIT", "ISI"], education_note="prestige college in India")
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setattr(llm, "generate_json", fake)
    client = _Fake()
    collect(QUANT, client=client)
    school_q = [(f, x) for f, x in client.searches if "education.schools.school" in json.dumps(f)]
    assert school_q, "no search used the schools"
    assert "education" in school_q[0][1]["fields"]
    titles = json.dumps([f for f, _ in client.searches])
    assert "quantitative trader" in titles and "software engineer" not in titles


def test_school_match_is_prescored_up():
    c = Criteria(role="Quantitative Trader", title_variants=["Quantitative Trader"], schools=["IIT"])
    a = {"title": "Quantitative Trader"}
    assert prescore(dict(a, _school_match=True), c) > prescore(a, c)


def test_out_of_credits_stops_cleanly_without_broadening():
    client = _Fake(status=402)
    evs = collect("need a junior quant trader in mumbai", client=client)
    errs = [e.message for e in evs if e.type == "error"]
    assert any("out of credits" in m.lower() and "402" in m for m in errs)
    levels = {e.data.get("level") for e in evs if e.type == "step" and e.step == "search" and e.data and "strategy" in e.data}
    assert levels == {0}  # did not keep broadening into more 402s
    assert evs[-1].type == "done"


@pytest.mark.parametrize("wanted,have,ok", [
    ("IIT", "Indian Institute of Technology, Bombay", True),
    ("IIT Bombay", "Indian Institute of Technology Bombay", True),
    ("IITs", "IIT Delhi", True),
    ("IIT", "IIIT Hyderabad", False),
    ("IIT", "International Institute of Information Technology", False),
    ("BITS", "Birla Institute of Technology and Science, Pilani", True),
    ("ISI", "Indian Statistical Institute", True),
    ("IIT", "Gujarat Technological University", False),
    ("Indian Institute of Science", "Indian Institute of Science (IISc)", True),
])
def test_school_matching(wanted, have, ok):
    assert school_matches(wanted, have) is ok


def test_degree_matching():
    assert degree_matches("B.Tech", "Bachelor of Technology - BTech")
    assert degree_matches("MBA", "Post Graduate Diploma in Management (PGDM)")
    assert not degree_matches("PhD", "Bachelor of Engineering - BE")


def _person(school: str, end_year: int = 2024) -> dict:
    return {
        "basic_profile": {"name": "Asha Rao", "headline": "Quantitative Trader at Graviton",
                          "location": {"city": "Mumbai", "country": "India"}},
        "experience": {"employment_details": {"current": [
            {"title": "Quantitative Trader", "name": "Graviton Research Capital", "start_date": "2024-07-01"}],
            "past": []}},
        "education": {"schools": [{"school": school, "degree": "Bachelor of Technology - BTech", "end_year": end_year}]},
        "_source": {"endpoint": "person/enrich"},
    }


def test_education_claim_and_ranking_prefer_the_asked_schools():
    c = Criteria(role="Quantitative Trader", title_variants=["Quantitative Trader", "Quant Trader"],
                 seniority="junior", schools=["IIT", "ISI", "BITS Pilani"], education_note="prestige college in India")

    async def score(school):
        claims, _ = await verify_candidate(_person(school), None, c, None)
        s, reasons = await rank_candidate(_person(school), claims, c)
        return claims, s, reasons

    claims, s_iit, reasons = asyncio.run(score("Indian Institute of Technology, Kharagpur"))
    edu = [k for k in claims if k.claim.startswith("Education:")]
    assert edu and edu[0].status == "verified" and edu[0].source.field.startswith("education.schools[0]")
    assert any("one of the schools the brief asks for" in r.text for r in reasons)
    _, s_other, reasons_o = asyncio.run(score("Gujarat Technological University"))
    assert any("not one of the schools" in r.text for r in reasons_o)
    assert s_iit > s_other


def test_junior_brief_caps_a_twenty_year_career():
    c = Criteria(role="Quantitative Trader", title_variants=["Quantitative Trader"], seniority="junior",
                 schools=["IIT"], education_note="prestige college in India")
    senior = _person("Indian Institute of Technology, Kanpur", end_year=2004)
    senior["experience"]["employment_details"]["past"] = [
        {"title": "Trader", "name": "Old Bank", "start_date": "2004-07-01", "end_date": "2024-06-30"}]
    fresh = _person("Indian Institute of Technology, Kanpur")

    async def score(p):
        claims, _ = await verify_candidate(p, None, c, None)
        return await rank_candidate(p, claims, c)

    s_senior, reasons = asyncio.run(score(senior))
    s_fresh, _ = asyncio.run(score(fresh))
    assert any(r.text.startswith("Too senior for a junior role") for r in reasons)
    assert s_senior <= 60 < s_fresh


def test_student_roles_do_not_count_as_experience():
    """Live run: 2026 graduates showed ~3.6 yrs from E-Cell and hostel roles, a 2015 grad ~14 yrs from a 2013
    internship. Only work after (or alongside, once graduated) counts."""
    c = Criteria(role="Quantitative Trader", seniority="junior", schools=["IIT"])
    p = _person("Indian Institute of Technology Delhi", end_year=2026)
    p["experience"]["employment_details"]["current"] = [
        {"title": "Quantitative Trader", "name": "Tower Research Capital", "start_date": "2026-07-01"}]
    p["experience"]["employment_details"]["past"] = [
        {"title": "Overall Coordinator", "name": "E-Cell, IIT Delhi", "start_date": "2023-01-01", "end_date": "2024-01-01"},
        {"title": "Secretary", "name": "Hostel Board", "start_date": "2022-08-01", "end_date": "2023-05-01"},
        {"title": "Quant Research Intern", "name": "Graviton", "start_date": "2025-05-01", "end_date": "2025-07-01"},
    ]
    claims, _ = asyncio.run(verify_candidate(p, None, c, None, today=__import__("datetime").date(2026, 10, 31)))
    exp = next(k for k in claims if k.claim.endswith("of experience"))
    assert exp.claim == "~0.3 yrs of experience"
    assert "3 internship/student roles not counted" in exp.evidence

    q = _person("Indian Institute of Technology Delhi", end_year=2015)
    q["experience"]["employment_details"]["current"] = [
        {"title": "Quantitative Trader", "name": "AlphaGrep", "start_date": "2015-07-01"}]
    q["experience"]["employment_details"]["past"] = [
        {"title": "Summer Intern", "name": "Goldman Sachs", "start_date": "2013-05-01", "end_date": "2013-07-01"}]
    claims, _ = asyncio.run(verify_candidate(q, None, c, None, today=__import__("datetime").date(2026, 10, 31)))
    exp = next(k for k in claims if k.claim.endswith("of experience"))
    assert exp.claim == "~11 yrs of experience"
