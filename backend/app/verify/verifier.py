"""WS3 verifier: turn a candidate's record into checkable claims and label each one.

Each claim is verified / contradicted / unverifiable and always carries a Source.
What gets checked against what:
  - "claimed" facts (a resume or seeded fake passed as person["claimed"], or the profile headline)
    are checked against the employment record from Person Enrich and the Company Enrich record.
  - Employer claims with no graph backing are corroborated by Crustdata web search when possible.
Missing data or a failed call never produces a guess: the claim becomes unverifiable.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from ..schemas import Claim, Criteria, Source

from .profile import (
    CompanyFacts, get_path, Job, Profile, company_key, domain_terms, load_company, load_person, norm, parse_date,
    same_company, seniority_rank, skill_matches, school_matches, degree_matches, stage_bucket, funding_stage_known, title_similarity, tokens, unwrap_record, unwrap_url,
)

if TYPE_CHECKING:  # avoid a hard dependency on WS1's module at import time
    from ..crustdata.client import CrustdataClient

log = logging.getLogger(__name__)

RECENT_CHANGE_DAYS = 120
TENURE_TOLERANCE_DAYS = 183
EXPERIENCE_TOLERANCE_YEARS = 1.5
CALL_TIMEOUT_S = float(os.getenv("VERIFY_CALL_TIMEOUT", "8"))


class _Claims:
    def __init__(self) -> None:
        self.items: list[Claim] = []

    def add(self, text: str, status: str, evidence: str, endpoint: str, field: str | None = None, url: str | None = None) -> Claim:
        c = Claim(id=f"k{len(self.items) + 1}", claim=text, status=status, evidence=evidence,
                  source=Source(endpoint=endpoint, field=field, url=url))
        self.items.append(c)
        return c


def _years(a: date, b: date) -> float:
    return (b - a).days / 365.25


def _fmt_years(y: float) -> str:
    return f"{y:.1f} yrs" if y < 10 else f"{y:.0f} yrs"


def _months_ago(d: date, today: date) -> str:
    days = (today - d).days
    if days < 0:
        return f"starts {d.isoformat()}"
    if days < 60:
        return f"{max(1, days // 7)} weeks ago"
    return f"{days // 30} months ago"


async def _safe(coro, what: str):
    try:
        return await asyncio.wait_for(coro, timeout=CALL_TIMEOUT_S)
    except Exception as e:  # CrustdataError, timeout, anything: the claim just stays unverifiable
        log.warning("verify: %s failed: %s", what, e)
        return None


def _headline_employer(headline: str | None) -> str | None:
    if not headline:
        return None
    m = re.search(r"\b(?:at|@)\s+([A-Z0-9][\w&.\- ]{1,40}?)(?:\s*[|,·•(\-]|$)", headline)
    return m.group(1).strip() if m else None


def _headline_title(headline: str | None) -> str | None:
    if not headline:
        return None
    return re.split(r"\s+(?:at|@)\s+|\s*[|·•]\s*", headline, maxsplit=1)[0].strip() or None


async def _fetch_company(client: CrustdataClient, job: Job | None) -> dict | None:
    if job is None or client is None:
        return None
    if job.company_id or job.domain:
        r = await _safe(client.company_enrich(company_id=str(job.company_id) if job.company_id else None, domain=job.domain), "company_enrich")
        if r:
            return r
    if job.company:
        return await _safe(client.company_identify(name=job.company), "company_identify")
    return None


async def _web_corroborate(client: CrustdataClient, name: str | None, employer: str | None) -> dict | None:
    """Return the first web result that mentions both the person and the employer."""
    if client is None or not name or not employer or os.getenv("VERIFY_WEB", "1") != "1":
        return None
    results = await _safe(client.web_search(f'"{name}" "{employer}"'), "web_search") or []
    name_toks = tokens(name)
    ckey = company_key(employer)
    # Prefer results whose URL is a real page; opaque google.com/goto links still work but cite worse.
    results = sorted((r for r in results[:8] if isinstance(r, dict)),
                     key=lambda r: "google." in (_result_url(r) or ""))
    for r in results:
        if not isinstance(r, dict):
            continue
        text = norm(" ".join(str(r.get(k) or "") for k in ("title", "snippet", "description", "content", "text")))
        if ckey and ckey in text and name_toks and name_toks <= set(text.split()):
            return r
    return None


def _result_url(r: dict | None) -> str | None:
    if not r:
        return None
    return unwrap_url(r.get("url") or r.get("link") or r.get("source_url"))


def _strip_likely(e: str) -> str:
    return re.sub(r"^likely, from [a-z ]+: ", "", e)


def _company_is(company: dict, job: Job) -> bool:
    """Does this company record describe the job's employer? Id match wins; otherwise compare name/domain."""
    rec = unwrap_record(company, "company_data")
    cid = rec.get("crustdata_company_id") or get_path(rec, "basic_info.crustdata_company_id")
    if cid and job.company_id:
        return str(cid) == str(job.company_id)
    name = get_path(rec, "basic_info.name") or rec.get("company_name") or rec.get("name")
    dom = get_path(rec, "basic_info.primary_domain") or rec.get("company_website_domain")
    if job.domain and dom and norm(job.domain) == norm(dom):
        return True
    return same_company(name, job.company) if name and job.company else True


def _has(text: str | None, term: str) -> bool:
    return bool(text) and bool(re.search(rf"\b{re.escape(norm(term))}\b", norm(text)))


def _text_evidence(pr: Profile, k: str) -> tuple[str, str] | None:
    """(evidence, field) when the term appears in the headline or a job title."""
    if _has(pr.headline, k):
        return "named in profile headline", pr.headline_field or "headline"
    for j in pr.current + pr.past:
        if _has(j.title, k):
            return f"in job title '{j.title}' at {j.company}", f"{j.path}.title"
    return None


_STAGE_ORDER = {"seed": 0, "early": 1, "growth": 2, "late": 3, "public": 3, "enterprise": 3}


def _claimed_bucket(claimed: str) -> str | None:
    c = norm(claimed)
    if "seed" in c or "pre series" in c or "angel" in c:
        return "seed"
    return stage_bucket(CompanyFacts(stage=claimed)) or ("early" if "startup" in c else None)


def _stage_conflict(claimed: str | None, bucket: str | None, headcount: int | None, by_size: bool, stage: str | None) -> str | None:
    """Reason text when a claimed company stage clashes with the record, else None.
    Against a real funding round any different bucket is a clash; against size alone only a clear one is."""
    if not claimed or not bucket:
        return None
    cb = _claimed_bucket(claimed)
    if cb is None:
        return None
    if not by_size:
        if norm(claimed) == norm(stage) or cb == bucket or (bucket in ("seed", "early") and "startup" in norm(claimed)):
            return None
        return f"latest priced round is {stage}"
    if headcount is None:
        return None
    if _STAGE_ORDER[cb] >= 2 and headcount < 300:
        return f"a {claimed} company with only ~{headcount:,} employees is implausible"
    if cb == "seed" and headcount >= 1000:
        return f"~{headcount:,} employees is far beyond seed stage"
    return None


def domain_hits(pr: Profile, cf: CompanyFacts | None, skill: str) -> list[tuple[str, str, str]]:
    """Every (evidence, field, endpoint) backing a domain-type skill (e.g. payments), at most one per employer.
    Current employer first, so the ranker can tell a current domain role from a past one."""
    terms = domain_terms(skill) or (norm(skill),)
    hits: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    cur_key = company_key(pr.current[0].company) if pr.current else None
    if cf and cf.industry and any(_has(cf.industry, t) for t in terms):
        hits.append((f"likely, from industry: current employer {cf.name} is in {cf.industry}", "taxonomy.professional_network_industry", cf.endpoint))
        seen.add(company_key(cf.name) if cf.name else cur_key or "")
    for j in pr.current + pr.past:
        key = company_key(j.company)
        if key in seen:
            continue
        when = "current" if j in pr.current else "past"
        if j.company_industry and any(_has(j.company_industry, t) for t in terms):
            hits.append((f"likely, from industry: {when} employer {j.company} is in {j.company_industry}", f"{j.path}.company_professional_network_industry", pr.endpoint))
        elif any(_has(j.company, t) for t in terms):
            hits.append((f"likely, from employer name: {when} employer {j.company}", f"{j.path}.name", pr.endpoint))
        elif j.company_description and any(_has(j.company_description, t) for t in terms):
            hits.append((f"likely, from company description: {when} employer {j.company} describes itself as '{j.company_description[:60].strip()}...'",
                         f"{j.path}.company_description", pr.endpoint))
        else:
            continue
        seen.add(key)
    return hits


def _edu_text(e: dict) -> str:
    bits = [b for b in (e.get("degree"), e.get("field_of_study"), str(e["end_year"]) if e.get("end_year") else None) if b]
    return e["school"] + (f" · {', '.join(bits)}" if bits else "")


def education_claim(out: _Claims, pr: Profile, criteria: Criteria, ep: str) -> Claim:
    """One "Education: <school> · <degree, year>" claim. The ranker re-reads the school and degree from the text."""
    eds = pr.education
    if not eds:
        return out.add("Education", "unverifiable", "no education on the record", ep, "education.schools")
    def ok(e: dict) -> tuple[str | None, str | None]:
        s = next((w for w in criteria.schools if school_matches(w, e["school"])), None)
        d = next((w for w in criteria.degrees if degree_matches(w, e.get("degree") or "")), None)
        return s, d
    scored = [(bool(s) * 2 + bool(d), i, e, s, d) for i, e in enumerate(eds) for s, d in [ok(e)]]
    best = max(scored, key=lambda x: (x[0], -x[1]))
    _, _, e, s, d = best
    asked = []
    if s:
        asked.append(f"school matches '{s}' from the brief")
    if d:
        asked.append(f"degree matches '{d}'")
    if not s and criteria.schools:
        asked.append("not one of the schools the brief asks for")
    ev = "; ".join(asked) + f" ({len(eds)} school{'s' if len(eds) != 1 else ''} on the record)"
    return out.add(f"Education: {_edu_text(e)}", "verified", ev, ep, e["path"])


async def verify_candidate(
    person: dict,
    company: dict | None,
    criteria: Criteria,
    client: CrustdataClient | None,
    today: date | None = None,
) -> tuple[list[Claim], list[str]]:
    """Return (claims, flags). Never raises on bad or missing data."""
    today = today or date.today()
    person = unwrap_record(person or {})
    pr: Profile = load_person(person)
    claimed: dict[str, Any] = person.get("claimed") or {}
    claimed_src = claimed.get("_source") or "candidate resume"
    ep = pr.endpoint
    out = _Claims()
    flags: list[str] = []
    flagged: set[str] = set()  # claim ids that already have a specific flag

    cur: Job | None = pr.current[0] if pr.current else None

    if company is not None and cur is not None and not _company_is(company, cur):
        log.warning("verify: company record %s doesn't match current employer %s; refetching",
                    get_path(company, "basic_info.name") or get_path(company, "company_name"), cur.company)
        company = None
    if company is None and cur is not None:
        company = await _fetch_company(client, cur)
        if company is not None and not _company_is(company, cur):
            company = None
    cf: CompanyFacts | None = load_company(company)

    # 1. Employer
    stated_employer = claimed.get("employer") or _headline_employer(pr.headline)
    stated_via = claimed_src if claimed.get("employer") else "profile headline"
    if stated_employer and cur and not same_company(stated_employer, cur.company):
        other = next((j for j in pr.current[1:] if same_company(stated_employer, j.company)), None)
        if other:
            out.add(f"Works at {stated_employer}", "verified",
                    f"{stated_employer} is listed as a current role alongside {cur.company}", ep, other.path)
        else:
            left = next((j for j in pr.past if same_company(stated_employer, j.company)), None)
            ev = f"{stated_via} says {stated_employer}, but the employment record shows current employer {cur.company}"
            if cur.start:
                ev += f" since {cur.start.isoformat()}"
            if left and left.end:
                ev += f"; left {left.company} {left.end.isoformat()}"
            flagged.add(out.add(f"Works at {stated_employer}", "contradicted", ev, ep, cur.path).id)
            flags.append(f"Profile out of date: says {stated_employer}, now at {cur.company}")
    elif cur:
        ev = f"current employer from {ep}"
        fld, url = cur.path, None
        if cf and cf.name and same_company(cf.name, cur.company):
            ev += f", matched to company record {cf.name}"
        out.add(f"Works at {cur.company}", "verified", ev, ep, fld, url)
    elif stated_employer:
        hit = await _web_corroborate(client, pr.name, stated_employer)
        if hit:
            out.add(f"Works at {stated_employer}", "verified",
                    f"web result names {pr.name} at {stated_employer}: {hit.get('title') or ''}".strip(),
                    "web/search", None, _result_url(hit))
        else:
            out.add(f"Works at {stated_employer}", "unverifiable",
                    "no current employer in the graph and no web result naming them there", ep, "current_employers")
    else:
        out.add("Current employer", "unverifiable", "no current employer in the graph", ep, "current_employers")

    # 2. Title
    graph_title = cur.title if cur else None
    level = cur.seniority_level if cur else None
    # Crustdata's seniority_level (e.g. "Senior") is shown when the title itself doesn't say it.
    level_note = f" ({level})" if level and graph_title and seniority_rank(level) > seniority_rank(graph_title) else ""
    stated_title = claimed.get("title") or _headline_title(pr.headline)
    if stated_title and graph_title:
        sim = title_similarity(stated_title, graph_title)
        record_rank = max(seniority_rank(graph_title), seniority_rank(cur.seniority_level) if cur.seniority_level else 0)
        inflated = seniority_rank(stated_title) > record_rank
        if sim >= 0.5 and not inflated:
            out.add(f"Title: {graph_title}{level_note}", "verified", f"stated '{stated_title}' matches record '{graph_title}'", ep, f"{cur.path}.title")
        elif inflated:
            out.add(f"Title: {stated_title}", "contradicted",
                    f"stated '{stated_title}' is more senior than the record '{graph_title}' at {cur.company}", ep, f"{cur.path}.title")
        elif claimed.get("title"):
            out.add(f"Title: {stated_title}", "contradicted",
                    f"stated '{stated_title}' but the record says '{graph_title}' at {cur.company}", ep, f"{cur.path}.title")
        else:
            # Headline wording often differs from the formal title; record the formal one.
            out.add(f"Title: {graph_title}{level_note}", "verified", f"title on current role (headline reads '{stated_title}')", ep, f"{cur.path}.title")
    elif graph_title:
        out.add(f"Title: {graph_title}{level_note}", "verified", "title on current role", ep, f"{cur.path}.title")
    elif stated_title:
        out.add(f"Title: {stated_title}", "unverifiable", "no title on the current role in the graph", ep, pr.headline_field)

    # 3. Tenure at current employer
    if cur and cur.start:
        yrs = _years(cur.start, today)
        claimed_start = parse_date(claimed.get("start_date"))
        tenure_co = claimed.get("employer") or cur.company
        claimed_tenure = claimed.get("tenure_years")
        if claimed_start and abs((claimed_start - cur.start).days) > TENURE_TOLERANCE_DAYS:
            out.add(f"At {tenure_co} since {claimed_start.isoformat()}", "contradicted",
                    f"record shows current role at {cur.company} starting {cur.start.isoformat()}", ep, f"{cur.path}.start_date")
        elif claimed_tenure is not None and abs(float(claimed_tenure) - yrs) > TENURE_TOLERANCE_DAYS / 365.25:
            out.add(f"{claimed_tenure} yrs at {tenure_co}", "contradicted",
                    f"record shows start {cur.start.isoformat()} ({_fmt_years(yrs)})", ep, f"{cur.path}.start_date")
        else:
            out.add(f"At {cur.company} since {cur.start.isoformat()} ({_fmt_years(yrs)})", "verified",
                    "start date of current role", ep, f"{cur.path}.start_date")
    elif cur:
        out.add(f"Tenure at {cur.company}", "unverifiable", "current role has no start date", ep, f"{cur.path}.start_date")

    # 4. Total experience (only when claimed, or computable)
    starts = [j.start for j in pr.current + pr.past if j.start]
    if starts:
        total = _years(min(starts), today)
        cy = claimed.get("years_experience")
        first_job = min((j for j in pr.current + pr.past if j.start), key=lambda j: j.start)
        exp_field = f"{first_job.path}.start_date"
        if cy is not None and float(cy) - total > EXPERIENCE_TOLERANCE_YEARS:
            out.add(f"{cy} yrs of experience", "contradicted",
                    f"earliest role in the record starts {min(starts).isoformat()} ({_fmt_years(total)})", ep, exp_field)
        else:
            out.add(f"~{_fmt_years(total)} of experience", "verified",
                    f"earliest role starts {min(starts).isoformat()} ({first_job.company})", ep, exp_field)
    elif claimed.get("years_experience") is not None:
        out.add(f"{claimed['years_experience']} yrs of experience", "unverifiable", "no dated roles in the graph", ep, "past_employers")

    # 5. Location
    stated_loc = claimed.get("location")
    if stated_loc and pr.location:
        if tokens(stated_loc) & tokens(pr.location):
            out.add(f"Based in {pr.location}", "verified", f"matches stated '{stated_loc}'", ep, pr.location_field)
        else:
            out.add(f"Based in {stated_loc}", "contradicted", f"record says {pr.location}", ep, pr.location_field)
    elif pr.location:
        out.add(f"Based in {pr.location}", "verified", "location on profile", ep, pr.location_field)
    else:
        out.add(f"Based in {stated_loc}" if stated_loc else "Location", "unverifiable", "no location in the graph", ep, "location")

    # 6. Company stage / size. A funding round is evidence of stage; headcount alone is only a size-based guess.
    claimed_stage = claimed.get("company_stage")
    if cf:
        bucket = stage_bucket(cf)
        by_size = bucket is not None and not funding_stage_known(cf)
        bits = [b for b in (
            cf.stage if not by_size else None, f"~{cf.headcount:,} employees" if cf.headcount else None,
            f"founded {cf.founded}" if cf.founded else None, cf.industry,
        ) if b]
        name = cf.name or (cur.company if cur else "Company")
        fld = cf.stage_field if not by_size else cf.headcount_field
        conflict = _stage_conflict(claimed_stage, bucket, cf.headcount, by_size, cf.stage)
        if conflict:
            out.add(f"{name} is {claimed_stage}", "contradicted", f"company record: {', '.join(bits)}; {conflict}", cf.endpoint, fld)
        elif bits:
            label = (f" ({bucket} by size)" if by_size else f" ({bucket} stage)") if bucket else ""
            out.add(f"{name}: {', '.join(bits)}{label}", "verified", "company record" + (" (no funding round; stage guessed from size)" if by_size else ""),
                    cf.endpoint, fld)
        else:
            out.add(f"{name} stage/size", "unverifiable", "company record has no funding or headcount", cf.endpoint)
    elif cur and (cur.company_headcount or cur.company_headcount_range):
        hc = cur.company_headcount
        bucket = stage_bucket(CompanyFacts(headcount=hc)) if hc else None
        bits = [b for b in (f"~{hc:,} employees" if hc else f"{cur.company_headcount_range} employees", cur.company_industry) if b]
        fld = f"{cur.path}.company_headcount_latest" if hc else f"{cur.path}.company_headcount_range"
        conflict = _stage_conflict(claimed_stage, bucket, hc, True, None)
        if conflict:
            out.add(f"{cur.company} is {claimed_stage}", "contradicted", f"employment record: {', '.join(bits)}; {conflict}", ep, fld)
        else:
            label = f" ({bucket} by size)" if bucket else ""
            out.add(f"{cur.company}: {', '.join(bits)}{label}", "verified", "company size on the employment record (no company record)", ep, fld)
    elif cur:
        out.add(f"{cur.company} stage/size", "unverifiable", "company record not found", "company/enrich")

    # 7. Skills the brief asks for
    short_must = [m for m in criteria.must_haves if isinstance(m, str) and len(m.split()) <= 3]
    wanted = list(dict.fromkeys(criteria.skills + short_must + [s for s in (claimed.get("skills") or []) if isinstance(s, str)]))
    missing = []
    for skill in wanted[:10]:
        k = norm(skill)
        if not k:
            continue
        listed = next((g for g in pr.skills if skill_matches(skill, g)), None)
        if listed:
            ev = "listed in profile skills" + (f" as '{listed}'" if norm(listed) != k else "")
            dom = domain_hits(pr, cf, skill) if domain_terms(skill) else []
            if dom:
                ev += f" | also inferred: {'; '.join(_strip_likely(h[0]) for h in dom[:3])}"
            out.add(f"Skill: {skill}", "verified", ev, ep, pr.skills_field)
        else:
            hit = _text_evidence(pr, k)
            dom = domain_hits(pr, cf, skill) if domain_terms(skill) else []
            if hit:  # direct evidence; employer-industry hits are listed separately as inferred
                ev = hit[0] + (f" | also inferred: {'; '.join(_strip_likely(h[0]) for h in dom[:3])}" if dom else "")
                primary = (hit[0], hit[1], ep)
            elif dom:
                primary = dom[0]
                ev = "inferred only: " + "; ".join(_strip_likely(h[0]) for h in dom[:4])
            else:
                missing.append(skill)
                continue
            out.add(f"Skill: {skill}", "verified", ev, primary[2], primary[1])
            continue
    if missing:
        out.add(f"Skills not evidenced: {', '.join(missing)}", "unverifiable",
                "not found in profile skills, headline, titles or employer industries", ep, pr.skills_field or "skills")

    # 8. Career history: what kind of companies and roles came before (company context, not just the latest title).
    history = sorted([j for j in pr.current + pr.past if j.company], key=lambda j: j.start or date.min, reverse=True)
    if len(history) >= 2:
        parts = []
        for j in history[:4]:
            kind = [x for x in (
                f"~{j.company_headcount:,} people" if j.company_headcount else (f"{j.company_headcount_range} people" if j.company_headcount_range else None),
                j.company_industry,
            ) if x]
            yrs = _years(j.start, j.end or today) if j.start else None
            parts.append(f"{j.title or 'role'} at {j.company}" + (f" ({', '.join(kind)})" if kind else "") + (f", {_fmt_years(yrs)}" if yrs else ""))
        out.add(f"Career: {'; '.join(parts)}", "verified", f"{len(history)} roles on the employment record", ep,
                "experience.employment_details" if pr.current and ".employment_details" in pr.current[0].path else "past_employers")
        # 9. Progression: seniority over time, oldest to newest.
        dated = [j for j in reversed(history) if j.title and j.start]
        if len(dated) >= 2:
            ranks = [max(seniority_rank(j.title), seniority_rank(j.seniority_level) if j.seniority_level else 0) for j in dated]
            trend = "rising" if ranks[-1] > ranks[0] else "falling" if ranks[-1] < ranks[0] else "flat"
            path = " -> ".join(dict.fromkeys(j.title for j in dated[-4:]))
            out.add(f"Progression ({trend}): {path}", "verified", f"titles from {dated[0].start.year} to {dated[-1].start.year}", ep,
                    "experience.employment_details" if ".employment_details" in dated[-1].path else "past_employers")

    # 10. Education, when the brief asks for schools or degrees ("prestige college in India" -> IIT, ISI, BITS...)
    if criteria.schools or criteria.degrees:
        education_claim(out, pr, criteria, ep)

    # Flags: freshness is Crustdata's edge, so surface recent moves loudly.
    if cur and cur.start and 0 <= (today - cur.start).days <= RECENT_CHANGE_DAYS:
        flags.insert(0, f"Changed jobs {_months_ago(cur.start, today)} (joined {cur.company})")
    recent_exit = [j for j in pr.past if j.end and 0 <= (today - j.end).days <= RECENT_CHANGE_DAYS]
    if recent_exit and not (cur and cur.start and (today - cur.start).days <= RECENT_CHANGE_DAYS):
        j = recent_exit[0]
        flags.append(f"Left {j.company} {_months_ago(j.end, today)}")
    if not pr.current and pr.past:
        flags.append("No current role in the graph (may be between jobs)")
    distinct: list[Job] = []
    for j in pr.current:  # the same employer often appears twice (two titles at Wipro)
        if not any((j.company_id and j.company_id == d.company_id) or same_company(j.company, d.company) for d in distinct):
            distinct.append(j)
    if len(distinct) > 1:
        flags.append(f"Holds {len(distinct)} concurrent roles: {', '.join(j.company for j in distinct[:3])}")
    # Reviews of existing sourcing tools keep citing stale profiles; say how old our data is when it's old.
    fetched = parse_date(get_path(person, "_source.fetched_at"))
    if fetched and (today - fetched).days > 30:
        flags.append(f"Profile data is {(today - fetched).days} days old (fetched {fetched.isoformat()})")
    for c in out.items:
        if c.status == "contradicted" and c.id not in flagged:
            flags.append(f"Contradicted: {c.claim}")

    return out.items, list(dict.fromkeys(flags))
