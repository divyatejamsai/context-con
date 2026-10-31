"""Stand-ins used only when WS1's Crustdata client or WS3's verifier/ranker isn't importable yet,
or when CRUSTDATA_MODE=dev. They let the pipeline run end to end with no network or keys.
They follow the shared interfaces in CONTEXT.md section 7a exactly.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

from . import people
from .schemas import Claim, Criteria, Reason, Source


def _src(endpoint: str, payload: str) -> dict:
    return {"endpoint": endpoint, "request_hash": hashlib.sha1(payload.encode()).hexdigest()[:12],
            "fetched_at": datetime.now(timezone.utc).isoformat(), "dev_fixture": True}


_DEV_PEOPLE = [
    ("Ananya Rao", "Senior Backend Engineer", "Razorpay", "razorpay.com", "Bangalore, Karnataka, India", "2021-03-01", ["python", "payments", "kafka"]),
    ("Karthik Menon", "Staff Engineer, Payments", "Juspay", "juspay.in", "Bangalore, Karnataka, India", "2026-10-06", ["go", "payments", "distributed systems"]),
    ("Priya Shah", "Backend Developer", "Swiggy", "swiggy.com", "Bangalore, Karnataka, India", "2019-07-15", ["java", "kubernetes"]),
    ("Rahul Verma", "Senior Software Engineer", "PhonePe", "phonepe.com", "Pune, Maharashtra, India", "2022-01-10", ["java", "payments", "postgres"]),
    ("Meera Iyer", "Engineering Manager", "Cred", "cred.club", "Bangalore, Karnataka, India", "2020-05-01", ["python", "fintech"]),
    ("Arjun Nair", "Senior Backend Engineer", "Zerodha", "zerodha.com", "Bangalore, Karnataka, India", "2023-08-21", ["go", "postgres", "fintech"]),
]


class DevCrustdataClient:
    """Synthetic data with roughly Crustdata-like shapes. Not real people."""

    def __init__(self, *_, **__):
        self._people = {}
        for i, (n, t, co, dom, loc, start, skills) in enumerate(_DEV_PEOPLE):
            url = f"https://www.linkedin.com/in/dev-{n.lower().replace(' ', '-')}"
            self._people[url] = {
                "name": n, "headline": f"{t} at {co}", "location": loc, "linkedin_profile_url": url,
                "skills": skills,
                "current_employers": [{"employer_name": co, "employee_title": t, "start_date": start,
                                       "employer_company_website_domain": dom, "employer_company_id": str(1000 + i)}],
                "past_employers": [],
            }

    async def person_search(self, filters: dict, limit: int = 25) -> list[dict]:
        titles = [t.lower() for t in filters.get("titles") or []]
        locs = [l.lower() for l in filters.get("locations") or []]
        skills = [s.lower() for s in filters.get("skills") or []]
        out = []
        for p in self._people.values():
            t = people.title(p).lower()
            if titles and not any(w in t for tt in titles for w in tt.split() if len(w) > 3 and w not in ("senior", "engineer")) \
                    and not any(tt in t for tt in titles):
                continue
            if locs and not any(l in p["location"].lower() for l in locs):
                continue
            if skills and not set(skills) & set(p["skills"]):
                continue
            out.append({k: p[k] for k in ("name", "headline", "location", "linkedin_profile_url", "current_employers")}
                       | {"_source": _src("person/search", repr(filters))})
        return out[:limit]

    async def person_enrich(self, profile_url: str) -> dict | None:
        p = self._people.get(profile_url)
        return dict(p, _source=_src("person/enrich", profile_url)) if p else None

    async def company_enrich(self, company_id: str | None = None, domain: str | None = None) -> dict | None:
        for p in self._people.values():
            e = p["current_employers"][0]
            if domain == e["employer_company_website_domain"] or company_id == e["employer_company_id"]:
                return {"company_name": e["employer_name"], "company_website_domain": e["employer_company_website_domain"],
                        "headcount": 1200, "industry": "Financial Services", "_source": _src("company/enrich", domain or company_id or "")}
        return None

    async def company_identify(self, name: str | None = None, domain: str | None = None) -> dict | None:
        return await self.company_enrich(domain=domain)

    async def company_search(self, filters: dict, limit: int = 25) -> list[dict]:
        return []

    async def job_search(self, filters: dict, limit: int = 25) -> list[dict]:
        return []

    async def web_search(self, query: str) -> list[dict]:
        return []

    async def web_fetch(self, url: str) -> dict | None:
        return None


async def basic_verify(person: dict, company: dict | None, criteria: Criteria, client) -> tuple[list[Claim], list[str]]:
    """Minimal verifier: turns enriched fields into cited claims. WS3's verifier replaces this."""
    ep = people.source_endpoint(person, "person/enrich")
    claims: list[Claim] = []
    flags: list[str] = []
    emp = people.current_employer(person)
    co, t = people.company(person), people.title(person)
    if co:
        start = people.first(emp, "start_date")
        claims.append(Claim(id="k1", claim=f"Works at {co}" + (f" since {str(start)[:7]}" if start else ""),
                            status="verified", evidence="current employer from profile record",
                            source=Source(endpoint=ep, field="current_employers[0]")))
        try:
            days = (date.today() - date.fromisoformat(str(start)[:10])).days if start else None
        except ValueError:
            days = None
        if days is not None and 0 <= days <= 90:
            flags.append(f"Changed jobs {max(days // 7, 1)} weeks ago")
    if t:
        claims.append(Claim(id="k2", claim=f"Current title: {t}", status="verified", evidence="title from profile record",
                            source=Source(endpoint=ep, field="current_employers[0].employee_title")))
    loc = people.location(person)
    if loc:
        ok = not criteria.locations or any(l.lower() in loc.lower() for l in criteria.locations)
        claims.append(Claim(id="k3", claim=f"Located in {loc}", status="verified", evidence=f"location={loc}",
                            source=Source(endpoint=ep, field="location")))
        if not ok:
            flags.append(f"Outside requested location ({', '.join(criteria.locations)})")
    if company:
        hc = people.first(company, "headcount", "employee_count", "headcount.latest_count")
        if hc:
            claims.append(Claim(id="k4", claim=f"{co or 'Employer'} has ~{hc} employees", status="verified",
                                evidence=f"headcount={hc}",
                                source=Source(endpoint=people.source_endpoint(company, "company/enrich"), field="headcount")))
    skills = [s.lower() for s in (people.first(person, "skills") or []) if isinstance(s, str)]
    for i, s in enumerate(criteria.must_haves[:3]):
        hit = any(s.lower() in sk or sk in s.lower() for sk in skills)
        claims.append(Claim(id=f"m{i + 1}", claim=f"Has {s} experience",
                            status="verified" if hit else "unverifiable",
                            evidence="listed in profile skills" if hit else "not found in profile record",
                            source=Source(endpoint=ep, field="skills")))
    return claims, flags


async def basic_rank(person: dict, claims: list[Claim], criteria: Criteria) -> tuple[int, list[Reason]]:
    """Minimal ranker: share of verified claims, penalised by contradictions. WS3's ranker replaces this."""
    if not claims:
        return 10, [Reason(text="No verifiable data on this profile", claim_ids=[])]
    v = [c for c in claims if c.status == "verified"]
    x = [c for c in claims if c.status == "contradicted"]
    must = [c for c in claims if c.id.startswith("m")]
    must_ok = [c for c in must if c.status == "verified"]
    score = 40 + int(30 * len(v) / len(claims)) + (int(30 * len(must_ok) / len(must)) if must else 15) - 20 * len(x)
    reasons = [Reason(text=c.claim, claim_ids=[c.id]) for c in (must_ok + [c for c in v if c not in must_ok])[:3]]
    if x:
        reasons.append(Reason(text=f"{len(x)} claim(s) contradicted by the data", claim_ids=[c.id for c in x]))
    return max(0, min(100, score)), reasons
