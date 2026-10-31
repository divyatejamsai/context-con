"""Backtest Sourced on last year's real job openings: did it find the people who were actually hired?

This is the judging spec on the Hiring theme slide: "tested on last year's real job openings, find the people who
were actually hired". Everything here runs on live Crustdata data; nothing is synthetic.

    cd backend
    python -m evals.backtest probe                      # which filter shapes the live API accepts (few credits)
    python -m evals.backtest openings --max-jobs 120    # real postings + the people who actually joined
    python -m evals.backtest run                        # Sourced on each posting, knowledge cut off at the posting date
    python -m evals.backtest score --out ../docs/BACKTEST.md   # redacted scorecard (no person names)
    python -m evals.backtest tune --out ../docs/BACKTEST.md    # fit likelihood-to-move weights, 5-fold CV, offline
    python -m evals.backtest all --max-jobs 120 --out ../docs/BACKTEST.md

Method (see docs/BACKTEST.md for the write-up)
1. Openings: Crustdata Job Search for postings added in the window (default 2025-06-01..2025-12-31).
2. Ground truth: Person Search for people whose job at that company started between the posting date (minus a
   small slack, since LinkedIn start dates are month-precision) and posting + 180 days, in a role whose title matches
   the posting. Internal moves are excluded. Openings whose title matches more than MAX_HIRES joiners are dropped as
   ambiguous (a 3,000-person company hiring 20 "Software Engineers" would make recall meaningless).
3. Point-in-time run: Sourced runs on a brief made from the posting itself (title, company, location, JD text).
   Every person record it sees, from search or enrich, is rewritten to how it looked on the posting date: jobs that
   started after the cutoff (or in the cutoff month) are removed, jobs that ended after it become current again, the
   current title is recomputed, and a headline or summary that names a later employer is blanked. Search is
   rewritten so a title filter on the current job also matches past jobs, then every row is re-checked against the
   original filter using its as-of record. Web search and web fetch are switched off (they return today's web).
   The verifier and ranker run with today = posting date.
4. Scoring:
   - Retrieval: is any real hire in Sourced's search pool at all?
   - End to end (task A): Sourced as shipped enriches its top MAX_ENRICH by prescore and ranks them. Hit@k and MRR of
     the best-ranked real hire.
   - Ranking (task B): the real hire(s) plus up to DISTRACTORS of the strongest other people from the same as-of
     pool, all verified and ranked the same way. Hit@k and MRR, against a random-order and a prescore-order baseline.
     This isolates "would Sourced put the person who got the job at the top of a realistic slate".

Known leaks that can't be removed with the data available (stated in the scorecard): location and skills are
today's values; company records for candidates' employers are today's (headcount, funding).

Outputs: backend/data/backtest/{openings.json, results.jsonl} hold real people and stay local (backend/data is
gitignored). The scorecard written by `score` has no person names, only public posting details and ranks.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import math
import random
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app import orchestrator, people  # noqa: E402
from app.verify.profile import company_key, expand_title, norm, parse_date, same_company  # noqa: E402

log = logging.getLogger("backtest")

DATA_DIR = ROOT / "backend" / "data" / "backtest"
CUR = "experience.employment_details.current"
PAST = "experience.employment_details.past"

WINDOW_START = "2025-06-01"
WINDOW_END = "2025-12-31"
HIRE_SLACK_DAYS = 31       # month-precision start dates: a hire "starting" 2025-10-01 can be for a 2025-10-15 posting
HIRE_HORIZON_DAYS = 180    # joined within six months of the posting
MAX_HIRES = 5              # more title-matching joiners than this = ambiguous opening, dropped
MIN_HEADCOUNT, MAX_HEADCOUNT = 10, 5000
DISTRACTORS = 24           # task B slate = hires + this many others from the as-of pool
KS = (1, 3, 5, 10)


# =============================================================================================== helpers

def _d(v: Any) -> date | None:
    return parse_date(v)


def norm_url(u: str | None) -> str | None:
    return orchestrator._norm_profile(u)


def person_key(p: dict) -> str | None:
    """Stable id for matching a hire to a pool row: LinkedIn slug, else crustdata_person_id."""
    u = norm_url(people.profile_url(p))
    if u:
        return "url:" + u
    pid = p.get("crustdata_person_id")
    return f"pid:{pid}" if pid is not None else None


def keys_of(p: dict) -> set[str]:
    out = set()
    u = norm_url(people.profile_url(p))
    if u:
        out.add("url:" + u)
    if p.get("crustdata_person_id") is not None:
        out.add(f"pid:{p['crustdata_person_id']}")
    return out


_SENIORITY = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "associate", "intern", "trainee", "head",
              "chief", "i", "ii", "iii", "iv", "1", "2", "3", "4", "level", "l1", "l2", "l3", "l4", "l5", "grade"}
_STOP = {"of", "and", "the", "for", "in", "at", "to", "a", "an", "with", "on", "remote", "hybrid", "onsite", "full",
         "time", "fulltime", "part", "contract", "urgent", "hiring", "immediate", "joiner", "joiners", "opening",
         "india", "bangalore", "bengaluru", "mumbai", "pune", "delhi", "gurgaon", "gurugram", "noida", "hyderabad",
         "chennai", "kolkata", "ahmedabad", "jaipur", "kochi", "team", "role", "position", "job", "wfo", "wfh"}
_FUNCTION = {"engineer", "developer", "designer", "manager", "analyst", "scientist", "architect", "consultant",
             "executive", "specialist", "recruiter", "accountant", "marketer", "writer", "officer", "administrator",
             "associate", "representative", "coordinator", "lead", "director", "intern", "tester", "programmer",
             "researcher", "strategist", "partner", "advisor", "editor", "operator", "technician", "sales", "design",
             "ux", "administrator", "support", "head", "officer"}


_SAME_FUNCTION = {"developer": "engineer", "programmer": "engineer", "dev": "engineer", "engg": "engineer",
                  "sde": "engineer", "swe": "engineer"}
_JOIN = [(r"\bback\s*end\b", "backend"), (r"\bfront\s*end\b", "frontend"), (r"\bfull\s*stack\b", "fullstack"),
         (r"\bdev\s*ops\b", "devops"), (r"\bquality assurance\b", "qa"), (r"\bbusiness intelligence\b", "bi"), (r"\bsoftware development engineer\b", "software engineer")]


def _core_of(t: str) -> set[str]:
    t = norm(expand_title(t))
    for pat, rep in _JOIN:
        t = re.sub(pat, rep, t)
    toks = {_SAME_FUNCTION.get(x, x) for x in t.split()}
    return {x for x in toks if len(x) > 1 and x not in _SENIORITY and x not in _STOP}


def core_tokens(title: str | None) -> set[str]:
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title or "")   # "(Node.js/TypeScript)" is a stack, not the role
    # "Backend Engineer - Payments | Bangalore", "Full Stack Engineer with AWS LEX", "QA Engineer for Fintech"
    parts = [x for x in re.split(r"\s[-|–—@/]\s|,|\s(?:with|for|at|in)\s", t, flags=re.I) if x.strip()]
    if not parts:
        return set()
    core = _core_of(parts[0])
    # "Manager, Software Engineering" / "Big Data - Senior Engineer": the head alone is not the role
    if len(parts) > 1 and (not (core - _FUNCTION) or not (core & _FUNCTION)):
        core |= _core_of(parts[1])
    return core


_JUNIOR_HIRE = re.compile(r"\b(intern|internship|trainee|apprentice)\b", re.I)


def role_match(posting_title: str | None, person_title: str | None) -> bool:
    """Is a joiner's title the role that was posted? Both must share the job function word plus the specialisation
    when the posting has one ("Backend Engineer" ~ "Software Engineer - Backend", not ~ "Sales Manager", and not
    a bare "Principal Engineer" or "Senior Developer", which says nothing about the specialisation)."""
    if _JUNIOR_HIRE.search(person_title or "") and not _JUNIOR_HIRE.search(posting_title or ""):
        return False  # an intern joining is not the hire for a regular opening
    a, b = core_tokens(posting_title), core_tokens(person_title)
    if not a or not b:
        return False
    sa, sb = a - _FUNCTION, b - _FUNCTION
    fa, fb = a & _FUNCTION, b & _FUNCTION
    # "Java Full Stack" names no function word: any function on the joiner's side is fine
    same_function = bool(fa & fb) or not fa or not fb
    if not same_function or not (sa & sb):
        return False  # the specialisation must match, not just "engineer"
    if a <= b or b <= a:
        return True
    shared = a & b
    jacc = len(shared) / len(a | b)
    nested = sa <= sb or sb <= sa  # "Java Full Stack" ~ "Full Stack Developer"
    return jacc >= 0.5 or len(shared) >= 2 or nested


# =============================================================================================== point in time

def _jobs(person: dict, path: str) -> list[dict]:
    v = people.first(person, path)
    return [j for j in v if isinstance(j, dict)] if isinstance(v, list) else []


def _at_company(job: dict, cid: Any, cname: str | None) -> bool:
    jid = job.get("crustdata_company_id")
    if cid is not None and jid is not None and str(jid) == str(cid):
        return True
    return bool(cname) and same_company(job.get("name") or job.get("company_name"), cname)


def _after_cutoff(start: date | None, cutoff: date) -> bool:
    # same month counts as after: "2025-10-01" may be a join on the 20th, after a posting on the 15th
    return bool(start) and (start > cutoff or (start.year, start.month) == (cutoff.year, cutoff.month))


def as_of(person: dict | None, cutoff: date, hiring_company_id: Any = None, hiring_company: str | None = None) -> dict | None:
    """The person's record as it would have read on `cutoff`. Pure function; returns a new dict."""
    if not person:
        return person
    p = copy.deepcopy(person)
    dropped_companies: set[str] = set()
    if hiring_company:
        dropped_companies.add(hiring_company)
    current, past = [], []
    for kind, jobs in (("current", _jobs(p, CUR)), ("past", _jobs(p, PAST))):
        for j in jobs:
            start, end = _d(j.get("start_date")), _d(j.get("end_date"))
            at_hirer = _at_company(j, hiring_company_id, hiring_company)
            if at_hirer and (start is None or start >= cutoff - timedelta(days=HIRE_SLACK_DAYS + 14)):
                dropped_companies.add(j.get("name") or "")
                continue   # the job we are trying to predict
            if _after_cutoff(start, cutoff) or (start is None and kind == "current" and at_hirer):
                dropped_companies.add(j.get("name") or "")
                continue
            # an end date in the cutoff month is ambiguous (month precision): they may still have been there
            if end and end <= cutoff and (end.year, end.month) != (cutoff.year, cutoff.month):
                past.append(j)
            else:
                j = {k: v for k, v in j.items() if k not in ("years_at_company", "years_at_company_raw")}
                j["end_date"] = None
                current.append(j)
    current.sort(key=lambda j: _d(j.get("start_date")) or date.min, reverse=True)
    past.sort(key=lambda j: _d(j.get("end_date")) or date.min, reverse=True)
    exp = p.setdefault("experience", {})
    if not isinstance(exp, dict):
        exp = p["experience"] = {}
    ed = exp.setdefault("employment_details", {})
    ed["current"], ed["past"] = current, past
    for k in ("recently_changed_jobs", "years_of_experience", "years_of_experience_raw"):
        exp.pop(k, None)

    bp = p.get("basic_profile") if isinstance(p.get("basic_profile"), dict) else None
    keys = {company_key(c) for c in dropped_companies if c and len(company_key(c)) >= 3}

    def leaks(s: Any) -> bool:
        if not isinstance(s, str) or not s:
            return False
        n = f" {norm(s)} "
        return any(f" {k} " in n or k.replace(" ", "") in n.replace(" ", "") for k in keys)

    if bp is not None:
        bp["current_title"] = current[0].get("title") if current else None
        # today's headline/summary can't be dated (they leak later employers, often obliquely: "AI Engineer at
        # Crowe" for "Crowe Capabilities Center"), so as-of records have none, for hires and everyone else alike
        for k in ("headline", "summary"):
            bp[k] = None
    for k in ("headline", "summary", "title", "current_title"):
        if k in p and (leaks(p.get(k)) or k in ("title", "current_title")):
            p[k] = None
    p["_asof"] = cutoff.isoformat()
    return p


# ---- filter rewriting + local re-check --------------------------------------------------------------

_TIME_FIELDS = (CUR + ".", PAST + ".", "basic_profile.headline", "basic_profile.current_title",
                "skills.professional_network_skills")


def widen_to_past(node: Any) -> Any:
    """A filter on the current job also matches past jobs, so people whose then-current title fit are found."""
    if isinstance(node, dict) and "conditions" in node:
        return {**node, "conditions": [widen_to_past(c) for c in node["conditions"]]}
    if isinstance(node, dict) and str(node.get("field", "")).startswith(CUR + "."):
        past = {**node, "field": PAST + node["field"][len(CUR):]}
        return {"op": "or", "conditions": [node, past]}
    return node


def _values(d: Any, path: str) -> list[Any]:
    cur = [d]
    for part in path.split("."):
        nxt = []
        for c in cur:
            if isinstance(c, dict):
                v = c.get(part)
            else:
                continue
            if isinstance(v, list):
                nxt.extend(v)
            elif v is not None:
                nxt.append(v)
        cur = nxt
    return cur


def _fuzzy(value: str, query: str) -> bool:
    q = norm(query).split()
    v = norm(value)
    return bool(q) and all(re.search(rf"(?<![a-z0-9]){re.escape(t)}", v) for t in q)


def matches(node: Any, person: dict) -> bool:
    """Re-check a person/search filter on an as-of record. Only time-dependent fields are judged locally; for the
    rest (location, ids) the server's match is trusted, since we have nothing older to check against."""
    if isinstance(node, dict) and "conditions" in node:
        res = [matches(c, person) for c in node["conditions"]]
        return all(res) if node.get("op", "and") == "and" else any(res)
    if not isinstance(node, dict):
        return True
    fld, typ, val = str(node.get("field", "")), node.get("type"), node.get("value")
    if not fld.startswith(_TIME_FIELDS):
        return True
    vals = [v for v in _values(person, fld) if isinstance(v, (str, int, float))]
    if fld.startswith("skills.") and "skills" not in person:
        return True  # search didn't return skills, can't judge
    if typ == "(.)":
        return any(_fuzzy(str(v), str(val)) for v in vals)
    if typ == "=":
        return any(norm(v) == norm(val) for v in vals)
    if typ == "in" and isinstance(val, list):
        return any(norm(v) == norm(x) for v in vals for x in val)
    return True


class AsOfClient:
    """Wraps CrustdataClient so the pipeline only ever sees the world as of `cutoff`."""

    def __init__(self, inner, cutoff: date, hiring_company_id=None, hiring_company: str | None = None,
                 search_widen: int = 2):
        self.inner, self.cutoff = inner, cutoff
        self.cid, self.cname = hiring_company_id, hiring_company
        self.search_widen = search_widen
        self.stats = {"search_rows": 0, "kept": 0, "dropped_after_cutoff": 0}

    def _t(self, p):
        return as_of(p, self.cutoff, self.cid, self.cname)

    async def person_search(self, filters: dict, limit: int = 25, **extra) -> list[dict]:
        fields = list(dict.fromkeys([*(extra.pop("fields", None) or orchestrator.PERSON_SEARCH_FIELDS), "skills"]))
        try:
            rows = await self.inner.person_search(widen_to_past(filters), limit=min(100, limit * self.search_widen),
                                                  fields=fields, **extra)
        except Exception as e:  # server refused the widened filter: fall back to today's filter, still re-checked
            log.warning("widened search refused (%s); using the original filter", e)
            rows = await self.inner.person_search(filters, limit=min(100, limit * self.search_widen), fields=fields, **extra)
        out = []
        for r in rows:
            self.stats["search_rows"] += 1
            t = self._t(r)
            if matches(filters, t):
                out.append(t)
            else:
                self.stats["dropped_after_cutoff"] += 1
        self.stats["kept"] += len(out)
        return out[:limit]

    async def person_enrich(self, url: str, *a, **kw):
        return self._t(await self.inner.person_enrich(url, *a, **kw))

    async def person_enrich_many(self, urls: list[str], *a, **kw):
        res = await self.inner.person_enrich_many(urls, *a, **kw)
        return {u: self._t(p) for u, p in res.items()}

    async def request(self, name: str, payload: dict):
        if name.startswith("person/") or name.startswith("web/") or name.startswith("job/"):
            return None  # the pipeline only uses request() for company/enrich batches
        return await self.inner.request(name, payload)

    async def company_enrich(self, *a, **kw):
        return await self.inner.company_enrich(*a, **kw)

    async def company_identify(self, *a, **kw):
        return await self.inner.company_identify(*a, **kw)

    async def company_search(self, *a, **kw):
        return await self.inner.company_search(*a, **kw)

    async def job_search(self, *a, **kw):
        return []

    async def web_search(self, *a, **kw):
        return []  # today's web would leak the outcome

    async def web_fetch(self, *a, **kw):
        return None


@contextmanager
def frozen_today(cutoff: date):
    """The ranker computes tenure and company age from date.today(); pin it to the posting date."""
    from app.verify import ranker, verifier

    class _Frozen(date):
        @classmethod
        def today(cls):
            return cutoff

    saved = (ranker.date, verifier.date)
    ranker.date = verifier.date = _Frozen
    try:
        yield
    finally:
        ranker.date, verifier.date = saved


# =============================================================================================== openings

@dataclass
class Opening:
    job_id: str
    title: str
    company: str
    company_id: Any
    posted: str
    city: str | None
    country: str | None
    url: str | None
    industry: str | None
    headcount: int | None
    description: str
    hires: list[dict] = field(default_factory=list)   # {key, keys, name, title, start, url}  (private)

    def brief(self, max_jd: int = 2500) -> str:
        where = ", ".join(x for x in (self.city, self.country) if x)
        about = ", ".join(x for x in (self.industry, f"{self.headcount} people" if self.headcount else None) if x)
        jd = re.sub(r"\s+", " ", self.description or "").strip()[:max_jd]
        return (f"Hiring: {self.title} at {self.company}{f' ({about})' if about else ''}"
                f"{f', {where}' if where else ''}.\n{jd}")


def opening_from_job(j: dict) -> Opening | None:
    g = lambda *ks: people.first(j, *ks)  # noqa: E731
    title, posted = g("job_details.title", "title"), g("metadata.date_added", "date_added")
    cid, cname = g("company.basic_info.crustdata_company_id"), g("company.basic_info.name", "company_name")
    if not (title and posted and (cid or cname)):
        return None
    hc = g("company.headcount.total")
    inds = g("company.basic_info.industries")
    return Opening(
        job_id=str(g("crustdata_job_id", "job_details.job_id") or f"{cname}|{title}|{posted}"),
        title=str(title), company=str(cname or ""), company_id=cid, posted=str(posted)[:10],
        city=g("location.city"), country=g("location.country"), url=g("job_details.url"),
        industry=inds[0] if isinstance(inds, list) and inds else (inds if isinstance(inds, str) else None),
        headcount=int(hc) if isinstance(hc, (int, float)) else None,
        description=str(g("content.description") or ""),
    )


_STAFFING = re.compile(r"staffing|recruit|job ?board|jobgether|talent solutions|manpower|placement|outsourc", re.I)


def _and(*conds):
    conds = [c for c in conds if c]
    return conds[0] if len(conds) == 1 else {"op": "and", "conditions": conds}


class OutOfCredits(SystemExit):
    pass


def _out_of_credits(e: BaseException) -> bool:
    return getattr(e, "status", None) == 402 or "insufficient_credits" in str(e) or " 402" in str(e)


async def _first_ok(label: str, attempts: list[tuple[str, Any]]):
    """Run (name, coroutine factory) in order; return (name, rows) of the first one the API accepts."""
    last = None
    for name, make in attempts:
        try:
            rows = await make()
            log.info("%s: %s -> %d rows", label, name, len(rows))
            return name, rows
        except Exception as e:  # noqa: BLE001
            if _out_of_credits(e):
                raise OutOfCredits(f"Crustdata says the key is out of credits (402) at {label}; stopping. "
                                   "Rerun after a top-up: cached calls and finished openings are reused.") from e
            last = e
            log.info("%s: %s refused (%s)", label, name, str(e)[:200])
    raise RuntimeError(f"{label}: every filter shape was refused; last error: {last}")


def _months(start: date, end: date) -> list[tuple[date, date]]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + cur.month // 12, cur.month % 12 + 1, 1)
        out.append((max(cur, start), min(nxt - timedelta(days=1), end)))
        cur = nxt
    return out


async def fetch_jobs(client, start: str, end: str, country: str | None, categories: list[str], limit: int) -> tuple[str, list[dict]]:
    """Postings across the whole window: one query per month (a single query returns only the newest day)."""
    loc = {"field": "location.country", "type": "=", "value": country} if country else None
    cat = ({"field": "job_details.category", "type": "in", "value": categories} if len(categories) > 1 else
           {"field": "job_details.category", "type": "=", "value": categories[0]}) if categories else None
    lo, hi = _d(start), _d(end)
    months = _months(lo, hi)
    per = max(3, -(-limit // len(months)))
    rows, shape = [], None
    for a, b in months:
        dl = [{"field": "metadata.date_added", "type": "=>", "value": a.isoformat()},
              {"field": "metadata.date_added", "type": "=<", "value": b.isoformat()}]
        attempts = [
            ("date+country+category", lambda dl=dl: client.job_search(_and(*dl, loc, cat), limit=per)),
            ("date(T00:00:00)+country+category", lambda dl=dl: client.job_search(_and(
                *[{**d, "value": d["value"] + "T00:00:00"} for d in dl], loc, cat), limit=per)),
            ("date+country", lambda dl=dl: client.job_search(_and(*dl, loc), limit=per)),
        ]
        try:
            shape, got = await _first_ok(f"job_search {a:%Y-%m}", attempts)
        except RuntimeError as e:
            log.warning("%s", e)
            continue
        except Exception as e:  # noqa: BLE001
            if _out_of_credits(e):
                raise OutOfCredits(f"Crustdata says the key is out of credits (402); stopping. {e}")
            raise
        rows += got
    if shape is None:
        raise RuntimeError("job_search: every month's query was refused")
    rows = [r for r in rows if (dt := _d(people.first(r, "metadata.date_added"))) and lo <= dt <= hi]
    return f"{shape}, {len(months)} monthly queries x {per}", rows


async def find_hires(client, op: Opening, limit: int = 100) -> tuple[list[dict], dict]:
    """People who joined op.company in a matching role within HIRE_HORIZON_DAYS of the posting."""
    posted = _d(op.posted)
    lo, hi = posted - timedelta(days=HIRE_SLACK_DAYS), posted + timedelta(days=HIRE_HORIZON_DAYS)
    rows: dict[str, dict] = {}
    info: dict[str, Any] = {}
    fields = ["crustdata_person_id", "basic_profile", "experience", "social_handles"]
    for kind in ("current", "past"):
        base = f"experience.employment_details.{kind}"
        by_id = {"field": f"{base}.crustdata_company_id", "type": "=", "value": op.company_id} if op.company_id else None
        by_id_in = {"field": f"{base}.crustdata_company_id", "type": "in", "value": [op.company_id]} if op.company_id else None
        by_name = {"field": f"{base}.name", "type": "(.)", "value": op.company}
        since = {"field": f"{base}.start_date", "type": "=>", "value": lo.isoformat()}
        until = {"field": f"{base}.start_date", "type": "=<", "value": hi.isoformat()}
        attempts = []
        # company-id fields are refused by person/search ("Unsupported filter field"); the name match is filtered
        # back to the exact company by id on each employment row (_at_company)
        for label, who in (("name", by_name), ("id", by_id), ("id-in", by_id_in)):
            if not who:
                continue
            for lim in dict.fromkeys((limit, 25)):
                attempts.append((f"{kind}:{label}+window/{lim}", lambda w=who, n=lim: client.person_search(_and(w, since, until), limit=n, fields=fields)))
                attempts.append((f"{kind}:{label}+start/{lim}", lambda w=who, n=lim: client.person_search(_and(w, since), limit=n, fields=fields)))
        try:
            shape, got = await _first_ok(f"hires {op.company}", attempts)
            info[kind] = shape
        except RuntimeError as e:
            info[kind] = f"failed: {e}"
            continue
        for r in got:
            k = person_key(r)
            if k:
                rows.setdefault(k, r)
    hires = []
    for k, r in rows.items():
        jobs = _jobs(r, CUR) + _jobs(r, PAST)
        at = [j for j in jobs if _at_company(j, op.company_id, op.company)]
        if not at:
            continue
        joined = [j for j in at if (s := _d(j.get("start_date"))) and lo <= s <= hi and role_match(op.title, j.get("title"))]
        if not joined:
            continue
        first_start = min(_d(j.get("start_date")) or date.max for j in at)
        if first_start < lo:
            continue  # was already there: an internal move, not a hire from outside
        j = min(joined, key=lambda j: _d(j.get("start_date")))
        hires.append({"key": k, "keys": sorted(keys_of(r)), "name": people.name(r), "title": j.get("title"),
                      "start": str(j.get("start_date"))[:10], "url": people.profile_url(r)})
    info["joiners_seen"] = len(rows)
    return hires, info


async def build_openings(client, args) -> list[Opening]:
    cats = [c for c in (args.categories or "").split(",") if c]
    shape, jobs = await fetch_jobs(client, args.start, args.end, args.country or None, cats, args.job_limit)
    print(f"job search ({shape}): {len(jobs)} postings in {args.start}..{args.end}")
    ops, seen_co = [], {}
    for j in jobs:
        op = opening_from_job(j)
        if not op:
            continue
        if op.headcount is not None and not (MIN_HEADCOUNT <= op.headcount <= MAX_HEADCOUNT):
            continue
        if _STAFFING.search(f"{op.company} {op.industry or ''}"):
            continue  # staffing firms and job boards post for clients; their own joiners aren't the hire
        key = (op.company_id or op.company, core_tokens(op.title).__repr__())
        if key in seen_co:
            continue  # the same role reposted
        seen_co[key] = 1
        ops.append(op)
    random.Random(args.seed).shuffle(ops)
    ops = ops[: args.max_jobs]
    print(f"{len(ops)} distinct postings at {MIN_HEADCOUNT}-{MAX_HEADCOUNT} person companies; finding who joined...")
    kept, why = [], {"no_hire": 0, "ambiguous": 0, "error": 0}
    for i, op in enumerate(ops, 1):
        try:
            hires, info = await find_hires(client, op)
        except Exception as e:  # noqa: BLE001
            if _out_of_credits(e):
                raise OutOfCredits(f"Crustdata says the key is out of credits (402); stopping after {i - 1} postings. {e}")
            why["error"] += 1
            log.warning("hire lookup failed for %s: %s", op.company, e)
            continue
        if not hires:
            why["no_hire"] += 1
        elif len(hires) > MAX_HIRES:
            why["ambiguous"] += 1
        else:
            op.hires = hires
            kept.append(op)
        print(f"  [{i}/{len(ops)}] {op.company[:30]:30} {op.title[:40]:40} joiners={info.get('joiners_seen')} "
              f"hires={len(hires)} ({info.get('current')}; {info.get('past')})")
        if args.target and len(kept) >= args.target:
            break
    print(f"openings with 1-{MAX_HIRES} identified hires: {len(kept)}  (skipped: {why})")
    return kept


# =============================================================================================== run

async def run_opening(client, op: Opening, *, slate: int = DISTRACTORS, verbose: bool = False,
                      talent_flow: bool = True) -> dict:
    """Sourced on one posting, as of the posting date. Returns a private result row (has names)."""
    from app.brief import analyze_brief
    from app.fallbacks import basic_rank, basic_verify

    cutoff = _d(op.posted)
    asof = AsOfClient(client, cutoff, op.company_id, op.company)
    hire_keys = {k for h in op.hires for k in h["keys"]}
    t0 = time.monotonic()
    out: dict[str, Any] = {"job_id": op.job_id, "company": op.company, "title": op.title, "posted": op.posted,
                           "url": op.url, "n_hires": len(op.hires), "hires": op.hires}

    async def emit(ev):
        if verbose:
            print("   ", getattr(ev, "message", ev))

    analysis = await analyze_brief(op.brief())
    crit = analysis.criteria
    crit.hiring_company = op.company if talent_flow else None
    out["criteria"] = {"role": crit.role, "title_variants": crit.title_variants, "locations": crit.locations,
                       "skills": crit.skills[:8]}
    pool = await orchestrator.search_pool(asof, crit, emit)
    out["pool"] = len(pool)
    out["feeder_rows"] = sum(1 for p in pool if p.get("_feeder"))
    out["hire_via_feeder"] = any(p.get("_feeder") and keys_of(p) & hire_keys for p in pool)
    out["asof_search"] = dict(asof.stats)
    in_pool = [p for p in pool if keys_of(p) & hire_keys]
    out["hire_in_pool"] = bool(in_pool)

    pre = {id(p): orchestrator.prescore(p, crit) for p in pool}
    by_pre = sorted(pool, key=lambda p: pre[id(p)], reverse=True)
    sourced_pick = by_pre[: orchestrator.MAX_ENRICH]                       # task A: what Sourced enriches
    others = [p for p in by_pre if not (keys_of(p) & hire_keys)][:slate]   # task B distractors

    # hires not in the pool still get a seat on the task-B slate, from their (as-of) enrich record
    missing = [h for h in op.hires if not any(set(h["keys"]) & keys_of(p) for p in in_pool)]
    hire_rows = list(in_pool)
    urls_missing = [h["url"] for h in missing if h.get("url")]
    if urls_missing:
        got = await asof.person_enrich_many(urls_missing)
        hire_rows += [{**p, "_injected": True} for p in got.values() if p]

    union: dict[str, dict] = {}
    for p in [*sourced_pick, *others, *hire_rows]:
        k = person_key(p)
        if k:
            union.setdefault(k, p)
    urls = [u for u in (people.profile_url(p) for p in union.values()) if u]
    enriched = await asof.person_enrich_many(urls) if urls else {}
    persons = {k: {**p, **(enriched.get(people.profile_url(p)) or {})} for k, p in union.items()}
    companies: dict = {}
    await orchestrator.prefetch_companies(asof, list(persons.values()), companies)

    verify, rank = orchestrator._load_verifier(), orchestrator._load_ranker()
    a_set = {person_key(p) for p in sourced_pick}
    scored: dict[str, dict] = {}
    sem = asyncio.Semaphore(orchestrator.CONCURRENCY)

    async def one(k: str, p: dict):
        async with sem:
            person, company, _ = await orchestrator.enrich(asof, p, enriched, companies)
            try:
                claims, _flags = await verify(person, company, crit, asof, today=cutoff)
            except TypeError:
                claims, _flags = await verify(person, company, crit, asof)
            except Exception:  # noqa: BLE001
                claims, _flags = await basic_verify(person, company, crit, asof)
            try:
                score, _ = await rank(person, claims, crit)
            except Exception:  # noqa: BLE001
                score, _ = await basic_rank(person, claims, crit)
            try:  # parts for offline re-ranking with other move weights (evals.backtest tune)
                from app.verify import ranker as _r
                raw, gapped = _r.rank_parts(person, claims, crit)
                signals = _r.move_signals(person, crit)
            except Exception:  # noqa: BLE001
                raw, gapped, signals = float(score), False, {}
            scored[k] = {"score": int(score), "verified": sum(c.status == "verified" for c in claims),
                         "contradicted": sum(c.status == "contradicted" for c in claims),
                         "prescore": orchestrator.prescore(p, crit), "hire": bool(keys_of(p) & hire_keys),
                         "in_a": k in a_set, "raw": round(raw, 3), "gapped": gapped, "signals": signals,
                         "name": people.name(person), "title": people.title(person)}

    with frozen_today(cutoff):
        await asyncio.gather(*(one(k, p) for k, p in persons.items()))

    def order(keys: list[str]) -> list[str]:
        return sorted(keys, key=lambda k: (scored[k]["score"], scored[k]["verified"], -scored[k]["contradicted"],
                                           scored[k]["prescore"]), reverse=True)

    def best_rank(ranked: list[str]) -> int | None:
        return next((i + 1 for i, k in enumerate(ranked) if scored[k]["hire"]), None)

    a_keys = [person_key(p) for p in sourced_pick if person_key(p) in scored]
    b_keys = [k for k in {person_key(p) for p in [*others, *hire_rows]} if k in scored]
    a_ranked, b_ranked = order(a_keys), order(b_keys)
    b_pre = sorted(b_keys, key=lambda k: scored[k]["prescore"], reverse=True)
    out.update({
        "a_n": len(a_ranked), "a_rank": best_rank(a_ranked),
        "b_n": len(b_ranked), "b_rank": best_rank(b_ranked), "b_rank_prescore": best_rank(b_pre),
        "b_hires": sum(scored[k]["hire"] for k in b_keys),
        "hire_scores": [scored[k]["score"] for k in b_keys if scored[k]["hire"]],
        "top_score": scored[b_ranked[0]]["score"] if b_ranked else None,
        "slate": [{**scored[k], "key": k} for k in b_ranked],
        "seconds": round(time.monotonic() - t0, 1),
    })
    return out


# =============================================================================================== score

def _random_mrr(n: int, h: int) -> float:
    """Expected reciprocal rank of the best of h hires placed uniformly at random among n."""
    if n <= 0 or h <= 0:
        return 0.0
    # P(best rank = r) = C(n-r, h-1) / C(n, h)
    total = math.comb(n, h)
    return sum(math.comb(n - r, h - 1) / total / r for r in range(1, n - h + 2))


def _random_hit(n: int, h: int, k: int) -> float:
    if n <= 0 or h <= 0:
        return 0.0
    k = min(k, n)
    return 1 - math.comb(n - h, k) / math.comb(n, k) if n - h >= k else 1.0


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error")]
    n = len(ok)

    def hit(key, k):
        return sum(1 for r in ok if r.get(key) and r[key] <= k) / n if n else 0.0

    def mrr(key):
        return sum(1 / r[key] for r in ok if r.get(key)) / n if n else 0.0

    b_ok = [r for r in ok if r.get("b_n")]
    return {
        "openings": n, "errors": len(rows) - n,
        "retrieval": sum(r["hire_in_pool"] for r in ok) / n if n else 0.0,
        "a": {**{f"hit@{k}": hit("a_rank", k) for k in KS}, "mrr": mrr("a_rank")},
        "b": {**{f"hit@{k}": hit("b_rank", k) for k in KS}, "mrr": mrr("b_rank")},
        "b_prescore": {**{f"hit@{k}": hit("b_rank_prescore", k) for k in KS}, "mrr": mrr("b_rank_prescore")},
        "b_random": {**{f"hit@{k}": (sum(_random_hit(r["b_n"], r["b_hires"], k) for r in b_ok) / n if n else 0.0) for k in KS},
                     "mrr": sum(_random_mrr(r["b_n"], r["b_hires"]) for r in b_ok) / n if n else 0.0},
        "avg_slate": sum(r.get("b_n", 0) for r in ok) / n if n else 0.0,
        "avg_pool": sum(r.get("pool", 0) for r in ok) / n if n else 0.0,
    }


def scorecard(rows: list[dict], meta: dict) -> str:
    s = summarize(rows)
    pct = lambda x: f"{100 * x:.0f}%"  # noqa: E731
    line = lambda name, d: f"| {name} | " + " | ".join(pct(d[f'hit@{k}']) for k in KS) + f" | {d['mrr']:.3f} |"  # noqa: E731
    out = [
        "# Backtest: does Sourced find the people who were actually hired?",
        "",
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} from live Crustdata data. "
        f"Postings added {meta.get('start')}..{meta.get('end')}"
        + (f", {meta.get('country')}" if meta.get('country') else "")
        + (f", categories {meta.get('categories')}" if meta.get('categories') else "") + ".",
        "No person names appear in this file. Each real hire is identified only by rank.",
        "",
        f"**{s['openings']} real openings** with 1-{MAX_HIRES} identified hires each"
        + (f" ({s['errors']} runs errored and are excluded)" if s["errors"] else "") + ". "
        f"Average as-of search pool: {s['avg_pool']:.0f} people. Average ranking slate: {s['avg_slate']:.1f}.",
        "",
        "## Results",
        "",
        f"- **Retrieval:** a real hire was in Sourced's own search pool for **{pct(s['retrieval'])}** of openings.",
        "- **End to end (A):** Sourced as shipped: search, enrich its top "
        f"{orchestrator.MAX_ENRICH} by prescore, verify, rank. Did the real hire make that list, and where?",
        f"- **Ranking (B):** real hire(s) plus up to {DISTRACTORS} of the strongest other people from the same as-of "
        "pool, all verified and ranked the same way. Where does the person who got the job land?",
        "",
        "| | " + " | ".join(f"hit@{k}" for k in KS) + " | MRR |",
        "|---|" + "---|" * (len(KS) + 1),
        line("A: Sourced end to end", s["a"]),
        line("B: Sourced ranker", s["b"]),
        line("B baseline: search prescore order", s["b_prescore"]),
        line("B baseline: random order (expected)", s["b_random"]),
        "",
        "## Per opening",
        "",
        "| # | Company | Posting | Posted | Hires | Pool | Hire in pool | A rank | B rank / slate | B prescore rank |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        if r.get("error"):
            out.append(f"| {i} | {r['company']} | {r['title']} | {r['posted']} | {r.get('n_hires')} | | error | | | |")
            continue
        out.append(f"| {i} | {r['company']} | {r['title'][:60]} | {r['posted']} | {r['n_hires']} | {r['pool']} | "
                   f"{'yes' if r['hire_in_pool'] else 'no'} | {r['a_rank'] or '-'} | "
                   f"{r['b_rank'] or '-'} / {r['b_n']} | {r['b_rank_prescore'] or '-'} |")
    out += [
        "",
        "## How it was run",
        "",
        "- Openings: Crustdata Job Search, postings at companies of "
        f"{MIN_HEADCOUNT}-{MAX_HEADCOUNT} people, one per company and role. Staffing firms and job boards are "
        "excluded, since they post for clients and their own joiners aren't the hire.",
        f"- Real hire: someone whose job at that company started between {HIRE_SLACK_DAYS} days before and "
        f"{HIRE_HORIZON_DAYS} days after the posting date, in a role whose title matches the posting, and who was not "
        "already at the company (internal moves are excluded). Found with Crustdata Person Search on current and "
        f"past employers. Openings with more than {MAX_HIRES} matching joiners are dropped as ambiguous.",
        "- Knowledge cutoff = posting date. Every person record Sourced sees is rewritten to how it read on that date: "
        "later jobs are removed (a start in the posting month counts as later), jobs that ended later are current "
        "again, the current title is recomputed, and a headline or summary naming a later employer is blanked. Search "
        "filters on the current job also match past jobs, and each row is re-checked against the original filter on "
        "its as-of record. Web search and fetch are off. The verifier and ranker run with today = posting date.",
        "- The brief is the posting itself: title, company, location and the first 2,500 characters of the JD.",
        "- Known leaks the data can't remove: location and skills are today's values, and candidates' employer records "
        "(headcount, funding) are today's.",
        "- Reproduce: `cd backend && python -m evals.backtest all` (needs `CRUSTDATA_API_KEY`; `LLM_MODE=live` for "
        "Gemini brief parsing). Private per-person results stay in `backend/data/backtest/` (gitignored).",
    ]
    return "\n".join(out) + "\n"


# =============================================================================================== tune

TUNE_GRID = {"sweet_spot": (0, 2, 4, 6), "due": (0, 2, 4, 6), "between_jobs": (0, 2, 4, 6), "step_up": (0, 2, 4),
             "adjacent_title": (0, 2, 4), "just_moved": (0, -2, -4, -6), "overqualified": (0, -2, -4, -6)}
FOLDS = 5


def _fold(job_id: str) -> int:
    import hashlib
    return int(hashlib.sha1(str(job_id).encode()).hexdigest(), 16) % FOLDS


def rerank(row: dict, w: dict[str, float]) -> tuple[int | None, int | None]:
    """(A rank, B rank) of the best real hire when the slate is re-scored with move weights `w`."""
    from app.verify.ranker import final_score, move_bonus

    def key(c):
        f = final_score(c["raw"], c["gapped"], move_bonus(c.get("signals") or {}, w)[0])
        return (f, c["verified"], -c["contradicted"], c["prescore"])

    def best(cands):
        ranked = sorted(cands, key=key, reverse=True)
        return next((i + 1 for i, c in enumerate(ranked) if c["hire"]), None)

    slate = row.get("slate") or []
    b = best(slate)
    a = best([c for c in slate if c.get("in_a")])  # Sourced's own top MAX_ENRICH are all on the slate
    return a, b


def _metrics(ranks: list[int | None]) -> dict:
    n = len(ranks) or 1
    return {**{f"hit@{k}": sum(1 for r in ranks if r and r <= k) / n for k in KS},
            "mrr": sum(1 / r for r in ranks if r) / n}


def _objective(rows: list[dict], w: dict) -> tuple[float, float]:
    ranks = [rerank(r, w)[1] for r in rows]
    m = _metrics(ranks)
    return m["mrr"], m["hit@5"]


def fit_weights(rows: list[dict]) -> dict[str, float]:
    """Coordinate ascent over TUNE_GRID on task-B MRR (hit@5 breaks ties). Starts at zero and only moves a weight
    on a strict improvement, so signals that don't help stay off."""
    w = {k: 0.0 for k in TUNE_GRID}
    best = _objective(rows, w)
    for _ in range(3):
        moved = False
        for sig, vals in TUNE_GRID.items():
            for v in vals:
                if v == w[sig]:
                    continue
                cand = {**w, sig: float(v)}
                obj = _objective(rows, cand)
                if obj > best:
                    best, w, moved = obj, cand, True
        if not moved:
            break
    return w


def tune(rows: list[dict]) -> dict:
    rows = [r for r in rows if not r.get("error") and r.get("slate") and "raw" in r["slate"][0]]
    if len(rows) < FOLDS:
        raise SystemExit(f"need at least {FOLDS} scored openings with saved slates to tune, have {len(rows)}")
    zero = {k: 0.0 for k in TUNE_GRID}
    before_a, before_b, after_a, after_b, fold_w = [], [], [], [], []
    for f in range(FOLDS):
        train = [r for r in rows if _fold(r["job_id"]) != f]
        test = [r for r in rows if _fold(r["job_id"]) == f]
        if not test:
            continue
        w = fit_weights(train)
        fold_w.append(w)
        for r in test:
            a0, b0 = rerank(r, zero)
            a1, b1 = rerank(r, w)
            before_a.append(a0); before_b.append(b0); after_a.append(a1); after_b.append(b1)
    final = fit_weights(rows)
    return {"openings": len(rows), "folds": FOLDS,
            "heldout_before": {"a": _metrics(before_a), "b": _metrics(before_b)},
            "heldout_after": {"a": _metrics(after_a), "b": _metrics(after_b)},
            "fold_weights": fold_w, "weights": {k: v for k, v in final.items()},
            "in_sample_after": {"b": _metrics([rerank(r, final)[1] for r in rows])}}


def tune_section(t: dict) -> str:
    pct = lambda x: f"{100 * x:.0f}%"  # noqa: E731
    row = lambda name, d: f"| {name} | " + " | ".join(pct(d[f'hit@{k}']) for k in KS) + f" | {d['mrr']:.3f} |"  # noqa: E731
    on = {k: v for k, v in t["weights"].items() if v}
    return "\n".join([
        "## Tuning: who is ready to move",
        "",
        "Fit alone doesn't say who takes the job. Sourced's ranker now adds a capped likelihood-to-move bonus read from "
        "employment history alone: 1.5-4 years into the current role, at or past their usual tenure, between jobs, a "
        "one-level step up, the same work under a different title, and negatives for a very recent move or being "
        f"overqualified. Weights were fitted by coordinate ascent on task-B MRR. The numbers below are **{t['folds']}-fold "
        f"cross-validated on {t['openings']} openings**: every opening is scored with weights fitted only on the other folds.",
        "",
        "| Held-out openings | " + " | ".join(f"hit@{k}" for k in KS) + " | MRR |",
        "|---|" + "---|" * (len(KS) + 1),
        row("A before (fit only)", t["heldout_before"]["a"]),
        row("A after (fit + move)", t["heldout_after"]["a"]),
        row("B before (fit only)", t["heldout_before"]["b"]),
        row("B after (fit + move)", t["heldout_after"]["b"]),
        "",
        f"Weights fitted on all openings (shipped as `MOVE_WEIGHTS`): `{json.dumps(on) if on else 'all zero: no signal helped'}`. "
        "Per-fold weights: " + "; ".join(f"`{json.dumps({k: v for k, v in w.items() if v})}`" for w in t["fold_weights"]) + ".",
        "",
    ])


# =============================================================================================== diagnose

def diagnose(rows: list[dict]) -> str:
    """Why do real hires rank where they do? Prints titles and score parts only, never names."""
    from statistics import median
    out, agg = [], {"hires": 0, "no_title": 0, "title_matches_posting": 0, "title_matches_variant": 0,
                    "gapped": 0, "contradicted": 0, "below_median": 0, "injected": 0}
    sig_h, sig_o = {}, {}
    for r in rows:
        if r.get("error") or not r.get("slate"):
            continue
        slate = r["slate"]
        others = [c for c in slate if not c["hire"]]
        med = median([c["score"] for c in others]) if others else 0
        variants = (r.get("criteria") or {}).get("title_variants") or []
        out.append(f"\n## {r['company']} | {r['title']} | posted {r['posted']} | pool {r.get('pool')} | "
                   f"variants {variants} | locs {(r.get('criteria') or {}).get('locations')}")
        out.append(f"   others: median score {med}, top titles {[c.get('title') for c in sorted(others, key=lambda c: -c['score'])[:3]]}")
        for h in r.get("hires") or []:
            out.append(f"   joined as: {h.get('title')} on {h.get('start')}")
        for c in slate:
            if not c["hire"]:
                continue
            agg["hires"] += 1
            t = c.get("title")
            agg["no_title"] += not t
            agg["title_matches_posting"] += bool(t and role_match(r["title"], t))
            agg["title_matches_variant"] += bool(t and any(_fuzzy(t, v) for v in variants))
            agg["gapped"] += bool(c.get("gapped"))
            agg["contradicted"] += bool(c.get("contradicted"))
            agg["below_median"] += c["score"] < med
            for k, v in (c.get("signals") or {}).items():
                sig_h[k] = sig_h.get(k, 0) + v
            on = [k for k, v in (c.get("signals") or {}).items() if v]
            out.append(f"   HIRE as-of title={t!r} score={c['score']} raw={c.get('raw')} gapped={c.get('gapped')} "
                       f"verified={c['verified']} contradicted={c['contradicted']} prescore={c['prescore']} signals={on}")
        for c in others:
            for k, v in (c.get("signals") or {}).items():
                sig_o[k] = sig_o.get(k, 0) + v
    n_o = sum(len([c for c in r.get("slate") or [] if not c["hire"]]) for r in rows if not r.get("error")) or 1
    head = [f"# Backtest diagnosis ({agg['hires']} real hires on slates)", "", json.dumps(agg),
            "signal rate, hires vs others: " + json.dumps({k: (round(sig_h.get(k, 0) / max(1, agg['hires']), 2),
                                                                round(sig_o.get(k, 0) / n_o, 2)) for k in sig_o})]
    return "\n".join(head + out) + "\n"


# =============================================================================================== cli

def _save_openings(ops: list[Opening], meta: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "openings.json").write_text(json.dumps({"meta": meta, "openings": [o.__dict__ for o in ops]}, indent=1, default=str))


def _load_openings() -> tuple[list[Opening], dict]:
    d = json.loads((DATA_DIR / "openings.json").read_text())
    return [Opening(**o) for o in d["openings"]], d.get("meta", {})


async def cmd_probe(client, args):
    """Cheap check of which filter shapes the live API accepts (limit 2)."""
    print("job search:")
    cats = [c for c in (args.categories or "").split(",") if c]
    try:
        shape, jobs = await fetch_jobs(client, args.start, args.end, args.country or None, cats, 3)
        print(f"  OK via {shape}: {len(jobs)} rows")
        for j in jobs[:3]:
            op = opening_from_job(j)
            print("   ", op and (op.company, op.title, op.posted, op.company_id, op.headcount))
    except Exception as e:  # noqa: BLE001
        print("  FAILED:", e)
        jobs = []
    op = next((o for o in map(opening_from_job, jobs) if o), None)
    if op:
        hires, info = await find_hires(client, op, limit=5)
        print(f"hire search on {op.company}: {info}; hires={len(hires)}")
    print("widened person search (current OR past title):")
    try:
        rows = await client.person_search(widen_to_past({"field": f"{CUR}.title", "type": "(.)", "value": "backend engineer"}),
                                          limit=2, fields=orchestrator.PERSON_SEARCH_FIELDS + ["skills"])
        print(f"  OK: {len(rows)} rows")
    except Exception as e:  # noqa: BLE001
        print("  REFUSED:", e)


async def main_async(args) -> int:
    global DATA_DIR
    if args.tag:
        DATA_DIR = DATA_DIR / args.tag
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    client, note = orchestrator.make_client()
    if note:
        print("WARNING:", note)
    meta = {"start": args.start, "end": args.end, "country": args.country, "categories": args.categories}
    try:
        if args.cmd == "probe":
            await cmd_probe(client, args)
            return 0
        if args.cmd == "diagnose":
            rows = [json.loads(x) for x in (DATA_DIR / "results.jsonl").read_text().splitlines() if x.strip()]
            print(diagnose(rows))
            return 0
        if args.cmd == "openings" or (args.cmd == "all" and not args.openings_from):
            ops = await build_openings(client, args)
            _save_openings(ops, meta)
            print(f"saved {DATA_DIR / 'openings.json'}")
        if args.cmd in ("run", "all") and args.openings_from and not (DATA_DIR / "openings.json").exists():
            src = DATA_DIR.parent / args.openings_from / "openings.json"
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / "openings.json").write_text(src.read_text())
        if args.cmd in ("run", "all"):
            ops, meta = _load_openings()
            if args.limit:
                ops = ops[: args.limit]
            res_path = DATA_DIR / "results.jsonl"
            done = {}
            if res_path.exists() and not args.fresh:
                for line in res_path.read_text().splitlines():
                    r = json.loads(line)
                    if not r.get("error"):
                        done[r["job_id"]] = r
            with res_path.open("w") as f:
                for i, op in enumerate(ops, 1):
                    r = done.get(op.job_id)
                    if r is None:
                        try:
                            r = await run_opening(client, op, slate=args.slate, verbose=args.verbose,
                                                  talent_flow=not args.no_talent_flow)
                        except Exception as e:  # noqa: BLE001
                            if _out_of_credits(e):
                                raise OutOfCredits(f"Crustdata says the key is out of credits (402); stopped at "
                                                   f"opening {i}. Finished ones are saved in {res_path}. {e}")
                            log.exception("run failed")
                            r = {"job_id": op.job_id, "company": op.company, "title": op.title, "posted": op.posted,
                                 "n_hires": len(op.hires), "error": f"{type(e).__name__}: {e}"}
                    f.write(json.dumps(r, default=str) + "\n")
                    f.flush()
                    print(f"  [{i}/{len(ops)}] {op.company[:28]:28} {op.title[:36]:36} pool={r.get('pool')} "
                          f"in_pool={r.get('hire_in_pool')} A={r.get('a_rank')} B={r.get('b_rank')}/{r.get('b_n')} "
                          f"{r.get('error') or ''}")
        if args.cmd in ("score", "run", "tune", "all"):
            rows = [json.loads(x) for x in (DATA_DIR / "results.jsonl").read_text().splitlines() if x.strip()]
            if not meta.get("start") and (DATA_DIR / "openings.json").exists():
                meta = _load_openings()[1]
            md = scorecard(rows, meta)
            tpath = DATA_DIR / "tune.json"
            if args.cmd in ("tune", "all"):
                t = tune(rows)
                tpath.write_text(json.dumps(t, indent=1))
                print("tuned weights:", json.dumps(t["weights"]))
                print(f"set them with RANK_MOVE_WEIGHTS='{json.dumps({k: v for k, v in t['weights'].items() if v})}'")
            if tpath.exists():
                md += "\n" + tune_section(json.loads(tpath.read_text()))
            print(md)
            if args.out:
                Path(args.out).write_text(md)
                print(f"wrote {args.out}")
    finally:
        if hasattr(client, "aclose"):
            await client.aclose()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["probe", "openings", "run", "score", "tune", "diagnose", "all"])
    ap.add_argument("--start", default=WINDOW_START)
    ap.add_argument("--end", default=WINDOW_END)
    ap.add_argument("--country", default="India")
    ap.add_argument("--categories", default="Engineering", help="comma separated job_details.category values, '' = all")
    ap.add_argument("--job-limit", type=int, default=200, help="rows to ask Job Search for")
    ap.add_argument("--max-jobs", type=int, default=120, help="postings to look up hires for")
    ap.add_argument("--target", type=int, default=0, help="stop once this many openings have hires")
    ap.add_argument("--limit", type=int, default=0, help="run only the first N openings")
    ap.add_argument("--slate", type=int, default=DISTRACTORS)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--fresh", action="store_true", help="ignore earlier results.jsonl")
    ap.add_argument("--no-talent-flow", action="store_true", help="Sourced without the talent-flow search (ablation)")
    ap.add_argument("--out", default="")
    ap.add_argument("--tag", default="", help="keep this run's files in backend/data/backtest/<tag>/ (e.g. dev, test-before)")
    ap.add_argument("--openings-from", default="", help="reuse openings.json from another tag (same openings, other config)")
    ap.add_argument("-v", "--verbose", action="store_true")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
