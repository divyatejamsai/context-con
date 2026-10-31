"""Normalise Crustdata person/company dicts into flat facts, each with the field path it came from.

Crustdata's response shape varies between endpoints and API versions, so every accessor tries
several known paths and records which one hit. That path becomes Source.field on the claim.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


def get_path(d: Any, path: str) -> Any:
    """Read 'a.b[0].c' from nested dicts/lists. Returns None on any miss."""
    cur = d
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if cur is None:
            return None
        if part.startswith("["):
            idx = int(part[1:-1])
            if not isinstance(cur, list) or idx >= len(cur):
                return None
            cur = cur[idx]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def first(d: Any, *paths: str) -> tuple[Any, str | None]:
    """First non-empty value among paths, plus the path that produced it."""
    for p in paths:
        v = get_path(d, p)
        if v not in (None, "", [], {}):
            return v, p
    return None, None


def parse_date(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):
        if 1800 <= v <= 2200:  # a bare year, e.g. year_founded: 2014
            return date(int(v), 1, 1)
        try:  # epoch seconds or ms
            return datetime.utcfromtimestamp(v / 1000 if v > 1e11 else v).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    for fmt in ("%b %Y", "%B %Y", "%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def norm(s: Any) -> str:
    """Lowercase, accents folded (Nestlé -> nestle), punctuation to spaces. Non-Latin letters (群益金鼎, Яндекс) are kept,
    so names in other scripts don't normalise to an empty string and fail every comparison."""
    t = unicodedata.normalize("NFKD", str(s or "")).lower()
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^\w ]+|_", " ", t).strip()


_COMPANY_SUFFIX = re.compile(
    r"\b(inc|llc|ltd|limited|pvt|private|corp|corporation|co|company|technologies|technology|tech|labs|gmbh|plc|india|software)\b"
)


def company_key(s: Any) -> str:
    return re.sub(r"\s+", " ", _COMPANY_SUFFIX.sub(" ", norm(s))).strip()


def same_company(a: Any, b: Any) -> bool:
    ka, kb = company_key(a), company_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb.split() or kb in ka.split() or ka.replace(" ", "") == kb.replace(" ", "")


def tokens(s: Any) -> set[str]:
    return {t for t in norm(s).split() if len(t) > 1}


def title_similarity(a: Any, b: Any) -> float:
    ta, tb = tokens(expand_title(a)), tokens(expand_title(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_TITLE_ABBREV = {
    "sr": "senior", "jr": "junior", "eng": "engineer", "engg": "engineer", "swe": "software engineer",
    "sde": "software engineer", "dev": "developer", "mgr": "manager", "vp": "vice president",
    "ml": "machine learning", "pm": "product manager", "em": "engineering manager",
}


def expand_title(s: Any) -> str:
    return " ".join(_TITLE_ABBREV.get(t, t) for t in norm(s).split())


SENIOR_WORDS = {"senior", "staff", "principal", "lead", "head", "director", "vice", "chief", "architect"}


def seniority_rank(title: Any) -> int:
    t = tokens(expand_title(title))
    if t & {"chief", "vice", "director", "head", "cxo", "owner", "partner", "founder", "cto", "ceo"}:
        return 4
    if t & {"principal", "staff", "architect"}:
        return 3
    if t & {"senior", "lead"}:
        return 2
    if t & {"junior", "intern", "trainee", "associate"}:
        return 0
    return 1


@dataclass
class Job:
    company: str | None
    title: str | None
    start: date | None
    end: date | None
    company_id: Any = None
    domain: str | None = None
    path: str = ""  # e.g. current_employers[0]
    seniority_level: str | None = None
    company_headcount: int | None = None  # job-level company facts that Person Enrich carries
    company_headcount_range: str | None = None
    company_industry: str | None = None
    company_description: str | None = None


@dataclass
class Profile:
    name: str | None = None
    name_field: str | None = None
    headline: str | None = None
    headline_field: str | None = None
    location: str | None = None
    location_field: str | None = None
    profile_url: str | None = None
    current: list[Job] = field(default_factory=list)
    past: list[Job] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    skills_field: str | None = None
    education: list[dict] = field(default_factory=list)  # {school, degree, field_of_study, end_year, path}
    endpoint: str = "person/enrich"


_CURRENT_PATHS = ("current_employers", "experience.employment_details.current", "employment_details.current", "current_positions")
_PAST_PATHS = ("past_employers", "experience.employment_details.past", "employment_details.past", "past_positions")


def _jobs(person: dict, paths: tuple[str, ...]) -> list[Job]:
    items, p = first(person, *paths)
    if not isinstance(items, list):
        return []
    out = []
    for i, e in enumerate(items):
        if not isinstance(e, dict):
            continue
        company, _ = first(e, "employer_name", "company_name", "name", "company.name", "company")
        title, _ = first(e, "employee_title", "title", "position", "job_title")
        start, _ = first(e, "start_date", "started_at", "date_from", "start")
        end, _ = first(e, "end_date", "ended_at", "date_to", "end")
        cid, _ = first(e, "crustdata_company_id", "employer_company_id", "company_id", "company.id")
        dom, _ = first(e, "employer_company_website_domain", "company_website_domain", "company_domain", "domain", "company.domain")
        if isinstance(dom, list):
            dom = dom[0] if dom else None
        level, _ = first(e, "seniority_level", "seniority")
        hc, _ = first(e, "company_headcount_latest")
        hc_range, _ = first(e, "company_headcount_range")
        ind, _ = first(e, "company_professional_network_industry", "company_industries[0]")
        desc, _ = first(e, "company_description")
        out.append(Job(company if isinstance(company, str) else None, title, parse_date(start), parse_date(end), cid, dom,
                       f"{p}[{i}]", level if isinstance(level, str) else None,
                       hc if isinstance(hc, int) else None, hc_range if isinstance(hc_range, str) else None,
                       ind if isinstance(ind, str) else None, desc if isinstance(desc, str) else None))
    return out


def unwrap_record(d: Any, key: str = "person_data") -> dict:
    """Accept a raw cached response ({response: [{matches: [{person_data}]}]}) as well as a bare record."""
    if isinstance(d, dict) and "response" in d and not d.get("basic_profile"):
        d = d["response"]
    if isinstance(d, list):
        d = d[0] if d else {}
    if isinstance(d, dict) and isinstance(d.get("matches"), list):
        m = d["matches"][0] if d["matches"] else {}
        d = (m.get(key) if isinstance(m, dict) else None) or {}
    return d if isinstance(d, dict) else {}


def load_person(person: dict) -> Profile:
    person = unwrap_record(person)
    pr = Profile()
    pr.endpoint = get_path(person, "_source.endpoint") or "person/enrich"
    pr.name, pr.name_field = first(person, "name", "basic_profile.name", "full_name")
    pr.headline, pr.headline_field = first(person, "headline", "basic_profile.headline", "title")
    loc, pr.location_field = first(
        person, "location", "basic_profile.location.full_location", "basic_profile.location.raw",
        "basic_profile.location", "location_details.raw", "region",
    )
    if isinstance(loc, dict):
        loc = ", ".join(str(v) for k, v in loc.items() if v and k in ("city", "state", "country", "full_location", "raw"))
    pr.location = loc or None
    pr.profile_url, _ = first(
        person, "linkedin_profile_url", "profile_url", "flagship_profile_url",
        "social_handles.professional_network_identifier.profile_url",
    )
    pr.current = [j for j in _jobs(person, _CURRENT_PATHS) if j.company]
    cur_title, _ = first(person, "basic_profile.current_title", "current_title")
    if pr.current and not pr.current[0].title and isinstance(cur_title, str):
        pr.current[0].title = cur_title
    pr.past = [j for j in _jobs(person, _PAST_PATHS) if j.company]
    pr.current.sort(key=lambda j: j.start or date.min, reverse=True)
    skills, pr.skills_field = first(person, "skills.professional_network_skills", "skills.skills", "skills", "basic_profile.skills")
    if isinstance(skills, dict):
        skills = [s for v in skills.values() if isinstance(v, list) for s in v]
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,;|]", skills)]
    pr.skills = [s for s in (skills or []) if isinstance(s, str) and s]
    pr.education = _education(person)
    return pr


def _education(person: dict) -> list[dict]:
    for path in ("education.schools", "education", "education_background", "schools"):
        rows = get_path(person, path)
        if isinstance(rows, list) and rows:
            out = []
            for i, r in enumerate(rows):
                if not isinstance(r, dict):
                    continue
                school = r.get("school") or r.get("institute_name") or r.get("school_name") or r.get("name")
                if isinstance(school, str) and school.strip():
                    out.append({"school": school.strip(), "degree": r.get("degree") or r.get("degree_name"),
                                "field_of_study": r.get("field_of_study"), "end_year": r.get("end_year"),
                                "path": f"{path}[{i}].school"})
            if out:
                return out
    return []


_SCHOOL_STOP = {"of", "and", "the", "for", "at", "in", "de"}


def _acronym(name: str) -> str:
    return "".join(w[0] for w in norm(name).split() if w not in _SCHOOL_STOP and not w.isdigit())


def school_matches(wanted: Any, have: Any) -> bool:
    """Does the school on a record ("Indian Institute of Technology, Bombay") match a school the brief asks for
    ("IIT", "IIT Bombay", "Indian Institute of Technology")? Word-level, plus acronyms of the record's name, so
    "IIT" never matches "IIIT Hyderabad" and "BITS" matches "Birla Institute of Technology and Science, Pilani"."""
    w, h = norm(wanted).split(), norm(have).split()
    if not w or not h:
        return False
    hs = set(h)
    acr = _acronym(str(have))
    for i, t in enumerate(w):
        dep = t[:-1] if len(t) > 3 and t.endswith("s") and t[:-1].isalpha() else t  # "IITs" -> "iit"
        if t in hs or dep in hs or (i == 0 and len(dep) >= 2 and len(dep) <= 6 and acr.startswith(dep)):
            continue
        return False
    return True


_DEGREE_ALIASES = {
    "btech": ("bachelor of technology", "b tech", "btech", "bachelor of engineering", "be"),
    "be": ("bachelor of engineering", "be", "b e", "bachelor of technology", "b tech", "btech"),
    "mtech": ("master of technology", "m tech", "mtech", "master of engineering", "me"),
    "mba": ("master of business administration", "mba", "pgdm", "post graduate diploma in management", "pgp"),
    "pgdm": ("post graduate diploma in management", "pgdm", "mba", "master of business administration"),
    "phd": ("doctor of philosophy", "phd", "ph d", "doctorate"),
    "ms": ("master of science", "ms", "m s", "msc", "m sc"), "masters": ("master",), "master": ("master",),
    "bachelors": ("bachelor",), "bachelor": ("bachelor",), "bsc": ("bachelor of science", "bsc", "b sc"),
    "msc": ("master of science", "msc", "m sc", "ms"),
}


def degree_matches(wanted: Any, have: Any) -> bool:
    w, h = norm(wanted), f" {norm(have)} "
    if not w or not h.strip():
        return False
    key = w.replace(" ", "")
    for alias in _DEGREE_ALIASES.get(key, (w,)):
        if f" {alias} " in h or (len(alias) > 6 and alias in h):
            return True
    return False


@dataclass
class CompanyFacts:
    name: str | None = None
    headcount: int | None = None
    headcount_field: str | None = None
    stage: str | None = None
    stage_field: str | None = None
    total_funding: float | None = None
    founded: int | None = None
    industry: str | None = None
    domain: str | None = None
    endpoint: str = "company/enrich"


def load_company(company: dict | None) -> CompanyFacts | None:
    if not company:
        return None
    c = CompanyFacts()
    c.endpoint = get_path(company, "_source.endpoint") or "company/enrich"
    c.name, _ = first(company, "company_name", "name", "basic_info.name", "basic_info.company_name")
    hc, c.headcount_field = first(
        company, "headcount.total", "headcount.linkedin_headcount", "headcount", "employee_count",
        "basic_info.employee_count", "linkedin_headcount",
    )
    try:
        c.headcount = int(hc) if hc is not None and not isinstance(hc, dict) else None
    except (TypeError, ValueError):
        c.headcount = None
    c.stage, c.stage_field = first(
        company, "funding.last_round_type", "funding_and_investment.last_funding_round_type",
        "last_funding_round_type", "funding.last_fundraise_type", "company_type", "basic_info.company_type",
    )
    if not re.search(r"series [a-j]\b|seed|angel|ipo|public", norm(c.stage)):
        # last_round_type is often secondary_market / corporate_round; use the latest priced round instead.
        ms = get_path(company, "funding.milestones") or []
        for i, m in enumerate(ms if isinstance(ms, list) else []):
            rt = m.get("round_type") if isinstance(m, dict) else None
            if rt and re.search(r"series [a-j]\b|seed|angel|ipo", norm(rt)):
                c.stage, c.stage_field = rt, f"funding.milestones[{i}].round_type"
                break
    if isinstance(c.stage, str):
        c.stage = re.sub(r"\bIpo\b", "IPO", norm(c.stage).title())
    tf, _ = first(company, "funding.total_investment_usd", "funding_and_investment.crunchbase_total_investment_usd",
                  "total_investment_usd", "funding_and_investment.total_investment_usd")
    try:
        c.total_funding = float(tf) if tf is not None else None
    except (TypeError, ValueError):
        c.total_funding = None
    yf, _ = first(company, "year_founded", "basic_info.year_founded", "founded_year")
    c.founded = parse_date(yf).year if parse_date(yf) else None
    c.industry, _ = first(company, "taxonomy.professional_network_industry", "linkedin_industries[0]", "industry", "basic_info.industries[0]", "taxonomy.linkedin_industry")
    c.domain, _ = first(company, "company_website_domain", "website_domain", "basic_info.primary_domain", "domain")
    return c


def stage_bucket(c: CompanyFacts | None) -> str | None:
    """Coarse stage label used for matching brief preferences: seed / early / growth / late / public / enterprise."""
    if c is None:
        return None
    s = norm(c.stage)
    if "ipo" in s or "public" in s or "post ipo" in s:
        return "public"
    if any(k in s for k in ("pre seed", "seed", "angel")):
        return "seed"
    if "series a" in s or "series b" in s:
        return "early"
    if "series c" in s or "series d" in s:
        return "growth"
    if re.search(r"series [e-j]\b", s) or "private equity" in s:
        return "late"
    if c.headcount is not None:
        if c.headcount < 50:
            return "seed"
        if c.headcount < 300:
            return "early"
        if c.headcount < 1500:
            return "growth"
        return "enterprise"
    return None


def unwrap_url(url: Any) -> str | None:
    """Google redirect links (google.com/url?q=...) -> the real target URL."""
    if not isinstance(url, str) or not url:
        return None
    from urllib.parse import parse_qs, unquote, urlparse

    u = urlparse(url)
    if "google." in u.netloc and u.path in ("/url", "/imgres", "/aclk", "/goto"):
        qs = parse_qs(u.query)
        for k in ("q", "url", "imgurl", "adurl"):
            if qs.get(k) and qs[k][0].startswith("http"):
                return unquote(qs[k][0])
    return url


def skill_matches(wanted: str, have: str) -> bool:
    """'Python' matches 'Python (Programming Language)'; 'Distributed Systems' matches 'Distributed Systems Design'."""
    w = norm(wanted)
    h = norm(re.sub(r"\([^)]*\)", " ", have))
    if not w or not h:
        return False
    return w == h or w.replace(" ", "") == h.replace(" ", "") or bool(re.search(rf"\b{re.escape(w)}\b", h))


# Brief "skills" that are really domains. Evidence can come from employer industry, name or description.
DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "payments": ("payment", "payments", "fintech", "financial services", "banking", "bank", "upi", "cards", "wallet", "lending", "remittance"),
    "fintech": ("fintech", "financial services", "payment", "payments", "banking", "lending", "insurance", "wealth", "trading"),
    "financial services": ("financial services", "banking", "bank", "investment", "capital markets", "fintech"),
    "banking": ("banking", "bank", "financial services"),
    "trading": ("trading", "capital markets", "investment management", "hedge fund", "brokerage", "exchange"),
    "crypto": ("crypto", "blockchain", "web3", "digital assets", "defi"),
    "ecommerce": ("e commerce", "ecommerce", "retail", "marketplace", "online shopping"),
    "e commerce": ("e commerce", "ecommerce", "retail", "marketplace"),
    "healthcare": ("healthcare", "health", "hospital", "medical", "pharma", "biotech"),
    "healthtech": ("healthcare", "health", "medical", "hospital"),
    "edtech": ("education", "e learning", "edtech", "learning"),
    "logistics": ("logistics", "supply chain", "transportation", "delivery", "freight"),
    "gaming": ("gaming", "games", "computer games", "esports"),
    "saas": ("saas", "software development", "software as a service", "b2b software"),
    "adtech": ("advertising", "adtech", "marketing technology"),
    "insurance": ("insurance", "insurtech"),
}


def domain_terms(skill: str) -> tuple[str, ...]:
    k = norm(skill)
    return DOMAIN_KEYWORDS.get(k) or DOMAIN_KEYWORDS.get(k.rstrip("s")) or ()


def funding_stage_known(c: CompanyFacts | None) -> bool:
    """True when the stage comes from an actual funding round or listing, not from headcount."""
    return bool(c and re.search(r"series [a-j]\b|seed|angel|ipo|public", norm(c.stage)))
