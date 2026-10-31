# Project Context: ContextCon 03 (IIT Bombay) x Crustdata Hackathon

> Living handover doc. Anyone (human or AI agent) picking this up should be able to continue from here alone.
> Update it every time a decision is made or a milestone is hit. Newest entries go at the top of each log.

Last updated: 2026-10-31 ~10:35 IST (wall clock; earlier timestamps in this doc ran ahead and are approximate)

> **NAME:** the agent-infra product is **Agaxes** ("agent access"). Older entries call it "Countersign".

> **STANDING RULE (user, ~11:42 IST): this must be a real product, not a faked demo.** Agent management, tests and the demo all run on real data: live Crustdata, live Gemini, real signatures and real ledger entries. Mocks and fixtures are only for offline unit tests and as a fallback, never for what judges see. A gap audit ("Audit gaps for a real product" thread) is running.

---

## 1. The event in one screen

- **What:** ContextCon IIT Bombay, "The Agentic Services Hackathon" (Techfest 2026-27, YC event, sponsored by Crustdata).
- **Goal set by organisers:** build an autonomous agent that does a professional service (normally done by a firm of people) end to end, with no human in the loop, on data about people and companies.
- **Hard requirements**
  - Must build on **Crustdata's API / identity graph** (people + company data). Using their keys is mandatory.
  - Deliverables by **3:30 PM IST**: a working code repo **and a 2-minute screen-recorded demo video** showing the product take a request it has never seen all the way to finished work.
  - Can be a single agent, a multi-agent system, an MCP server, or a CLI.
  - **Agents must not contact real people** during the event. Only the local environment and authorised APIs. (So: real sends run in test mode and land in our own inbox; see docs/OUTBOUND.md.)
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
- **Update ~11:25 IST:** Hiring continues in full, **and** all four agent-infra ideas (Passport, Send Guard, AI employee manager, ledger) are built alongside it. No pivot, no go/no-go switch. (An earlier ~11:23 note said:) the user chose to also build **Countersign** (Infrastructure for agents: AI employee manager + signed agent passports verified via Crustdata + hash-chained ledger), with the hiring agent "Sourced" as its first AI employee and as the fallback submission. Go/no-go at 14:00 IST. See the decision log.
- **Recommendation:** Hiring (runner-up: Revenue).
- **Decision:** ✅ **Hiring** chosen by user at 09:57 IST. Revenue stays the fallback if Hiring stalls in the first hour.

---

## 3. Decision log
| Time (IST) | Decision | Why | By |
|---|---|---|---|
| ~12:55 | **Sourced sends real email.** Addresses come only from Crustdata Person Enrich `fields:["contact"]` (never guessed); sends go through Send Guard, then Resend or SMTP (Gmail). **Every email goes to `OUTBOUND_TEST_TO` (our own inbox); there is no live mode** (user, ~13:07: "we don't wanna be sending mails to real people") | User: "we want the system to send emails... search for their email too"; event rule | dummyanaxes (thread: Make Sourced actually reach candidates) |
| ~12:36 | **Company accounts: real sign-up, login and sessions** gate `/` and `/console`. Two-step self-serve sign-up (work email, then Crustdata-prefilled company), same-domain users join one workspace, one-click demo workspace for judges | User asked for a company login page with the required details, informed by real ATS products and their reviews (G2/Capterra: Greenhouse/Lever are sales-gated with no trial, Greenhouse and Ashby reviews cite setup complexity and learning curve, Workable wins on ease of setup) | dummyanaxes |
| ~13:20 | **All open PRs merged into main (28f6266)** at the user's request ("merge all the updates"): #24 (Agaxes console redesign, UI rename, campaigns and shift-staffing pages; includes #16 UI guide and #15 guided demo), #22 (Agaxes agent runtime: tasks, approvals, pauses, budgets, Work view), #18 (brief to signed offer, 1,000-shift staffing with seeded fakes), #21 (real emails found through Crustdata person/enrich `contact`, sent through Send Guard to a test inbox only, reply tracking), #17 (backtest on 2025 real openings). Earlier: #19 login/sign-up, #20 sign-up buttons, #23 forgot password. 442 backend tests pass, and tsc and build pass. Resolved conflicts: main.py routers (kept all of them) and CONTEXT.md (kept main's). The Mac shows Agaxes branding everywhere. Note: `/person/contact/enrich` is 403 on this key, so emails come from `/person/enrich` fields ["contact"] (personal emails with status "deliverable") |
| ~12:55 | **Countersign renamed to Agaxes ("agent access").** Docs, README, CLI and script output and code comments now say Agaxes. Code identifiers, routes, file and dir names (`docs/COUNTERSIGN.md`, `fixtures/countersign/`, `CountersignMCP`, `COUNTERSIGN_ADMIN_TOKEN`, MCP server name `countersign`) are unchanged for now. Older log rows still say Countersign and mean the same thing | User: "this will be used by companies, name it agaxes (like agent access)" | dummyanaxes |
| ~12:25 | **Video story: "Sourced, run by Countersign".** The hiring agent runs as a governed AI employee: passport check, then cited shortlist, then Send Guard on drafts, then the ledger. The hiring-only close is dropped | User's pick on the story decision card | dummyanaxes |
| ~11:42 | **Standing rule: real product, not a faked demo.** Agent management, tests and demo run on real data (live Crustdata + Gemini). Mocks only for offline unit tests and as a fallback | User: "i want the final product to actually be a product and not just a faked demo" | dummyanaxes |
| ~11:37 | **Standing approval: push fixtures/recordings whenever** (incl. real-person data to the public repo); no need to ask again | User: "you can push whenever man" | dummyanaxes |
| ~11:41 | UI look changed again: Sourced dark theme replaced by neo-brutalist bento | User wanted it more creative; the earlier look read as default GitHub | dummyanaxes (via WS4) |
| ~11:31 | Thin shortlists: show 30-39 scorers as "near misses" instead of lowering the 40 bar | Keeps the bar honest while still showing options | WS2 |
| ~11:25 | **Correction: no pivot.** Build **all four agent-infra ideas (1 Agent Passport, 2 Send Guard, 3 AI employee manager, 4 hash-chained ledger) in parallel with Hiring.** Sourced/Hiring work continues in full. There is no go/no-go switch | User: "I wanna do 1,2,3,4 and still keep the hiring too and not pivot it" | dummyanaxes |
| ~11:23 | ~~Superseded by the row above~~ Build "Countersign" (working name)** under *Infrastructure for agents*, combining options 1, 3 and 4. It's an AI employee manager: onboard agents under a human sponsor with a role and scopes. Each agent gets a signed **passport** (Ed25519), verified live via Crustdata: the sponsor is real and still employed, the domain matches via Company Identify, and their title can grant the scope. **The agent is auto-suspended if the sponsor leaves.** A hash-chained, tamper-evident action ledger records actions with citations. Sourced (hiring agent) is the first "AI employee" and stays **untouched as the fallback submission**. Send Guard (option 2) is not a headline. Go/no-go 14:00 IST | User chose "A and C, and D" | dummyanaxes |
| ~11:16 | Pivot options proposed (see the row above for the decision): explore an agent-era infra pivot under the "Infrastructure for agents" theme. Options: (1) Agent Passport, a signed credential for an agent acting for a human, verified live via Crustdata (principal real, still employed, domain matches company, title carries authority); (2) Send Guard, an MCP pre-send check reusing the verifier to block false or stale claims; (3) AI employee manager (weak Crustdata fit, high risk); (4) hash-chained provenance log. Recommended by the "Rethink the hackathon idea" thread: **"Countersign" = 1+2 with 4 built in**, as an MCP server + verify page, with the hiring agent ("Sourced") as its first client and kept untouched as the fallback submission. Go/no-go 14:00 IST | User wants to think beyond the hiring agent | pending |
| ~11:13 | UI look changed from Dossier to "Sourced" | User found Dossier too generic | dummyanaxes (via WS4) |
| ~11:13 | Use the already-billed GCP project for Vertex instead of linking billing to the original one | User asked to fix Gemini now; avoids touching billing accounts | Claude (under the user's "fix gemini" ask) |
| ~11:00 | Keep repo public and merge real person fixtures into main (chosen over making the repo private) | Replay mode and demo work from the repo alone | dummyanaxes |
| ~10:46 | Commit real person fixtures to the public repo | Makes replay mode and the demo work from the repo alone | dummyanaxes |
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
| ~12:55 | **Real outbound (branch `claude/project-thread-cgbiwl`).** Hirer audit in `docs/SOURCED_AUDIT.md`: the shortlist works, but "verified" overstated what was proven, drafts had no address, sign-off or company, and nothing was ever sent or tracked. Live probe (Mac): `/person/enrich` with fields `["contact"]` returns `contact.personal_emails`/`business_emails` with `status: deliverable`; `/person/contact/enrich` returns 403 on our plan. New `backend/app/outbound/` (contacts, mailer, send.guarded_send, messages, tracking), `POST /api/agents/{id}/email`, `/api/messages(+/refresh)`, `/api/outbound/config`, run `?autosend=true`. UI: email per candidate, subject, Send, Sent/Delivered/Replied with reply text, "Email the shortlist for me" toggle, plain-English "How Sourced checks a claim". Setup in `docs/OUTBOUND.md`. 371 tests pass, next build clean, clicked through against a local SMTP server |
| ~13:05 | **Forgot password built** on the outreach thread's `send_transactional` (PR #21): `/forgot` sends a one-time 30-min link (3/hour, same answer for unknown emails), `/reset` sets the password, clears lockout and signs out every session. Without a provider the API returns 503 "email isn't set up". Also PR #20: visible Sign up buttons and "Create a new workspace" in the account menu |
| ~12:55 | **Company accounts built** (`backend/app/accounts/`, `frontend/src/app/{login,signup}`, `src/middleware.ts`, `components/account-menu.tsx`). SQLite + scrypt + hashed session tokens, lockout after 5 wrong passwords, free-mail domains refused, Crustdata Company Identify prefill marked `verified_via=crustdata`. 9 new tests, 365 backend tests pass, tsc/lint/build pass, browser walkthrough (redirects, sign-up, join, logout, bad password, demo) passes. FastAPI run endpoints stay open on purpose (scripts/MCP/fleet) |
| ~12:40 | **Replay backup fixed (e16c526):** 28 fixtures for the demo brief (8 person_search, 4 person_enrich, 4 company_enrich, plus 12 records in fixtures/countersign/people/). `CRUSTDATA_MODE=replay LLM_MODE=mock` now gives passport valid, a shortlist of 10 (top 90) and 5/5 guard cleared, the same on both runs. **Send Guard fixes merged (09eeec2):** O(1) ledger appends, skill/domain claims checked with verifier evidence, past-tense roles allowed. **demo_up.sh live on the Mac:** fleet scorecard PASS with 6 agents (Closer suspended) and a 57-entry ledger whose chain is intact; demo brief live in 13s. Known: test_sourced_sends_through_mcp fails on the Mac because it picks up the .env (passes in the cloud), so the Send Guard thread is pinning it |
| ~12:30 | **Live Send Guard findings (Mac).** (1) `guard_eval --live 120` stalled after enriching 120 people. `ledger.append()` re-reads the whole file on every append, which is O(n²); it was killed after 27 min and no report was written. (2) `sourced_agent` ran end to end in 41s, but Send Guard **blocked 8 of 10 drafts, mostly falsely**: it can't verify skill/domain claims ("experience with Payments") and flags past-tense past employers as stale. Both were sent to the Send Guard thread to fix; the Mac reruns once they're merged. Side effect: that run wrote 18 verdicts to the real `backend/data/ledger.jsonl` |
| ~12:26 | Merged **PR #13** (guided fleet demo, `backend/app/fleet/{api,demo}.py`). 354 tests pass, and tsc and build pass |
| ~12:24 | Merged **PR #11** (round-2 audit, `backend/scripts/demo_up.sh` one-command bring-up; 84741ea) and **PR #12** (ws/demo). `demo/script.md` v2 is a 1:55 live run: console roster, then Sourced passport check, then cited shortlist, then Send Guard clearing one draft and blocking a false "5 yrs at Fam" (he joined 2025-05), then payroll suspends Closer, then the ledger tamper is detected. It includes a pre-recording checklist, cut order, fallbacks, and a hiring-only close. README covers Countersign + Sourced, the 6-agent fleet, and the MCP/passport commands. 352 tests pass. **Mac is live now:** http://localhost:3000 and /console (Live badge, ledger intact), with health showing llm live and Crustdata key present. Queued: demo_up.sh with the fleet, one demo-brief run whose cache is committed as replay fixtures (replay currently finds 0 candidates), then the remaining checks |
| ~12:17 | Merged **PR #9 (console)** and **PR #10 (agent fleet, docs/FLEET.md, `scripts/run_fleet.py`)** into main. The user asked to push toward completion. 351 backend tests pass, and tsc and build pass |
| ~12:15 | **Passport hardening merged (9d978c2).** 7 rounds of live eval on the Mac: 539 real sponsors found through Person Search, 6,181 cases, and a red team of about 300 titles. The last round scored 735/735, 1833/1835 and 3609/3611, with 0 missed blocks. The only failures left are 'CFO (Designate)', which policy blocks because the person isn't in the role yet. Fixed along the way: CEO matching CTO or CFO, 'COO and Account Executive' passing as CEO, executive assistants to a CFO, 'CFO Recruiter', 'Freelance CFO' and 'CEO-elect'. contract.sign and payment.send need a clean authority title from an allowlist. Known limit: 'Analyst & Founder' is trusted as written; the fix is sponsor co-signing, which isn't built. An admin token on issue and revoke is opt-in via `COUNTERSIGN_ADMIN_TOKEN`. Red-team regression tests are in tests/test_countersign_redteam.py. The new dep is `cryptography` |
| ~12:05 | Mac: onboarded Sourced live as agent `agt_13e79e1cbd1d` (9/9 passport checks), with NEXT_PUBLIC_AGENT_ID set in frontend/.env.local and the frontend built. The guard eval (--live 120) is running |
| ~12:00 | Merged PR #7 (ws/ui-clean, aa779b6). The UI now defaults to **Live**, routes runs through `/api/agents/{NEXT_PUBLIC_AGENT_ID}/run` when that's set, and shows the passport and Send Guard steps with a cleared/blocked badge per candidate. Replay stays as a labelled fallback. Run `npm ci` after pulling, since the new `geist` font dependency is needed. tsc and build pass |
| ~11:58 | **Career context + review-informed scoring (ws/verify 2ad0c72, merged).** Two new verified claims per candidate: `Career:` (last 4 roles with company size, industry and years) and `Progression (rising/flat/falling)`, both citing experience.employment_details. New ranker factor **career fit** (weight 10): half the share of past years spent in similar roles, half the share at domain or preferred-type companies. A rising career gets +1.5 and a falling one is listed as a weakness. **Must-haves are now gates**: one with no evidence caps the score at 60, with a stated reason. Profiles older than 30 days are flagged as stale. Based on GoPerfect match scoring, TicNote's workflow, and G2/Gartner reviews of Juicebox and SeekOut (stale data, title-only matching, unstable ordering). WS2 to-do: sort the shortlist by (score desc, id). 125 tests pass; real-fixture scores run 25-76. Also merged earlier: PR #8 Send Guard, where the MCP tools take agent_id and signing is local (732b190) |
| ~11:51 | **Countersign merged to main (5050a79)** via the gap-audit branch `claude/project-thread-womuen` (PR #6), which brings in passport + ledger, Send Guard + MCP, and the AI-employee registry + console. Sourced now runs as an AI employee: `/api/agents/{id}/run` checks the passport live, signs every draft and runs it through Send Guard, and writes to the ledger. Also adds `/api/verify_resume` and `scripts/mcp_agent_demo.py`. 108 tests pass, frontend build passes. Gap list is in `docs/REAL_PRODUCT_GAPS.md`. Queued on the Mac: the guard eval (120 live), onboarding Sourced, one live agent run, MCP registered in Claude Code, and a redacted live scorecard |
| ~11:46 | Merged PR #5: bento UI given a professional finish (thinner borders, smaller shadows, no stickers/emoji, softer palette, sections "Why this candidate" / "Claims checked"). Frontend only, build passes |
| ~11:44 | Live recordings pushed: passport fixtures to `claude/project-thread-icv883` (9a7f3e0, 5 person_enrich + LIVE_CHECK.md), Send Guard fixtures to `claude/project-thread-gz8tzg` (66d5e70, 2 person_enrich + GUARD_LIVE_CHECK.md). Cloud threads can now replay them offline |
| ~11:43 | Countersign WS6 (Passport + ledger, `claude/project-thread-icv883` 547293c, not on main yet): beyond the 5 fixture scenarios, a real sponsor found via Person Search (Razorpay's Head of Talent Acquisition) got **allow** on `outreach.hiring` (7 live calls, 0 errors). Send Guard and the AI-employee console are being built on top of this branch |
| ~11:42 | **Send Guard (branch `claude/project-thread-gz8tzg`, 94e9eb1) verified live** (real Gemini claim extraction + Crustdata): 5/5 demo cases right. Clean outreach ALLOW. False tenure claim BLOCK. Recipient already left BLOCK. Sponsor left BLOCK. Body altered after signing BLOCK (signature invalid). 84 tests pass. **Live eval round 5 (1986396): 63/63, 36s**, near misses now shown (B2 4, B4 5). Passport and Guard live recordings are saved on the Mac, waiting on the user's OK to push (public repo, real people) |
| ~11:41 | Merged: **WS4 UI restyled as neo-brutalist bento** (PR #4, user asked for "more creative"): Bricolage Grotesque, ink borders, hard shadows, colour semantics (lime verified, coral contradicted, yellow selected, lavender citations). Shortlist, collapsed Near misses, greyed Below the bar. Export covers the shortlist only. Build passes. **WS2 7f9d78b:** domain-like employer names are identified by domain, and fuzzy identify results that don't match the employer are ignored (root cause of Tech Mahindra attached to nvme-z.tech) |
| ~11:39 | WS3 merged 3d96653, fixing eval-r4 items 1-5: negated preferences ("not big tech", "no startups") become weaknesses. Domain evidence is split into direct and inferred, with reduced credit for inferred-only. Company-preference reasons collapse to one per claim. Mismatched company records are rejected and refetched by the job's id. The years-in-role bonus counts only roles sharing the role's distinctive word and skips freelance/intern |
| ~11:38 | **Countersign passport (branch `claude/project-thread-icv883`, 547293c) verified live on the Mac:** 68/68 tests pass, and all 5 sponsor scenarios give the expected live verdict: authorised_founder allow; sponsor_left block (left employer 213 days ago); title_changed block (Co-Founder now Advisor, can't grant contract.sign); junior_sponsor block; spoofed_domain block (kiot-hr.com isn't kiot.io). Live recordings are saved locally, waiting on the user's OK to push them (real people's data, public repo) |
| ~11:36 | WS2 round 4 merged (c0f5f28): engineering title variants must contain the function word or an alias. Outreach is post-checked: a draft with no fact token falls back to the grounded template, and a missing question gets a CTA appended. Sign-off from `RECRUITER_NAME` env. Eval scorecard has a Near miss column. B4's "speaks Japanese" stays a hard constraint on purpose (should show Unverifiable). 60 tests pass |
| ~11:34 | **Live eval round 4 (c984c8b): 63/63, 49s.** A review of the sample output found 11 quality issues (wrong company record attached, "not big tech" check inverted, duplicate reasons, years-in-role bonus counting unrelated roles, generic or unsupported outreach lines). List in `/mnt/project-files/qa/live_eval_r4_review.md` (private, has real names), sent to WS2 and WS3. **Crustdata is blocked in cloud threads because the project has no cloud environment selected** (built-in default). The user needs to add one in Project settings with `api.crustdata.com` allowed. Meanwhile the Mac runs the passport/ledger branch live and records fixtures |
| ~11:31 | WS2 merged 08b8666: **near misses**. Candidates scoring 30-39 (`NEAR_MISS_MIN`) are flagged, and the final rank step's `data` now has `near_miss: [ids]` beside `order` and `shortlist` (backward compatible). The UI should show shortlist, then a collapsed "Near misses" section. 59 tests pass |
| ~11:30 | **Live eval round 3 (eb21764): 63/63, 64s total (was 161s), every brief under 13s**, 0 unexpected errors. Domain fit recovered (B2 9/10, B4 10/10, B1 7/10). Outreach now takes about 3s per draft (was 20s), and company lookups are batched. Remaining: thin shortlists on B2 (5) and B4 (2) |
| ~11:27 | WS2 round 3 merged (00f1b97): brief domain words skip hirer context ("our devtools co"). New `fit_terms()` (includes languages, word-boundary match) feeds prescore and the eval's domain fit; search `domain_terms` still excludes languages. Gemini Flash runs with `thinking_budget=0` (`GEMINI_FAST_THINKING_BUDGET`), outreach is capped at 12s. One batched Company Enrich call for all employers, misses capped at 6s, and a failed lookup isn't retried by the verifier. 58 tests pass |
| ~11:25 | **Live eval round 2 (dec0bbf): 63/63 checks**, 161s (was 319s). B1 variants all keep "backend". Top scores 45-94, verified 85-100%. Regressions: domain fit on B2 (1/10) and B4 (0/10). Outreach is now the bottleneck (up to 20s per draft). E3: 5/10 company enrich calls hit the 10s timeout. Sent to WS2 |
| ~11:22 | WS2 merged 0b62166: parse at temperature 0, deterministic domain terms unioned with the LLM's, `keep_function()` drops generic variants. **Speed fix:** company lookups are shared per company and capped at `COMPANY_TIMEOUT=10s` (uncapped retries were stalling candidates), outreach is capped at 20s, and concurrency is 10. `done.summary.timings_ms` reports the slowest candidate per stage. `Criteria.min_years` added. 56 tests pass |
| ~11:20 | **Live eval (real Crustdata + Gemini, main e38d511): 62/63 checks**, 319s total. B1 9/10 (payments domain term missing in one run: Gemini parse not stable), B2-B5 and E1-E3 all pass. Verified 88-100%, max 1 contradiction. Per-candidate stage is slow on B2, B4 and E3 (63-75s vs ~20s). B4 shortlisted only 1. Seniority fix confirmed (role "Senior Backend Engineer", variants all senior-level), and there's no duplicate payments must-have. Follow-ups sent to WS2: temperature 0 parse plus deterministic domain terms, keep the function word in variants, profile the slow stage, thin B4. `eval_live.md` contains real names, so never commit it |
| ~11:18 | WS3 merged 87c52a8, fixing QA items 7-10: a stage taken from headcount alone is labelled "(growth by size)", and startup preference needs a founding year within 12 years. Required years are parsed ("5+ yrs"), with short candidates capped and the gap named. Claimed stage is checked against job-level headcount for clear clashes. Employer-based domain evidence is worded "likely, from industry". 54 tests pass, and check_fakes passes with and without companies |
| ~11:16 | WS2 merged f27904c, fixing QA items 1-6: non-hiring text stops before any search, domain terms skip languages/tools and anything under 3 chars, ties broken by verified count, outreach hook taken from a verified fact. Items 7-10 belong to WS3. 51 tests pass |
| ~11:15 | QA pass (no Gemini): SSE, empty or failing search, failed batch enrich and missing company record all end cleanly with `done`. Every claim is sourced, and seeded fakes are 10/10 caught. 10 issues sent to WS2/WS3: non-hiring briefs still spend search credits, short skills like "go" fuzzy-match noise, the outreach fallback leaks scoring text, and "startup" is inferred from headcount alone. Report: `/mnt/project-files/qa/pipeline_review.md`. Crustdata is still refused from cloud sessions, so live runs stay on the Mac |
| ~11:14 | WS2 fixes merged (ea1a0b9): `enforce_seniority()` keeps the level on the role and every variant and drops lower ones. `normalise_terms()` strips filler from must-haves and drops duplicates of skills. Outreach uses verified facts only, puts the domain fact first, bans unsupported adjectives and signs "[Your name]". Also: non-hiring text stops cleanly, assumptions show in the feed, the ladder widens city to country, SHORTLIST_MIN=40, and done.summary gets `elapsed_ms` and `timings_ms`. **New eval harness:** `cd backend && python -m evals.run_evals --out ../eval_live.md` runs B1-B5 + E1-E3 (63/63 offline). 45 tests pass |
| ~11:13 | WS4 UI restyled as **"Sourced"** (PR #3, merged): dark-first, Linear-style surfaces, Inter and JetBrains Mono, tool-call cards per agent step, criteria chips with % fit. Same features and event contract as Dossier. tsc and build pass |
| ~11:12 | WS3 graded ranker merged (5df12a6): base capped at 90, plus bonuses up to +10 for years in role, current-role domain and stable tenure, each citing claim ids. Seniority gap scales role fit (1.0 / 0.6 / 0.35), and skill credit is graded by evidence source. Real-fixture scores now spread 81 down to 28 |
| ~11:11 | **Gemini works** (gemini-2.5-flash on the billed project; `.env` switched, old `.env` backed up locally). **Live run 3 (real Gemini + Crustdata)**: 26s, 0 errors, 132 profiles searched, 10 shortlisted. Scores 85,85,85,85,85,71,71,62,41,38. Claims: 68 verified, 10 unverifiable, 1 contradicted. Issues sent to WS2: parse_brief drops "Senior" from role and title variants (4 of 10 below senior), duplicates the domain as a "Payments experience" must-have (never matches, caps the score at 85), and outreach adds unsupported adjectives. gemini-2.5-pro is unused unless `RANK_USE_LLM=1` |
| ~11:13 | Gemini still blocked: billing was enabled on a different GCP project than the one in `.env`. Fix: point `.env` `GOOGLE_CLOUD_PROJECT` at the billed project and enable Vertex AI there (no billing changes) |
| ~11:12 | **Live run 2 (real Crustdata, mock LLM) after the domain fixes:** the domain query (skills OR headline) is accepted by the API. 70 profiles found, 10 shortlisted. Payments verified for 9 of 10 (headline 6, skills 2, past title 1). Claims: 69 verified, 1 unverifiable, 0 contradicted. **Issue:** 8 of 10 candidates score 100, so the ranker saturates and doesn't differentiate |
| ~11:09 | WS3 domain fix merged (e19a9d6): domain skills such as payments, fintech or saas map to industry keywords. Evidence order: profile skills, headline, job titles, Company Enrich industry, job-level industry or employer name, company description, citing the matched field. On real fixtures, 3 of 6 people now have payments verified. Concurrent roles are deduped by company |
| ~11:08 | WS2 domain fix merged (f45233a): each search level with titles also runs a domain query (all title variants + location + up to 3 domain terms, matched on skills OR headline). Hits get a +3 prescore boost. Skills and headline field names are not live-verified yet, but a rejected query fails alone |
| ~11:06 | **First live run (real Crustdata, mock LLM)**, brief "senior backend engineer, payments experience, Bangalore": 4 title-variant searches returned 62 profiles, 10 were enriched and shortlisted, 0 errors. Claims: 61 verified, 9 unverifiable, 0 contradicted. City filter confirmed on the real API. Issues sent to WS2/WS3: (a) the skills filter only applies at the last broaden step, so a domain like "payments" never shapes the search; (b) the verifier treats "payments" as a LinkedIn skill, so it's always unverifiable (fix: evidence it from employer industry); (c) false "concurrent roles: Wipro, Wipro" flag (fix: dedupe by company) |
| ~11:02 | **Blocker:** Vertex returns 403 BILLING_DISABLED on the GCP project, although the ADC login works. The user needs to link a billing account. Meanwhile, live Crustdata runs use `LLM_MODE=mock` |
| ~11:00 | WS1 person fixtures merged into main (e476941). 36 tests pass in replay mode |
| ~10:56 | Merged into main: **WS4 "Dossier" UI** (PR #2: trace, shortlist and dossier panes, compare table, pin/pass/hide-contradicted, Markdown/CSV/JSON export, keyboard shortcuts, bundled fonts, `frontend/.env.example`; tsc and `next build` pass). **WS3 real-data fixes**: skills match on the base name ("Python (Programming Language)"), stage/size fall back to job-level `company_headcount_latest` / `company_professional_network_industry`, titles show `seniority_level`, experience claims cite exact field paths, raw cached responses are unwrapped. **WS5**: final seeded fakes (5 fakes, 10 lies, all 7 lie types, 10/10 caught, 0 false positives) built locally and not committed, plus `show_fake.py` terminal view for the video. 36 backend tests pass |
| ~10:53 | WS1 complete on `ws/crustdata` (0bc2906): person fixtures (`person_search.json`, 5 `person_enrich_*.json`, `companies.json`), plus `SMOKE_REPORT.md`. The live smoke run passed all 15 steps, and the city-OR-country `(.)` location filter works on the real API. Merged at ~11:00 IST after the user's decision |
| ~10:51 | Vertex AI API enabled on the team's GCP project, and `GOOGLE_CLOUD_PROJECT` set in the Mac's `.env` (the project ID stays out of the repo). Next: confirm a live Gemini call |
| ~10:48 | WS1 v2 merged: `person_search` accepts raw Crustdata syntax or the simple shape (with city/country aliases, overridable via `CRUSTDATA_LOCATION_FIELDS`). Concurrent `person_enrich` calls are coalesced into batches of up to 25. Note: the orchestrator currently sends its own mapped filters (`to_crustdata_filters`), so WS2's mapping is the one in effect. Pick one at the first live run |
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
1. GCP project for Vertex: the one with billing (set in Mac `.env` only, never in the repo).
1. ~~LLM key~~ Resolved 10:12: Gemini via Vertex ADC. Each dev machine runs the ADC setup (`bash <(curl -sSL https://storage.googleapis.com/cloud-samples-data/adc/setup_adc.sh)`, or `gcloud auth application-default login`), then sets `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` in `.env`.
2. Crustdata API key, rate limits and credit cost per call (from the 10:00 walkthrough).
4. ~~Real people's data in a public repo~~ Decided ~11:00 IST: keep public and merge.
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
- **Env vars (all workstreams use these names):** `RECRUITER_NAME` (outreach sign-off, default "[Your name]"), `CRUSTDATA_MODE` = `live | cache | replay` (default `cache`), `LLM_MODE` = `live | mock`, `GEMINI_FAST_MODEL` (default `gemini-2.5-flash`), `GEMINI_SMART_MODEL` (default `gemini-2.5-pro`). Python deps go in `backend/requirements.txt` (owned by WS2).
- **WS2:** event models `StepEvent / CandidateEvent / ErrorEvent / DoneEvent` live in `schemas.py`. `StepEvent` has optional `data` (the parse step sends `{"criteria": {...}}`). All `Criteria` / `Candidate` fields have defaults. `llm.py` also exports `LLMError` and `is_mock()`.
- **WS2 to WS1 (10:40):** the orchestrator calls `CrustdataClient(api_key=..., mode=CRUSTDATA_MODE)` and passes `person_search` filters as `{"titles": [one title], "locations": [...], "skills": [...], "seniority": str | None}`, one call per title variant, in parallel. WS1 maps that to the real API filter syntax.
- **WS2 to WS3 (10:40):** if `verify/` is missing or throws, `app/fallbacks.py` runs a basic verifier/ranker instead. The orchestrator namespaces claim ids per candidate (`k1` -> `c3-k1`), and reasons that cite unknown claim ids are dropped.
- **WS2 to WS4 (10:40):** extra endpoints `GET /api/run?brief=...` (for EventSource) and `GET /api/replay?delay=0.6` (streams `fixtures/run.jsonl`). The final step event `{"step":"rank","data":{"order":[ids]}}` gives the shortlist order.
- **`CRUSTDATA_MODE=dev`** = synthetic people, used automatically if `app/crustdata/` isn't present.
- **WS3 verifier (10:43):** self-reported facts come from `person["claimed"]` (keys: `employer, title, start_date, tenure_years, years_experience, location, company_stage, skills`); otherwise they come from the profile headline. **WS5 seeded fakes must use the `claimed` key.** Facts are checked against Person Enrich employment and Company Enrich, and the employer falls back to `web_search` when the graph has nothing. `verify_candidate` takes an optional `today=` kwarg for tests. It never raises: each Crustdata call has an 8s timeout, and a failed call means that claim is unverifiable. Flags: job change in the last 120 days, recent exit, stale headline, concurrent roles, each contradiction.
- **WS3 ranker (updated ~11:12):** graded, with the base capped at 90 and up to +10 in cited bonuses (see progress log). Original design: deterministic weights: role 30, skills 25, location 15, company pref 15, experience 15, rescaled to only the factors the brief mentions. Each contradiction costs -12 points, a stale headline -6. `RANK_USE_LLM=1` rewrites the reason text with Gemini and keeps the claim ids.
- **Seeded-fakes demo beat:** there is no resume-verify endpoint, so the video shows it as a terminal shot (`demo/seeded_fakes/show_fake.py`). Run `make_fakes.py` on the Mac before recording.
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
- Person location: `basic_profile.location.{city, state, country, full_location, raw}`.
- Person-level fixtures are on `main` (user's decision, ~11:00 IST, repo stays public). to the public repo (user decision on WS1's card, ~10:46 IST), pushed from Sai's Mac together with `companies.json`.
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

### WS7 Send Guard (Countersign part 2), progress log
Branch `claude/project-thread-gz8tzg`, based on WS6 (`claude/project-thread-icv883`, 547293c). Owns `backend/app/agents/guard.py`, `guard_api.py`, `guard_demo.py`, `backend/mcp_server.py`, `backend/tests/test_guard.py`.
- **~11:45 IST, first version done, 16 tests green (all 84 backend tests pass offline).** `check_send(passport, signature, to, body, scope, client=None, *, today=None, graph=None) -> Verdict`. Checks: WS6 `verify_passport(scope, record=False)` (p1..), then `message_signature_valid` (g1, WS6 `verify_message_signature`), `recipient_still_at_company` (g2, `Graph.person(url)`, catches "left Trinkerr on 2022-12-01"), and one `claims_in_body_true` per fact the draft states about the recipient (g3+). Allow only if every check passes; unverifiable blocks. One `guard.verdict` ledger entry per check, with all sources.
- **Claim extraction:** Gemini (`llm.generate_json`, schema `BodyClaims`: employer, title, start_date, tenure_years, years_experience, location, company_stage), merged with a deterministic second-person regex extractor. `LLM_MODE=mock` uses the regex only. Facts are checked by WS3 `verify_candidate` with `person["claimed"]`, so the guard and the hiring verifier agree. A draft with no checkable facts passes that check (opinions and questions aren't claims). The LLM path has not run live yet (no Vertex in the cloud).
- **HTTP:** `POST /api/guard/check` -> Verdict, `POST /api/guard/send` -> `{verdict, sent}` (on allow, appends to `backend/data/outbox.jsonl`, `OUTBOX_PATH` overrides; never emails). Both take an optional `today` for demos. Auto-included by WS6's `api.py`.
- **MCP server:** `cd backend && CRUSTDATA_MODE=replay python mcp_server.py` (stdio; plain JSON-RPC, no MCP SDK dependency; tested with the official `mcp` client). Tools: `verify_agent`, `check_before_send`, `send_message`, `sign_message`, `ledger_lookup`. Claude Code: `claude mcp add countersign -e CRUSTDATA_MODE=replay -- python /abs/path/backend/mcp_server.py`.
- **Terminal demo:** `cd backend && CRUSTDATA_MODE=replay LLM_MODE=mock python -m app.agents.guard_demo` runs 5 cases: clean outreach (allow), "congrats on 5 years at Fam" (block, record says 2025-05-01), recipient already left (block), sponsor left PulseTrader (block), body altered after signing (block).
- **~12:00 IST, exhaustive eval (user asked for far more than 5 cases).** `backend/evals/guard_eval.py` builds cases from each real person's own record, so labels are ground truth: true claims (employer, exact title, rounded tenure, start year, city + aliases, experience), sender facts that must not block, false (tenure +3y, other company, inflated title, wrong city, experience +6y), stale (former employer as current, former title), subtle (tenure +1.5y, "Senior" added, start year -2, nearby city), tamper/authority (altered body, whitespace, other agent's signature, edited/expired/revoked passport, missing scope, sponsor left, junior sponsor, unknown recipient), and held-out paraphrases the rule extractor was not tuned on. Offline (14 real people, rules only): **507 cases, false-allow 0/299, false-block 14/208 (6.7%)**; all 14 are held-out "since you joined X back in YEAR" wordings that the safety net blocks as unverifiable (fails closed). First run before fixes was 15.6% false-allow / 10.5% false-block.
- **Fixes from the eval:** tenure, start date and title are now checked against the role the draft names (concurrent or past roles, not just the first current job); year-only start dates compare years; city aliases (Bangalore/Bengaluru, Gurgaon/Gurugram, Bombay/Mumbai...); naming a former employer is a stale fail; camelCase / "Pvt. Ltd." / "Head of X" / "&" in names and titles; number words. **Fail closed on missed claims:** with Gemini, its `other` list holds facts that fit no field (unverifiable); without Gemini, a keyword safety net flags second-person sentences that state a duration, year, title, location or employer the extractor didn't return. Pitches ("you'd be joining...") and sender facts are skipped.
- **Sourced really calls Send Guard over MCP:** `python -m app.agents.sourced_agent "<brief>"` runs the live pipeline, then signs each shortlisted draft with Sourced's passport key and calls `send_message` on a spawned `mcp_server.py` (stdio JSON-RPC). Identity comes from WS8's registry (active agent named Sourced) when present, else `backend/data/sourced_identity.json`. `--from-run file.jsonl` replays a saved `/api/run` stream; `--fixture-people` runs offline. Offline: 5/5 of Sourced's own drafts were sent, and a draft with an injected false claim was blocked.
- **~12:10 IST, gap audit P1-8 fixed:** MCP tools and `/api/guard/*` take `agent_id`; the server loads the passport from WS8's registry (a `passport` JSON is still accepted for agents not onboarded here). The `sign_message` tool is gone, so no private key ever crosses the wire: agents sign locally with `passport.sign_message`. A non-active registry status adds a failing `agent_active` check. Tested merged with WS8's real registry (113 tests pass): a suspended Sourced is blocked (`agent_active` + `not_revoked`) and is never swapped for a fresh local passport. **`scripts/mcp_agent_demo.py` on the audit branch still calls `sign_message`: it must sign locally and send `agent_id`.**
- **~12:40 IST, fixes from the first live Mac run.** (1) The eval hung at 120 people: `ledger.append` re-read the whole file on every write (O(n^2)). The ledger now keeps the tail (count, last hash, revocations) and reads only new bytes; `verify_chain` still reads everything. 20k appends take 1.7s, and tamper detection is unchanged. (2) Sourced drafts were blocked 8/10 on skill/domain claims ("experience with Payments"): the guard now extracts `skills` and checks them with the verifier's skills/headline/title/industry evidence. (3) Past roles in past tense ("you were Tech Lead at TransFi", "your earlier work at Cvent") were flagged as stale: they're now `past_roles`, checked against past (or current) jobs. Stale fires only when a former employer is mentioned in present tense. The eval adds a `sourced` category (Sourced's own drafts, Gemini when live; all must be allowed) plus skill/past-role true and false cases. Offline: 582 cases, false-allow 0/327, false-block 14/255 (the same held-out wording as before).
- **Needs Sai's Mac (Crustdata still 403 from the cloud):** `cd backend && LLM_MODE=live CRUSTDATA_MODE=cache python -m evals.guard_eval --live 120 --out ../evals_out_guard.md` (120+ people across 10 roles and 7 cities, plus Gemini extraction; the report is gitignored because it names people), then `python -m app.agents.sourced_agent "senior backend engineer, payments, bangalore"`.

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

> **Superseded (~12:24):** the current script is `demo/script.md` v2, a 1:55 live run. The text below is the original plan, kept for history.
Draft beats: (1) 10s problem: recruiters are paid on hires, and profiles are stale. (2) Paste a messy brief judges haven't seen. (3) Live feed shows the agent searching title variants. (4) Shortlist appears; open one candidate and show every claim cited, plus a "changed jobs 3 weeks ago" catch. (5) Show a contradicted claim being flagged. (6) 10s close: no human in the loop, every claim sourced.
