"""The agent loop: brief -> criteria -> search (with broadening) -> enrich -> verify -> rank -> outreach.

`run(brief)` is an async generator of SSE events (schemas.Event). It never raises: every failure
becomes an ErrorEvent and the run still finishes with a DoneEvent.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import AsyncIterator

from . import people
from .brief import analyze_brief, brief_domain_words, broaden_ladder, clean_term, default_assumptions
from .fallbacks import DevCrustdataClient, basic_rank, basic_verify
from .outreach import draft_outreach, template_draft
from .schemas import (Candidate, CandidateEvent, Claim, Criteria, DoneEvent, ErrorEvent, Event, Reason,
                      RunSummary, StepEvent)

log = logging.getLogger(__name__)

SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "25"))
MIN_POOL = int(os.getenv("MIN_POOL", "3"))          # broaden the search while the pool is smaller than this
MAX_ENRICH = int(os.getenv("MAX_ENRICH", "10"))      # how many candidates get the full enrich/verify/rank treatment
CONCURRENCY = int(os.getenv("PIPELINE_CONCURRENCY", "10"))
COMPANY_TIMEOUT = float(os.getenv("COMPANY_TIMEOUT", "6"))    # cap on Company Identify + Enrich per company
OUTREACH_TIMEOUT = float(os.getenv("OUTREACH_TIMEOUT", "12"))  # slower than this -> template draft
CANDIDATE_TIMEOUT = float(os.getenv("CANDIDATE_TIMEOUT", "120"))
SHORTLIST_MIN = int(os.getenv("SHORTLIST_MIN", "40"))  # below this a candidate is shown but not shortlisted
NEAR_MISS_MIN = int(os.getenv("NEAR_MISS_MIN", "30"))  # [NEAR_MISS_MIN, SHORTLIST_MIN) = near miss, flagged as such


# ---- pluggable parts (WS1 / WS3), with fallbacks so the pipeline always runs --------------------

def make_client():
    """Returns (client, note). note is a warning string when a fallback is used."""
    mode = os.getenv("CRUSTDATA_MODE", "cache").lower()
    if mode == "dev":
        return DevCrustdataClient(), "Using synthetic dev data (CRUSTDATA_MODE=dev)"
    try:
        from .crustdata.client import CrustdataClient
    except Exception as e:  # WS1 not merged yet
        log.warning("Crustdata client unavailable (%s); using dev data", e)
        return DevCrustdataClient(), "Crustdata client not available; using synthetic dev data"
    return CrustdataClient(api_key=os.getenv("CRUSTDATA_API_KEY"), mode=mode), None


def _load_verifier():
    try:
        from .verify.verifier import verify_candidate
        return verify_candidate
    except Exception as e:
        log.warning("WS3 verifier unavailable (%s); using basic verifier", e)
        return basic_verify


def _load_ranker():
    try:
        from .verify.ranker import rank_candidate
        return rank_candidate
    except Exception as e:
        log.warning("WS3 ranker unavailable (%s); using basic ranker", e)
        return basic_rank


# ---- steps ----------------------------------------------------------------------------------------

# Real person/search filter grammar (see crustdata/client.py): leaf {"field","type","value"} or
# {"op": "and"|"or", "conditions": [...]}. "(.)" is a fuzzy contains match.
PERSON_SEARCH_FIELDS = ["crustdata_person_id", "basic_profile", "experience", "social_handles"]
SCHOOL_FIELD = os.getenv("CRUSTDATA_SCHOOL_FIELD", "education.schools.school")  # not live-verified (credits ran out)


class OutOfCredits(Exception):
    """Crustdata answered 402: the key has no credits left. Retrying or broadening only burns time."""
_COUNTRIES = {"india", "united states", "usa", "us", "united kingdom", "uk", "singapore", "germany", "canada",
              "australia", "france", "netherlands", "uae", "united arab emirates"}
_CITY_SPELLINGS = {"bangalore": ["bangalore", "bengaluru"], "mumbai": ["mumbai", "bombay"],
                   "gurgaon": ["gurgaon", "gurugram"], "delhi": ["delhi", "new delhi"]}


def to_crustdata_filters(f: dict) -> dict:
    """Simple pipeline filters {"titles","locations","skills"} -> Crustdata person/search grammar."""
    conds: list[dict] = []
    titles = f.get("titles") or []
    if titles:
        leaves = [{"field": "experience.employment_details.current.title", "type": "(.)", "value": t.lower()} for t in titles]
        conds.append(leaves[0] if len(leaves) == 1 else {"op": "or", "conditions": leaves})
    locs = []
    for loc in f.get("locations") or []:
        l = loc.lower().strip()
        if l in _COUNTRIES:
            locs.append({"field": "basic_profile.location.country", "type": "=", "value": loc})
        else:
            locs += [{"field": "basic_profile.location.city", "type": "(.)", "value": v}
                     for v in _CITY_SPELLINGS.get(l, [l])]
    if locs:
        conds.append(locs[0] if len(locs) == 1 else {"op": "or", "conditions": locs})
    domain = f.get("domain") or []
    if domain:
        # domain fit: the term in their listed skills OR their headline (e.g. "payments")
        leaves = [{"field": fld, "type": "(.)", "value": d.lower()}
                  for d in domain for fld in ("skills.professional_network_skills", "basic_profile.headline")]
        conds.append({"op": "or", "conditions": leaves})
    skills = f.get("skills") or []
    if skills:
        leaves = [{"field": "skills.professional_network_skills", "type": "(.)", "value": s.lower()} for s in skills]
        conds.append(leaves[0] if len(leaves) == 1 else {"op": "or", "conditions": leaves})
    schools = f.get("schools") or []
    if schools:
        # education fit: any of the schools the brief asks for (the LLM expands "prestige college" into names)
        leaves = [{"field": SCHOOL_FIELD, "type": "(.)", "value": s.lower()} for s in schools]
        conds.append(leaves[0] if len(leaves) == 1 else {"op": "or", "conditions": leaves})
    return conds[0] if len(conds) == 1 else {"op": "and", "conditions": conds}


def is_out_of_credits(e: BaseException) -> bool:
    return isinstance(e, OutOfCredits) or getattr(e, "status", None) == 402 or " 402" in str(e)[:200]


async def person_search(client, simple: dict) -> list[dict]:
    if isinstance(client, DevCrustdataClient):
        if simple.get("schools"):
            return []  # dev data has no education records
        return await client.person_search(simple, limit=SEARCH_LIMIT)
    fields = PERSON_SEARCH_FIELDS + (["education"] if simple.get("schools") else [])
    try:
        return await client.person_search(to_crustdata_filters(simple), limit=SEARCH_LIMIT, fields=fields)
    except Exception as e:
        if is_out_of_credits(e):
            raise OutOfCredits(str(e)) from e
        raise


# languages/tools are matched by the verifier, not used as fuzzy domain search terms ("go" matches "Google")
_NOT_DOMAIN = {"go", "golang", "python", "java", "javascript", "typescript", "js", "ts", "rust", "c", "c++", "c#", "ruby",
               "php", "scala", "kotlin", "swift", "sql", "react", "node", "node.js", "aws", "gcp", "azure", "docker",
               "kubernetes", "k8s", "git", "linux", "html", "css", "postgres", "mysql", "redis", "kafka", "spark"}


def domain_terms(c: Criteria, n: int = 3) -> list[str]:
    """Short domain keywords from must-haves + skills ("payments experience" -> "payments"), not languages/tools."""
    out: list[str] = []
    for raw in brief_domain_words(c.raw_brief) + c.must_haves + c.skills:
        t = clean_term(raw)
        if t and 3 <= len(t) <= 30 and t not in _NOT_DOMAIN and t not in out:
            out.append(t)
    return out[:n]


_PROFILE_URL = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9_%\-]+/?", re.I)


def _norm_profile(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url, re.I)
    return m.group(1).lower() if m else url.lower().rstrip("/")


async def apply_template(client, url: str, criteria: Criteria, emit) -> str | None:
    """"Find me someone like <profile URL>": enrich that profile and fill criteria gaps from it.
    Returns the normalised profile key so that person is excluded from results."""
    try:
        if hasattr(client, "person_enrich_many"):
            person = (await client.person_enrich_many([url])).get(url)
        else:
            person = await client.person_enrich(url)
    except Exception as e:
        await emit(ErrorEvent(step="parse", message=f"Couldn't enrich the example profile ({type(e).__name__}); using the brief text only"))
        return _norm_profile(url)
    if not person:
        await emit(ErrorEvent(step="parse", message="Example profile not found in Crustdata; using the brief text only"))
        return _norm_profile(url)
    t, loc, sk = people.title(person), people.location(person), people.skills(person)
    filled = []
    generic = criteria.role.lower().replace("senior ", "") in ("software engineer", "")
    if t and generic:
        criteria.role = t
        criteria.title_variants = list(dict.fromkeys([t, *criteria.title_variants]))[:6]
        filled.append(f"title {t}")
    city = people.first(person, "basic_profile.location.city") or (loc.split(",")[0].strip() if loc else None)
    if city and not criteria.locations:
        criteria.locations = [city]
        filled.append(f"location {city}")
    if sk and not criteria.skills:
        criteria.skills = sk[:5]
        filled.append(f"skills {', '.join(sk[:5])}")
    await emit(StepEvent(
        step="parse",
        message=f"Using {people.name(person)}'s profile as the template"
                + (f" (filled {'; '.join(filled)})" if filled else "") + "; they are excluded from results",
        data={"criteria": criteria.model_dump(), "template": {"name": people.name(person), "profile_url": url,
              "source": people.source_endpoint(person, "person/enrich")}}))
    return _norm_profile(url)


def _ms(t: float) -> int:
    return int((time.monotonic() - t) * 1000)


def _key(p: dict) -> str:
    return people.profile_url(p) or f"{people.name(p)}|{people.company(p)}".lower()


async def search_pool(client, criteria: Criteria, emit) -> list[dict]:
    """Run each title variant as its own query (in parallel), merge + dedupe; broaden while too few hits."""
    pool: dict[str, dict] = {}
    domain = domain_terms(criteria)
    schools = criteria.schools[:12]
    for level, (desc, filters) in enumerate(broaden_ladder(criteria)):
        titles = filters.get("titles") or []
        queries = [dict(filters, titles=[t]) for t in titles] or [filters]
        if titles and domain:
            # one extra query so domain-fit people (e.g. payments) get into the pool, not just title matches
            queries.append(dict(filters, domain=domain))
        if titles and schools:
            # and one for the schools the brief asks for; if the field is rejected, only this query fails
            queries.append(dict(filters, schools=schools))
        where = f" in {', '.join(filters['locations'])}" if filters.get("locations") else ""
        what = f"{len(titles)} title variant{'s' if len(titles) != 1 else ''}" if titles else \
            f"skills {', '.join(filters.get('skills') or [])}"
        if titles and domain:
            what += f" + domain ({', '.join(domain)})"
        if titles and schools:
            what += f" + schools ({', '.join(schools[:4])}{'...' if len(schools) > 4 else ''})"
        prefix = "Broadening search: " if level else ""
        await emit(StepEvent(step="search", message=f"{prefix}Searching {what}{where}...",
                             data={"level": level, "strategy": desc, "filters": filters}))
        results = await asyncio.gather(*(person_search(client, q) for q in queries),
                                       return_exceptions=True)
        failed = 0
        for q, r in zip(queries, results):
            if isinstance(r, Exception):
                failed += 1
                log.warning("person_search failed for %s: %s", q, r)
                continue
            for p in r or []:
                if isinstance(p, dict):
                    kept = pool.setdefault(_key(p), p)
                    if q.get("domain"):
                        kept["_domain_match"] = True
                    if q.get("schools"):
                        kept["_school_match"] = True
        if failed and all(isinstance(r, Exception) and is_out_of_credits(r) for r in results):
            # nothing will come back until the key is topped up: stop instead of broadening into more 402s
            raise OutOfCredits("person/search -> 402")
        if failed:
            await emit(ErrorEvent(step="search", message=f"{failed} of {len(queries)} search queries failed after retries"))
        await emit(StepEvent(step="search", message=f"{len(pool)} unique profiles so far ({desc})",
                             data={"count": len(pool), "level": level}))
        if len(pool) >= MIN_POOL:
            break
    return list(pool.values())


def prescore(p: dict, c: Criteria) -> int:
    """Cheap relevance score on search data, to choose who gets enriched."""
    s = 0
    t = (people.title(p) or "").lower()
    if any(v.lower() in t for v in c.title_variants):
        s += 3
    elif any(w in t for v in c.title_variants for w in v.lower().split() if len(w) > 3):
        s += 1
    loc = (people.location(p) or "").lower()
    if c.locations and any(l.lower() in loc for l in c.locations):
        s += 2
    if p.get("_domain_match"):
        s += 3
    if p.get("_school_match"):
        s += 3
    blob = str(p).lower()
    s += sum(1 for k in fit_terms(c) if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", blob))
    return s


def fit_terms(c: Criteria) -> list[str]:
    """Everything the brief asks for as a keyword, languages included (matched on word boundaries, so 'go'
    doesn't hit 'Google'). Used for prescoring and evals; domain_terms() is the narrower set sent to search."""
    out: list[str] = []
    for raw in brief_domain_words(c.raw_brief) + c.must_haves + c.skills:
        t = clean_term(raw)
        if t and len(t) <= 30 and t not in out:
            out.append(t)
    return out


async def prefetch_companies(client, persons: list[dict], companies: dict) -> None:
    """One batched Company Enrich call for every employer id we know (the endpoint allows 15 req/min, and the
    verifier would otherwise call it once per candidate). Fills `companies` with finished futures."""
    try:
        from .crustdata.client import COMPANY_ENRICH_FIELDS, _unwrap_matches
    except Exception:
        return
    if not hasattr(client, "request"):
        return
    ids = list(dict.fromkeys(str(i) for i in (people.company_id(p) for p in persons) if i))
    ids = [i for i in ids if i not in companies]
    for chunk in (ids[i:i + 25] for i in range(0, len(ids), 25)):
        payload = {"crustdata_company_ids": [int(i) if i.isdigit() else i for i in chunk], "fields": COMPANY_ENRICH_FIELDS}
        try:
            res = await asyncio.wait_for(client.request("company/enrich", payload), timeout=COMPANY_TIMEOUT * 2)
            found = _unwrap_matches(res, "company_data")
        except Exception as e:
            log.warning("company batch enrich failed: %s", e)
            continue
        for i in chunk:
            fut = asyncio.get_running_loop().create_future()
            fut.set_result(found.get(i))
            if found.get(i) is not None:  # misses fall through to the per-company lookup
                companies[i] = fut


_DOMAIN_LIKE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|io|ai|in|co|tech|dev|app|org|net|xyz|so)$", re.I)


def _norm_co(s: str | None) -> str:
    s = re.sub(r"\.(com|io|ai|in|co|tech|dev|app|org|net|xyz|so)$", "", (s or "").lower())
    s = re.sub(r"\b(inc|ltd|llc|limited|pvt|private|technologies|technology|labs|corp|corporation|gmbh|co)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def same_employer(name: str | None, record: dict | None) -> bool:
    """Guard for name-based Company Identify, which fuzzy-matches ("nvme-z.tech" came back as Tech Mahindra)."""
    a = _norm_co(name)
    if not a or not record:
        return False
    names = [people.first(record, "basic_info.name", "company_name", "name"),
             people.first(record, "basic_info.primary_domain", "company_website_domain", "domain")]
    for n in names:
        b = _norm_co(n if isinstance(n, str) else None)
        if b and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))):
            return True
    return False


async def _lookup_company(client, cid, domain, cname) -> dict | None:
    if cid or domain:
        return await client.company_enrich(company_id=cid, domain=domain)
    if cname:
        # employer names that are domains ("nvme-z.tech") identify far better by domain
        ident = await (client.company_identify(domain=cname.lower()) if _DOMAIN_LIKE.match(cname.strip())
                       else client.company_identify(name=cname))
        if ident and not same_employer(cname, ident):
            log.info("identify for %r returned a different company; ignoring", cname)
            return None
        if ident:
            return await client.company_enrich(
                company_id=people.first(ident, "crustdata_company_id", "company_id", "id"),
                domain=people.first(ident, "basic_info.primary_domain", "company_website_domain", "domain")) or ident
    return None


async def enrich(client, p: dict, pre: dict | None = None, companies: dict | None = None) -> tuple[dict, dict | None, list[str]]:
    """Returns (person, company, problems). Falls back to search data when enrich fails.
    `pre` holds batch Person Enrich results ({url: person | None}) so we don't call per person."""
    problems: list[str] = []
    person = p
    url = people.profile_url(p)
    if url:
        try:
            full = pre[url] if pre is not None and url in pre else await client.person_enrich(url)
            if full:
                person = {**p, **full}
            else:
                problems.append("Person Enrich returned no record; using search data only")
        except Exception as e:
            problems.append(f"Person Enrich failed ({type(e).__name__}); using search data only")
    else:
        problems.append("No profile URL to enrich; using search data only")

    company = None
    domain, cid, cname = people.company_domain(person), people.company_id(person), people.company(person)
    key = str(cid or domain or (cname or "").lower() or "")
    if key:
        # one lookup per company per run, shared by colleagues; capped so a failing endpoint can't stall the run
        companies = {} if companies is None else companies
        if key not in companies:
            companies[key] = asyncio.ensure_future(
                asyncio.wait_for(_lookup_company(client, cid, domain, cname), timeout=COMPANY_TIMEOUT))
        try:
            company = await asyncio.shield(companies[key])
        except asyncio.TimeoutError:
            problems.append(f"Company Enrich timed out after {COMPANY_TIMEOUT:.0f}s; company claims unverifiable")
        except Exception as e:
            problems.append(f"Company Enrich failed ({type(e).__name__}); company claims unverifiable")
        # {} = "already looked up, nothing usable": stops the verifier from repeating the same slow call
        company = company or {}
    return person, company, problems


def _namespace(cid: str, claims: list[Claim], reasons: list[Reason]) -> tuple[list[Claim], list[Reason]]:
    """Make claim ids unique across candidates (k1 -> c3-k1) and keep reasons pointing at them."""
    m = {k.id: f"{cid}-{k.id}" for k in claims if not k.id.startswith(f"{cid}-")}
    claims = [k.model_copy(update={"id": m.get(k.id, k.id)}) for k in claims]
    reasons = [r.model_copy(update={"claim_ids": [m.get(i, i) for i in r.claim_ids]}) for r in reasons]
    known = {k.id for k in claims}
    # a reason that cites nothing real isn't allowed to stand as evidence
    reasons = [r for r in reasons if all(i in known for i in r.claim_ids)]
    return claims, reasons


async def process_candidate(cid: str, p: dict, criteria: Criteria, client, verify, rank, emit, seen_steps: set,
                            pre: dict | None = None, companies: dict | None = None,
                            slowest: dict | None = None) -> Candidate:
    slowest = {} if slowest is None else slowest
    clock = [time.monotonic()]

    def lap(name: str):
        now = time.monotonic()
        slowest[name] = max(slowest.get(name, 0), int((now - clock[0]) * 1000))
        clock[0] = now

    async def stage(step: str, msg: str):
        if step not in seen_steps:
            seen_steps.add(step)
            await emit(StepEvent(step=step, message=msg))

    person, company, problems = await enrich(client, p, pre, companies)
    lap("max_company_ms")
    for prob in problems:
        await emit(ErrorEvent(step="enrich", message=f"{people.name(p)}: {prob}"))

    await stage("verify", "Verifying each candidate's claims against Crustdata...")
    try:
        claims, flags = await verify(person, company, criteria, client)
    except Exception as e:
        await emit(ErrorEvent(step="verify", message=f"{people.name(p)}: verifier error ({type(e).__name__}), used basic checks"))
        claims, flags = await basic_verify(person, company, criteria, client)
    flags = list(flags) + [x for x in problems if "using search data only" in x][:1]
    lap("max_verify_ms")

    await stage("rank", "Scoring candidates against the brief (every reason cites a claim)...")
    try:
        score, reasons = await rank(person, claims, criteria)
    except Exception as e:
        await emit(ErrorEvent(step="rank", message=f"{people.name(p)}: ranker error ({type(e).__name__}), used basic score"))
        score, reasons = await basic_rank(person, claims, criteria)
    claims, reasons = _namespace(cid, claims, reasons)
    lap("max_rank_ms")

    cand = Candidate(
        id=cid, name=people.name(person), title=people.title(person), company=people.company(person),
        location=people.location(person), profile_url=people.profile_url(person),
        score=int(score), reasons=reasons, claims=claims, flags=flags,
    )
    if NEAR_MISS_MIN <= cand.score < SHORTLIST_MIN:
        cand.flags.append(f"Near miss: scored {cand.score}, just under the {SHORTLIST_MIN} shortlist bar")
    if cand.score >= SHORTLIST_MIN:  # drafts only for people we'd actually contact
        await stage("outreach", "Drafting outreach for shortlisted candidates (drafts only, never sent)...")
        try:
            cand.outreach_draft = await asyncio.wait_for(draft_outreach(cand, criteria), timeout=OUTREACH_TIMEOUT)
        except asyncio.TimeoutError:
            cand.outreach_draft = template_draft(cand, criteria)
        lap("max_outreach_ms")
    return cand


async def run(brief: str, client=None) -> AsyncIterator[Event]:
    queue: asyncio.Queue = asyncio.Queue()
    summary = RunSummary()
    timings: dict[str, int] = {}
    started = time.monotonic()
    _END = object()

    async def emit(ev: Event):
        await queue.put(ev)

    async def work():
        nonlocal client
        try:
            if not (brief or "").strip():
                await emit(ErrorEvent(step="parse", message="Empty brief: describe the role you're hiring for"))
                return
            await emit(StepEvent(step="parse", message="Reading the brief..."))
            t = time.monotonic()
            analysis = await analyze_brief(brief)
            criteria = analysis.criteria
            timings["parse"] = _ms(t)
            if not analysis.is_hiring:
                await emit(ErrorEvent(step="parse", message="This doesn't look like a hiring brief. Describe the role "
                                                            "you're hiring for (title, location, must-haves)."))
                return
            await emit(StepEvent(
                step="parse",
                message=f"Looking for {criteria.role or 'an unclear role'}"
                        + (f" in {', '.join(criteria.locations)}" if criteria.locations else "")
                        + f" ({len(criteria.title_variants)} title variants: {', '.join(criteria.title_variants)})",
                data={"criteria": criteria.model_dump(), "assumptions": analysis.assumptions}))
            if client is None:
                client, note = make_client()
                if note:
                    await emit(ErrorEvent(step="search", message=note))

            template_key = None
            m = _PROFILE_URL.search(brief)
            if m:
                template_key = await apply_template(client, m.group(0).rstrip("/"), criteria, emit)
                still = default_assumptions(criteria)  # the template may have filled some gaps
                analysis.assumptions = [a for a in analysis.assumptions if a in still or not a.startswith("No ")]
            if analysis.assumptions:
                await emit(StepEvent(step="parse", message="Assumptions: " + "; ".join(analysis.assumptions),
                                     data={"assumptions": analysis.assumptions}))

            if not criteria.role and not criteria.skills:
                await emit(ErrorEvent(step="parse", message="Couldn't tell which role you're hiring for. Name the role "
                                                            "(e.g. 'junior quant trader') and run it again."))
                return

            t = time.monotonic()
            try:
                pool = await search_pool(client, criteria, emit)
            except OutOfCredits:
                await emit(ErrorEvent(step="search", message="Crustdata is out of credits (HTTP 402), so no new profiles "
                                                             "can be searched. Top up the API key, or run with "
                                                             "CRUSTDATA_MODE=replay to use recorded data."))
                return
            if template_key:
                pool = [p for p in pool if _norm_profile(people.profile_url(p)) != template_key]
            timings["search"] = _ms(t)
            summary.searched = len(pool)
            if not pool:
                await emit(ErrorEvent(step="search", message="No matching profiles even after broadening the search"))
                return

            chosen = sorted(pool, key=lambda p: prescore(p, criteria), reverse=True)[:MAX_ENRICH]
            await emit(StepEvent(step="enrich", message=f"Enriching top {len(chosen)} of {len(pool)} profiles and their companies...",
                                 data={"count": len(chosen)}))
            verify, rank = _load_verifier(), _load_ranker()
            pre = None
            t = time.monotonic()
            if hasattr(client, "person_enrich_many"):
                # one batched call: Person Enrich allows only 15 requests/min
                urls = [u for u in (people.profile_url(p) for p in chosen) if u]
                try:
                    pre = await client.person_enrich_many(urls)
                except Exception as e:
                    await emit(ErrorEvent(step="enrich", message=f"Batch Person Enrich failed ({type(e).__name__}); using search data"))
                    pre = {u: None for u in urls}
            companies: dict = {}
            persons = [{**p, **((pre or {}).get(people.profile_url(p)) or {})} for p in chosen]
            await prefetch_companies(client, persons, companies)
            timings["enrich_batch"] = _ms(t)
            t = time.monotonic()
            sem = asyncio.Semaphore(CONCURRENCY)
            seen_steps: set = set()
            done: list[Candidate] = []
            slowest: dict[str, int] = {}

            async def one(i: int, p: dict):
                async with sem:
                    try:
                        cand = await asyncio.wait_for(
                            process_candidate(f"c{i + 1}", p, criteria, client, verify, rank, emit, seen_steps, pre,
                                              companies, slowest),
                            timeout=CANDIDATE_TIMEOUT)
                    except asyncio.TimeoutError:
                        await emit(ErrorEvent(step="enrich", message=f"{people.name(p)}: timed out, skipped"))
                        return
                    except Exception as e:
                        log.exception("candidate failed")
                        await emit(ErrorEvent(step="enrich", message=f"{people.name(p)}: failed ({type(e).__name__}), skipped"))
                        return
                    done.append(cand)
                    await emit(CandidateEvent(candidate=cand))

            await asyncio.gather(*(one(i, p) for i, p in enumerate(chosen)))
            timings["candidates"] = _ms(t)
            timings.update(slowest)  # slowest single candidate per stage, for profiling
            summary.enriched = len(done)
            pre_by_url = {people.profile_url(p): prescore(p, criteria) for p in chosen}
            ranked = sorted(done, key=lambda c: (c.score, sum(k.status == "verified" for k in c.claims),
                                                 -sum(k.status == "contradicted" for k in c.claims),
                                                 pre_by_url.get(c.profile_url, 0)), reverse=True)
            shortlist = [c for c in ranked if c.score >= SHORTLIST_MIN]
            near = [c for c in ranked if NEAR_MISS_MIN <= c.score < SHORTLIST_MIN]
            summary.shortlisted = len(shortlist)
            if ranked:
                top = f", top match {ranked[0].name} ({ranked[0].score})"
                msg = (f"Shortlist ready: {len(shortlist)} of {len(ranked)} candidates score {SHORTLIST_MIN}+{top}"
                       if shortlist else f"No candidate scored {SHORTLIST_MIN}+; showing the {len(ranked)} closest{top}")
                if near:
                    msg += f". {len(near)} near miss{'es' if len(near) != 1 else ''} ({NEAR_MISS_MIN}-{SHORTLIST_MIN - 1}) shown below"
                await emit(StepEvent(step="rank", message=msg,
                                     data={"order": [c.id for c in ranked], "shortlist": [c.id for c in shortlist],
                                           "near_miss": [c.id for c in near], "threshold": SHORTLIST_MIN}))
        except Exception as e:
            log.exception("run failed")
            await emit(ErrorEvent(message=f"Run failed: {type(e).__name__}: {e}"))
        finally:
            await queue.put(_END)

    task = asyncio.create_task(work())
    try:
        while True:
            ev = await queue.get()
            if ev is _END:
                break
            yield ev
        summary.timings_ms = timings
        summary.elapsed_ms = _ms(started)
        yield DoneEvent(summary=summary)
    finally:
        if not task.done():
            task.cancel()  # client disconnected
