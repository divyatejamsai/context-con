"""Company accounts: sign-up, login, sessions, lockout, workspace joining and the demo account."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.accounts import api as auth_api
from app.accounts.store import AccountStore, hash_password, verify_password
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    async def no_identify(domain):  # keep unit tests offline; live identify is exercised on the Mac
        return {"name": "Acme", "crustdata_company_id": 42, "industry": "Software"} if domain == "acme.io" else None
    monkeypatch.setattr(auth_api, "identify_company", no_identify)
    auth_api.reset_store(AccountStore(tmp_path / "accounts.db"))
    yield TestClient(app)
    auth_api.reset_store(None)


SIGNUP = {"email": "priya@acme.io", "password": "correct horse battery", "full_name": "Priya Rao",
          "job_role": "Head of Talent", "company_name": "Acme", "size_band": "51-200", "hiring_volume": "6-20",
          "hiring_for": ["Engineering"], "accept_terms": True}


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pass")
    assert h.startswith("scrypt$") and "s3cret" not in h
    assert verify_password("s3cret-pass", h) and not verify_password("wrong", h)


def test_signup_login_me_logout(client):
    r = client.post("/api/auth/signup", json=SIGNUP)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["workspace_role"] == "owner"
    assert body["company"]["domain"] == "acme.io" and body["company"]["verified_via"] == "crustdata"
    assert body["company"]["crustdata_company_id"] == 42
    tok = body["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json()["user"]["email"] == "priya@acme.io"

    login = client.post("/api/auth/login", json={"email": "PRIYA@acme.io", "password": SIGNUP["password"]})
    assert login.status_code == 200 and login.json()["token"] != tok

    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {tok}"})
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_rejects_personal_email_weak_password_and_duplicates(client):
    assert client.post("/api/auth/signup", json={**SIGNUP, "email": "x@gmail.com"}).json()["error"] == "personal_email"
    assert client.post("/api/auth/lookup", json={"email": "x@gmail.com"}).json()["error"] == "personal_email"
    assert client.post("/api/auth/signup", json={**SIGNUP, "password": "short"}).json()["field"] == "password"
    assert client.post("/api/auth/signup", json={**SIGNUP, "accept_terms": False}).json()["field"] == "accept_terms"
    assert client.post("/api/auth/signup", json=SIGNUP).status_code == 200
    assert client.post("/api/auth/signup", json=SIGNUP).status_code == 409


def test_second_person_joins_existing_workspace(client):
    client.post("/api/auth/signup", json=SIGNUP)
    look = client.post("/api/auth/lookup", json={"email": "sam@acme.io"}).json()
    assert look["existing_workspace"]["name"] == "Acme"
    r = client.post("/api/auth/signup", json={**SIGNUP, "email": "sam@acme.io", "full_name": "Sam", "company_name": ""})
    assert r.status_code == 200, r.text
    assert r.json()["joined_existing"] and r.json()["user"]["workspace_role"] == "member"


def test_unverified_domain_is_self_reported(client):
    r = client.post("/api/auth/signup", json={**SIGNUP, "email": "a@tiny-startup.dev", "company_name": "Tiny"})
    assert r.json()["company"]["verified_via"] == "self_reported"


def test_lockout_after_repeated_wrong_passwords(client):
    client.post("/api/auth/signup", json=SIGNUP)
    codes = [client.post("/api/auth/login", json={"email": SIGNUP["email"], "password": "nope"}).status_code
             for _ in range(5)]
    assert codes == [401] * 5
    r = client.post("/api/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    assert r.status_code == 429 and r.json()["error"] == "locked"


def test_unknown_email_and_bad_token(client):
    r = client.post("/api/auth/login", json={"email": "ghost@acme.io", "password": "whatever-123"})
    assert r.status_code == 401 and r.json()["error"] == "bad_credentials"
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_demo_workspace(client, monkeypatch):
    r = client.post("/api/auth/demo")
    assert r.status_code == 200 and r.json()["company"]["name"] == "Sourced Demo Co"
    monkeypatch.setenv("DEMO_ACCOUNT", "0")
    assert client.post("/api/auth/demo").status_code == 404


def test_band_mapping():
    assert auth_api._band("1001-5000") == "1001-5000"
    assert auth_api._band("10001+") == "5001+"
    assert auth_api._band("11-50") == "11-50"
    assert auth_api._band(None) is None
