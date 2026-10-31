"""Append-only, hash-chained ledger (docs/COUNTERSIGN.md part 4).

Each line of the JSONL file is {seq, ts, kind, payload, sources, prev_hash, hash}, where
hash = sha256(canonical JSON of every other field). Entries written while serving a signed-in request also carry
`actor` (who, from their session or the admin token, never from the request body), covered by the same hash. Editing, deleting or reordering any line breaks
the chain from that line on, and verify_chain() reports the first bad seq.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..schemas import Source

try:
    import fcntl
except ImportError:  # Windows: in-process lock only
    fcntl = None

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


def _read_raw(p: Path | None = None) -> list[dict]:
    p = p or path()
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


class _Tail:
    """What append() and is_revoked() need, kept up to date by reading only the bytes added since last time.
    Without it every append re-read the whole file (O(n^2) over a long eval). verify_chain() still reads it all."""

    def __init__(self) -> None:
        self.ino, self.offset, self.count, self.last_hash = None, 0, 0, GENESIS
        self.revoked: dict[str, dict | None] = {}


_tails: dict[str, _Tail] = {}


def _sync(p: Path) -> _Tail:
    t = _tails.setdefault(str(p), _Tail())
    if not p.exists():
        _tails[str(p)] = t = _Tail()
        return t
    st = p.stat()
    if st.st_ino != t.ino or st.st_size < t.offset:  # new, replaced or truncated file: start over
        _tails[str(p)] = t = _Tail()
        t.ino = st.st_ino
    if st.st_size == t.offset:
        return t
    with p.open("rb") as f:
        f.seek(t.offset)
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1  # only whole lines; a half-written last line is read next time
    for line in chunk[:end].decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            r = {"_corrupt": line}
        t.count += 1
        t.last_hash = r.get("hash", t.last_hash)
        if r.get("kind") in ("passport.revoked", "passport.reinstated"):
            for aid in {(r.get("payload") or {}).get(k) for k in ("agent_id", "subject")} - {None}:
                t.revoked[aid] = r if r["kind"] == "passport.revoked" else None
    t.offset += end
    return t


@contextmanager
def _file_lock(p: Path):
    """Cross-process lock next to the ledger, so two writers can't both claim the same seq."""
    with open(p.with_suffix(p.suffix + ".lock"), "a") as fh:
        if fcntl:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_UN)


def append(kind: str, payload: dict, sources: list[Source] | list[dict] | None = None) -> str:
    """Record an event; returns its hash. Sources are the Crustdata citations behind it."""
    srcs = [s.model_dump() if isinstance(s, Source) else dict(s) for s in (sources or []) if s]
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock, _file_lock(p):  # the API, the MCP server and scripts may append to the same file
        tail = _sync(p)
        prev = tail.last_hash
        entry = {
            "seq": tail.count,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            "payload": json.loads(canonical(payload)),
            "sources": srcs,
            "prev_hash": prev,
        }
        actor = _actor()
        if actor:
            entry["actor"] = actor
        entry["hash"] = entry_hash(entry)
        with p.open("a") as f:
            f.write(canonical(entry) + "\n")
    return entry["hash"]


def _actor() -> dict | None:
    try:
        from ..accounts.authz import current
    except ImportError:
        return None
    p = current()
    return p.actor() if p is not None and p.via != "open" else None


def verify_chain(p: Path | None = None) -> tuple[bool, int | None]:
    """(ok, first bad seq). A line is bad if its hash doesn't match its content or doesn't link to the previous one.
    p checks another copy of a ledger (e.g. one handed over for audit) instead of the live one."""
    prev = GENESIS
    for i, e in enumerate(_read_raw(p)):
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
    with _lock:
        return _sync(path()).revoked.get(agent_id)
