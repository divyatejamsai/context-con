# Project Context: ContextCon 03 (IIT Bombay) x Crustdata Hackathon

> Living handover doc. Anyone (human or AI agent) picking this up should be able to continue from here alone.
> Update it every time a decision is made or a milestone is hit. Newest entries go at the top of each log.

Last updated: 2026-10-31 ~10:18 IST

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
| 10:12 | LLM = Gemini on Vertex AI via ADC; repo = divyatejamsai/context-con | User choice | dummyanaxes |
| 10:05 | Stack: Python/FastAPI agent + Next.js UI, SSE streaming, cache/replay mode | 2-person split, UI needed for hiring demo, replay protects demo | dummyanaxes + Claude |
| 09:57 | **Theme = Hiring** (confirmed) | User picked it from the recommendation | dummyanaxes |
| 09:55 | Recommend Hiring theme, Revenue as fallback | Best Crustdata fit + lowest risk + verification criterion built in (see section 2) | Claude (pending user OK) |

## 4. Progress log
| Time (IST) | What happened |
|---|---|
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
_(Fill in once building starts.)_

## 9. Demo script (2 minutes)
Draft beats: (1) 10s problem: recruiters are paid on hires, and profiles are stale. (2) Paste a messy brief judges haven't seen. (3) Live feed shows the agent searching title variants. (4) Shortlist appears; open one candidate and show every claim cited, plus a "changed jobs 3 weeks ago" catch. (5) Show a contradicted claim being flagged. (6) 10s close: no human in the loop, every claim sourced.
