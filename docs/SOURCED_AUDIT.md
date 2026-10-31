# Sourced, audited as a paying hirer (2026-10-31, ~12:40 IST)

I ran the agent end to end (`/api/agents/sourced/run`, demo brief "senior backend engineer payments bangalore",
the committed replay fixtures) and read every screen, claim, draft and guard check as someone who would pay for it.

## What a hirer gets today (before this change)

1. **A good shortlist.** 70 profiles searched, 10 enriched, ranked 60 to 90, every reason linked to a claim. This part works.
2. **"9 of 9 claims verified", which overstates what was proven.** The checks are real, but most of them compare a
   person's own profile (headline, current title) with Crustdata's structured record of the *same* person and their
   company. That catches stale or inflated profiles (headline names an employer they left, a "Series B" company that is
   pre-seed, a tenure that doesn't add up). It does **not** prove the person is good, available or interested. The UI
   never said what was compared with what, so "verified" read like a background check. Source chips showed raw API
   paths (`person/enrich.experience.employment_details.current[0].start_date`).
3. **A draft that can't be sent.** No email address, a `[Your name]` sign-off, no subject, and no mention of which
   company is hiring. Every surface said "Draft · never sent". The hirer had to find the person's email themselves.
   The "verification" of the draft (Send Guard) ran and then nothing happened.
4. **No pipeline after the shortlist.** No record of who was contacted, nothing about delivery, replies or follow-ups.
   Re-running the brief starts from zero.
5. **No hands-off mode.** The event deck says the agent should fill roles with nobody at the keyboard. Sourced stopped
   at "here are drafts, copy them".
6. Smaller: Send Guard only checks the top 5 drafts (`GUARD_MAX`). The console's "send" button writes to an outbox
   file. The offline template draft produced lines like "What stood out: title: Senior Backend Engineer".

**Verdict:** a convincing research tool, not something a hirer would pay for. The paid outcome is conversations with
real candidates, and the product stopped one step short of the first one.

## What this change does

| Gap | Fix |
|---|---|
| No email | Each shortlisted candidate's email comes from **Crustdata Person Enrich with `fields: ["contact"]`**, checked live on 2026-10-31. It returns `contact.business_emails` / `personal_emails`, each with a status such as `deliverable`. Sourced picks a deliverable work email at the current employer, then any deliverable work email, then a deliverable personal email. **It never guesses.** If Crustdata has none, the UI says so. (`/person/contact/enrich` returns 403 on our plan.) |
| Can't send | **Send email** in the dossier. The exact text, edits included, is signed with the agent's key and run through Send Guard again, then sent through **Resend or any SMTP server (Gmail app password works)**. The sign-off is the real sponsor and the subject names the hiring company |
| No emails to real people | **Enforced, not a default.** Every email goes to your own inbox (`OUTBOUND_TEST_TO`), with a banner naming the candidate's real address. There is no live mode (user decision) |
| No status | Every send creates a message record (`backend/data/messages.json`) and a `message.sent` ledger entry citing the guard verdict and the Crustdata source of the address. The dossier shows **Sent → Delivered → Replied** (or Bounced / Blocked / Failed) and polls every 20s. Resend status comes from its API. Replies (and bounces) are read over IMAP and threaded by Message-ID, falling back to the subject plus sender |
| Hands-off | **"Email the shortlist for me"** (`?autosend=true` or `AUTO_SEND=1`): every draft Send Guard clears is emailed during the run, reusing the run's own verdict, so there's no second check |
| Verification unclear | "How Sourced checks a claim" explains, in plain words, what is compared with what, what each label means, and what it can't tell you. Source chips read "Crustdata person record · current job, start date" |

## Still open

- Replies need IMAP credentials (Gmail: the same app password). With Resend alone you get delivery status but no replies.
- The conversation engine (brief to signed offer) should send through `app.outbound.send.guarded_send` and receive
  replies through `tracking.register_reply_handler`. That's being wired up in its own thread.
- Contact lookups cost Crustdata credits (business email about 1, personal about 2 per person, secondhand figures).
  They run only for the drafts Send Guard checks (top 5 by default).
- The console's own "send" (`/api/agents/{id}/send`) still writes to the outbox file. Sourced's real path is
  `/api/agents/{id}/email`.
