"""Run the two high-volume hiring jobs end to end on real Crustdata data and print the scorecards.

    cd backend && python scripts/run_talent.py --live                 # fetch real pools, record them, run both
    cd backend && python scripts/run_talent.py                        # replay the recorded pools (fixtures/*/pool.json)
    cd backend && python scripts/run_talent.py --only staffing --shifts 1000 --fake-rate 0.15
    cd backend && python scripts/run_talent.py --only campaign --brief "...three lines..." --size 100 --days 42

staffing   ~1,200 real shift workers from Person Search (6 lines of work x 6 cities) become applicants, 15% with one
           planted lie; every application is screened against the record, 1,000 shifts are assigned. Prints fake-catch
           precision/recall (per lie type) and fill rate. Report: backend/data/talent/staffing_report.json
campaign   the brief is parsed, ~100 real candidates sourced and ranked, and Sourced (the onboarded AI recruiter, needs
           contract.sign for offers: added here through the sponsor's live authority check) runs every conversation
           through Send Guard on a simulated clock with simulated replies until an offer is signed.
           Transcripts: backend/data/campaigns/<id>.json

--live records the pools to fixtures/staffing/pool.json and fixtures/campaign/pool.json so the API's replay works.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND.parent / ".env")
load_dotenv(BACKEND / ".env")

BRIEF = "Senior backend engineer, payments, Bangalore\nBudget 40-55 LPA, notice under 60 days\nOne hire, start by January"


def pct(x):
    return "n/a" if x is None else f"{x:.1%}"


async def staffing(a, client) -> dict:
    from app.talent.pool import PoolGraph, load_pool, save_pool
    from app.talent.staffing import fetch_shift_pool, make_shifts, run_staffing, seed_applications

    t0 = time.time()
    if a.live:
        pool = await fetch_shift_pool(client, per_role=a.per_role)
        save_pool("staffing", pool, {"source": "crustdata person/search", "per_role": a.per_role})
        print(f"[staffing] fetched {len(pool)} real profiles live in {time.time() - t0:.0f}s -> fixtures/staffing/pool.json")
    else:
        pool, _ = load_pool("staffing")
        print(f"[staffing] replaying {len(pool)} recorded profiles")
    if not pool:
        print("[staffing] no pool: run with --live")
        return {}
    today = date.fromisoformat(a.today) if a.today else date.today()
    apps, key = seed_applications(pool, fake_rate=a.fake_rate, seed=a.seed, today=today)
    shifts = make_shifts(a.shifts, start=today + timedelta(days=1), seed=a.seed)

    async def say(ev):
        if ev["type"] == "step":
            print(f"[staffing] {ev['message']}")
    out = await run_staffing(apps, shifts, PoolGraph(pool, client), today=today, answer_key=key, emit=say)
    r, fc = out["report"], out["report"]["fake_catch"]
    print(f"\n[staffing] {len(apps)} applications, {fc['fakes_planted']} fakes planted")
    print(f"  fake catch: precision {pct(fc['precision'])}  recall {pct(fc['recall'])}  "
          f"(TP {fc['true_positives']}, FP {fc['false_positives']}, FN {fc['false_negatives']}); fakes staffed: {len(fc['fakes_staffed'])}")
    for lie, d in fc["by_lie_type"].items():
        print(f"    {lie:22s} {d['caught']}/{d['planted']}")
    print(f"  fill rate: {r['filled']}/{r['shifts']} = {pct(r['fill_rate'])} with {r['workers_used']} workers "
          f"({r['workers_cleared']} cleared); open: {r['open_reasons']}")
    for fa in fc["false_alarms"][:10]:
        print(f"    false alarm {fa['app_id']}: {fa['reason']}")
    for m in fc["missed"][:10]:
        print(f"    missed {m['app_id']}: {m['lie']} ({m['truth']})")
    d = BACKEND / "data" / "talent"
    d.mkdir(parents=True, exist_ok=True)
    (d / "staffing_report.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"  full report: {d / 'staffing_report.json'} ({time.time() - t0:.0f}s)")
    return r


async def campaign(a, client) -> dict:
    from app.agents import registry
    from app.sourced_agent import resolve_agent_id
    from app.talent import campaign as C
    from app.talent.pool import load_pool, save_pool

    aid = resolve_agent_id(a.agent)
    try:
        rec = registry.get_agent(aid)
    except Exception:  # noqa: BLE001
        print(f"[campaign] no agent {a.agent}: run scripts/onboard_sourced.py first")
        return {}
    if "contract.sign" not in rec["passport"]["scopes"]:
        print("[campaign] granting contract.sign (offer letters) through the sponsor's live authority check...")
        try:
            rec, v = await registry.set_scopes(aid, [*rec["passport"]["scopes"], "contract.sign"], client)
        except registry.ScopeDenied as e:
            print(f"[campaign] sponsor can't grant offers: {e}. Offers will be held for a countersign.")
    pool = None
    if not a.live:
        pool, _ = load_pool("campaign")
        pool = pool or None
        print(f"[campaign] replaying {len(pool or [])} recorded candidates" if pool else "[campaign] no recorded pool, sourcing via the client")
    t0 = time.time()
    start = datetime.combine(date.today(), datetime.min.time()).replace(hour=9)
    camp, eng = await C.create(a.brief, aid, client, size=a.size, mode="sim", seed=a.seed, start=start, pool=pool)
    if a.live and camp.get("records"):
        save_pool("campaign", camp["records"], {"brief": a.brief, "source": "crustdata person/search"})
    print(f"[campaign] {camp['id']}: {len(camp['conversations'])} conversations opened in {time.time() - t0:.0f}s; job {camp['job']}")
    if not camp["conversations"]:
        print("[campaign] no candidates found for this brief; nothing to run")
        return {}
    for day in range(0, a.days, 7):
        await eng.advance(eng.now + timedelta(days=7))
        C.save(camp)
        s = eng.summary()
        print(f"  day {s['day']:>2}: {s['stages']}  guard allowed {s['stats']['guard_allowed']}, blocked {s['stats']['guard_blocked']}")
        if s["status"] == "filled":
            break
    s = eng.summary()
    print(f"[campaign] {s['status']} on day {s['day']}; funnel {s['funnel']}")
    for h in s["hires"]:
        print(f"  signed: {h['name']} at {h['ctc_lpa']} LPA on {h['at'][:10]}, offer sha256 {h['doc_sha256'][:12]}, ledger {h['ledger_entry'][:12]}")
    print(f"  transcripts: {C.campaigns_dir() / (camp['id'] + '.json')} ({time.time() - t0:.0f}s)")
    return s


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="fetch fresh pools from Crustdata and record them")
    ap.add_argument("--only", choices=["staffing", "campaign"])
    ap.add_argument("--shifts", type=int, default=1000)
    ap.add_argument("--fake-rate", type=float, default=0.15)
    ap.add_argument("--per-role", type=int, default=250)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--today")
    ap.add_argument("--brief", default=BRIEF)
    ap.add_argument("--agent", default="sourced")
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--days", type=int, default=42)
    a = ap.parse_args()
    from app.agents.api import crustdata

    client = crustdata()
    if a.live and (client is None or client.mode == "replay"):
        print("--live needs CRUSTDATA_API_KEY in .env and CRUSTDATA_MODE=cache or live")
        return 2
    if a.only != "campaign":
        await staffing(a, client)
    if a.only != "staffing":
        await campaign(a, client)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
