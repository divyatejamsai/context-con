"""The supervisor: a loop inside the API server that runs AI employees and keeps them inside their limits.

Every tick (1s, or sooner when something changes) it:
  1. stops running work the employer has taken away: an agent that is suspended, offboarded or revoked (from the
     console, the payroll run, or anywhere else that changes the registry) has its task cancelled mid-flight;
     a paused agent has its task interrupted and put back at the head of its queue;
  2. fires schedules that are due (recurring tasks);
  3. starts the recurring payroll run (every sponsor re-checked live against Crustdata) when it is due;
  4. starts queued tasks: one at a time per agent, a few agents at once, only for active, unpaused agents with
     task budget left today.

Every lifecycle change goes on the hash-chained ledger: task.assigned / started / finished, agent.paused / resumed,
runtime.policy, runtime.approval, runtime.payroll.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..agents import ledger, registry
from ..fleet.demo import store_dir
from . import store
from .kinds import KINDS, can_do, title_for
from .worker import METER, BudgetExceeded, InprocMCP, Meter, MeteredClient, execute_approval, meter_llm, reject_approval

log = logging.getLogger(__name__)

FINISHED = ("done", "failed", "cancelled", "refused")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Runtime:
    def __init__(self, client: Any = None, *, tick: float = 1.0, max_concurrent: int | None = None,
                 today: date | None = None, payroll: bool = True, task_timeout: float | None = None):
        self.client = client
        self.tick_s = tick
        self.max_concurrent = max_concurrent or int(os.getenv("RUNTIME_MAX_CONCURRENT", "4"))
        self.task_timeout = task_timeout or float(os.getenv("RUNTIME_TASK_TIMEOUT", "900"))
        self.today = today
        self.payroll_on = payroll
        self.mcp = InprocMCP()
        self.running: dict[str, asyncio.Task] = {}        # task_id -> its asyncio task
        self.stop_reason: dict[str, tuple[str, bool]] = {}  # task_id -> (why, requeue)
        self.loop_task: asyncio.Task | None = None
        self.payroll_task: asyncio.Task | None = None
        self.started_at: str | None = None
        self.last_tick: float = 0.0
        self._wake: asyncio.Event | None = None
        self.max_attempts = int(os.getenv("RUNTIME_MAX_ATTEMPTS", "2"))
        self.lease_s = float(os.getenv("AGAXES_AGENT_LEASE_S", "600"))
        self.launch_claude = os.getenv("AGAXES_LAUNCH_CLAUDE", "0") == "1" and bool(shutil.which("claude"))
        self.launches: dict[str, asyncio.subprocess.Process] = {}   # task_id -> Claude Code started for it

    # ---- lifecycle ------------------------------------------------------------------------------

    async def start(self) -> None:
        meter_llm()
        self.recover()
        self._wake = asyncio.Event()
        self.started_at = store.now()
        self.loop_task = asyncio.create_task(self._loop(), name="countersign-supervisor")
        log.info("Agaxes runtime started (store %s)", store.path())

    async def stop(self) -> None:
        for tid in list(self.running):
            self._stop(tid, "runtime shut down", requeue=True)
        for t in [self.loop_task, self.payroll_task, *self.running.values()]:
            if t and not t.done():
                t.cancel()
        await asyncio.gather(*[t for t in [self.loop_task, self.payroll_task, *self.running.values()] if t],
                             return_exceptions=True)

    @property
    def alive(self) -> bool:
        return bool(self.loop_task and not self.loop_task.done())

    def recover(self) -> None:
        """After a crash or restart: work that was mid-flight goes back in the queue; half-sent approvals go back to
        pending (the outbox write is the last step, and the guard re-checks on approval, so retrying is safe)."""
        for t in store.tasks(status="running"):
            store.update_task(t["task_id"], status="queued", waiting_on="interrupted by a restart; will run again")
            store.task_step(t["task_id"], "Runtime restarted while this was running: back in the queue", "system")
        for a in store.approvals(status="sending"):
            store.update_approval(a["approval_id"], status="pending")

    def wake(self) -> None:
        if self._wake is not None:
            self._wake.set()

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - the supervisor must keep running
                log.exception("supervisor tick failed")
            self.last_tick = time.time()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.tick_s)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    # ---- one tick -------------------------------------------------------------------------------

    async def tick(self) -> None:
        agents = {a["agent_id"]: a for a in registry.list_agents()}
        self.enforce(agents)
        self._schedules(agents)
        self._payroll()
        self._start_queued(agents)

    def enforce(self, agents: dict[str, dict] | None = None) -> None:
        agents = agents if agents is not None else {a["agent_id"]: a for a in registry.list_agents()}
        for tid in list(self.running):
            t = store.get_task(tid)
            ag = agents.get(t["agent_id"]) if t else None
            if ag is None or ag["status"] != "active":
                why = f"{ag['name']} was {ag['status']}" + (f": {ag['reason']}" if ag.get("reason") else "") if ag else "agent removed"
                self._stop(tid, why, requeue=False)
            elif store.policy(ag["agent_id"])["paused"]:
                self._stop(tid, "agent paused", requeue=True)
        for t in store.tasks(status="running"):  # outside agents: claimed over HTTP, no asyncio task here
            if t["task_id"] in self.running:
                continue
            ag = agents.get(t["agent_id"])
            if ag is None or ag["status"] != "active":
                why = f"{ag['name']} was {ag['status']}" + (f": {ag['reason']}" if ag.get("reason") else "") if ag else "agent removed"
                store.task_step(t["task_id"], f"Stopped by Agaxes: {why}. The agent is refused on its next call.", "control")
                self._finish(t["task_id"], "cancelled", error=why)
                self._kill_launch(t["task_id"])
            elif _parse(t["steps"][-1]["ts"] if t["steps"] else t.get("started_at")) and \
                    (_utcnow() - _parse(t["steps"][-1]["ts"] if t["steps"] else t["started_at"])).total_seconds() > self.lease_s:
                store.task_step(t["task_id"], f"{ag['name']} went silent for {int(self.lease_s)}s: back in the queue", "control")
                store.update_task(t["task_id"], status="queued", waiting_on=f"{ag['name']} went silent; waiting for it to claim again")
                ledger.append("task.interrupted", {"agent_id": ag["agent_id"], "task_id": t["task_id"], "why": "agent went silent"})
                self._kill_launch(t["task_id"])
            elif store.policy(ag["agent_id"])["paused"]:
                store.task_step(t["task_id"], "Stopped by Agaxes: agent paused. The agent is told to stop on its next call.", "control")
                store.update_task(t["task_id"], status="queued", waiting_on="interrupted: agent paused")
                ledger.append("task.interrupted", {"agent_id": ag["agent_id"], "task_id": t["task_id"], "why": "agent paused"})
                self._kill_launch(t["task_id"])
        for ag in agents.values():
            if ag["status"] == "offboarded":
                for t in store.tasks(ag["agent_id"], status="queued"):
                    self._finish(t["task_id"], "cancelled", error=f"{ag['name']} was offboarded")
                for a in store.approvals("pending", ag["agent_id"]):
                    store.update_approval(a["approval_id"], status="expired", decided_at=store.now(),
                                          decided_by="runtime", note=f"{ag['name']} was offboarded")

    def _stop(self, task_id: str, why: str, *, requeue: bool) -> None:
        at = self.running.get(task_id)
        if at and not at.done() and task_id not in self.stop_reason:
            self.stop_reason[task_id] = (why, requeue)
            store.task_step(task_id, f"Stopped by Agaxes: {why}", "control")
            at.cancel()

    def _schedules(self, agents: dict[str, dict]) -> None:
        now = _utcnow()
        for s in store.schedules():
            due = _parse(s.get("next_run_at"))
            if not s["enabled"] or (due and due > now):
                continue
            nxt = _iso(now + timedelta(minutes=max(1, float(s["every_minutes"]))))
            open_ = [t for t in store.tasks(s["agent_id"], status=("queued", "running")) if t.get("schedule_id") == s["schedule_id"]]
            ag = agents.get(s["agent_id"])
            if open_:
                store.update_schedule(s["schedule_id"], next_run_at=nxt, last_skip="previous run still going")
                continue
            if not ag or ag["status"] != "active":
                store.update_schedule(s["schedule_id"], next_run_at=nxt,
                                      last_skip=f"agent {ag['status'] if ag else 'missing'}; nothing started")
                continue
            try:
                t = self.assign(s["agent_id"], s["kind"], s.get("input") or {}, by=f"schedule {s['schedule_id']}",
                                schedule_id=s["schedule_id"])
                store.update_schedule(s["schedule_id"], next_run_at=nxt, last_run_at=store.now(), last_task_id=t["task_id"],
                                      runs=s.get("runs", 0) + 1, last_skip=None)
            except ValueError as e:
                store.update_schedule(s["schedule_id"], next_run_at=nxt, last_skip=str(e))

    def _payroll(self) -> None:
        if not self.payroll_on or (self.payroll_task and not self.payroll_task.done()):
            return
        p = store.payroll()
        if not p["enabled"]:
            return
        due = _parse(p.get("next_run_at"))
        if due is None:  # first start: give the server a minute before the first live re-check
            store.set_payroll(next_run_at=_iso(_utcnow() + timedelta(minutes=1)))
            return
        if due <= _utcnow():
            self.payroll_task = asyncio.create_task(self.run_payroll("schedule"))

    async def run_payroll(self, by: str) -> dict:
        """Re-check every active agent's sponsor live; the registry suspends the ones that fail. enforce() then stops
        whatever they were doing."""
        p = store.payroll()
        store.set_payroll(running=True, next_run_at=_iso(_utcnow() + timedelta(minutes=max(1, float(p["every_minutes"])))))
        before = {a["agent_id"]: a["status"] for a in registry.list_agents()}
        try:
            verdicts = await registry.recheck_all(self.client)
            after = {a["agent_id"]: a for a in registry.list_agents()}
            suspended = [after[i]["name"] for i, s in before.items() if s == "active" and i in after and after[i]["status"] != "active"]
            res = {"at": store.now(), "by": by, "checked": len(verdicts), "suspended": suspended,
                   "allowed": sum(v.decision == "allow" for v in verdicts)}
        except Exception as e:  # noqa: BLE001
            log.exception("payroll run failed")
            res = {"at": store.now(), "by": by, "error": f"{type(e).__name__}: {e}", "checked": 0, "suspended": []}
        res["ledger_entry"] = ledger.append("runtime.payroll", res)
        store.set_payroll(running=False, last_run_at=res["at"], last_result=res)
        self.enforce()
        self.wake()
        return res

    def _start_queued(self, agents: dict[str, dict]) -> None:
        busy = {store.get_task(t)["agent_id"] for t in self.running if store.get_task(t)}
        for t in store.tasks(status="queued"):
            if len(self.running) >= self.max_concurrent:
                return
            ag = agents.get(t["agent_id"])
            why = None
            if not ag:
                why = "agent not in the registry"
            elif ag["status"] != "active":
                why = f"{ag['name']} is {ag['status']}"
            elif store.policy(ag["agent_id"])["paused"]:
                why = f"{ag['name']} is paused"
            elif ag["agent_id"] in busy or (ag.get("runtime") == "external" and store.tasks(ag["agent_id"], status="running")):
                why = f"{ag['name']} is busy with another task"
            elif store.usage(ag["agent_id"])["tasks"] >= store.policy(ag["agent_id"])["budget"]["tasks_per_day"]:
                why = "daily task budget reached"
            if why:
                if t.get("waiting_on") != why:
                    store.update_task(t["task_id"], waiting_on=why)
                continue
            if ag.get("runtime") == "external":
                why = f"waiting for {ag['name']} to pick it up"
                if self.launch_claude and t["task_id"] not in self.launches:
                    self._launch(t, ag)
                    why = f"Agaxes started {ag['name']} on this machine; waiting for it to claim the task"
                if t.get("waiting_on") != why:
                    store.update_task(t["task_id"], waiting_on=why)
                continue
            busy.add(ag["agent_id"])
            self.running[t["task_id"]] = asyncio.create_task(self._run(t["task_id"], ag), name=t["task_id"])

    # ---- outside agents: start Claude Code on this machine for a queued task --------------------

    def _launch(self, t: dict, ag: dict) -> None:
        from .external import claude_prompt
        exe = shutil.which("claude")
        cli = str(Path(__file__).resolve().parents[2] / "scripts" / "agaxes_agent.py")
        cmd = [exe, "-p", claude_prompt(ag, t["task_id"], f"{sys.executable} {cli}"),
               "--allowedTools", f"Bash({sys.executable} {cli}:*)"]

        async def go() -> None:
            try:
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                            env=os.environ.copy())
            except OSError as e:
                store.task_step(t["task_id"], f"Could not start {ag['name']}: {e}", "system")
                return
            self.launches[t["task_id"]] = proc
            store.task_step(t["task_id"], f"Agaxes started {ag['name']} (Claude Code, pid {proc.pid}) to work this task", "system")
            out, _ = await proc.communicate()
            text = (out or b"").decode(errors="replace").strip()
            if text:
                store.task_step(t["task_id"], f"{ag['name']} said: {text[-1500:]}", "agent")
            cur = store.get_task(t["task_id"])
            if cur and cur["status"] in ("queued", "running") and proc.returncode not in (None, 0, -15, 143):
                last = (text.splitlines() or [""])[-1][:300]
                self._finish(t["task_id"], "failed", error=f"{ag['name']} could not run (exit {proc.returncode}): {last}")
                self.launches.pop(t["task_id"], None)

        self.launches[t["task_id"]] = None  # type: ignore[assignment]  # reserved: don't launch twice
        asyncio.create_task(go())

    def _kill_launch(self, task_id: str) -> None:
        proc = self.launches.get(task_id)
        if proc is not None and proc.returncode is None:
            proc.terminate()
            store.task_step(task_id, "Agaxes ended the agent's process on this machine", "control")
        self.launches.pop(task_id, None)  # a resumed task may be launched again

    # ---- running one task -----------------------------------------------------------------------

    async def _run(self, task_id: str, agent: dict) -> None:
        t = store.get_task(task_id)
        METER.set(Meter(task_id, agent["agent_id"]))
        store.add_usage(agent["agent_id"], tasks=1)
        entry = ledger.append("task.started", {"agent_id": agent["agent_id"], "task_id": task_id, "kind": t["kind"],
                                               "title": t["title"], "attempt": t["attempts"] + 1})
        store.task_mutate(task_id, lambda x: (x.update(status="running", started_at=x["started_at"] or store.now(),
                                                       attempts=x["attempts"] + 1, waiting_on=None, error=None),
                                              x["ledger"].append(entry)))
        store.task_step(task_id, f"{agent['name']} started: {t['title']}", "system")
        work = store_dir() / "work"
        work.mkdir(parents=True, exist_ok=True)
        from .worker import RuntimeCtx
        ctx = RuntimeCtx(mcp=self.mcp, agent=agent, key=registry.private_key(agent["agent_id"]),
                         client=MeteredClient(self.client) if self.client is not None else None, out_dir=work,
                         today=self.today, say=lambda line: store.task_step(task_id, line.rstrip()), emit=None)
        ctx.task_id = task_id
        t0 = time.time()
        try:
            res = await asyncio.wait_for(KINDS[t["kind"]]["handler"](ctx, t["input"]), timeout=self.task_timeout)
            status = "refused" if res.get("refused") else ("done" if res.get("ok") else "failed")
            self._finish(task_id, status, result=res.get("summary"), seconds=time.time() - t0)
        except asyncio.CancelledError:
            why, requeue = self.stop_reason.pop(task_id, ("cancelled", False))
            if requeue:
                store.update_task(task_id, status="queued", waiting_on=f"interrupted: {why}")
                ledger.append("task.interrupted", {"agent_id": agent["agent_id"], "task_id": task_id, "why": why})
            else:
                self._finish(task_id, "cancelled", error=why, seconds=time.time() - t0)
        except BudgetExceeded as e:
            self._finish(task_id, "failed", error=f"Stopped: {e}", seconds=time.time() - t0)
        except asyncio.TimeoutError:
            self._finish(task_id, "failed", error=f"timed out after {int(self.task_timeout)}s", seconds=time.time() - t0)
        except Exception as e:  # noqa: BLE001 - one task failing never takes the runtime down
            log.exception("task %s failed", task_id)
            err = f"{type(e).__name__}: {e}"
            if isinstance(e, ValueError) or (store.get_task(task_id) or {}).get("attempts", 9) >= self.max_attempts:
                self._finish(task_id, "failed", error=err, seconds=time.time() - t0)
            else:  # a transient failure (network, model, timeout inside a call): one more try
                store.task_step(task_id, f"Failed ({err}); Agaxes will retry it once", "system")
                store.update_task(task_id, status="queued", waiting_on=f"retrying after: {err[:160]}")
                ledger.append("task.retry", {"agent_id": agent["agent_id"], "task_id": task_id, "error": err[:300]})
        finally:
            self.running.pop(task_id, None)
            self.stop_reason.pop(task_id, None)
            self.wake()

    def _finish(self, task_id: str, status: str, *, result: str | None = None, error: str | None = None,
                seconds: float | None = None) -> None:
        t = store.get_task(task_id)
        if not t:
            return
        entry = ledger.append(f"task.{status}", {"agent_id": t["agent_id"], "task_id": task_id, "kind": t["kind"],
                                                 "title": t["title"], "result": result, "error": error,
                                                 "usage": t["usage"], "seconds": round(seconds, 1) if seconds else None})
        store.task_mutate(task_id, lambda x: (x.update(status=status, finished_at=store.now(), result=result, error=error,
                                                       waiting_on=None, seconds=round(seconds, 1) if seconds else None),
                                              x["ledger"].append(entry)))
        store.task_step(task_id, f"{status.capitalize()}: {result or error or ''}".rstrip(": "), "system")

    # ---- the employer's controls ----------------------------------------------------------------

    def assign(self, agent_id: str, kind: str, inp: dict, *, by: str, title: str | None = None,
               schedule_id: str | None = None, ref: dict | None = None) -> dict:
        agent = registry.get_agent(agent_id)
        why = can_do(agent, kind)
        if why:
            raise ValueError(why)
        for f in KINDS[kind]["fields"]:
            if f["required"] and not str(inp.get(f["name"]) or "").strip():
                raise ValueError(f"{f['label']} is required")
        t = store.add_task(agent, kind, title or title_for(kind, inp), inp, by=by, schedule_id=schedule_id, ref=ref)
        entry = ledger.append("task.assigned", {"agent_id": agent_id, "task_id": t["task_id"], "kind": kind,
                                                "title": t["title"], "by": by, "schedule_id": schedule_id})
        store.task_mutate(t["task_id"], lambda x: x["ledger"].append(entry))
        store.task_step(t["task_id"], f"Assigned to {agent['name']} by {by}", "system")
        self.wake()
        return store.get_task(t["task_id"])

    def cancel(self, task_id: str, by: str) -> dict:
        t = store.get_task(task_id)
        if not t:
            raise KeyError(task_id)
        if t["status"] == "running" and task_id not in self.running:  # an outside agent's task
            store.task_step(task_id, f"Stopped by Agaxes: cancelled by {by}", "control")
            self._finish(task_id, "cancelled", error=f"cancelled by {by}")
            self._kill_launch(task_id)
        elif t["status"] == "running":
            self._stop(task_id, f"cancelled by {by}", requeue=False)
        elif t["status"] == "queued":
            self._finish(task_id, "cancelled", error=f"cancelled by {by} before it started")
        else:
            raise ValueError(f"task is already {t['status']}")
        self.wake()
        return store.get_task(task_id)

    def retry(self, task_id: str, by: str) -> dict:
        t = store.get_task(task_id)
        if not t:
            raise KeyError(task_id)
        return self.assign(t["agent_id"], t["kind"], t["input"], by=f"{by} (retry of {task_id})", title=t["title"], ref=t.get("ref"))

    def pause(self, agent_id: str, by: str, reason: str | None = None) -> dict:
        registry.get_agent(agent_id)
        pol = store.set_policy(agent_id, paused=True, paused_reason=reason or f"paused by {by}")
        ledger.append("agent.paused", {"agent_id": agent_id, "by": by, "reason": reason})
        self.enforce()
        self.wake()
        return pol

    def resume(self, agent_id: str, by: str) -> dict:
        registry.get_agent(agent_id)
        pol = store.set_policy(agent_id, paused=False, paused_reason=None)
        ledger.append("agent.resumed", {"agent_id": agent_id, "by": by})
        self.wake()
        return pol

    def set_policy(self, agent_id: str, by: str, *, require_approval: bool | None = None, budget: dict | None = None) -> dict:
        registry.get_agent(agent_id)
        pol = store.set_policy(agent_id, require_approval=require_approval, budget=budget)
        ledger.append("runtime.policy", {"agent_id": agent_id, "by": by, "require_approval": pol["require_approval"],
                                         "budget": pol["budget"]})
        self.wake()
        return pol

    def suspend(self, agent_id: str, by: str, reason: str) -> dict:
        rec = registry.suspend(agent_id, reason, by=by)
        self.enforce()
        self.wake()
        return rec

    async def approve(self, approval_id: str, by: str) -> dict:
        return await execute_approval(approval_id, by, self.mcp)

    def reject(self, approval_id: str, by: str, note: str | None = None) -> dict:
        return reject_approval(approval_id, by, note)

    def add_schedule(self, agent_id: str, kind: str, inp: dict, every_minutes: float, by: str) -> dict:
        agent = registry.get_agent(agent_id)
        why = can_do(agent, kind)
        if why:
            raise ValueError(why)
        if every_minutes < 1:
            raise ValueError("every_minutes must be at least 1")
        s = store.add_schedule(agent_id=agent_id, agent_name=agent["name"], kind=kind, input=inp,
                               title=title_for(kind, inp), every_minutes=every_minutes, created_by=by)
        ledger.append("runtime.schedule", {"agent_id": agent_id, "schedule_id": s["schedule_id"], "kind": kind,
                                           "every_minutes": every_minutes, "by": by, "action": "created"})
        self.wake()
        return s


# ---- read model for the console -------------------------------------------------------------------

def _secs(t: dict) -> float | None:
    a, b = _parse(t.get("started_at")), _parse(t.get("finished_at"))
    return (b - a).total_seconds() if a and b else t.get("seconds")


def metrics(agent_id: str, tasks: list[dict], approvals: list[dict]) -> dict:
    mine = [t for t in tasks if t["agent_id"] == agent_id]
    fin = [t for t in mine if t["status"] in FINISHED]
    done = [t for t in fin if t["status"] == "done"]
    graded = [t for t in fin if t["status"] in ("done", "failed", "refused")]
    sends = [s for t in mine for s in t["output"].get("sends", [])]
    durs = [d for d in (_secs(t) for t in done) if d]
    last = max((t.get("finished_at") or t.get("started_at") or "" for t in mine), default="") or None
    return {
        "tasks_total": len(mine), "done": len(done), "failed": sum(t["status"] == "failed" for t in fin),
        "refused": sum(t["status"] == "refused" for t in fin), "cancelled": sum(t["status"] == "cancelled" for t in fin),
        "success_rate": round(len(done) / len(graded), 3) if graded else None,
        "avg_seconds": round(sum(durs) / len(durs), 1) if durs else None,
        "drafts": len(sends), "guard_blocked": sum(s["state"] == "blocked" for s in sends),
        "sent": sum(a["status"] == "sent" for a in approvals if a["agent_id"] == agent_id)
                + sum(s["state"] == "sent" and not s.get("approval_id") for s in sends),
        "pending_approval": sum(a["status"] == "pending" for a in approvals if a["agent_id"] == agent_id),
        "rejected": sum(a["status"] == "rejected" for a in approvals if a["agent_id"] == agent_id),
        "blocked_at_send": sum(a["status"] == "blocked_at_send" for a in approvals if a["agent_id"] == agent_id),
        "findings": sum(len(t["output"].get("findings", [])) for t in mine),
        "false_claims": sum(len(f.get("contradicted") or []) for t in mine for f in t["output"].get("findings", [])),
        "approval_rate": (lambda dec: round(sum(a["status"] in ("sent", "blocked_at_send") for a in dec) / len(dec), 3) if dec else None)(
            [a for a in approvals if a["agent_id"] == agent_id and a["status"] in ("sent", "blocked_at_send", "rejected")]),
        "filed": sum(len(t["output"].get("filed", [])) for t in mine),
        "crustdata_calls": sum(t["usage"].get("crustdata", 0) for t in mine),
        "llm_calls": sum(t["usage"].get("llm", 0) for t in mine),
        "last_active": last,
    }


def _brief_task(t: dict) -> dict:
    out = t.get("output") or {}
    return {**{k: v for k, v in t.items() if k not in ("steps", "output", "input")},
            "last_step": (t["steps"][-1]["text"] if t["steps"] else None),
            "counts": {"sends": len(out.get("sends", [])), "findings": len(out.get("findings", [])),
                       "shortlist": len(out.get("shortlist", [])), "artifacts": len(out.get("artifacts", []))}}


def state(rt: Runtime | None) -> dict:
    snap = store.snapshot()
    tasks = sorted(snap["tasks"].values(), key=lambda t: t["created_at"])
    apvs = sorted(snap["approvals"].values(), key=lambda a: a["created_at"])
    agents = []
    for a in registry.list_agents():
        aid = a["agent_id"]
        cur = next((t for t in tasks if t["agent_id"] == aid and t["status"] == "running"), None)
        queued = [t for t in tasks if t["agent_id"] == aid and t["status"] == "queued"]
        pol = store.policy(aid)
        kinds_ok = [k for k in KINDS if can_do(a, k) is None]
        if a["status"] != "active":
            activity = a["status"]
        elif pol["paused"]:
            activity = "paused"
        elif cur:
            activity = "working"
        elif any(x["status"] == "pending" and x["agent_id"] == aid for x in apvs):
            activity = "waiting_on_you"
        else:
            activity = "idle"
        agents.append({
            "agent_id": aid, "name": a["name"], "role": a["role"], "job": a.get("job"), "runtime": a.get("runtime"),
            "employee_no": a.get("employee_no"), "status": a["status"], "reason": a.get("reason"),
            "sponsor": a["passport"]["sponsor"], "scopes": a["passport"]["scopes"], "activity": activity,
            "policy": pol, "usage_today": store.usage(aid), "kinds": kinds_ok,
            "current": _brief_task(cur) if cur else None, "queued": len(queued),
            "metrics": metrics(aid, tasks, apvs),
        })
    recent = list(reversed(tasks))[:80]
    pending = [a for a in apvs if a["status"] == "pending"]
    decided = list(reversed([a for a in apvs if a["status"] != "pending"]))[:40]
    try:
        chain_ok, bad = ledger.verify_chain()
    except Exception:  # noqa: BLE001
        chain_ok, bad = False, None
    today_s = store.today()
    return {
        "version": snap.get("version", 0),
        "runtime": {"alive": bool(rt and rt.alive), "started_at": rt.started_at if rt else None,
                    "running": len(rt.running) if rt else 0, "max_concurrent": rt.max_concurrent if rt else 0,
                    "modes": {"crustdata": os.getenv("CRUSTDATA_MODE", "cache"), "llm": os.getenv("LLM_MODE", "live")}},
        "totals": {
            "agents": len([a for a in agents if a["status"] != "offboarded"]),
            "working": sum(a["activity"] == "working" for a in agents),
            "queued": sum(t["status"] == "queued" for t in tasks),
            "done_today": sum(t["status"] == "done" and (t.get("finished_at") or "").startswith(today_s) for t in tasks),
            "failed_today": sum(t["status"] in ("failed", "refused") and (t.get("finished_at") or "").startswith(today_s) for t in tasks),
            "pending_approvals": len(pending),
            "sent_today": sum(a["status"] == "sent" and (a.get("decided_at") or "").startswith(today_s) for a in apvs),
            "blocked_today": sum(s["state"] == "blocked" for t in tasks if (t.get("created_at") or "").startswith(today_s)
                                 for s in t["output"].get("sends", [])),
        },
        "agents": agents,
        "tasks": [_brief_task(t) for t in recent],
        "approvals": {"pending": pending, "decided": decided},
        "schedules": snap["schedules"] and sorted(snap["schedules"].values(), key=lambda s: s["created_at"]) or [],
        "payroll": store.payroll(),
        "ledger": {"chain_ok": chain_ok, "first_bad_seq": bad},
    }
