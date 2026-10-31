"""Outreach drafts. Event rule: drafts are NEVER sent; nothing here contacts anyone."""
from __future__ import annotations

import logging

from . import llm
from .schemas import Candidate, Criteria

log = logging.getLogger(__name__)

PROMPT = """Write a short, warm recruiting outreach message (max 90 words) to {name}, currently {title} at {company}.
Role we're hiring for: {role}. What the client wants: {wants}.
Mention 1-2 specific facts from the VERIFIED evidence below and nothing else about them (no invented details).
No subject line, no placeholders like [Company], sign off as "— The hiring team".

Verified evidence:
{evidence}
"""


def template_draft(c: Candidate, criteria: Criteria) -> str:
    first_name = c.name.split()[0] if c.name else "there"
    hook = next((r.text for r in c.reasons if r.claim_ids), None)
    at = f" at {c.company}" if c.company else ""
    lines = [f"Hi {first_name},", ""]
    lines.append(f"I came across your work as {c.title or 'an engineer'}{at}"
                 + (f", in particular: {hook[0].lower() + hook[1:]}." if hook else "."))
    lines.append(f"We're hiring a {criteria.role or 'senior engineer'}"
                 + (f" in {', '.join(criteria.locations)}" if criteria.locations else "")
                 + " and I think your background is a strong fit. Open to a 15-minute chat this week?")
    lines += ["", "— The hiring team"]
    return "\n".join(lines)


async def draft_outreach(c: Candidate, criteria: Criteria) -> str:
    verified = [k for k in c.claims if k.status == "verified"]
    if llm.is_mock() or not verified:
        return template_draft(c, criteria)
    prompt = PROMPT.format(
        name=c.name, title=c.title or "an engineer", company=c.company or "their current company", role=criteria.role,
        wants=", ".join(criteria.must_haves + criteria.skills[:3]) or criteria.raw_brief,
        evidence="\n".join(f"- {k.claim}" for k in verified[:6]),
    )
    try:
        return await llm.generate_text(prompt, tier="fast")
    except Exception as e:
        log.warning("outreach LLM failed, using template: %s", e)
        return template_draft(c, criteria)
