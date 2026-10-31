"""Brief parsing: messy free text -> Criteria, plus the search broadening ladder."""
from __future__ import annotations

import logging
import re

from . import llm
from .schemas import Criteria

log = logging.getLogger(__name__)

PARSE_PROMPT = """You are a senior technical recruiter. Turn this hiring brief into structured search criteria.
The brief may be vague, abbreviated or misspelled; fix typos and expand abbreviations ("eng" = engineer, "blr" = Bangalore).

Rules:
- role: one clean canonical job title.
- title_variants: 3-6 real job titles people with this role actually use on LinkedIn (include the role itself first).
  Think "goes by another title": e.g. Backend Engineer -> Software Engineer (Backend), Server-side Developer, SDE II.
- seniority: one of intern, junior, mid, senior, staff, principal, lead, manager, director, vp, cxo, or null.
- skills: concrete skills/domains mentioned or clearly implied.
- locations: cities/countries, canonical spelling ("Bengaluru" -> "Bangalore"). Empty if remote/unspecified.
- company_preferences: e.g. "startup", "fintech", "FAANG", named companies.
- must_haves vs nice_to_haves: split by how strongly the brief states them.
- raw_brief: copy the brief verbatim.

Brief:
\"\"\"{brief}\"\"\"
"""

_CITY_ALIASES = {
    "blr": "Bangalore", "bangalore": "Bangalore", "bengaluru": "Bangalore", "bengalore": "Bangalore",
    "mumbai": "Mumbai", "bombay": "Mumbai", "delhi": "Delhi", "ncr": "Delhi", "gurgaon": "Gurgaon",
    "gurugram": "Gurgaon", "noida": "Noida", "hyderabad": "Hyderabad", "hyd": "Hyderabad", "pune": "Pune",
    "chennai": "Chennai", "kolkata": "Kolkata", "san francisco": "San Francisco", "sf": "San Francisco",
    "new york": "New York", "nyc": "New York", "london": "London", "singapore": "Singapore",
    "berlin": "Berlin", "remote": "",
}
_SENIORITY = ["intern", "junior", "senior", "staff", "principal", "lead", "manager", "director", "vp", "head", "cto", "ceo"]
_ROLE_WORDS = {
    "backend": ("Backend Engineer", ["Software Engineer, Backend", "Backend Developer", "Server Side Engineer"]),
    "frontend": ("Frontend Engineer", ["Software Engineer, Frontend", "Frontend Developer", "UI Engineer"]),
    "full stack": ("Full Stack Engineer", ["Full Stack Developer", "Software Engineer"]),
    "fullstack": ("Full Stack Engineer", ["Full Stack Developer", "Software Engineer"]),
    "ml": ("Machine Learning Engineer", ["ML Engineer", "Applied Scientist", "AI Engineer"]),
    "machine learning": ("Machine Learning Engineer", ["ML Engineer", "Applied Scientist", "AI Engineer"]),
    "data scien": ("Data Scientist", ["Applied Scientist", "Machine Learning Scientist"]),
    "data eng": ("Data Engineer", ["Big Data Engineer", "Analytics Engineer"]),
    "devops": ("DevOps Engineer", ["Site Reliability Engineer", "Platform Engineer", "Infrastructure Engineer"]),
    "sre": ("Site Reliability Engineer", ["DevOps Engineer", "Platform Engineer"]),
    "android": ("Android Engineer", ["Android Developer", "Mobile Engineer"]),
    "ios": ("iOS Engineer", ["iOS Developer", "Mobile Engineer"]),
    "product manager": ("Product Manager", ["Senior Product Manager", "Product Owner"]),
    "pm": ("Product Manager", ["Senior Product Manager", "Product Owner"]),
    "designer": ("Product Designer", ["UX Designer", "UI/UX Designer"]),
    "sales": ("Account Executive", ["Sales Manager", "Business Development Manager"]),
    "marketing": ("Marketing Manager", ["Growth Manager", "Product Marketing Manager"]),
    "recruit": ("Technical Recruiter", ["Talent Acquisition Specialist", "Recruiter"]),
}
_SKILL_WORDS = ["payments", "python", "go", "golang", "java", "rust", "kubernetes", "aws", "gcp", "react", "node",
                "typescript", "distributed systems", "fintech", "llm", "pytorch", "kafka", "postgres", "sql", "spark"]


def heuristic_parse(brief: str) -> Criteria:
    """No-LLM fallback so the pipeline still runs with LLM_MODE=mock or when the LLM fails."""
    text = brief.lower()
    role, variants = "Software Engineer", ["Software Engineer", "Software Developer"]
    for key, (r, v) in _ROLE_WORDS.items():
        if re.search(rf"\b{re.escape(key)}", text):
            role, variants = r, [r, *v]
            break
    seniority = next((s for s in _SENIORITY if re.search(rf"\b{s}\b", text)), None)
    if seniority == "senior" or (seniority is None and re.search(r"\bsr\.?\b", text)):
        seniority = "senior"
        variants = [f"Senior {v}" if not v.startswith("Senior") else v for v in variants]
        role = f"Senior {role}"
    locations = []
    for alias, city in _CITY_ALIASES.items():
        if city and re.search(rf"\b{re.escape(alias)}\b", text) and city not in locations:
            locations.append(city)
    skills = [s for s in _SKILL_WORDS if re.search(rf"\b{re.escape(s)}\b", text)]
    prefs = [p for p in ("startup", "fintech", "faang", "saas", "enterprise") if p in text]
    return Criteria(
        role=role, title_variants=list(dict.fromkeys(variants)), seniority=seniority, skills=skills,
        locations=locations, company_preferences=prefs, must_haves=skills[:2], nice_to_haves=[], raw_brief=brief,
    )


async def parse_brief(brief: str) -> Criteria:
    brief = (brief or "").strip()
    fallback = heuristic_parse(brief)
    if llm.is_mock():
        return fallback
    try:
        c = await llm.generate_json(PARSE_PROMPT.format(brief=brief), Criteria, tier="fast")
    except Exception as e:
        log.warning("parse_brief LLM failed, using heuristic: %s", e)
        return fallback
    if not c.role:
        return fallback
    c.raw_brief = brief
    variants = [c.role, *c.title_variants]
    c.title_variants = list(dict.fromkeys(v.strip() for v in variants if v and v.strip()))[:6]
    return c


def _strip_seniority(title: str) -> str:
    return re.sub(r"^(senior|sr\.?|staff|principal|lead|junior|jr\.?)\s+", "", title, flags=re.I).strip()


def broaden_ladder(c: Criteria) -> list[tuple[str, dict]]:
    """Successively looser person-search filter sets, tightest first: (description, filters).

    Filter shape handed to CrustdataClient.person_search (WS1 maps it to the real API):
        {"titles": [...], "locations": [...], "skills": [...], "seniority": str | None}
    """
    titles = c.title_variants or [c.role]
    base_titles = list(dict.fromkeys(_strip_seniority(t) for t in titles))
    ladder = [
        ("exact titles + location", {"titles": titles, "locations": c.locations, "seniority": c.seniority}),
        ("titles without seniority", {"titles": base_titles, "locations": c.locations, "seniority": None}),
    ]
    if c.locations:
        ladder.append(("dropped location", {"titles": base_titles, "locations": [], "seniority": None}))
    if c.skills:
        ladder.append(("skills only", {"titles": [], "locations": c.locations, "skills": c.skills[:3], "seniority": None}))
    # de-duplicate identical steps (e.g. no seniority to strip)
    seen, out = set(), []
    for desc, f in ladder:
        key = repr(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in f.items()))
        if key not in seen:
            seen.add(key)
            out.append((desc, f))
    return out
