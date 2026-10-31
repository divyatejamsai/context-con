"""Smoke-test every Crustdata endpoint and save real responses as fixtures.

Run from the repo root (needs CRUSTDATA_API_KEY in .env):
    python backend/scripts/smoke_crustdata.py            # reuses saved fixtures, only calls what's missing
    python backend/scripts/smoke_crustdata.py --fresh    # re-call everything

Writes
    fixtures/crustdata/<endpoint>/<hash>.json   replayable entries (CRUSTDATA_MODE=replay serves these)
    fixtures/crustdata/<name>.json              readable copies, e.g. person_enrich_<handle>.json
    fixtures/crustdata/SMOKE_REPORT.md          status per endpoint + field paths of a sample record
Costs roughly 20 credits.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.crustdata import CrustdataClient, CrustdataError, ResponseCache  # noqa: E402

FIXTURES = ROOT / "fixtures" / "crustdata"

PERSON_FIELDS = ["crustdata_person_id", "basic_profile", "experience", "social_handles"]
FALLBACK_PROFILES = ["https://www.linkedin.com/in/dvdhsu/"]  # example from Crustdata docs
SEARCH_FILTERS = {
    "op": "and",
    "conditions": [
        {"field": "experience.employment_details.current.title", "type": "(.)", "value": "backend engineer"},
        {"field": "basic_profile.location.country", "type": "=", "value": "India"},
    ],
}

results: list[dict] = []
CLIENT_KWARGS: dict = {}  # tests inject a mock transport here


class WriteOnlyCache(ResponseCache):
    """--fresh: always call the API but still record the responses."""

    def get(self, endpoint, rhash):
        return None


def save(name: str, data) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def field_paths(obj, prefix="", depth=0, out=None) -> list[str]:
    """Dot paths of a sample record so other workstreams know what's there."""
    out = [] if out is None else out
    if depth > 5:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "_source":
                continue
            field_paths(v, f"{prefix}.{k}" if prefix else k, depth + 1, out)
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], (dict, list)):
            field_paths(obj[0], f"{prefix}[]", depth + 1, out)
        else:
            out.append(f"{prefix}[]  e.g. {json.dumps(obj[:2], default=str)[:60]}")
    else:
        out.append(f"{prefix}  e.g. {json.dumps(obj, default=str)[:60]}")
    return out


async def step(name: str, coro):
    t = time.monotonic()
    try:
        out = await coro
        n = len(out) if isinstance(out, (list, dict)) and not (isinstance(out, dict) and "_source" in out) else (1 if out else 0)
        sample = out[0] if isinstance(out, list) and out else out
        if isinstance(sample, dict) and "_source" not in sample:  # enrich_many dict
            sample = next((v for v in sample.values() if v), None)
        results.append({"name": name, "ok": True, "rows": n, "secs": time.monotonic() - t,
                        "origin": (sample or {}).get("_source", {}).get("origin") if isinstance(sample, dict) else None,
                        "paths": field_paths(sample) if sample else []})
        print(f"  OK   {name:<18} rows={n:<3} {time.monotonic() - t:.1f}s")
        return out
    except CrustdataError as e:
        results.append({"name": name, "ok": False, "error": str(e)[:400], "secs": time.monotonic() - t})
        print(f"  FAIL {name:<18} {str(e)[:200]}")
        return None


def profile_url(p: dict) -> str | None:
    return (((p.get("social_handles") or {}).get("professional_network_identifier") or {}).get("profile_url")
            or p.get("linkedin_profile_url") or p.get("profile_url"))


def handle(url: str) -> str:
    m = re.search(r"/in/([^/?#]+)", url or "")
    return re.sub(r"[^a-zA-Z0-9_-]", "", m.group(1) if m else url)[:40]


async def main(fresh: bool) -> int:
    cache = (WriteOnlyCache if fresh else ResponseCache)(cache_dir=FIXTURES, fixtures_dir=None)
    async with CrustdataClient(mode="cache", cache=cache, **CLIENT_KWARGS) as c:
        print(f"Crustdata smoke test (mode={'fresh' if fresh else 'cache'}) -> {FIXTURES}")

        people = await step("person_search", c.person_search(SEARCH_FILTERS, limit=10, fields=PERSON_FIELDS))
        if people is None:  # field list may need a premium group: retry with defaults
            people = await step("person_search_min", c.person_search(SEARCH_FILTERS, limit=10))
        if people:
            save("person_search", people)

        urls = [u for u in (profile_url(p) for p in people or []) if u][:5] or FALLBACK_PROFILES
        enriched = await step("person_enrich", c.person_enrich_many(urls))
        for url, person in (enriched or {}).items():
            if person:
                save(f"person_enrich_{handle(url)}", person)

        ident = await step("company_identify", c.company_identify(domain="razorpay.com"))
        if ident:
            save("company_identify", ident)
        company = await step("company_enrich", c.company_enrich(
            company_id=(ident or {}).get("crustdata_company_id"), domain=None if ident else "razorpay.com"))
        if company:
            save("company_enrich", company)

        companies = await step("company_search", c.company_search(
            {"op": "and", "conditions": [{"field": "locations.country", "type": "in", "value": ["IND"]},
                                         {"field": "headcount.total", "type": ">", "value": 200}]}, limit=5))
        if companies:
            save("company_search", companies)

        jobs = await step("job_search", c.job_search(
            {"op": "and", "conditions": [{"field": "job_details.category", "type": "=", "value": "Engineering"},
                                         {"field": "job_details.title", "type": "(.)", "value": "backend"}]}, limit=5))
        if jobs:
            save("job_search", jobs)

        hits = await step("web_search", c.web_search("Razorpay senior backend engineer payments"))
        if hits:
            save("web_search", hits)
        page = await step("web_fetch", c.web_fetch("https://razorpay.com/about/"))
        if page:
            save("web_fetch", page)

        stats = dict(c.stats)

    write_report(stats)
    failed = [r["name"] for r in results if not r["ok"]]
    print(f"\nstats: {stats}")
    print("ALL OK" if not failed else f"FAILED: {failed}")
    return 1 if failed else 0


def write_report(stats: dict) -> None:
    lines = ["# Crustdata smoke report", "", f"Generated {time.strftime('%Y-%m-%d %H:%M:%S %Z')} · stats `{stats}`", "",
             "| step | status | rows | origin | secs |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['name']} | {'OK' if r['ok'] else 'FAIL: ' + r['error'].replace('|', '/')[:150]} "
                     f"| {r.get('rows', '')} | {r.get('origin') or ''} | {r['secs']:.1f} |")
    for r in results:
        if r.get("paths"):
            lines += ["", f"## {r['name']}: fields of first record", "```", *r["paths"][:120], "```"]
    (FIXTURES / "SMOKE_REPORT.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="ignore saved fixtures and call the API again")
    sys.exit(asyncio.run(main(ap.parse_args().fresh)))
