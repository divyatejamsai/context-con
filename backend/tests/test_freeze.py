"""The emergency stop (app/runtime/freeze.py): one click freezes an agent, a sponsor's agents or every agent, and shows
what each of them touched in the last 24 hours. Restore brings them back only after a fresh sponsor check."""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.agents import ledger, registry, seal
from app.agents.api import crustdata
from app.fleet.demo import onboard
from app.runtime import freeze as fz
from app.runtime import kinds, store
from app.runtime.supervisor import Runtime

TODAY = date(2026, 10, 31)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    for var, name in (("AGENTS_PATH", "agents.json"), ("LEDGER_PATH", "ledger.jsonl"), ("ISSUER_KEY_PATH", "issuer.key"),
                      ("OUTBOX_PATH", "outbox.jsonl"), ("RUNTIME_PATH", "runtime.json"), ("SEALS_PATH", "seals.jsonl")):
        monkeypatch.setenv(var, str(tmp_path / name))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.delenv("COUNTERSIGN_ADMIN_TOKEN", raising=False)
    store.reset_cache()
    from app.agents import api as agents_api
    from app.runtime import worker
    monkeypatch.setattr(agents_api, "_client", None)
    monkeypatch.setattr(worker, "_mcp_mod", None)
    yield tmp_path
    store.reset_cache()


@pytest.fixture
def slow_kind(monkeypatch):
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
async def test_freeze_one_agent_stops_everything_and_turns_its_verify_links_red(slow_kind):
    ags = fleet()
    pid = ags["pipeline"]["agent_id"]
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(pid, "sales_outreach", {}, by="test")
        await until(lambda: status(t["task_id"]) == "done", 120)
        pending = store.approvals("pending", pid)
        assert len(pending) == 3
        sent = await rt.approve(pending[0]["approval_id"], "Pankaj")
        assert sent["status"] == "sent"
        sid = seal.latest(pid, seal.sha(pending[0]["body"]))["seal_id"]
        assert (await seal.verify(sid))["verdict"] != "invalid"

        rt.set_policy(pid, "test", budget={"tasks_per_day": 50})
        long = rt.assign(pid, "slow", {"n": 2000}, by="test")
        queued = rt.assign(pid, "slow", {"n": 2}, by="test")
        sch = rt.add_schedule(pid, "slow", {"n": 2}, 60, "test")
        await until(lambda: slow_kind["steps"] > 3)

        pre = fz.preview("agent", pid)
        assert pre["will"]["suspend"] == ["Pipeline"] and pre["will"]["pending_approvals"] == 2
        f = fz.freeze(rt, "agent", pid, "it emailed the wrong list", "admin@grewon.com")
        assert f["status"] == "active" and [a["name"] for a in f["agents"]] == ["Pipeline"]

        await until(lambda: status(long["task_id"]) == "cancelled")
        n = slow_kind["steps"]
        await asyncio.sleep(0.3)
        assert slow_kind["steps"] == n  # it really stopped
        assert "emergency stop" in store.get_task(long["task_id"])["error"]
        assert status(queued["task_id"]) == "cancelled"
        assert not store.approvals("pending", pid)
        assert {a["status"] for a in store.approvals(agent_id=pid) if a["approval_id"] != pending[0]["approval_id"]} == {"expired"}
        assert not next(s for s in store.schedules() if s["schedule_id"] == sch["schedule_id"])["enabled"]
        ag = registry.get_agent(pid)
        assert ag["status"] == "suspended" and ag["suspended_by"].startswith(f"emergency stop {f['freeze_id']}")
        assert ledger.is_revoked(pid)
        v = await seal.verify(sid)
        assert v["verdict"] == "invalid" and any(c["name"] == "agent_in_good_standing" and c["status"] == "fail" for c in v["checks"])
        late = rt.assign(pid, "slow", {"n": 2}, by="test")  # new work waits: a frozen agent never starts it
        await asyncio.sleep(0.3)
        assert status(late["task_id"]) == "queued" and "suspended" in store.get_task(late["task_id"])["waiting_on"]
        # the other agents are untouched
        assert registry.get_agent(ags["diligence"]["agent_id"])["status"] == "active"

        # what it touched in the last 24 hours, frozen at stop time
        b = next(a for a in f["blast"]["agents"] if a["agent_id"] == pid)
        assert len(b["messages_sent"]) == 1 and b["messages_sent"][0]["to"]["name"] == pending[0]["to"]["name"]
        assert len(b["people"]) == 1 and b["data"]["crustdata_calls"] > 0
        assert {x["status"] for x in b["approvals"]} == {"sent", "pending"}
        assert f["blast"]["totals"]["messages_sent"] == 1 and f["blast"]["totals"]["pending_approvals"] == 2

        started = ledger.entries(kind="freeze.started")
        assert len(started) == 1 and started[0]["payload"]["agent_ids"] == [pid]
        assert set(started[0]["payload"]["cancelled_approvals"]) == {a["approval_id"] for a in pending[1:]}
        assert ledger.verify_chain()[0]
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_restore_needs_a_passing_check_and_can_bring_the_work_back(slow_kind):
    ags = fleet()
    pid, rid = ags["pipeline"]["agent_id"], ags["reference"]["agent_id"]
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(pid, "sales_outreach", {}, by="test")
        await until(lambda: status(t["task_id"]) == "done", 120)
        long = rt.assign(rid, "slow", {"n": 2000}, by="test")
        await until(lambda: slow_kind["steps"] > 3)
        registry.suspend(ags["diligence"]["agent_id"], "on leave", by="sponsor")  # already suspended before the stop

        f = fz.freeze(rt, "all", None, "suspected prompt injection", "admin")
        assert {a["name"] for a in f["agents"]} == {"Sourced", "Pipeline", "Diligence", "Reference", "Closer"}
        assert all(registry.get_agent(a["agent_id"])["status"] == "suspended" for a in f["agents"])
        await until(lambda: status(long["task_id"]) == "cancelled")
        assert fz.active_for(pid)["freeze_id"] == f["freeze_id"]

        r = await fz.restore(rt, f["freeze_id"], "admin", crustdata(), bring_back=True)
        out = {a["name"]: a["outcome"] for a in r["agents"]}
        assert out["Pipeline"] == out["Reference"] == out["Sourced"] == "restored"
        assert out["Closer"] == "still_suspended"          # its sponsor left: a fresh check fails, so it stays out
        assert out["Diligence"] == "was_suspended_before"  # the stop never reinstates what it didn't suspend
        assert registry.get_agent(ags["diligence"]["agent_id"])["status"] == "suspended"
        assert registry.get_agent(pid)["status"] == "active" and not ledger.is_revoked(pid)
        assert len(store.approvals("pending", pid)) == 3   # the pulled drafts are back in front of a person
        assert r["requeued_tasks"] and store.get_task(r["requeued_tasks"][0])["agent_id"] == rid
        await until(lambda: slow_kind["steps"] > 0 and status(r["requeued_tasks"][0]) == "running")
        assert r["status"] == "lifted" and ledger.entries(kind="freeze.restored")
        with pytest.raises(ValueError):
            await fz.restore(rt, f["freeze_id"], "admin", crustdata())
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_freeze_by_sponsor_and_overlapping_stops():
    ags = fleet()
    f1 = fz.freeze(None, "agent", ags["sourced"]["agent_id"], "check", "admin")
    pankaj = registry.get_agent(ags["pipeline"]["agent_id"])["passport"]["sponsor"]
    f2 = fz.freeze(None, "sponsor", pankaj["profile_url"], "Pankaj's account was phished", "admin")
    assert {a["name"] for a in f2["agents"]} == {"Sourced", "Pipeline"}
    assert {a["name"]: a["prior_status"] for a in f2["agents"]} == {"Sourced": "suspended", "Pipeline": "active"}
    assert registry.get_agent(ags["diligence"]["agent_id"])["status"] == "active"
    # lifting the sponsor stop doesn't free Sourced: the first stop still holds it
    r2 = await fz.restore(None, f2["freeze_id"], "admin", crustdata())
    assert {a["name"]: a["outcome"] for a in r2["agents"]} == {"Sourced": "was_suspended_before", "Pipeline": "restored"}
    assert registry.get_agent(ags["sourced"]["agent_id"])["status"] == "suspended"
    r1 = await fz.restore(None, f1["freeze_id"], "admin", crustdata())
    assert r1["agents"][0]["outcome"] == "restored"
    sp = fz.sponsors()
    assert sp[0]["name"] == pankaj["name"] and len(sp[0]["agents"]) == 2
    with pytest.raises(ValueError):
        fz.freeze(None, "sponsor", "nobody at all", "x", "admin")


def test_http_routes(monkeypatch, slow_kind):
    monkeypatch.setenv("RUNTIME_ENABLED", "1")
    from app.main import app
    ags = fleet()
    rid = ags["reference"]["agent_id"]
    with TestClient(app) as c:
        p = c.post("/api/runtime/freeze/preview", json={"scope": "all"})
        assert p.status_code == 200, p.text
        assert len(p.json()["agents"]) == 5 and "totals" in p.json()["blast"]
        assert c.post("/api/runtime/freeze/preview", json={"scope": "agent", "target": "nope"}).status_code == 404
        f = c.post("/api/runtime/freeze", json={"scope": "agent", "target": "Reference", "reason": "test"})
        assert f.status_code == 200, f.text
        fid = f.json()["freeze_id"]
        o = c.get("/api/runtime/freeze").json()
        assert [x["freeze_id"] for x in o["active"]] == [fid] and o["sponsors"]
        b = c.get(f"/api/runtime/freeze/blast?agent_id={rid}&hours=24").json()
        assert [a["name"] for a in b["agents"]] == ["Reference"]
        st = c.get("/api/runtime/state").json()
        assert {a["name"]: a["status"] for a in st["agents"]}["Reference"] == "suspended"
        r = c.post(f"/api/runtime/freeze/{fid}/restore", json={"bring_back": True})
        assert r.status_code == 200, r.text
        assert r.json()["agents"][0]["outcome"] == "restored"
        assert c.post(f"/api/runtime/freeze/{fid}/restore", json={}).status_code == 400
        assert c.post("/api/runtime/freeze/frz_nope/restore", json={}).status_code == 404


@pytest.mark.asyncio
async def test_a_frozen_agent_comes_back_only_by_lifting_the_stop():
    ags = fleet()
    pid = ags["pipeline"]["agent_id"]
    f = fz.freeze(None, "agent", pid, "check", "admin")
    with pytest.raises(registry.Frozen, match=f["freeze_id"]):
        await registry.reinstate(pid, crustdata())
    assert registry.get_agent(pid)["status"] == "suspended" and ledger.is_revoked(pid)
    # an agent suspended by hand before the stop isn't held by it: reinstating it from its page still works
    did = ags["diligence"]["agent_id"]
    registry.suspend(did, "on leave", by="sponsor")
    f2 = fz.freeze(None, "all", None, "incident", "admin")
    assert fz.holders(did) == [] and fz.holders(pid) == [f["freeze_id"]]
    agent, _ = await registry.reinstate(did, crustdata())
    assert agent["status"] == "active"
    await fz.restore(None, f2["freeze_id"], "admin", crustdata())
    assert registry.get_agent(pid)["status"] == "suspended"  # the first stop still holds it
    await fz.restore(None, f["freeze_id"], "admin", crustdata())
    assert registry.get_agent(pid)["status"] == "active"


def test_reinstate_routes_refuse_a_frozen_agent(monkeypatch):
    monkeypatch.setenv("RUNTIME_ENABLED", "0")
    from app.main import app
    ags = fleet()
    rid = ags["reference"]["agent_id"]
    with TestClient(app) as c:
        fid = c.post("/api/runtime/freeze", json={"scope": "agent", "target": rid, "reason": "t"}).json()["freeze_id"]
        r = c.post(f"/api/agents/{rid}/reinstate")
        assert r.status_code == 409 and "lift the stop" in r.json()["detail"]
        assert c.post("/api/passport/reinstate", json={"agent_id": rid, "reason": "x"}).status_code == 409
        assert ledger.is_revoked(rid)
        assert c.post(f"/api/runtime/freeze/{fid}/restore", json={}).json()["agents"][0]["outcome"] == "restored"
        assert c.post(f"/api/agents/{rid}/reinstate").status_code == 400  # active now: nothing to reinstate
