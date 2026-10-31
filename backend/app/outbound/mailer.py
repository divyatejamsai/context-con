"""Email providers and the send policy. Real sends only: if nothing is configured, nothing is sent and we say so.

Providers (OUTBOUND_PROVIDER, default: resend if RESEND_API_KEY is set, else smtp if SMTP_HOST is set, else none)
    resend   POST https://api.resend.com/emails. Delivery status is read back from GET /emails/{id} (last_event).
             Without a verified domain Resend only sends from onboarding@resend.dev to your own account address,
             which is exactly what test mode needs.
    smtp     any SMTP server, e.g. Gmail with an app password (smtp.gmail.com:465, SMTP_USER, SMTP_PASSWORD).
             Status is "sent" once the server accepts it; bounces and replies are read over IMAP (tracking.py).

Policy (OUTBOUND_MODE)
    test (default)  every email is delivered to OUTBOUND_TEST_TO (your own inbox), never to the candidate. The real
                    address Crustdata found is kept on the record and shown in a banner at the top of the email.
                    The event rule: agents contact only our own team.
    live            emails go to the candidate's real address. Needs OUTBOUND_LIVE_CONFIRM=yes as well, so one
                    stray env var can't start emailing real people.
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import httpx

log = logging.getLogger(__name__)

RESEND_URL = os.getenv("RESEND_API_URL", "https://api.resend.com")


class SendRefused(Exception):
    """Policy or configuration stops this send (not a provider failure)."""


@dataclass
class Envelope:
    intended_to: str                   # the candidate's real address (from Crustdata)
    to_name: str | None
    subject: str
    body: str
    from_name: str | None = None
    reply_to: str | None = None
    in_reply_to: str | None = None     # Message-ID of the message this follows up
    references: list[str] = field(default_factory=list)


@dataclass
class Delivery:
    provider: str
    mode: str
    delivered_to: str                  # where it actually went (the test inbox in test mode)
    provider_id: str | None
    message_id: str                    # RFC 5322 Message-ID we set, used to thread replies
    status: str                        # sent (accepted by the provider)
    from_addr: str


def mode() -> str:
    return (os.getenv("OUTBOUND_MODE") or "test").strip().lower()


def provider() -> str:
    p = (os.getenv("OUTBOUND_PROVIDER") or "").strip().lower()
    if p:
        return p
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    if os.getenv("SMTP_HOST"):
        return "smtp"
    return "none"


def from_addr() -> str:
    if os.getenv("MAIL_FROM"):
        return os.environ["MAIL_FROM"]
    if provider() == "resend":
        return "onboarding@resend.dev"
    return os.getenv("SMTP_USER") or ""


def reply_to() -> str | None:
    return os.getenv("MAIL_REPLY_TO") or os.getenv("IMAP_USER") or (os.getenv("SMTP_USER") if provider() == "smtp" else None)


def config() -> dict:
    """What the UI shows about sending. No secrets."""
    m, p = mode(), provider()
    test_to = os.getenv("OUTBOUND_TEST_TO") or ""
    ready, why = True, ""
    if p == "none":
        ready, why = False, "No email provider set up: add RESEND_API_KEY, or SMTP_HOST/SMTP_USER/SMTP_PASSWORD, to backend/.env"
    elif m == "test" and not test_to:
        ready, why = False, "Test mode needs OUTBOUND_TEST_TO (your own inbox) in backend/.env"
    elif m == "live" and os.getenv("OUTBOUND_LIVE_CONFIRM", "").lower() != "yes":
        ready, why = False, "Live mode also needs OUTBOUND_LIVE_CONFIRM=yes"
    elif m not in ("test", "live"):
        ready, why = False, f"Unknown OUTBOUND_MODE {m!r} (use test or live)"
    elif not from_addr():
        ready, why = False, "No sender address: set MAIL_FROM"
    return {"provider": p, "mode": m, "ready": ready, "reason": why, "test_to": test_to if m == "test" else None,
            "from": from_addr() or None, "reply_to": reply_to()}


def _target(env: Envelope) -> str:
    c = config()
    if not c["ready"]:
        raise SendRefused(c["reason"])
    return c["test_to"] if c["mode"] == "test" else env.intended_to


def _text(env: Envelope, to: str) -> str:
    if to.lower() == env.intended_to.lower():
        return env.body
    who = f"{env.to_name} <{env.intended_to}>" if env.to_name else env.intended_to
    return (f"[Sourced test send. In live mode this goes to {who}, the address Crustdata has on record.]\n\n{env.body}")


def _msgid() -> str:
    dom = (from_addr().rsplit("@", 1)[-1] or "sourced.local") if "@" in from_addr() else "sourced.local"
    return make_msgid(idstring=uuid.uuid4().hex[:12], domain=dom)


async def send(env: Envelope) -> Delivery:
    """Send one email. Raises SendRefused (policy/config) or RuntimeError (the provider failed)."""
    to = _target(env)
    p = provider()
    msgid = _msgid()
    text = _text(env, to)
    if p == "resend":
        return await _send_resend(env, to, text, msgid)
    if p == "smtp":
        return await asyncio.to_thread(_send_smtp, env, to, text, msgid)
    raise SendRefused(f"Unknown OUTBOUND_PROVIDER {p!r}")


async def _send_resend(env: Envelope, to: str, text: str, msgid: str) -> Delivery:
    sender = formataddr((env.from_name, from_addr())) if env.from_name else from_addr()
    headers = {"X-Sourced-Message-Id": msgid}
    if env.in_reply_to:
        headers["In-Reply-To"] = env.in_reply_to
        headers["References"] = " ".join(env.references or [env.in_reply_to])
    payload = {"from": sender, "to": [to], "subject": env.subject, "text": text, "headers": headers}
    rt = env.reply_to or reply_to()
    if rt:
        payload["reply_to"] = rt
    async with httpx.AsyncClient(base_url=RESEND_URL, timeout=20) as http:
        r = await http.post("/emails", json=payload, headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"})
    if r.status_code >= 300:
        raise RuntimeError(f"Resend refused the email ({r.status_code}): {r.text[:300]}")
    return Delivery(provider="resend", mode=mode(), delivered_to=to, provider_id=(r.json() or {}).get("id"),
                    message_id=msgid, status="sent", from_addr=from_addr())


def _send_smtp(env: Envelope, to: str, text: str, msgid: str) -> Delivery:
    m = EmailMessage()
    m["From"] = formataddr((env.from_name, from_addr())) if env.from_name else from_addr()
    m["To"] = formataddr((env.to_name, to)) if env.to_name and to == env.intended_to else to
    m["Subject"] = env.subject
    m["Date"] = formatdate(localtime=False)
    m["Message-ID"] = msgid
    rt = env.reply_to or reply_to()
    if rt:
        m["Reply-To"] = rt
    if env.in_reply_to:
        m["In-Reply-To"] = env.in_reply_to
        m["References"] = " ".join(env.references or [env.in_reply_to])
    m.set_content(text)
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "465"))
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                if user:
                    s.login(user, pw or "")
                s.send_message(m)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                if os.getenv("SMTP_STARTTLS", "true").lower() != "false":  # false only for a local test server
                    s.starttls(context=ctx)
                if user:
                    s.login(user, pw or "")
                s.send_message(m)
    except (smtplib.SMTPException, OSError) as e:
        raise RuntimeError(f"SMTP send failed: {e}") from e
    return Delivery(provider="smtp", mode=mode(), delivered_to=to, provider_id=None, message_id=msgid,
                    status="sent", from_addr=from_addr())


async def resend_status(provider_id: str) -> str | None:
    """Resend's last_event for an email: sent, delivered, delivery_delayed, bounced, complained, opened, clicked."""
    if not provider_id or not os.getenv("RESEND_API_KEY"):
        return None
    async with httpx.AsyncClient(base_url=RESEND_URL, timeout=15) as http:
        r = await http.get(f"/emails/{provider_id}", headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"})
    if r.status_code >= 300:
        log.info("resend status %s -> %s", provider_id, r.status_code)
        return None
    return (r.json() or {}).get("last_event")


async def send_transactional(to: str, subject: str, body: str) -> Delivery:
    """Account email (password reset, sign-in links) to a user of this product, not outreach: no Send Guard and no
    test redirect, since it goes to the address the user signed up with. Raises SendRefused if no provider is set."""
    p = provider()
    if p == "none" or not from_addr():
        raise SendRefused("No email provider set up")
    env = Envelope(intended_to=to, to_name=None, subject=subject, body=body, from_name="Sourced")
    msgid = _msgid()
    if p == "resend":
        return await _send_resend(env, to, body, msgid)
    return await asyncio.to_thread(_send_smtp, env, to, body, msgid)
