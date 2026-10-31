"""Run the guided fleet demo in a terminal: the same seven-beat story the console's demo page streams.

    cd backend && python scripts/run_fleet.py                                       # live (.env modes), real store
    cd backend && python scripts/run_fleet.py --claude-code                         # + the real Claude Code CLI
    cd backend && CRUSTDATA_MODE=replay LLM_MODE=mock python scripts/run_fleet.py --store /tmp/fleet   # offline

Beats (app/fleet/demo.py): 1 onboard, 2 real work (Pipeline sales, Reference resume checks, Diligence vendor brief),
3 sponsor left (payroll run suspends Closer, then refuses it), 4 scope refusal (Diligence emails a vendor),
5 wrong facts (stale CRM row, false tenure), 6 tampering (forged passport, edited ledger copy), 7 Claude Code.
Every agent reaches Countersign only over the MCP server. Exit 1 if any beat's outcome is wrong.

Options: --store DIR (default backend/data, which the console reads), --only work,stale,... (beat ids; onboard always
runs), --vendor, --leads, --applicants, --today YYYY-MM-DD, --pause SECONDS (between beats, for a live narration),
--sourced (also run Sourced's hiring pipeline under its passport), --brief, --json (raw events), -v (every check).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(BACKEND / ".env")

TTY = sys.stdout.isatty()
G, R, B, DIM, END = (("\033[32m", "\033[31m", "\033[1m", "\033[2m", "\033[0m") if TTY else ("",) * 5)


def set_store(store: Path | None) -> None:
    if store is None:
        return
    store.mkdir(parents=True, exist_ok=True)
    for var, name in (("AGENTS_PATH", "agents.json"), ("LEDGER_PATH", "ledger.jsonl"),
                      ("ISSUER_KEY_PATH", "issuer_ed25519.key"), ("OUTBOX_PATH", "outbox.jsonl")):
        os.environ[var] = str(store / name)


def src(c: dict) -> str:
    s = c.get("source") or {}
    return f" {DIM}({s.get('endpoint')}{', ' + s['field'] if s.get('field') else ''}){END}" if s.get("endpoint") else ""


def show(ev: dict, verbose: bool) -> None:
    t = ev["type"]
    if t == "start":
        print(f"{B}Countersign fleet demo{END}  store {ev['store']}  "
              f"CRUSTDATA_MODE={ev['modes']['crustdata']}  LLM_MODE={ev['modes']['llm']}")
    elif t == "beat":
        print(f"\n{B}{'=' * 4} {ev['n']}. {ev['title']} {'=' * max(4, 86 - len(ev['title']))}{END}\n{DIM}{ev['narration']}{END}")
    elif t == "line":
        print(ev["text"])
    elif t == "verdict":
        if ev["action"] in ("clock_in", "send") and not verbose and ev["agent"] != "Claude Code" and "Forged" not in ev["headline"]:
            return  # the agent's own line already said it; -v prints every check
        col = G if ev["decision"] == "allow" else R
        print(f"  {col}{(ev['decision'] or '?').upper():<5}{END} [{ev['action']}] {ev['agent']}: {ev['headline']}")
        for c in ev.get("checks", []):
            if verbose or c.get("status") != "pass":
                print(f"         {c.get('status'):>12}  {c.get('name')}: {c.get('detail')}{src(c)}")
    elif t == "finding" and verbose:
        for c in ev["contradicted"]:
            print(f"         contradicted  {c['claim']}{src(c)}")
    elif t == "artifact":
        print(f"  wrote {ev['path']}")
    elif t == "beat_done":
        print(f"  {G + 'OK' if ev['ok'] else R + 'FAIL'}{END}  {ev['summary']}")
    elif t == "error":
        print(f"  {R}error{END} {ev['message']}")
    elif t == "done":
        print(f"\n{B}{'=' * 4} Scorecard {'=' * 80}{END}")
        print(f"  {'agent':<12} {'status':<10} {'checked':>7} {'allowed':>7} {'blocked':>7} {'work':>5}  top block reason")
        for a in ev["scorecard"]:
            top = a["block_reasons"][0][0] if a.get("block_reasons") else ""
            print(f"  {a['agent']:<12} {a['status']:<10} {a['messages_checked']:>7} {a['allowed']:>7} {a['blocked']:>7} "
                  f"{a.get('work_filed', 0):>5}  {top}")
        print(f"  ledger: {ev['entries']} entries, chain {'intact' if ev['chain_ok'] else 'BROKEN'}")
        print(f"\n{G + 'PASS' if ev['ok'] else R + 'FAIL'}{END}")


async def run_sourced(brief: str, client) -> bool:
    from app.agents import registry
    from app.sourced_agent import run_as_agent

    ag = next((a for a in registry.list_agents() if a["name"] == "Sourced" and a["status"] == "active"), None)
    if not ag:
        print("  Sourced is not active in this store")
        return False
    print(f"\n{B}==== Sourced: hiring run under its passport {'=' * 50}{END}\n  brief: {brief}")
    done, guarded = False, 0
    async for ev in run_as_agent(brief, ag["agent_id"], client):
        if ev["type"] == "step" and ev.get("step") in ("passport", "guard"):
            print(f"  {ev['step']:<9} {ev['message']}")
            guarded += bool(ev["step"] == "guard" and (ev.get("data") or {}).get("decision"))
        elif ev["type"] == "error":
            print(f"  error     {ev['message']}")
        elif ev["type"] == "done":
            done = True
    if os.getenv("CRUSTDATA_MODE", "cache") == "replay":
        print(f"  {DIM}replay: no recorded search for this brief, so no shortlist; not counted{END}")
        return done
    print(f"  {G + 'OK' if done and guarded else R + 'FAIL'}{END}  {guarded} shortlisted draft(s) went through Send Guard")
    return done and guarded > 0  # a live run that guards nothing hasn't shown anything


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path)
    ap.add_argument("--only")
    ap.add_argument("--vendor", default="razorpay.com")
    ap.add_argument("--leads", type=Path, default=ROOT / "fixtures/fleet/pipeline_leads.json")
    ap.add_argument("--applicants", type=Path)
    ap.add_argument("--today", type=date.fromisoformat)
    ap.add_argument("--pause", type=float, default=0.0)
    ap.add_argument("--claude-code", action="store_true")
    ap.add_argument("--sourced", action="store_true")
    ap.add_argument("--brief", default="senior backend engineer payments bangalore")
    ap.add_argument("--json", action="store_true", help="print the raw event stream (one JSON object per line)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    set_store(a.store)
    os.environ.setdefault("LOG_LEVEL", "ERROR")  # replay misses and retries are noise; the beats say what happened
    logging.basicConfig(level=os.environ["LOG_LEVEL"], format="%(levelname)s %(name)s: %(message)s")

    from app.agents.api import crustdata
    from app.fleet.demo import BEATS, DemoOptions, story

    client = crustdata()
    only = ["onboard", *a.only.split(",")] if a.only else [b[0] for b in BEATS]
    opts = DemoOptions(store=a.store, client=client, today=a.today, vendor=a.vendor, leads=a.leads,
                       applicants=a.applicants, claude_code=a.claude_code, only=only)
    ok = False
    try:
        async for ev in story(opts):
            print(json.dumps(ev, default=str)) if a.json else show(ev, a.verbose)
            if ev["type"] == "beat_done" and a.pause:
                await asyncio.sleep(a.pause)
            if ev["type"] == "done":
                ok = ev["ok"]
        if a.sourced:
            ok &= await run_sourced(a.brief, client)
    finally:
        if client is not None:
            await client.aclose()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
