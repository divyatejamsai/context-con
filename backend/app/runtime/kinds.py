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
    if kind == "reference_check":
        return "Check the applicant pile" if not (inp.get("resumes") or "").strip() else "Check pasted resumes"
    return kind


def can_do(agent: dict, kind: str) -> str | None:
    """None if the agent may take this kind of task, else why not."""
    spec = KINDS.get(kind)
    if not spec:
        return f"unknown task kind {kind}"
    if agent.get("runtime") == "external":
        return f"{agent['name']} runs outside Agaxes; it can't be assigned work here"
    if spec["scope"] not in agent["passport"]["scopes"]:
        return f"{agent['name']}'s passport has no {spec['scope']} scope"
    if agent.get("status") == "offboarded":
        return f"{agent['name']} is offboarded"
    return None


def agent_or_raise(agent_id: str) -> dict:
    return registry.get_agent(agent_id)
