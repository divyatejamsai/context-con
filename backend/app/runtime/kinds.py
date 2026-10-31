"""The jobs an AI employee can be given. Each one runs the agent's real code (app/fleet/*, app/sourced_agent.py)
on real Crustdata and Gemini, inside a RuntimeCtx.

A kind declares the scope it needs (assignment is refused if the agent's passport lacks it), the input fields the
console shows, and a handler that returns {"ok", "summary"}. Everything else (steps, sends, findings, artifacts,
ledger entries) is collected on the task as the agent works.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..agents import registry
from ..agents.passport import sign_message
from ..fleet import diligence, pipeline, reference
from ..fleet.demo import ensure_applicants
from . import store
from .worker import RuntimeCtx

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEADS = ROOT / "fixtures/fleet/pipeline_leads.json"
SOURCING_STEPS = ["passport", "parse", "search", "enrich", "verify", "rank", "guard"]

Handler = Callable[[RuntimeCtx, dict], Awaitable[dict]]


def progress(ctx: RuntimeCtx, done: int, total: int, label: str) -> None:
    store.update_task(ctx.task_id, progress={"done": done, "total": total, "label": label})


# ---- sourcing (Sourced) ---------------------------------------------------------------------------

async def sourcing(ctx: RuntimeCtx, inp: dict) -> dict:
    from ..sourced_agent import run_as_agent
    brief = (inp.get("brief") or "").strip()
    if not brief:
        raise ValueError("a hiring brief is required")
    cands: dict[str, dict] = {}
    shortlist: list[str] = []
    summary: dict = {}
    error = None
    async for ev in run_as_agent(brief, ctx.agent_id, client=ctx.client):
        typ = ev.get("type")
        if typ == "step":
            step = ev.get("step") or ""
            if step in SOURCING_STEPS:
                progress(ctx, SOURCING_STEPS.index(step) + 1, len(SOURCING_STEPS), step)
            ctx.log(f"  {step:<9} {ev.get('message', '')}")
            if step == "rank" and ev.get("data"):
                shortlist = ev["data"].get("shortlist") or ev["data"].get("order", [])[:3]
        elif typ == "candidate":
            c = ev["candidate"]
            cands[c["id"]] = c
        elif typ == "error":
            error = ev.get("message")
            ctx.log(f"  error     {error}")
        elif typ == "done":
            summary = ev.get("summary") or {}
    if error and not cands:
        return {"ok": False, "summary": error}

    short = [cands[i] for i in shortlist if i in cands] or sorted(cands.values(), key=lambda c: -c.get("score", 0))[:5]
    store.task_mutate(ctx.task_id, lambda t: t["output"].__setitem__("shortlist", [
        {"name": c.get("name"), "title": c.get("title"), "company": c.get("company"), "location": c.get("location"),
         "score": c.get("score"), "profile_url": c.get("profile_url"),
         "reasons": [r.get("text") if isinstance(r, dict) else str(r) for r in (c.get("reasons") or [])][:3],
         "guard": (c.get("guard") or {}).get("decision")} for c in short]))
    # Drafts Send Guard already cleared go to the employer's approval inbox (or out, if approvals are off).
    held = 0
    for c in short:
        g = c.get("guard") or {}
        if g.get("decision") != "allow" or not c.get("outreach_draft"):
            continue
        to = {"name": c.get("name"), "profile_url": c.get("profile_url"), "company": c.get("company")}
        body = c["outreach_draft"]
        sig = sign_message(ctx.passport, ctx.key, body)
        await ctx.after_guard(to, body, "outreach.hiring", sig, {"decision": "allow", "checks": g.get("checks", []),
                                                                 "ledger_entry": g.get("ledger_entry")})
        held += 1
    found = summary.get("candidates_found") or summary.get("total") or len(cands)
    return {"ok": bool(cands), "summary": f"{len(short)} shortlisted from {found} found; {held} draft(s) cleared by Send Guard"}


# ---- sales outreach (Pipeline) --------------------------------------------------------------------

def parse_leads(text: str | None) -> list[dict]:
    """One lead per line: Name | LinkedIn URL | Company the CRM has. Empty -> the CRM export in fixtures."""
    if not (text or "").strip():
        return [{k: v for k, v in x.items() if k != "stale_since"} for x in json.loads(DEFAULT_LEADS.read_text())["leads"]]
    leads = []
    for line in text.splitlines():
        parts = [p.strip() for p in re.split(r"\s*[|,\t]\s*", line.strip()) if p.strip()]
        if len(parts) >= 3 and "linkedin.com" in parts[1]:
            leads.append({"name": parts[0], "profile_url": parts[1], "company": parts[2]})
    if not leads:
        raise ValueError("no leads understood: one per line as 'Name | LinkedIn URL | Company'")
    return leads


async def sales_outreach(ctx: RuntimeCtx, inp: dict) -> dict:
    leads = parse_leads(inp.get("leads"))
    progress(ctx, 0, len(leads), "researching leads")
    rep = await pipeline.run(ctx, leads)
    if rep.refused_at_clock_in:
        return {"ok": False, "refused": True, "summary": "Refused at clock-in: the passport did not pass"}
    sends = (store.get_task(ctx.task_id) or {}).get("output", {}).get("sends", [])
    held = sum(s["state"] in ("pending_approval", "sent") for s in sends)
    return {"ok": True, "summary": f"{len(leads)} leads worked: {held} cleared by Send Guard, "
                                   f"{sum(s['state'] == 'blocked' for s in sends)} blocked"}


# ---- vendor diligence (Diligence) -----------------------------------------------------------------

async def vendor_diligence(ctx: RuntimeCtx, inp: dict) -> dict:
    domain = re.sub(r"^https?://|/.*$", "", (inp.get("domain") or "").strip().lower()).removeprefix("www.")
    if not domain or "." not in domain:
        raise ValueError("a vendor domain is required, e.g. razorpay.com")
    progress(ctx, 1, 3, "identifying vendor")
    rep = await diligence.research(ctx, domain)
    if rep.refused_at_clock_in:
        return {"ok": False, "refused": True, "summary": "Refused at clock-in: the passport did not pass"}
    progress(ctx, 3, 3, "brief filed" if rep.ok else "no brief")
    return {"ok": rep.ok, "summary": (f"Cited brief on {rep.vendor['name']} filed on the ledger" if rep.ok and rep.vendor
                                      else f"No brief: Crustdata had nothing for {domain}")}


# ---- reference checks (Reference) -----------------------------------------------------------------

async def reference_check(ctx: RuntimeCtx, inp: dict) -> dict:
    text = (inp.get("resumes") or "").strip()
    if text:
        d = ctx.out_dir / f"resumes-{ctx.task_id}"
        d.mkdir(parents=True, exist_ok=True)
        for i, chunk in enumerate(c for c in re.split(r"\n\s*-{3,}\s*\n", text) if c.strip()):
            (d / f"{i + 1:02d}.resume.txt").write_text(chunk.strip() + "\n")
    else:
        d = ensure_applicants(None, ctx.out_dir.parent, ctx.today)
    n = len(list(d.glob("*.resume.txt")))
    progress(ctx, 0, n, "checking resumes")
    rep = await reference.run(ctx, d)
    if rep.refused_at_clock_in:
        return {"ok": False, "refused": True, "summary": "Refused at clock-in: the passport did not pass"}
    f = (store.get_task(ctx.task_id) or {}).get("output", {}).get("findings", [])
    flagged = sum(1 for x in f if x.get("contradicted"))
    return {"ok": rep.ok, "summary": f"{len(f)} of {n} resumes checked against Crustdata; {flagged} with false claims"}


KINDS: dict[str, dict[str, Any]] = {
    "sourcing": {
        "label": "Source candidates", "scope": "data.read", "agent_hint": "Sourced",
        "description": "Search Crustdata for people who fit a hiring brief, verify every claim, rank them and draft "
                       "outreach. Drafts Send Guard clears wait for your approval.",
        "fields": [{"name": "brief", "label": "Hiring brief", "type": "textarea", "required": True,
                    "placeholder": "Senior backend engineer, payments, Bangalore, 5+ years"}],
        "handler": sourcing},
    "sales_outreach": {
        "label": "Work the lead list", "scope": "outreach.sales", "agent_hint": "Pipeline",
        "description": "Look up each lead on Crustdata, draft a grounded sales email, and run it through Send Guard. "
                       "Stale CRM rows get blocked.",
        "fields": [{"name": "leads", "label": "Leads (optional)", "type": "textarea", "required": False,
                    "placeholder": "Name | LinkedIn URL | Company the CRM has\n(empty: the CRM export)"}],
        "handler": sales_outreach},
    "vendor_diligence": {
        "label": "Vendor diligence brief", "scope": "data.read", "agent_hint": "Diligence",
        "description": "Company Identify, Enrich and Web Fetch on a vendor, then a cited brief filed on the ledger.",
        "fields": [{"name": "domain", "label": "Vendor domain", "type": "text", "required": True,
                    "placeholder": "razorpay.com"}],
        "handler": vendor_diligence},
    "reference_check": {
        "label": "Check resumes", "scope": "data.read", "agent_hint": "Reference",
        "description": "Extract each resume's claims and check them against Crustdata; every false claim comes back "
                       "with the field that disproves it.",
        "fields": [{"name": "resumes", "label": "Resumes (optional)", "type": "textarea", "required": False,
                    "placeholder": "Paste resumes separated by a line of ---\n(empty: the applicant pile)"}],
        "handler": reference_check},
}


KINDS["assignment"] = {
    "label": "Task for an outside agent", "scope": "data.read", "agent_hint": "Claude Code", "external": True,
    "description": "Written instructions for an agent that runs on its own machine (e.g. Claude Code). It claims the task, "
                   "reports progress and asks before sending, all signed with its own key, and stops when you pause it.",
    "fields": [{"name": "instructions", "label": "Instructions", "type": "textarea", "required": True,
                "placeholder": "Draft a two-line note to Vinod Sonagara (https://www.linkedin.com/in/vinod-sonagara) at Fam "
                               "about a backend role, and ask to send it."}],
    "handler": None}


def public_kinds() -> list[dict]:
    return [{"kind": k, **{x: v for x, v in spec.items() if x != "handler"}} for k, spec in KINDS.items()]


def title_for(kind: str, inp: dict) -> str:
    if kind == "sourcing":
        b = (inp.get("brief") or "").strip().splitlines()[0] if inp.get("brief") else ""
        return f"Source: {b[:70]}"
    if kind == "vendor_diligence":
        return f"Diligence on {inp.get('domain')}"
    if kind == "sales_outreach":
        return "Work the CRM lead list" if not (inp.get("leads") or "").strip() else "Work a custom lead list"
    if kind == "interview_scheduling":
        n = len(parse_people(inp.get("candidates")))
        return f"Schedule {n} interview(s)" + (f": {inp['role']}" if inp.get("role") else "")
    if kind == "assignment":
        return (inp.get("instructions") or "Task").strip().splitlines()[0][:80]
    if kind == "reference_check":
        return "Check the applicant pile" if not (inp.get("resumes") or "").strip() else "Check pasted resumes"
    return kind


def is_external(agent: dict) -> bool:
    """Runs on its own machine, or holds its own key (enrolled / rotated): Agaxes can't run its code or sign for it."""
    return agent.get("runtime") == "external" or agent.get("key_custody") == "agent"


def can_do(agent: dict, kind: str) -> str | None:
    """None if the agent may take this kind of task, else why not."""
    spec = KINDS.get(kind)
    if not spec:
        return f"unknown task kind {kind}"
    if bool(spec.get("external")) != is_external(agent):
        return (f"{agent['name']} runs on its own machine: give it an outside-agent task" if is_external(agent)
                else f"{spec['label']} is for outside agents (like Claude Code)")
    if spec["scope"] not in agent["passport"]["scopes"]:
        return f"{agent['name']}'s passport has no {spec['scope']} scope"
    if agent.get("status") == "offboarded":
        return f"{agent['name']} is offboarded"
    return None


def agent_or_raise(agent_id: str) -> dict:
    return registry.get_agent(agent_id)


# ---- interview scheduling (Scheduler) -------------------------------------------------------------

SCHED_PROMPT = """You are {agent}, an AI recruiting coordinator acting for {sponsor} ({title}, {company}). Write a short
interview invitation (max 70 words) to {name}.

Facts you may use about {first} (from Crustdata; state nothing else about them): {facts}
Role: {role}. Interviewer: {interviewer}. Length: {minutes} minutes.
Offer exactly these times and ask them to reply with the one that works: {slots}

Rules: no claims about their tenure, seniority, skills, current title or current company. Start with "Hi {first}," on its own line, then a sentence
starting "We'd like to invite you to interview for our {role} opening". No subject line, no placeholders.
End with exactly this line:
{signoff}
"""


def parse_people(text: str | None) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in re.split(r"\s*[|\t]\s*", line.strip()) if p.strip()]
        if len(parts) >= 3 and "linkedin.com" in parts[1]:
            rows.append({"name": parts[0], "profile_url": parts[1], "company": parts[2]})
    return rows


def parse_slots(text: str | None) -> list[str]:
    return [s.strip(" -•") for s in (text or "").splitlines() if s.strip(" -•")]


async def interview_scheduling(ctx: RuntimeCtx, inp: dict) -> dict:
    from .. import llm
    from ..fleet.base import llm_live
    from ..verify.profile import load_person, same_company
    people = parse_people(inp.get("candidates"))
    slots = parse_slots(inp.get("slots"))
    if not people:
        raise ValueError("no candidates understood: one per line as 'Name | LinkedIn URL | Company'")
    if len(slots) < 2:
        raise ValueError("give at least two interview slots, one per line")
    role = (inp.get("role") or "the open role").strip()
    interviewer = (inp.get("interviewer") or ctx.passport.sponsor.name).strip()
    minutes = int(re.sub(r"\D", "", str(inp.get("minutes") or "45")) or 45)
    progress(ctx, 0, len(people), "proposing slots")
    if not await ctx.clock_in("outreach.hiring"):
        return {"ok": False, "refused": True, "summary": "Refused at clock-in: the passport did not pass"}
    sp = ctx.passport.sponsor
    signoff = f"{ctx.agent['name']} (AI recruiting coordinator for {sp.name}, {sp.company})"
    plan, sources = [], []
    for i, who in enumerate(people):
        offer = [slots[(2 * i) % len(slots)], slots[(2 * i + 1) % len(slots)]]
        person = await ctx.graph.person(who["profile_url"])
        facts = "none"
        if person:
            pr = load_person(person)
            cur = [j for j in pr.current if j.title and j.company]
            if cur:
                facts = f"currently {cur[0].title} at {cur[0].company}"
            moved = not any(same_company(j.company, who["company"]) for j in pr.current)
            sources.append({"endpoint": "person/enrich", "field": "experience.employment_details.current", "url": who["profile_url"]})
            ctx.log(f"  check     {who['name']}: {facts}" + (" (not at the company on file: Send Guard will decide)" if moved else ""))
        else:
            ctx.log(f"  check     {who['name']}: no Crustdata record")
        first = who["name"].split()[0]
        body = (f"Hi {first},\n\nWe'd like to invite you to interview for our {role} opening at {sp.company}. Could you do a "
                f"{minutes}-minute call with {interviewer}? Options: {offer[0]} or {offer[1]}. Reply with the one that works "
                f"for you.\n\n{signoff}")
        by = "template"
        if llm_live():
            try:
                text = await llm.generate_text(SCHED_PROMPT.format(
                    agent=ctx.agent["name"], sponsor=sp.name, title=sp.title, company=sp.company, name=who["name"], first=first,
                    facts=facts, role=role, interviewer=interviewer, minutes=minutes, slots=" or ".join(offer), signoff=signoff))
                if text and all(o.split()[0] in text for o in offer):
                    body, by = f"{text.rsplit(signoff, 1)[0].rstrip()}\n\n{signoff}", "gemini"
            except llm.LLMError:
                pass
        v = await ctx.send({"name": who["name"], "profile_url": who["profile_url"], "company": who["company"]}, body, "outreach.hiring")
        state = "waiting for your approval" if v.get("pending_approval") else ("sent" if v.get("sent") else "blocked")
        plan.append({"candidate": who["name"], "company": who["company"], "slots": offer, "interviewer": interviewer,
                     "minutes": minutes, "invite": state, "drafted_by": by})
    store.task_mutate(ctx.task_id, lambda t: t["output"].__setitem__("schedule", plan))
    ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Agaxes//Scheduler//EN"]
    for p in plan:
        for s in p["slots"]:
            ics += ["BEGIN:VEVENT", f"SUMMARY:HOLD {role} interview: {p['candidate']} with {interviewer}",
                    f"DESCRIPTION:Proposed slot ({s}), {p['minutes']} min. Invite {p['invite']}.", "STATUS:TENTATIVE", "END:VEVENT"]
    ics.append("END:VCALENDAR")
    store.task_mutate(ctx.task_id, lambda t: t["output"].setdefault("artifacts", []).append(
        {"kind": "interview_holds", "title": "Proposed interview holds (.ics)", "content": "\n".join(ics)}))
    held = sum(p["invite"] != "blocked" for p in plan)
    await ctx.file("interview_schedule", f"{held} of {len(plan)} interview invites cleared; slots proposed to each",
                   {"role": role, "interviewer": interviewer, "plan": plan}, sources)
    return {"ok": True, "summary": f"Proposed slots to {len(plan)} candidate(s): {held} invite(s) cleared by Send Guard, "
                                   f"{len(plan) - held} blocked"}


KINDS["interview_scheduling"] = {
    "label": "Schedule interviews", "scope": "outreach.hiring", "agent_hint": "Scheduler",
    "description": "Checks each candidate on Crustdata, proposes two interview slots each, and drafts the invites. "
                   "Invites go through Send Guard and wait for your approval; holds come back as a calendar file.",
    "fields": [
        {"name": "candidates", "label": "Candidates", "type": "textarea", "required": True,
         "placeholder": "Name | LinkedIn URL | Company (one per line; 'Schedule interviews' on a sourcing task fills this)"},
        {"name": "slots", "label": "Interview slots", "type": "textarea", "required": True,
         "placeholder": "Tue 4 Nov, 10:00 IST\nTue 4 Nov, 15:00 IST\nWed 5 Nov, 11:30 IST"},
        {"name": "role", "label": "Role", "type": "text", "required": False, "placeholder": "Senior Backend Engineer"},
        {"name": "interviewer", "label": "Interviewer", "type": "text", "required": False, "placeholder": "the sponsor"},
    ],
    "handler": interview_scheduling}

TEMPLATES = [
    {"key": "scheduler", "name": "Scheduler", "role": "recruiter", "scopes": ["outreach.hiring", "data.read"],
     "job": "Schedules interviews: checks candidates on Crustdata, proposes slots, drafts invites for approval",
     "sponsor_from": "Sourced"},
]
