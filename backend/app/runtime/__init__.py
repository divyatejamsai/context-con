"""Countersign's agent runtime: the control plane that actually runs AI employees on real tasks.

    store.py       tasks, approvals, schedules, per-agent policies and daily usage (backend/data/runtime.json)
    kinds.py       the jobs agents can be given (sourcing, sales outreach, vendor diligence, reference checks)
    worker.py      what one task runs inside: the agent's Ctx with approvals, budgets and live progress
    supervisor.py  the long-running loop: starts queued work, stops agents that are paused or suspended,
                   fires schedules and the recurring payroll run
    api.py         /api/runtime/* for the console's Work view

See docs/RUNTIME.md.
"""
