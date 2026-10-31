"""Sign a message body as an onboarded agent, locally. For outside agents (e.g. Claude Code) that call
Countersign over MCP: the MCP tools take a signature, never a private key, so the agent signs here first.

    python scripts/agent_sign.py <agent_id> "<exact body>"            -> base64 signature for check_before_send
    python scripts/agent_sign.py <agent_id> --work <kind> "<summary>"  -> signature for record_work (no details)

Reads the agent's key from the registry store (AGENTS_PATH), so it runs on the agent's own machine.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_id")
    ap.add_argument("body")
    ap.add_argument("--work", metavar="KIND", help="sign a record_work filing with this kind; body is the summary")
    a = ap.parse_args()

    from app.agents import registry
    from app.agents.models import Passport
    from app.agents.passport import sign_message
    from app.fleet.base import work_body

    rec = registry.get_agent(a.agent_id)
    body = work_body(a.work, a.body, None) if a.work else a.body
    print(sign_message(Passport.model_validate(rec["passport"]), registry.private_key(a.agent_id), body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
