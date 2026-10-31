"""Auth routes for company accounts. Mounted in app/main.py.

POST /api/auth/lookup   {email}                    -> domain checks + Crustdata Company Identify prefill
POST /api/auth/signup   {email, password, ...}     -> creates user (+ workspace) and a session
POST /api/auth/login    {email, password}          -> session
POST /api/auth/demo                                -> session for the shared demo workspace (DEMO_ACCOUNT=0 disables)
POST /api/auth/logout   Authorization: Bearer <t>  -> revokes the session
GET  /api/auth/me       Authorization: Bearer <t>  -> user + company, 401 if the session is missing or expired

The Next.js app calls these from its own /api/auth/* route handlers and keeps the token in an httpOnly cookie,
so the token never reaches browser JavaScript.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re


from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .store import AccountStore, AuthError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Consumer mailboxes: a workspace is keyed by company domain, so these can't identify a company.
FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.co.uk", "ymail.com", "outlook.com", "hotmail.com",
    "hotmail.co.uk", "live.com", "msn.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com",
    "pm.me", "gmx.com", "gmx.de", "mail.com", "zoho.com", "zohomail.in", "yandex.com", "yandex.ru", "rediffmail.com",
    "qq.com", "163.com", "126.com", "tutanota.com", "hey.com", "fastmail.com", "duck.com", "mailinator.com",
}
SIZE_BANDS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001+"]
JOB_ROLES = ["Recruiter", "Sourcer", "Head of Talent", "Hiring manager", "Founder or executive", "HR or People ops",
             "Agency recruiter", "Other"]
HIRING_VOLUMES = ["1-5", "6-20", "21-50", "51-200", "200+"]
EMAIL_RE = re.compile(r"^[^@\s]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")

DEMO_EMAIL = "demo@sourced-demo.dev"

_store: AccountStore | None = None


def store() -> AccountStore:
    global _store
    if _store is None:
        _store = AccountStore()
        _ensure_demo(_store)
    return _store


def reset_store(s: AccountStore | None) -> None:
    """Tests swap in a temp-file store."""
    global _store
    _store = s
    if s is not None:
        _ensure_demo(s)


def demo_enabled() -> bool:
    return os.getenv("DEMO_ACCOUNT", "1") != "0"


def _ensure_demo(s: AccountStore) -> None:
    if not demo_enabled() or s.user_by_email(DEMO_EMAIL):
        return
    import secrets
    # Nobody logs in to the demo with a password (the "Use the demo workspace" button does it server-side),
    # so it gets a random one unless DEMO_ACCOUNT_PASSWORD is set.
    s.create_account(
        email=DEMO_EMAIL, password=os.getenv("DEMO_ACCOUNT_PASSWORD") or secrets.token_urlsafe(24),
        full_name="Demo Recruiter", job_role="Head of Talent",
        company={"name": "Sourced Demo Co", "size_band": "51-200", "industry": "Software Development",
                 "hq_country": "India", "hiring_volume": "6-20", "hiring_for": ["Engineering", "Product"],
                 "current_ats": "None yet", "verified_via": "demo"})


# ---- request models ---------------------------------------------------------------------------------------------

class LookupIn(BaseModel):
    email: str = Field(max_length=254)


class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    full_name: str = Field(min_length=1, max_length=120)
    job_role: str | None = Field(default=None, max_length=60)
    company_name: str | None = Field(default=None, max_length=160)
    size_band: str | None = None
    industry: str | None = Field(default=None, max_length=120)
    hq_country: str | None = Field(default=None, max_length=80)
    hiring_volume: str | None = None
    hiring_for: list[str] = Field(default_factory=list, max_length=12)
    current_ats: str | None = Field(default=None, max_length=60)
    accept_terms: bool = False


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


# ---- helpers ----------------------------------------------------------------------------------------------------

def _err(code: str, message: str, status: int = 400, field: str | None = None) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, "field": field}, status_code=status)


def _domain_of(email: str) -> str | None:
    email = email.strip().lower()
    return email.rsplit("@", 1)[1] if EMAIL_RE.match(email) else None


def _band(rng: str | None) -> str | None:
    """Crustdata's employee_count_range ('1001-5000', '10001+') -> one of SIZE_BANDS."""
    if not rng:
        return None
    m = re.match(r"(\d+)", rng.replace(",", ""))
    if not m:
        return None
    lo = int(m.group(1))
    for band in reversed(SIZE_BANDS):
        if lo >= int(re.match(r"\d+", band).group()):
            return band
    return None


async def identify_company(domain: str) -> dict | None:
    """Live Crustdata Company Identify on the email domain. Returns None (never raises) when there's no match,
    no key, or the API is slow: sign-up then falls back to typed-in details marked self_reported."""
    try:
        from ..crustdata.client import CrustdataClient
        async with CrustdataClient() as client:
            data = await asyncio.wait_for(client.company_identify(domain=domain), timeout=8)
    except Exception as e:  # noqa: BLE001  (missing key, network, timeout: all mean "no prefill")
        log.info("company identify for %s unavailable: %s", domain, e)
        return None
    info = (data or {}).get("basic_info") or {}
    if not info.get("name"):
        return None
    domains = {d.lower() for d in (info.get("all_domains") or [])} | {(info.get("primary_domain") or "").lower()}
    if domain not in domains:
        return None  # fuzzy match to some other company: don't attach it
    return {
        "name": info["name"],
        "size_band": _band(info.get("employee_count_range")),
        "employee_count_range": info.get("employee_count_range"),
        "industry": (info.get("industries") or [None])[0],
        "logo_url": info.get("logo_permalink"),
        "linkedin_url": info.get("professional_network_url"),
        "year_founded": info.get("year_founded"),
        "crustdata_company_id": info.get("crustdata_company_id") or (data or {}).get("crustdata_company_id"),
        "source": {"endpoint": "company/identify", "field": "basic_info", "url": None},
    }


def _session_payload(user: dict, company: dict, token: str, expires: str, joined: bool = False) -> dict:
    return {"token": token, "expires_at": expires, "user": user, "company": company, "joined_existing": joined}


def _bearer(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


# ---- routes -----------------------------------------------------------------------------------------------------

@router.get("/options")
async def options():
    return {"size_bands": SIZE_BANDS, "job_roles": JOB_ROLES, "hiring_volumes": HIRING_VOLUMES,
            "demo_enabled": demo_enabled()}


@router.post("/lookup")
async def lookup(body: LookupIn):
    domain = _domain_of(body.email)
    if not domain:
        return _err("invalid_email", "Enter a valid email address.", field="email")
    if domain in FREE_EMAIL_DOMAINS:
        return _err("personal_email", "Use your work email. Workspaces are set up per company domain.", field="email")
    s = store()
    if s.user_by_email(body.email):
        return _err("email_taken", "An account with this email already exists. Log in instead.", 409, field="email")
    existing = s.company_by_domain(domain)
    if existing:
        return {"domain": domain, "existing_workspace": {"name": existing["name"],
                                                         "members": len(s.members(existing["id"]))}, "company": None}
    return {"domain": domain, "existing_workspace": None, "company": await identify_company(domain)}


@router.post("/signup")
async def signup(body: SignupIn, request: Request):
    domain = _domain_of(body.email)
    if not domain:
        return _err("invalid_email", "Enter a valid email address.", field="email")
    if domain in FREE_EMAIL_DOMAINS:
        return _err("personal_email", "Use your work email. Workspaces are set up per company domain.", field="email")
    if len(body.password) < 10:
        return _err("weak_password", "Use at least 10 characters.", field="password")
    if body.password.lower() in {body.email.lower(), body.email.split("@")[0].lower()}:
        return _err("weak_password", "Don't use your email as your password.", field="password")
    if not body.accept_terms:
        return _err("terms", "Accept the terms to create a workspace.", field="accept_terms")
    if body.size_band and body.size_band not in SIZE_BANDS:
        return _err("invalid", "Pick a company size from the list.", field="size_band")
    if body.hiring_volume and body.hiring_volume not in HIRING_VOLUMES:
        return _err("invalid", "Pick a hiring volume from the list.", field="hiring_volume")

    s = store()
    company: dict = {}
    if not s.company_by_domain(domain):
        if not (body.company_name or "").strip():
            return _err("required", "Enter your company name.", field="company_name")
        # Re-check the domain server-side instead of trusting a client-sent "verified" flag.
        found = await identify_company(domain)
        company = {
            "name": body.company_name, "size_band": body.size_band, "industry": body.industry or (found or {}).get("industry"),
            "hq_country": body.hq_country, "hiring_volume": body.hiring_volume, "hiring_for": body.hiring_for,
            "current_ats": body.current_ats,
            "crustdata_company_id": (found or {}).get("crustdata_company_id"),
            "verified_via": "crustdata" if found else "self_reported",
        }
    try:
        user, comp, joined = s.create_account(email=body.email, password=body.password, full_name=body.full_name,
                                              job_role=body.job_role, company=company)
    except AuthError as e:
        return _err(e.code, e.message, e.status, field="email")
    token, expires = s.create_session(user["id"], request.headers.get("user-agent"))
    return _session_payload(user, comp, token, expires, joined)


@router.post("/login")
async def login(body: LoginIn, request: Request):
    s = store()
    try:
        user = s.authenticate(body.email, body.password)
    except AuthError as e:
        return _err(e.code, e.message, e.status)
    token, expires = s.create_session(user["id"], request.headers.get("user-agent"))
    return _session_payload(user, s.company(user["company_id"]), token, expires)


@router.post("/demo")
async def demo(request: Request):
    if not demo_enabled():
        return _err("demo_disabled", "The demo workspace is turned off on this server.", 404)
    s = store()
    row = s.user_by_email(DEMO_EMAIL)
    token, expires = s.create_session(row["id"], request.headers.get("user-agent"))
    return _session_payload(s.user(row["id"]), s.company(row["company_id"]), token, expires)


@router.post("/logout")
async def logout(authorization: str | None = Header(default=None)):
    token = _bearer(authorization)
    if token:
        store().revoke_session(token)
    return {"ok": True}


@router.get("/me")
async def me(authorization: str | None = Header(default=None)):
    found = store().session_user(_bearer(authorization))
    if not found:
        return _err("unauthenticated", "Your session has ended. Log in again.", 401)
    user, company, expires = found
    return {"user": user, "company": company, "expires_at": expires}


