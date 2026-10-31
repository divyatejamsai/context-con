# Alerts: when an agent needs a person

Agaxes tells the person responsible when an AI employee needs them, so nobody has to keep the console open.

| Alert | Raised when | Approve / Reject in the alert |
|---|---|---|
| **Approval** | an agent holds a message or an offer letter for approval; a two-approver item got its first approval and needs a second, different person | yes |
| **Block** | Send Guard blocks a draft, a task or an offer is refused, or a rule blocks something | no (link to the agent) |
| **Stop** | an agent is suspended (payroll check, sponsor, admin), or an emergency stop freezes agents (one alert per stop) | no |

**Who.** The agent's assigned recruiters who can act (member or above), then its company's admins and owners. The
first of them whose preferences allow a channel gets that channel's alert, with links bound to them. Everyone who can
see the agent sees it on the console bell.

**Channels.**
- **Email**, to `OUTBOUND_TEST_TO` only (the user's own inbox, never anyone else's address: no emails to real people).
  The email names whose alert it is. Needs the same SMTP / Resend settings as outreach (docs/OUTBOUND.md).
- **Slack**, when `SLACK_WEBHOOK_URL` (an incoming webhook) is set, with Approve, Reject and Open buttons.
- **The bell** in the console header and sidebar: unread count, inline Approve / Reject, per-person read state, and
  alert settings (email and Slack on or off, and which kinds of alert) plus "Send me a test alert".

**One-click links** (`backend/app/alerts/links.py`). Each Approve / Reject link is HMAC-signed, bound to one person,
expires after `ALERT_LINK_HOURS` (24), and works once (one alert's Approve and Reject share one use). Opening it shows
the draft, the Send Guard result and any rules, and acts only when the button is pressed, because mail scanners open
links. At that moment Agaxes re-checks the person: still in the company, still member or above, still able to see the
agent. The decision runs the same approval path as the console (Send Guard runs again, rules apply) and the
`runtime.approval` ledger entry carries `actor: {via: "alert_link", user_id, email, role, workspace_id, link}`.

**Never in the way.** Alerts listen to new approvals (`runtime/store.py`) and ledger entries (`agents/ledger.py`) in the
API process, deliver in the background, and record delivery failures on the alert instead of raising. At most
`ALERT_EMAILS_PER_HOUR` (30) alert emails an hour; the same block for the same agent and person alerts once per 10 minutes.

API: `GET /api/alerts`, `POST /api/alerts/read`, `GET|PUT /api/alerts/prefs`, `POST /api/alerts/test`, and the public
`GET|POST /api/alerts/action/{token}` behind the `/act/{token}` page.
