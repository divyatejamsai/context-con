# context-con: Countersign + Sourced

Built at **ContextCon 03 (IIT Bombay x Crustdata x YC)**.

**Sourced** is an autonomous hiring agent. Give it a messy three-line brief and it returns a ranked shortlist of real
candidates from Crustdata's people graph. Every claim about every candidate is labelled **Verified / Contradicted /
Unverifiable**, with its source attached. Outreach is drafted, never sent.

**Countersign** is trust infrastructure for AI employees, and Sourced is employee #1. Each agent gets an Ed25519
**passport** tied to a real human sponsor, and Countersign checks live against Crustdata that the sponsor exists, is
still employed, and can grant the agent's scopes. **Send Guard** blocks a draft before it goes out if the recipient
has moved on or the draft makes a false claim. A **payroll check** re-verifies every sponsor and suspends agents whose
sponsor has left. Every action lands on a **hash-chained ledger** with its citations, so editing any line is detected.
Any agent, Claude Code included, can reach it over **MCP**.

The **fleet** is six real agents for Countersign to manage: Sourced (hiring), Pipeline (sales), Diligence (vendor
briefs), Reference (resume checks), Closer (its sponsor left, so it gets suspended) and Claude Code (an outside
agent). See [docs/FLEET.md](docs/FLEET.md) and [docs/COUNTERSIGN.md](docs/COUNTERSIGN.md).

> **New here (human or AI agent)? Read [CONTEXT.md](CONTEXT.md) first.** It holds every decision, the architecture, the API contract, the build plan and the progress log.

## Stack
- Agent backend: Python 3.11, FastAPI, SSE streaming
- Frontend: Next.js, Tailwind, shadcn/ui
- LLM: Gemini on Vertex AI (ADC auth)
- Data: Crustdata API + Crustdata MCP
- Countersign: Ed25519 passports (`cryptography`), JSONL hash-chained ledger, MCP server (`backend/mcp_server.py`)

## How to run

**Prereqs:** Python 3.11+, Node 20+, a Crustdata API key, and gcloud access to a Vertex AI project (only for `LLM_MODE=live`).

```bash
git clone https://github.com/divyatejamsai/context-con && cd context-con
cp .env.example .env    # fill CRUSTDATA_API_KEY, GOOGLE_CLOUD_PROJECT (optional: COUNTERSIGN_ADMIN_TOKEN). Never commit .env
gcloud auth application-default login   # Vertex ADC for Gemini (skip with LLM_MODE=mock)
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && cd ..
```

**One command (demo / recording)**
```bash
backend/scripts/demo_up.sh             # seed the fleet live, then start the API on :8000 and the UI on :3000
backend/scripts/demo_up.sh --no-fleet  # store already seeded: just start the API and UI
```
It runs `backend/scripts/run_fleet.py`, which onboards the six AI employees, runs a payroll check and each agent's real
job, checks the ledger chain and prints a scorecard. Then it opens:
- `http://localhost:3000`: **Sourced**, running live under its passport, with drafts checked by Send Guard
- `http://localhost:3000/console`: the **Countersign console** (roster, passports, payroll check, Send Guard, ledger)

The steps below do the same by hand.

**Backend** (FastAPI, port 8000)
```bash
cd backend && source .venv/bin/activate
python scripts/smoke_crustdata.py   # optional: checks every Crustdata endpoint
uvicorn app.main:app --reload --port 8000
```

**Frontend** (Next.js, port 3000)
```bash
cd frontend
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local   # optional, this is the default
NEXT_PUBLIC_AGENT_ID=sourced npm run dev   # http://localhost:3000 (Sourced) and /console (Countersign)
```

**Countersign and the fleet**
```bash
cd backend
python scripts/run_fleet.py                  # live: onboard the fleet, payroll check, every agent's job, ledger check
python scripts/run_fleet.py --claude-code    # also drives the real Claude Code CLI over MCP
python scripts/mcp_agent_demo.py             # a minimal agent calling Send Guard over MCP
claude mcp add countersign -e AGENTS_PATH=$PWD/data/agents.json -- python $PWD/mcp_server.py   # give Claude Code the tools
```
State lives in `backend/data/` (agents.json, ledger.jsonl, outbox.jsonl; gitignored). Nothing is ever really sent:
cleared drafts go to `outbox.jsonl`.

**Try it without the UI**
```bash
curl -N "localhost:8000/api/agents/sourced/run?brief=senior+backend+engineer+payments+bangalore"   # Sourced under its passport
curl -s localhost:8000/api/ledger | jq '.chain_ok, [.entries[].kind]'
curl -s -X POST localhost:8000/api/verify_resume -H 'content-type: application/json' \
  -d '{"profile_url":"https://www.linkedin.com/in/pankajsavaliya","claimed":{"employer":"Google"}}'
```

**Modes** (set in `.env`)
| Var | Values | Use |
|---|---|---|
| `CRUSTDATA_MODE` | `live` / `cache` / `replay` / `dev` | `cache` = live + saved responses; `replay` = fully offline from cache + `fixtures/` (demo safety); `dev` = synthetic people, no network |
| `LLM_MODE` | `live` / `mock` | `mock` needs no Vertex credentials |
| `MAX_ENRICH` / `MIN_POOL` | default 10 / 3 | candidates fully verified; search auto-broadens below this pool size |

The UI defaults to **Live**. **Replay** (a recorded `fixtures/run.jsonl`) is an explicit, labelled fallback. Offline fleet check: `cd backend && CRUSTDATA_MODE=replay LLM_MODE=mock python scripts/run_fleet.py --store /tmp/fleet`.

**Tests:** `cd backend && LLM_MODE=mock python -m pytest -q`

**Demo material:** test briefs and edge cases in [`demo/briefs.md`](demo/briefs.md), the video script in
[`demo/script.md`](demo/script.md) (Countersign + fleet, run live), and seeded-fake resumes (real profiles plus planted lies the verifier must catch) in
[`demo/seeded_fakes/`](demo/seeded_fakes/README.md). More detail in [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md).
