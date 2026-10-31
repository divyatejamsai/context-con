"""Seals: how the person (or agent) on the receiving end checks that a message really came from a governed agent.

Every message Agaxes lets out (the outbox) and every signed offer letter ends with a footer:

    --
    Sent by Scheduler, AI agent for Grewon Technologies, vouched for by Pankaj Savaliya. Verify: <url>/verify/<seal id>

The agent's signature covers the content above the footer (the footer is the envelope). Anyone can open the link with
no login, or call GET/POST /api/verify, and get one plain verdict built from these checks:

    issued_by_agaxes     the passport carries Agaxes's issuer signature
    agent_signature      the content was signed by the key in that passport
    content_untampered   the text is exactly what was signed (paste what you received to check it)
    agent_in_good_standing   the agent is active now: not suspended, offboarded or revoked
    in_scope             the action (e.g. contract.sign for an offer) is in the passport
    sponsor checks       the sponsor still exists, still works there and can still grant that scope (live, or the
                         recorded Crustdata data in replay/cache mode)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ledger
from .models import Passport

MARK = "\n\n-- \nSent by "
_lock = threading.Lock()
_SEAL_RE = re.compile(r"/verify/([a-f0-9]{12})\b")


def base_url() -> str:
    return os.getenv("AGAXES_PUBLIC_URL", "http://localhost:3000").rstrip("/")


def path() -> Path:
    if os.getenv("SEALS_PATH"):
        return Path(os.environ["SEALS_PATH"])
    from .guard import outbox_path
    return outbox_path().parent / "seals.jsonl"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def issue(passport: Passport | dict, signature: str, body: str, scope: str, kind: str = "message",
          to: dict | None = None) -> tuple[str, str]:
    """Record the seal and return (seal_id, body with the verify footer)."""
    p = passport if isinstance(passport, Passport) else Passport.model_validate(passport)
    sid = secrets.token_hex(6)
    s = p.sponsor
    footer = (f"{MARK}{p.agent_name}, AI agent for {s.company}, vouched for by {s.name}. "
              f"Verify: {base_url()}/verify/{sid}")
    rec = {"seal_id": sid, "agent_id": p.agent_id, "agent_name": p.agent_name, "kind": kind, "scope": scope,
           "sha256": sha(body), "body": body, "signature": signature, "to": (to or {}).get("name"),
           "company": s.company, "sponsor": s.name, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    rec["ledger_entry"] = ledger.append("seal.issued", {k: rec[k] for k in ("seal_id", "agent_id", "kind", "scope", "sha256", "to")})
    out = path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with _lock, out.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return sid, body + footer


def get(seal_id: str) -> dict | None:
    try:
        lines = path().read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if f'"seal_id": "{seal_id}"' in line:
            return json.loads(line)
    return None


_BANNER = re.compile(r"^\s*\[[^\]]*this copy came to [^\]]*\]\s*", re.S)  # the test-inbox note (outbound/mailer.py)


def split(text: str) -> tuple[str, str | None]:
    """(the signed content, the seal id from the footer, if any). Tolerates the test-inbox banner and mail clients
    that turn line endings into CRLF or trim the space in the "-- " signature line."""
    t = _BANNER.sub("", text.replace("\r\n", "\n"), count=1)
    m = _SEAL_RE.search(t)
    i = max(t.rfind("\n-- \nSent by "), t.rfind("\n--\nSent by "))
    content = t[:i].rstrip("\n") if i >= 0 else t
    return content, (m.group(1) if m else None)


def latest(agent_id: str, body_sha: str) -> dict | None:
    """The newest seal this agent got for exactly this content."""
    try:
        lines = path().read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        r = json.loads(line)
        if r["agent_id"] == agent_id and r["sha256"] == body_sha:
            return r
    return None


def sealed_text(rec: dict) -> str:
    return (f"{rec['body']}{MARK}{rec['agent_name']}, AI agent for {rec['company']}, vouched for by {rec['sponsor']}. "
            f"Verify: {base_url()}/verify/{rec['seal_id']}")


async def email_copy(rec: dict, subject: str, to: dict | None = None) -> dict:
    """Deliver the sealed text to the test inbox (OUTBOUND_TEST_TO, never the recipient: app/outbound/mailer.py), so a
    person can open it in their mail client and click Verify. Never raises; says why when nothing was sent."""
    from ..outbound import mailer
    c = mailer.config()
    if not c["ready"]:
        return {"emailed": False, "why": c["reason"]}
    try:
        d = await mailer.send(mailer.Envelope(intended_to=(to or {}).get("email") or f"{rec.get('to') or 'recipient'} (no address on file)",
                                              to_name=rec.get("to"), subject=subject, body=sealed_text(rec),
                                              from_name=f"{rec['agent_name']} (AI agent, {rec['company']})"))
    except Exception as e:  # noqa: BLE001
        return {"emailed": False, "why": f"{type(e).__name__}: {e}"}
    ledger.append("seal.emailed", {"seal_id": rec["seal_id"], "delivered_to": d.delivered_to, "provider": d.provider})
    return {"emailed": True, "delivered_to": d.delivered_to, "provider": d.provider}


async def verify(seal_id: str | None = None, text: str | None = None, client: Any = None) -> dict:
    from . import registry
    from .passport import signature_valid, verify_message_signature, verify_passport
    content = None
    if text:
        content, found = split(text)
        seal_id = seal_id or found
    s = get(seal_id) if seal_id else None
    if not s:
        return {"verdict": "invalid", "headline": "No Agaxes seal matches this link or message.", "checks": [], "seal": None}
    checks: list[dict] = []

    def add(name: str, label: str, status: str, detail: str) -> None:
        checks.append({"name": name, "label": label, "status": status, "detail": detail})

    try:
        rec = registry.get_agent(s["agent_id"])
    except Exception:  # noqa: BLE001
        rec = None
    if rec is None:
        add("agent_known", "Agent is known to Agaxes", "fail", "The agent behind this seal is not in the registry")
    else:
        p = Passport.model_validate(rec["passport"])
        add("issued_by_agaxes", "Passport issued by Agaxes", "pass" if signature_valid(p) else "fail",
            "Issuer signature on the passport is valid" if signature_valid(p) else "The passport's issuer signature is invalid")
        body = content if content is not None else s["body"]
        sig_ok = verify_message_signature(p, body, s["signature"] or "")
        add("agent_signature", "Signed by the agent's key", "pass" if sig_ok else "fail",
            f"Signature matches {p.agent_name}'s public key" if sig_ok else "Signature does not match this text and the agent's key")
        if content is not None:
            same = sha(content) == s["sha256"]
            add("content_untampered", "Content not altered", "pass" if same else "fail",
                "Text is exactly what the agent signed" if same else "Text differs from what the agent signed")
        else:
            add("content_untampered", "Content not altered", "pass",
                "Showing the signed text: compare it with what you received, or paste it below")
        rev = ledger.is_revoked(p.agent_id)
        good = rec["status"] == "active" and not rev
        add("agent_in_good_standing", "Agent in good standing now", "pass" if good else "fail",
            "Active, not suspended or revoked" if good else
            f"{p.agent_name} is {rec['status']}" + (f": {rec.get('reason')}" if rec.get("reason") else ""))
        in_scope = s["scope"] in p.scopes
        add("in_scope", f"Allowed to do this ({s['scope']})", "pass" if in_scope else "fail",
            f"Passport grants {s['scope']}" if in_scope else f"Passport does not grant {s['scope']}")
        v = await verify_passport(p, client, s["scope"], record=False)
        labels = {"sponsor_exists": "Sponsor is a real person", "sponsor_still_employed": "Sponsor still works there",
                  "sponsor_can_grant_scope": "Sponsor can grant this", "sponsor_title_current": "Sponsor's title is current",
                  "not_expired": "Passport not expired"}
        for c in v.checks:
            if c.name in labels:
                add(c.name, labels[c.name], c.status, c.detail)
    bad = [c for c in checks if c["status"] == "fail"]
    unsure = [c for c in checks if c["status"] == "unverifiable"]
    verdict = "invalid" if bad else ("unconfirmed" if unsure else "genuine")
    who = f"{s['agent_name']}, an AI agent for {s['company']} vouched for by {s['sponsor']}"
    headline = {"genuine": f"Genuine. This was sent by {who}, and every check passes right now.",
                "invalid": f"Do not trust this. {bad[0]['label'] if bad else ''}: {bad[0]['detail'] if bad else ''}",
                "unconfirmed": f"Signed by {who}, but some live checks couldn't be run right now."}[verdict]
    return {"verdict": verdict, "headline": headline, "checks": checks,
            "seal": {k: s[k] for k in ("seal_id", "agent_name", "kind", "scope", "to", "company", "sponsor", "created_at",
                                       "sha256", "body", "ledger_entry")}}
