# context-con: Verified Hiring Agent

Built at **ContextCon 03 (IIT Bombay x Crustdata x YC)**, Hiring theme.

An autonomous recruiting agent: give it a messy three-line hiring brief and it returns a ranked shortlist of real candidates from Crustdata's people graph. Every claim about every candidate is checked and labelled **Verified / Contradicted / Unverifiable**, with its source attached. Outreach is drafted, never sent.

> **New here (human or AI agent)? Read [CONTEXT.md](CONTEXT.md) first.** It holds every decision, the architecture, the API contract, the build plan and the progress log.

## Stack
- Agent backend: Python 3.11, FastAPI, SSE streaming
- Frontend: Next.js, Tailwind, shadcn/ui
- LLM: Gemini on Vertex AI (ADC auth)
- Data: Crustdata API + Crustdata MCP

## How to run

**Prereqs:** Python 3.11+, Node 20+, a Crustdata API key, and gcloud access to a Vertex AI project (only for `LLM_MODE=live`).

```bash
git clone https://github.com/divyatejamsai/context-con && cd context-con
cp .env.example .env    # fill CRUSTDATA_API_KEY, GOOGLE_CLOUD_PROJECT. Never commit .env
gcloud auth application-default login   # Vertex ADC for Gemini (skip with LLM_MODE=mock)
```

**Backend** (FastAPI, port 8000)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/smoke_crustdata.py   # optional: checks every Crustdata endpoint
uvicorn app.main:app --reload --port 8000
```

**Frontend** (Next.js, port 3000)
```bash
cd frontend
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local   # optional, this is the default
npm run dev                  # open http://localhost:3000, toggle "Live" top-right (or /?mode=live)
```

**Try it without the UI**
```bash
curl -N -X POST localhost:8000/api/run -H 'content-type: application/json' \
  -d '{"brief":"need a senior backend eng asap, payments exp, blr or remote india, ex startup pref"}'
```

**Modes** (set in `.env`)
| Var | Values | Use |
|---|---|---|
| `CRUSTDATA_MODE` | `live` / `cache` / `replay` / `dev` | `cache` = live + saved responses; `replay` = fully offline from cache + `fixtures/` (demo safety); `dev` = synthetic people, no network |
| `LLM_MODE` | `live` / `mock` | `mock` needs no Vertex credentials |
| `MAX_ENRICH` / `MIN_POOL` | default 10 / 3 | candidates fully verified; search auto-broadens below this pool size |

No backend at all? The UI's default **Replay** mode streams a recorded run (`fixtures/run.jsonl`).

**Tests:** `cd backend && LLM_MODE=mock python -m pytest -q`

**Demo material:** test briefs and edge cases in [`demo/briefs.md`](demo/briefs.md), the video script in
[`demo/script.md`](demo/script.md), and seeded-fake resumes (real profiles plus planted lies the verifier must catch) in
[`demo/seeded_fakes/`](demo/seeded_fakes/README.md). More detail in [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md).
