"""Reference, an AI background checker. Reads the applicant pile (plain-text resumes) and checks every claim
against Crustdata before anyone spends time on an interview.

Per resume: Gemini extracts the claims (employer, title, start date, years of experience, location, company
stage, skills); Person Enrich and Company Enrich fetch the record; the verifier (app/verify) marks each claim
verified / contradicted / unverifiable with the field that decides it. Each check is filed on the ledger.
Read-only: it never contacts the candidate or their references.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import BaseModel

from .. import llm
from ..schemas import Criteria
from ..verify.profile import load_person
from ..verify.verifier import verify_candidate
from .base import Ctx, Report, llm_live

log = logging.getLogger(__name__)

JOB = "Checks applicant resumes against Crustdata and flags false claims before interviews (read-only)"


class ResumeClaims(BaseModel):
    name: str | None = None
    profile_url: str | None = None
    employer: str | None = None
    title: str | None = None
    start_date: str | None = None
    years_experience: float | None = None
    location: str | None = None
    company_stage: str | None = None
    skills: list[str] = []


PROMPT = """Extract what this resume claims, exactly as written (do not correct anything). start_date as YYYY-MM-DD.
company_stage is how the resume describes the current company (e.g. "Series B", "Privately Held"), if it does.

RESUME:
{text}
"""


def parse_resume(text: str) -> ResumeClaims:
    """Line-based reader for plain resumes, used when the LLM is off (and as a check on the LLM's URL)."""
    lines = [ln.strip() for ln in text.strip().splitlines()]
    c = ResumeClaims(name=lines[0] if lines else None)
    for ln in lines[1:]:
        if m := re.match(r"(https?://\S*linkedin\.com/in/\S+)", ln):
            c.profile_url = m.group(1)
        elif m := re.match(r"In current role since (\S+)", ln):
            c.start_date = m.group(1)
        elif m := re.match(r"(\d+(?:\.\d+)?) years of experience", ln):
            c.years_experience = float(m.group(1))
        elif m := re.match(r"Based in (.+)", ln):
            c.location = m.group(1)
        elif m := re.match(r"Current company: (.+)", ln):
            c.company_stage = m.group(1)
        elif m := re.match(r"Skills: (.+)", ln):
            c.skills = [s.strip() for s in m.group(1).split(",") if s.strip()]
        elif " at " in ln and not c.employer:
            c.title, c.employer = (s.strip() for s in ln.rsplit(" at ", 1))
    return c


async def extract(text: str) -> tuple[ResumeClaims, str]:
    base = parse_resume(text)
    if llm_live():
        try:
            got = await llm.generate_json(PROMPT.format(text=text), ResumeClaims)
            got.profile_url = got.profile_url or base.profile_url
            return got, "gemini"
        except llm.LLMError as e:
            log.warning("Gemini resume extraction failed: %s", e)
    return base, "parser (LLM off)"


async def run(ctx: Ctx, applicants: Path) -> Report:
    rep = ctx.report = Report(agent=ctx.agent["name"], job=JOB, expected="every planted lie contradicted, cited")
    if not await ctx.clock_in("data.read"):
        return rep
    files = sorted(applicants.glob("*.resume.txt"))
    ctx.log(f"  pile      {len(files)} resumes in {applicants}")
    rows = []
    for f in files:
        claims, by = await extract(f.read_text())
        if not claims.profile_url:
            ctx.log(f"  check     {claims.name or f.name}: no profile URL on the resume, can't check")
            continue
        person = await ctx.graph.person(claims.profile_url)
        if not person:
            ctx.log(f"  check     {claims.name}: no Crustdata record, every claim unverifiable")
            continue
        company = None
        cur = load_person(person).current
        if cur and cur[0].company_id and ctx.client:
            company = await ctx.client.company_enrich(company_id=cur[0].company_id)
        claimed = {k: v for k, v in claims.model_dump(exclude={"name", "profile_url"}).items() if v not in (None, "", [])}
        claimed["_source"] = f"resume {f.name}"
        checked, flags = await verify_candidate({**person, "claimed": claimed}, company,
                                                Criteria(role="Reference check", raw_brief="resume verification"),
                                                ctx.client, today=ctx.today)
        bad = [c for c in checked if c.status == "contradicted"]
        ok = sum(c.status == "verified" for c in checked)
        ctx.log(f"  check     {claims.name} ({by}): {ok} verified, {len(bad)} contradicted"
                + "".join(f"\n              x {c.claim} -> {c.evidence}" for c in bad))
        rows.append({"name": claims.name, "contradicted": len(bad)})
        await ctx.file("resume_check", f"{claims.name}: {len(bad)} false claim(s), {ok} verified",
                       {"candidate": claims.name, "profile_url": claims.profile_url, "extracted_by": by,
                        "contradicted": [{"claim": c.claim, "evidence": c.evidence} for c in bad],
                        "verified": [c.claim for c in checked if c.status == "verified"],
                        "unverifiable": [c.claim for c in checked if c.status == "unverifiable"], "flags": flags},
                       [c.source for c in checked if c.source])
    flagged = sum(1 for r in rows if r["contradicted"])
    ctx.log(f"  result    {flagged} of {len(rows)} applicants flagged for the sponsor")
    rep.ok = bool(rows)
    return rep
