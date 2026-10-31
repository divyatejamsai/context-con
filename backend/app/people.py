"""Defensive field access for Crustdata person/company dicts.

Crustdata's response shapes vary between endpoints and API versions, so every lookup tries
several known keys and never raises.
"""
from __future__ import annotations

from typing import Any


def first(d: dict | None, *keys: str) -> Any:
    """First non-empty value among dotted `keys` (e.g. "current_employers.0.title")."""
    if not d:
        return None
    for key in keys:
        cur: Any = d
        for part in key.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                cur = None
            if cur is None:
                break
        if cur not in (None, "", [], {}):
            return cur
    return None


def profile_url(p: dict) -> str | None:
    return first(p, "social_handles.professional_network_identifier.profile_url", "linkedin_profile_url",
                 "profile_url", "linkedin_url", "flagship_profile_url", "basic_profile.linkedin_profile_url", "url")


def name(p: dict) -> str:
    n = first(p, "name", "full_name", "basic_profile.name")
    if not n:
        n = " ".join(x for x in (first(p, "first_name"), first(p, "last_name")) if x)
    return n or "Unknown"


def current_employer(p: dict) -> dict:
    emp = first(p, "experience.employment_details.current.0", "current_employers.0", "employment_details.current.0",
                "experience.current.0", "current_employer")
    return emp if isinstance(emp, dict) else {}


def title(p: dict) -> str | None:
    return first(p, "basic_profile.current_title", "title", "current_title", "job_title") or first(
        current_employer(p), "employee_title", "title", "position") or first(p, "basic_profile.headline", "headline")


def company(p: dict) -> str | None:
    return first(p, "company", "current_company", "company_name") or first(
        current_employer(p), "employer_name", "company_name", "name")


def company_domain(p: dict) -> str | None:
    return first(current_employer(p), "employer_company_website_domain.0", "employer_company_website_domain",
                 "company_website_domain", "company_domain", "domain")


def company_id(p: dict) -> str | None:
    v = first(current_employer(p), "crustdata_company_id", "employer_company_id", "company_id")
    if isinstance(v, list):
        v = v[0] if v else None
    return str(v) if v is not None else None


def location(p: dict) -> str | None:
    loc = first(p, "basic_profile.location", "location", "region", "location_details.raw")
    if isinstance(loc, dict):
        loc = ", ".join(str(v) for v in (loc.get("city"), loc.get("state"), loc.get("country")) if v)
    return loc or None


def source_endpoint(d: dict | None, default: str) -> str:
    return first(d, "_source.endpoint") or default


def skills(p: dict) -> list[str]:
    v = first(p, "skills.professional_network_skills", "skills")
    return [s for s in v if isinstance(s, str)] if isinstance(v, list) else []
