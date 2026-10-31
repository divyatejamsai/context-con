"""Outreach drafts. Event rule: drafts are NEVER sent; nothing here contacts anyone."""
from __future__ import annotations

import logging
import os
import re

from . import llm
from .schemas import Candidate, Criteria

log = logging.getLogger(__name__)

PROMPT = """Write a short, warm recruiting outreach message (max 90 words) to {name}.
The role: {role}.

Hard rules:
- Every statement about {first} or their employer must come from the VERIFIED FACTS below. Nothing else.
  Do not describe experience they "have" unless a fact says so; the role's requirements are not facts about them.
- Name at least one specific fact (an employer, a skill, a tenure) in the first two sentences. Lead with the first fact.
- No adjectives or descriptions of any company ("leading", "fast-growing", "innovative", "financial services company")
  unless those exact words are in a fact.
- The second-to-last line must be a direct question asking for a short call this week.
- No subject line. No placeholders. End with exactly:
{signoff}

VERIFIED FACTS:
{evidence}
"""


def signoff() -> str:
    return os.getenv("RECRUITER_NAME") or "[Your name]"


_STOP = {"the", "and", "at", "in", "of", "since", "skill", "title", "based", "works", "with", "for", "yrs", "years"}


def _fact_tokens(claims) -> set[str]:
    toks = set()
    for k in claims:
        for w in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{2,}", k.claim):
            w = w.rstrip(".-").lower()
            if w not in _STOP:
                toks.add(w)
    return toks


def check_draft(draft: str, claims, c: Candidate, criteria: Criteria) -> str | None:
    """Post-check the LLM draft. Returns a fixed draft, or None if it must be replaced by the template."""
    text = (draft or "").strip()
    if not text:
        return None
    if not _fact_tokens(claims) & set(re.findall(r"[a-z0-9+#]+(?:[.-][a-z0-9+#]+)*", text.lower())):
        return None  # cites no fact at all: generic, use the grounded template instead
    body = text.rsplit(signoff(), 1)[0].rstrip() if signoff() in text else text
    if "?" not in body:
        body += "\n\nWould you be open to a 15-minute call this week?"
    return f"{body}\n\n{signoff()}"


def _hook_sentence(fact: str) -> str:
    """Turn a claim into a sentence for a person: "Skill: payments" -> "Your payments experience stood out." """
    m = re.match(r"skill:\s*(.+)", fact, re.I)
    if m:
        return f"Your {m.group(1).strip()} experience stood out."
    m = re.match(r"at (.+?) since (.+?)(?: \(.*\))?$", fact, re.I)
    if m:
        return f"Your time at {m.group(1)} since {m.group(2)[:4]} stood out."
    return f"What stood out: {fact[0].lower() + fact[1:]}."


def template_draft(c: Candidate, criteria: Criteria) -> str:
    first_name = c.name.split()[0] if c.name else "there"
    # hook from a verified fact (domain first), never from ranker/scoring text
    facts = [k.claim.rstrip(".") for k in _domain_first(c, criteria)
             if not re.search(r"\b(claims?|verified|score|matches the|crustdata)\b", k.claim, re.I)
             and not re.match(r"(title|based in|career|progression)\b", k.claim, re.I)]  # already said, or too long
    hook = facts[0] if facts else None
    at = f" at {c.company}" if c.company else ""
    lines = [f"Hi {first_name},", ""]
    lines.append(f"I came across your work as {c.title or 'an engineer'}{at}" + (f". {_hook_sentence(hook)}" if hook else "."))
    lines.append(f"We're hiring a {criteria.role or 'senior engineer'}"
                 + (f" in {', '.join(criteria.locations)}" if criteria.locations else "")
                 + " and I think your background is a strong fit. Open to a 15-minute chat this week?")
    lines += ["", signoff()]
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
    facts = verified[:6]
    prompt = PROMPT.format(
        name=c.name, first=(c.name or "them").split()[0], role=criteria.role, signoff=signoff(),
        evidence="\n".join(f"- {k.claim}" for k in facts),
    )
    try:
        draft = await llm.generate_text(prompt, tier="fast")
    except Exception as e:
        log.warning("outreach LLM failed, using template: %s", e)
        return template_draft(c, criteria)
    return check_draft(draft, facts, c, criteria) or template_draft(c, criteria)
