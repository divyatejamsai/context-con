"""The sent-message store: one record per email, with its status history and any replies.

File: backend/data/messages.json (MESSAGES_PATH overrides), gitignored with the rest of backend/data.
Status moves forward only: blocked | failed | sent -> delivered -> replied (bounced and complained are final).
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
_lock = threading.Lock()

# later statuses win; bounced/complained/failed are final
ORDER = {"blocked": 0, "failed": 0, "sent": 1, "delivery_delayed": 1, "delivered": 2, "opened": 3, "clicked": 3,
         "replied": 4, "bounced": 5, "complained": 5}
FINAL = {"blocked", "failed", "bounced", "complained"}


def path() -> Path:
    return Path(os.getenv("MESSAGES_PATH") or REPO_ROOT / "backend" / "data" / "messages.json")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict[str, dict]:
    p = path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text() or "{}")
    except json.JSONDecodeError:
        return {}


def _save(rows: dict[str, dict]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1, default=str))
    tmp.replace(p)


def create(rec: dict[str, Any]) -> dict:
    rec = {"id": "msg_" + uuid.uuid4().hex[:12], "created_at": now(), "events": [], "replies": [], **rec}
    rec["events"] = rec["events"] or [{"ts": rec["created_at"], "status": rec.get("status", "sent"), "detail": rec.get("detail", "")}]
    with _lock:
        rows = _load()
        rows[rec["id"]] = rec
        _save(rows)
    return rec


def get(msg_id: str) -> dict | None:
    return _load().get(msg_id)


def list_all(agent_id: str | None = None, profile_url: str | None = None, thread_key: str | None = None) -> list[dict]:
    rows = sorted(_load().values(), key=lambda r: r.get("created_at", ""), reverse=True)
    if agent_id:
        rows = [r for r in rows if r.get("agent_id") == agent_id]
    if profile_url:
        from ..agents.graph import norm_url
        rows = [r for r in rows if norm_url((r.get("to") or {}).get("profile_url")) == norm_url(profile_url)]
    if thread_key:
        rows = [r for r in rows if r.get("thread_key") == thread_key]
    return rows


def set_status(msg_id: str, status: str, detail: str = "") -> dict | None:
    """Move a message forward. Returns the record if it changed, else None."""
    with _lock:
        rows = _load()
        r = rows.get(msg_id)
        if not r or r.get("status") in FINAL or ORDER.get(status, -1) <= ORDER.get(r.get("status"), -1):
            return None
        r["status"] = status
        r["events"].append({"ts": now(), "status": status, "detail": detail})
        _save(rows)
        return r


def add_reply(msg_id: str, reply: dict) -> dict | None:
    """Attach a reply (deduplicated by its Message-ID). Returns the record if the reply is new."""
    with _lock:
        rows = _load()
        r = rows.get(msg_id)
        if not r or any(x.get("message_id") == reply.get("message_id") for x in r["replies"]):
            return None
        r["replies"].append(reply)
        if r.get("status") not in FINAL:
            r["status"] = "replied"
        r["events"].append({"ts": now(), "status": "replied", "detail": f"reply from {reply.get('from')}"})
        _save(rows)
        return r


def public(r: dict) -> dict:
    """What the API returns (everything; kept as a hook in case fields need hiding)."""
    return r
