"""Outside agents (Claude Code, another company's bot) working Agaxes tasks from their own machine.

They hold their own private key and talk to Agaxes over HTTP (scripts/agaxes_agent.py is a ready client; the MCP
server exposes the same calls). Every call is signed with the agent's key over

    agaxes|<action>|<agent_id>|<task_id>|<ts>|<text>

so only the holder of the key can claim, report or finish a task, and an old call can't be replayed (ts must be
within 5 minutes). The employer's controls reach them the same way as in-house agents:
  - a paused, suspended or offboarded agent can't claim work, and its next progress call is answered "stop";
  - a send goes through Send Guard and then the approval inbox, exactly like an in-house agent's;
  - everything lands on the task and the ledger.
"""
from __future__ import annotations

import time

from ..agents import ledger, registry
from ..agents.models import Passport
from ..agents.passport import signature_valid, verify_message_signature
from . import store
from .kinds import KINDS
from .worker import METER, Meter, RuntimeCtx

MAX_SKEW = 300


class AgentAuthError(PermissionError):
    pass


def signed_text(action: str, agent_id: str, task_id: str | None, ts: int, text: str = "") -> str:
    return f"agaxes|{action}|{agent_id}|{task_id or ''}|{ts}|{text}"


def authenticate(action: str, agent_id: str, task_id: str | None, ts: int, text: str, signature: str) -> dict:
    try:
        rec = registry.get_agent(agent_id)
    except Exception:  # noqa: BLE001
        raise AgentAuthError(f"unknown agent {agent_id}")
    p = Passport.model_validate(rec["passport"])
    if not signature_valid(p):
        raise AgentAuthError("passport signature invalid")
    if abs(time.time() - int(ts)) > MAX_SKEW:
        raise AgentAuthError("stale or future timestamp: sign the call with the current time")
    if not verify_message_signature(p, signed_text(action, agent_id, task_id, ts, text), signature or ""):
        raise AgentAuthError("signature does not match this agent's key")
    return rec


def _stop_reason(rec: dict) -> str | None:
    if rec["status"] != "active":
        return f"{rec['name']} is {rec['status']}" + (f": {rec['reason']}" if rec.get("reason") else "")
    pol = store.policy(rec["agent_id"])
    if pol["paused"]:
        return f"{rec['name']} is paused: {pol['paused_reason'] or 'by the employer'}"
    return None


def claim(rec: dict, task_id: str | None = None) -> dict:
    """The agent's next queued task (or the one named), now running. {"task": None, "stop"/"reason"} if none."""
    why = _stop_reason(rec)
    if why:
        return {"task": None, "stop": True, "reason": why}
    aid = rec["agent_id"]
    running = store.tasks(aid, status="running")
    if running and (task_id is None or running[0]["task_id"] == task_id):
        t = running[0]  # already claimed: hand it back (an agent that restarted)
    else:
        queued = [t for t in store.tasks(aid, status="queued") if task_id in (None, t["task_id"])]
        if not queued:
            return {"task": None, "stop": False, "reason": "no task waiting for you"}
        pol = store.policy(aid)
        if store.usage(aid)["tasks"] >= pol["budget"]["tasks_per_day"]:
            return {"task": None, "stop": True, "reason": "daily task budget reached"}
        t = queued[0]
        store.add_usage(aid, tasks=1)
        entry = ledger.append("task.started", {"agent_id": aid, "task_id": t["task_id"], "kind": t["kind"],
                                               "title": t["title"], "attempt": t["attempts"] + 1, "runtime": "external"})
        store.task_mutate(t["task_id"], lambda x: (x.update(status="running", started_at=x["started_at"] or store.now(),
                                                            attempts=x["attempts"] + 1, waiting_on=None, error=None),
                                                   x["ledger"].append(entry)))
        store.task_step(t["task_id"], f"{rec['name']} claimed the task (signed with its own key)", "system")
        t = store.get_task(t["task_id"])
    return {"task": {"task_id": t["task_id"], "kind": t["kind"], "title": t["title"], "input": t["input"],
                     "scopes": rec["passport"]["scopes"],
                     "rules": "Report progress after each step and stop at once if told to. Ask before sending anything: "
                              "use send, which goes through Send Guard and your employer's approval."},
            "stop": False}


def _running_task(rec: dict, task_id: str) -> tuple[dict | None, str | None]:
    t = store.get_task(task_id)
    if not t or t["agent_id"] != rec["agent_id"]:
        return None, "not your task"
    why = _stop_reason(rec)
    if why:
        return t, why
    if t["status"] != "running":
        return t, f"task is {t['status']}" + (f": {t['error']}" if t.get("error") else "") + \
            (f" ({t['waiting_on']})" if t.get("waiting_on") else "")
    return t, None


def progress(rec: dict, task_id: str, text: str, done: int | None = None, total: int | None = None) -> dict:
    t, why = _running_task(rec, task_id)
    if t is None:
        return {"continue": False, "stop": True, "reason": why}
    if why:
        store.task_step(task_id, f"{rec['name']} tried to continue and was told to stop: {why}", "control")
        return {"continue": False, "stop": True, "reason": why}
    store.task_step(task_id, f"  {text.strip()[:1000]}", "agent")
    if done is not None or total is not None:
        store.task_mutate(task_id, lambda x: x["progress"].update(
            done=int(done if done is not None else x["progress"]["done"]),
            total=int(total if total is not None else x["progress"]["total"]), label="working"))
    return {"continue": True, "stop": False}


def complete(rt, rec: dict, task_id: str, summary: str, ok: bool = True) -> dict:
    t, why = _running_task(rec, task_id)
    if t is None or why:
        return {"recorded": False, "stop": True, "reason": why}
    store.task_mutate(task_id, lambda x: x["output"].setdefault("artifacts", []).append(
        {"kind": "report", "title": f"{rec['name']}'s report", "content": summary}))
    rt._finish(task_id, "done" if ok else "failed", result=summary.strip().splitlines()[0][:300] if summary.strip() else "done")
    rt.wake()
    return {"recorded": True, "status": "done" if ok else "failed"}


async def send(rt, rec: dict, task_id: str, to: dict, body: str, scope: str, message_signature: str) -> dict:
    """Send Guard, then the employer's approval policy, exactly as for an in-house agent."""
    t, why = _running_task(rec, task_id)
    if t is None or why:
        return {"decision": "block", "sent": False, "stop": True, "reason": why}
    METER.set(Meter(task_id, rec["agent_id"]))
    ctx = RuntimeCtx(mcp=rt.mcp, agent=rec, key=b"", client=None, out_dir=store.path().parent, today=rt.today,
                     say=lambda line: store.task_step(task_id, line.rstrip()), emit=None)
    ctx.task_id = task_id
    v = await rt.mcp.tool("check_before_send", {"agent_id": rec["agent_id"], "signature": message_signature, "to": to,
                                                "body": body, "scope": scope, **ctx._today()})
    res = await ctx.after_guard(to, body, scope, message_signature, v)
    out = {"decision": res.get("decision"), "sent": bool(res.get("sent")), "pending_approval": res.get("pending_approval"),
           "failed_checks": [f"{c['name']}: {c['detail']}" for c in res.get("checks", []) if c.get("status") != "pass"]}
    out["next"] = ("Waiting for your employer's approval; carry on with the rest of the task." if out["pending_approval"]
                   else "Sent to the outbox." if out["sent"] else "Blocked: do not send this. Fix the draft or report it.")
    return out


def claude_prompt(agent: dict, task_id: str, cli: str) -> str:
    aid = agent["agent_id"]
    return (
        f"You are {agent['name']}, an AI employee governed by Agaxes (agent id {aid}). Your employer assigned you task "
        f"{task_id}. Work it using ONLY this command-line client, which signs every call with your key:\n"
        f"  {cli} next {aid} --task {task_id}            claim the task and read its instructions\n"
        f"  {cli} progress {aid} {task_id} \"<what you just did>\"   after every step\n"
        f"  {cli} send {aid} {task_id} --name \"<name>\" --url <linkedin url> --company \"<company>\" --scope <scope> \"<exact message>\"\n"
        f"  {cli} done {aid} {task_id} \"<your final report>\"\n"
        "Rules: never contact anyone except through `send` (it goes through Send Guard and your employer's approval; "
        "nothing is emailed). If any command prints STOP, stop immediately and do nothing else. Keep messages short and "
        "factual; don't state facts about a person that you haven't been given. Finish with `done`."
    )
