"""Demo: an AI agent signs a short note and Agaxes emails it to your own test inbox with a Verify link.

    cd backend && python scripts/send_signed_email.py [--agent Offer] [--text "..."]

Needs the email settings in backend/.env (SMTP_HOST/SMTP_USER/SMTP_PASSWORD or RESEND_API_KEY, and OUTBOUND_TEST_TO =
your own address; nothing is ever sent anywhere else) and AGAXES_PUBLIC_URL pointing at the console the mail will be
opened next to (default http://localhost:3000). Open the email, click Verify: the page checks the agent's signature,
its passport, its sponsor and that the text wasn't changed. Suspend the agent in the console and reload: it turns red.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.agents import registry, seal  # noqa: E402
from app.agents.models import Passport  # noqa: E402
from app.agents.passport import sign_message  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="Scheduler", help="agent name on the payroll (default Scheduler)")
    ap.add_argument("--to", default="you", help="who the note is addressed to")
    ap.add_argument("--text", default=None)
    a = ap.parse_args()
    rec = next((x for x in registry.list_agents() if x["name"] == a.agent and x["status"] != "offboarded"), None) or \
        next((x for x in registry.list_agents() if x["status"] == "active" and x.get("private_key")), None)
    if not rec:
        print("No in-house agent on the payroll: onboard the fleet in the console first.")
        return 1
    p = Passport.model_validate(rec["passport"])
    s = p.sponsor
    text = a.text or (f"Hi {a.to},\n\nThis note was written and signed by {p.agent_name}, an AI agent working for "
                      f"{s.company}. Before you trust anything an AI agent sends you, click Verify below: it shows "
                      f"who vouches for the agent, what it's allowed to do, and whether this text was changed.\n\n"
                      f"{p.agent_name}")
    sig = sign_message(p, registry.private_key(rec["agent_id"]), text)
    scope = "outreach.hiring" if "outreach.hiring" in p.scopes else p.scopes[0]
    sid, _ = seal.issue(p, sig, text, scope, "message", {"name": a.to})
    res = await seal.email_copy(seal.get(sid), f"{p.agent_name} (AI agent for {s.company}): please verify me")
    print(f"Verify link: {seal.base_url()}/verify/{sid}")
    print("Emailed to " + res["delivered_to"] if res["emailed"] else f"Not emailed: {res['why']}")
    return 0 if res["emailed"] else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
