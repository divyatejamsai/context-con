"""Connecting an agent end to end: catalog, owner and sponsor, high-risk review with separation of duties, issuing a
template agent or an outside agent's enrollment, the first signed call, and tool enforcement at runtime."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.accounts import api as auth_api
from app.accounts.store import AccountStore
from app.agents import connect, enroll, ledger, registry

SPONSOR = {s["id"]: s for s in json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}[
    "authorised_founder"]["sponsor"]
PW = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    for var, name in (("AGENTS_PATH", "agents.json"), ("LEDGER_PATH", "ledger.jsonl"), ("ISSUER_KEY_PATH", "issuer.key"),
                      ("OUTBOX_PATH", "outbox.jsonl"), ("RUNTIME_PATH", "runtime.json")):
        monkeypatch.setenv(var, str(tmp_path / name))
    monkeypatch.setenv("CRUSTDATA_MODE", "replay")
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.setenv("RUNTIME_ENABLED", "0")
    monkeypatch.delenv("COUNTERSIGN_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("AGAXES_REQUIRE_LOGIN", raising=False)
    from app.agents import api as agents_api
    monkeypatch.setattr(agents_api, "_client", None)

    async def no_identify(domain):
        return None
    monkeypatch.setattr(auth_api, "identify_company", no_identify)
    auth_api.reset_store(AccountStore(tmp_path / "accounts.db"))
    yield tmp_path
    auth_api.reset_store(None)


@pytest.fixture
def c():
    from app.main import app
    return TestClient(app)


def signup(c, email, company="Acme") -> tuple[str, str]:
    r = c.post("/api/auth/signup", json={"email": email, "password": PW, "full_name": email.split("@")[0].title(),
                                         "company_name": company, "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["user"]["id"]


def h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def body(**kw) -> dict:
    b = {"agent_type": "template", "template": "diligence", "name": "Diligence", "scopes": ["data.read"],
         "tools": ["crustdata.companies", "web"], "budget": {"crustdata_calls_per_day": 50, "sends_per_day": 0},
         "require_approval": True, "sponsor": SPONSOR}
    b.update(kw)
    return b


def sign(raw: bytes, data: bytes) -> str:
    return base64.b64encode(Ed25519PrivateKey.from_private_bytes(raw).sign(data)).decode()


def new_key() -> tuple[bytes, str]:
    k = Ed25519PrivateKey.generate()
    raw = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw, base64.b64encode(pub).decode()


# ---- catalog ------------------------------------------------------------------------------------------------------

def test_catalog_explains_every_scope_with_risk_and_who_can_grant(c):
    cat = c.get("/api/connect/catalog").json()
    scopes = {s["key"]: s for s in cat["scopes"]}
    assert set(scopes) == set(registry.ALL_SCOPES)
    assert scopes["data.read"]["risk"] == "low" and not scopes["data.read"]["needs_review"]
    assert scopes["contract.sign"]["needs_review"] and scopes["payment.send"]["risk"] == "critical"
    assert all(s["allows"] and s["never"] and s["who_can_grant"] for s in cat["scopes"])
    assert {t["key"] for t in cat["agent_types"]} == {"template", "claude_code", "mcp", "http"}
    sourced = next(t for t in cat["templates"] if t["key"] == "sourced")
    assert "Source candidates" in sourced["jobs"]
    assert cat["budget_defaults"]["sends_per_day"] > 0


# ---- template agent, open mode --------------------------------------------------------------------------------------

def test_template_agent_issues_with_tools_budget_and_a_signed_first_call(c):
    r = c.post("/api/connect/requests", json=body())
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["status"] == "approved" and not req["review"]["required"] and req["risk"] == "low"

    r = c.post(f"/api/connect/requests/{req['request_id']}/issue")
    assert r.status_code == 200, r.text
    out = r.json()
    agent = out["agent"]
    assert agent["tools"] == ["crustdata.companies", "web"] and agent["connection_id"] == req["request_id"]
    assert agent["key_custody"] == "agaxes"
    from app.runtime import store
    pol = store.policy(agent["agent_id"])
    assert pol["budget"]["crustdata_calls_per_day"] == 50 and pol["budget"]["sends_per_day"] == 0
    assert pol["require_approval"] is True

    # issuing twice is refused
    assert c.post(f"/api/connect/requests/{req['request_id']}/issue").status_code == 409

    t = c.post(f"/api/connect/requests/{req['request_id']}/test").json()
    assert t["connected"] is True
    assert registry.get_agent(agent["agent_id"])["first_seen_at"]
    kinds = [e["kind"] for e in ledger.entries()]
    for k in ("connect.requested", "agent.onboarded", "connect.policy", "connect.issued", "agent.first_heartbeat"):
        assert k in kinds, k
    assert agent["status"] == "active", agent["last_verdict"]  # the replayed sponsor check passes
    assert t["request"]["status"] == "connected"
    # a second test doesn't write a second first-heartbeat
    c.post(f"/api/connect/requests/{req['request_id']}/test")
    assert [e["kind"] for e in ledger.entries()].count("agent.first_heartbeat") == 1


def test_bad_requests_are_refused_with_a_reason(c):
    r = c.post("/api/connect/requests", json=body(tools=["email"]))
    assert r.status_code == 400 and "needs the outreach" in r.json()["detail"]
    r = c.post("/api/connect/requests", json=body(scopes=["outreach.sales"]))  # Diligence is an analyst
    assert r.status_code == 400 and "role ceiling" in r.json()["detail"]
    r = c.post("/api/connect/requests", json=body(budget={"sends_per_day": 10_000}))
    assert r.status_code == 400
    r = c.post("/api/connect/requests", json=body(template="nope"))
    assert r.status_code == 400
    r = c.post("/api/connect/requests", json=body(sponsor={**SPONSOR, "profile_url": ""}))
    assert r.status_code == 400


# ---- high-risk review and owners, with company accounts ---------------------------------------------------------------

def test_high_risk_scope_needs_a_different_admin_to_approve(c):
    a_tok, a_id = signup(c, "ana@acme.com")
    b_tok, b_id = signup(c, "ben@acme.com")
    v_tok, v_id = signup(c, "vic@acme.com")
    assert c.put(f"/api/workspace/members/{b_id}", json={"role": "admin"}, headers=h(a_tok)).status_code == 200
    assert c.put(f"/api/workspace/members/{v_id}", json={"role": "viewer"}, headers=h(a_tok)).status_code == 200

    ppl = c.get("/api/connect/people", headers=h(a_tok)).json()["members"]
    assert {p["email"]: p["can_own"] for p in ppl} == {"ana@acme.com": True, "ben@acme.com": True, "vic@acme.com": False}

    offer = body(template="offer", name="Offer", scopes=["contract.sign", "data.read"], tools=["crustdata.people", "esign"])
    assert c.post("/api/connect/requests", json=offer, headers=h(a_tok)).status_code == 400  # no owner
    r = c.post("/api/connect/requests", json={**offer, "owner_user_id": v_id}, headers=h(a_tok))
    assert r.status_code == 400 and "viewer" in r.json()["detail"]
    r = c.post("/api/connect/requests", json={**offer, "owner_user_id": a_id}, headers=h(a_tok))
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["status"] == "pending_review" and req["review"]["scopes"] == ["contract.sign"]
    assert req["owner"]["email"] == "ana@acme.com" and req["risk"] == "high"

    rid = req["request_id"]
    assert c.post(f"/api/connect/requests/{rid}/issue", headers=h(a_tok)).status_code == 409
    r = c.post(f"/api/connect/requests/{rid}/approve", json={}, headers=h(a_tok))
    assert r.status_code == 403 and "Ben" in r.json()["detail"]
    r = c.post(f"/api/connect/requests/{rid}/approve", json={"note": "offers only"}, headers=h(b_tok))
    assert r.status_code == 200 and r.json()["review"]["by"] == "ben@acme.com"
    r = c.post(f"/api/connect/requests/{rid}/issue", headers=h(a_tok))
    assert r.status_code == 200, r.text
    agent = r.json()["agent"]
    assert a_id in agent["assignees"] and agent["owner"]["email"] == "ana@acme.com"
    assert agent["workspace_id"] == req["workspace_id"]

    # another company can't see or act on it
    x_tok, _ = signup(c, "xi@other.com", company="Other")
    assert c.get(f"/api/connect/requests/{rid}", headers=h(x_tok)).status_code == 404
    assert c.get("/api/connect/requests", headers=h(x_tok)).json() == []


def test_sole_admin_can_approve_their_own_request_and_it_is_flagged(c):
    tok, uid = signup(c, "solo@tiny.com", company="Tiny")
    offer = body(template="offer", name="Offer", scopes=["contract.sign"], tools=["esign"], owner_user_id=uid)
    rid = c.post("/api/connect/requests", json=offer, headers=h(tok)).json()["request_id"]
    r = c.post(f"/api/connect/requests/{rid}/approve", json={}, headers=h(tok))
    assert r.status_code == 200 and r.json()["review"]["sole_admin"] is True
    e = [x for x in ledger.entries() if x["kind"] == "connect.approved"][-1]
    assert e["payload"]["sole_admin"] is True and e["actor"]["email"] == "solo@tiny.com"


def test_reject_and_cancel(c):
    rid = c.post("/api/connect/requests", json=body(template="offer", name="Offer", scopes=["contract.sign"],
                                                   tools=[])).json()["request_id"]
    r = c.post(f"/api/connect/requests/{rid}/reject", json={"note": "not yet"})
    assert r.json()["status"] == "rejected"
    assert c.post(f"/api/connect/requests/{rid}/issue").status_code == 409
    rid2 = c.post("/api/connect/requests", json=body()).json()["request_id"]
    assert c.post(f"/api/connect/requests/{rid2}/cancel").json()["status"] == "cancelled"


# ---- outside agent: enrollment, then its own first signed call -------------------------------------------------------

def test_claude_code_enrolls_with_its_own_key_and_its_heartbeat_completes_the_connection(c):
    b = body(agent_type="claude_code", template=None, name="Claude Code", role="researcher", tools=["crustdata.people"],
             budget={"tasks_per_day": 5})
    req = c.post("/api/connect/requests", json=b).json()
    assert req["runtime"] == "own"
    out = c.post(f"/api/connect/requests/{req['request_id']}/issue").json()
    assert out["request"]["status"] == "awaiting_agent"
    assert out["token"] in out["command"] and "claude mcp add agaxes" in out["mcp_command"]
    assert json.loads(out["mcp_config"])["mcpServers"]["agaxes"]["args"] == ["backend/mcp_server.py"]
    t = c.post(f"/api/connect/requests/{req['request_id']}/test").json()
    assert t["connected"] is False and "enrollment" in t["waiting_for"]

    raw, pub = new_key()
    r = c.post("/api/agents/enroll", json={"token": out["token"], "public_key": pub,
                                           "proof": sign(raw, enroll.proof_text(out["token"], pub).encode())})
    assert r.status_code == 200, r.text
    agent = r.json()["agent"]
    got = c.get(f"/api/connect/requests/{req['request_id']}").json()
    assert got["agent_id"] == agent["agent_id"] and got["status"] in ("enrolled", "failed")
    rec = registry.get_agent(agent["agent_id"])
    assert rec["tools"] == ["crustdata.people"] and rec["key_custody"] == "agent"
    from app.runtime import store
    assert store.policy(agent["agent_id"])["budget"]["tasks_per_day"] == 5

    # Agaxes can't fake the outside agent's first call: it holds no key
    t = c.post(f"/api/connect/requests/{req['request_id']}/test").json()
    assert t["connected"] is False and "first signed call" in t["waiting_for"]

    from app.agents.models import Passport
    from app.agents.passport import _message_bytes, sign_message
    from app.runtime.external import signed_text
    p = Passport.model_validate(rec["passport"])
    ts = int(time.time())
    bad = c.post("/api/agents/heartbeat", json={"agent_id": agent["agent_id"], "ts": ts, "text": "hi",
                                                "signature": sign(new_key()[0], _message_bytes(p, signed_text("heartbeat", agent["agent_id"], None, ts, "hi")))})
    assert bad.status_code == 401
    ok = c.post("/api/agents/heartbeat", json={"agent_id": agent["agent_id"], "ts": ts, "text": "hi",
                                               "signature": sign_message(p, raw, signed_text("heartbeat", agent["agent_id"], None, ts, "hi"))})
    assert ok.status_code == 200 and ok.json()["first"] is True
    got = c.get(f"/api/connect/requests/{req['request_id']}").json()
    assert got["first_seen_at"] and got["test"]["via"] == "agent"
    assert got["agent_status"] == "active" and got["status"] == "connected"


# ---- sponsor lookup and tools at runtime ----------------------------------------------------------------------------

class FakeCrust:
    def __init__(self, rows):
        self.rows = rows

    async def person_search(self, filters, limit=25, **kw):
        return self.rows

    async def person_enrich(self, url, fields=None):
        return next((r for r in self.rows
                     if r["social_handles"]["professional_network_identifier"]["profile_url"] == url), None)


def person(name, title, company, url):
    return {"basic_profile": {"name": name}, "social_handles": {"professional_network_identifier": {"profile_url": url}},
            "experience": {"employment_details": {"current": [{"name": company, "title": title}]}}}


@pytest.mark.asyncio
async def test_find_and_check_sponsor_read_title_authority_from_crustdata():
    fake = FakeCrust([person("Ana Rao", "Intern", "Other Co", "https://linkedin.com/in/ana2"),
                      person("Ana Rao", "Head of Talent", "Acme", "https://linkedin.com/in/ana")])
    res = await connect.find_sponsor(fake, "Ana Rao", "Acme", ["outreach.hiring", "contract.sign", "payment.send"])
    best = res["matches"][0]
    assert best["profile_url"].endswith("/ana") and best["works_there"]
    assert best["grants"] == {"outreach.hiring": True, "contract.sign": True, "payment.send": False}
    assert res["matches"][1]["grants"]["outreach.hiring"] is False  # doesn't work there
    chk = await connect.check_sponsor(fake, "https://linkedin.com/in/ana", "Acme", ["data.read"])
    assert chk["found"] and chk["title"] == "Head of Talent" and chk["grants"]["data.read"]
    assert (await connect.check_sponsor(None, "x", "Acme"))["found"] is False


@pytest.mark.asyncio
async def test_metered_client_refuses_tools_the_agent_wasnt_connected_to(monkeypatch):
    from app.runtime import store
    from app.runtime.worker import METER, Meter, MeteredClient, ToolNotAllowed
    from app.agents.models import Sponsor
    a = registry.onboard("Diligence", "analyst", Sponsor(**SPONSOR), ["data.read"])
    registry.annotate(a["agent_id"], tools=["crustdata.companies"])
    calls = []

    class Inner:
        async def company_enrich(self, *a, **k):
            calls.append("company_enrich")
            return {}

        async def person_enrich(self, *a, **k):
            calls.append("person_enrich")
            return {}

    METER.set(Meter("t_x", a["agent_id"]))
    monkeypatch.setattr(store, "task_mutate", lambda *a, **k: None)
    mc = MeteredClient(Inner())
    await mc.company_enrich(domain="acme.com")
    with pytest.raises(ToolNotAllowed, match="Crustdata People"):
        await mc.person_enrich("https://linkedin.com/in/x")
    assert calls == ["company_enrich"]
    registry.annotate(a["agent_id"], tools=None)
    assert connect.tool_allowed(registry.get_agent(a["agent_id"]), "person_enrich") is None
    METER.set(None)
