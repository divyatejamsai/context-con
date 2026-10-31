"""One-click Approve / Reject links for alerts: signed, expiring, single-use, bound to one person.

A link is  base64url(json claims) "." base64url(HMAC-SHA256(secret, that first part)).  Claims:
    a  approval id          d  "approve" | "reject"      u  user id (None when no accounts exist yet)
    e  that person's email  x  expiry (unix seconds)     j  link id, shared by one alert's Approve/Reject pair
The secret is ALERT_LINK_SECRET, else a random key kept in backend/data/alert_link.key (created on first use, 0600).
Single use is enforced by app/alerts/core.py, which records the link id the moment an action goes through.
Opening a link (GET) never acts: mail scanners prefetch links, so the action is the POST from the page it opens.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

LINK_HOURS = float(os.getenv("ALERT_LINK_HOURS", "24"))
ACTIONS = ("approve", "reject")


class LinkError(Exception):
    """The link is forged, expired, used, or for something that no longer exists."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _key_path() -> Path:
    from ..runtime.store import path as runtime_path
    return Path(os.getenv("ALERT_LINK_KEY_PATH") or runtime_path().parent / "alert_link.key")


def _secret() -> bytes:
    if os.getenv("ALERT_LINK_SECRET"):
        return os.environ["ALERT_LINK_SECRET"].encode()
    p = _key_path()
    try:
        return bytes.fromhex(p.read_text().strip())
    except (OSError, ValueError):
        p.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        p.write_text(key.hex())
        try:
            p.chmod(0o600)
        except OSError:
            pass
        return key


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make(approval_id: str, action: str, user: dict | None, link_id: str, *, hours: float | None = None) -> str:
    if action not in ACTIONS:
        raise ValueError(action)
    claims = {"a": approval_id, "d": action, "u": (user or {}).get("id"), "e": (user or {}).get("email"),
              "x": int(time.time() + 3600 * (hours if hours is not None else LINK_HOURS)), "j": link_id}
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read(token: str) -> dict:
    """Claims of a genuine, unexpired link. Raises LinkError otherwise (single use is checked by the caller)."""
    try:
        body, sig = token.strip().split(".")
        want = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            raise ValueError
        claims = json.loads(_unb64(body))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise LinkError("invalid", "This link isn't a genuine Agaxes link.") from None
    if claims.get("d") not in ACTIONS or not claims.get("a") or not claims.get("j"):
        raise LinkError("invalid", "This link isn't a genuine Agaxes link.")
    if time.time() > claims.get("x", 0):
        raise LinkError("expired", "This link has expired. Open the console to decide instead.")
    return claims
