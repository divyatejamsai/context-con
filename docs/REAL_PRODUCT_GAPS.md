# Real-product audit

## Round 2 (2026-10-31, ~12:20 IST)

Checked `main` (PRs #6, #7, #8 and ws/verify) merged with the open **PR #9** (console) and **PR #10** (agent fleet).
They merge with no conflicts. **130 backend tests pass** and `next build` is clean. The offline fleet run
(`run_fleet.py`, replay + mock) prints PASS: Pipeline 3 cleared, 1 stale lead blocked. Diligence's brief is filed
and its email refused (no scope). Reference contradicted every planted lie. Closer was suspended and refused twice.
The forged passport is blocked. The ledger chain is OK across 40 entries.

**Faked or seeded data found:** none posing as real. The console no longer falls back to a recorded snapshot
(PR #9), and the web UI defaults to Live (PR #7). The fleet's inputs are labelled test inputs: CRM leads
(`fixtures/fleet/pipeline_leads.json`), seeded-fake resumes and sponsor scenarios. All of them are real Crustdata
profiles, and every verdict comes from live checks.

**Fixed on this branch:** `agent_id=sourced` resolves to the newest active Sourced, so the UI can use
`NEXT_PUBLIC_AGENT_ID=sourced` and nobody copies ids. `backend/scripts/demo_up.sh` is one command: seed the fleet
into the real store, start the backend, start the UI as Sourced (Live), and the console is at `/console`.

| # | Gap | Owner |
|---|---|---|
| **P0-1** | **The demo script is stale.** `demo/script.md` still tells the hiring-only story, records in replay, and shows seeded fakes in a terminal. Nothing covers the passport, Send Guard, console, fleet or ledger | Demo thread: rewrite for the chosen story (see P0-2). Suggested beats are below |
| **P0-2** | **The submission story isn't decided.** The CONTEXT go/no-go was due 14:00: Hiring (Sourced) or Agaxes, or Sourced as Agaxes's first AI employee | The user |
| **P0-3** | **Nothing has run live since the merges.** In replay, Sourced finds 0 candidates because no search responses are cached in the repo, so the replay backup has nothing to show for Sourced | Mac/main thread: `git pull`, run `backend/scripts/demo_up.sh` live, run the demo brief once, and push the cache for that brief as fixtures (standing approval) so replay is a real backup |
| **P0-4** | PR #9 and PR #10 are open | The user, to merge. They merge cleanly, and tests and build pass with both |
| P1-5 | The fleet scorecard marks Sourced "OK" even when its run shortlists nobody and guards no drafts (that's what happens in replay) | Fleet thread: in live mode, require at least 1 guard verdict |
| P1-6 | README describes only the hiring agent: no Agaxes, console, fleet, MCP or `demo_up.sh` | Demo thread (owns the README "How to run") |
| P1-7 | Agent run routes (`/api/agents/{id}/run`) don't check the admin token, though the passport still gates the agent. Anyone who can reach the API can spend Crustdata credits | Roadmap, unless the API is exposed |
| P2 | Persistence in JSON files, agent keys stored in the registry, no hosted URL, payroll not scheduled (same as round 1) | Roadmap |

**Suggested 2-minute run of show (if the story is Sourced, managed by Agaxes):**
1. Paste an unseen brief, then show the passport check passing live (sponsor, employer and title cited).
2. Search, enrich and verify, then the shortlist with cited claims.
3. Send Guard clears a true draft. One edited with a false claim is blocked, with a citation.
4. Console: the fleet, then a payroll run that suspends Closer (its sponsor left) with a citation.
5. Ledger: chain OK. Edit one line in the file and the console flags the entry.
6. Close: every agent action is authorised by a real person, checked against Crustdata, and recorded.

---

## Round 1 (~12:00 IST)

Audit of every branch (`main`, `ws/*`, Agaxes `claude/project-thread-icv883` passport + ledger,
`claude/project-thread-gz8tzg` Send Guard + MCP, `claude/project-thread-kiaijw` AI employee registry + console)
for mocks, seeded data posing as real, stubbed flows and missing pieces. All three Agaxes branches merge
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
| **P0-1** | Agaxes was three unmerged branches, and Sourced never ran under a passport: no passport check, no ledger entries for its runs, drafts never went through Send Guard | **Fixed on this branch.** `GET/POST /api/agents/{agent_id}/run` (`backend/app/sourced_agent.py`): live passport check (`data.read`) before any search, a blocked passport stops the run; `run.started` / `run.finished` ledger entries carrying every claim source; each shortlisted draft is signed with the agent's key and checked by Send Guard (`guard` steps, `candidate.guard`). `scripts/onboard_sourced.py` onboards Sourced in the real store. Needs the PR merged |
| **P0-2** | Web UI defaults to **Replay** (a recorded `fixtures/run.jsonl`) unless `NEXT_PUBLIC_DEFAULT_MODE=live` | UI thread (PR #5): default to Live, keep Replay as an explicit, labelled fallback. Also: call `/api/agents/{NEXT_PUBLIC_AGENT_ID}/run` when that env is set, render the `passport` and `guard` steps, and show a cleared/blocked badge from `candidate.guard` |
| **P0-3** | Demo plan says record in replay mode | Main (Mac) thread: record a **live** run (`CRUSTDATA_MODE=cache`, `LLM_MODE=live`), replay only as backup. Show `/api/health` (live modes) on screen |
| **P0-4** | Live guard cost: each shortlisted draft costs one more Person Enrich (15 req/min). On a rate limit the guard fails closed and shows "blocked" | Main (Mac) thread: do one live run through `/api/agents/{id}/run` before recording; lower `GUARD_MAX` (default 5) if needed |
| **P1-5** | Seeded fakes could only be shown in a terminal (no resume endpoint) | **Fixed (backend):** `POST /api/verify_resume {name, profile_url, claimed:{employer,title,start_date,...}}` returns cited claims and writes a `resume.verified` ledger entry. A small form in the UI is the UI thread's call; curl works today |
| **P1-6** | No agent actually called the MCP guard | **Fixed:** `scripts/mcp_agent_demo.py` spawns `mcp_server.py` and speaks MCP JSON-RPC over stdio (initialize, tools/list, sign, check_before_send, ledger_lookup); clean draft ALLOW, false tenure BLOCK, chain OK. For the video, the Mac thread can also add it to Claude Code (`claude mcp add countersign -- python backend/mcp_server.py`) so a real external agent calls it |
| **P1-7** | No human auth: anyone who reaches the API can onboard, suspend, reinstate, widen scopes, or mint a signed passport (`/api/passport/issue`) | **Partly fixed:** `/api/passport/issue`, `/revoke`, `/reinstate` need `x-admin-token` when `COUNTERSIGN_ADMIN_TOKEN` is set (passport thread, merged here). Still open: the registry routes (`POST /api/agents`, suspend, reinstate, scopes) and the console sending the header (console thread) |
| **P1-8** | MCP tools take the full passport JSON, and `sign_message` sends the agent's private key over the wire | **Fixed:** MCP tools and `/api/guard/*` take `agent_id` (passport loaded from the registry), `sign_message` tool removed; agents sign locally. `mcp_agent_demo.py` updated |
| **P1-9** | No committed proof of the live eval (reports are gitignored because they name real people) | Main (Mac) thread: commit a redacted scorecard (checks passed, timings, counts, no names) next to the existing LIVE_CHECK notes |
| **P1-10** | Console falls back to a recorded snapshot automatically when the backend is down | Labelled "snapshot", so honest. Console thread: make sure the video shows the "live" badge |
| P2-11 | Persistence is JSON files under `backend/data/` (single process) | Roadmap: SQLite/Postgres |
| P2-12 | Key management: issuer key in a local file or env, agent private keys in plaintext in `agents.json` | Roadmap: KMS, agent-held keys |
| P2-13 | No hosted URL: Vertex ADC only on laptops; cloud sandboxes can't reach api.crustdata.com | Roadmap: Dockerfile + host, Gemini API-key path. Cloud runs need `api.crustdata.com` allowed in the project's cloud environment |
| P2-14 | Payroll re-check is a button, not scheduled | Roadmap: cron `recheck_all` / Crustdata Watcher |
| P2-15 | Nothing is ever really sent | By design (event rule): allowed drafts go to the outbox file |
| **P0-16** | Sourced was the only real agent, so the registry, guard and ledger had almost nothing to manage | **Fixed on `claude/project-thread-6gjqrs`:** a fleet of 5 more agents with different jobs, sponsors and scopes (`backend/app/fleet/`, docs/FLEET.md), all reaching Agaxes over MCP, plus a real Claude Code run. `scripts/run_fleet.py` runs it all. New MCP tool `record_work` files each agent's signed work with its sources |

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
python scripts/run_fleet.py --claude-code     # the whole fleet, incl. Claude Code, over MCP (docs/FLEET.md)
```
Offline check of the same flow: `CRUSTDATA_MODE=replay LLM_MODE=mock python -m pytest -q tests/test_sourced_agent.py`.
