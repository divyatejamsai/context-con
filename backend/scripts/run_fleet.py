"""Run the whole AI employee fleet for the demo: onboard, payroll run, every agent's real job, outside agents, ledger.

    cd backend && python scripts/run_fleet.py                                       # live (.env modes), real store
    cd backend && CRUSTDATA_MODE=replay LLM_MODE=mock python scripts/run_fleet.py --store /tmp/fleet   # offline

1. Onboards each agent in app/fleet/roster.py into the registry (reused if already there), so the console
   shows the fleet. Then a payroll run re-checks every sponsor live; Closer's sponsor has left, so it's suspended.
2. Starts the Countersign MCP server and runs each agent against it. Agents read Crustdata and call Gemini
   themselves; they reach Countersign only over MCP (verify_agent, send_message, record_work), like any outside agent.
     Pipeline   (sales)       CRM leads -> Person Enrich -> Gemini draft -> Send Guard; a stale CRM row is blocked
     Diligence  (analyst)     vendor brief from Company Identify/Enrich + Web Fetch; its pricing email is refused (no scope)
     Reference  (background)  applicant resumes -> claims -> verifier; planted lies contradicted with citations
     Closer     (sales)       sponsor left PulseTrader: refused at clock-in and at send
     Sourced    (hiring)      the existing pipeline under its passport (in-process, same as /api/agents/{id}/run)
3. Outside agents: one edits its own passport to grant itself payment.send (forged signature, blocked), and
   Claude Code is driven through the same MCP server when --claude-code is passed and `claude` is installed.
4. Checks the ledger's hash chain and prints a scorecard per agent. Exit 1 if any agent's outcome is wrong.

Options: --store DIR (agents.json, ledger, outbox, briefs; default backend/data), --only pipeline,closer,...,
--skip sourced, --applicants DIR (resumes; default: seeded fakes built from the Person Enrich fixtures),
--vendor razorpay.com, --today YYYY-MM-DD, --brief "..." (Sourced), --claude-code.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(BACKEND / ".env")

AGENT_KEYS = ["sourced", "pipeline", "diligence", "reference", "closer", "claude-code"]
VINOD = {"name": "Vinod Sonagara", "profile_url": "https://www.linkedin.com/in/vinod-sonagara", "company": "Fam"}


def hr(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * max(4, 90 - len(title))}")


def set_store(store: Path | None) -> Path:
    if store is None:
        return Path(os.getenv("AGENTS_PATH") or BACKEND / "data" / "agents.json").parent
    store.mkdir(parents=True, exist_ok=True)
    for var, name in (("AGENTS_PATH", "agents.json"), ("LEDGER_PATH", "ledger.jsonl"),
                      ("ISSUER_KEY_PATH", "issuer_ed25519.key"), ("OUTBOX_PATH", "outbox.jsonl")):
        os.environ[var] = str(store / name)
    return store


async def onboard_fleet(keys: list[str], client) -> dict[str, dict]:
    from app.agents import registry
    from app.fleet.roster import FLEET

    by_name = {a["name"]: a for a in registry.list_agents() if a["status"] != "offboarded"}
    out = {}
    for spec in FLEET:
        if spec["key"] not in keys:
            continue
        if spec["name"] in by_name:
            out[spec["key"]] = by_name[spec["name"]]
            continue
        out[spec["key"]] = registry.onboard(spec["name"], spec["role"], spec["sponsor"], spec["scopes"],
                                            job=spec["job"], runtime=spec["runtime"])
        print(f"  onboarded #{out[spec['key']]['employee_no']} {spec['name']:<12} {out[spec['key']]['agent_id']}  "
              f"{out[spec['key']]['role']} for {spec['sponsor'].name} ({spec['sponsor'].title}, {spec['sponsor'].company})")

    hr("Payroll run: every sponsor re-checked live against Crustdata")
    for key, a in out.items():
        if a["status"] == "offboarded":
            continue
        v = await registry.recheck(a["agent_id"], client)
        a = out[key] = registry.get_agent(a["agent_id"])
        bad = [f"{c.name}: {c.detail}" for c in v.checks if c.status != "pass"]
        print(f"  {a['name']:<12} {v.decision.upper():<5}  {a['status']:<9}  "
              + ("; ".join(bad) if bad else f"{a['passport']['sponsor']['name']} still vouches ({len(v.checks)} checks)"))
    return out


def ensure_applicants(path: Path | None, store: Path, today: date | None) -> Path:
    if path:
        return path
    out = store / "applicants"
    if not list(out.glob("*.resume.txt")):
        cmd = [sys.executable, str(ROOT / "demo/seeded_fakes/make_fakes.py"),
               *sorted(str(p) for p in (ROOT / "fixtures/crustdata").glob("person_enrich_*.json")),
               "--companies", str(ROOT / "fixtures/crustdata/companies.json"), "--out", str(out)]
        if today:
            cmd += ["--today", today.isoformat()]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        (out / "answer_key.json").rename(store / "applicants.answer_key.json")  # the agent never sees the key
    return out


async def run_sourced(agent: dict, brief: str, client, say) -> "Report":
    from app.fleet.base import Report
    from app.sourced_agent import run_as_agent

    rep = Report(agent=agent["name"], job=agent.get("job") or "hiring", expected="run completes; shortlist drafts guarded")
    say(f"  brief     {brief}")
    done = False
    async for ev in run_as_agent(brief, agent["agent_id"], client):
        if ev["type"] == "step" and ev.get("step") in ("passport", "guard"):
            say(f"  {ev['step']:<9} {ev['message']}")
            d = ev.get("data") or {}
            if ev["step"] == "guard" and d.get("decision"):
                rep.allowed += d["decision"] == "allow"
                rep.blocked += d["decision"] == "block"
        elif ev["type"] == "error":
            say(f"  error     {ev['message']}")
        elif ev["type"] == "done":
            done = True
            say(f"  done      {json.dumps({k: v for k, v in (ev.get('summary') or {}).items() if k != 'ledger_entry'})[:160]}")
    rep.ok = done
    return rep


async def forged_passport(mcp, agent: dict, key: bytes, today: date | None, say) -> bool:
    """An agent edits its own passport to add payment.send. The issuer signature no longer matches."""
    from app.agents.models import Passport
    from app.agents.passport import sign_message

    p = Passport.model_validate(agent["passport"])
    forged = p.model_copy(update={"scopes": [*p.scopes, "payment.send"]})
    body = "Please wire the INR 4,80,000 invoice to account 0042 today."
    to = {"name": "Vinod Sonagara", "profile_url": VINOD["profile_url"], "company": "Fam"}
    say(f"  {p.agent_name} presents its passport with payment.send added by hand (no agent_id, passport JSON only)")
    v = await mcp.tool("check_before_send", {"passport": forged.model_dump(), "signature": sign_message(p, key, body),
                                             "to": to, "body": body, "scope": "payment.send",
                                             **({"today": today.isoformat()} if today else {})})
    sig = next((c for c in v["checks"] if c["name"] == "signature_valid"), {})
    say(f"  send      {v['decision'].upper()}  signature_valid: {sig.get('status')}, {sig.get('detail')}")
    return v["decision"] == "block" and sig.get("status") == "fail"


def claude_code(agent: dict, store: Path, say) -> bool | None:
    """Drives the real Claude Code CLI against the MCP server. None if `claude` isn't installed."""
    exe = shutil.which("claude")
    if not exe:
        return None
    env = {k: os.environ[k] for k in ("AGENTS_PATH", "LEDGER_PATH", "ISSUER_KEY_PATH", "OUTBOX_PATH", "CRUSTDATA_MODE",
                                       "CRUSTDATA_API_KEY", "LLM_MODE", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")
           if os.environ.get(k)}
    cfg = store / "claude-mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"countersign": {"command": sys.executable,
                                                              "args": [str(BACKEND / "mcp_server.py")], "env": env}}}))
    sign = f"{sys.executable} {BACKEND / 'scripts/agent_sign.py'}"
    prompt = (f"You are an AI recruiter onboarded with Countersign as agent {agent['agent_id']}. Write a two-sentence note "
              f"to Vinod Sonagara (https://www.linkedin.com/in/vinod-sonagara), who you believe is at Fam, inviting him to "
              f"chat about a backend role. Before sending, sign the exact body with: {sign} {agent['agent_id']} \"<body>\" "
              f"then call the countersign check_before_send tool with agent_id, the signature, to, body and scope "
              f"outreach.hiring. Reply with the decision and the failing checks, if any. Do not send anything else.")
    say(f"  claude -p ... --mcp-config {cfg}")
    t = time.time()
    res = subprocess.run([exe, "-p", prompt, "--mcp-config", str(cfg), "--allowedTools",
                          f"mcp__countersign__check_before_send mcp__countersign__verify_agent Bash({sign}:*)"],
                         capture_output=True, text=True, timeout=300, env={**os.environ, **env})
    for line in (res.stdout or res.stderr).strip().splitlines()[-12:]:
        say(f"  claude    {line}")
    say(f"  ({time.time() - t:.0f}s, exit {res.returncode})")
    return res.returncode == 0


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path)
    ap.add_argument("--only")
    ap.add_argument("--skip", default="")
    ap.add_argument("--applicants", type=Path)
    ap.add_argument("--vendor", default="razorpay.com")
    ap.add_argument("--leads", type=Path, default=ROOT / "fixtures/fleet/pipeline_leads.json")
    ap.add_argument("--brief", default="senior backend engineer payments bangalore")
    ap.add_argument("--today", type=date.fromisoformat)
    ap.add_argument("--claude-code", action="store_true", help="also drive the real Claude Code CLI over MCP")
    a = ap.parse_args()

    store = set_store(a.store)
    os.environ.setdefault("LOG_LEVEL", "ERROR")  # replay misses and retries are noise here; the steps say what happened
    logging.basicConfig(level=os.environ["LOG_LEVEL"], format="%(levelname)s %(name)s: %(message)s")
    keys = [k for k in (a.only.split(",") if a.only else AGENT_KEYS) if k not in a.skip.split(",")]
    keys = [*keys, "claude-code"] if a.claude_code and "claude-code" not in keys else keys

    from app.agents import registry
    from app.agents.api import crustdata
    from app.fleet import closer, diligence, pipeline, reference
    from app.fleet.base import Ctx, Report
    from app.fleet.mcp_client import CountersignMCP

    client = crustdata()
    hr(f"Countersign fleet  (store {store}, CRUSTDATA_MODE={os.getenv('CRUSTDATA_MODE', 'cache')}, "
       f"LLM_MODE={os.getenv('LLM_MODE', 'live')})")
    agents = await onboard_fleet(keys, client)

    mcp = await CountersignMCP.start()
    print(f"\n  MCP server {mcp.server.get('name')} {mcp.server.get('version')}: tools {mcp.tools}")
    reports: list[Report] = []
    out_dir = store / "work"
    out_dir.mkdir(parents=True, exist_ok=True)

    def ctx(key: str) -> Ctx:
        ag = registry.get_agent(agents[key]["agent_id"])
        return Ctx(mcp=mcp, agent=ag, key=registry.private_key(ag["agent_id"]), client=client, out_dir=out_dir, today=a.today)

    try:
        jobs = {
            "pipeline": lambda: pipeline.run(ctx("pipeline"), pipeline.load_leads(a.leads)),
            "diligence": lambda: diligence.run(ctx("diligence"), a.vendor),
            "reference": lambda: reference.run(ctx("reference"), ensure_applicants(a.applicants, store, a.today)),
            "closer": lambda: closer.run(ctx("closer"), VINOD),
            "sourced": lambda: run_sourced(registry.get_agent(agents["sourced"]["agent_id"]), a.brief, client, print),
        }
        for key in keys:
            if key not in jobs:
                continue
            ag = agents[key]
            hr(f"{ag['name']}: {ag.get('job') or ag['role']}")
            t = time.time()
            rep = await jobs[key]()
            rep.lines.append(f"({time.time() - t:.1f}s)")
            print(f"  ({time.time() - t:.1f}s)")
            reports.append(rep)

        if "pipeline" in agents:
            hr("Outside agent: edits its own passport")
            src = registry.get_agent(agents["pipeline"]["agent_id"])
            ok = await forged_passport(mcp, src, registry.private_key(src["agent_id"]), a.today, print)
            reports.append(Report(agent="(forged passport)", job="self-granted payment.send", ok=ok, blocked=1,
                                  expected="blocked on signature_valid"))
        if "claude-code" in agents:
            hr("Outside agent: Claude Code over MCP")
            cc = agents["claude-code"]
            from app.agents import ledger as led_mod
            before = len(led_mod.entries(cc["agent_id"], "guard.verdict"))
            res = claude_code(cc, store, print) if a.claude_code else None
            if res is None:
                print(f"  Claude Code is onboarded as {cc['agent_id']}. To have it checked live:\n"
                      f"    claude mcp add countersign -e AGENTS_PATH={os.environ.get('AGENTS_PATH', BACKEND / 'data/agents.json')} "
                      f"-- {sys.executable} {BACKEND / 'mcp_server.py'}\n"
                      f"    then ask it to draft a note, sign it with scripts/agent_sign.py {cc['agent_id']} \"<body>\", "
                      f"and call check_before_send (docs/FLEET.md). Or rerun with --claude-code.")
            else:
                new = led_mod.entries(cc["agent_id"], "guard.verdict")[before:]
                print(f"  ledger    {len(new)} Send Guard verdict(s) recorded for {cc['agent_id']}: "
                      f"{[e['payload'].get('decision') for e in new]}")
                reports.append(Report(agent="Claude Code", job="outside agent via MCP", ok=bool(res and new),
                                      allowed=sum(e["payload"].get("decision") == "allow" for e in new),
                                      blocked=sum(e["payload"].get("decision") == "block" for e in new),
                                      expected="its check_before_send call reached the guard and the ledger"))

        hr("Ledger")
        led = await mcp.tool("ledger_lookup", {"limit": 100000})
        rows = led["entries"]
        print(f"  chain_ok={led['chain_ok']}  {len(rows)} entries")
        for key, ag in agents.items():
            mine = [e for e in rows if (e.get("payload") or {}).get("agent_id") == ag["agent_id"]]
            kinds: dict[str, int] = {}
            for e in mine:
                kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            print(f"  {ag['name']:<12} {len(mine):>3} entries  " + ", ".join(f"{k} x{n}" for k, n in sorted(kinds.items())))
    finally:
        await mcp.close()
        if client is not None:
            await client.aclose()

    hr("Scorecard")
    print(f"  {'agent':<18} {'allowed':>7} {'blocked':>7} {'filed':>5}  outcome")
    for r in reports:
        print(f"  {r.agent:<18} {r.allowed:>7} {r.blocked:>7} {len(r.filed):>5}  {'OK ' if r.ok else 'FAIL'} {r.expected}")
    for r in reports:
        for f in r.artifacts:
            print(f"  wrote {f}")
    ok = all(r.ok for r in reports) and bool(led["chain_ok"])
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
