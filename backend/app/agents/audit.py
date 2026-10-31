"""Audit export: the ledger as a file an auditor can keep, check offline, and load into a spreadsheet or a SIEM.

JSONL export: line 1 is a signed manifest, every other line is a ledger entry exactly as stored.

    {"type": "agaxes.audit_export/v1", "generated_at", "generated_by", "filters", "count", "first_seq", "last_seq",
     "entries_sha256", "head": {seq, hash}, "chain_ok", "issuer": {key_id, public_key}, "issuer_signature"}

To check it (verify_export(), scripts/verify_export.py):
  1. each entry hashes to the hash it carries (nothing edited);
  2. where two exported entries are consecutive (seq n and n+1), the second's prev_hash is the first's hash;
     a full export (no filters) must be one unbroken chain from seq 0;
  3. sha256 of the entry lines equals entries_sha256 (nothing added, dropped or reordered);
  4. issuer_signature verifies over the manifest with the issuer key at GET /api/passport/issuer.

CSV export: one row per entry (seq, ts, kind, agent, actor, payload, hash, prev_hash), with the same manifest's
sha256 and signature in the X-Agaxes-Export-* response headers. The CSV is for reading; the JSONL is the evidence.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import ledger
from .passport import issuer_key, issuer_key_id, issuer_public_key

TYPE = "agaxes.audit_export/v1"


def _entries_digest(rows: Iterable[dict]) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update((ledger.canonical(r) + "\n").encode())
    return h.hexdigest()


def _in_window(row: dict, since: str | None, until: str | None) -> bool:
    ts = row.get("ts") or ""
    return (not since or ts >= since) and (not until or ts <= until)


def build(rows: list[dict], *, filters: dict, generated_by: dict | None) -> dict:
    """The signed manifest for these rows (already filtered by the caller)."""
    allrows = ledger._read_raw()
    ok, bad = ledger.verify_chain()
    body: dict[str, Any] = {
        "type": TYPE,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_by": generated_by,
        "filters": {k: v for k, v in filters.items() if v},
        "count": len(rows),
        "first_seq": rows[0].get("seq") if rows else None,
        "last_seq": rows[-1].get("seq") if rows else None,
        "entries_sha256": _entries_digest(rows),
        "head": {"seq": allrows[-1].get("seq"), "hash": allrows[-1].get("hash")} if allrows else None,
        "chain_ok": ok, "first_bad_seq": bad,
        "issuer": {"key_id": issuer_key_id(), "public_key": issuer_public_key()},
    }
    body["issuer_signature"] = base64.b64encode(issuer_key().sign(ledger.canonical(body).encode())).decode()
    return body


def select(*, agent_id: str | None, kind: str | None, since: str | None, until: str | None,
           visible=lambda r: True) -> list[dict]:
    return [r for r in ledger.entries(agent_id, kind) if _in_window(r, since, until) and visible(r)]


def to_jsonl(manifest: dict, rows: list[dict]) -> str:
    return "".join(ledger.canonical(x) + "\n" for x in [manifest, *rows])


def _agent_of(row: dict) -> str:
    p = row.get("payload") or {}
    return p.get("agent_id") or p.get("subject") or (p.get("passport") or {}).get("agent_id") or ""


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seq", "ts", "kind", "agent_id", "actor", "actor_via", "payload", "sources", "hash", "prev_hash"])
    for r in rows:
        a = r.get("actor") or {}
        payload = ledger.canonical(r.get("payload") or {})
        if payload[:1] in "=+-@":  # spreadsheet formula injection: never let a cell start a formula
            payload = "'" + payload
        w.writerow([r.get("seq"), r.get("ts"), r.get("kind"), _agent_of(r), a.get("email") or a.get("approved_by") or "",
                    a.get("via") or "", payload, len(r.get("sources") or []), r.get("hash"), r.get("prev_hash")])
    return buf.getvalue()


def verify_export(text: str, issuer_public_key_b64: str | None = None) -> dict:
    """Checks a JSONL export offline. issuer_public_key_b64 defaults to the key the manifest names, so pass the one
    from GET /api/passport/issuer to also prove the export came from this Agaxes."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    lines = [ln for ln in text.splitlines() if ln.strip()]
    try:
        manifest = json.loads(lines[0])
        rows = [json.loads(ln) for ln in lines[1:]]
    except (IndexError, json.JSONDecodeError):
        return {"ok": False, "checks": [{"name": "format", "status": "fail", "detail": "not an Agaxes JSONL export"}]}
    add("format", manifest.get("type") == TYPE, f"manifest type {manifest.get('type')}")

    edited = [r.get("seq") for r in rows if ledger.entry_hash(r) != r.get("hash")]
    add("entries_unedited", not edited, "every entry hashes to the hash it carries" if not edited
        else f"entries edited after they were written: seq {edited[:5]}")

    broken = [b.get("seq") for a, b in zip(rows, rows[1:])
              if b.get("seq") == (a.get("seq") or 0) + 1 and b.get("prev_hash") != a.get("hash")]
    if not manifest.get("filters"):
        starts = not rows or (rows[0].get("seq") == 0 and rows[0].get("prev_hash") == ledger.GENESIS)
        gaps = [b.get("seq") for a, b in zip(rows, rows[1:]) if b.get("seq") != (a.get("seq") or 0) + 1]
        broken += gaps + ([] if starts else [rows[0].get("seq")])
    add("chain_links", not broken, "consecutive entries link to each other" if not broken
        else f"chain broken or entries missing at seq {broken[:5]}")

    digest_ok = _entries_digest(rows) == manifest.get("entries_sha256") and len(rows) == manifest.get("count")
    add("entries_match_manifest", digest_ok, f"{len(rows)} entries, same digest as signed" if digest_ok
        else "entries were added, removed or reordered after export")

    sig = manifest.get("issuer_signature") or ""
    body = {k: v for k, v in manifest.items() if k != "issuer_signature"}
    key = issuer_public_key_b64 or (manifest.get("issuer") or {}).get("public_key") or ""
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(base64.b64decode(sig), ledger.canonical(body).encode())
        sig_ok = True
    except (InvalidSignature, ValueError, TypeError):
        sig_ok = False
    add("issuer_signature", sig_ok, "signed by the Agaxes issuer key" if sig_ok
        else "signature doesn't verify: the manifest was changed, or another key signed it")
    return {"ok": all(c["status"] == "pass" for c in checks), "checks": checks, "count": len(rows),
            "chain_ok_at_export": manifest.get("chain_ok")}
