"""Who may do what in Agaxes: roles from the company login, workspace isolation, the actor on every ledger entry,
outside-agent enrollment with agent-held keys, key rotation, the signed audit export, and member management."""
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
from app.agents import audit, enroll, ledger, registry

SPONSORS = {s["id"]: s for s in json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
SPONSOR = SPONSORS["authorised_founder"]["sponsor"]
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


def signup(c, email, company="Acme") -> str:
    r = c.post("/api/auth/signup", json={"email": email, "password": PW, "full_name": email.split("@")[0].title(),
                                         "company_name": company, "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def onboard(c, headers=None, name="Scout"):
    r = c.post("/api/agents", json={"name": name, "role": "researcher", "sponsor": SPONSOR}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["agent"]


def new_key() -> tuple[bytes, str]:
    k = Ed25519PrivateKey.generate()
    raw = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw, base64.b64encode(pub).decode()


def sign(raw: bytes, data: bytes) -> str:
    return base64.b64encode(Ed25519PrivateKey.from_private_bytes(raw).sign(data)).decode()


# ---- open mode stays exactly as before ----------------------------------------------------------------------------

def test_open_mode_needs_no_login_and_reports_it(c):
    assert c.get("/api/health").json()["auth_mode"] == "open"
    a = onboard(c)
    assert c.get("/api/agents").status_code == 200
    assert c.post(f"/api/agents/{a['agent_id']}/suspend", json={"reason": "x", "by": "anyone"}).status_code == 200


def test_admin_token_alone_keeps_reads_public_but_protects_writes_and_email(c, monkeypatch):
    monkeypatch.setenv("COUNTERSIGN_ADMIN_TOKEN", "s3cret")
    assert c.get("/api/agents").status_code == 200
    assert c.post("/api/agents", json={"name": "X", "role": "researcher", "sponsor": SPONSOR}).status_code == 401
    # these used to be open even with the admin token set: a real email, a credit-spending run and lookups
    body = {"to": {"name": "A", "profile_url": "https://www.linkedin.com/in/a", "company": "B"}, "body": "hi"}
    assert c.post("/api/agents/agt_x/email", json=body).status_code == 401
    assert c.get("/api/agents/agt_x/run", params={"brief": "x"}).status_code == 401
    assert c.get("/api/contacts", params={"profile_url": "https://www.linkedin.com/in/a"}).status_code == 401
    assert c.post("/api/messages/refresh").status_code == 401
    assert c.post("/api/verify_resume", json={"profile_url": "https://www.linkedin.com/in/a"}).status_code == 401
    assert c.post("/api/runtime/tasks", json={"agent_id": "a", "kind": "x"}).status_code == 401
    assert c.get("/api/agents/agt_x/run", params={"brief": "x", "token": "wrong"}).status_code == 401


# ---- roles and workspaces -----------------------------------------------------------------------------------------

def test_login_required_mode_gates_reads_too(c, monkeypatch):
    monkeypatch.setenv("AGAXES_REQUIRE_LOGIN", "1")
    assert c.get("/api/agents").status_code == 401
    assert c.get("/api/ledger").status_code == 401
    assert c.get("/api/runtime/state").status_code == 401
    assert c.get("/api/agents", headers=h("not-a-real-session")).status_code == 401
    tok = signup(c, "owner@acme.io")
    assert c.get("/api/agents", headers=h(tok)).status_code == 200
    assert c.get("/api/passport/issuer").status_code == 200  # verifying an agent stays public


def test_workspaces_only_see_and_touch_their_own_agents(c, monkeypatch):
    monkeypatch.setenv("AGAXES_REQUIRE_LOGIN", "1")
    acme, beta = signup(c, "owner@acme.io"), signup(c, "owner@beta.io", "Beta")
    a = onboard(c, h(acme), "Acme Scout")
    b = onboard(c, h(beta), "Beta Scout")
    assert a["workspace_id"] and a["workspace_id"] != b["workspace_id"]

    assert [x["name"] for x in c.get("/api/agents", headers=h(acme)).json()] == ["Acme Scout"]
    assert [x["name"] for x in c.get("/api/agents", headers=h(beta)).json()] == ["Beta Scout"]
    # another workspace's agent looks like it doesn't exist, for reads and for every control
    assert c.get(f"/api/agents/{a['agent_id']}", headers=h(beta)).status_code == 404
    assert c.post(f"/api/agents/{a['agent_id']}/suspend", json={"reason": "x"}, headers=h(beta)).status_code == 404
    assert c.post(f"/api/runtime/agents/{a['agent_id']}/pause", json={}, headers=h(beta)).status_code == 404
    assert c.put(f"/api/agents/{a['agent_id']}/scopes", json={"scopes": ["data.read"]}, headers=h(beta)).status_code == 404
    assert c.post(f"/api/agents/{a['agent_id']}/email", headers=h(beta), json={
        "to": {"name": "A", "profile_url": "https://www.linkedin.com/in/a", "company": "B"}, "body": "hi"}).status_code == 404
    assert c.get("/api/ledger/export", params={"agent_id": a["agent_id"]}, headers=h(beta)).status_code == 404

    led = c.get("/api/ledger", headers=h(beta)).json()
    assert led["entries"] and all(a["agent_id"] not in json.dumps(e) for e in led["entries"])
    assert any(b["agent_id"] in json.dumps(e) for e in led["entries"])
    # the operator (admin token) still sees everything
    monkeypatch.setenv("COUNTERSIGN_ADMIN_TOKEN", "s3cret")
    assert len(c.get("/api/agents", headers={"x-admin-token": "s3cret"}).json()) == 2


def test_roles_viewer_member_admin(c, monkeypatch):
    monkeypatch.setenv("AGAXES_REQUIRE_LOGIN", "1")
    owner = signup(c, "owner@acme.io")
    member = signup(c, "sam@acme.io")  # joins Acme by domain, as a member
    viewer_tok = signup(c, "vic@acme.io")
    vic = next(m for m in c.get("/api/workspace/members", headers=h(owner)).json()["members"] if m["email"] == "vic@acme.io")
    assert c.put(f"/api/workspace/members/{vic['id']}", json={"role": "viewer"}, headers=h(owner)).status_code == 200

    assert c.post("/api/agents", json={"name": "X", "role": "researcher", "sponsor": SPONSOR},
                  headers=h(member)).status_code == 403  # onboarding is admin work
    a = onboard(c, h(owner))
    assert c.put(f"/api/agents/{a['agent_id']}/assignees", json={"user_ids": [vic["id"]]}, headers=h(owner)).status_code == 200
    assert c.post(f"/api/runtime/agents/{a['agent_id']}/pause", json={}, headers=h(viewer_tok)).status_code == 403
    assert c.get(f"/api/agents/{a['agent_id']}", headers=h(viewer_tok)).status_code == 200
    assert c.post(f"/api/agents/{a['agent_id']}/suspend", json={"reason": "x"}, headers=h(member)).status_code == 403
    assert c.post("/api/agents/enrollments", json={"name": "CC", "sponsor": SPONSOR}, headers=h(member)).status_code == 403
    assert c.put(f"/api/workspace/members/{vic['id']}", json={"role": "owner"}, headers=h(member)).status_code == 403
    ws = c.get("/api/workspace", headers=h(viewer_tok)).json()
    assert ws["role"] == "viewer" and ws["auth_mode"] == "login_required" and len(ws["roles"]) == 5
    assert ws["access"]["level"] == "own_work"


def test_actor_comes_from_the_session_not_the_request_body(c, monkeypatch):
    monkeypatch.setenv("AGAXES_REQUIRE_LOGIN", "1")
    tok = signup(c, "owner@acme.io")
    a = onboard(c, h(tok))
    r = c.post(f"/api/agents/{a['agent_id']}/suspend", json={"reason": "audit", "by": "the CEO"}, headers=h(tok))
    assert r.json()["suspended_by"] == "owner@acme.io"  # a typed-in "by" can't impersonate someone
    rows = ledger.entries(a["agent_id"])
    onb = next(e for e in rows if e["kind"] == "agent.onboarded")
    assert onb["actor"]["email"] == "owner@acme.io" and onb["actor"]["via"] == "session"
    assert onb["payload"]["workspace_id"] == a["workspace_id"]
    assert ledger.verify_chain() == (True, None)  # the actor is inside the hash
    e = dict(onb)
    e["actor"] = {**e["actor"], "email": "someone@else.io"}
    assert ledger.entry_hash(e) != onb["hash"]


def test_last_owner_stays_and_removed_members_are_signed_out(c):
    owner = signup(c, "owner@acme.io")
    sam = signup(c, "sam@acme.io")
    ms = {m["email"]: m for m in c.get("/api/workspace/members", headers=h(owner)).json()["members"]}
    assert c.put(f"/api/workspace/members/{ms['owner@acme.io']['id']}", json={"role": "admin"},
                 headers=h(owner)).status_code == 409
    assert c.put(f"/api/workspace/members/{ms['sam@acme.io']['id']}", json={"role": "boss"},
                 headers=h(owner)).status_code == 400
    assert c.delete(f"/api/workspace/members/{ms['sam@acme.io']['id']}", headers=h(owner)).status_code == 200
    assert c.get("/api/auth/me", headers=h(sam)).status_code == 401
    assert [e["kind"] for e in ledger.entries(kind="workspace.member_removed")]


# ---- outside agents enroll with their own key -------------------------------------------------------------------

def test_outside_agent_enrolls_with_its_own_key_end_to_end(c, monkeypatch):
    monkeypatch.setenv("AGAXES_REQUIRE_LOGIN", "1")
    tok = signup(c, "owner@acme.io")
    r = c.post("/api/agents/enrollments", headers=h(tok), json={
        "name": "Claude Code", "role": "researcher", "sponsor": SPONSOR, "scopes": ["data.read"], "ttl_minutes": 30})
    assert r.status_code == 200, r.text
    token, enr = r.json()["token"], r.json()["enrollment"]
    assert "enroll " + token in r.json()["command"] and enr["status"] == "pending" and "token_hash" not in enr
    assert token not in Path(enroll._path()).read_text()  # only the hash is stored
    assert token not in Path(ledger.path()).read_text()

    raw, pub = new_key()
    other_raw, _ = new_key()
    bad = c.post("/api/agents/enroll", json={"token": token, "public_key": pub,
                                             "proof": sign(other_raw, enroll.proof_text(token, pub).encode())})
    assert bad.status_code == 401  # a sniffed token can't be paired with a key you don't hold
    assert c.post("/api/agents/enroll", json={"token": "agx_enr_nope", "public_key": pub, "proof": "x"}).status_code == 401

    ok = c.post("/api/agents/enroll", json={"token": token, "public_key": pub,
                                            "proof": sign(raw, enroll.proof_text(token, pub).encode())})
    assert ok.status_code == 200, ok.text
    agent = ok.json()["agent"]
    aid = agent["agent_id"]
    assert agent["key_custody"] == "agent" and agent["runtime"] == "external" and agent["passport"]["public_key"] == pub
    assert agent["workspace_id"] and agent["status"] == "active"
    stored = json.loads(Path(registry._path()).read_text())[aid]
    assert stored["private_key"] is None  # Agaxes never had it
    with pytest.raises(registry.RegistryError):
        registry.private_key(aid)
    assert c.post("/api/agents/enroll", json={"token": token, "public_key": pub,
                                              "proof": sign(raw, enroll.proof_text(token, pub).encode())}).status_code == 401
    enrolled = next(e for e in ledger.entries(aid) if e["kind"] == "agent.onboarded")
    assert enrolled["actor"]["via"] == "enrollment" and enrolled["actor"]["approved_by"] == "owner@acme.io"
    assert [x["agent_id"] for x in c.get("/api/agents", headers=h(tok)).json()] == [aid]
    listed = c.get("/api/agents/enrollments", headers=h(tok)).json()
    assert listed[0]["status"] == "used" and listed[0]["agent_id"] == aid

    # it signs runtime calls with its own key
    from app.agents.models import Passport
    from app.agents.passport import sign_message
    from app.runtime.external import signed_text
    p = Passport.model_validate(agent["passport"])

    def claim(key):
        ts = int(time.time())
        return c.post("/api/runtime/agent/claim", json={"agent_id": aid, "ts": ts,
                                                        "signature": sign_message(p, key, signed_text("claim", aid, None, ts))})
    assert claim(raw).status_code == 200

    # rotation: signed by the old key and the new one; afterwards the old key is refused
    new_raw, new_pub = new_key()
    ts = int(time.time())
    text = signed_text("rotate_key", aid, None, ts, new_pub)
    from app.agents.ledger import canonical
    body = {"new_public_key": new_pub, "ts": ts, "signature": sign_message(p, raw, text),
            "new_key_proof": sign(new_raw, canonical({"agent_id": aid, "body": text}).encode())}
    assert c.post(f"/api/agents/{aid}/rotate_key", json={**body, "new_key_proof": sign(other_raw, b"x")}).status_code == 401
    rot = c.post(f"/api/agents/{aid}/rotate_key", json=body)
    assert rot.status_code == 200, rot.text
    assert c.post(f"/api/agents/{aid}/rotate_key", json=body).status_code in (400, 401)  # no replay
    p2 = Passport.model_validate(rot.json()["passport"])
    assert p2.public_key == new_pub and p2.scopes == p.scopes
    ts = int(time.time())
    old = c.post("/api/runtime/agent/claim", json={"agent_id": aid, "ts": ts, "signature": sign_message(
        p, raw, signed_text("claim", aid, None, ts))})
    assert old.status_code == 401
    ts = int(time.time())
    assert c.post("/api/runtime/agent/claim", json={"agent_id": aid, "ts": ts, "signature": sign_message(
        p2, new_raw, signed_text("claim", aid, None, ts))}).status_code == 200
    assert c.get(f"/api/passport/{aid}").json()["passport"]["public_key"] == new_pub
    assert "passport.key_rotated" in [e["kind"] for e in ledger.entries(aid)]


def test_scope_change_keeps_an_agent_held_key(c):
    r = c.post("/api/agents/enrollments", json={"name": "Bot", "role": "researcher", "sponsor": SPONSOR,
                                                "scopes": ["data.read"]})
    token = r.json()["token"]
    raw, pub = new_key()
    aid = c.post("/api/agents/enroll", json={"token": token, "public_key": pub,
                                             "proof": sign(raw, enroll.proof_text(token, pub).encode())}).json()["agent"]["agent_id"]
    out = c.put(f"/api/agents/{aid}/scopes", json={"scopes": []})
    assert out.status_code == 200, out.text
    a = registry.get_agent(aid)
    assert a["passport"]["public_key"] == pub and a.get("private_key") is None


def test_expired_and_revoked_enrollments_fail(c):
    mk = lambda: c.post("/api/agents/enrollments", json={"name": "Bot", "sponsor": SPONSOR, "ttl_minutes": 1}).json()
    e1, e2 = mk(), mk()
    rows = json.loads(Path(enroll._path()).read_text())
    rows[e1["enrollment"]["enrollment_id"]]["expires_at"] = "2020-01-01T00:00:00+00:00"
    Path(enroll._path()).write_text(json.dumps(rows))
    assert c.post(f"/api/agents/enrollments/{e2['enrollment']['enrollment_id']}/revoke").status_code == 200
    for e in (e1, e2):
        raw, pub = new_key()
        r = c.post("/api/agents/enroll", json={"token": e["token"], "public_key": pub,
                                               "proof": sign(raw, enroll.proof_text(e["token"], pub).encode())})
        assert r.status_code == 401 and ("expired" in r.text or "revoked" in r.text)


def test_enrollment_rejects_role_ceiling_up_front(c):
    r = c.post("/api/agents/enrollments", json={"name": "Bot", "role": "analyst", "sponsor": SPONSOR,
                                                "scopes": ["payment.send"]})
    assert r.status_code == 400 and "ceiling" in r.text


# ---- audit export -------------------------------------------------------------------------------------------------

def test_audit_export_verifies_and_catches_tampering(c):
    a = onboard(c)
    c.post(f"/api/agents/{a['agent_id']}/suspend", json={"reason": "audit"})
    r = c.get("/api/ledger/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    text = r.text
    issuer = c.get("/api/passport/issuer").json()["public_key"]
    res = audit.verify_export(text, issuer)
    assert res["ok"], res
    assert c.post("/api/ledger/export/verify", json={"export": text}).json()["ok"]

    lines = text.splitlines()
    edited = json.loads(lines[2])
    edited["payload"]["agent_name"] = "Someone else"
    bad = audit.verify_export("\n".join([lines[0], lines[1], json.dumps(edited), *lines[3:]]), issuer)
    assert not bad["ok"] and {c_["name"] for c_ in bad["checks"] if c_["status"] == "fail"} >= {"entries_unedited"}
    dropped = audit.verify_export("\n".join([lines[0], *lines[2:]]), issuer)
    assert not dropped["ok"]
    assert not audit.verify_export(text, base64.b64encode(b"\x00" * 32).decode())["ok"]  # another issuer's key
    assert "ledger.exported" in [e["kind"] for e in ledger.entries()]

    csv = c.get("/api/ledger/export", params={"format": "csv", "agent_id": a["agent_id"]})
    assert csv.status_code == 200 and csv.text.startswith("seq,ts,kind,agent_id")
    assert csv.headers["x-agaxes-export-signature"] and a["agent_id"] in csv.text
    filtered = c.get("/api/ledger/export", params={"agent_id": a["agent_id"]}).text
    assert audit.verify_export(filtered, issuer)["ok"]
    assert c.get("/api/ledger/export", params={"format": "xml"}).status_code == 400


# ---- the hierarchy: platform operator > company owner/admin > recruiter (own work) -------------------------------

def test_hierarchy_operator_company_recruiter(c, monkeypatch):
    monkeypatch.setenv("AGAXES_REQUIRE_LOGIN", "1")
    from app.agents.models import Sponsor
    fleet = registry.onboard("Fleet bot", "analyst", Sponsor(**SPONSOR), ["data.read"])  # seeded, pre-accounts: no company
    acme_owner = signup(c, "owner@acme.io")
    beta_owner = signup(c, "owner@beta.io", "Beta")
    rec_tok = signup(c, "riya@acme.io")  # an Acme recruiter (member)
    riya = next(m for m in c.get("/api/workspace/members", headers=h(acme_owner)).json()["members"]
                if m["email"] == "riya@acme.io")
    mine = onboard(c, h(acme_owner), "Acme Sourced")
    other = onboard(c, h(acme_owner), "Acme Closer")
    beta = onboard(c, h(beta_owner), "Beta Scout")
    assert c.put(f"/api/agents/{mine['agent_id']}/assignees", json={"user_ids": [riya["id"]]},
                 headers=h(acme_owner)).status_code == 200

    # recruiter: only the agent assigned to them, no company-wide views
    names = lambda tok: sorted(a["name"] for a in c.get("/api/agents", headers=h(tok)).json())
    assert names(rec_tok) == ["Acme Sourced"]
    assert c.get(f"/api/agents/{other['agent_id']}", headers=h(rec_tok)).status_code == 404
    assert c.get("/api/ledger", headers=h(rec_tok)).status_code == 403
    assert c.get("/api/ledger/export", headers=h(rec_tok)).status_code == 403
    assert c.get("/api/workspace/members", headers=h(rec_tok)).status_code == 403
    assert c.get("/api/platform/companies", headers=h(rec_tok)).status_code == 403
    st = c.get("/api/runtime/state", headers=h(rec_tok))
    assert st.status_code in (200, 503)
    me = c.get("/api/auth/me", headers=h(rec_tok)).json()
    assert me["access"]["level"] == "own_work" and "ledger" not in me["access"]["views"]

    # company owner: the whole company, nothing else; not the platform view
    assert names(acme_owner) == ["Acme Closer", "Acme Sourced"]
    assert c.get("/api/ledger", headers=h(acme_owner)).status_code == 200
    assert c.get("/api/platform/companies", headers=h(acme_owner)).status_code == 403
    assert c.get("/api/auth/me", headers=h(acme_owner)).json()["access"]["level"] == "company"
    # an owner can't assign someone from another company
    beta_people = c.get("/api/workspace/members", headers=h(beta_owner)).json()["members"]
    assert c.put(f"/api/agents/{mine['agent_id']}/assignees", json={"user_ids": [beta_people[0]["id"]]},
                 headers=h(acme_owner)).status_code == 400

    # platform operator: every company, its people and agents, including the pre-accounts fleet
    monkeypatch.setenv("AGAXES_OPERATOR_EMAILS", "ops@agaxes.io")
    ops = signup(c, "ops@agaxes.io", "Agaxes")
    assert c.get("/api/auth/me", headers=h(ops)).json()["access"]["level"] == "platform"
    assert names(ops) == sorted(["Fleet bot", "Acme Sourced", "Acme Closer", "Beta Scout"])
    plat = c.get("/api/platform/companies", headers=h(ops)).json()
    by = {x["domain"]: x for x in plat["companies"]}
    assert {a["name"] for a in by["acme.io"]["agents"]} == {"Acme Sourced", "Acme Closer"}
    assert {m["email"] for m in by["acme.io"]["members"]} == {"owner@acme.io", "riya@acme.io"}
    assert [a["name"] for a in plat["unassigned_agents"]] == ["Fleet bot"]
    # only the operator moves an agent between companies
    assert c.put(f"/api/platform/agents/{fleet['agent_id']}/workspace", json={"workspace_id": by["beta.io"]["id"]},
                 headers=h(acme_owner)).status_code == 403
    assert c.put(f"/api/platform/agents/{fleet['agent_id']}/workspace", json={"workspace_id": by["beta.io"]["id"]},
                 headers=h(ops)).status_code == 200
    assert names(beta_owner) == ["Beta Scout", "Fleet bot"]
    assert c.get("/api/ledger", headers=h(ops)).status_code == 200
    assert beta  # (used above)


def test_demo_logins_cover_every_level(c):
    from app.agents import registry as reg
    from app.agents.models import Sponsor
    reg.onboard("Sourced", "recruiter", Sponsor(**SPONSOR), ["data.read"])   # seeded like demo_up.sh: no company
    reg.onboard("Closer", "analyst", Sponsor(**SPONSOR), ["data.read"])
    seen = {}
    for who in ("operator", "admin", "recruiter"):
        r = c.post("/api/auth/demo", json={"as": who})
        assert r.status_code == 200, r.text
        seen[who] = r.json()
        tok = r.json()["token"]
        seen[who]["agents"] = sorted(a["name"] for a in c.get("/api/agents", headers=h(tok)).json())
    assert seen["operator"]["access"]["level"] == "platform" and seen["operator"]["agents"] == ["Closer", "Sourced"]
    # the demo company sees the seeded (pre-accounts) fleet, so the demo shows every agent without re-onboarding
    assert seen["admin"]["access"]["level"] == "company" and seen["admin"]["agents"] == ["Closer", "Sourced"]
    assert seen["recruiter"]["access"]["level"] == "own_work" and seen["recruiter"]["agents"] == ["Sourced"]
    assert seen["recruiter"]["user"]["workspace_role"] == "member"
    assert c.post("/api/auth/demo").json()["access"]["level"] == "company"  # no body: as before, the demo company
    assert c.post("/api/auth/demo", json={"as": "god"}).status_code == 400


def test_seeded_fleet_default_workspace(c, monkeypatch):
    from app.agents import registry as reg
    from app.agents.models import Sponsor
    reg.onboard("Closer", "analyst", Sponsor(**SPONSOR), ["data.read"])  # seeded: no company
    acme = signup(c, "owner@acme.io")
    names = lambda tok: sorted(a["name"] for a in c.get("/api/agents", headers=h(tok)).json())
    demo = c.post("/api/auth/demo").json()["token"]
    assert names(demo) == ["Closer"] and names(acme) == []  # only the demo company, never a real one
    ledger = c.get("/api/ledger", headers=h(demo)).json()
    assert any((r.get("payload") or {}).get("agent_id") for r in (ledger if isinstance(ledger, list) else ledger.get("entries", [])))
    monkeypatch.setenv("AGAXES_DEFAULT_WORKSPACE", "none")
    assert names(demo) == []
    monkeypatch.setenv("AGAXES_DEFAULT_WORKSPACE", "acme.io")
    assert names(acme) == ["Closer"] and names(demo) == []
