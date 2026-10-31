"""Offline tests for the real-hires backtest (evals/backtest.py): point-in-time rewriting, hire detection, scoring."""
import asyncio
import json
import os
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("LLM_MODE", "mock")

from evals import backtest as bt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VINOD = json.loads((ROOT / "fixtures/crustdata/person_enrich_vinod-sonagara.json").read_text())
FAM = 13599234


def _titles(p, kind):
    return [(j["name"], j.get("title")) for j in p["experience"]["employment_details"][kind]]


def test_as_of_removes_the_job_being_predicted_and_reopens_jobs_that_ended_later():
    p = bt.as_of(VINOD, date(2025, 6, 15), FAM, "Fam")
    assert ("Fam", "Backend Engineer") not in _titles(p, "current") + _titles(p, "past")
    assert _titles(p, "current") == [("Newtral", "Advisor")]
    assert p["basic_profile"]["current_title"] == "Advisor"
    assert p["basic_profile"]["headline"] is None          # "Building Tech at Fam" names the later employer
    assert "Fam" not in json.dumps(p["experience"])
    assert VINOD["basic_profile"]["headline"].startswith("Building Tech at Fam")  # input untouched


def test_as_of_before_a_later_job_started():
    p = bt.as_of(VINOD, date(2024, 6, 1))
    # Co-Founder at Newtral (2023-01 .. 2025-03) was current in mid 2024; Advisor and Fam didn't exist yet
    assert _titles(p, "current") == [("Newtral", "Co-Founder")]
    assert p["experience"]["employment_details"]["current"][0]["end_date"] is None
    assert [n for n, _ in _titles(p, "past")] == ["Trinkerr", "Leena AI", "SupplyCopia"]


def test_as_of_same_month_start_counts_as_after_cutoff():
    p = bt.as_of(VINOD, date(2025, 5, 20))  # Fam start 2025-05-01 is month precision: could be after the 20th
    assert "Fam" not in [n for n, _ in _titles(p, "current")]


def test_widened_filter_and_local_recheck():
    f = {"op": "and", "conditions": [
        {"field": "experience.employment_details.current.title", "type": "(.)", "value": "backend engineer"},
        {"field": "basic_profile.location.city", "type": "(.)", "value": "bengaluru"}]}
    w = bt.widen_to_past(f)
    leaf = w["conditions"][0]
    assert leaf["op"] == "or" and leaf["conditions"][1]["field"] == "experience.employment_details.past.title"
    # mid 2025 Vinod is an Advisor: today's "Backend Engineer at Fam" must not get him into a backend search
    assert not bt.matches(f, bt.as_of(VINOD, date(2025, 6, 15), FAM, "Fam"))
    # in 2022 he was a Backend Engineer at Trinkerr
    assert bt.matches(f, bt.as_of(VINOD, date(2022, 6, 15)))


@pytest.mark.parametrize("posting,title,ok", [
    ("Backend Engineer (Nodejs/TypeScript)", "Backend Engineer", True),
    ("Senior Backend Engineer - Payments", "Software Engineer - Backend", False),  # "- Payments" is dropped; no shared spec
    ("Backend Developer", "Senior Backend Developer", True),
    ("Data Scientist", "Senior Data Scientist II", True),
    ("Backend Engineer", "Sales Manager", False),
    ("Product Designer", "Product Manager", False),
    ("Software Development Engineer II", "SDE 2", True),
    ("Frontend Engineer, Bangalore", "Frontend Developer", False),
    ("Machine Learning Engineer", "ML Engineer", True),
])
def test_role_match(posting, title, ok):
    assert bt.role_match(posting, title) is ok


def _row(name, slug, jobs_cur, jobs_past=(), city="Bengaluru", headline=""):
    mk = lambda j: {"name": j[0], "title": j[1], "start_date": j[2], "end_date": j[3] if len(j) > 3 else None,  # noqa: E731
                    "crustdata_company_id": j[4] if len(j) > 4 else hash(j[0]) % 10**6}
    return {"crustdata_person_id": hash(slug) % 10**6,
            "basic_profile": {"name": name, "headline": headline, "current_title": jobs_cur[0][1] if jobs_cur else None,
                              "location": {"city": city, "country": "India"}},
            "experience": {"employment_details": {"current": [mk(j) for j in jobs_cur], "past": [mk(j) for j in jobs_past]}},
            "skills": {"professional_network_skills": ["Python", "Payments"]},
            "social_handles": {"professional_network_identifier": {"profile_url": f"https://www.linkedin.com/in/{slug}"}}}


HIRE = _row("Hire Person", "hire-1", [("Acmepay", "Backend Engineer", "2025-11-01", None, 42)],
            [("Oldco", "Backend Engineer", "2022-01-01", "2025-10-01", 7)], headline="Backend @ Acmepay")
INTERNAL = _row("Internal Mover", "int-1", [("Acmepay", "Backend Engineer", "2025-11-01", None, 42)],
                [("Acmepay", "Support Engineer", "2023-01-01", "2025-10-31", 42)])
WRONG_ROLE = _row("Sales Joiner", "sales-1", [("Acmepay", "Sales Manager", "2025-11-01", None, 42)])
OTHERS = [_row(f"Other {i}", f"o-{i}", [(f"Co{i}", "Backend Engineer", "2021-01-01", None, 100 + i)]) for i in range(6)]
LATE_SWITCHER = _row("Late Switcher", "late-1", [("Newco", "Backend Engineer", "2026-03-01", None, 9)],
                     [("Shop", "Store Manager", "2019-01-01", "2026-02-01", 8)])


class FakeClient:
    """Answers every search with the same people, like a loose server match; enrich returns the same record."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def person_search(self, filters, limit=25, **extra):
        self.calls.append(filters)
        return [json.loads(json.dumps(r)) for r in self.rows][:limit]

    async def person_enrich_many(self, urls, *a, **kw):
        by = {bt.people.profile_url(r): r for r in self.rows}
        return {u: json.loads(json.dumps(by[u])) if u in by else None for u in urls}

    async def person_enrich(self, url, *a, **kw):
        return (await self.person_enrich_many([url]))[url]

    async def request(self, *a, **kw):
        return None

    async def company_enrich(self, *a, **kw):
        return None

    async def company_identify(self, *a, **kw):
        return None

    async def web_search(self, *a, **kw):
        raise AssertionError("web search must be off in a backtest")


OPENING = bt.Opening(job_id="j1", title="Backend Engineer", company="Acmepay", company_id=42, posted="2025-10-20",
                     city="Bengaluru", country="India", url=None, industry="Financial Services", headcount=300,
                     description="We need a backend engineer with Python and payments experience.")


def test_find_hires_keeps_outside_joiners_in_the_posted_role():
    hires, info = asyncio.run(bt.find_hires(FakeClient([HIRE, INTERNAL, WRONG_ROLE, *OTHERS]), OPENING))
    assert [h["name"] for h in hires] == ["Hire Person"]
    assert hires[0]["start"] == "2025-11-01"


def test_run_opening_end_to_end_without_leaks():
    op = bt.Opening(**{**OPENING.__dict__})
    op.hires, _ = asyncio.run(bt.find_hires(FakeClient([HIRE, *OTHERS]), op))
    client = FakeClient([HIRE, LATE_SWITCHER, *OTHERS])
    r = asyncio.run(bt.run_opening(client, op))
    assert r["hire_in_pool"] is True
    names = [s["name"] for s in r["slate"]]
    assert "Late Switcher" not in names  # a store manager on the posting date, so not in a backend search
    hire = next(s for s in r["slate"] if s["hire"])
    assert hire["title"] == "Backend Engineer"  # his as-of title at Oldco, not the job at Acmepay
    assert r["b_rank"] is not None and 1 <= r["b_rank"] <= r["b_n"]
    assert r["a_n"] <= bt.orchestrator.MAX_ENRICH


def test_asof_client_never_leaks_the_hiring_company():
    client = bt.AsOfClient(FakeClient([HIRE]), date(2025, 10, 20), 42, "Acmepay")
    rows = asyncio.run(client.person_search({"field": "experience.employment_details.current.title", "type": "(.)",
                                             "value": "backend"}))
    assert rows and "Acmepay" not in json.dumps(rows)
    assert asyncio.run(client.web_search("x")) == []


def test_random_baseline_and_summary():
    assert bt._random_mrr(1, 1) == 1.0
    assert abs(bt._random_mrr(2, 1) - 0.75) < 1e-9
    assert abs(bt._random_hit(10, 1, 3) - 0.3) < 1e-9
    rows = [{"job_id": "a", "hire_in_pool": True, "a_rank": 1, "b_rank": 1, "b_rank_prescore": 2, "b_n": 10, "b_hires": 1, "pool": 30},
            {"job_id": "b", "hire_in_pool": False, "a_rank": None, "b_rank": 4, "b_rank_prescore": 1, "b_n": 10, "b_hires": 1, "pool": 20}]
    s = bt.summarize(rows)
    assert s["retrieval"] == 0.5 and s["a"]["hit@1"] == 0.5 and s["b"]["hit@5"] == 1.0
    assert abs(s["b"]["mrr"] - (1 + 0.25) / 2) < 1e-9
    md = bt.scorecard([{**r, "company": "Acmepay", "title": "Backend Engineer", "posted": "2025-10-20", "n_hires": 1}
                       for r in rows], {"start": "2025-06-01", "end": "2025-12-31"})
    assert "Hire Person" not in md and "hit@1" in md
