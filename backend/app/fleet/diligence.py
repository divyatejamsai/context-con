"""Diligence, an AI research analyst. Before the sponsor's company signs up with a vendor, it builds a cited
brief on that vendor from Crustdata: Company Identify, Company Enrich (headcount, funding, hiring) and the
vendor's own About page (Web Fetch). Gemini writes the brief from those facts only; every fact keeps its source.

It holds data.read and nothing else. It then tries to ask the vendor's sales team for pricing, and Send Guard
refuses: least privilege is enforced at send time, not just in the console.
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from .. import llm
from .base import Ctx, Report, llm_live

log = logging.getLogger(__name__)

JOB = "Builds cited vendor-diligence briefs from Crustdata before a contract is signed (read-only)"


class Brief(BaseModel):
    verdict: str            # one line: proceed / proceed with care / hold, and why
    strengths: list[str]
    risks: list[str]
    questions_for_vendor: list[str]


PROMPT = """You are Diligence, an AI research analyst for {sponsor} at {company}. {company} is considering {vendor}
as a vendor. Using ONLY the numbered facts below, write a short diligence brief. Cite facts as [n] at the end of
each item. Do not add any fact that is not listed.

FACTS:
{facts}
"""


def _pct(x) -> str:
    return f"{x:+.1f}%" if isinstance(x, (int, float)) else "n/a"


def _frac_pct(x):
    """hiring.openings_growth_percent is a fraction (-0.73), unlike headcount.growth_percent (-3.15 = -3.15%)."""
    return x * 100 if isinstance(x, (int, float)) else None


def facts_from(co: dict, page: dict | None) -> list[dict]:
    """Numbered facts, each with the Crustdata field it came from."""
    b, h, f, hi, loc = (co.get(k) or {} for k in ("basic_info", "headcount", "funding", "hiring", "locations"))
    out: list[tuple[str | None, str, str]] = [
        (b.get("status") and f"Company status: {b['status']}", "company/enrich", "basic_info.status"),
        (b.get("year_founded") and f"Founded in {b['year_founded']}", "company/enrich", "basic_info.year_founded"),
        (b.get("company_type") and f"Company type: {b['company_type']}", "company/enrich", "basic_info.company_type"),
        (h.get("total") and f"Headcount: {h['total']:,} ({b.get('employee_count_range') or 'range n/a'})",
         "company/enrich", "headcount.total"),
        ((h.get("growth_percent") or {}).get("yoy") is not None and
         f"Headcount change: {_pct(h['growth_percent'].get('yoy'))} year on year, {_pct(h['growth_percent'].get('six_months'))} over six months",
         "company/enrich", "headcount.growth_percent"),
        (f.get("total_investment_usd") and f"Total funding raised: ${f['total_investment_usd'] / 1e6:,.0f}M over {f.get('num_funding_rounds') or '?'} rounds",
         "company/enrich", "funding.total_investment_usd"),
        (f.get("last_fundraise_date") and f"Last round: {f.get('last_round_type') or 'unknown type'} on {f['last_fundraise_date']}",
         "company/enrich", "funding.last_fundraise_date"),
        (f.get("acquisitions") and f"Has acquired {len(f['acquisitions'])} companies", "company/enrich", "funding.acquisitions"),
        (hi.get("openings_count") is not None and
         f"Open roles: {hi['openings_count']} ({_pct(_frac_pct((hi.get('openings_growth_percent') or {}).get('yoy')))} year on year)",
         "company/enrich", "hiring.openings_count"),
        (loc.get("headquarters") and f"Headquarters: {loc['headquarters']}", "company/enrich", "locations.headquarters"),
        ((co.get("taxonomy") or {}).get("categories") and f"Categories: {', '.join(co['taxonomy']['categories'][:6])}",
         "company/enrich", "taxonomy.categories"),
    ]
    if page and page.get("title"):
        out.append((f"Their About page is titled \"{page['title'].strip()}\"", "web/fetch", "title"))
    return [{"n": i + 1, "fact": t, "source": {"endpoint": ep, "field": fld}} for i, (t, ep, fld) in
            enumerate(x for x in out if x[0])]


def template_brief(vendor: str, facts: list[dict]) -> Brief:
    """No LLM: a plain brief that restates the facts. Labelled as such in the report."""
    risks = [f"{x['fact']} [{x['n']}]" for x in facts if re.search(r"change: -|Open roles: \d+ \(-", x["fact"])]
    strengths = [f"{x['fact']} [{x['n']}]" for x in facts if x not in risks and re.search(r"status: active|funding|Headcount:", x["fact"])]
    return Brief(verdict=f"Proceed with care: {vendor} is established, but check the risks below (template brief, LLM off)",
                 strengths=strengths, risks=risks or ["None found in the Crustdata record"],
                 questions_for_vendor=["Pricing and volume tiers", "Uptime SLA and incident history", "Data residency"])


async def run(ctx: Ctx, vendor_domain: str) -> Report:
    """Brief, then the overreach. The demo story runs the two halves as separate beats."""
    rep = await research(ctx, vendor_domain)
    if rep.ok and rep.vendor:
        rep.ok = await ask_vendor(ctx, rep.vendor)
    return rep


async def research(ctx: Ctx, vendor_domain: str) -> Report:
    rep = ctx.report = Report(agent=ctx.agent["name"], job=JOB, expected="cited brief filed on the ledger")
    if not await ctx.clock_in("data.read"):
        rep.ok = False
        return rep
    sp = ctx.passport.sponsor
    ident = await ctx.client.company_identify(domain=vendor_domain) if ctx.client else None
    if not ident:
        ctx.log(f"  research  Company Identify found nothing for {vendor_domain}; no brief")
        rep.ok = False
        return rep
    name = (ident.get("basic_info") or {}).get("name") or vendor_domain
    cid = ident.get("crustdata_company_id")
    ctx.log(f"  research  Company Identify: {vendor_domain} is {name} (crustdata id {cid})")
    co = await ctx.client.company_enrich(company_id=cid) or {}
    page = await ctx.client.web_fetch(f"https://{vendor_domain}/about/")
    facts = facts_from({**ident, **co}, page)
    ctx.log(f"  research  Company Enrich + Web Fetch: {len(facts)} cited facts")

    by = "template (LLM off)"
    brief = template_brief(name, facts)
    if llm_live():
        try:
            brief = await llm.generate_json(PROMPT.format(sponsor=sp.name, company=sp.company, vendor=name,
                                                          facts="\n".join(f"[{x['n']}] {x['fact']}" for x in facts)),
                                            Brief, tier="smart")
            by = "gemini"
        except llm.LLMError as e:
            log.warning("Gemini brief failed: %s", e)
    ctx.log(f"  brief     ({by}) {brief.verdict}")

    md = [f"# Vendor brief: {name}", f"For {sp.name} ({sp.title}, {sp.company}). Written by {ctx.agent['name']} "
          f"({ctx.agent_id}), {by}.", "", f"**Verdict:** {brief.verdict}", "", "## Strengths",
          *[f"- {s}" for s in brief.strengths], "", "## Risks", *[f"- {s}" for s in brief.risks], "",
          "## Ask the vendor", *[f"- {q}" for q in brief.questions_for_vendor], "", "## Facts (Crustdata)",
          *[f"{x['n']}. {x['fact']} ({x['source']['endpoint']}, {x['source']['field']})" for x in facts]]
    path = ctx.out_dir / f"brief-{re.sub(r'[^a-z0-9]+', '-', name.lower())}.md"
    path.write_text("\n".join(md) + "\n")
    rep.artifacts.append(str(path))
    ctx._emit({"type": "artifact", "kind": "vendor_brief", "title": f"Vendor brief: {name}", "path": str(path),
               "content": "\n".join(md)})
    res = await ctx.file("vendor_brief", f"{name}: {brief.verdict}",
                   {"vendor": name, "domain": vendor_domain, "crustdata_company_id": cid, "drafted_by": by,
                    "brief": brief.model_dump(), "facts": [x["fact"] for x in facts], "file": path.name},
                   [x["source"] for x in facts])
    rep.ok = bool(res.get("recorded"))
    rep.vendor = {"name": name, "profile_url": (ident.get("basic_info") or {}).get("professional_network_url") or ""}
    return rep


async def ask_vendor(ctx: Ctx, vendor: dict) -> bool:
    """Overreach on purpose: pricing questions go to the vendor, but this agent may only read. True if refused on scope."""
    sp, name = ctx.passport.sponsor, vendor["name"]
    ask = f"Hi, {sp.company} is evaluating {name}. Could you share pricing for our volume?\n\nDiligence (AI analyst for {sp.name})"
    to = {"name": f"{name} sales", "profile_url": vendor["profile_url"], "company": name}
    v = await ctx.send(to, ask, "outreach.sales")
    refused = not v.get("sent") and any(c["name"] == "scope_in_passport" and c["status"] == "fail" for c in v["checks"])
    ctx.log("  result    the pricing email stayed in the drafts: Diligence holds data.read only. The brief goes to the sponsor."
            if refused else "  result    UNEXPECTED: an analyst without outreach scope was not refused on scope")
    return refused
