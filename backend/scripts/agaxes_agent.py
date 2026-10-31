"""Agaxes client for an outside agent (Claude Code, a cron job, another company's bot), run on the agent's machine.

Every call is signed locally with the agent's own key; only signatures cross the wire. Talks to AGAXES_API_URL
(default http://localhost:8000).

An agent on another machine enrolls first, with the one-time token its employer's admin created
(POST /api/agents/enrollments). The key pair is made here and the private key never leaves this machine:

    python scripts/agaxes_agent.py enroll <token>          -> prints the agent id; key saved in ~/.agaxes/<agent_id>.json
    python scripts/agaxes_agent.py rotate <agent_id>       -> new key pair, passport re-issued, old key stops working
    python scripts/agaxes_agent.py ping <agent_id>         -> a signed heartbeat (enroll sends the first one itself)

Agents onboarded on the Agaxes server itself (in the same repo) fall back to the key in the registry store.

    python scripts/agaxes_agent.py next <agent_id> [--task <task_id>]
    python scripts/agaxes_agent.py progress <agent_id> <task_id> "what I just did" [--done N --total M]
    python scripts/agaxes_agent.py send <agent_id> <task_id> --name N --url U --company C --scope outreach.hiring "body"
    python scripts/agaxes_agent.py done <agent_id> <task_id> "final report" [--failed]

Prints STOP (exit code 3) whenever Agaxes tells the agent to stop: paused, suspended, offboarded, or task cancelled.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def home() -> Path:
    return Path(os.getenv("AGAXES_HOME") or Path.home() / ".agaxes")


def load_identity(agent_id: str) -> dict | None:
    f = home() / f"{agent_id}.json"
    return json.loads(f.read_text()) if f.exists() else None


def save_identity(agent_id: str, passport: dict, private_key: bytes) -> Path:
    home().mkdir(parents=True, exist_ok=True, mode=0o700)
    f = home() / f"{agent_id}.json"
    tmp = f.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # only this user can read the key
    with os.fdopen(fd, "w") as fh:
        json.dump({"agent_id": agent_id, "passport": passport,
                   "private_key": base64.b64encode(private_key).decode()}, fh, indent=2)
    tmp.replace(f)
    return f


def _new_key() -> tuple[bytes, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    raw = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw, base64.b64encode(pub).decode()


def _sign_raw(raw: bytes, data: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return base64.b64encode(Ed25519PrivateKey.from_private_bytes(raw).sign(data)).decode()


def enroll(api: str, token: str) -> int:
    """Make a key pair here, prove we hold it, and swap the one-time token for a passport bound to our key."""
    from app.agents.enroll import proof_text
    raw, pub = _new_key()
    r = httpx.post(f"{api}/api/agents/enroll", json={"token": token, "public_key": pub,
                                                     "proof": _sign_raw(raw, proof_text(token, pub).encode())}, timeout=120)
    if r.status_code >= 400:
        print(f"REFUSED ({r.status_code}): {r.json().get('detail', r.text)}")
        return 2
    res = r.json()
    agent = res["agent"]
    f = save_identity(agent["agent_id"], res["passport"], raw)
    print(json.dumps({"agent_id": agent["agent_id"], "name": agent["name"], "status": agent["status"],
                      "decision": res["verdict"]["decision"], "key_file": str(f)}, indent=2))
    print(f"Enrolled as {agent['name']} ({agent['agent_id']}). Private key kept at {f}; Agaxes only has the public key.")
    if agent["status"] != "active":
        return 3
    return ping(api, agent["agent_id"])  # the first signed call: completes the connection in the console


def ping(api: str, agent_id: str, text: str = "hello from my own machine") -> int:
    """A signed heartbeat. Agaxes checks the signature against the passport's key and records the first one."""
    from app.agents.models import Passport
    from app.agents.passport import sign_message
    from app.runtime.external import signed_text
    cur = load_identity(agent_id)
    if not cur:
        print(f"no local key for {agent_id} in {home()}")
        return 2
    ts = int(time.time())
    sig = sign_message(Passport.model_validate(cur["passport"]), base64.b64decode(cur["private_key"]),
                       signed_text("heartbeat", agent_id, None, ts, text))
    r = httpx.post(f"{api}/api/agents/heartbeat", json={"agent_id": agent_id, "ts": ts, "text": text, "signature": sig},
                   timeout=60)
    if r.status_code >= 400:
        print(f"REFUSED ({r.status_code}): {r.json().get('detail', r.text)}")
        return 2
    res = r.json()
    print(f"Heartbeat accepted{' (first signed call: connection complete)' if res.get('first') else ''}.")
    if res.get("stop"):
        print(f"STOP: {res.get('reason')}")
        return 3
    return 0


def rotate(api: str, agent_id: str) -> int:
    from app.agents.ledger import canonical
    from app.agents.models import Passport
    from app.agents.passport import sign_message
    from app.runtime.external import signed_text
    cur = load_identity(agent_id)
    if not cur:
        print(f"no local key for {agent_id} in {home()}: rotate from the machine that enrolled it")
        return 2
    raw, pub = _new_key()
    ts = int(time.time())
    text = signed_text("rotate_key", agent_id, None, ts, pub)
    old_sig = sign_message(Passport.model_validate(cur["passport"]), base64.b64decode(cur["private_key"]), text)
    new_proof = _sign_raw(raw, canonical({"agent_id": agent_id, "body": text}).encode())
    r = httpx.post(f"{api}/api/agents/{agent_id}/rotate_key", json={"new_public_key": pub, "ts": ts, "signature": old_sig,
                                                                    "new_key_proof": new_proof}, timeout=60)
    if r.status_code >= 400:
        print(f"REFUSED ({r.status_code}): {r.json().get('detail', r.text)}")
        return 2
    f = save_identity(agent_id, r.json()["passport"], raw)
    print(f"Key rotated for {agent_id}. New key at {f}; the old key no longer works.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("next"); n.add_argument("agent_id"); n.add_argument("--task")
    p = sub.add_parser("progress"); p.add_argument("agent_id"); p.add_argument("task_id"); p.add_argument("text")
    p.add_argument("--done", type=int); p.add_argument("--total", type=int)
    s = sub.add_parser("send"); s.add_argument("agent_id"); s.add_argument("task_id"); s.add_argument("body")
    s.add_argument("--name", required=True); s.add_argument("--url", required=True); s.add_argument("--company", required=True)
    s.add_argument("--scope", default="outreach.hiring")
    d = sub.add_parser("done"); d.add_argument("agent_id"); d.add_argument("task_id"); d.add_argument("text")
    d.add_argument("--failed", action="store_true")
    e = sub.add_parser("enroll"); e.add_argument("token")
    r = sub.add_parser("rotate"); r.add_argument("agent_id")
    hb = sub.add_parser("ping"); hb.add_argument("agent_id"); hb.add_argument("text", nargs="?", default="heartbeat")
    a = ap.parse_args()
    api = os.getenv("AGAXES_API_URL", "http://localhost:8000").rstrip("/")
    if a.cmd == "enroll":
        return enroll(api, a.token)
    if a.cmd == "rotate":
        return rotate(api, a.agent_id)
    if a.cmd == "ping":
        return ping(api, a.agent_id, a.text)

    from app.agents import registry
    from app.agents.models import Passport
    from app.agents.passport import sign_message
    from app.runtime.external import signed_text

    base = api + "/api/runtime/agent"
    local = load_identity(a.agent_id)
    if local:
        p_, key = Passport.model_validate(local["passport"]), base64.b64decode(local["private_key"])
    else:
        p_ = Passport.model_validate(registry.get_agent(a.agent_id)["passport"])
        key = registry.private_key(a.agent_id)

    def call(action: str, task_id: str | None, text: str = "", **extra) -> dict:
        ts = int(time.time())
        sig = sign_message(p_, key, signed_text(action, a.agent_id, task_id, ts, text))
        r = httpx.post(f"{base}/{action}", json={"agent_id": a.agent_id, "task_id": task_id, "ts": ts, "text": text,
                                                 "signature": sig, **extra}, timeout=120)
        if r.status_code >= 400:
            print(f"REFUSED ({r.status_code}): {r.json().get('detail', r.text)}")
            sys.exit(2)
        return r.json()

    if a.cmd == "next":
        res = call("claim", a.task)
    elif a.cmd == "progress":
        res = call("progress", a.task_id, a.text, done=a.done, total=a.total)
    elif a.cmd == "done":
        res = call("complete", a.task_id, a.text, ok=not a.failed)
    else:
        r = httpx.post(f"{base}/send", json={"agent_id": a.agent_id, "task_id": a.task_id, "body": a.body, "scope": a.scope,
                                             "to": {"name": a.name, "profile_url": a.url, "company": a.company},
                                             "signature": sign_message(p_, key, a.body)}, timeout=300)
        res = r.json() if r.status_code < 400 else {"stop": True, "reason": r.text}
    print(json.dumps(res, indent=2))
    if res.get("stop"):
        print(f"STOP: {res.get('reason')}. Do nothing else on this task.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
