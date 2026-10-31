"""Async Crustdata API client (WS1).

Modes
    live    every call hits the API, nothing is read or written on disk
    cache   (default) read cache/ + fixtures/ first, otherwise call the API and write cache/
    replay  never touches the network; serves only cache/crustdata + fixtures/crustdata.
            A miss returns None / [] (logged), so a demo can't crash on wifi.

Every dict returned carries
    "_source": {"endpoint": "person/enrich", "request_hash": "...", "fetched_at": "ISO", "origin": "live|cache|fixture"}
so verifier claims can cite it.

None / [] means "not found". CrustdataError is raised only for auth/bad-request
errors or after retries are exhausted on 429/5xx/timeouts.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from typing import Any

import httpx

from .cache import ResponseCache, now_iso, request_hash

try:  # .env is optional; the key may already be in the environment
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

log = logging.getLogger("crustdata")

BASE_URL = os.getenv("CRUSTDATA_BASE_URL", "https://api.crustdata.com")
API_VERSION = os.getenv("CRUSTDATA_API_VERSION", "2025-11-01")
TIMEOUT_S = 20.0
MAX_ATTEMPTS = 4
RETRY_STATUSES = {429, 500, 502, 503, 504}
MODES = ("live", "cache", "replay")


class CrustdataError(Exception):
    def __init__(self, message: str, status: int | None = None, endpoint: str | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.endpoint = endpoint
        self.body = body


@dataclass(frozen=True)
class Endpoint:
    name: str     # logical name used in _source and as cache folder
    method: str
    path: str
    rpm: int = 30  # documented requests/minute


class _RateLimiter:
    """Sliding 60s window per endpoint so we stay under the documented limits instead of eating 429s."""

    def __init__(self, rpm: int):
        self.rpm = rpm
        self.calls: list[float] = []
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            loop = asyncio.get_running_loop()
            while True:
                now = loop.time()
                self.calls = [t for t in self.calls if now - t < 60]
                if len(self.calls) < self.rpm:
                    self.calls.append(now)
                    return
                await asyncio.sleep(60 - (now - self.calls[0]) + 0.05)


# Logical name -> HTTP route. Paths can be overridden with env vars
# (CRUSTDATA_PATH_PERSON_SEARCH=/foo) if the docs differ from what we expect.
ENDPOINTS: dict[str, Endpoint] = {
    e.name: Endpoint(e.name, e.method, os.getenv("CRUSTDATA_PATH_" + e.name.upper().replace("/", "_"), e.path), e.rpm)
    for e in [
        Endpoint("person/search", "POST", "/person/search"),
        Endpoint("person/enrich", "POST", "/person/enrich", rpm=15),
        Endpoint("company/search", "POST", "/company/search"),
        Endpoint("company/identify", "POST", "/company/identify"),
        Endpoint("company/enrich", "POST", "/company/enrich", rpm=15),
        Endpoint("job/search", "POST", "/job/search"),
        Endpoint("web/search", "POST", "/web/search/live"),
        Endpoint("web/fetch", "POST", "/web/enrich/live", rpm=10),
    ]
}

# Keys under which list endpoints may return their rows, tried in order.
_LIST_KEYS = ("profiles", "people", "persons", "companies", "jobs", "job_listings", "results", "data", "items", "records")


def extract_list(body: Any) -> list[dict]:
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if isinstance(body, dict):
        for key in _LIST_KEYS:
            val = body.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
            if isinstance(val, dict):  # e.g. {"data": {"results": [...]}}
                inner = extract_list(val)
                if inner:
                    return inner
    return []


def extract_one(body: Any) -> dict | None:
    if isinstance(body, list):
        return next((r for r in body if isinstance(r, dict)), None)
    if isinstance(body, dict):
        rows = extract_list(body)
        if rows:
            return rows[0]
        for key in ("profile", "person", "company", "result", "data"):
            if isinstance(body.get(key), dict):
                return body[key]
        return body or None
    return None


class CrustdataClient:
    def __init__(
        self,
        api_key: str | None = None,
        mode: str | None = None,
        *,
        cache: ResponseCache | None = None,
        max_concurrency: int = int(os.getenv("CRUSTDATA_MAX_CONCURRENCY", "5")),
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_base: float = 1.0,
    ):
        self.mode = (mode or os.getenv("CRUSTDATA_MODE", "cache")).lower()
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        self.api_key = api_key or os.getenv("CRUSTDATA_API_KEY")
        if self.mode != "replay" and not self.api_key:
            raise CrustdataError("CRUSTDATA_API_KEY is not set (put it in .env), or use mode='replay'")
        self.cache = cache or ResponseCache()
        self.backoff_base = backoff_base
        self._sem = asyncio.Semaphore(max_concurrency)
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=TIMEOUT_S,
            transport=transport,
            headers={
                "authorization": f"Bearer {self.api_key or ''}",
                "x-api-version": API_VERSION,
                "content-type": "application/json",
                "accept": "application/json",
            },
        )
        self._limiters = {name: _RateLimiter(ep.rpm) for name, ep in ENDPOINTS.items()}
        self.stats = {"live": 0, "cache": 0, "fixture": 0, "miss": 0, "retries": 0, "errors": 0}

    async def __aenter__(self) -> "CrustdataClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ core

    async def request(self, name: str, payload: dict[str, Any]) -> tuple[Any, dict] | None:
        """Low-level call. Returns (raw_body, source) or None when not found / replay miss."""
        ep = ENDPOINTS[name]
        rhash = request_hash(name, payload)

        if self.mode in ("cache", "replay"):
            hit = self.cache.get(name, rhash)
            if hit:
                entry, origin = hit
                self.stats[origin] += 1
                if entry.get("status") == 404:
                    return None
                return entry.get("response"), self._source(name, rhash, entry.get("fetched_at"), origin)
            if self.mode == "replay":
                self.stats["miss"] += 1
                log.warning("replay miss %s %s %s", name, rhash, payload)
                return None

        status, body = await self._send(ep, payload)
        fetched_at = now_iso()
        self.stats["live"] += 1
        if self.mode == "cache":
            self.cache.put(name, rhash, payload, status, body, fetched_at)
        if status == 404:
            return None
        return body, self._source(name, rhash, fetched_at, "live")

    async def _send(self, ep: Endpoint, payload: dict[str, Any]) -> tuple[int, Any]:
        last_err: str = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            retry_after: float | None = None
            try:
                await self._limiters[ep.name].wait()
                async with self._sem:
                    if ep.method == "GET":
                        resp = await self._http.get(ep.path, params=payload)
                    else:
                        resp = await self._http.request(ep.method, ep.path, json=payload)
                body = _json_or_text(resp)
                if resp.status_code < 300 or resp.status_code == 404:
                    return resp.status_code, body
                if resp.status_code not in RETRY_STATUSES:
                    self.stats["errors"] += 1
                    raise CrustdataError(
                        f"{ep.method} {ep.path} -> {resp.status_code}: {str(body)[:300]}",
                        status=resp.status_code, endpoint=ep.name, body=body,
                    )
                last_err = f"HTTP {resp.status_code}"
                retry_after = _parse_retry_after(resp.headers.get("retry-after"))
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = f"{type(e).__name__}: {e}"
            if attempt < MAX_ATTEMPTS:
                self.stats["retries"] += 1
                delay = retry_after if retry_after is not None else self.backoff_base * 2 ** (attempt - 1)
                delay = min(delay, 20) + random.uniform(0, self.backoff_base * 0.25)
                log.info("retry %s attempt %d after %.1fs (%s)", ep.name, attempt, delay, last_err)
                await asyncio.sleep(delay)
        self.stats["errors"] += 1
        raise CrustdataError(f"{ep.method} {ep.path} failed after {MAX_ATTEMPTS} attempts: {last_err}", endpoint=ep.name)

    @staticmethod
    def _source(name: str, rhash: str, fetched_at: str | None, origin: str) -> dict:
        return {"endpoint": name, "request_hash": rhash, "fetched_at": fetched_at, "origin": origin}

    async def _list(self, name: str, payload: dict) -> list[dict]:
        res = await self.request(name, payload)
        if res is None:
            return []
        body, src = res
        return [{**row, "_source": src} for row in extract_list(body)]

    async def _one(self, name: str, payload: dict) -> dict | None:
        res = await self.request(name, payload)
        if res is None:
            return None
        body, src = res
        row = extract_one(body)
        return {**row, "_source": src} if row else None

    # ------------------------------------------------------------- endpoints
    # Request/response shapes follow docs.crustdata.com (x-api-version 2025-11-01).
    # Filter grammar: leaf {"field": ..., "type": "=", "value": ...} or group
    # {"op": "and"|"or", "conditions": [...]}. Operators: = != < =< > => in not_in
    # is_null is_not_null (.) [.] geo_distance. Note "=<" / "=>", not "<=" / ">=".

    async def person_search(self, filters: dict, limit: int = 25, **extra) -> list[dict]:
        """Rows are person records (basic_profile, experience, ...). extra: fields, sorts, cursor, search."""
        return await self._list("person/search", {"filters": filters, "limit": limit, **extra})

    async def person_enrich(self, profile_url: str, fields: list[str] | None = None) -> dict | None:
        if not profile_url:
            return None
        return (await self.person_enrich_many([profile_url], fields)).get(profile_url)

    async def person_enrich_many(self, profile_urls: list[str], fields: list[str] | None = None) -> dict[str, dict | None]:
        """Batch enrich (25 per request; the endpoint allows only 15 req/min). Returns {url: person | None}."""
        urls = list(dict.fromkeys(u for u in profile_urls if u))
        out: dict[str, dict | None] = {u: None for u in urls}
        chunks = [urls[i:i + 25] for i in range(0, len(urls), 25)]
        payloads = [{"professional_network_profile_urls": c, "fields": fields or PERSON_ENRICH_FIELDS} for c in chunks]
        for res in await asyncio.gather(*(self.request("person/enrich", p) for p in payloads)):
            out.update(_unwrap_matches(res, "person_data"))
        by_norm = {_norm_url(k): v for k, v in out.items() if v is not None}
        return {u: out.get(u) or by_norm.get(_norm_url(u)) for u in urls}

    async def company_search(self, filters: dict, limit: int = 25, **extra) -> list[dict]:
        return await self._list("company/search", {"filters": filters, "limit": limit, **extra})

    async def company_identify(self, name: str | None = None, domain: str | None = None) -> dict | None:
        """Free. Returns company_data ({crustdata_company_id, basic_info}) of the best match."""
        if not (name or domain):
            return None
        payload = {"domains": [domain]} if domain else {"names": [name]}
        return next(iter(_unwrap_matches(await self.request("company/identify", payload), "company_data").values()), None)

    async def company_enrich(self, company_id: str | int | None = None, domain: str | None = None,
                             fields: list[str] | None = None) -> dict | None:
        """2 credits/record. Prefer company_id (crustdata_company_id from person experience) over domain."""
        if not (company_id or domain):
            return None
        if company_id:
            payload = {"crustdata_company_ids": [_as_id(company_id)]}
        else:
            payload = {"domains": [domain]}
        payload["fields"] = fields or COMPANY_ENRICH_FIELDS
        return next(iter(_unwrap_matches(await self.request("company/enrich", payload), "company_data").values()), None)

    async def job_search(self, filters: dict, limit: int = 25, **extra) -> list[dict]:
        return await self._list("job/search", {"filters": filters, "limit": limit, **extra})

    async def web_search(self, query: str, **extra) -> list[dict]:
        """Rows: {source, title, url, snippet, position}. extra: sources, site, location, page."""
        if not query:
            return []
        return await self._list("web/search", {"query": query[:5000], **extra})

    async def web_fetch(self, url: str) -> dict | None:
        """Returns {success, url, title, content, timestamp} or None if the page couldn't be fetched."""
        if not url:
            return None
        res = await self.request("web/fetch", {"urls": [url]})
        if res is None:
            return None
        body, src = res
        rows = body if isinstance(body, list) else extract_list(body)
        row = next((r for r in rows if isinstance(r, dict) and r.get("success") and r.get("url") == url), None)
        row = row or next((r for r in rows if isinstance(r, dict) and r.get("success")), None)
        return {**row, "_source": {**src, "url": row.get("url")}} if row else None


PERSON_ENRICH_FIELDS = ["basic_profile", "experience", "education", "skills", "social_handles"]
COMPANY_ENRICH_FIELDS = ["basic_info", "headcount", "funding", "locations", "taxonomy", "hiring"]


def _norm_url(u: str) -> str:
    u = (u or "").strip().lower().split("?")[0].rstrip("/")
    for prefix in ("https://", "http://", "www."):
        u = u.removeprefix(prefix)
    return u


def _as_id(v: str | int) -> int | str:
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def _unwrap_matches(res: tuple[Any, dict] | None, data_key: str) -> dict[str, dict | None]:
    """Enrich/identify return [{matched_on, match_status?, matches: [{confidence_score, <data_key>}]}].
    Returns {matched_on: record-with-_source | None}, best match (highest confidence) per input."""
    if res is None:
        return {}
    body, src = res
    entries = body if isinstance(body, list) else extract_list(body)
    out: dict[str, dict | None] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        key = str(e.get("matched_on"))
        matches = [m for m in e.get("matches") or [] if isinstance(m, dict) and isinstance(m.get(data_key), dict)]
        if not matches or e.get("match_status") in ("not_found",):
            out[key] = None
            continue
        best = max(matches, key=lambda m: m.get("confidence_score") or 0)
        out[key] = {
            **best[data_key],
            "_match": {"confidence_score": best.get("confidence_score"), "match_type": e.get("match_type"),
                       "match_status": e.get("match_status")},
            "_source": {**src, "matched_on": e.get("matched_on")},
        }
    return out


def _json_or_text(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _parse_retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None
