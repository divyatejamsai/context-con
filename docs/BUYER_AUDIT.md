# Agaxes, audited the way a buyer would audit it

Reviewer's hat: head of IT or security at a 200-person company that wants to let AI agents (Sourced, Claude Code,
a vendor's bot) act for the company. Compared against what that buyer already sees in the market: Okta / Auth0 for
AI agents (agent identity, token vault, async human approval, fine-grained authorization), Astrix and other
non-human-identity tools (discover every agent and secret, rotate, posture), Aembit (workload IAM, secretless
access, conditional policies), Zenity (agent security posture and runtime detection), Credal (permission-aware data
access with audit logs), and MCP gateways (one choke point for tool calls: allowlists, auth, rate limits, logging).
The comparison is from product knowledge, not a fresh read of reviews today.

Checked on `main` at f5a7520 (442 backend tests passing), then fixed on `claude/project-thread-dncbb6` (454 passing).

## Where Agaxes is already ahead

- **Authority is checked against the real world, live.** No competitor checks that the human sponsor still works
  at the company and has the title to grant a scope (Crustdata person/enrich, company/identify). Okta and Aembit
  trust whatever the directory says; Agaxes catches "sponsor left three weeks ago" with a citation.
- **Pre-send content checks.** Send Guard blocks a message whose factual claims about the recipient are false.
  Gateways log tool calls; none check what the message says.
- **Tamper-evident ledger and receipts.** Hash-chained, issuer-signed receipts a third party can verify offline.
  Most products have audit logs; few make them provable.
- **Signed calls, no shared secret** for outside agents (per-call Ed25519 signatures with a 5-minute window), the
  same idea as Aembit's "secretless".

## Gaps, ranked by what would stop a purchase

| # | Gap (before this branch) | Why a buyer cares | Status |
|---|---|---|---|
| 1 | **The control plane had no login.** Anyone who could reach the API could make Sourced send a real email (`POST /api/agents/{id}/email`), start credit-spending runs, look up contacts, approve sends, pause or suspend agents. Even with the admin token set, the email, agent run, contact lookup, resume check and message refresh routes stayed open | Fails any security review on day one | **Fixed.** Every Agaxes route goes through `app/accounts/authz.py` |
| 2 | **No roles; the company login wasn't connected to Agaxes** | Least privilege: the recruiter who approves sends shouldn't be the one who widens scopes | **Fixed.** viewer < member < admin < owner, from the company session (Bearer). viewer reads and exports, member runs work and approves sends, admin governs (onboard, scopes, suspend, enrollments, payroll), owner changes roles. `GET /api/workspace`, `GET/PUT/DELETE /api/workspace/members`. A workspace always keeps one owner; removing someone signs them out everywhere |
| 3 | **"Approved by" was whatever the client typed** (`by` fields) | An audit trail anyone can write a name into is not an audit trail | **Fixed.** Every ledger entry written during a signed-in request carries `actor` (user id, email, role, workspace) from the session, inside the entry's hash. `by` labels are replaced by the session's email |
| 4 | **No tenant isolation.** One flat registry, ledger and work queue for everyone | Two customers on one deployment could see and control each other's agents | **Fixed** for agents, ledger, the Work view (agents, tasks, approvals), messages, payroll runs and audit export. Another workspace's agent answers 404, not 403, so ids don't leak. Agents onboarded before accounts existed show to the demo workspace and to `AGAXES_DEFAULT_WORKSPACE` |
| 5 | **An outside agent couldn't be onboarded from its own machine.** `agaxes_agent.py` read the private key from the server's registry file, so "Claude Code on a laptop" only worked on the server. Agaxes held every agent's private key | The whole point of agent identity is that only the agent can act as itself | **Fixed.** Admin creates a one-time enrollment (`POST /api/agents/enrollments`, token shown once, only its hash stored, expires). The agent runs `agaxes_agent.py enroll <token>`: it makes its key pair locally, proves possession, and gets a passport bound to its key. Agaxes stores only the public key (`key_custody: "agent"`). `agaxes_agent.py rotate` re-issues the passport for a new key, signed with both keys, and the old key stops working at once |
| 6 | **No audit export** | Auditors and SIEMs need the log out of the product | **Fixed.** `GET /api/ledger/export?format=jsonl|csv&agent_id=&kind=&since=&until=`. JSONL = signed manifest + entries, checked offline by `scripts/verify_export.py` (catches edits, dropped or added lines, a different signer). CSV for spreadsheets, with the signature in headers. Each export is itself a ledger entry |
| 7 | Replay of a captured key-change call | Low, but a rotation must be one-shot | **Fixed.** `rotate_key` signatures are single use |
| 8 | **Secure by default.** Auth is still open when neither `COUNTERSIGN_ADMIN_TOKEN` nor `AGAXES_REQUIRE_LOGIN=1` is set, so the demo keeps working | Production must start locked | Open on purpose for the demo. `/api/health` and `/api/workspace` now report `auth_mode` (`open`, `writes_protected`, `login_required`). Turn on `AGAXES_REQUIRE_LOGIN=1` once the console calls through `/api/backend` |
| 9 | **Policies aren't editable in the UI.** Per-agent approvals and budgets are (`PUT /api/runtime/agents/{id}/policy`), but role ceilings and the sponsor-authority title rules are code | Every company's org chart is different | Next: a policy store for role ceilings and title rules, editable by admins, each change on the ledger |
| 10 | Anyone with a company email auto-joins the workspace as **member**, who can approve sends | Should be viewer, or need an owner's OK | Next: join requests, or join as viewer. The owner can already demote |
| 11 | No SSO (Okta, Entra, Google) or SCIM | Standard enterprise checkbox | Roadmap |
| 12 | Approvals only reach someone who opens the console | Okta's async authorization pings the approver's phone | Runtime thread: Slack or email notification to the approver, approve from the link |
| 13 | Agaxes only knows agents that onboard | Astrix's core pitch is finding the agents and keys nobody registered | Roadmap: scan GitHub, Slack and Google Workspace for OAuth apps and API keys |
| 14 | Send Guard covers outbound messages, not every tool call | MCP gateways put policy on every call | Roadmap: a guard mode for any MCP tool (allowlist, rate limit, ledger) |
| 15 | In-house agents' private keys sit in `backend/data/agents.json`; persistence is JSON files | Key custody and durability | Roadmap: KMS or OS keychain, Postgres. Outside agents now hold their own keys |

## The access hierarchy (added after the audit, at the user's request)

| Level | Who | Sees |
|---|---|---|
| Platform | **operator** (emails in `AGAXES_OPERATOR_EMAILS`, the demo operator, or the admin token) | Every company, its people and AI employees: `GET /api/platform/companies`; moves an agent into a company with `PUT /api/platform/agents/{id}/workspace`. The seeded fleet (onboarded before accounts) lives here |
| Company | **owner**, **admin** | Only their own company: every AI employee, the ledger and export, members, enrollments, payroll |
| Own work | **member** (a recruiter), **viewer** (read-only) | Only the AI employees assigned to them (`PUT /api/agents/{id}/assignees`), their tasks and approvals, Sourced. No company ledger, member list or registry, no platform view |

`GET /api/auth/me` returns `access: {level, role, views, summary}` so the console hides what the backend refuses.
Demo sign-ins: `POST /api/auth/demo {"as": "operator" | "admin" | "recruiter"}` (no body = the demo company's
owner, as before). At demo sign-in the demo company gets Sourced, assigned to the demo recruiter.

## Try it

```bash
cd backend
AGAXES_REQUIRE_LOGIN=1 uvicorn app.main:app --port 8000
# sign up (work email), then as the owner:
curl -s localhost:8000/api/agents/enrollments -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"Claude Code","role":"analyst","sponsor":{...}}' | jq -r .command
# on the agent's machine:
AGAXES_API_URL=http://<host>:8000 python backend/scripts/agaxes_agent.py enroll agx_enr_...
python backend/scripts/agaxes_agent.py next <agent_id>        # signed with the key in ~/.agaxes/<agent_id>.json
python backend/scripts/agaxes_agent.py rotate <agent_id>
# audit:
curl -s localhost:8000/api/ledger/export -H "Authorization: Bearer $TOKEN" -o ledger.jsonl
python scripts/verify_export.py ledger.jsonl --issuer-key "$(curl -s localhost:8000/api/passport/issuer | jq -r .public_key)"
```

The console calls the backend from the browser, and the session token lives in an httpOnly cookie, so a signed-in
console goes through the new same-origin proxy `frontend/src/app/api/backend/[...path]` (adds the Bearer header,
streams SSE). The UI thread is switching the console to it.

Tests: `backend/tests/test_access.py` (roles, isolation, actor, enrollment, rotation, export, members). The flow above
was also run over real HTTP against a local server: enroll, claim with the agent's own key, rotate, claim with the
new key, export, verify (all checks pass).
