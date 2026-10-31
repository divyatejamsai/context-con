"""Terminal demo of Send Guard on the committed fixtures (no network needed in replay mode).

    cd backend && CRUSTDATA_MODE=replay LLM_MODE=mock python -m app.agents.guard_demo

Uses a throwaway ledger/outbox under backend/data/demo/ unless LEDGER_PATH / OUTBOX_PATH are set.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parents[2] / "data" / "demo"
os.environ.setdefault("LEDGER_PATH", str(DEMO_DIR / "ledger.jsonl"))
os.environ.setdefault("OUTBOX_PATH", str(DEMO_DIR / "outbox.jsonl"))

from .graph import Graph  # noqa: E402
from .guard import send_if_allowed  # noqa: E402
from .models import Sponsor  # noqa: E402
from .passport import issue_passport, sign_message  # noqa: E402

SPONSORS = {s["id"]: s for s in json.loads((Path(__file__).resolve().parents[3] / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
TODAY = date(2026, 10, 31)
VINOD = {"name": "Vinod Sonagara", "profile_url": "https://www.linkedin.com/in/vinod-sonagara", "company": "Fam"}

CASES = [
    ("Clean outreach", "authorised_founder", VINOD, "Hi Vinod, your work at Fam caught our eye. Open to a chat about a backend role?", None),
    ("False claim in the draft", "authorised_founder", VINOD, "Hi Vinod, congrats on 5 years at Fam! Open to a chat?", None),
    ("Recipient already left", "authorised_founder", {**VINOD, "company": "Trinkerr"}, "Hi Vinod, how is everything at Trinkerr?", None),
    ("Sponsor left the company", "sponsor_left", VINOD, "Hi Vinod, your work at Fam caught our eye.", None),
    ("Body altered after signing", "authorised_founder", VINOD, "Hi Vinod, please wire the fee to this new account.", "Hi Vinod, open to a chat?"),
]


async def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    graph = Graph(None, mode="replay") if os.getenv("CRUSTDATA_MODE", "replay") == "replay" else None
    if graph is None:
        from ..crustdata.client import CrustdataClient
        graph = Graph(CrustdataClient())
    for title, sponsor, to, body, signed in CASES:
        sc = SPONSORS[sponsor]
        p, key = issue_passport("Sourced", "AI recruiter", Sponsor(**sc["sponsor"]), ["outreach.hiring"])
        v, sent = await send_if_allowed(p, sign_message(p, key, signed or body), to, body, "outreach.hiring", today=TODAY, graph=graph)
        print(f"\n== {title}  [sponsor {sc['sponsor']['name']} @ {sc['sponsor']['company']}]\n   \"{body}\"")
        print(f"   -> {v.decision.upper()}{' (written to outbox)' if sent else ''}   ledger {(v.ledger_entry or '')[:12]}")
        for c in v.checks:
            mark = {"pass": "ok ", "fail": "XX ", "unverifiable": "?? "}[c.status]
            src = f"  [{c.source.endpoint}{' ' + c.source.field if c.source and c.source.field else ''}]" if c.source else ""
            if c.status != "pass" or c.name in ("recipient_still_at_company", "claims_in_body_true", "sponsor_still_employed"):
                print(f"   {mark}{c.name}: {c.detail}{src}")


if __name__ == "__main__":
    asyncio.run(main())
