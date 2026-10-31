"""Real candidate pools from Crustdata Person Search, shared by the conversation engine and shift staffing.

    fetch_pool(client, filters, want)   pages Person Search (cursor) until `want` unique profiles or no more pages
    PoolGraph(records, client)          a Graph that serves records already fetched from Crustdata by profile URL,
                                        so Send Guard and the verifier don't pay for a second lookup of the same person
    save_pool / load_pool               record a pool as a fixture (fixtures/<name>/pool.json) for replay

Every record keeps its `_source` (endpoint person/search, request hash, fetched_at), so each claim checked against it
cites where the fact came from.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agents.graph import Graph, norm_url
from ..verify.profile import load_person, unwrap_record

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[3]
SEARCH_FIELDS = ["crustdata_person_id", "basic_profile", "experience", "social_handles"]  # same as the live-tested orchestrator


def profile_url(rec: dict) -> str | None:
    return load_person(rec).profile_url


async def fetch_pool(client: Any, filters: dict, want: int, page: int = 100, max_pages: int = 20) -> list[dict]:
    """Unique person records (by profile URL) for raw Crustdata `filters`. Stops at `want`, an empty page or no cursor.
    Clients without a raw `request` (DevCrustdataClient) get a single person_search call."""
    if client is None:
        return []
    out: dict[str, dict] = {}
    if not hasattr(client, "request"):
        rows = await client.person_search(filters, limit=want)
        for r in rows or []:
            u = profile_url(r)
            if u:
                out.setdefault(norm_url(u), r)
        return list(out.values())[:want]
    from ..crustdata.client import extract_list

    cursor = None
    for _ in range(max_pages):
        payload = {"filters": filters, "limit": min(page, max(want - len(out), 1)), "fields": SEARCH_FIELDS}
        if cursor:
            payload["cursor"] = cursor
        try:
            res = await client.request("person/search", payload)
        except Exception as e:  # noqa: BLE001 - a page size the API refuses: retry once at the size the pipeline uses
            if getattr(e, "status", None) in (400, 422) and payload["limit"] > 25:
                page = 25
                payload["limit"] = min(page, max(want - len(out), 1))
                res = await client.request("person/search", payload)
            else:
                raise
        if res is None:
            break
        body, src = res
        rows = extract_list(body)
        for r in rows:
            u = profile_url(r)
            if u:
                out.setdefault(norm_url(u), {**r, "_source": src})
        cursor = body.get("next_cursor") if isinstance(body, dict) else None
        if not rows or not cursor or len(out) >= want:
            break
    return list(out.values())[:want]


def title_filter(titles: list[str]) -> dict:
    leaves = [{"field": "experience.employment_details.current.title", "type": "(.)", "value": t.lower()} for t in titles]
    return leaves[0] if len(leaves) == 1 else {"op": "or", "conditions": leaves}


def city_filter(cities: list[str]) -> dict:
    from ..orchestrator import _CITY_SPELLINGS

    vals = list(dict.fromkeys(v for c in cities for v in _CITY_SPELLINGS.get(c.lower(), [c.lower()])))
    leaves = [{"field": "basic_profile.location.city", "type": "(.)", "value": v} for v in vals]
    return leaves[0] if len(leaves) == 1 else {"op": "or", "conditions": leaves}


def all_of(*conds: dict | None) -> dict:
    cs = [c for c in conds if c]
    return cs[0] if len(cs) == 1 else {"op": "and", "conditions": cs}


class PoolGraph(Graph):
    """Graph that answers from records we already hold (fetched from Crustdata), then falls back to the client."""

    def __init__(self, records: list[dict] | dict[str, dict], client: Any | None = None, mode: str | None = None):
        super().__init__(client, mode)
        items = records.values() if isinstance(records, dict) else records
        self.records: dict[str, dict] = {}
        for r in items:
            u = profile_url(r)
            if u:
                self.records[norm_url(u)] = r

    def add(self, rec: dict) -> None:
        u = profile_url(rec)
        if u:
            self.records[norm_url(u)] = rec

    async def person(self, profile_url: str) -> dict | None:
        hit = self.records.get(norm_url(profile_url))
        if hit is not None:
            return hit
        rec = await super().person(profile_url)
        if rec is not None:
            self.records[norm_url(profile_url)] = unwrap_record(rec)
        return rec


def pool_path(name: str) -> Path:
    return REPO_ROOT / "fixtures" / name / "pool.json"


def save_pool(name: str, records: list[dict], meta: dict | None = None) -> Path:
    p = pool_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"saved_at": datetime.now(timezone.utc).isoformat(), "meta": meta or {},
                             "count": len(records), "records": records}, indent=1, default=str))
    return p


def load_pool(name: str) -> tuple[list[dict], dict]:
    p = pool_path(name)
    if not p.exists():
        return [], {}
    d = json.loads(p.read_text())
    return d.get("records") or [], d.get("meta") or {}
