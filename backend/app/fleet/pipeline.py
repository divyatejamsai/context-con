"""Pipeline, an AI sales rep. Works a lead list from the CRM and pitches Grewon's backend engineering team.

For each lead: Person Enrich on Crustdata (what the lead does now), a Gemini draft grounded only in those facts,
then a guarded send over MCP (outreach.sales). The draft addresses the lead at the company the CRM has on file,
so a stale CRM row is exactly what Send Guard's recipient check is there to catch. Ends by filing the run.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .. import llm
from ..verify.profile import load_person, same_company
from .base import Ctx, Report, llm_live

log = logging.getLogger(__name__)

JOB = "Works the CRM lead list and drafts sales outreach for Grewon's backend engineering services"
PITCH = ("Grewon Technologies builds and runs backend and cloud infrastructure for product teams "
         "(Python, Django, AWS, Terraform, Kubernetes).")

PROMPT = """You are Pipeline, an AI sales rep acting for {sponsor} at Grewon Technologies. Write a short cold email
(max 80 words) to {name} about Grewon's services.

What Grewon does (you may say this): {pitch}

Facts about {first} (from Crustdata; state nothing else about them or their company):
{facts}

Rules:
- Address them at {company} (the account you are working). Mention {company} once, as "your team at {company}".
- No claims about their title, tenure, seniority, location or company size. No adjectives about their company.
- Say nothing about what they know, use or work with: never "As a <title>, you...". Grewon's stack goes only in a
  sentence that starts with "We" or "Grewon".
- One direct question asking for a 15-minute call this week.
- No subject line, no placeholders. End with exactly this line:
{signoff}
"""


def signoff(ctx: Ctx) -> str:
    return f"Pipeline (AI assistant to {ctx.passport.sponsor.name}, Grewon)"


def template(first: str, company: str, sig: str) -> str:
    return (f"Hi {first}, I'm reaching out about your team at {company}. {PITCH} If your backend roadmap is "
            f"stretched, we can take a project off your plate. Open to a 15-minute call this week?\n\n{sig}")


async def draft(ctx: Ctx, lead: dict, person: dict) -> tuple[str, str]:
    """(body, drafted_by). Gemini when live; the grounded template when the LLM is off or its draft is unusable."""
    first = (lead["name"] or "there").split()[0]
    pr = load_person(person)
    facts = [f"- Currently {j.title} at {j.company}" for j in pr.current if j.title and j.company]
    if pr.current and pr.current[0].company_industry:
        facts.append(f"- {pr.current[0].company} is in {pr.current[0].company_industry}")
    sig = signoff(ctx)
    if llm_live():
        try:
            text = await llm.generate_text(PROMPT.format(
                sponsor=ctx.passport.sponsor.name, name=lead["name"], first=first, pitch=PITCH,
                facts="\n".join(facts) or "- none", company=lead["company"], signoff=sig))
            if text and lead["company"].lower() in text.lower() and "?" in text:
                body = text.rsplit(sig, 1)[0].rstrip()
                return f"{body}\n\n{sig}", "gemini"
            log.warning("Gemini draft for %s unusable, using template", lead["name"])
        except llm.LLMError as e:
            log.warning("Gemini failed for %s: %s", lead["name"], e)
    return template(first, lead["company"], sig), "template (LLM off)"


async def run(ctx: Ctx, leads: list[dict]) -> Report:
    rep = ctx.report = Report(agent=ctx.agent["name"], job=JOB, expected="leads at their CRM company cleared; stale rows blocked")
    if not await ctx.clock_in("data.read"):
        return rep
    sources, outcomes = [], []
    for lead in leads:
        person = await ctx.graph.person(lead["profile_url"])
        if not person:
            ctx.log(f"  research  {lead['name']}: no Crustdata record, skipped")
            continue
        sources.append({"endpoint": "person/enrich", "field": "experience.employment_details.current",
                        "url": lead["profile_url"]})
        pr = load_person(person)
        now = ", ".join(f"{j.title} at {j.company}" for j in pr.current[:2]) or "no current role"
        stale = not any(same_company(j.company, lead["company"]) for j in pr.current)
        ctx.log(f"  research  {lead['name']}: CRM says {lead['company']}; Crustdata says {now}")
        body, by = await draft(ctx, lead, person)
        ctx.log(f"  draft     ({by}) {body.splitlines()[0][:110]}")
        v = await ctx.send({"name": lead["name"], "profile_url": lead["profile_url"], "company": lead["company"]},
                           body, "outreach.sales")
        outcomes.append({"lead": lead["name"], "crm_company": lead["company"], "decision": v["decision"],
                         "sent": bool(v.get("sent")), "drafted_by": by, "guard_entry": v.get("ledger_entry")})
        if stale and v.get("sent"):
            rep.ok = False  # a stale CRM row must never clear the guard
    await ctx.file("outreach_run", f"{rep.allowed} of {len(outcomes)} drafts cleared, {rep.blocked} blocked by Send Guard",
                   {"leads": outcomes}, sources)
    rep.ok = rep.ok and rep.allowed > 0
    return rep


def load_leads(path: Path) -> list[dict]:
    return json.loads(path.read_text())["leads"]
