"""Agaxes client for an outside agent (Claude Code, a cron job, another company's bot), run on the agent's machine.

Every call is signed locally with the agent's own key (read from the registry store at AGENTS_PATH, as agent_sign.py
does); only signatures cross the wire. Talks to AGAXES_API_URL (default http://localhost:8000).

    python scripts/agaxes_agent.py next <agent_id> [--task <task_id>]
    python scripts/agaxes_agent.py progress <agent_id> <task_id> "what I just did" [--done N --total M]
    python scripts/agaxes_agent.py send <agent_id> <task_id> --name N --url U --company C --scope outreach.hiring "body"
    python scripts/agaxes_agent.py done <agent_id> <task_id> "final report" [--failed]

Prints STOP (exit code 3) whenever Agaxes tells the agent to stop: paused, suspended, offboarded, or task cancelled.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("next"); n.add_argument("agent_id"); n.add_argument("--task")
    p = sub.add_parser("progress"); p.add_argument("agent_id"); p.add_argument("task_id"); p.add_argument("text")
    p.add_argument("--done", type=int); p.add_argument("--total", type=int)
    s = sub.add_parser("send"); s.add_argument("agent_id"); s.add_argument("task_id"); s.add_argument("body")
    s.add_argument("--name", required=True); s.add_argument("--url", required=True); s.add_argument("--company", required=True)
    s.add_argument("--scope", default="outreach.hiring")
    d = sub.add_parser("done"); d.add_argument("agent_id"); d.add_argument("task_id"); d.add_argument("text")
    d.add_argument("--failed", action="store_true")
    a = ap.parse_args()

    from app.agents import registry
    from app.agents.models import Passport
    from app.agents.passport import sign_message
    from app.runtime.external import signed_text

    base = os.getenv("AGAXES_API_URL", "http://localhost:8000").rstrip("/") + "/api/runtime/agent"
    p_ = Passport.model_validate(registry.get_agent(a.agent_id)["passport"])
    key = registry.private_key(a.agent_id)

    def call(action: str, task_id: str | None, text: str = "", **extra) -> dict:
        ts = int(time.time())
        sig = sign_message(p_, key, signed_text(action, a.agent_id, task_id, ts, text))
        r = httpx.post(f"{base}/{action}", json={"agent_id": a.agent_id, "task_id": task_id, "ts": ts, "text": text,
                                                 "signature": sig, **extra}, timeout=120)
        if r.status_code >= 400:
            print(f"REFUSED ({r.status_code}): {r.json().get('detail', r.text)}")
            sys.exit(2)
        return r.json()

    if a.cmd == "next":
        res = call("claim", a.task)
    elif a.cmd == "progress":
        res = call("progress", a.task_id, a.text, done=a.done, total=a.total)
    elif a.cmd == "done":
        res = call("complete", a.task_id, a.text, ok=not a.failed)
    else:
        r = httpx.post(f"{base}/send", json={"agent_id": a.agent_id, "task_id": a.task_id, "body": a.body, "scope": a.scope,
                                             "to": {"name": a.name, "profile_url": a.url, "company": a.company},
                                             "signature": sign_message(p_, key, a.body)}, timeout=300)
        res = r.json() if r.status_code < 400 else {"stop": True, "reason": r.text}
    print(json.dumps(res, indent=2))
    if res.get("stop"):
        print(f"STOP: {res.get('reason')}. Do nothing else on this task.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
