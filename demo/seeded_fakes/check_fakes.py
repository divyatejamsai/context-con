"""QA: run WS3's verifier on the seeded fakes and report which planted lies were caught.

Usage (from repo root): python demo/seeded_fakes/check_fakes.py demo/seeded_fakes/out [--companies fixtures/crustdata/companies.json]
Runs offline (no Crustdata client); pass --companies so company-stage lies can be checked.
Exit code 1 if any planted lie is missed or any true claim is marked contradicted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas import Criteria  # noqa: E402
from app.verify.verifier import verify_candidate  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from make_fakes import load_companies, P  # noqa: E402

# Which claim text each claimed key produces when the verifier contradicts it.
KEY_HINT = {"employer": "Works at", "title": "Title:", "start_date": " since ", "years_experience": "of experience",
            "location": "Based in", "company_stage": " is "}

CRIT = Criteria(role="Engineer", title_variants=[], seniority=None, skills=[], locations=[],
                company_preferences=[], must_haves=[], nice_to_haves=[], raw_brief="seeded fake check")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--companies")
    args = ap.parse_args()
    out = Path(args.dir)
    companies = load_companies(args.companies)
    ok = True
    for entry in json.loads((out / "answer_key.json").read_text()):
        person = json.loads((out / entry["file"]).read_text())
        cur = P.load_person(person).current
        company = companies.get(str(cur[0].company_id)) if cur and cur[0].company_id is not None else None
        claims, flags = await verify_candidate(person, company, CRIT, None)
        bad = [c for c in claims if c.status == "contradicted"]
        print(f"\n{entry['name']}")
        planted_keys = set()
        for lie in entry["lies"]:
            planted_keys.add(lie["key"])
            hit = next((c for c in bad if KEY_HINT[lie["key"]] in c.claim and str(lie["claimed"]) in c.claim), None)
            print(f"  {'CAUGHT' if hit else 'MISSED'} {lie['type']}: {lie['claimed']!r}"
                  + (f" -> {hit.evidence} [{hit.source.endpoint} {hit.source.field}]" if hit else ""))
            ok &= bool(hit)
        planted_text = [str(l["claimed"]) for l in entry["lies"]]
        for c in bad:
            if not any(t in c.claim for t in planted_text):
                print(f"  FALSE POSITIVE: {c.claim} ({c.evidence})")
                ok = False
    print("\nPASS" if ok else "\nFAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
