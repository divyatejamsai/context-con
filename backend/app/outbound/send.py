"""guarded_send: the one way an AI employee emails someone.

    res = await guarded_send("sourced", to={"name", "profile_url", "company"}, subject=..., body=...,
                             scope="outreach.hiring", thread_key="campaign:conv")

1. The agent must be active in the registry (its passport is loaded from there).
2. The email address comes from Crustdata (contacts.find_email) unless the caller passes one it got from Crustdata.
3. The body is signed with the agent's key and run through Send Guard (passport, signature, recipient still at the
   company, every claim in the body). Anything but allow stops here. A verdict the caller already has for this exact
   body (the run's own guard step, passed as verdict + verdict_body) is reused instead of paying for the checks twice.
4. The email goes out through the configured provider (mailer.py; test mode redirects to your own inbox).
5. A message record (messages.py) and a message.sent ledger entry are written, citing the guard verdict and the
   Crustdata source of the address.
Never raises for expected failures: the result says what happened.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from pydantic import BaseModel

from ..agents import ledger, registry
from ..agents.graph import Graph
from ..agents.guard import blocking_reasons, check_send
from ..agents.models import Passport, Verdict
from ..agents.passport import sign_message
from . import mailer, messages
from .contacts import ContactInfo, find_email

log = logging.getLogger(__name__)


class SendResult(BaseModel):
    ok: bool                          # an email actually left
    status: str                       # sent | blocked | no_email | not_configured | failed | inactive
    detail: str
    message: dict | None = None       # the stored message record
    verdict: dict | None = None       # Send Guard verdict (decision, checks, ledger_entry)
    contact: dict | None = None


def _sha(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


def _signoff(p: Passport) -> str:
    s = p.sponsor
    return f"{s.name}\n{s.title + ', ' if s.title else ''}{s.company}"


def finalize_body(body: str, passport: Passport) -> str:
    """Replace the draft's sign-off placeholder with the real sponsor, so the email says who is hiring."""
    return body.replace("[Your name]", _signoff(passport)).strip()


async def guarded_send(agent_id: str, to: dict, subject: str, body: str, *, scope: str = "outreach.hiring",
                       thread_key: str | None = None, email: ContactInfo | dict | None = None,
                       verdict: Verdict | dict | None = None, verdict_body: str | None = None,
                       client: Any = None, graph: Graph | None = None) -> SendResult:
    from ..agents.api import crustdata
    from ..sourced_agent import resolve_agent_id

    agent_id = resolve_agent_id(agent_id)
    try:
        rec = registry.get_agent(agent_id)
    except Exception:  # noqa: BLE001
        return SendResult(ok=False, status="inactive", detail=f"Unknown agent {agent_id}")
    if rec.get("status") != "active":
        return SendResult(ok=False, status="inactive", detail=f"{rec.get('name')} is {rec.get('status')}: it may not send")
    passport = Passport.model_validate(rec["passport"])
    body = finalize_body(body or "", passport)
    subject = (subject or "").strip() or f"{passport.role} at {passport.sponsor.company}"
    to = {k: to.get(k) for k in ("name", "profile_url", "company") if to.get(k)}

    cfg = mailer.config()
    if not cfg["ready"]:
        return SendResult(ok=False, status="not_configured", detail=cfg["reason"])

    client = client if client is not None else crustdata()
    graph = graph or Graph(client)

    # 2. the address
    contact = ContactInfo.model_validate(email) if isinstance(email, dict) else email
    if contact is None or not contact.email:
        contact = await find_email(client, to.get("profile_url") or "")
    if not contact.email:
        return SendResult(ok=False, status="no_email", detail=contact.error or contact.note, contact=contact.model_dump())

    # 3. Send Guard on the exact body that will go out
    v = Verdict.model_validate(verdict) if isinstance(verdict, dict) else verdict
    reuse = v is not None and v.decision == "allow" and verdict_body is not None and finalize_body(verdict_body, passport) == body
    if not reuse:
        key = registry.private_key(agent_id)
        try:
            v = await check_send(passport, sign_message(passport, key, body), to, body, scope, client, graph=graph,
                                 agent_status=rec.get("status"))
        except Exception as e:  # noqa: BLE001 - a guard failure blocks
            log.warning("guard failed: %s", e)
            v = None
    vd = v.model_dump() if v else {"decision": "block", "checks": [], "ledger_entry": None, "error": "Send Guard could not finish"}
    base = {"agent_id": agent_id, "thread_key": thread_key, "scope": scope, "to": to, "subject": subject, "body": body,
            "contact": contact.model_dump(mode="json"), "guard": vd}
    if vd["decision"] != "allow":
        why = "; ".join(blocking_reasons(v)) if v else vd["error"]
        m = messages.create({**base, "status": "blocked", "detail": why})
        return SendResult(ok=False, status="blocked", detail=why, message=m, verdict=vd, contact=contact.model_dump())

    # 4. send, following the thread when there is one
    prior = [r for r in messages.list_all(thread_key=thread_key) if r.get("message_id")] if thread_key else []
    env = mailer.Envelope(intended_to=contact.email, to_name=to.get("name"), subject=subject, body=body,
                          from_name=f"{passport.sponsor.name} ({passport.sponsor.company})",
                          in_reply_to=prior[0]["message_id"] if prior else None,
                          references=[r["message_id"] for r in reversed(prior)])
    try:
        d = await mailer.send(env)
    except mailer.SendRefused as e:
        return SendResult(ok=False, status="not_configured", detail=str(e), verdict=vd, contact=contact.model_dump())
    except Exception as e:  # noqa: BLE001 - provider error
        m = messages.create({**base, "status": "failed", "detail": str(e)[:300]})
        return SendResult(ok=False, status="failed", detail=str(e)[:300], message=m, verdict=vd, contact=contact.model_dump())

    entry = ledger.append("message.sent", {
        "agent_id": agent_id, "scope": scope, "thread_key": thread_key, "to": to, "intended_to": contact.email,
        "delivered_to": d.delivered_to, "mode": d.mode, "provider": d.provider, "provider_id": d.provider_id,
        "message_id": d.message_id, "subject": subject, "body_sha256": _sha(body), "guard_entry": vd.get("ledger_entry"),
    }, [contact.source] if contact.source else [])
    detail = (f"Sent to {d.delivered_to} (test mode; {contact.email} in live mode)" if d.mode == "test"
              else f"Sent to {d.delivered_to}")
    m = messages.create({**base, "status": "sent", "detail": detail, "provider": d.provider, "provider_id": d.provider_id,
                         "message_id": d.message_id, "mode": d.mode, "intended_to": contact.email,
                         "delivered_to": d.delivered_to, "from": d.from_addr, "ledger_entry": entry})
    return SendResult(ok=True, status="sent", detail=detail, message=m, verdict=vd, contact=contact.model_dump())

