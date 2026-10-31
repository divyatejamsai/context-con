"""Onboard Sourced (the hiring agent) as an AI employee in the real store, then print how to run it.

    cd backend && python scripts/onboard_sourced.py                               # sponsor = fixture scenario authorised_founder
    cd backend && python scripts/onboard_sourced.py --scenario <id>               # any scenario in fixtures/countersign/sponsors.json
    cd backend && python scripts/onboard_sourced.py --name "..." --profile-url https://www.linkedin.com/in/... \\
        --company "..." --domain example.com --title "Head of Talent"             # a real sponsor of your own

Runs the same live sponsor check as the console (verify_passport against Crustdata, CRUSTDATA_MODE from .env).
If an active Sourced already exists it is reused.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND.parent / ".env")
load_dotenv(BACKEND / ".env")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="authorised_founder")
    ap.add_argument("--name")
    ap.add_argument("--profile-url")
    ap.add_argument("--company")
    ap.add_argument("--domain")
    ap.add_argument("--title")
    ap.add_argument("--new", action="store_true", help="onboard a fresh Sourced even if one is active")
    a = ap.parse_args()

    from app.agents import registry
    from app.agents.api import crustdata
    from app.agents.models import Sponsor

    if not a.new:
        for ag in registry.list_agents():
            if ag["name"] == "Sourced" and ag["status"] == "active":
                print(f"Sourced already active: {ag['agent_id']}")
                return _usage(ag["agent_id"])
    if a.name:
        sponsor = Sponsor(name=a.name, profile_url=a.profile_url, company=a.company, company_domain=a.domain, title=a.title)
    else:
        sc = {s["id"]: s for s in json.loads((BACKEND.parent / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
        sponsor = Sponsor(**sc[a.scenario]["sponsor"])
    ag = registry.onboard("Sourced", "recruiter", sponsor)
    v = await registry.recheck(ag["agent_id"], crustdata())
    print(f"Onboarded Sourced {ag['agent_id']} under {sponsor.name} ({sponsor.title}, {sponsor.company}): {v.decision.upper()}")
    for c in v.checks:
        print(f"  {c.status:>12}  {c.name}: {c.detail}")
    if v.decision != "allow":
        print("The sponsor check failed, so Sourced is suspended. Pick a sponsor Crustdata can vouch for.")
        return 1
    return _usage(ag["agent_id"])


def _usage(agent_id: str) -> int:
    print(f"\nRun it:  curl -N 'http://localhost:8000/api/agents/{agent_id}/run?brief=senior+backend+engineer+payments+bangalore'")
    print(f"UI:      set NEXT_PUBLIC_AGENT_ID={agent_id} once the web UI reads it (handed to the UI thread)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
