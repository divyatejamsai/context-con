# Backend (WS2: pipeline + API)

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in keys; never commit .env
uvicorn app.main:app --reload --port 8000
```

| Env | Values | Notes |
|---|---|---|
| `LLM_MODE` | `live` / `mock` | `mock` needs no Vertex credentials (heuristic brief parsing, template outreach) |
| `CRUSTDATA_MODE` | `cache` (default) / `live` / `replay` / `dev` | `dev` = synthetic people, no network. `replay` needs person-level responses in `cache/` (they are not committed) |
| `MAX_ENRICH` | default 10 | candidates that get full enrich/verify/rank/outreach |
| `MIN_POOL` | default 3 | search auto-broadens while fewer profiles than this |

Endpoints: `POST /api/run {"brief": "..."}` (SSE), `GET /api/run?brief=...` (SSE for EventSource),
`GET /api/replay?delay=0.6` (streams `fixtures/run.jsonl`, demo safety net), `GET /api/health`.

Quick check: `curl -N -X POST localhost:8000/api/run -H 'content-type: application/json' -d '{"brief":"sr backend eng, payments, blr"}'`

Tests: `LLM_MODE=mock python -m pytest -q`

Pipeline (`app/orchestrator.py`): parse brief (`brief.py`) -> person search per title variant in parallel, broadening
(drop seniority -> drop location -> skills only) while results are thin -> pick top `MAX_ENRICH` by a cheap prescore ->
per candidate, concurrently: Person + Company Enrich -> WS3 `verify_candidate` -> WS3 `rank_candidate` -> outreach draft
(never sent). If WS3's verifier/ranker is missing or throws, a basic one in `fallbacks.py` keeps the run going.
Claim ids are namespaced per candidate (`c3-k1`) and reasons citing unknown claim ids are dropped.

Person search: the orchestrator builds simple filters and `to_crustdata_filters()` turns them into the real grammar
(title `(.)` on `experience.employment_details.current.title`, city spellings OR-ed, country `=`). Person Enrich is one
batched `person_enrich_many` call per run (the endpoint allows 15 req/min). Simple filter shape:
`{"titles": [one title], "locations": [...], "skills": [...], "seniority": str | None}`
