"""Records the AI employee console's offline snapshot (frontend/src/app/console/demo.json).

Runs the real registry and verify_passport offline on WS6's demo sponsors (fixtures/countersign/sponsors.json),
in a throwaway ledger/store, so the console has something true to show when no backend is running.

    cd backend && python scripts/console_demo.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "src" / "app" / "console" / "demo.json"
sys.path.insert(0, str(ROOT / "backend"))


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    os.environ.update(AGENTS_PATH=str(tmp / "agents.json"), LEDGER_PATH=str(tmp / "ledger.jsonl"),
                      ISSUER_KEY_PATH=str(tmp / "issuer.key"), CRUSTDATA_MODE="replay")
    from app.agents import ledger, registry
    from app.agents.models import Sponsor

    scenarios = json.loads((ROOT / "fixtures" / "countersign" / "sponsors.json").read_text())["scenarios"]
    sp = {s["id"]: Sponsor(**s["sponsor"]) for s in scenarios}

    sourced = registry.onboard("Sourced", "recruiter", sp["authorised_founder"])
    registry.onboard("Scout", "recruiter", sp["sponsor_left"], ["outreach.hiring"])
    quill = registry.onboard("Quill", "procurement", sp["junior_sponsor"])
    registry.onboard("Atlas", "analyst", sp["title_changed"])

    payroll = await registry.recheck_all(client=None)
    try:
        await registry.set_scopes(quill["agent_id"], ["data.read", "contract.sign"], None)
    except registry.ScopeDenied:
        pass
    await registry.add_review(sourced["agent_id"], "Pankaj Savaliya", "keep",
                              "First week: sponsor checks green, outreach stays within hiring.")

    agents = [{**a, "scorecard": registry.scorecard(a["agent_id"])} for a in registry.list_agents()]
    ok, bad = ledger.verify_chain()
    OUT.write_text(json.dumps({
        "agents": agents,
        "roles": registry.roles(),
        "scenarios": scenarios,
        "ledger": {"chain_ok": ok, "first_bad_seq": bad, "entries": ledger.entries()},
        "payroll": [v.model_dump() for v in payroll],
    }, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(agents)} agents, {len(ledger.entries())} ledger entries")


if __name__ == "__main__":
    asyncio.run(main())
