## How to run

> Draft from WS5. Paste into the repo README; commands to be confirmed against WS1/WS2/WS4 once they land.

**Prereqs:** Python 3.11, Node 20+, a Crustdata API key, gcloud with access to the Vertex AI project.

```bash
git clone https://github.com/divyatejamsai/context-con && cd context-con
cp .env.example .env    # fill CRUSTDATA_API_KEY, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION
gcloud auth application-default login   # Vertex ADC for Gemini
```

**Backend** (FastAPI, port 8000)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/smoke_crustdata.py          # optional: checks every Crustdata endpoint
uvicorn app.main:app --reload --port 8000
```

**Frontend** (Next.js, port 3000)
```bash
cd frontend && npm install && npm run dev   # open http://localhost:3000
```

**Try it without the UI**
```bash
curl -N -X POST localhost:8000/api/run -H 'content-type: application/json' \
  -d '{"brief":"need a senior backend eng asap, payments exp, blr or remote india, ex startup pref"}'
```

**Modes** (env vars)
| Var | Values | Use |
|---|---|---|
| `CRUSTDATA_MODE` | `live` / `cache` / `replay` | `replay` runs fully offline from `cache/` + `fixtures/` (demo safety) |
| `LLM_MODE` | `live` / `mock` | `mock` returns canned JSON, no Vertex needed |

**Test briefs and seeded fakes:** see `demo/briefs.md` and `demo/seeded_fakes/README.md`.
