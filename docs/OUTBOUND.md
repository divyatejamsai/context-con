# Outbound: find the email, send it through Send Guard, track delivery and replies

Code: `backend/app/outbound/`. Tests: `backend/tests/test_outbound.py`.

```
shortlisted candidate
  -> contacts.find_emails     Crustdata Person Enrich, fields ["contact"] (deliverable work email > personal; never guessed)
  -> send.guarded_send        agent active? -> sign body -> Send Guard (passport, signature, recipient, every claim)
  -> mailer.send              Resend API or SMTP; every email goes to OUTBOUND_TEST_TO, never to a candidate
  -> messages + ledger        message record (status history, replies) + message.sent entry
  -> tracking.refresh         Resend last_event; IMAP replies and bounces, threaded by Message-ID
```

## Set it up (backend/.env, never committed)

Pick one provider.

**Gmail (sending and replies, no domain needed).** Turn on 2-step verification, create an app password at
https://myaccount.google.com/apppasswords, then:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<16-char app password>
OUTBOUND_TEST_TO=you@gmail.com     # test mode: every email lands here
```
IMAP defaults to imap.gmail.com with the same login, so replies show up in the UI.

**Resend (delivery status from the provider).** Create an API key at https://resend.com/api-keys:
```
RESEND_API_KEY=re_...
OUTBOUND_TEST_TO=<the email you signed up to Resend with>   # without a verified domain Resend only sends to you
# MAIL_FROM=hiring@your-verified-domain.com                 # once a domain is verified
# For replies, also set IMAP_HOST / IMAP_USER / IMAP_PASSWORD and MAIL_REPLY_TO to that mailbox.
```

**No emails to real people (enforced).** Every outreach email goes to `OUTBOUND_TEST_TO`, with a banner naming the
candidate and the address Crustdata has for them. There is no live mode and no setting that turns one on
(user decision, 2026-10-31).

Check it: `curl localhost:8000/api/outbound/config` shows `ready: true`.

## API

| Route | What it does |
|---|---|
| `GET /api/outbound/config` | provider, mode, test inbox, whether replies are on, why not ready |
| `GET /api/contacts?profile_url=` | the email Crustdata has for a profile, with its status and source |
| `POST /api/agents/{id}/email` | `{to:{name,profile_url,company}, subject, body, email?, scope?, thread_key?}`: Send Guard, then send |
| `GET /api/agents/{id}/run?brief=&autosend=true` | the full run, emailing every cleared draft |
| `GET /api/messages?profile_url=&thread_key=` | sent, blocked and failed emails with status history and replies |
| `POST /api/messages/refresh` | poll delivery status and replies now (the UI does this every 20s while anything is open) |

## For other agents (the conversation engine)

```python
from app.outbound.send import guarded_send
res = await guarded_send("sourced", to, subject, body, scope="outreach.hiring", thread_key=f"{campaign}:{conv}")
# res.ok, res.status (sent | blocked | no_email | not_configured | failed | inactive), res.detail, res.message

from app.outbound.tracking import register_reply_handler
register_reply_handler(lambda msg, reply: engine.receive(msg["thread_key"], reply["text"]))
```
Follow-ups with the same `thread_key` are sent as replies in the same email thread (In-Reply-To / References).
Account email (password resets) uses `mailer.send_transactional(to, subject, body)`, which skips Send Guard and the test redirect.
