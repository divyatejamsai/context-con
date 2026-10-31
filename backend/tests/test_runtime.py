"""The agent runtime (app/runtime): real fleet agents on real (replayed) Crustdata, under the employer's controls."""
import asyncio
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.agents import ledger, registry
from app.agents.api import crustdata
from app.fleet.demo import onboard
from app.runtime import kinds, store
from app.runtime.supervisor import Runtime, state

TODAY = date(2026, 10, 31)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    for var, name in (("AGENTS_PATH", "agents.json"), ("LEDGER_PATH", "ledger.jsonl"), ("ISSUER_KEY_PATH", "issuer.key"),
                      ("OUTBOX_PATH", "outbox.jsonl"), ("RUNTIME_PATH", "runtime.json")):
        monkeypatch.setenv(var, str(tmp_path / name))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.delenv("COUNTERSIGN_ADMIN_TOKEN", raising=False)
    store.reset_cache()
    # Crustdata clients hold loop-bound locks: give every test (each has its own event loop) fresh ones.
    from app.agents import api as agents_api
    from app.runtime import worker
    monkeypatch.setattr(agents_api, "_client", None)
    monkeypatch.setattr(worker, "_mcp_mod", None)
    yield tmp_path
    store.reset_cache()


@pytest.fixture
def slow_kind(monkeypatch):
    """A job that takes as long as the test wants: lets us stop an agent mid-task."""
    gate = {"steps": 0}

    async def handler(ctx, inp):
        await ctx.clock_in("data.read")
        for i in range(int(inp.get("n", 200))):
            ctx.log(f"  working   step {i}")
            gate["steps"] += 1
            await asyncio.sleep(0.02)
        return {"ok": True, "summary": "finished"}

    monkeypatch.setitem(kinds.KINDS, "slow", {"label": "Slow", "scope": "data.read", "fields": [], "handler": handler,
                                              "description": "", "agent_hint": None})
    return gate


async def until(cond, timeout=60.0):
    t = 0.0
    while not cond():
        await asyncio.sleep(0.05)
        t += 0.05
        if t > timeout:
            raise AssertionError("timed out waiting")


def fleet() -> dict:
    return {k: a for k, a, _ in onboard(["sourced", "pipeline", "diligence", "reference", "closer"])}


def status(tid: str) -> str:
    return store.get_task(tid)["status"]


@pytest.mark.asyncio
async def test_agents_do_real_work_and_sends_wait_for_approval(tmp_path):
    ags = fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        p = rt.assign(ags["pipeline"]["agent_id"], "sales_outreach", {}, by="test")
        d = rt.assign(ags["diligence"]["agent_id"], "vendor_diligence", {"domain": "razorpay.com"}, by="test")
        c = rt.assign(ags["closer"]["agent_id"], "sales_outreach", {}, by="test")
        await until(lambda: all(status(t["task_id"]) not in ("queued", "running") for t in (p, d, c)), 120)
        pt, dt, ct = (store.get_task(t["task_id"]) for t in (p, d, c))
        assert pt["status"] == "done" and dt["status"] == "done"
        assert ct["status"] == "refused" and ct["output"]["clock_in"]["failed"][0]["name"] == "sponsor_still_employed"
        sends = {s["to"]["name"]: s["state"] for s in pt["output"]["sends"]}
        assert sends["Shivank Verma"] == "blocked"  # stale CRM row never reaches a person
        assert sum(v == "pending_approval" for v in sends.values()) == 3
        assert not (tmp_path / "outbox.jsonl").exists()  # nothing leaves before a person approves
        assert dt["output"]["artifacts"][0]["kind"] == "vendor_brief" and dt["output"]["filed"]
        assert pt["usage"]["crustdata"] > 0 and store.usage(ags["pipeline"]["agent_id"])["tasks"] == 1

        pending = store.approvals("pending")
        assert len(pending) == 3 and all(a["preview"]["decision"] == "allow" for a in pending)
        ok = await rt.approve(pending[0]["approval_id"], "Pankaj")
        assert ok["status"] == "sent" and ok["result"]["sent"]
        with pytest.raises(ValueError):
            await rt.approve(pending[0]["approval_id"], "Pankaj")  # no double send
        no = rt.reject(pending[1]["approval_id"], "Pankaj", "not this quarter")
        assert no["status"] == "rejected"
        outbox = [json.loads(x) for x in (tmp_path / "outbox.jsonl").read_text().splitlines()]
        assert [m["to"]["name"] for m in outbox] == [pending[0]["to"]["name"]]
        states = {s.get("approval_id"): s["state"] for s in store.get_task(p["task_id"])["output"]["sends"]}
        assert states[pending[0]["approval_id"]] == "sent" and states[pending[1]["approval_id"]] == "rejected"

        kinds_on_ledger = [e["kind"] for e in ledger.entries()]
        for k in ("task.assigned", "task.started", "task.done", "task.refused", "runtime.approval"):
            assert k in kinds_on_ledger
        assert ledger.verify_chain()[0]
        s = state(rt)
        m = {a["name"]: a for a in s["agents"]}
        assert m["Pipeline"]["metrics"]["sent"] == 1 and m["Pipeline"]["metrics"]["rejected"] == 1
        assert m["Pipeline"]["metrics"]["guard_blocked"] == 1 and m["Pipeline"]["activity"] == "waiting_on_you"
        assert m["Closer"]["metrics"]["refused"] == 1
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_approval_rechecks_at_send_time(tmp_path):
    """Approving a draft for an agent that was suspended in the meantime sends nothing."""
    ags = fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(ags["pipeline"]["agent_id"], "sales_outreach", {}, by="test")
        await until(lambda: status(t["task_id"]) == "done", 120)
        registry.suspend(ags["pipeline"]["agent_id"], "sponsor asked to stop", by="sponsor")
        a = store.approvals("pending")[0]
        res = await rt.approve(a["approval_id"], "someone")
        assert res["status"] == "blocked_at_send" and not res["result"]["sent"]
        assert not (tmp_path / "outbox.jsonl").exists()
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_pause_interrupts_running_work_and_resume_reruns_it(slow_kind):
    ags = fleet()
    aid = ags["diligence"]["agent_id"]
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(aid, "slow", {"n": 400}, by="test")
        await until(lambda: slow_kind["steps"] > 3)
        rt.pause(aid, "employer", "checking its work")
        await until(lambda: status(t["task_id"]) == "queued")
        n = slow_kind["steps"]
        await asyncio.sleep(0.4)
        assert slow_kind["steps"] == n  # it really stopped
        assert "paused" in store.get_task(t["task_id"])["waiting_on"]
        assert state(rt)["agents"][[a["name"] for a in state(rt)["agents"]].index("Diligence")]["activity"] == "paused"
        rt.resume(aid, "employer")
        await until(lambda: slow_kind["steps"] > n)
        assert status(t["task_id"]) == "running"
        rt.cancel(t["task_id"], "employer")
        await until(lambda: status(t["task_id"]) == "cancelled")
        kinds_on_ledger = [e["kind"] for e in ledger.entries()]
        assert {"agent.paused", "agent.resumed", "task.interrupted", "task.cancelled"} <= set(kinds_on_ledger)
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_suspension_from_anywhere_stops_the_agent_mid_task(slow_kind):
    ags = fleet()
    aid = ags["reference"]["agent_id"]
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(aid, "slow", {"n": 400}, by="test")
        q = rt.assign(aid, "slow", {"n": 5}, by="test")
        await until(lambda: slow_kind["steps"] > 3)
        registry.suspend(aid, "sponsor on leave", by="sponsor")  # the registry, not the runtime: it still notices
        await until(lambda: status(t["task_id"]) == "cancelled")
        assert "suspended" in store.get_task(t["task_id"])["error"]
        await asyncio.sleep(0.3)
        assert status(q["task_id"]) == "queued" and "suspended" in store.get_task(q["task_id"])["waiting_on"]
        registry.offboard(aid, "role closed", by="sponsor")
        await until(lambda: status(q["task_id"]) == "cancelled")
        with pytest.raises(ValueError):
            rt.assign(aid, "slow", {}, by="test")
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_budgets_and_scopes_are_enforced(slow_kind):
    ags = fleet()
    with pytest.raises(ValueError, match="outreach.sales"):
        Runtime().assign(ags["diligence"]["agent_id"], "sales_outreach", {}, by="test")  # read-only analyst
    aid = ags["pipeline"]["agent_id"]
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    rt.set_policy(aid, "employer", budget={"tasks_per_day": 1, "crustdata_calls_per_day": 2})
    await rt.start()
    try:
        a = rt.assign(aid, "slow", {"n": 2}, by="test")
        b = rt.assign(aid, "slow", {"n": 2}, by="test")
        await until(lambda: status(a["task_id"]) == "done")
        await asyncio.sleep(0.3)
        assert status(b["task_id"]) == "queued" and "budget" in store.get_task(b["task_id"])["waiting_on"]
        rt.cancel(b["task_id"], "test")
        rt.set_policy(aid, "employer", budget={"tasks_per_day": 10})
        c = rt.assign(aid, "sales_outreach", {}, by="test")  # 4 Person Enrich calls against a cap of 2
        await until(lambda: status(c["task_id"]) in ("failed", "done"), 120)
        tc = store.get_task(c["task_id"])
        assert tc["status"] == "failed" and "crustdata budget" in tc["error"] and tc["usage"]["crustdata"] == 2
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_schedules_run_recurring_work_and_restart_recovers(slow_kind):
    ags = fleet()
    aid = ags["reference"]["agent_id"]
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    s = rt.add_schedule(aid, "slow", {"n": 2}, 60, "employer")
    await until(lambda: any(t.get("schedule_id") == s["schedule_id"] and t["status"] == "done" for t in store.tasks()))
    assert store.schedules()[0]["runs"] == 1 and store.schedules()[0]["next_run_at"] > store.now()
    long = rt.assign(aid, "slow", {"n": 1000}, by="test")
    await until(lambda: status(long["task_id"]) == "running")
    # a crash: the process dies with work in flight
    rt.loop_task.cancel()
    for x in rt.running.values():
        x.cancel()
    await asyncio.sleep(0.1)
    store.update_task(long["task_id"], status="running")
    store.reset_cache()
    rt2 = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt2.start()
    try:
        await until(lambda: store.get_task(long["task_id"])["attempts"] >= 2)
        assert any("restarted" in s["text"] for s in store.get_task(long["task_id"])["steps"])
    finally:
        await rt2.stop()


@pytest.mark.asyncio
async def test_payroll_run_suspends_and_stops_the_agent_whose_sponsor_left(slow_kind):
    ags = fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(ags["closer"]["agent_id"], "slow", {"n": 1000}, by="test")
        await until(lambda: status(t["task_id"]) in ("running", "done"))
        res = await rt.run_payroll("test")
        assert "Closer" in res["suspended"] and res["ledger_entry"]
        await until(lambda: status(t["task_id"]) == "cancelled")
        assert registry.get_agent(ags["closer"]["agent_id"])["status"] == "suspended"
    finally:
        await rt.stop()


def test_http_routes(monkeypatch, slow_kind):
    monkeypatch.setenv("RUNTIME_ENABLED", "1")
    from app.main import app
    ags = fleet()
    with TestClient(app) as c:
        k = c.get("/api/runtime/kinds").json()
        assert {x["kind"] for x in k} >= {"sourcing", "sales_outreach", "vendor_diligence", "reference_check"}
        r = c.post("/api/runtime/tasks", json={"agent_id": ags["diligence"]["agent_id"], "kind": "vendor_diligence",
                                              "input": {"domain": "razorpay.com"}, "by": "Charish"})
        assert r.status_code == 200, r.text
        tid = r.json()["task_id"]
        bad = c.post("/api/runtime/tasks", json={"agent_id": ags["diligence"]["agent_id"], "kind": "sales_outreach"})
        assert bad.status_code == 400 and "outreach.sales" in bad.json()["detail"]
        for _ in range(400):
            if c.get(f"/api/runtime/tasks/{tid}").json()["status"] not in ("queued", "running"):
                break
            asyncio.run(asyncio.sleep(0.05))
        tj = c.get(f"/api/runtime/tasks/{tid}").json()
        assert tj["status"] == "done", (tj["steps"], tj["output"].get("clock_in"))
        st = c.get("/api/runtime/state").json()
        assert st["runtime"]["alive"] and st["totals"]["done_today"] >= 1 and st["ledger"]["chain_ok"]
        aid = ags["pipeline"]["agent_id"]
        assert c.post(f"/api/runtime/agents/{aid}/pause", json={"by": "me", "reason": "audit"}).json()["paused"]
        assert not c.post(f"/api/runtime/agents/{aid}/resume", json={"by": "me"}).json()["paused"]
        pol = c.put(f"/api/runtime/agents/{aid}/policy", json={"require_approval": False, "budget": {"sends_per_day": 3}}).json()
        assert pol["require_approval"] is False and pol["budget"]["sends_per_day"] == 3
        s = c.post("/api/runtime/schedules", json={"agent_id": aid, "kind": "sales_outreach", "every_minutes": 30}).json()
        assert not c.post(f"/api/runtime/schedules/{s['schedule_id']}/toggle").json()["enabled"]
        assert c.delete(f"/api/runtime/schedules/{s['schedule_id']}").status_code == 200
        assert c.put("/api/runtime/payroll", json={"every_minutes": 15}).json()["every_minutes"] == 15


def test_receipts_verify_and_catch_edits():
    import copy
    from app.runtime import receipts
    ledger.append("agent.onboarded", {"agent_id": "agt_x"})
    h = ledger.append("task.done", {"agent_id": "agt_x", "result": "3 cleared"})
    ledger.append("task.started", {"agent_id": "agt_x"})
    r = receipts.issue(h[:12])
    assert r["entry"]["hash"] == h and r["previous"]["seq"] == 0
    assert receipts.verify_receipt(r)["valid"]
    forged = copy.deepcopy(r)
    forged["entry"]["payload"]["result"] = "5 cleared"
    v = receipts.verify_receipt(forged)
    assert not v["valid"] and {c["name"] for c in v["checks"] if c["status"] == "fail"} >= {"entry_hash"}
    resigned = copy.deepcopy(r)
    resigned["head"]["seq"] = 99
    assert not receipts.verify_receipt(resigned)["valid"]  # issuer signature covers the whole receipt


def test_outside_agent_is_governed_end_to_end(monkeypatch, tmp_path):
    """Claude Code (runtime external) gets a task, works it from 'its own machine' over HTTP with signed calls, asks
    before sending, and is stopped by pause and suspend like any in-house agent."""
    import time as _t
    from app.agents.models import Passport
    from app.agents.passport import sign_message
    from app.runtime.external import signed_text
    monkeypatch.setenv("RUNTIME_ENABLED", "1")
    from app.main import app
    ags = {k: a for k, a, _ in onboard(["claude-code", "pipeline"])}
    cc = ags["claude-code"]
    aid, p, key = cc["agent_id"], Passport.model_validate(cc["passport"]), registry.private_key(cc["agent_id"])

    def call(c, action, task_id=None, text="", sig_key=key, **extra):
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from app.agents.passport import _message_bytes
        ts = int(_t.time())
        raw = Ed25519PrivateKey.from_private_bytes(sig_key).sign(_message_bytes(p, signed_text(action, aid, task_id, ts, text)))
        return c.post(f"/api/runtime/agent/{action}", json={"agent_id": aid, "task_id": task_id, "ts": ts, "text": text,
                      "signature": base64.b64encode(raw).decode(), **extra})

    with TestClient(app) as c:
        bad = c.post("/api/runtime/tasks", json={"agent_id": ags["pipeline"]["agent_id"], "kind": "assignment",
                                                 "input": {"instructions": "x"}})
        assert bad.status_code == 400  # in-house agents don't take outside-agent tasks
        t = c.post("/api/runtime/tasks", json={"agent_id": aid, "kind": "assignment",
                                               "input": {"instructions": "Draft a note to Vinod at Fam and ask to send it"}}).json()
        asyncio.run(asyncio.sleep(0.3))
        assert "pick it up" in c.get(f"/api/runtime/tasks/{t['task_id']}").json()["waiting_on"]
        other = registry.private_key(ags["pipeline"]["agent_id"])
        assert call(c, "claim", sig_key=other).status_code == 401  # someone else's key
        got = call(c, "claim").json()
        assert got["task"]["task_id"] == t["task_id"] and "Vinod" in got["task"]["input"]["instructions"]
        assert call(c, "progress", t["task_id"], "drafting the note").json()["continue"]

        body = "Hi Vinod, your work at Fam caught our eye. Open to a chat about a backend role?"
        r = c.post("/api/runtime/agent/send", json={"agent_id": aid, "task_id": t["task_id"], "body": body, "scope": "outreach.hiring",
                   "to": {"name": "Vinod Sonagara", "profile_url": "https://www.linkedin.com/in/vinod-sonagara", "company": "Fam"},
                   "signature": sign_message(p, key, body)}).json()
        assert r["decision"] == "allow" and r["pending_approval"] and not r["sent"]
        lie = "Hi Vinod, congrats on 5 years at Fam! Open to a chat?"
        r2 = c.post("/api/runtime/agent/send", json={"agent_id": aid, "task_id": t["task_id"], "body": lie, "scope": "outreach.hiring",
                    "to": {"name": "Vinod Sonagara", "profile_url": "https://www.linkedin.com/in/vinod-sonagara", "company": "Fam"},
                    "signature": sign_message(p, key, lie)}).json()
        assert r2["decision"] == "block" and not r2["pending_approval"]
        assert not (tmp_path / "outbox.jsonl").exists()

        c.post(f"/api/runtime/agents/{aid}/pause", json={"by": "me"})
        asyncio.run(asyncio.sleep(0.3))
        stop = call(c, "progress", t["task_id"], "still going").json()
        assert stop["stop"] and "paused" in stop["reason"]
        assert c.get(f"/api/runtime/tasks/{t['task_id']}").json()["status"] == "queued"
        assert call(c, "claim").json()["stop"]
        c.post(f"/api/runtime/agents/{aid}/resume", json={"by": "me"})
        assert call(c, "claim").json()["task"]["task_id"] == t["task_id"]
        done = call(c, "complete", t["task_id"], "Drafted the note; one clean draft is waiting for approval.").json()
        assert done["recorded"]
        tj = c.get(f"/api/runtime/tasks/{t['task_id']}").json()
        assert tj["status"] == "done" and tj["output"]["artifacts"][0]["kind"] == "report"

        t2 = c.post("/api/runtime/tasks", json={"agent_id": aid, "kind": "assignment", "input": {"instructions": "again"}}).json()
        assert call(c, "claim").json()["task"]["task_id"] == t2["task_id"]
        c.post(f"/api/runtime/agents/{aid}/suspend", json={"by": "me", "reason": "audit"})
        asyncio.run(asyncio.sleep(0.3))
        assert c.get(f"/api/runtime/tasks/{t2['task_id']}").json()["status"] == "cancelled"
        assert call(c, "progress", t2["task_id"], "hello?").json()["stop"]
        kinds_on_ledger = [e["kind"] for e in ledger.entries()]
        assert kinds_on_ledger.count("task.started") >= 2 and "task.cancelled" in kinds_on_ledger


def test_hire_scheduler_and_schedule_interviews_from_a_shortlist(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_ENABLED", "1")
    from app.main import app
    fleet()
    people = ("Vinod Sonagara | https://www.linkedin.com/in/vinod-sonagara | Fam\n"
              "Shivank Verma | https://www.linkedin.com/in/shivankverma | PulseTrader")  # stale: he left PulseTrader
    with TestClient(app) as c:
        tpl = c.get("/api/runtime/templates").json()
        assert tpl[0]["name"] == "Scheduler" and not tpl[0]["hired"]
        h = c.post("/api/runtime/hire", json={"key": "scheduler"}).json()
        assert h["decision"] == "allow"
        assert c.post("/api/runtime/hire", json={"key": "scheduler"}).status_code == 409
        sid = h["agent"]["agent_id"]
        t = c.post("/api/runtime/tasks", json={"agent_id": sid, "kind": "interview_scheduling", "input": {
            "candidates": people, "slots": "Tue 4 Nov, 10:00 IST\nTue 4 Nov, 15:00 IST\nWed 5 Nov, 11:30 IST",
            "role": "Senior Backend Engineer", "interviewer": "Pankaj Savaliya"}}).json()
        for _ in range(400):
            tj = c.get(f"/api/runtime/tasks/{t['task_id']}").json()
            if tj["status"] not in ("queued", "running"):
                break
            asyncio.run(asyncio.sleep(0.05))
        assert tj["status"] == "done", (tj["error"], tj["steps"][-5:])
        plan = {p["candidate"]: p for p in tj["output"]["schedule"]}
        assert plan["Vinod Sonagara"]["invite"] == "waiting for your approval"
        assert plan["Shivank Verma"]["invite"] == "blocked"  # Send Guard: no longer at PulseTrader
        assert plan["Vinod Sonagara"]["slots"] != plan["Shivank Verma"]["slots"]
        assert "BEGIN:VCALENDAR" in tj["output"]["artifacts"][0]["content"]
        assert not (tmp_path / "outbox.jsonl").exists()


@pytest.mark.asyncio
async def test_transient_failure_is_retried_once(monkeypatch):
    calls = {"n": 0}

    async def flaky(ctx, inp):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("Crustdata reset the connection")
        return {"ok": True, "summary": "second try worked"}

    monkeypatch.setitem(kinds.KINDS, "flaky", {"label": "Flaky", "scope": "data.read", "fields": [], "handler": flaky,
                                               "description": "", "agent_hint": None})
    ags = fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(ags["diligence"]["agent_id"], "flaky", {}, by="test")
        await until(lambda: status(t["task_id"]) == "done")
        tt = store.get_task(t["task_id"])
        assert tt["attempts"] == 2 and tt["result"] == "second try worked"
        assert "task.retry" in [e["kind"] for e in ledger.entries()]
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_launched_agent_that_cannot_start_fails_the_task(monkeypatch, tmp_path):
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho 'Failed to authenticate: OAuth session expired'\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv("AGAXES_LAUNCH_CLAUDE", "1")
    ags = {k: a for k, a, _ in onboard(["claude-code"])}
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(ags["claude-code"]["agent_id"], "assignment", {"instructions": "say hi"}, by="test")
        await until(lambda: status(t["task_id"]) == "failed", 20)
        assert "OAuth session expired" in store.get_task(t["task_id"])["error"]
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_edit_then_approve_resigns_and_reguards(tmp_path):
    ags = fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(ags["pipeline"]["agent_id"], "sales_outreach", {}, by="test")
        await until(lambda: status(t["task_id"]) == "done", 120)
        a, b = store.approvals("pending")[:2]
        first = a["to"]["name"].split()[0]
        ok = await rt.approve(a["approval_id"], "Pankaj", body=f"Hi {first}, quick question: open to a 15-minute call this week?\n\nPipeline")
        assert ok["status"] == "sent" and ok["edited_by"] == "Pankaj" and ok["original_body"] != ok["body"]
        bad = await rt.approve(b["approval_id"], "Pankaj", body=f"Hi {b['to']['name'].split()[0]}, congrats on 9 years at {b['to']['company']}!")
        assert bad["status"] == "blocked_at_send"  # the guard checks the edited text from scratch
        outbox = [json.loads(x) for x in (tmp_path / "outbox.jsonl").read_text().splitlines()]
        assert len(outbox) == 1 and "quick question" in outbox[0]["body"]
        e = [x for x in ledger.entries() if x["kind"] == "runtime.approval"]
        assert e[0]["payload"]["edited"] is True
    finally:
        await rt.stop()
