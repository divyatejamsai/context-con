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
