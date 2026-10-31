"""Delivery status and replies for sent messages. Call refresh() (POST /api/messages/refresh does) as often as you like.

Delivery
    resend  GET /emails/{id} -> last_event (delivered, bounced, complained, opened, clicked, delivery_delayed)
    smtp    accepted by the server = sent. A bounce notice in the mailbox that names our Message-ID marks it bounced.
Replies (IMAP, any provider)
    IMAP_HOST / IMAP_USER / IMAP_PASSWORD; with Gmail SMTP they default to imap.gmail.com and the SMTP login.
    Point MAIL_REPLY_TO at that mailbox so candidates' replies land there. A message is a reply to ours when its
    In-Reply-To/References names our Message-ID, or (some clients drop those) its subject is "Re: <our subject>" and
    it comes from the address we sent to.
Reply handlers: register_reply_handler(fn) gets (message_record, reply) for every new reply, e.g. the conversation
engine feeding it to the right conversation by message_record["thread_key"].
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Awaitable, Callable

from ..agents import ledger
from . import mailer, messages

log = logging.getLogger(__name__)

ReplyHandler = Callable[[dict, dict], Awaitable[None] | None]
_handlers: list[ReplyHandler] = []


def register_reply_handler(fn: ReplyHandler) -> None:
    _handlers.append(fn)


def imap_settings() -> dict | None:
    host = os.getenv("IMAP_HOST")
    user, pw = os.getenv("IMAP_USER"), os.getenv("IMAP_PASSWORD")
    if not host and (os.getenv("SMTP_HOST") or "").endswith("gmail.com"):
        host = "imap.gmail.com"
    user = user or os.getenv("SMTP_USER")
    pw = pw or os.getenv("SMTP_PASSWORD")
    if not (host and user and pw):
        return None
    return {"host": host, "port": int(os.getenv("IMAP_PORT", "993")), "user": user, "password": pw}


def _dec(v: str | None) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:  # noqa: BLE001
        return v or ""


def _norm_subject(s: str) -> str:
    s = _dec(s).strip()
    while True:
        t = re.sub(r"^\s*(re|fw|fwd|aw)\s*:\s*", "", s, flags=re.I)
        if t == s:
            return s.lower()
        s = t


def _body_text(m: email.message.Message) -> str:
    part = None
    if m.is_multipart():
        for p in m.walk():
            if p.get_content_type() == "text/plain" and "attachment" not in str(p.get("Content-Disposition") or ""):
                part = p
                break
    else:
        part = m
    if part is None:
        return ""
    raw = part.get_payload(decode=True) or b""
    text = raw.decode(part.get_content_charset() or "utf-8", "replace")
    # keep the new text, drop the quoted original
    lines = []
    for line in text.splitlines():
        if line.startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()[:4000]


def _fetch_mail(since_days: int = 14) -> list[email.message.Message]:
    cfg = imap_settings()
    if not cfg:
        return []
    out = []
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
    with imaplib.IMAP4_SSL(cfg["host"], cfg["port"]) as im:
        im.login(cfg["user"], cfg["password"])
        boxes = ['"[Gmail]/All Mail"', "INBOX"] if "gmail" in cfg["host"] else ["INBOX"]
        for box in boxes:
            typ, _ = im.select(box, readonly=True)
            if typ == "OK":
                break
        typ, data = im.search(None, "SINCE", since)
        ids = (data[0] or b"").split()[-300:] if typ == "OK" else []
        for i in ids:
            typ, msg = im.fetch(i, "(BODY.PEEK[])")
            if typ == "OK" and msg and isinstance(msg[0], tuple):
                out.append(email.message_from_bytes(msg[0][1]))
    return out


def match_replies(sent: list[dict], mail: list[email.message.Message]) -> list[tuple[dict, dict, str]]:
    """[(message_record, reply_or_bounce, kind)] where kind is reply or bounce. Pure, so it is unit-tested."""
    ours = {r["message_id"]: r for r in sent if r.get("message_id")}
    by_subject: dict[str, list[dict]] = {}
    for r in sent:
        by_subject.setdefault(_norm_subject(r.get("subject") or ""), []).append(r)
    found = []
    for m in mail:
        mid = (m.get("Message-ID") or "").strip()
        if mid in ours:
            continue  # our own sent copy
        refs = set(re.findall(r"<[^>]+>", f"{m.get('In-Reply-To') or ''} {m.get('References') or ''}"))
        frm = parseaddr(m.get("From") or "")[1].lower()
        target = next((ours[x] for x in refs if x in ours), None)
        text = _body_text(m)
        is_bounce = frm.startswith(("mailer-daemon", "postmaster")) or "delivery status notification" in _dec(m.get("Subject")).lower()
        if is_bounce:
            target = target or next((r for k, r in ours.items() if k in (text + str(m))), None)
            if target:
                found.append((target, {"message_id": mid, "from": frm, "text": text[:500]}, "bounce"))
            continue
        if target is None:
            cands = by_subject.get(_norm_subject(m.get("Subject") or ""), [])
            if _dec(m.get("Subject")).lower().startswith("re"):
                target = next((r for r in cands if frm in {(r.get("delivered_to") or "").lower(), (r.get("intended_to") or "").lower()}), None)
        if target is None:
            continue
        try:
            when = parsedate_to_datetime(m.get("Date")).astimezone(timezone.utc).isoformat(timespec="seconds")
        except Exception:  # noqa: BLE001
            when = messages.now()
        found.append((target, {"message_id": mid or f"<{hash(text)}@unknown>", "from": frm, "subject": _dec(m.get("Subject")),
                               "date": when, "text": text}, "reply"))
    return found


async def refresh() -> dict:
    """Update every open message. Returns counts and any problem, never raises."""
    sent = [r for r in messages.list_all() if r.get("status") not in messages.FINAL and r.get("message_id")]
    changed, errors = 0, []
    for r in sent:
        if r.get("provider") == "resend" and r.get("provider_id"):
            try:
                ev = await mailer.resend_status(r["provider_id"])
            except Exception as e:  # noqa: BLE001
                errors.append(f"resend status: {e}")
                ev = None
            if ev and messages.set_status(r["id"], ev, f"Resend: {ev}"):
                changed += 1
                ledger.append("message.status", {"agent_id": r.get("agent_id"), "message": r["id"], "status": ev,
                                                 "provider_id": r["provider_id"]})
    replies = 0
    if imap_settings() and sent:
        try:
            mail = await asyncio.to_thread(_fetch_mail)
        except Exception as e:  # noqa: BLE001 - imaplib errors, auth
            mail = []
            errors.append(f"IMAP: {e}")
        for rec, rep, kind in match_replies(sent, mail):
            if kind == "bounce":
                if messages.set_status(rec["id"], "bounced", f"bounce notice from {rep['from']}"):
                    changed += 1
                    ledger.append("message.status", {"agent_id": rec.get("agent_id"), "message": rec["id"], "status": "bounced"})
                continue
            new = messages.add_reply(rec["id"], rep)
            if not new:
                continue
            replies += 1
            ledger.append("message.reply", {"agent_id": rec.get("agent_id"), "message": rec["id"], "thread_key": rec.get("thread_key"),
                                            "from": rep["from"], "reply_message_id": rep["message_id"]})
            for fn in _handlers:
                try:
                    res = fn(new, rep)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:  # noqa: BLE001
                    log.warning("reply handler failed: %s", e)
    return {"checked": len(sent), "updated": changed, "new_replies": replies, "errors": errors,
            "replies_enabled": bool(imap_settings())}
