"""Demo view: show one seeded-fake resume next to what the verifier concluded, claim by claim.

Usage (from repo root): python demo/seeded_fakes/show_fake.py demo/seeded_fakes/out/<slug>.person.json \
    [--companies fixtures/crustdata/companies.json]
Offline: uses the saved enrich record, no API calls. Made for the "seeded fakes" beat of the video.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

from app.schemas import Criteria  # noqa: E402
from app.verify.verifier import verify_candidate  # noqa: E402
from make_fakes import P, load_companies, render  # noqa: E402

COLOR = {"verified": "\033[32m", "contradicted": "\033[31m", "unverifiable": "\033[33m"}
ICON = {"verified": "✓ VERIFIED    ", "contradicted": "✗ CONTRADICTED", "unverifiable": "? UNVERIFIABLE"}
RESET, DIM, BOLD = "\033[0m", "\033[2m", "\033[1m"
CRIT = Criteria(role="Engineer", title_variants=[], seniority=None, skills=[], locations=[],
                company_preferences=[], must_haves=[], nice_to_haves=[], raw_brief="seeded fake resume check")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("person")
    ap.add_argument("--companies")
    args = ap.parse_args()
    person = json.loads(Path(args.person).read_text())
    pr = P.load_person(person)
    cur = pr.current[0] if pr.current else None
    company = load_companies(args.companies).get(str(cur.company_id)) if cur and cur.company_id is not None else None

    print(f"{BOLD}Resume as submitted{RESET}")
    for line in render(pr.name or "", pr.profile_url, person.get("claimed") or {}).splitlines():
        print(f"  {line}")
    claims, flags = await verify_candidate(person, company, CRIT, None)
    print(f"\n{BOLD}What Crustdata's graph says{RESET}")
    for c in sorted(claims, key=lambda c: c.status != "contradicted"):
        src = c.source.endpoint + (f" · {c.source.field}" if c.source.field else "")
        print(f"  {COLOR[c.status]}{ICON[c.status]}{RESET}  {c.claim}")
        print(f"  {DIM}{' ' * 16}{c.evidence}  [{src}]{RESET}")
    n_bad = sum(c.status == "contradicted" for c in claims)
    print(f"\n{BOLD}{n_bad} claim(s) contradicted{RESET}" + (f" · flags: {'; '.join(flags)}" if flags else ""))


if __name__ == "__main__":
    asyncio.run(main())
