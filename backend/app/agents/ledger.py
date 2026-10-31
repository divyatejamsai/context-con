"""Append-only, hash-chained ledger (docs/COUNTERSIGN.md part 4).

Each line of the JSONL file is {seq, ts, kind, payload, sources, prev_hash, hash}, where
hash = sha256(canonical JSON of every other field). Editing, deleting or reordering any line breaks
the chain from that line on, and verify_chain() reports the first bad seq.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..schemas import Source

REPO_ROOT = Path(__file__).resolve().parents[3]
GENESIS = "0" * 64
_lock = threading.Lock()


def path() -> Path:
    return Path(os.getenv("LEDGER_PATH", REPO_ROOT / "backend" / "data" / "ledger.jsonl"))


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def _read_raw() -> list[dict]:
    p = path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"seq": len(out), "_corrupt": line})
    return out


def append(kind: str, payload: dict, sources: list[Source] | list[dict] | None = None) -> str:
    """Record an event; returns its hash. Sources are the Crustdata citations behind it."""
    srcs = [s.model_dump() if isinstance(s, Source) else dict(s) for s in (sources or []) if s]
    with _lock:
        rows = _read_raw()
        prev = rows[-1].get("hash", GENESIS) if rows else GENESIS
        entry = {
            "seq": len(rows),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            "payload": json.loads(canonical(payload)),
            "sources": srcs,
            "prev_hash": prev,
        }
        entry["hash"] = entry_hash(entry)
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(canonical(entry) + "\n")
    return entry["hash"]


def verify_chain() -> tuple[bool, int | None]:
    """(ok, first bad seq). A line is bad if its hash doesn't match its content or doesn't link to the previous one."""
    prev = GENESIS
    for i, e in enumerate(_read_raw()):
        if "_corrupt" in e or e.get("seq") != i or e.get("prev_hash") != prev or entry_hash(e) != e.get("hash"):
            return False, i
        prev = e["hash"]
    return True, None


def entries(agent_id: str | None = None, kind: str | None = None) -> list[dict]:
    rows = _read_raw()
    if agent_id:
        rows = [r for r in rows if _mentions(r, agent_id)]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    return rows


def _mentions(row: dict, agent_id: str) -> bool:
    p = row.get("payload") or {}
    return p.get("agent_id") == agent_id or p.get("subject") == agent_id or (p.get("passport") or {}).get("agent_id") == agent_id


def is_revoked(agent_id: str) -> dict | None:
    """Latest revoke/reinstate entry wins. Returns the revoke entry if the agent is currently revoked."""
    state = None
    for r in entries(agent_id):
        if r.get("kind") == "passport.revoked":
            state = r
        elif r.get("kind") == "passport.reinstated":
            state = None
    return state
