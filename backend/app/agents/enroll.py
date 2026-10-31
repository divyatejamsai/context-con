"""Onboarding an outside agent (Claude Code on a laptop, another company's bot) without Agaxes ever holding its key.

1. An admin creates an enrollment: who the agent is (name, role, sponsor, scopes). Agaxes returns a one-time token,
   shown once, valid for ttl_minutes (default 60). Only the token's SHA-256 is stored.
2. On its own machine the agent makes an Ed25519 key pair and calls POST /api/agents/enroll with the token, its
   public key, and a proof: its signature over  agaxes|enroll|<sha256(token)>|<public_key>  (so a token sniffed in
   transit can't be paired with someone else's key without also holding that key).
3. Agaxes onboards the agent with that public key (key_custody "agent", no private key stored), runs the live
   sponsor check, and burns the token. A second use, an expired or revoked token all fail.

Key rotation: the agent signs  agaxes|rotate_key|<agent_id>||<ts>|<new_public_key>  with its current key and
the same text with the new key; Agaxes re-issues the passport bound to the new key.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ledger, registry
from .models import Sponsor

_lock = threading.Lock()
MAX_TTL_MINUTES = 7 * 24 * 60


class EnrollError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _path() -> Path:
    return registry._path().parent / "enrollments.json"


def _load() -> dict[str, dict]:
    p = _path()
    return json.loads(p.read_text() or "{}") if p.exists() else {}


def _save(rows: dict[str, dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2))
    tmp.replace(p)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def proof_text(token: str, public_key: str) -> str:
    return f"agaxes|enroll|{token_hash(token)}|{public_key}"


def status_of(row: dict, now: datetime | None = None) -> str:
    if row.get("used_at"):
        return "used"
    if row.get("revoked_at"):
        return "revoked"
    if datetime.fromisoformat(row["expires_at"]) <= (now or _now()):
        return "expired"
    return "pending"


def public(row: dict) -> dict:
    return {**{k: v for k, v in row.items() if k != "token_hash"}, "status": status_of(row)}


def create(*, name: str, role: str, sponsor: Sponsor, scopes: list[str] | None, days: int, job: str | None,
           ttl_minutes: int, workspace_id: str | None, created_by: str) -> tuple[dict, str]:
    """Returns (enrollment, token). The token is shown once."""
    if not name.strip():
        raise EnrollError("agent name is required")
    if not 1 <= ttl_minutes <= MAX_TTL_MINUTES:
        raise EnrollError(f"ttl_minutes must be between 1 and {MAX_TTL_MINUTES}")
    key = registry.role_key(role)
    role_title = registry.ROLES[key]["title"] if key else role.strip()
    try:
        registry.check_ceiling(role_title, list(scopes or (registry.ROLES[key]["default_scopes"] if key else ["data.read"])))
    except registry.RegistryError as e:
        raise EnrollError(str(e))
    token = "agx_enr_" + secrets.token_urlsafe(32)
    now = _now()
    row = {
        "enrollment_id": f"enr_{uuid.uuid4().hex[:12]}",
        "token_hash": token_hash(token),
        "name": name.strip(), "role": role, "sponsor": sponsor.model_dump(), "scopes": scopes, "days": days,
        "job": job, "workspace_id": workspace_id, "created_by": created_by,
        "created_at": _iso(now), "expires_at": _iso(now + timedelta(minutes=ttl_minutes)),
        "used_at": None, "revoked_at": None, "agent_id": None,
    }
    with _lock:
        rows = _load()
        rows[row["enrollment_id"]] = row
        _save(rows)
    ledger.append("agent.enrollment_created", {k: row[k] for k in ("enrollment_id", "name", "role", "scopes",
                                                                    "workspace_id", "created_by", "expires_at")})
    return public(row), token


def list_all(workspace_id: str | None = None, scoped: bool = False) -> list[dict]:
    with _lock:
        rows = list(_load().values())
    if scoped:
        rows = [r for r in rows if r.get("workspace_id") == workspace_id]
    return [public(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]


def revoke(enrollment_id: str, by: str, workspace_id: str | None = None, scoped: bool = False) -> dict:
    with _lock:
        rows = _load()
        row = rows.get(enrollment_id)
        if not row or (scoped and row.get("workspace_id") != workspace_id):
            raise EnrollError("no such enrollment", 404)
        if status_of(row) != "pending":
            raise EnrollError(f"this enrollment is already {status_of(row)}")
        row["revoked_at"] = _iso(_now())
        _save(rows)
    ledger.append("agent.enrollment_revoked", {"enrollment_id": enrollment_id, "by": by})
    return public(row)


def claim(token: str, public_key: str, proof: str) -> dict:
    """Checks the token and the proof of key possession, then burns the token. Returns the enrollment row.
    The caller onboards the agent; if that fails it calls release() so the admin's link isn't wasted."""
    from .passport import normalise_public_key, verify_raw
    try:
        public_key = normalise_public_key(public_key)
    except ValueError as e:
        raise EnrollError(str(e))
    th = token_hash(token)
    with _lock:
        rows = _load()
        row = next((r for r in rows.values() if r["token_hash"] == th), None)
        if row is None:
            raise EnrollError("this enrollment link isn't valid", 401)
        st = status_of(row)
        if st != "pending":
            raise EnrollError(f"this enrollment link is {st}: ask your admin for a new one", 401)
        if not verify_raw(public_key, proof_text(token, public_key), proof or ""):
            raise EnrollError("proof doesn't match the public key: sign the enrollment text with the new key", 401)
        if any(a["passport"]["public_key"] == public_key for a in registry.list_agents()):
            raise EnrollError("this public key already belongs to another agent: make a fresh key pair")
        row["used_at"] = _iso(_now())
        _save(rows)
    return {**row, "public_key": public_key}


def release(enrollment_id: str) -> None:
    with _lock:
        rows = _load()
        if enrollment_id in rows:
            rows[enrollment_id]["used_at"] = None
            _save(rows)


def finish(enrollment_id: str, agent_id: str) -> None:
    with _lock:
        rows = _load()
        rows[enrollment_id]["agent_id"] = agent_id
        _save(rows)


def rotate_text(agent_id: str, ts: int, new_public_key: str) -> str:
    from ..runtime.external import signed_text
    return signed_text("rotate_key", agent_id, None, ts, new_public_key)
