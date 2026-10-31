# Emergency stop

One click freezes **one agent**, **every agent a person vouched for**, or **every agent**, and shows what each of them
touched in the last 24 hours. Console: **Workforce → Emergency stop** (`/console?view=estop`), or the **Emergency stop**
button on any active agent's page. Code: `backend/app/runtime/freeze.py`, routes in `backend/app/runtime/freeze_api.py`,
UI in `frontend/src/app/console/estop.tsx`. Tests: `backend/tests/test_freeze.py`.

## What a stop does

It reuses the controls Agaxes already has, so everything that refuses a suspended agent refuses a frozen one:

1. Each active agent is suspended through the registry: its passport is revoked on the ledger, so Send Guard, MCP calls
   and every public `/verify/<seal>` link turn red at once.
2. Its running task is stopped mid-flight (outside agents are refused on their next call) and its queued tasks are cancelled.
3. Drafts waiting for approval are pulled (status `expired`, nothing can send them) and its schedules are switched off.

Agents that were already suspended stay suspended and are listed; offboarded agents are left out. New work assigned to a
frozen agent just waits in the queue.

## What it touched (blast radius)

For each agent, from the ledger and the runtime store, over the last 24 hours: messages sent (emails, approved drafts,
signed offers, sends without approval), people contacted (recipients and repliers), data read (Crustdata and LLM calls,
tasks and filed work), approvals asked of a person and how they ended, Send Guard blocks, rule blocks (`rule.enforced`)
and spend (calls, sends, offers signed with CTC). The preview shows it before you confirm, and the stop keeps a copy as
it was at the moment of the stop.

## Lifting a stop

**Lift stop** runs a fresh sponsor check for every agent the stop suspended; only the ones that pass come back (an agent
whose sponsor left stays suspended). Agents that were suspended before the stop, or that another stop still holds, are
left alone. Schedules come back on for the agents that return. With **bring back the stopped work** the stopped tasks
are re-queued and the pulled drafts go back in front of a person (Send Guard checks them again at send time).

## API

    GET  /api/runtime/freeze                       {active, history, sponsors}
    GET  /api/runtime/freeze/blast?agent_id=&hours=24
    POST /api/runtime/freeze/preview               {scope: agent|sponsor|all, target?}
    POST /api/runtime/freeze                       {scope, target?, reason}            admin
    POST /api/runtime/freeze/{id}/restore          {bring_back?}                       admin

A company admin only ever stops their own company's agents ("all" means every agent they can see).

## Ledger

`freeze.started` `{freeze_id, scope, target, label, reason, by, agent_ids, agent_names, suspended, stopped_tasks,
cancelled_approvals, schedules_off, blast_totals}` and `freeze.restored` `{freeze_id, by, agent_ids, restored,
still_suspended, kept_suspended, bring_back, requeued_tasks, returned_approvals}`. Each frozen agent also gets the usual
`passport.revoked` entry, with a reason starting `suspended by emergency stop frz_…`.
