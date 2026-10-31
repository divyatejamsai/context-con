# Project Context: ContextCon 03 (IIT Bombay) x Crustdata Hackathon

> Living handover doc. Anyone (human or AI agent) picking this up should be able to continue from here alone.
> Update it every time a decision is made or a milestone is hit. Newest entries go at the top of each log.

Last updated: 2026-10-31 ~10:35 IST (wall clock; earlier timestamps in this doc ran ahead and are approximate)

---

## 1. The event in one screen

- **What:** ContextCon IIT Bombay, "The Agentic Services Hackathon" (Techfest 2026-27, YC event, sponsored by Crustdata).
- **Goal set by organisers:** build an autonomous agent that does a professional service (normally done by a firm of people) end to end, with no human in the loop, on data about people and companies.
- **Hard requirements**
  - Must build on **Crustdata's API / identity graph** (people + company data). Using their keys is mandatory.
  - Deliverables by **3:30 PM IST**: a working code repo **and a 2-minute screen-recorded demo video** showing the product take a request it has never seen all the way to finished work.
  - Can be a single agent, a multi-agent system, an MCP server, or a CLI.
  - **Agents must not contact real people** during the event. Only the local environment and authorised APIs. (So: draft emails/messages, never send them.)
  - Prep/sketches allowed beforehand; **coding starts 10:30 AM IST**.
- **Judging criteria** (what we optimise for)
  1. End-to-end execution with no human intervention.
  2. Data integrity and verification: uses Crustdata's graph and **cites a source for every claim**.
  3. Robustness: messy inputs, unformatted requests, unexpected/empty tool responses.
  4. Demo clarity (2-min video, then live finals for shortlisted teams).
- **Timeline (IST, 31 Oct 2026):** 10:30 code start · 12:30 lightning talks · 1:30 optional mentor checkpoint · 3:00 last call · **3:30 code freeze + submission** · 5:00 finalists · 5:30 live finals · 7:30 winners.
- **Prizes:** $8k / $3k / $1k Crustdata credits, YC office hours (Jon Xu) for top 3, PPI chance at Crustdata for standout builders.

### Crustdata API (from the problem statement)
- Base: `https://api.crustdata.com`
- Headers: `authorization: Bearer <API_KEY>` and `x-api-version: 2025-11-01`
- Endpoints: Person Search, Person Enrich, Company Search, Company Identify, Company Enrich, Job Search, Web Search & Fetch, Watcher.
- **Crustdata MCP server:** `https://install.crustdata.com/mcp` (handy for exploring the API from Claude/Cursor during dev).
- **API key:** stored only in `.env` as `CRUSTDATA_API_KEY` (gitignored). Never commit it or paste it into this doc. See `.env.example`.
- (Fill in after the 10:00 API walkthrough: rate limits, credit cost per call, response shapes, gotchas.)

Source files: `yc-hackathon/ContextCon 03_ IIT Bombay · The Themes.pdf`, `yc-hackathon/ContextCon PS - CrustData.pdf`

---

## 2. Theme decision

### Constraints we judged against
- **5 hours of build time**, ending in a 2-minute video. Anything that needs data Crustdata doesn't have, backtesting over historical point-in-time data, or real payments/real people is high risk.
- **Crustdata fit**: the more the core loop is Person/Company/Job search + enrich, the less glue code and the higher the "data integrity" score.
- **Demo-ability**: a judge should see input -> agent working -> cited result in under 2 minutes.

### Theme scorecard

| Theme | Crustdata fit | 5-hr risk | Impressiveness | Verdict |
|---|---|---|---|---|
| **Hiring** | Excellent (Person Search/Enrich, Job Search, Company Enrich) | Low | High: "prove or disprove every claim" maps straight onto the verification criterion | **Recommended** |
| **Revenue** | Excellent (Company Search, Job Search as buying signal, Person Search for decision-maker, Watcher) | Low | High, but "AI SDR" is the most crowded idea in the room | Strong runner-up |
| Trust & compliance | Good for company side (Identify/Enrich), but registries, filings and other lenders' files are not in Crustdata | Medium | Very high if it works | Risky: no ground truth for "shell vs real" in 5 hrs |
| Investing | Good for founders/companies | High: judged on calls "tested on past dates using only what was known that day", needs point-in-time data | High | Avoid |
| Research & markets | Weak: needs filings/10-Ks, scored on future numbers | High | High | Avoid |
| Insurance | Weak: needs policies, photos, image forensics | High | Medium | Avoid |
| Buying & paying | Weak: invoices/ERP, not people/company data | Medium-High | Medium | Avoid |
| Agents that spend | Weak: needs real shops/payments, adversarial sellers | High | Medium | Avoid |
| Supply chain | Weak: shipments, BOMs, no-API portals | High | Medium | Avoid |
| Infrastructure for agents | Mixed ("who knows whom" graph fits; others don't) | Medium | Hard to show in a 2-min demo | Avoid unless strong infra team |

### Why Hiring (recommendation)
1. **Every step is a Crustdata call.** Brief -> Person Search -> Person Enrich -> Company Enrich -> Job Search / Web Fetch for evidence. Little external data needed, so little that can break.
2. **It scores on the hardest criterion for free.** The theme literally asks to "prove or disprove every claim on a candidate's record", which is the judges' "verifiable citation for every claim" criterion.
3. **Crustdata's edge is freshness** ("changed jobs weeks before their profile says so"). An agent that shows it caught a recent job change is a sponsor-pleasing demo moment.
4. **"A request it has never seen" is easy to show:** judges can type any three-line role brief live.
5. **Cheap pivot.** Hiring and Revenue share ~80% of the plumbing (people/company search + enrich + cited report). If Hiring stalls in the first hour, we can switch to Revenue without losing code.

### Proposed product shape (draft, to confirm)
**Working name:** "Brief-to-Shortlist" verified recruiting agent.

- **Input:** a messy 3-line hiring brief (e.g. "need a senior backend eng, payments exp, Bangalore, ex-startup, can start soon").
- **Agent loop:**
  1. Parse brief -> structured criteria, including title synonyms ("goes by another title").
  2. Person Search (multiple query variants) -> candidate pool.
  3. Person Enrich + Company Enrich on each -> full record.
  4. **Verifier agent:** checks each claim (current employer, tenure, title, company stage/size, location) against the graph and web fetch. Labels each claim Verified / Contradicted / Unverifiable, with the source attached.
  5. Rank candidates against the brief, with reasons that cite the evidence.
  6. Draft (never send) a personalised outreach note per top candidate.
- **Output:** a ranked shortlist report where every line has a citation, plus flagged claims.
- **Stretch goals:** (a) "applications seeded with fakes": feed in a few resumes with planted false claims and show the verifier catching them; (b) Watcher to re-check shortlisted candidates for job changes; (c) expose as an MCP server.
- **Robustness to show:** vague/typo'd brief, zero search results (auto-broaden), API errors/timeouts (retry + mark unverifiable instead of guessing).

### Status
- **Recommendation:** Hiring (runner-up: Revenue).
- **Decision:** ✅ **Hiring** chosen by user at 09:57 IST. Revenue stays the fallback if Hiring stalls in the first hour.

---

## 3. Decision log
| Time (IST) | Decision | Why | By |
|---|---|---|---|
| ~10:46 | Seeded-fake resumes are built locally and never committed | Public repo; they contain real people's records | WS5 |
| 10:43 | Ranker is deterministic and weighted (LLM only rewrites reason text, optional) | Reproducible scores; judges want decisions that stay the same however the case is worded | WS3 |
| 10:35 | Demo brief = B1 (payments backend, Bangalore) | Indian fintech is dense in Crustdata, so the demo returns rich results | WS5 |
| 10:35 | Seeded fakes are built from real Person Enrich fixtures, with lie types: stale_current_job, inflated_title, fake_employer, stretched_tenure, wrong_location | Lies must be disprovable from the graph | WS5 |
| 10:35 | Standard env var names: CRUSTDATA_MODE, LLM_MODE, GEMINI_FAST_MODEL, GEMINI_SMART_MODEL | Avoid naming drift between workstreams | Claude (doc owner) |
| 10:25 | Split build into 5 parallel workstreams (WS1-WS5) with fixed folder ownership and shared interfaces | User wants parallel work; ownership avoids merge conflicts | dummyanaxes |
| 10:12 | LLM = Gemini on Vertex AI via ADC; repo = divyatejamsai/context-con | User choice | dummyanaxes |
| 10:05 | Stack: Python/FastAPI agent + Next.js UI, SSE streaming, cache/replay mode | 2-person split, UI needed for hiring demo, replay protects demo | dummyanaxes + Claude |
| 09:57 | **Theme = Hiring** (confirmed) | User picked it from the recommendation | dummyanaxes |
| 09:55 | Recommend Hiring theme, Revenue as fallback | Best Crustdata fit + lowest risk + verification criterion built in (see section 2) | Claude (pending user OK) |

## 4. Progress log
| Time (IST) | What happened |
|---|---|
| ~10:47 | WS2 merged: the orchestrator maps simple filters to Crustdata syntax in `to_crustdata_filters()`: title `(.)` on `experience.employment_details.current.title`, city `(.)` on `basic_profile.location.city` with spelling variants OR-ed (bangalore\|bengaluru), country `=` on `basic_profile.location.country`, skills `(.)` on `skills.professional_network_skills`. **City and skills field names are unverified until the first live run.** One `person_enrich_many` call per run (15 req/min limit). `CRUSTDATA_MODE` default = cache |
| ~10:46 | WS5: root README now has "How to run" (section 8 lives there). Seeded fakes are generated on the Mac from cached Person Enrich and never committed, because they contain real people's data. check_fakes still passes against main (5 fakes, 0 misses, 0 false positives). Open: WS4 `frontend/.env.example` is missing although its README references it |
| ~10:44 | **All 6 branches merged into `main`** (ws/crustdata, ws/pipeline, ws/verify, ws/ui, ws/demo). Clean merges, 30 backend tests pass in replay and dev modes. Every workstream should now rebase on `main`. Cloud pushes work again |
| ~10:42 | WS3 fixed 2 real-data bugs: stage now comes from the latest priced round in `funding.milestones` (Razorpay's `last_round_type` is `secondary_market`), and `year_founded` is an int year, not an epoch. `web_search` links are opaque `google.com/goto?url=` tokens, so the verifier prefers direct URLs |
| ~10:37 | Merged `ws/crustdata` into `integrate`: 26 backend tests pass in both dev and replay modes |
| ~10:34 | WS1: Crustdata client live-tested on the Mac, all 8 endpoints OK, pushed `ws/crustdata` (6c4c0e8) |
| ~10:35 | Repo made public. All workstreams combined on local branch `integrate` (commit 024338c, 16 backend tests pass in mock/dev). Push from the cloud is refused until the Claude GitHub App gets access to `context-con`. **Public repo: never commit keys, `.env`, or GCP project details** |
| ~10:33 | WS4: UI done, replay + live modes, works against WS2 backend in mock/dev |
| 10:47 | WS5: seeded fakes now emit `<slug>.person.json` (real enrich record + `claimed`). `check_fakes.py` caught 8/8 planted lies with 0 false positives (offline, on WS3 dev data). Waiting on real Person Enrich fixtures from WS1 |
| 10:46 | Crustdata allowed in the cloud environment; GitHub linked, but the Claude GitHub App can't see private repo `context-con` yet, so the user is adding it under repository access |
| 10:43 | WS3: verifier + ranker done, integrated with WS2 pipeline on dev data (16/16 tests) |
| 10:40 | WS2: `/api/run` SSE end to end in mock mode (9 tests pass); fallback verifier in place |
| 10:34 | Pushed CONTEXT.md workstreams update: commit de76200 on main |
| 10:35 | WS2 finished schemas.py, llm.py and run.jsonl. WS5 finished briefs, seeded-fakes generator, script v1 and run steps. Neither is pushed yet (cloud threads have no GitHub access) |
| 10:27 | First push to GitHub: commit 18c9e38 on main (CONTEXT.md, README, .gitignore, .env.example). `.env` with Crustdata key created on Sai's Mac (gitignored, chmod 600). TODO: set GOOGLE_CLOUD_PROJECT in .env |
| 10:25 | Workstreams defined (section 7a). Found: Crustdata blocked from cloud sandboxes, so live calls run on Sai's Mac |
| 10:18 | Crustdata API key + MCP URL received; key kept in local `.env` only. Repo cloned, first push of docs |
| 10:12 | LLM and repo decided. Blocker: GitHub account not linked to Claude yet |
| 10:05 | Team (2), stack, architecture, API contract and build plan added. Blocker: LLM key |
| 09:57 | Theme locked: Hiring. Next: team size, tech stack, build plan |
| 09:55 | Read themes + problem statement, wrote theme analysis, created this doc |

## 5. Team, stack and open questions

**Team:** 2 people. Called **A (agent/backend)** and **B (UI/demo)** below.

**Stack (decided 10:05 IST)**
| Layer | Choice | Why |
|---|---|---|
| Agent backend | **Python 3.11 + FastAPI**, `httpx` for Crustdata, `pydantic` models | Best for LLM + data wrangling; FastAPI streams agent steps easily |
| Live updates | **Server-Sent Events (SSE)** from `/api/run` | Judges watch the agent think in real time; simpler than websockets |
| Frontend | **Next.js (React) + Tailwind + shadcn/ui** | Fast to make it look polished; B can build against fixture JSON before the backend exists |
| LLM | **Gemini on Vertex AI**, auth via **ADC** (Application Default Credentials). Python `google-genai` SDK with `vertexai=True`, project + region from env. Use a Flash model for parsing/drafts (fast) and a Pro model for verify/rank (accuracy); exact model IDs to confirm from the Vertex console | Brief parsing, title synonyms, claim judging, ranking reasons, outreach drafts |
| Data | Crustdata API (mandatory), all responses cached to `cache/*.json` | Saves credits in dev; **replay mode** keeps the demo working if the API or wifi dies |

**Open questions**
1. ~~LLM key~~ Resolved 10:12: Gemini via Vertex ADC. Each dev machine runs the ADC setup (`bash <(curl -sSL https://storage.googleapis.com/cloud-samples-data/adc/setup_adc.sh)`, or `gcloud auth application-default login`), then sets `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` in `.env`.
2. Crustdata API key, rate limits and credit cost per call (from the 10:00 walkthrough).
3. ~~Repo URL~~ https://github.com/divyatejamsai/context-con (private, branch `main`). Local clone on Sai's Mac: `~/context-con`. Claude pushes via a session on that Mac using Sai's git login.

## 6. Architecture

```
[Next.js UI] --POST brief--> [FastAPI /api/run]  --SSE events--> [UI live feed + shortlist]
                                    |
          1 parse_brief (LLM)  -> criteria + title synonyms + location/seniority
          2 search     (Crustdata Person Search, several query variants; auto-broaden if 0 results)
          3 enrich     (Person Enrich + Company Enrich, parallel, cached)
          4 verify     (per claim: Verified / Contradicted / Unverifiable, each with source)
          5 rank       (LLM score vs criteria; every reason must cite a claim id)
          6 outreach   (LLM draft, NEVER sent: event rule)
```

**Rule for every claim shown in the UI:** it must carry `source` (endpoint + field, or URL). No source = shown as Unverifiable, never invented.

### API contract (A and B both build to this, agree on it at 10:30)
`POST /api/run` body `{ "brief": "free text" }` -> SSE stream of events:
```json
{"type":"step","step":"search","message":"Searching 3 title variants in Bangalore...","ts":"..."}
{"type":"candidate","candidate":{
  "id":"c1","name":"...","title":"...","company":"...","location":"...","profile_url":"...",
  "score":82,
  "reasons":[{"text":"5 yrs payments at Razorpay","claim_ids":["k1"]}],
  "claims":[{"id":"k1","claim":"Works at Razorpay since 2021","status":"verified",
             "evidence":"employer + start_date from Person Enrich","source":{"endpoint":"person/enrich","field":"current_employers[0]","url":null}}],
  "flags":["Changed jobs 3 weeks ago"],
  "outreach_draft":"Hi ..."}}
{"type":"error","step":"enrich","message":"Timeout for 2 profiles, marked unverifiable"}
{"type":"done","summary":{"searched":120,"enriched":25,"shortlisted":8}}
```
B starts with a `fixtures/run.jsonl` of these events so the UI is never blocked on the backend.

## 7a. Parallel workstreams (decided 10:25 IST)

The build runs as **5 workstreams at once**. Each one owns its own folders, so nobody edits anyone else's files. All of them code against the contracts in this section and in section 6. **CONTEXT.md and repo setup are owned by the "Plan the Hiring agent build" thread.** Every other workstream reports its decisions there so they get logged here.

### Environment facts every workstream must know
- **Crustdata (`api.crustdata.com`) is blocked from Claude's cloud sandboxes** by the network policy. Real Crustdata calls run on Sai's Mac (or after the project's cloud environment allows that domain). Until then, cloud workstreams code against **fixtures** (saved real responses).
- **Gemini / Vertex ADC credentials exist only on the team's laptops.** Cloud workstreams must make every LLM call go through `backend/app/llm.py`, which supports `LLM_MODE=mock` (returns canned JSON) so code can be tested without credentials.
- Secrets live only in `.env` (gitignored). Never commit keys.
- Branches: each workstream works on `ws/<name>` and merges to `main` at the checkpoints (12:30, 13:30, 14:15).

### Repo layout and ownership
```
backend/
  app/
    main.py, orchestrator.py, brief.py, outreach.py, schemas.py, llm.py   -> WS2 Pipeline & API
    crustdata/client.py, crustdata/cache.py                               -> WS1 Crustdata
    verify/verifier.py, verify/ranker.py                                  -> WS3 Verifier
  scripts/smoke_crustdata.py                                              -> WS1
  tests/                                                                  -> each WS owns tests for its folder
  pyproject.toml / requirements.txt                                       -> WS2 (others ask WS2 to add deps)
fixtures/
  crustdata/*.json     (real sample responses)                            -> WS1
  run.jsonl            (sample SSE event stream for the UI)               -> WS2 (first version from section 6 contract)
frontend/                                                                 -> WS4 UI
demo/  (briefs.md, script.md, seeded_fakes/)                              -> WS5 Demo & QA
```

### Shared interfaces (code against these, do not change them without telling the doc owner)

**Crustdata client (WS1 provides, WS2/WS3 consume)**
```python
class CrustdataError(Exception): ...

class CrustdataClient:          # backend/app/crustdata/client.py
    def __init__(self, api_key: str | None = None, mode: str = "live"):  # mode: live | cache | replay
    async def person_search(self, filters: dict, limit: int = 25) -> list[dict]
    async def person_enrich(self, profile_url: str) -> dict | None
    async def company_search(self, filters: dict, limit: int = 25) -> list[dict]
    async def company_identify(self, name: str | None = None, domain: str | None = None) -> dict | None
    async def company_enrich(self, company_id: str | None = None, domain: str | None = None) -> dict | None
    async def job_search(self, filters: dict, limit: int = 25) -> list[dict]
    async def web_search(self, query: str) -> list[dict]
    async def web_fetch(self, url: str) -> dict | None
```
- Every returned dict carries `"_source": {"endpoint": "person/enrich", "request_hash": "...", "fetched_at": "ISO"}` so claims can cite it.
- Retries with backoff on 429/5xx, timeout 20s, raises `CrustdataError` only after retries. `None` / `[]` means "not found", never an exception.
- `mode=replay` serves only from `cache/` + `fixtures/crustdata/` (demo safety). `mode=cache` = live but reads/writes cache.

**LLM wrapper (WS2 provides, WS3 consumes)**
```python
# backend/app/llm.py
async def generate_json(prompt: str, schema: type[BaseModel], tier: Literal["fast","smart"] = "fast") -> BaseModel
async def generate_text(prompt: str, tier: Literal["fast","smart"] = "fast") -> str
# fast = Gemini Flash, smart = Gemini Pro, via google-genai with vertexai=True. LLM_MODE=mock returns schema-valid stub data.
```

**Core types (WS2 owns `backend/app/schemas.py`, mirrors the SSE contract in section 6)**
```python
class Criteria(BaseModel):
    role: str; title_variants: list[str]; seniority: str | None; skills: list[str]
    locations: list[str]; company_preferences: list[str]; must_haves: list[str]; nice_to_haves: list[str]; raw_brief: str
class Source(BaseModel):  endpoint: str; field: str | None = None; url: str | None = None
class Claim(BaseModel):   id: str; claim: str; status: Literal["verified","contradicted","unverifiable"]; evidence: str; source: Source
class Reason(BaseModel):  text: str; claim_ids: list[str]
class Candidate(BaseModel):
    id: str; name: str; title: str | None; company: str | None; location: str | None; profile_url: str | None
    score: int; reasons: list[Reason]; claims: list[Claim]; flags: list[str]; outreach_draft: str | None
```

**Verifier (WS3 provides, WS2 calls)**
```python
# backend/app/verify/verifier.py
async def verify_candidate(person: dict, company: dict | None, criteria: Criteria, client: CrustdataClient) -> tuple[list[Claim], list[str]]  # (claims, flags)
# backend/app/verify/ranker.py
async def rank_candidate(person: dict, claims: list[Claim], criteria: Criteria) -> tuple[int, list[Reason]]  # every Reason cites claim ids
```

### Contract additions (logged 10:35 IST, all backward compatible)
- **Env vars (all workstreams use these names):** `CRUSTDATA_MODE` = `live | cache | replay` (default `cache`), `LLM_MODE` = `live | mock`, `GEMINI_FAST_MODEL` (default `gemini-2.5-flash`), `GEMINI_SMART_MODEL` (default `gemini-2.5-pro`). Python deps go in `backend/requirements.txt` (owned by WS2).
- **WS2:** event models `StepEvent / CandidateEvent / ErrorEvent / DoneEvent` live in `schemas.py`. `StepEvent` has optional `data` (the parse step sends `{"criteria": {...}}`). All `Criteria` / `Candidate` fields have defaults. `llm.py` also exports `LLMError` and `is_mock()`.
- **WS2 to WS1 (10:40):** the orchestrator calls `CrustdataClient(api_key=..., mode=CRUSTDATA_MODE)` and passes `person_search` filters as `{"titles": [one title], "locations": [...], "skills": [...], "seniority": str | None}`, one call per title variant, in parallel. WS1 maps that to the real API filter syntax.
- **WS2 to WS3 (10:40):** if `verify/` is missing or throws, `app/fallbacks.py` runs a basic verifier/ranker instead. The orchestrator namespaces claim ids per candidate (`k1` -> `c3-k1`), and reasons that cite unknown claim ids are dropped.
- **WS2 to WS4 (10:40):** extra endpoints `GET /api/run?brief=...` (for EventSource) and `GET /api/replay?delay=0.6` (streams `fixtures/run.jsonl`). The final step event `{"step":"rank","data":{"order":[ids]}}` gives the shortlist order.
- **`CRUSTDATA_MODE=dev`** = synthetic people, used automatically if `app/crustdata/` isn't present.
- **WS3 verifier (10:43):** self-reported facts come from `person["claimed"]` (keys: `employer, title, start_date, tenure_years, years_experience, location, company_stage, skills`); otherwise they come from the profile headline. **WS5 seeded fakes must use the `claimed` key.** Facts are checked against Person Enrich employment and Company Enrich, and the employer falls back to `web_search` when the graph has nothing. `verify_candidate` takes an optional `today=` kwarg for tests. It never raises: each Crustdata call has an 8s timeout, and a failed call means that claim is unverifiable. Flags: job change in the last 120 days, recent exit, stale headline, concurrent roles, each contradiction.
- **WS3 ranker (10:43):** deterministic weights: role 30, skills 25, location 15, company pref 15, experience 15, rescaled to only the factors the brief mentions. Each contradiction costs -12 points, a stale headline -6. `RANK_USE_LLM=1` rewrites the reason text with Gemini and keeps the claim ids.
- **WS5 to WS2/WS3 (stretch):** `POST /api/verify_resume` with body `{name, profile_url, claims:[{id, claim}]}` returns `list[Claim]` (same Claim type). Powers the "seeded fakes" demo.
- **WS5 to WS1:** save 3-5 Person Enrich fixtures as `fixtures/crustdata/person_enrich_*.json` plus `fixtures/crustdata/companies.json` (map of company_id to Company Enrich response). These are used to build the final seeded-fake resumes.

### Real Crustdata facts (from WS1's live smoke test on Sai's Mac, ~10:34 IST)
- All 8 endpoints returned OK live. Client is on branch `ws/crustdata` (6c4c0e8).
- **Person Enrich is rate-limited to 15 requests/min.** Use `person_enrich_many(urls)`, which batches 25 per call.
- Enrich and identify return the record itself, plus `_match` and `_source`.
- Field paths:
  - person: `basic_profile.{name, headline, current_title, location.city/country}`
  - jobs: `experience.employment_details.{current,past}[].{title, name, crustdata_company_id, start_date, end_date, seniority_level}`
  - LinkedIn URL: `social_handles.professional_network_identifier.profile_url`
  - skills: `skills.professional_network_skills[]`
  - company stage: `funding.{last_round_type, total_investment_usd}`. Size: `headcount.total`
- Gotchas: `web_search` URLs are Google redirect links (unwrap before citing), and `web_fetch` content is raw HTML.
- Person-level fixtures are **not committed**, because the repo is public. That's the user's decision, pending.
- **Demo-safety risk:** replay mode can't produce candidates from the repo alone, because person data isn't committed. For a reliable demo, run each demo brief live once on the Mac (in `cache` mode) so `cache/` fills locally, then record in `replay` mode.

### Branches (all on GitHub, merged to `main` at ~10:44 IST)
`ws/crustdata` (WS1), `ws/pipeline` (WS2), `ws/verify` (WS3), `ws/ui` (WS4), `ws/demo` (WS5). Keep working on your `ws/*` branch, rebased on `main`, and merge again at each checkpoint.

### The workstreams

| WS | Name | Owns | First deliverable (by) | Depends on |
|---|---|---|---|---|
| WS1 | Crustdata client + cache/replay | `backend/app/crustdata/`, `backend/scripts/`, `fixtures/crustdata/` | Smoke test run **on Sai's Mac**, real responses saved as fixtures (10:50) | API key in `.env` |
| WS2 | Pipeline + API | `backend/app/` (except crustdata/, verify/), `fixtures/run.jsonl` | `llm.py` + `schemas.py` + `run.jsonl` committed (10:50); `/api/run` SSE end-to-end with real data (12:30) | WS1 fixtures, WS3 for verify step |
| WS3 | Verifier + ranker | `backend/app/verify/` | Claim extraction + checks on fixture people (12:00); ranker (13:00) | WS1 fixtures, WS2 `schemas.py`/`llm.py` |
| WS4 | Web UI | `frontend/` | UI fully working on `fixtures/run.jsonl` (12:30); wired to live backend (14:00) | `run.jsonl` (can write its own from section 6 until WS2's lands) |
| WS5 | Demo & QA | `demo/`, README "How to run" | 5 messy test briefs + edge cases (11:15); seeded-fake resumes (13:00); demo script (14:00); record video (15:15) | everything, for the final run |

Humans: **Sai** runs anything that needs the Mac (Crustdata live calls, Vertex, running the app, recording). The second teammate can pair on WS4 UI or WS5 demo.

## 7. Build plan (IST)

| Time | A (agent/backend) | B (UI/demo) | Checkpoint |
|---|---|---|---|
| 10:30-11:00 | Repo + FastAPI skeleton. **Smoke-test every Crustdata endpoint**, save real responses into `cache/` | Next.js + Tailwind + shadcn skeleton, write `fixtures/run.jsonl` from contract | Contract agreed, real sample data saved |
| 11:00-12:30 | `parse_brief` -> `search` -> `enrich` streaming over SSE | Brief input page, live step feed, shortlist cards (from fixtures) | **12:30: a real brief returns real candidates end to end (no verify yet)** |
| 12:30-13:30 | `verify` + `rank` with cited reasons | Candidate drawer: claims with Verified/Contradicted/Unverifiable badges + source links, outreach draft | 13:30 mentor checkpoint: show it |
| 13:30-14:15 | Robustness: typo'd/vague brief, 0 results -> broaden, API errors -> retry then mark unverifiable, replay mode | Wire UI to live backend, error/empty states, polish | **14:15: full flow works live** |
| 14:15-14:45 | Stretch (only if green): "seeded fakes", i.e. upload resumes with planted false claims, verifier flags them | Stretch UI for resume upload | Hard stop on new features at 14:45 |
| 14:45-15:15 | Fix bugs, README, prime cache for demo briefs | Write demo script, **record 2-min video** | Video recorded by 15:15 |
| 15:15-15:30 | Push repo, submit | Submit video | **15:30 code freeze** |

**Cut order if behind:** stretch goal -> outreach drafts -> ranking polish. Never cut: verify + citations (it's the judging criterion).

## 8. How to run
See the root `README.md` "How to run" section (kept there so it stays next to the code).

## 9. Demo script (2 minutes)
Draft beats: (1) 10s problem: recruiters are paid on hires, and profiles are stale. (2) Paste a messy brief judges haven't seen. (3) Live feed shows the agent searching title variants. (4) Shortlist appears; open one candidate and show every claim cited, plus a "changed jobs 3 weeks ago" catch. (5) Show a contradicted claim being flagged. (6) 10s close: no human in the loop, every claim sourced.
