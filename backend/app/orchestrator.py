"""The agent loop: brief -> criteria -> search (with broadening) -> enrich -> verify -> rank -> outreach.

`run(brief)` is an async generator of SSE events (schemas.Event). It never raises: every failure
becomes an ErrorEvent and the run still finishes with a DoneEvent.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator

from . import people
from .brief import broaden_ladder, parse_brief
from .fallbacks import DevCrustdataClient, basic_rank, basic_verify
from .outreach import draft_outreach
from .schemas import (Candidate, CandidateEvent, Claim, Criteria, DoneEvent, ErrorEvent, Event, Reason,
                      RunSummary, StepEvent)

log = logging.getLogger(__name__)

SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "25"))
MIN_POOL = int(os.getenv("MIN_POOL", "3"))          # broaden the search while the pool is smaller than this
MAX_ENRICH = int(os.getenv("MAX_ENRICH", "10"))      # how many candidates get the full enrich/verify/rank treatment
CONCURRENCY = int(os.getenv("PIPELINE_CONCURRENCY", "5"))
CANDIDATE_TIMEOUT = float(os.getenv("CANDIDATE_TIMEOUT", "120"))


# ---- pluggable parts (WS1 / WS3), with fallbacks so the pipeline always runs --------------------

def make_client():
    """Returns (client, note). note is a warning string when a fallback is used."""
    mode = os.getenv("CRUSTDATA_MODE", "live").lower()
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

def _key(p: dict) -> str:
    return people.profile_url(p) or f"{people.name(p)}|{people.company(p)}".lower()


async def search_pool(client, criteria: Criteria, emit) -> list[dict]:
    """Run each title variant as its own query (in parallel), merge + dedupe; broaden while too few hits."""
    pool: dict[str, dict] = {}
    for level, (desc, filters) in enumerate(broaden_ladder(criteria)):
        titles = filters.get("titles") or []
        queries = [dict(filters, titles=[t]) for t in titles] or [filters]
        where = f" in {', '.join(filters['locations'])}" if filters.get("locations") else ""
        what = f"{len(titles)} title variant{'s' if len(titles) != 1 else ''}" if titles else \
            f"skills {', '.join(filters.get('skills') or [])}"
        prefix = "Broadening search: " if level else ""
        await emit(StepEvent(step="search", message=f"{prefix}Searching {what}{where}...",
                             data={"level": level, "strategy": desc, "filters": filters}))
        results = await asyncio.gather(*(client.person_search(q, limit=SEARCH_LIMIT) for q in queries),
                                       return_exceptions=True)
        failed = 0
        for q, r in zip(queries, results):
            if isinstance(r, Exception):
                failed += 1
                log.warning("person_search failed for %s: %s", q, r)
                continue
            for p in r or []:
                if isinstance(p, dict):
                    pool.setdefault(_key(p), p)
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
    blob = str(p).lower()
    s += sum(1 for k in c.skills + c.must_haves if k.lower() in blob)
    return s


async def enrich(client, p: dict) -> tuple[dict, dict | None, list[str]]:
    """Returns (person, company, problems). Falls back to search data when enrich fails."""
    problems: list[str] = []
    person = p
    url = people.profile_url(p)
    if url:
        try:
            full = await client.person_enrich(url)
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
    try:
        if cid or domain:
            company = await client.company_enrich(company_id=cid, domain=domain)
        elif cname:
            ident = await client.company_identify(name=cname)
            if ident:
                company = await client.company_enrich(company_id=people.first(ident, "company_id", "id"),
                                                      domain=people.first(ident, "company_website_domain", "domain")) or ident
    except Exception as e:
        problems.append(f"Company Enrich failed ({type(e).__name__})")
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


async def process_candidate(cid: str, p: dict, criteria: Criteria, client, verify, rank, emit, seen_steps: set) -> Candidate:
    async def stage(step: str, msg: str):
        if step not in seen_steps:
            seen_steps.add(step)
            await emit(StepEvent(step=step, message=msg))

    person, company, problems = await enrich(client, p)
    for prob in problems:
        await emit(ErrorEvent(step="enrich", message=f"{people.name(p)}: {prob}"))

    await stage("verify", "Verifying each candidate's claims against Crustdata...")
    try:
        claims, flags = await verify(person, company, criteria, client)
    except Exception as e:
        await emit(ErrorEvent(step="verify", message=f"{people.name(p)}: verifier error ({type(e).__name__}), used basic checks"))
        claims, flags = await basic_verify(person, company, criteria, client)
    flags = list(flags) + [x for x in problems if "using search data only" in x][:1]

    await stage("rank", "Scoring candidates against the brief (every reason cites a claim)...")
    try:
        score, reasons = await rank(person, claims, criteria)
    except Exception as e:
        await emit(ErrorEvent(step="rank", message=f"{people.name(p)}: ranker error ({type(e).__name__}), used basic score"))
        score, reasons = await basic_rank(person, claims, criteria)
    claims, reasons = _namespace(cid, claims, reasons)

    cand = Candidate(
        id=cid, name=people.name(person), title=people.title(person), company=people.company(person),
        location=people.location(person), profile_url=people.profile_url(person),
        score=int(score), reasons=reasons, claims=claims, flags=flags,
    )
    await stage("outreach", "Drafting outreach (drafts only, never sent)...")
    cand.outreach_draft = await draft_outreach(cand, criteria)
    return cand


async def run(brief: str, client=None) -> AsyncIterator[Event]:
    queue: asyncio.Queue = asyncio.Queue()
    summary = RunSummary()
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
            criteria = await parse_brief(brief)
            await emit(StepEvent(
                step="parse",
                message=f"Looking for {criteria.role}"
                        + (f" in {', '.join(criteria.locations)}" if criteria.locations else "")
                        + f" ({len(criteria.title_variants)} title variants)",
                data={"criteria": criteria.model_dump()}))

            if client is None:
                client, note = make_client()
                if note:
                    await emit(ErrorEvent(step="search", message=note))

            pool = await search_pool(client, criteria, emit)
            summary.searched = len(pool)
            if not pool:
                await emit(ErrorEvent(step="search", message="No matching profiles even after broadening the search"))
                return

            chosen = sorted(pool, key=lambda p: prescore(p, criteria), reverse=True)[:MAX_ENRICH]
            await emit(StepEvent(step="enrich", message=f"Enriching top {len(chosen)} of {len(pool)} profiles and their companies...",
                                 data={"count": len(chosen)}))
            verify, rank = _load_verifier(), _load_ranker()
            sem = asyncio.Semaphore(CONCURRENCY)
            seen_steps: set = set()
            done: list[Candidate] = []

            async def one(i: int, p: dict):
                async with sem:
                    try:
                        cand = await asyncio.wait_for(
                            process_candidate(f"c{i + 1}", p, criteria, client, verify, rank, emit, seen_steps),
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
            summary.enriched = len(done)
            ranked = sorted(done, key=lambda c: c.score, reverse=True)
            summary.shortlisted = len(ranked)
            if ranked:
                await emit(StepEvent(step="rank", message=f"Shortlist ready: {len(ranked)} candidates, top match {ranked[0].name} ({ranked[0].score})",
                                     data={"order": [c.id for c in ranked]}))
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
        yield DoneEvent(summary=summary)
    finally:
        if not task.done():
            task.cancel()  # client disconnected
