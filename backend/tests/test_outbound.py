"""Real outbound (app/outbound): email from Crustdata's contact field, Send Guard before every send, a real provider
call (Resend's HTTP API, mocked at the transport), test-mode redirect, message store, delivery status and replies."""
import json
from email.message import EmailMessage
from pathlib import Path

import httpx
import pytest

from app.agents import ledger, registry
from app.agents.models import Sponsor
from app.fallbacks import DevCrustdataClient
from app.outbound import mailer, messages, tracking
from app.outbound.contacts import find_emails, pick
from app.outbound.send import guarded_send
from app.sourced_agent import run_as_agent

pytestmark = pytest.mark.asyncio
SCENARIOS = {s["id"]: s for s in json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    for k in ("RESEND_API_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "IMAP_HOST", "MAIL_FROM", "MAIL_REPLY_TO",
              "OUTBOUND_PROVIDER", "OUTBOUND_MODE", "OUTBOUND_TEST_TO", "OUTBOUND_LIVE_CONFIRM", "AUTO_SEND"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AGENTS_PATH", str(tmp_path / "agents.json"))
    monkeypatch.setenv("LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("MESSAGES_PATH", str(tmp_path / "messages.json"))
    monkeypatch.setenv("ISSUER_KEY_PATH", str(tmp_path / "issuer.key"))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")


@pytest.fixture
def resend(monkeypatch):
    """Resend configured in test mode; every HTTP call it makes is captured."""
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("OUTBOUND_TEST_TO", "team@example.com")
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.method == "POST":
            return httpx.Response(200, json={"id": f"em_{len(calls)}"})
        return httpx.Response(200, json={"id": req.url.path.rsplit("/", 1)[-1], "last_event": "delivered"})

    real = httpx.AsyncClient
    monkeypatch.setattr(mailer.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return calls


def contact_record(url, personal=(), business=(), domain="acme.io"):
    return {"contact": {"personal_emails": [{"email": e, "status": s, "last_updated": "2026-09-03T11:20:31Z"} for e, s in personal],
                        "business_emails": [{"email": e, "status": s} for e, s in business], "phone_numbers": []},
            "experience": {"employment_details": {"current": [{"company_website_domain": domain}]}},
            "_source": {"endpoint": "person/enrich", "origin": "live"}}


class ContactClient(DevCrustdataClient):
    """Dev client plus the contact field, the way live Person Enrich returns it."""
    mode = "replay"

    async def person_enrich_many(self, urls, fields=None):
        assert fields == ["contact"]
        return {u: contact_record(u, personal=[(f"{u.rstrip('/').rsplit('/', 1)[-1]}@gmail.com", "deliverable")]) for u in urls}


def onboard() -> str:
    return registry.onboard("Sourced", "recruiter", Sponsor(**SCENARIOS["authorised_founder"]["sponsor"]),
                            ["outreach.hiring", "data.read"])["agent_id"]


# ---- finding the email -----------------------------------------------------------------------

def test_pick_prefers_deliverable_work_email_at_current_employer():
    rec = contact_record("u", personal=[("me@gmail.com", "deliverable")],
                         business=[("old@other.com", "deliverable"), ("me@acme.io", "deliverable"), ("x@acme.io", "risky")])
    c = pick("u", rec)
    assert c.email == "me@acme.io" and c.kind == "business" and c.source.field == "contact"
    assert [o.email for o in c.options][:2] == ["me@acme.io", "old@other.com"]


def test_pick_falls_back_to_personal_and_says_so():
    c = pick("u", contact_record("u", personal=[("me@gmail.com", "deliverable")]))
    assert c.email == "me@gmail.com" and "Personal email" in c.note and "no work email" in c.note


def test_no_email_is_reported_not_guessed():
    c = pick("u", contact_record("u"))
    assert c.email is None and "no email" in c.note.lower()
    assert pick("u", None).email is None


async def test_find_emails_batches_and_never_raises():
    got = await find_emails(ContactClient(), ["https://linkedin.com/in/a", "https://linkedin.com/in/b"])
    assert got["https://linkedin.com/in/a"].email == "a@gmail.com"

    class Broken:
        async def person_enrich_many(self, *_):
            raise RuntimeError("429")
    bad = await find_emails(Broken(), ["u"])
    assert bad["u"].email is None and bad["u"].error


# ---- send policy -----------------------------------------------------------------------------

def test_config_is_not_ready_without_provider_or_test_inbox(monkeypatch):
    assert mailer.config()["ready"] is False and "provider" in mailer.config()["reason"]
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    assert mailer.config()["ready"] is False and "OUTBOUND_TEST_TO" in mailer.config()["reason"]
    monkeypatch.setenv("OUTBOUND_MODE", "live")
    assert mailer.config()["ready"] is False and "CONFIRM" in mailer.config()["reason"]
    monkeypatch.setenv("OUTBOUND_LIVE_CONFIRM", "yes")
    assert mailer.config()["ready"] is True


async def test_test_mode_redirects_to_own_inbox_with_banner(resend):
    d = await mailer.send(mailer.Envelope(intended_to="cand@gmail.com", to_name="Cand", subject="Hi", body="Hello"))
    sent = json.loads(resend[0].content)
    assert sent["to"] == ["team@example.com"] and d.delivered_to == "team@example.com"
    assert "cand@gmail.com" in sent["text"] and sent["text"].endswith("Hello")
    assert sent["from"] == "onboarding@resend.dev" and d.provider_id == "em_1" and d.message_id.startswith("<")


async def test_live_mode_sends_to_the_real_address(resend, monkeypatch):
    monkeypatch.setenv("OUTBOUND_MODE", "live")
    monkeypatch.setenv("OUTBOUND_LIVE_CONFIRM", "yes")
    await mailer.send(mailer.Envelope(intended_to="cand@gmail.com", to_name="Cand", subject="Hi", body="Hello"))
    sent = json.loads(resend[0].content)
    assert sent["to"] == ["cand@gmail.com"] and sent["text"] == "Hello"


# ---- guarded send, end to end ----------------------------------------------------------------

async def _cleared_candidate(aid):
    """Run Sourced (offline dev data) and return a shortlisted candidate whose draft Send Guard cleared."""
    events = [e async for e in run_as_agent("senior backend engineer, payments, Bangalore", aid, client=ContactClient())]
    cands = {e["candidate"]["id"]: e["candidate"] for e in events if e["type"] == "candidate"}
    ok = [c for c in cands.values() if (c.get("guard") or {}).get("decision") == "allow"]
    assert ok, "expected at least one cleared draft"
    return ok[0], events


async def test_run_finds_emails_and_signs_with_the_real_sponsor(resend):
    aid = onboard()
    c, events = await _cleared_candidate(aid)
    assert c["contact"]["email"].endswith("@gmail.com") and c["contact"]["status"] == "deliverable"
    assert "[Your name]" not in c["outreach_draft"] and SCENARIOS["authorised_founder"]["sponsor"]["name"] in c["outreach_draft"]
    assert SCENARIOS["authorised_founder"]["sponsor"]["company"] in c["outreach_subject"]
    assert not resend, "nothing is sent without autosend or a Send click"


async def test_guarded_send_sends_records_and_ledgers(resend):
    aid = onboard()
    c, _ = await _cleared_candidate(aid)
    to = {"name": c["name"], "profile_url": c["profile_url"], "company": c["company"]}
    res = await guarded_send("sourced", to, c["outreach_subject"], c["outreach_draft"], client=ContactClient())
    assert res.ok and res.status == "sent", res.detail
    m = messages.list_all()[0]
    assert m["status"] == "sent" and m["intended_to"] == c["contact"]["email"] and m["delivered_to"] == "team@example.com"
    assert m["guard"]["decision"] == "allow" and m["provider_id"]
    kinds = [e["kind"] for e in ledger.entries()]
    assert "message.sent" in kinds and ledger.verify_chain() == (True, None)


async def test_edited_body_with_a_false_claim_is_blocked_and_not_sent(resend):
    aid = onboard()
    c, _ = await _cleared_candidate(aid)
    to = {"name": c["name"], "profile_url": c["profile_url"], "company": c["company"]}
    lie = c["outreach_draft"].replace("Hi ", f"Hi! Loved your 9 years at Google. ", 1)
    res = await guarded_send(aid, to, "Hello", lie, client=ContactClient())
    assert not res.ok and res.status == "blocked"
    assert not [r for r in resend if r.method == "POST"]
    assert messages.list_all()[0]["status"] == "blocked"


async def test_not_configured_sends_nothing():
    aid = onboard()
    res = await guarded_send(aid, {"name": "A", "profile_url": "u"}, "s", "b", client=ContactClient())
    assert res.status == "not_configured" and not messages.list_all()


async def test_autosend_emails_every_cleared_draft_with_no_one_at_the_keyboard(resend):
    aid = onboard()
    events = [e async for e in run_as_agent("senior backend engineer, payments, Bangalore", aid, client=ContactClient(), autosend=True)]
    sends = [e for e in events if e.get("step") == "send"]
    cleared = [e for e in events if e.get("step") == "guard" and (e.get("data") or {}).get("decision") == "allow"]
    assert sends and len(sends) == len(cleared) and all(e["data"]["status"] == "sent" for e in sends)
    posts = [r for r in resend if r.method == "POST"]
    assert len(posts) == len(sends), "the run's own verdict is reused: one send per cleared draft, no second guard"


# ---- delivery status and replies -------------------------------------------------------------

async def test_refresh_reads_delivery_status_from_resend(resend):
    aid = onboard()
    c, _ = await _cleared_candidate(aid)
    await guarded_send(aid, {"name": c["name"], "profile_url": c["profile_url"], "company": c["company"]},
                       c["outreach_subject"], c["outreach_draft"], client=ContactClient())
    out = await tracking.refresh()
    assert out["updated"] == 1 and messages.list_all()[0]["status"] == "delivered"
    assert "message.status" in [e["kind"] for e in ledger.entries()]


def _mail(frm, subject, body, **h):
    m = EmailMessage()
    m["From"], m["Subject"], m["Date"] = frm, subject, "Sat, 31 Oct 2026 08:00:00 +0000"
    for k, v in h.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    return m


def test_match_replies_by_header_subject_and_bounce():
    sent = [{"id": "m1", "message_id": "<a@x>", "subject": "Vijay, Backend at Acme", "delivered_to": "team@example.com",
             "intended_to": "v@gmail.com"},
            {"id": "m2", "message_id": "<b@x>", "subject": "Ana, Backend at Acme", "delivered_to": "team@example.com",
             "intended_to": "a@gmail.com"}]
    mail = [
        _mail("me@x", "Vijay, Backend at Acme", "our own copy", Message_ID="<a@x>"),
        _mail("Vijay <v@gmail.com>", "Re: Vijay, Backend at Acme", "Sure, Tuesday works.\n\nOn Sat someone wrote:\n> hi",
              Message_ID="<r1@g>", In_Reply_To="<a@x>"),
        _mail("team@example.com", "RE: Ana, Backend at Acme", "Not looking, thanks", Message_ID="<r2@g>"),
        _mail("stranger@x.com", "Re: Ana, Backend at Acme", "spam", Message_ID="<r3@g>"),
        _mail("MAILER-DAEMON@x.com", "Undelivered Mail", "could not deliver <b@x>", Message_ID="<d1@x>"),
    ]
    got = {(r["id"], kind, rep.get("text")) for r, rep, kind in tracking.match_replies(sent, mail)}
    assert ("m1", "reply", "Sure, Tuesday works.") in got
    assert ("m2", "reply", "Not looking, thanks") in got
    assert any(k == "bounce" and i == "m2" for i, k, _ in got)
    assert not any(t == "spam" for _, _, t in got)


def test_status_only_moves_forward_and_replies_dedupe():
    r = messages.create({"status": "sent", "message_id": "<a@x>"})
    assert messages.set_status(r["id"], "delivered")
    assert messages.set_status(r["id"], "sent") is None
    assert messages.add_reply(r["id"], {"message_id": "<r@x>", "from": "v@x", "text": "yes"})
    assert messages.add_reply(r["id"], {"message_id": "<r@x>", "from": "v@x", "text": "yes"}) is None
    assert messages.get(r["id"])["status"] == "replied"
