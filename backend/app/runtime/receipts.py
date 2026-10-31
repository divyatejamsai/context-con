"""Receipts: proof of one action that a third party (a candidate, an auditor) can check without trusting us.

A receipt carries the ledger entry itself, the entry before it (its hash is the entry's prev_hash), the ledger head
at the time of issue, and Countersign's Ed25519 signature over all of that. To check one:

  1. recompute sha256(canonical(entry without "hash")) and compare with entry.hash: the entry wasn't edited;
  2. check entry.prev_hash == previous.hash, and recompute previous.hash too: it sits in the chain where it says;
  3. verify issuer_signature over canonical(receipt without the signature) with the issuer public key published at
     GET /api/passport/issuer (the same key that signs every passport);
  4. optionally ask Countersign (POST /api/runtime/receipts/verify) whether the live ledger still holds that hash at
     that seq: if someone rewrote history after issuing the receipt, this is where it shows.

verify_receipt() does 1-3 offline and 4 against the local ledger; scripts/verify_receipt.py runs it on a file.
"""
from __future__ import annotations

import base64
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..agents import ledger
from ..agents.passport import issuer_key, issuer_key_id, issuer_public_key
from . import store


def _rows() -> list[dict]:
    return ledger._read_raw()


def issue(entry_hash: str) -> dict:
    rows = _rows()
    i = next((n for n, e in enumerate(rows) if e.get("hash") == entry_hash or e.get("hash", "").startswith(entry_hash)), None)
    if i is None:
        raise KeyError(entry_hash)
    ok, bad = ledger.verify_chain()
    body: dict[str, Any] = {
        "type": "countersign.receipt/v1", "issued_at": store.now(),
        "entry": rows[i], "previous": rows[i - 1] if i > 0 else None,
        "head": {"seq": rows[-1].get("seq"), "hash": rows[-1].get("hash")},
        "chain_ok_at_issue": ok, "issuer": {"key_id": issuer_key_id(), "public_key": issuer_public_key()},
    }
    sig = issuer_key().sign(ledger.canonical(body).encode())
    return {**body, "issuer_signature": base64.b64encode(sig).decode()}


def verify_receipt(r: dict, *, check_live: bool = True) -> dict:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    e, prev = r.get("entry") or {}, r.get("previous")
    add("entry_hash", ledger.entry_hash(e) == e.get("hash"), "the entry hashes to the hash it carries"
        if ledger.entry_hash(e) == e.get("hash") else "the entry was edited after it was written")
    if prev is None:
        add("chain_link", e.get("seq") == 0, "first entry of the ledger" if e.get("seq") == 0
            else "the entry before it is missing from the receipt")
    else:
        link = ledger.entry_hash(prev) == prev.get("hash") and e.get("prev_hash") == prev.get("hash")
        add("chain_link", link, f"links to entry #{prev.get('seq')}" if link else "does not link to the entry before it")
    body = {k: v for k, v in r.items() if k != "issuer_signature"}
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(issuer_public_key()))
        pub.verify(base64.b64decode(r.get("issuer_signature") or ""), ledger.canonical(body).encode())
        same_key = (r.get("issuer") or {}).get("public_key") == issuer_public_key()
        add("issuer_signature", same_key, "signed by this Agaxes issuer" if same_key
            else "signed with a different key than this issuer's")
    except (InvalidSignature, ValueError):
        add("issuer_signature", False, "the receipt's signature does not verify: it was altered or forged")
    if check_live:
        live = next((x for x in _rows() if x.get("seq") == e.get("seq")), None)
        same = bool(live) and live.get("hash") == e.get("hash")
        add("still_on_ledger", same, f"the live ledger still holds this entry at #{e.get('seq')}" if same
            else "the live ledger no longer matches this receipt: history was rewritten")
    return {"valid": all(c["status"] == "pass" for c in checks), "checks": checks,
            "entry": {"seq": e.get("seq"), "kind": e.get("kind"), "ts": e.get("ts"), "hash": e.get("hash")}}
