# Real-product audit (2026-10-31, ~12:00 IST)

Audit of every branch (`main`, `ws/*`, Countersign `claude/project-thread-icv883` passport + ledger,
`claude/project-thread-gz8tzg` Send Guard + MCP, `claude/project-thread-kiaijw` AI employee registry + console)
for mocks, seeded data posing as real, stubbed flows and missing pieces. All three Countersign branches merge
cleanly together (only CONTEXT.md conflicted; main's copy kept). With this branch's additions, **108 backend tests pass**.

## What is already real (checked in code)
- Sourced: brief parsing, Person Search with auto-broadening, Person/Company Enrich, verifier, ranker and outreach
  all hit Crustdata and Gemini in `live`/`cache` mode. Fallbacks (keyword brief parse, template outreach) are
  labelled in the stream, never silent. `LLM_MODE` defaults to `live`; mock only when set.
- Passport: Ed25519 issuer signature, expiry, revocation via the ledger, and live sponsor checks (exists, still
  employed, domain via Company Identify, title can grant the scope). Verified live on the Mac (LIVE_CHECK.md).
- Send Guard: message signature, recipient still at company, every factual claim in the draft checked by the
  verifier. Fails closed. Verified live (GUARD_LIVE_CHECK.md).
- Ledger: append-only, hash-chained, `verify_chain()` finds the first tampered line.
- Registry: role ceilings, fail-closed suspension, reinstate only after a fresh live check.

## Gap list, by priority

| # | Gap | Status / owner |
|---|---|---|
| **P0-1** | Countersign was three unmerged branches, and Sourced never ran under a passport: no passport check, no ledger entries for its runs, drafts never went through Send Guard | **Fixed on this branch.** `GET/POST /api/agents/{agent_id}/run` (`backend/app/sourced_agent.py`): live passport check (`data.read`) before any search, a blocked passport stops the run; `run.started` / `run.finished` ledger entries carrying every claim source; each shortlisted draft is signed with the agent's key and checked by Send Guard (`guard` steps, `candidate.guard`). `scripts/onboard_sourced.py` onboards Sourced in the real store. Needs the PR merged |
| **P0-2** | Web UI defaults to **Replay** (a recorded `fixtures/run.jsonl`) unless `NEXT_PUBLIC_DEFAULT_MODE=live` | UI thread (PR #5): default to Live, keep Replay as an explicit, labelled fallback. Also: call `/api/agents/{NEXT_PUBLIC_AGENT_ID}/run` when that env is set, render the `passport` and `guard` steps, and show a cleared/blocked badge from `candidate.guard` |
| **P0-3** | Demo plan says record in replay mode | Main (Mac) thread: record a **live** run (`CRUSTDATA_MODE=cache`, `LLM_MODE=live`), replay only as backup. Show `/api/health` (live modes) on screen |
| **P0-4** | Live guard cost: each shortlisted draft costs one more Person Enrich (15 req/min). On a rate limit the guard fails closed and shows "blocked" | Main (Mac) thread: do one live run through `/api/agents/{id}/run` before recording; lower `GUARD_MAX` (default 5) if needed |
| **P1-5** | Seeded fakes could only be shown in a terminal (no resume endpoint) | **Fixed (backend):** `POST /api/verify_resume {name, profile_url, claimed:{employer,title,start_date,...}}` returns cited claims and writes a `resume.verified` ledger entry. A small form in the UI is the UI thread's call; curl works today |
| **P1-6** | No agent actually called the MCP guard | **Fixed:** `scripts/mcp_agent_demo.py` spawns `mcp_server.py` and speaks MCP JSON-RPC over stdio (initialize, tools/list, sign, check_before_send, ledger_lookup); clean draft ALLOW, false tenure BLOCK, chain OK. For the video, the Mac thread can also add it to Claude Code (`claude mcp add countersign -- python backend/mcp_server.py`) so a real external agent calls it |
| **P1-7** | No human auth: anyone who reaches the API can onboard, suspend, reinstate, widen scopes, or mint a signed passport (`/api/passport/issue`) | Passport thread (issue route) + console thread (registry routes, console header). Smallest fix: `COUNTERSIGN_ADMIN_TOKEN` checked on mutating routes. Fine for a local demo; say it's on the roadmap |
| **P1-8** | MCP tools take the full passport JSON, and `sign_message` sends the agent's private key over the wire | Send Guard thread: accept `agent_id` and load the passport from the registry; keep signing on the agent side |
| **P1-9** | No committed proof of the live eval (reports are gitignored because they name real people) | Main (Mac) thread: commit a redacted scorecard (checks passed, timings, counts, no names) next to the existing LIVE_CHECK notes |
| **P1-10** | Console falls back to a recorded snapshot automatically when the backend is down | Labelled "snapshot", so honest. Console thread: make sure the video shows the "live" badge |
| P2-11 | Persistence is JSON files under `backend/data/` (single process) | Roadmap: SQLite/Postgres |
| P2-12 | Key management: issuer key in a local file or env, agent private keys in plaintext in `agents.json` | Roadmap: KMS, agent-held keys |
| P2-13 | No hosted URL: Vertex ADC only on laptops; cloud sandboxes can't reach api.crustdata.com | Roadmap: Dockerfile + host, Gemini API-key path. Cloud runs need `api.crustdata.com` allowed in the project's cloud environment |
| P2-14 | Payroll re-check is a button, not scheduled | Roadmap: cron `recheck_all` / Crustdata Watcher |
| P2-15 | Nothing is ever really sent | By design (event rule): allowed drafts go to the outbox file |

## Run it end to end (Mac, live)
```bash
cd backend
python scripts/onboard_sourced.py            # live sponsor check; prints the agent id
uvicorn app.main:app --port 8000
curl -N "localhost:8000/api/agents/<agent_id>/run?brief=senior+backend+engineer+payments+bangalore"
curl -s localhost:8000/api/ledger | jq '.chain_ok, [.entries[].kind]'
curl -s -X POST localhost:8000/api/verify_resume -H 'content-type: application/json' \
  -d '{"profile_url":"https://www.linkedin.com/in/pankajsavaliya","claimed":{"employer":"Google"}}'
python scripts/mcp_agent_demo.py             # an agent calling Send Guard over MCP
```
Offline check of the same flow: `CRUSTDATA_MODE=replay LLM_MODE=mock python -m pytest -q tests/test_sourced_agent.py`.
