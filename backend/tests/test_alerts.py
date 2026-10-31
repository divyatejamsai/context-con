"""Alerts (app/alerts): the responsible person hears about approvals, blocks and stops by email / Slack / the bell, and
can approve or reject from the alert with a signed, single-use, expiring link that lands on the ledger as them."""
from __future__ import annotations

import re

import httpx
import pytest

from app.accounts import api as auth_api
from app.accounts.store import AccountStore
from app.agents import ledger, registry
from app.agents.api import crustdata
from app.alerts import core as alerts
from app.alerts import links
from app.fleet.demo import onboard
from app.outbound import mailer
from app.runtime import store
from app.runtime.supervisor import Runtime

from .test_runtime import TODAY, until

PW = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    for var, name in (("AGENTS_PATH", "agents.json"), ("LEDGER_PATH", "ledger.jsonl"), ("ISSUER_KEY_PATH", "issuer.key"),
                      ("OUTBOX_PATH", "outbox.jsonl"), ("RUNTIME_PATH", "runtime.json")):
        monkeypatch.setenv(var, str(tmp_path / name))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.setenv("RUNTIME_ENABLED", "0")
    monkeypatch.setenv("AGAXES_DEFAULT_WORKSPACE", "none")
    monkeypatch.setenv("AGAXES_PUBLIC_URL", "https://agaxes.test")
    for v in ("COUNTERSIGN_ADMIN_TOKEN", "AGAXES_REQUIRE_LOGIN", "SLACK_WEBHOOK_URL", "ALERT_SLACK_WEBHOOK_URL",
              "RESEND_API_KEY", "ALERT_LINK_SECRET"):
        monkeypatch.delenv(v, raising=False)
    # email "set up" to the test inbox; the provider call itself is captured, nothing leaves the machine
    monkeypatch.setenv("OUTBOUND_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.invalid")
    monkeypatch.setenv("MAIL_FROM", "agaxes@example.com")
    monkeypatch.setenv("OUTBOUND_TEST_TO", "inbox@example.com")
    from app.agents import api as agents_api
    from app.runtime import worker
    monkeypatch.setattr(agents_api, "_client", None)
    monkeypatch.setattr(worker, "_mcp_mod", None)

    async def no_identify(domain):
        return None
    monkeypatch.setattr(auth_api, "identify_company", no_identify)
    auth_api.reset_store(AccountStore(tmp_path / "accounts.db"))
    store.reset_cache()
    alerts.reset_cache()
    alerts.install()
    yield tmp_path
    alerts.uninstall()
    alerts.reset_cache()
    store.reset_cache()
    auth_api.reset_store(None)


@pytest.fixture
def inbox(monkeypatch):
    sent: list[dict] = []

    async def fake(to, subject, body, *, html=None, from_name="Sourced"):
        sent.append({"to": to, "subject": subject, "text": body, "html": html})
        return mailer.Delivery(provider="smtp", mode="test", delivered_to=to, provider_id=None, message_id="<x@y>",
                               status="sent", from_addr="agaxes@example.com")
    monkeypatch.setattr(mailer, "send_transactional", fake)
    return sent


def client():
    from app.main import app
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def signup(c, email, company="Acme") -> str:
    r = await c.post("/api/auth/signup", json={"email": email, "password": PW, "full_name": email.split("@")[0].title(),
                                               "company_name": company, "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def token_from(text: str, action: str) -> str:
    return re.search(rf"{action.capitalize()}:\s+https://agaxes\.test/act/(\S+)", text).group(1)


async def pipeline_with_approvals(c, owner_tok: str, assignee_email: str) -> dict:
    me = (await c.get("/api/auth/me", headers=h(owner_tok))).json()
    people = {m["email"]: m for m in (await c.get("/api/workspace/members", headers=h(owner_tok))).json()["members"]}
    ag = {k: a for k, a, _ in onboard(["pipeline"])}["pipeline"]
    registry.set_workspace(ag["agent_id"], me["company"]["id"])
    registry.set_assignees(ag["agent_id"], [people[assignee_email]["id"]])
    rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
    await rt.start()
    try:
        t = rt.assign(ag["agent_id"], "sales_outreach", {}, by="test")
        await until(lambda: store.get_task(t["task_id"])["status"] not in ("queued", "running"), 120)
    finally:
        await rt.stop()
    await alerts.drain()
    return {"agent": ag, "people": people}


@pytest.mark.asyncio
async def test_approval_alert_emails_the_assignee_and_the_link_approves_once_as_them(inbox):
    async with client() as c:
        owner = await signup(c, "owner@acme.io")
        riya = await signup(c, "riya@acme.io")
        beta = await signup(c, "owner@beta.io", "Beta")
        ctx = await pipeline_with_approvals(c, owner, "riya@acme.io")
        pending = store.approvals("pending")
        assert len(pending) == 3

        approval_mails = [m for m in inbox if "wants to send a message" in m["subject"]]
        assert len(approval_mails) == 3 and all(m["to"] == "inbox@example.com" for m in inbox)  # only the test inbox
        assert any("Send Guard blocked" in m["subject"] for m in inbox)  # the stale CRM row
        m = approval_mails[0]
        assert "riya@acme.io" in m["text"] and ">Approve</a>" in m["html"] and "Pipeline" in m["text"]

        tok = token_from(m["text"], "approve")
        pv = (await c.get(f"/api/alerts/action/{tok}")).json()  # opening the link never acts
        assert pv["state"] == "ready" and pv["action"] == "approve" and pv["for"]["email"] == "riya@acme.io"
        aid = pv["approval"]["approval_id"]
        assert store.get_approval(aid)["status"] == "pending"

        r = await c.post(f"/api/alerts/action/{tok}", json={})
        assert r.status_code == 200, r.text
        assert r.json()["approval"]["status"] == "sent" and store.get_approval(aid)["decided_by"] == "riya@acme.io"
        e = next(x for x in ledger.entries(kind="runtime.approval") if x["payload"]["approval_id"] == aid)
        assert e["actor"]["via"] == "alert_link" and e["actor"]["email"] == "riya@acme.io" and e["actor"]["user_id"]
        assert ledger.verify_chain() == (True, None)

        again = await c.post(f"/api/alerts/action/{tok}", json={})
        assert again.status_code == 409  # single use (and it's decided)
        rej = token_from(m["text"], "reject")
        assert (await c.post(f"/api/alerts/action/{rej}", json={})).status_code == 409  # the pair is spent too

        # the reject link of another alert, with a note
        m2 = next(x for x in approval_mails if pv["approval"]["to"]["name"] not in x["subject"])
        r2 = await c.post(f"/api/alerts/action/{token_from(m2['text'], 'reject')}", json={"note": "not this quarter"})
        assert r2.status_code == 200 and r2.json()["approval"]["status"] == "rejected"

        # forged and expired links
        assert (await c.get(f"/api/alerts/action/{tok[:-3]}abc")).status_code == 404
        last = store.approvals("pending")[0]
        old = links.make(last["approval_id"], "approve", ctx["people"]["riya@acme.io"], "x.1", hours=-1)
        assert (await c.post(f"/api/alerts/action/{old}", json={})).status_code == 410

        # the bell: riya and the owner see Acme's alerts, Beta sees none of them
        feed = (await c.get("/api/alerts", headers=h(riya))).json()
        assert feed["unread"] >= 4 and any(i["approval_status"] == "sent" for i in feed["items"])
        assert (await c.get("/api/alerts", headers=h(beta))).json()["items"] == []
        await c.post("/api/alerts/read", json={}, headers=h(riya))
        assert (await c.get("/api/alerts", headers=h(riya))).json()["unread"] == 0
        assert (await c.get("/api/alerts", headers=h(owner))).json()["unread"] >= 4  # read state is per person

        # someone demoted to viewer since the alert can't use their link any more
        riya_id = ctx["people"]["riya@acme.io"]["id"]
        assert (await c.put(f"/api/workspace/members/{riya_id}", json={"role": "viewer"}, headers=h(owner))).status_code == 200
        live = links.make(last["approval_id"], "approve", ctx["people"]["riya@acme.io"], "x.2")
        r3 = await c.post(f"/api/alerts/action/{live}", json={})
        assert r3.status_code == 403 and store.get_approval(last["approval_id"])["status"] == "pending"


@pytest.mark.asyncio
async def test_preferences_route_email_to_the_next_responsible_person(inbox):
    async with client() as c:
        owner = await signup(c, "owner@acme.io")
        riya = await signup(c, "riya@acme.io")
        r = await c.put("/api/alerts/prefs", json={"email": False}, headers=h(riya))
        assert r.status_code == 200 and r.json()["prefs"]["email"] is False
        assert r.json()["channels"]["email"]["ready"] and not r.json()["channels"]["slack"]["ready"]
        await pipeline_with_approvals(c, owner, "riya@acme.io")
        mails = [m for m in inbox if "wants to send" in m["subject"]]
        assert mails and all("owner@acme.io" in m["text"] for m in mails)
        a = alerts.all_alerts()[0]
        assert a["channels"]["email"]["for"] == "owner@acme.io" and a["channels"]["slack"]["status"] == "skipped"
        # turning a topic off for everyone: no email for blocks
        await c.put("/api/alerts/prefs", json={"block": False}, headers=h(owner))
        await c.put("/api/alerts/prefs", json={"block": False}, headers=h(riya))
        n = len(inbox)
        ledger.append("guard.verdict", {"agent_id": alerts.all_alerts()[0]["agent_id"], "decision": "block",
                                        "to": {"name": "Someone New"}, "checks": [{"name": "x", "status": "fail", "detail": "moved on"}]})
        await alerts.drain()
        assert len(inbox) == n and alerts.all_alerts()[-1]["channels"]["email"]["status"] == "off"


@pytest.mark.asyncio
async def test_stops_alert_once_and_slack_gets_buttons(inbox, monkeypatch):
    posts = []

    async def fake_post(self, url, json=None, **kw):
        posts.append((url, json))
        return httpx.Response(200, text="ok")
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/T/B/x")
    ags = {k: a for k, a, _ in onboard(["pipeline", "diligence"])}
    ids = [a["agent_id"] for a in ags.values()]
    # an emergency stop suspends each agent (one passport.revoked each) and writes one freeze.started
    for i in ids:
        registry.suspend(i, "suspended by emergency stop frz_abc: leak suspected", by="owner@acme.io")
    ledger.append("freeze.started", {"freeze_id": "frz_abc", "scope": "all", "agent_ids": ids,
                                     "agent_names": ["Pipeline", "Diligence"], "reason": "leak suspected",
                                     "by": "owner@acme.io", "stopped_tasks": 1, "cancelled_approvals": 2})
    await alerts.drain()
    stops = [a for a in alerts.all_alerts() if a["kind"] == "stop"]
    assert len(stops) == 1 and stops[0]["title"] == "Emergency stop: 2 agents frozen"
    assert len([m for m in inbox if "Emergency stop" in m["subject"]]) == 1
    assert posts and posts[0][0].startswith("https://hooks.slack.test/")

    # a payroll suspension is its own alert; an approval on Slack carries Approve / Reject buttons
    posts.clear()
    ag = {k: a for k, a, _ in onboard(["reference"])}["reference"]
    registry.suspend(ag["agent_id"], "sponsor left the company", by="payroll check")
    store.add_approval(task_id="tsk_x", agent_id=ag["agent_id"], agent_name="Reference", action="send",
                       to={"name": "Asha Rao", "company": "Acme"}, body="Hi Asha", scope="outreach.hiring",
                       signature="s", today=None, preview={"decision": "allow", "checks": []})
    await alerts.drain()
    assert any(a["title"] == "Reference was suspended" for a in alerts.all_alerts())
    acts = [b for _, j in posts for b in j["blocks"] if b["type"] == "actions"]
    assert any([e["text"]["text"] for e in b["elements"]] == ["Approve", "Reject", "Open in Agaxes"] for b in acts)


@pytest.mark.asyncio
async def test_without_accounts_the_link_acts_as_the_employer_and_never_breaks_the_runtime(inbox, monkeypatch):
    ag = {k: a for k, a, _ in onboard(["pipeline"])}["pipeline"]
    a = store.add_approval(task_id="tsk_x", agent_id=ag["agent_id"], agent_name="Pipeline", action="send",
                           to={"name": "Asha Rao", "company": "Acme"}, body="Hi", scope="outreach.sales",
                           signature="s", today=None, preview={"decision": "allow", "checks": []})
    await alerts.drain()
    mail = next(m for m in inbox if "Asha Rao" in m["subject"])
    async with client() as c:
        r = await c.post(f"/api/alerts/action/{token_from(mail['text'], 'reject')}", json={"note": "no"})
        assert r.status_code == 200 and r.json()["approval"]["status"] == "rejected"
    e = ledger.entries(kind="runtime.approval")[-1]
    assert e["actor"]["via"] == "alert_link" and e["payload"]["decision"] == "rejected"

    # a failing email provider is recorded on the alert, never raised into the code that made the approval
    async def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(mailer, "send_transactional", boom)
    store.add_approval(task_id="tsk_y", agent_id=ag["agent_id"], agent_name="Pipeline", action="send",
                       to={"name": "Ben"}, body="Hi", scope="outreach.sales", signature="s", today=None, preview={})
    await alerts.drain()
    assert alerts.all_alerts()[-1]["channels"]["email"]["status"] == "failed"
    assert store.get_approval(a["approval_id"])["status"] == "rejected"


@pytest.mark.asyncio
async def test_two_approver_offer_asks_a_second_person_and_counts_link_approvals_as_people(inbox, monkeypatch, tmp_path):
    from app.rules import engine
    from app.runtime.kinds import hire_template
    async with client() as c:
        owner = await signup(c, "owner@acme.io")
        await signup(c, "riya@acme.io")
        me = (await c.get("/api/auth/me", headers=h(owner))).json()
        people = {m["email"]: m for m in (await c.get("/api/workspace/members", headers=h(owner))).json()["members"]}
        onboard(["sourced"])
        rt = Runtime(crustdata(), tick=0.05, payroll=False, today=TODAY)
        await rt.start()
        try:
            offer, _ = await hire_template("offer", rt.client)
            registry.set_workspace(offer["agent_id"], me["company"]["id"])
            registry.set_assignees(offer["agent_id"], [people["riya@acme.io"]["id"]])
            engine.create("offer_approvers", {"threshold": "₹30L", "approvers": 2}, by="owner", workspace_id=None)
            t = rt.assign(offer["agent_id"], "offer_letter", {"candidate": "Pankaj Savaliya | https://www.linkedin.com/in/pankaj-savaliya | Acme",
                                                               "role": "Senior Backend Engineer", "compensation": "₹42 LPA"}, by="test")
            await until(lambda: store.get_task(t["task_id"])["status"] not in ("queued", "running"), 60)
        finally:
            await rt.stop()
        await alerts.drain()
        first = next(m for m in inbox if "sign an offer letter" in m["subject"])
        assert "riya@acme.io" in first["text"] and "needs 2 different people" in first["text"]
        r = await c.post(f"/api/alerts/action/{token_from(first['text'], 'approve')}", json={})
        assert r.status_code == 200 and r.json()["approval"]["status"] == "pending"
        await alerts.drain()
        second = next(m for m in inbox if "1 of 2 approved" in m["subject"])
        assert "owner@acme.io" in second["text"] and "riya@acme.io" in second["text"]  # for the owner; riya approved
        r2 = await c.post(f"/api/alerts/action/{token_from(second['text'], 'approve')}", json={})
        assert r2.status_code == 200 and r2.json()["approval"]["status"] == "signed"
        signed = ledger.entries(kind="offer.signed")[-1]
        assert signed["payload"]["approvers"] == ["riya@acme.io", "owner@acme.io"]
        assert signed["actor"]["via"] == "alert_link" and signed["actor"]["email"] == "owner@acme.io"
