"""SQLite store for company workspaces, users and sessions.

- Passwords are hashed with scrypt (stdlib, per-user 16-byte salt). Plain passwords are never stored or logged.
- Session tokens are 256-bit random values. Only their SHA-256 is stored, so a leaked DB can't be replayed.
- Sessions expire after SESSION_DAYS (default 14) and slide forward on use, so a recruiter isn't logged out
  mid-week (a common ATS complaint), but an idle laptop still times out.
- After MAX_FAILED wrong passwords an account locks for LOCK_MINUTES.

DB path: backend/data/accounts.db (gitignored with the rest of backend/data/), override with ACCOUNTS_DB.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "accounts.db"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))
MAX_FAILED = 5
RESET_MINUTES = 30
RESETS_PER_HOUR = 3
LOCK_MINUTES = 10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT NOT NULL UNIQUE,
  size_band TEXT,
  industry TEXT,
  hq_country TEXT,
  hiring_volume TEXT,
  hiring_for TEXT,          -- JSON list
  current_ats TEXT,
  crustdata_company_id INTEGER,
  verified_via TEXT,        -- 'crustdata' when Company Identify matched the email domain, else 'self_reported'
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL REFERENCES companies(id),
  email TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  job_role TEXT,
  workspace_role TEXT NOT NULL,   -- 'owner' (created the workspace) or 'member'
  password_hash TEXT NOT NULL,
  failed_logins INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  created_at TEXT NOT NULL,
  last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  user_agent TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS password_resets (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(dk) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), dk)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class AccountStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("ACCOUNTS_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    # ---- reads -------------------------------------------------------------
    def company_by_domain(self, domain: str) -> dict | None:
        row = self._db.execute("SELECT * FROM companies WHERE domain = ?", (domain.lower(),)).fetchone()
        return _company(row) if row else None

    def user_by_email(self, email: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()

    def members(self, company_id: str) -> list[dict]:
        rows = self._db.execute("SELECT * FROM users WHERE company_id = ? ORDER BY created_at", (company_id,)).fetchall()
        return [_user(r) for r in rows]

    # ---- writes ------------------------------------------------------------
    def create_account(self, *, email: str, password: str, full_name: str, job_role: str | None,
                       company: dict[str, Any]) -> tuple[dict, dict, bool]:
        """Creates the user, and the company workspace if this domain has none yet.

        Returns (user, company, joined_existing). A second person from the same domain joins the existing
        workspace as a member instead of creating a duplicate one.
        """
        email = email.lower().strip()
        domain = email.rsplit("@", 1)[1]
        with self._lock:
            if self.user_by_email(email):
                raise AuthError("email_taken", "An account with this email already exists. Log in instead.", 409)
            existing = self.company_by_domain(domain)
            now = _iso(_now())
            if existing:
                company_id, joined = existing["id"], True
            else:
                company_id, joined = f"co_{uuid.uuid4().hex[:12]}", False
                self._db.execute(
                    "INSERT INTO companies (id, name, domain, size_band, industry, hq_country, hiring_volume, hiring_for,"
                    " current_ats, crustdata_company_id, verified_via, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (company_id, company["name"].strip(), domain, company.get("size_band"), company.get("industry"),
                     company.get("hq_country"), company.get("hiring_volume"), json.dumps(company.get("hiring_for") or []),
                     company.get("current_ats"), company.get("crustdata_company_id"),
                     company.get("verified_via") or "self_reported", now))
            user_id = f"usr_{uuid.uuid4().hex[:12]}"
            self._db.execute(
                "INSERT INTO users (id, company_id, email, full_name, job_role, workspace_role, password_hash, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (user_id, company_id, email, full_name.strip(), job_role, "member" if joined else "owner",
                 hash_password(password), now))
            self._db.commit()
        return self.user(user_id), self.company(company_id), joined

    def authenticate(self, email: str, password: str) -> dict:
        row = self.user_by_email(email.strip())
        now = _now()
        if row is None:
            verify_password(password, hash_password("timing-equaliser"))  # don't reveal which emails exist via timing
            raise AuthError("bad_credentials", "Email or password is incorrect.", 401)
        if row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > now:
            raise AuthError("locked", f"Too many wrong passwords. Try again in {LOCK_MINUTES} minutes.", 429)
        if not verify_password(password, row["password_hash"]):
            failed = row["failed_logins"] + 1
            locked = _iso(now + timedelta(minutes=LOCK_MINUTES)) if failed >= MAX_FAILED else None
            with self._lock:
                self._db.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                                 (0 if locked else failed, locked, row["id"]))
                self._db.commit()
            raise AuthError("bad_credentials", "Email or password is incorrect.", 401)
        with self._lock:
            self._db.execute("UPDATE users SET failed_logins = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
                             (_iso(now), row["id"]))
            self._db.commit()
        return self.user(row["id"])

    def create_session(self, user_id: str, user_agent: str | None = None) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        now = _now()
        expires = _iso(now + timedelta(days=SESSION_DAYS))
        with self._lock:
            self._db.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, user_agent) VALUES (?,?,?,?,?)",
                             (_token_hash(token), user_id, _iso(now), expires, (user_agent or "")[:200]))
            self._db.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))
            self._db.commit()
        return token, expires

    def session_user(self, token: str) -> tuple[dict, dict, str] | None:
        """Returns (user, company, expires_at) for a live session, sliding its expiry forward."""
        if not token:
            return None
        th = _token_hash(token)
        row = self._db.execute("SELECT * FROM sessions WHERE token_hash = ?", (th,)).fetchone()
        now = _now()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
            return None
        expires = _iso(now + timedelta(days=SESSION_DAYS))
        if datetime.fromisoformat(row["expires_at"]) - now < timedelta(days=SESSION_DAYS - 1):
            with self._lock:
                self._db.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (expires, th))
                self._db.commit()
        else:
            expires = row["expires_at"]
        user = self.user(row["user_id"])
        return user, self.company(user["company_id"]), expires

    def revoke_session(self, token: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
            self._db.commit()

    # ---- password reset ----------------------------------------------------
    def create_reset(self, user_id: str) -> str | None:
        """One-time reset token, valid RESET_MINUTES. None if this user already asked RESETS_PER_HOUR times this hour."""
        now = _now()
        recent = self._db.execute("SELECT COUNT(*) FROM password_resets WHERE user_id = ? AND created_at > ?",
                                  (user_id, _iso(now - timedelta(hours=1)))).fetchone()[0]
        if recent >= RESETS_PER_HOUR:
            return None
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute("INSERT INTO password_resets (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                             (_token_hash(token), user_id, _iso(now), _iso(now + timedelta(minutes=RESET_MINUTES))))
            self._db.commit()
        return token

    def reset_email(self, token: str) -> str | None:
        row = self._db.execute("SELECT u.email FROM password_resets r JOIN users u ON u.id = r.user_id"
                               " WHERE r.token_hash = ?", (_token_hash(token or ""),)).fetchone()
        return row["email"] if row else None

    def reset_password(self, token: str, new_password: str) -> dict:
        """Uses the token once, sets the new password, clears any lockout and signs out every existing session."""
        th = _token_hash(token or "")
        row = self._db.execute("SELECT * FROM password_resets WHERE token_hash = ?", (th,)).fetchone()
        now = _now()
        if row is None or row["used_at"] or datetime.fromisoformat(row["expires_at"]) <= now:
            raise AuthError("reset_invalid", "This reset link has expired or was already used. Ask for a new one.", 400)
        with self._lock:
            self._db.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
                             (_iso(now), row["user_id"]))
            self._db.execute("UPDATE users SET password_hash = ?, failed_logins = 0, locked_until = NULL WHERE id = ?",
                             (hash_password(new_password), row["user_id"]))
            self._db.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
            self._db.commit()
        return self.user(row["user_id"])

    def user(self, user_id: str) -> dict:
        return _user(self._db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def company(self, company_id: str) -> dict:
        return _company(self._db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone())


def _user(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in ("id", "company_id", "email", "full_name", "job_role", "workspace_role", "created_at",
                                "last_login_at")}


def _company(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["hiring_for"] = json.loads(d.get("hiring_for") or "[]")
    return d
