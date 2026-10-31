"""On-disk cache for Crustdata responses.

One JSON file per request: <dir>/<endpoint_slug>/<request_hash>.json
    {"endpoint": ..., "request": {...}, "status": 200, "response": <raw body>, "fetched_at": ISO}

The same format is used for cache/crustdata/ (written at runtime) and
fixtures/crustdata/ (committed, written by scripts/smoke_crustdata.py), so
replay mode can serve from either.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = Path(os.getenv("CRUSTDATA_CACHE_DIR", REPO_ROOT / "cache" / "crustdata"))
DEFAULT_FIXTURES_DIR = Path(os.getenv("CRUSTDATA_FIXTURES_DIR", REPO_ROOT / "fixtures" / "crustdata"))


def request_hash(endpoint: str, request: dict[str, Any]) -> str:
    canonical = json.dumps({"endpoint": endpoint, "request": request}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(endpoint: str) -> str:
    return endpoint.strip("/").replace("/", "_")


class ResponseCache:
    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR, fixtures_dir: Path | str | None = DEFAULT_FIXTURES_DIR):
        self.cache_dir = Path(cache_dir)
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else None

    def _path(self, root: Path, endpoint: str, rhash: str) -> Path:
        return root / _slug(endpoint) / f"{rhash}.json"

    def get(self, endpoint: str, rhash: str) -> tuple[dict, str] | None:
        """Return (entry, origin) where origin is "cache" or "fixture"."""
        for root, origin in ((self.cache_dir, "cache"), (self.fixtures_dir, "fixture")):
            if root is None:
                continue
            path = self._path(root, endpoint, rhash)
            if path.exists():
                try:
                    return json.loads(path.read_text()), origin
                except (OSError, json.JSONDecodeError):
                    continue
        return None

    def put(self, endpoint: str, rhash: str, request: dict, status: int, response: Any, fetched_at: str) -> Path:
        path = self._path(self.cache_dir, endpoint, rhash)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"endpoint": endpoint, "request": request, "status": status, "response": response, "fetched_at": fetched_at}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, indent=2, ensure_ascii=False, default=str))
        tmp.replace(path)
        return path

    def entries(self, endpoint: str) -> list[dict]:
        """All stored entries for an endpoint (cache first, then fixtures). Used for replay fallbacks."""
        out = []
        for root in (self.cache_dir, self.fixtures_dir):
            if root is None:
                continue
            d = root / _slug(endpoint)
            if d.is_dir():
                for p in sorted(d.glob("*.json")):
                    try:
                        out.append(json.loads(p.read_text()))
                    except (OSError, json.JSONDecodeError):
                        pass
        return out
