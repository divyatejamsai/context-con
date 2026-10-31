"""Read-only view of Crustdata's graph for sponsor checks.

Wraps CrustdataClient. In replay mode (no network) it also serves the committed Person Enrich
fixtures by profile URL, so the demo and tests work from the repo alone. Every record keeps a
`_source` so checks can cite it.
"""
from __future__ import annotations

import glob
import json
import logging
import os
from pathlib import Path
from typing import Any

from ..verify.profile import unwrap_record

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_GLOBS = ("fixtures/crustdata/person_enrich_*.json", "fixtures/countersign/people/*.json")


def norm_url(u: str | None) -> str:
    u = (u or "").strip().lower().split("?")[0].rstrip("/")
    for p in ("https://", "http://", "www."):
        u = u.removeprefix(p)
    return u


def _fixture_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for g in FIXTURE_GLOBS:
        for f in sorted(glob.glob(str(REPO_ROOT / g))):
            try:
                rec = unwrap_record(json.loads(Path(f).read_text()))
            except (OSError, json.JSONDecodeError):
                continue
            url = ((rec.get("social_handles") or {}).get("professional_network_identifier") or {}).get("profile_url")
            if url:
                rec.setdefault("_source", {"endpoint": "person/enrich", "origin": "fixture", "file": Path(f).name})
                idx[norm_url(url)] = rec
    return idx


class Graph:
    def __init__(self, client: Any | None = None, mode: str | None = None):
        self.client = client
        self.mode = (mode or getattr(client, "mode", None) or os.getenv("CRUSTDATA_MODE", "cache")).lower()
        self._fixtures: dict[str, dict] | None = None

    @property
    def offline(self) -> bool:
        return self.mode == "replay" or self.client is None

    def _fx(self) -> dict[str, dict]:
        if self._fixtures is None:
            self._fixtures = _fixture_index()
        return self._fixtures

    async def person(self, profile_url: str) -> dict | None:
        """Raises on transport/API errors (callers mark the check unverifiable)."""
        rec = None
        if self.client is not None:
            rec = await self.client.person_enrich(profile_url)
        if rec is None and self.offline:
            rec = self._fx().get(norm_url(profile_url))
        return rec

    async def company_by_domain(self, domain: str) -> dict | None:
        if self.client is None:
            return None
        return await self.client.company_identify(domain=domain)
