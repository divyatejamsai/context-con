"""Find a candidate's email address from Crustdata. No guessing: if Crustdata has no address, we say so.

Person Enrich with fields ["contact"] (x-api-version 2025-11-01, checked live on 2026-10-31) returns
    person_data.contact = {business_emails: [...], personal_emails: [{email, last_updated, status}], phone_numbers, websites}
where status is e.g. "deliverable". (/person/contact/enrich exists too, but our plan gets a 403 on it.)

Pick order: a deliverable business email at the candidate's current employer's domain, then any deliverable business
email, then a deliverable personal email, then anything else Crustdata returned (marked with its status).
Every result carries a Source so the UI and the ledger can cite where the address came from.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from ..schemas import Source

log = logging.getLogger(__name__)

CONTACT_FIELDS = ["contact"]
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailOption(BaseModel):
    email: str
    kind: str                      # business | personal
    status: str | None = None      # Crustdata's status, e.g. "deliverable"
    last_updated: str | None = None


class ContactInfo(BaseModel):
    profile_url: str
    email: str | None = None       # the address we would send to (None = Crustdata has none)
    kind: str | None = None
    status: str | None = None
    last_updated: str | None = None
    options: list[EmailOption] = Field(default_factory=list)  # everything Crustdata returned, best first
    source: Source | None = None
    note: str = ""                 # plain-English line for the UI ("Personal email, marked deliverable by Crustdata")
    error: str | None = None       # the lookup failed (not the same as "no email")


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def _rows(contact: dict, key: str, kind: str) -> list[EmailOption]:
    out = []
    for r in contact.get(key) or []:
        if isinstance(r, str):
            r = {"email": r}
        if not isinstance(r, dict):
            continue
        e = (r.get("email") or r.get("value") or "").strip()
        if _EMAIL.match(e):
            out.append(EmailOption(email=e, kind=kind, status=(r.get("status") or None), last_updated=r.get("last_updated")))
    return out


def _employer_domains(person: dict | None) -> set[str]:
    doms = set()
    for j in ((person or {}).get("experience") or {}).get("employment_details", {}).get("current") or []:
        d = (j.get("company_website_domain") or "").lower().removeprefix("www.")
        if d:
            doms.add(d)
    return doms


def pick(profile_url: str, record: dict | None, employer_domains: set[str] | None = None) -> ContactInfo:
    """Choose the address to use from a Person Enrich record that has a `contact` block."""
    src = (record or {}).get("_source") or {}
    source = Source(endpoint="person/enrich", field="contact", url=profile_url) if record else None
    if record is None:
        return ContactInfo(profile_url=profile_url, note="Crustdata has no record for this profile")
    contact = record.get("contact") or {}
    doms = (employer_domains or set()) | _employer_domains(record)
    biz, personal = _rows(contact, "business_emails", "business"), _rows(contact, "personal_emails", "personal")

    def rank(o: EmailOption) -> tuple:
        ok = (o.status or "").lower() in ("deliverable", "valid", "verified")
        at_employer = o.kind == "business" and any(_domain(o.email) == d or _domain(o.email).endswith("." + d) for d in doms)
        return (not ok, not at_employer, o.kind != "business")

    options = sorted(biz + personal, key=rank)
    if not options:
        msg = contact.get("business_emails_message")
        return ContactInfo(profile_url=profile_url, source=source,
                           note="Crustdata has no email for this person" + (f" ({msg})" if msg else ""))
    best = options[0]
    status = best.status or "status unknown"
    note = f"{best.kind.capitalize()} email from Crustdata, marked {status}"
    if best.kind == "personal" and not biz:
        note += " (no work email on record)"
    log.debug("contact for %s from %s", profile_url, src.get("origin"))
    return ContactInfo(profile_url=profile_url, email=best.email, kind=best.kind, status=best.status,
                       last_updated=best.last_updated, options=options, source=source, note=note)


async def find_emails(client: Any, profile_urls: list[str]) -> dict[str, ContactInfo]:
    """Batch lookup (25 per Person Enrich call). Never raises: a failed lookup comes back with `error` set."""
    urls = [u for u in dict.fromkeys(profile_urls) if u]
    if not urls:
        return {}
    if client is None:
        return {u: ContactInfo(profile_url=u, error="no Crustdata client (key missing?)", note="Email lookup unavailable") for u in urls}
    try:
        recs = await client.person_enrich_many(urls, CONTACT_FIELDS)
    except Exception as e:  # noqa: BLE001 - CrustdataError, network
        log.warning("contact lookup failed: %s", e)
        return {u: ContactInfo(profile_url=u, error=str(e)[:200], note="Email lookup failed, try again") for u in urls}
    return {u: pick(u, recs.get(u)) for u in urls}


async def find_email(client: Any, profile_url: str) -> ContactInfo:
    return (await find_emails(client, [profile_url])).get(profile_url) or ContactInfo(profile_url=profile_url)
