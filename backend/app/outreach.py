"""Outreach drafts. Event rule: drafts are NEVER sent; nothing here contacts anyone."""
from __future__ import annotations

import logging
import re

from . import llm
from .schemas import Candidate, Criteria

log = logging.getLogger(__name__)

PROMPT = """Write a short, warm recruiting outreach message (max 90 words) to {name}.
Role we're hiring for: {role}. What the client wants: {wants}.

Hard rules:
- Every statement about {first} or their employer must come from the VERIFIED FACTS below. Nothing else.
- Lead with the domain fact (the first fact listed) because it is why we're reaching out.
- No adjectives or descriptions of any company ("leading", "fast-growing", "innovative", "financial services company")
  unless those exact words are in a fact.
- No subject line. No other placeholders. End with exactly:
[Your name]

VERIFIED FACTS:
{evidence}
"""


def template_draft(c: Candidate, criteria: Criteria) -> str:
    first_name = c.name.split()[0] if c.name else "there"
    # hook from a verified fact (domain first), never from ranker/scoring text
    facts = [k.claim.rstrip(".") for k in _domain_first(c, criteria)
             if not re.search(r"\b(claims?|verified|score|matches the|crustdata)\b", k.claim, re.I)]
    hook = facts[0] if facts else None
    at = f" at {c.company}" if c.company else ""
    lines = [f"Hi {first_name},", ""]
    lines.append(f"I came across your work as {c.title or 'an engineer'}{at}"
                 + (f", in particular: {hook[0].lower() + hook[1:]}." if hook else "."))
    lines.append(f"We're hiring a {criteria.role or 'senior engineer'}"
                 + (f" in {', '.join(criteria.locations)}" if criteria.locations else "")
                 + " and I think your background is a strong fit. Open to a 15-minute chat this week?")
    lines += ["", "[Your name]"]
    return "\n".join(lines)


def _domain_first(c: Candidate, criteria: Criteria) -> list:
    """Verified claims, the ones matching the brief's domain terms (e.g. payments) first."""
    from .orchestrator import domain_terms  # local import: orchestrator imports this module

    terms = domain_terms(criteria)
    verified = [k for k in c.claims if k.status == "verified"]
    hit = [k for k in verified if any(t in (k.claim + " " + k.evidence).lower() for t in terms)]
    return hit + [k for k in verified if k not in hit]


async def draft_outreach(c: Candidate, criteria: Criteria) -> str:
    verified = _domain_first(c, criteria)
    if llm.is_mock() or not verified:
        return template_draft(c, criteria)
    prompt = PROMPT.format(
        name=c.name, first=(c.name or "them").split()[0], role=criteria.role,
        wants=", ".join(dict.fromkeys(criteria.must_haves + criteria.skills[:3])) or criteria.raw_brief,
        evidence="\n".join(f"- {k.claim}" for k in verified[:6]),
    )
    try:
        return await llm.generate_text(prompt, tier="fast")
    except Exception as e:
        log.warning("outreach LLM failed, using template: %s", e)
        return template_draft(c, criteria)
