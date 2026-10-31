"""Auth routes for company accounts. Mounted in app/main.py.

POST /api/auth/lookup   {email}                    -> domain checks + Crustdata Company Identify prefill
POST /api/auth/signup   {email, password, ...}     -> creates user (+ workspace) and a session
POST /api/auth/login    {email, password}          -> session
POST /api/auth/demo     {as?}                      -> a demo session (DEMO_ACCOUNT=0 disables). as = "admin" (default: the
                                                      demo company's owner), "recruiter" (a member who sees only the
                                                      agents assigned to them) or "operator" (the platform, every company)
POST /api/auth/forgot   {email}                    -> emails a one-time reset link (30 min) via app.outbound.mailer
POST /api/auth/reset    {token, password}          -> sets the password, signs out other sessions, returns a session
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


DEMO_RECRUITER_EMAIL = "recruiter@sourced-demo.dev"
DEMO_PEOPLE = {"admin": DEMO_EMAIL, "recruiter": DEMO_RECRUITER_EMAIL}


def _ensure_demo(s: AccountStore) -> None:
    if not demo_enabled():
        return
    import secrets
    from .authz import OPERATOR_DEMO_EMAIL
    if not s.user_by_email(OPERATOR_DEMO_EMAIL):
        s.create_account(email=OPERATOR_DEMO_EMAIL, password=secrets.token_urlsafe(24), full_name="Platform Operator",
                         job_role="Agaxes operator", company={"name": "Agaxes Platform", "verified_via": "demo"})
    _ensure_demo_company(s)
    if not s.user_by_email(DEMO_RECRUITER_EMAIL):  # joins the demo company by domain, as a member
        s.create_account(email=DEMO_RECRUITER_EMAIL, password=secrets.token_urlsafe(24), full_name="Riya Recruiter",
                         job_role="Recruiter", company={})


def _ensure_demo_company(s: AccountStore) -> None:
    if s.user_by_email(DEMO_EMAIL):
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


class ForgotIn(BaseModel):
    email: str = Field(max_length=254)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=200)


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


def _password_problem(password: str, email: str) -> str | None:
    if len(password) < 10:
        return "Use at least 10 characters."
    if password.lower() in {email.lower(), email.split("@")[0].lower()}:
        return "Don't use your email as your password."
    return None


def app_url() -> str:
    return (os.getenv("PUBLIC_APP_URL") or "http://localhost:3000").rstrip("/")


async def send_reset_email(to: str, name: str, link: str) -> None:
    """Raises SendRefused (or ImportError before the mailer exists) when email isn't set up."""
    from ..outbound.mailer import send_transactional
    first = (name or "there").split()[0]
    body = (f"Hi {first},\n\nSomeone asked to reset the password for your Sourced account ({to}).\n\n"
            f"Set a new password here (the link works once, for 30 minutes):\n{link}\n\n"
            "If this wasn't you, ignore this email. Your password stays the same.\n\nSourced")
    await send_transactional(to, "Reset your Sourced password", body)


def _access(user: dict, company: dict) -> dict:
    from .authz import RANK, Principal, operator_emails
    role = "operator" if user["email"].lower() in operator_emails() else user.get("workspace_role") or "member"
    return Principal(via="session", role=role if role in RANK else "viewer", user=user, company=company).access()


def _session_payload(user: dict, company: dict, token: str, expires: str, joined: bool = False) -> dict:
    return {"token": token, "expires_at": expires, "user": user, "company": company, "joined_existing": joined,
            "access": _access(user, company)}


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
    if problem := _password_problem(body.password, body.email):
        return _err("weak_password", problem, field="password")
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


GENERIC_SENT = "If that email has a Sourced account, a reset link is on its way. It works once, for 30 minutes."


@router.post("/forgot")
async def forgot(body: ForgotIn):
    s = store()
    row = s.user_by_email(body.email.strip())
    if row is None or row["email"] in {DEMO_EMAIL, DEMO_RECRUITER_EMAIL, "operator@agaxes-demo.dev"}:
        return {"ok": True, "message": GENERIC_SENT}  # same answer either way: don't reveal which emails exist
    token = s.create_reset(row["id"])
    if token is None:
        return {"ok": True, "message": GENERIC_SENT}
    try:
        await send_reset_email(row["email"], row["full_name"], f"{app_url()}/reset?token={token}")
    except Exception as e:  # noqa: BLE001  SendRefused, missing mailer, provider down
        log.warning("password reset email not sent: %s", e)
        unset = type(e).__name__ in {"SendRefused", "ImportError", "ModuleNotFoundError"}
        return _err("email_unavailable",
                    "Email isn't set up on this server, so we can't send a reset link. Ask your workspace owner, "
                    "or set SMTP_* or RESEND_API_KEY in backend/.env." if unset
                    else "We couldn't send the email just now. Try again in a minute.", 503)
    return {"ok": True, "message": GENERIC_SENT}


@router.post("/reset")
async def reset(body: ResetIn, request: Request):
    s = store()
    email = s.reset_email(body.token)
    if email and (problem := _password_problem(body.password, email)):
        return _err("weak_password", problem, field="password")
    try:
        user = s.reset_password(body.token, body.password)
    except AuthError as e:
        return _err(e.code, e.message, e.status)
    token, expires = s.create_session(user["id"], request.headers.get("user-agent"))
    return _session_payload(user, s.company(user["company_id"]), token, expires)


class DemoIn(BaseModel):
    as_: str = Field(default="admin", alias="as")


def claim_demo_agents(s: AccountStore) -> None:
    """The demo company's own AI employee is Sourced: give it any Sourced that isn't in a company yet, and assign it
    to the demo recruiter. The rest of the seeded fleet stays on the platform (operator only)."""
    try:
        from ..agents import registry
        owner, rec = s.user_by_email(DEMO_EMAIL), s.user_by_email(DEMO_RECRUITER_EMAIL)
        if not owner:
            return
        for a in registry.list_agents():
            if a["name"].lower() == "sourced" and not a.get("workspace_id") and a["status"] != "offboarded":
                registry.set_workspace(a["agent_id"], owner["company_id"], by="demo setup")
                if rec:
                    registry.set_assignees(a["agent_id"], [rec["id"]], by="demo setup")
    except Exception as e:  # noqa: BLE001  a demo nicety: never block the sign-in
        log.warning("couldn't give Sourced to the demo company: %s", e)


@router.post("/demo")
async def demo(request: Request, body: DemoIn | None = None):
    if not demo_enabled():
        return _err("demo_disabled", "The demo workspace is turned off on this server.", 404)
    from .authz import OPERATOR_DEMO_EMAIL
    who = (body.as_ if body else "admin").lower()
    email = {"operator": OPERATOR_DEMO_EMAIL, **DEMO_PEOPLE}.get(who)
    if not email:
        return _err("invalid", "as is one of admin, recruiter, operator.", field="as")
    s = store()
    claim_demo_agents(s)
    row = s.user_by_email(email)
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
    return {"user": user, "company": company, "expires_at": expires, "access": _access(user, company)}


