"""Runtime state on disk: one JSON file next to the registry (RUNTIME_PATH overrides).

Holds tasks (with their live steps and output), approvals waiting on a person, recurring schedules, each agent's
policy (paused, approvals, daily budgets) and daily usage. One process owns it (the API server that runs the
supervisor); writes are atomic (temp file + rename), so a crash never leaves half a file. On start the supervisor
puts tasks that were running when the process died back in the queue.
"""
from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
MAX_TASKS = 500
MAX_STEPS = 400

DEFAULT_BUDGET = {"tasks_per_day": 40, "sends_per_day": 25, "crustdata_calls_per_day": 300, "llm_calls_per_day": 200}
DEFAULT_POLICY = {"paused": False, "paused_reason": None, "require_approval": True, "budget": DEFAULT_BUDGET}
DEFAULT_PAYROLL = {"enabled": True, "every_minutes": 30, "last_run_at": None, "next_run_at": None, "last_result": None}

_lock = threading.RLock()
_state: dict | None = None
_state_path: Path | None = None


def path() -> Path:
    if os.getenv("RUNTIME_PATH"):
        return Path(os.environ["RUNTIME_PATH"])
    agents = Path(os.getenv("AGENTS_PATH") or BACKEND / "data" / "agents.json")
    return agents.parent / "runtime.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def _empty() -> dict:
    return {"tasks": {}, "approvals": {}, "schedules": {}, "policies": {}, "usage": {}, "payroll": dict(DEFAULT_PAYROLL),
            "version": 0}


def _load() -> dict:
    global _state, _state_path
    p = path()
    if _state is None or _state_path != p:
        _state_path = p
        try:
            _state = {**_empty(), **json.loads(p.read_text())}
        except (OSError, json.JSONDecodeError):
            _state = _empty()
    return _state


def _save() -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    s = _load()
    s["version"] = s.get("version", 0) + 1
    tasks = s["tasks"]
    if len(tasks) > MAX_TASKS:  # drop the oldest finished tasks
        done = [t for t in tasks.values() if t["status"] in ("done", "failed", "cancelled", "refused")]
        for t in sorted(done, key=lambda t: t["created_at"])[: len(tasks) - MAX_TASKS]:
            tasks.pop(t["task_id"], None)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, default=str))
    tmp.replace(p)


def reset_cache() -> None:
    """Tests switch RUNTIME_PATH between cases."""
    global _state, _state_path
    with _lock:
        _state, _state_path = None, None


def snapshot() -> dict:
    with _lock:
        return copy.deepcopy(_load())


def version() -> int:
    with _lock:
        return _load().get("version", 0)


# ---- tasks ----------------------------------------------------------------------------------------

def add_task(agent: dict, kind: str, title: str, inp: dict, *, by: str, schedule_id: str | None = None,
             ref: dict | None = None) -> dict:
    t = {"task_id": new_id("tsk"), "agent_id": agent["agent_id"], "agent_name": agent["name"], "kind": kind,
         "title": title, "input": inp, "status": "queued", "waiting_on": None, "assigned_by": by,
         "schedule_id": schedule_id, "ref": ref, "created_at": now(), "started_at": None, "finished_at": None,
         "attempts": 0, "progress": {"done": 0, "total": 0, "label": "queued"}, "steps": [], "output": {},
         "usage": {"crustdata": 0, "llm": 0, "sends": 0}, "error": None, "result": None, "ledger": []}
    with _lock:
        _load()["tasks"][t["task_id"]] = t
        _save()
    return copy.deepcopy(t)


def get_task(task_id: str) -> dict | None:
    with _lock:
        t = _load()["tasks"].get(task_id)
        return copy.deepcopy(t) if t else None


def update_task(task_id: str, **fields: Any) -> dict | None:
    with _lock:
        t = _load()["tasks"].get(task_id)
        if not t:
            return None
        t.update(fields)
        _save()
        return copy.deepcopy(t)


def task_step(task_id: str, text: str, kind: str = "log", data: dict | None = None, *, save: bool = True) -> None:
    with _lock:
        t = _load()["tasks"].get(task_id)
        if not t:
            return
        step = {"ts": now(), "kind": kind, "text": text}
        if data:
            step["data"] = data
        t["steps"].append(step)
        if len(t["steps"]) > MAX_STEPS:
            t["steps"] = t["steps"][:20] + [{"ts": now(), "kind": "log", "text": "(earlier steps trimmed)"}] + t["steps"][-(MAX_STEPS - 21):]
        if save:
            _save()


def task_mutate(task_id: str, fn) -> dict | None:
    """Apply fn(task) under the lock and save. For output lists and counters."""
    with _lock:
        t = _load()["tasks"].get(task_id)
        if not t:
            return None
        fn(t)
        _save()
        return copy.deepcopy(t)


def tasks(agent_id: str | None = None, status: str | tuple | None = None) -> list[dict]:
    with _lock:
        rows = list(_load()["tasks"].values())
    if agent_id:
        rows = [t for t in rows if t["agent_id"] == agent_id]
    if status:
        want = (status,) if isinstance(status, str) else status
        rows = [t for t in rows if t["status"] in want]
    return copy.deepcopy(sorted(rows, key=lambda t: t["created_at"]))


# ---- approvals ------------------------------------------------------------------------------------

def add_approval(**fields: Any) -> dict:
    a = {"approval_id": new_id("apv"), "status": "pending", "created_at": now(), "decided_at": None, "decided_by": None,
         "note": None, "result": None, **fields}
    with _lock:
        _load()["approvals"][a["approval_id"]] = a
        _save()
    return copy.deepcopy(a)


def get_approval(approval_id: str) -> dict | None:
    with _lock:
        a = _load()["approvals"].get(approval_id)
        return copy.deepcopy(a) if a else None


def update_approval(approval_id: str, **fields: Any) -> dict | None:
    with _lock:
        a = _load()["approvals"].get(approval_id)
        if not a:
            return None
        a.update(fields)
        _save()
        return copy.deepcopy(a)


def claim_approval(approval_id: str, by: str) -> dict | None:
    """pending -> sending, atomically, so two clicks can't send twice. None if it isn't pending."""
    with _lock:
        a = _load()["approvals"].get(approval_id)
        if not a or a["status"] != "pending":
            return None
        a.update(status="sending", decided_by=by, decided_at=now())
        _save()
        return copy.deepcopy(a)


def approvals(status: str | None = None, agent_id: str | None = None) -> list[dict]:
    with _lock:
        rows = list(_load()["approvals"].values())
    if status:
        rows = [a for a in rows if a["status"] == status]
    if agent_id:
        rows = [a for a in rows if a["agent_id"] == agent_id]
    return copy.deepcopy(sorted(rows, key=lambda a: a["created_at"]))


# ---- schedules ------------------------------------------------------------------------------------

def add_schedule(**fields: Any) -> dict:
    s = {"schedule_id": new_id("sch"), "enabled": True, "created_at": now(), "last_task_id": None, "last_run_at": None,
         "next_run_at": now(), "runs": 0, **fields}
    with _lock:
        _load()["schedules"][s["schedule_id"]] = s
        _save()
    return copy.deepcopy(s)


def update_schedule(schedule_id: str, **fields: Any) -> dict | None:
    with _lock:
        s = _load()["schedules"].get(schedule_id)
        if not s:
            return None
        s.update(fields)
        _save()
        return copy.deepcopy(s)


def delete_schedule(schedule_id: str) -> bool:
    with _lock:
        ok = _load()["schedules"].pop(schedule_id, None) is not None
        if ok:
            _save()
        return ok


def schedules() -> list[dict]:
    with _lock:
        return copy.deepcopy(sorted(_load()["schedules"].values(), key=lambda s: s["created_at"]))


# ---- policies, usage, payroll ---------------------------------------------------------------------

def policy(agent_id: str) -> dict:
    with _lock:
        p = _load()["policies"].get(agent_id) or {}
    out = copy.deepcopy(DEFAULT_POLICY)
    out.update({k: v for k, v in p.items() if k != "budget"})
    out["budget"] = {**DEFAULT_BUDGET, **(p.get("budget") or {})}
    return out


def set_policy(agent_id: str, **fields: Any) -> dict:
    with _lock:
        p = _load()["policies"].setdefault(agent_id, {})
        if "budget" in fields and fields["budget"] is not None:
            p["budget"] = {**(p.get("budget") or {}), **{k: int(v) for k, v in fields.pop("budget").items()
                                                          if k in DEFAULT_BUDGET and v is not None}}
        p.update({k: v for k, v in fields.items() if v is not None or k == "paused_reason"})
        _save()
    return policy(agent_id)


def usage(agent_id: str, day: str | None = None) -> dict:
    with _lock:
        u = (_load()["usage"].get(agent_id) or {}).get(day or today()) or {}
    return {"tasks": 0, "sends": 0, "crustdata": 0, "llm": 0, **u}


def add_usage(agent_id: str, *, save: bool = True, **inc: int) -> dict:
    with _lock:
        days = _load()["usage"].setdefault(agent_id, {})
        u = days.setdefault(today(), {"tasks": 0, "sends": 0, "crustdata": 0, "llm": 0})
        for k, v in inc.items():
            u[k] = u.get(k, 0) + v
        for old in sorted(days)[:-14]:  # keep two weeks
            days.pop(old, None)
        if save:
            _save()
        return dict(u)


def payroll() -> dict:
    with _lock:
        return {**DEFAULT_PAYROLL, **(_load().get("payroll") or {})}


def set_payroll(**fields: Any) -> dict:
    with _lock:
        s = _load()
        s["payroll"] = {**DEFAULT_PAYROLL, **(s.get("payroll") or {}), **fields}
        _save()
        return dict(s["payroll"])
