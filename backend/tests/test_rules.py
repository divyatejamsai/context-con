"""Company rules set without code (app/rules): templates and sentences, versions and the ledger, who may edit them,
and enforcement at action time: offers over a threshold need two different approvers, never-contact lists in Send
Guard, quiet hours that hold sends, and daily caps."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import ledger, registry
from app.agents.api import crustdata
from app.fleet.demo import onboard
from app.rules import engine
from app.runtime import store
from app.runtime.kinds import hire_template
from app.runtime.supervisor import Runtime
from app.runtime.worker import execute_approval

TODAY = date(2026, 10, 31)
CANDIDATE = "Pankaj Savaliya | https://www.linkedin.com/in/pankaj-savaliya | Acme"
PW = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    for var, name in (("AGENTS_PATH", "agents.json"), ("LEDGER_PATH", "ledger.jsonl"), ("ISSUER_KEY_PATH", "issuer.key"),
                      ("OUTBOX_PATH", "outbox.jsonl"), ("RUNTIME_PATH", "runtime.json")):
        monkeypatch.setenv(var, str(tmp_path / name))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.delenv("COUNTERSIGN_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("AGAXES_REQUIRE_LOGIN", raising=False)
    store.reset_cache()
    from app.agents import api as agents_api
    from app.runtime import worker
    monkeypatch.setattr(agents_api, "_client", None)
    monkeypatch.setattr(worker, "_mcp_mod", None)
    yield tmp_path
    store.reset_cache()


async def until(cond, timeout=60.0):
    import asyncio
    t = 0.0
    while not cond():
        await asyncio.sleep(0.05)
        t += 0.05
        if t > timeout:
            raise AssertionError("timed out waiting")


def fleet() -> dict:
    return {k: a for k, a, _ in onboard(["sourced", "pipeline", "diligence", "reference", "closer"])}


def kinds_on_ledger() -> list[str]:
    return [e["kind"] for e in ledger.entries()]


def enforced() -> list[dict]:
    return [e["payload"] for e in ledger.entries(kind="rule.enforced")]


# ---- templates, money, sentences -----------------------------------------------------------------------------

def test_money_is_read_the_way_recruiters_write_it():
    assert engine.parse_money("₹42 LPA fixed + ESOPs")[0] == 4_200_000
    assert engine.parse_money("₹30L")[0] == 3_000_000
    assert engine.parse_money("35 lakh")[0] == 3_500_000
    assert engine.parse_money("3,500,000")[0] == 3_500_000
    assert engine.parse_money("₹1.2 Cr")[0] == 12_000_000
    assert engine.parse_money("₹28-32 LPA")[0] == 3_200_000  # a range counts at its top end
    assert engine.parse_money("42 LPA + 0.5% ESOPs over 4 years")[0] == 4_200_000
    amount, note = engine.parse_money("$120k")
    assert amount == 120_000 * engine.USD_INR and "dollars" in note
    assert engine.parse_money("as agreed in your interviews")[0] is None
    assert engine.fmt_inr(3_000_000) == "₹30L" and engine.fmt_inr(12_000_000) == "₹1.2Cr"


def test_every_template_has_a_plain_sentence_and_bad_input_says_why():
    s = {t["type"]: t["example_sentence"] for t in engine.templates()}
    assert s["offer_approvers"] == "Offers over ₹30L need 2 approvers"
    assert s["quiet_hours"].startswith("No outreach between 20:00 and 08:00 IST")
    assert "contact people at our clients" in s["blocked_companies"]
    assert s["daily_cap"] == "Each AI employee may send at most 20 messages a day"
    assert engine.normalize("quiet_hours", {"start": "8pm", "end": "8am"})["start"] == "20:00"
    for rtype, params, why in (("offer_approvers", {"threshold": "lots"}, "amount"),
                               ("offer_approvers", {"approvers": 1}, "between 2 and 5"),
                               ("quiet_hours", {"start": "25:00"}, "time"),
                               ("blocked_companies", {"companies": []}, "at least one"),
                               ("nope", {}, "unknown rule type")):
        with pytest.raises(engine.RuleError, match=why):
            engine.normalize(rtype, params)


# ---- versions and the ledger ---------------------------------------------------------------------------------

def test_rules_are_versioned_and_every_change_is_on_the_ledger():
    ags = fleet()
    r = engine.create("blocked_companies", {"list_name": "our clients", "companies": "Razorpay\nZepto"},
                      agents=[ags["sourced"]["agent_id"]], by="admin@acme.io", workspace_id=None)
    assert r["version"] == 1 and r["sentence"] == "Sourced may never contact people at our clients (Razorpay and Zepto)"
    r = engine.update(r["rule_id"], by="admin@acme.io", params={"companies": ["Razorpay", "Zepto", "Swiggy"]})
    assert r["version"] == 2 and "Swiggy" in r["sentence"]
    assert engine.update(r["rule_id"], by="admin@acme.io", params={"companies": ["Razorpay", "Zepto", "Swiggy"]})["version"] == 2
    r = engine.update(r["rule_id"], by="owner@acme.io", enabled=False, note="client contract ended")
    assert r["version"] == 3 and not r["enabled"]
    r = engine.delete(r["rule_id"], by="owner@acme.io")
    assert r["deleted"] and [h["change"] for h in r["history"]] == ["created", "updated", "disabled", "deleted"]
    assert r["history"][0]["params"]["companies"] == ["Razorpay", "Zepto"]  # the old version is kept as it was
    assert engine.rules() == [] and len(engine.rules(include_deleted=True)) == 1
    k = kinds_on_ledger()
    for kind in ("rule.created", "rule.updated", "rule.disabled", "rule.deleted"):
        assert kind in k
    upd = ledger.entries(kind="rule.updated")[0]["payload"]
    assert upd["before"].endswith("(Razorpay and Zepto)") and "Swiggy" in upd["sentence"] and upd["changed"] == ["params"]
    assert ledger.verify_chain()[0]


def test_a_rule_for_one_agent_does_not_touch_another():
    ags = fleet()
    engine.create("blocked_companies", {"companies": ["Acme"]}, agents=[ags["sourced"]["agent_id"]], by="t",
                  workspace_id=None)
    assert engine.send_hits(ags["sourced"], {"name": "A", "company": "Acme Pvt Ltd"})[0]["effect"] == "block"
    assert engine.send_hits(ags["pipeline"], {"name": "A", "company": "Acme"}) == []
    assert engine.send_hits(ags["sourced"], {"name": "B", "company": "Globex"}) == []
    assert engine.send_hits(ags["sourced"], {"name": "C", "company": "", "email": "c@acme.com"}, "outreach.hiring") == []
    engine.create("blocked_companies", {"companies": ["globex.com"]}, by="t", workspace_id=None)
    assert engine.send_hits(ags["pipeline"], {"name": "D", "email": "d@globex.com"})[0]["detail"].startswith("D works at")


# ---- offers over a threshold need two different people -------------------------------------------------------

async def _offer(rt, offer_agent, comp: str) -> dict:
    t = rt.assign(offer_agent["agent_id"], "offer_letter", {"candidate": CANDIDATE, "role": "Senior Backend Engineer",
                                                             "compensation": comp}, by="test")
    await until(lambda: store.get_task(t["task_id"])["status"] not in ("queued", "running"), 60)
    task = store.get_task(t["task_id"])
    assert task["status"] == "done", task
    return task


@pytest.mark.asyncio
async def test_offer_over_threshold_needs_two_different_approvers():
    fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        offer_agent, _ = await hire_template("offer", rt.client)
        rule = engine.create("offer_approvers", {"threshold": "₹30L", "approvers": 2}, by="owner", workspace_id=None)
        task = await _offer(rt, offer_agent, "₹42 LPA fixed + ESOPs")
        a = store.get_approval(task["output"]["offer"]["approval_id"])
        assert a["approvals_needed"] == 2 and a["rules"][0]["rule_id"] == rule["rule_id"]
        assert "₹42L is over ₹30L" in a["rules"][0]["detail"]

        first = await execute_approval(a["approval_id"], "recruiter@acme.io", rt.mcp)
        assert first["status"] == "pending" and [x["by"] for x in first["approvals"]] == ["recruiter@acme.io"]
        assert store.get_task(task["task_id"])["output"]["offer"]["state"].startswith("approved by 1 of 2")
        with pytest.raises(ValueError, match="already approved"):
            await execute_approval(a["approval_id"], "Recruiter@acme.io", rt.mcp)  # same person, any case
        done = await execute_approval(a["approval_id"], "head-of-people@acme.io", rt.mcp)
        assert done["status"] == "signed" and done["result"]["signed"]
        assert len(done["approvals"]) == 2

        rows = [e["payload"] for e in ledger.entries(kind="runtime.approval")]
        assert rows[0]["outcome"] == "needs_more_approvers" and rows[0]["needed"] == 2
        hits = enforced()
        assert {h["outcome"] for h in hits} >= {"needs 2 approvers", "waiting for approver 2 of 2"}
        assert all(h["sentence"] == "Offers over ₹30L need 2 approvers" and h["version"] == 1 for h in hits)
        signed = ledger.entries(kind="offer.signed")[-1]["payload"]
        assert signed["approvers"] == ["recruiter@acme.io", "head-of-people@acme.io"]
        assert signed["rules"][0]["sentence"] == "Offers over ₹30L need 2 approvers"
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_offer_under_threshold_needs_one_and_a_rule_added_later_still_counts():
    fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        offer_agent, _ = await hire_template("offer", rt.client)
        engine.create("offer_approvers", {"threshold": "₹30L", "approvers": 2}, by="owner", workspace_id=None)
        small = await _offer(rt, offer_agent, "₹24 LPA")
        a = store.get_approval(small["output"]["offer"]["approval_id"])
        assert a["approvals_needed"] == 1 and a["rules"] == []
        assert (await execute_approval(a["approval_id"], "one@acme.io", rt.mcp))["status"] == "signed"

        engine.update(engine.rules()[0]["rule_id"], by="owner", enabled=False)
        big = await _offer(rt, offer_agent, "₹50 LPA")
        b = store.get_approval(big["output"]["offer"]["approval_id"])
        assert b["approvals_needed"] == 1  # drafted while the rule was off
        engine.update(engine.rules()[0]["rule_id"], by="owner", enabled=True, params={"approvers": 3})
        r = await execute_approval(b["approval_id"], "one@acme.io", rt.mcp)
        assert r["status"] == "pending" and r["approvals_needed"] == 3  # rules apply when the person acts
        r = await execute_approval(b["approval_id"], "two@acme.io", rt.mcp)
        assert r["status"] == "pending"
        assert (await execute_approval(b["approval_id"], "three@acme.io", rt.mcp))["status"] == "signed"

        unreadable = await _offer(rt, offer_agent, "")  # "as agreed": fail closed, the rule applies
        c = store.get_approval(unreadable["output"]["offer"]["approval_id"])
        assert c["approvals_needed"] == 3 and "couldn't read an amount" in c["rules"][0]["detail"]
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_offer_without_start_date_on_a_live_server_runtime():
    """The API server's runtime has no fixed `today`: an offer with no start date used to crash on None + timedelta."""
    fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False)
    await rt.start()
    try:
        offer_agent, _ = await hire_template("offer", rt.client)
        task = await _offer(rt, offer_agent, "₹42 LPA")
        assert task["output"]["offer"]["start_date"]
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_editing_a_big_offer_restarts_the_count():
    fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        offer_agent, _ = await hire_template("offer", rt.client)
        engine.create("offer_approvers", {"threshold": "₹30L", "approvers": 2}, by="owner", workspace_id=None)
        task = await _offer(rt, offer_agent, "₹42 LPA")
        aid = task["output"]["offer"]["approval_id"]
        await execute_approval(aid, "a@acme.io", rt.mcp)
        edited = store.get_approval(aid)["body"] + "\n\nPS: welcome aboard."
        r = await execute_approval(aid, "b@acme.io", rt.mcp, edited)
        assert r["status"] == "pending" and [x["by"] for x in r["approvals"]] == ["b@acme.io"] and r["body"] == edited
        done = await execute_approval(aid, "a@acme.io", rt.mcp)  # a approves the new text
        assert done["status"] == "signed" and "welcome aboard" in store.get_task(task["task_id"])["output"]["offer"]["letter"]
    finally:
        await rt.stop()


# ---- outreach: never-contact lists, quiet hours, daily caps ---------------------------------------------------

@pytest.mark.asyncio
async def test_never_contact_list_blocks_in_send_guard_and_names_the_rule(tmp_path):
    ags = fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(ags["pipeline"]["agent_id"], "sales_outreach", {}, by="test")
        await until(lambda: store.get_task(t["task_id"])["status"] == "done", 120)
        pending = store.approvals("pending")
        assert pending
        target = pending[0]["to"]["company"]
        rule = engine.create("blocked_companies", {"list_name": "our clients", "companies": [target]},
                             agents=[ags["pipeline"]["agent_id"]], by="owner", workspace_id=None)

        # a draft written before the rule: approving it now is blocked at send time, by the rule
        res = await rt.approve(pending[0]["approval_id"], "owner")
        assert res["status"] == "blocked_at_send" and not res["result"]["sent"]
        rc = [c for c in res["result"]["checks"] if c["name"] == "company_rule"]
        assert rc and rc[0]["status"] == "fail" and "our clients" in rc[0]["detail"] and "(v1)" in rc[0]["detail"]
        assert not (tmp_path / "outbox.jsonl").exists()

        # a new run: Send Guard blocks the draft itself, nothing reaches the approval inbox for that company
        before = len(store.approvals("pending"))
        t2 = rt.assign(ags["pipeline"]["agent_id"], "sales_outreach", {}, by="test")
        await until(lambda: store.get_task(t2["task_id"])["status"] == "done", 120)
        sends = [s for s in store.get_task(t2["task_id"])["output"]["sends"] if s["to"]["company"] == target]
        assert sends and all(s["state"] == "blocked" for s in sends)
        assert any(c["name"] == "company_rule" for s in sends for c in s["checks"])
        assert not [a for a in store.approvals("pending")[before:] if a["to"]["company"] == target]
        hits = [h for h in enforced() if h["rule_id"] == rule["rule_id"]]
        assert hits and all(h["agent_id"] == ags["pipeline"]["agent_id"] and h["to"]["company"] == target for h in hits)
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_quiet_hours_hold_sends_until_morning(tmp_path, monkeypatch):
    ags = fleet()
    night = datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc)  # 21:30 IST
    monkeypatch.setattr(engine, "_now", lambda: night)
    pid = ags["pipeline"]["agent_id"]
    store.set_policy(pid, require_approval=False)  # even an agent allowed to send on its own is held
    engine.create("quiet_hours", {"start": "20:00", "end": "08:00", "tz": "Asia/Kolkata", "effect": "hold"}, by="owner",
                  workspace_id=None)
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(pid, "sales_outreach", {}, by="test")
        await until(lambda: store.get_task(t["task_id"])["status"] == "done", 120)
        held = store.approvals("pending")
        assert held and all(a["rules"][0]["type"] == "quiet_hours" for a in held)
        assert not (tmp_path / "outbox.jsonl").exists()
        with pytest.raises(ValueError, match="Held by rule .*outreach opens at 08:00 IST"):
            await rt.approve(held[0]["approval_id"], "owner")
        assert store.get_approval(held[0]["approval_id"])["status"] == "pending"  # still in the inbox

        monkeypatch.setattr(engine, "_now", lambda: datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc))  # 09:30 IST
        res = await rt.approve(held[0]["approval_id"], "owner")
        assert res["status"] == "sent", res
        outs = {h["outcome"] for h in enforced()}
        assert {"held in the approval inbox", "approval refused for now; still pending"} <= outs
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_daily_caps_hold_tasks_and_stop_sends(tmp_path):
    ags = fleet()
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(ags["pipeline"]["agent_id"], "sales_outreach", {}, by="test")
        await until(lambda: store.get_task(t["task_id"])["status"] == "done", 120)
        engine.create("daily_cap", {"metric": "sends", "limit": 0, "per": "together"}, by="owner", workspace_id=None)
        res = await rt.approve(store.approvals("pending")[0]["approval_id"], "owner")
        assert res["status"] == "blocked_at_send" and "All AI employees together may send at most 0" in res["result"]["error"]

        cap = engine.create("daily_cap", {"metric": "tasks", "limit": 1, "per": "each"},
                            agents=[ags["pipeline"]["agent_id"]], by="owner", workspace_id=None)
        t2 = rt.assign(ags["pipeline"]["agent_id"], "sales_outreach", {}, by="test")
        await until(lambda: "Pipeline may start at most 1 tasks a day" in (store.get_task(t2["task_id"])["waiting_on"] or ""), 10)
        assert store.get_task(t2["task_id"])["status"] == "queued"
        engine.update(cap["rule_id"], by="owner", params={"limit": 5})
        await until(lambda: store.get_task(t2["task_id"])["status"] != "queued", 30)
        assert sum(h["action"] == "start_task" for h in enforced()) == 1  # once, not every tick
    finally:
        await rt.stop()


# ---- the console API: who may edit, what each company sees -----------------------------------------------------

@pytest.fixture
def c(tmp_path, monkeypatch):
    from app.accounts import api as auth_api
    from app.accounts.store import AccountStore

    async def no_identify(domain):
        return None
    monkeypatch.setattr(auth_api, "identify_company", no_identify)
    monkeypatch.setenv("RUNTIME_ENABLED", "0")
    auth_api.reset_store(AccountStore(tmp_path / "accounts.db"))
    from app.main import app
    yield TestClient(app)
    auth_api.reset_store(None)


def signup(c, email, company="Acme") -> str:
    r = c.post("/api/auth/signup", json={"email": email, "password": PW, "full_name": email.split("@")[0].title(),
                                         "company_name": company, "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_only_admins_edit_rules_and_each_company_sees_its_own(c, monkeypatch):
    monkeypatch.setenv("AGAXES_REQUIRE_LOGIN", "1")
    owner = signup(c, "owner@acme.io")
    member = signup(c, "sam@acme.io")
    other = signup(c, "boss@globex.io", company="Globex")
    body = {"type": "offer_approvers", "params": {"threshold": "30 lakh", "approvers": 2}}

    p = c.post("/api/rules/preview", json=body, headers=h(member)).json()
    assert p == {"ok": True, "sentence": "Offers over ₹30L need 2 approvers", "params": p["params"]}
    assert c.post("/api/rules/preview", json={"type": "quiet_hours", "params": {"start": "x"}}, headers=h(member)).json()["ok"] is False
    assert c.post("/api/rules", json=body, headers=h(member)).status_code == 403  # recruiters don't write rules
    r = c.post("/api/rules", json=body, headers=h(owner))
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["sentence"] == "Offers over ₹30L need 2 approvers" and rule["workspace_id"]
    assert c.post("/api/rules", json={"type": "quiet_hours", "params": {"start": "nope"}}, headers=h(owner)).status_code == 400

    listing = c.get("/api/rules", headers=h(member)).json()
    assert [x["rule_id"] for x in listing["rules"]] == [rule["rule_id"]] and listing["can_edit"] is False
    assert {t["type"] for t in listing["templates"]} == set(engine.TYPES)
    assert c.get("/api/rules", headers=h(owner)).json()["can_edit"] is True
    assert c.get("/api/rules", headers=h(other)).json()["rules"] == []  # Globex doesn't see Acme's rules
    assert c.get(f"/api/rules/{rule['rule_id']}", headers=h(other)).status_code == 404
    assert c.put(f"/api/rules/{rule['rule_id']}", json={"enabled": False}, headers=h(other)).status_code == 404

    assert c.put(f"/api/rules/{rule['rule_id']}", json={"enabled": False}, headers=h(member)).status_code == 403
    u = c.put(f"/api/rules/{rule['rule_id']}", json={"params": {"threshold": "₹40L"}}, headers=h(owner)).json()
    assert u["version"] == 2 and u["sentence"] == "Offers over ₹40L need 2 approvers"
    one = c.get(f"/api/rules/{rule['rule_id']}", headers=h(owner)).json()
    assert [x["change"] for x in one["history"]] == ["created", "updated"]
    assert c.delete(f"/api/rules/{rule['rule_id']}", headers=h(owner)).status_code == 200
    assert c.get("/api/rules", headers=h(owner)).json()["rules"] == []

    created = ledger.entries(kind="rule.created")[0]
    assert created["actor"]["email"] == "owner@acme.io" and created["payload"]["by"] == "owner@acme.io"
