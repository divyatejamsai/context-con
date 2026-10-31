# Agaxes agent runtime: the employer's control plane

Until now the fleet agents only ran inside the scripted demo story. The runtime (`backend/app/runtime/`) runs them
for real, all the time, inside the API server. The console's **Work** view (`/console?view=work`) is where the employer
manages them.

## What it does
| Control | How it really works |
|---|---|
| **Assign work** | `POST /api/runtime/tasks`. The task kind must fit the agent's passport scopes (a read-only analyst can't be given sales outreach). Kinds: `sourcing` (Sourced's hiring pipeline), `sales_outreach` (Pipeline), `vendor_diligence` (Diligence), `reference_check` (Reference). Each one runs the agent's own code on Crustdata and Gemini. |
| **Live status** | The supervisor loop starts queued work: one task per agent at a time, up to 4 agents at once. Every line the agent logs, every send, finding, artifact and filed work item lands on the task as it happens. The console polls `/api/runtime/state` every 1.5s. |
| **Approvals** | A draft goes through Send Guard first, and a block never reaches a person. A draft that clears waits in the approval inbox. **Approve** re-runs Send Guard at send time, so a recipient who has moved or an agent suspended in the meantime still gets blocked. Only then is the message written to the outbox. **Reject** records who rejected it and why. Both decisions go on the ledger. Approvals can be turned off per agent. |
| **Pause / resume** | Pause cancels the running task immediately (the asyncio task is cancelled mid-call) and puts it back at the head of the queue. Resume runs it again. |
| **Suspend / offboard** | Wherever it comes from (the console, the registry API, the payroll run), the supervisor sees the status change within a second and cancels the running task. Offboarding also cancels the agent's queued work and expires its pending approvals. |
| **Payroll run (auto-freeze)** | Every N minutes (default 30) every sponsor is re-checked live against Crustdata. An agent whose sponsor left or lost authority is suspended, and the step above stops its work. |
| **Budgets** | Per agent, per day: tasks, sends, Crustdata calls and Gemini calls. Calls are counted per task through a metered client. A task that goes over is stopped with "daily crustdata budget reached", and queued work waits until the next day. |
| **Schedules** | Recurring tasks (`every_minutes`). A schedule is skipped while its previous run is still going or while the agent isn't active. |
| **Report card** | Per agent: tasks done, success rate, average time, drafts, how many Send Guard blocked, how many were sent, approval rate, false claims caught, and Crustdata and Gemini calls. |
| **Receipts** | `GET /api/runtime/receipts/{hash}` returns a signed receipt for any ledger entry. It contains the entry, the entry before it and the head, plus the issuer's Ed25519 signature. `scripts/verify_receipt.py receipt.json` (or `POST /api/runtime/receipts/verify`) checks the entry hash, the chain link, the signature and whether the live ledger still holds that entry. |
| **Audit trail** | `task.assigned/started/done/failed/refused/cancelled/interrupted`, `agent.paused/resumed`, `runtime.policy`, `runtime.approval`, `runtime.schedule` and `runtime.payroll` all go on the hash-chained ledger, alongside the agents' own `guard.verdict` and `work.*` entries. |
| **Crash safety** | State is written to `backend/data/runtime.json` atomically (or to `RUNTIME_PATH`). On restart, tasks that were running go back in the queue, and half-sent approvals go back to pending. Approving re-checks the guard, so retrying is safe. |

## Scheduler (interview scheduling) and hiring from templates
- **Hire Scheduler** in the Work tab onboards a new AI employee from a template. It gets a passport sponsored by Sourced's sponsor, and the sponsor is checked live right away (`GET /api/runtime/templates`, `POST /api/runtime/hire`).
- `interview_scheduling` checks each candidate on Crustdata and proposes two slots per candidate from the list you give, spreading candidates across the slots. It drafts the invite (Gemini when live) and sends it through Send Guard and the approval inbox. It returns tentative calendar holds as an .ics artifact and files the plan on the ledger. A candidate who has left the company on file gets blocked by the guard.
- When a sourcing task finishes, its drawer shows **Schedule interviews**, which pre-fills the Scheduler task with the shortlist.

## Hiring flow (agents handing work to each other)
**Start hiring flow** in the Work tab (`POST /api/runtime/flows {brief, compensation}`) runs one brief through four AI
employees (`app/runtime/flow.py`):
1. **Shortlist** (`data.read`): Sourced searches, verifies and ranks candidates.
2. **Verify records** (`data.read`): a different agent re-checks the top five. Separation of duties means Sourced is refused. Each candidate gets a verdict (clear, flag or unverified) plus a report.
3. **Schedule interviews** (`outreach.hiring`): the Scheduler proposes real slots (an .ics file with DTSTART/DTEND in IST) and drafts invites, which wait for your approval.
4. **Offer letter** (`contract.sign`): the Scheduler is asked first and **refused**, because its passport has no contract.sign. The Offer agent drafts the letter. It's signed only after you approve it, and at that moment the passport is re-checked for contract.sign.

At each handoff, Agaxes runs a live `verify_agent` for the stage's scope on each candidate agent until one is allowed.
Every allow and deny is shown on the flow and written to the ledger (`flow.handoff`). Missing agents (Scheduler, Offer)
are hired from templates on first use. The flow ends with a hiring-committee packet (Markdown).

## Verify links (the receiving end)
Every message Agaxes lets out (the outbox) and every signed offer ends with
`Sent by <agent>, AI agent for <company>, vouched for by <sponsor>. Verify: <AGAXES_PUBLIC_URL>/verify/<seal>`.
The page needs no login (`/verify/<seal>`). So does the API (`GET /api/verify/<seal>`, `POST /api/verify {text}` for receiving agents). They check:
- that Agaxes issued the passport
- the agent's signature over the content
- that the content wasn't altered (paste what you received)
- that the agent is in good standing now
- that the action is in scope
- the sponsor's live checks

A suspended agent's links turn red. When email is configured (`OUTBOUND_TEST_TO` is your own inbox, see docs/OUTBOUND.md), approving a message or signing an offer also emails a copy to that inbox. `scripts/send_signed_email.py` sends one signed test note.

## Reliability
- A transient failure (network, model) is retried once (`RUNTIME_MAX_ATTEMPTS`, default 2). Bad input fails immediately.
- An outside agent that goes silent for `AGAXES_AGENT_LEASE_S` (600s) loses its claim, and the task goes back in the queue.
- **Data provider out of credits (Crustdata 402).** The client raises `OutOfCredits` at once and doesn't retry. Any task that
  hit it fails with "Data provider out of credits", and it isn't retried. The Work tab shows a banner (`runtime.provider` in
  `/api/runtime/state`, and `/api/health` reports it too), and any route that lets the error escape answers 402 with the
  same message. The payroll run doesn't suspend or revoke an agent whose check only couldn't run because of it. A
  definite failure, such as the sponsor leaving, still suspends. Sends still fail closed at the guard. The banner clears
  on the next successful live call.
- If a launched Claude Code exits with an error before finishing (for example, an expired login), the task fails with the reason instead of sitting in the queue.

## Outside agents (Claude Code), governed the same way
Agents that run on their own machine get tasks too (kind `assignment`: written instructions). They hold their own key,
and every call is signed `agaxes|action|agent_id|task_id|ts|text`. Replays are refused after 5 minutes.
- `POST /api/runtime/agent/claim`, `/progress`, `/complete`, `/send` (`scripts/agaxes_agent.py` is a ready client: `next`, `progress`, `send`, `done`).
- A send goes through Send Guard, then the approval inbox, exactly like an in-house agent's. A false claim is blocked and never reaches you.
- Pause, suspend, offboard and cancel are enforced on the agent's next call, which is answered **STOP** (the CLI prints `STOP` and exits 3). A paused task goes back in the queue, and the agent can't claim new work until it is resumed.
- With `AGAXES_LAUNCH_CLAUDE=1` and the `claude` CLI installed, Agaxes starts Claude Code itself on the machine for each queued task. It runs with the client as its only allowed tool. Pause or suspend also ends that process.

Verified with the real Claude Code CLI: it claimed a task and drafted a note, which Send Guard cleared and parked in the approval inbox, then it reported done. On a second task it reported two steps, the employer paused it, its process was ended, and the task went back in the queue.

## Run
```bash
cd backend && uvicorn app.main:app --port 8000      # the runtime starts with the API (RUNTIME_ENABLED=0 turns it off)
python scripts/run_fleet.py --only onboard          # or onboard from the console; then open /console?view=work
```
Env vars: `RUNTIME_MAX_CONCURRENT` (4), `RUNTIME_TASK_TIMEOUT` (900s), `RUNTIME_PATH`. Writes honour `COUNTERSIGN_ADMIN_TOKEN`.

## Honest limits
- In-house agents run inside the API process. They call the same `call_tool` the MCP server serves, in process, instead of over stdio. Outside agents use the signed HTTP calls above, and the plain MCP tools (`check_before_send` etc.) still work for agents that aren't given tasks.
- "Sent" means written to the outbox. Nothing is emailed (event rule).
- Pause and suspend cancel at the next `await`, which is the next Crustdata, Gemini or guard call, so within a second or so.
- Gemini calls are counted by wrapping `llm._call`, so mock mode counts 0.
