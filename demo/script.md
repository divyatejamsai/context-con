# 2-minute demo video script (v3: Sourced, run by Countersign)

**Story (chosen by the user):** Sourced is a hiring agent and **AI employee #1**. Countersign is what makes it safe to
let it work alone. Its passport ties it to a real human sponsor checked live on Crustdata. Send Guard stops a wrong
message before it's sent. A payroll check suspends any agent whose sponsor has left. Every action lands on a
tamper-evident ledger. The other five agents in the fleet show that the same rules hold for every AI employee.

Everything is recorded **live** (`CRUSTDATA_MODE=cache`, `LLM_MODE=live`). Replay is only a backup.
Target **1:55**. Setup: browser tabs `localhost:3000` (Sourced) and `localhost:3000/console` (Countersign), plus one terminal in `backend/`.

The beats follow the run of show in `docs/REAL_PRODUCT_GAPS.md` (round 2). Beats 4-5 use the guided fleet demo
(`app/fleet/demo.py`, `scripts/run_fleet.py`, `GET /api/demo/run`).

## Before recording (about 10 min, on the Mac)
```bash
git pull
cd backend && python scripts/run_fleet.py --claude-code    # guided demo, live: seeds the fleet + ledger, all 7 beats must be OK
cd .. && backend/scripts/demo_up.sh --no-fleet              # API :8000 + UI :3000 on the store just seeded
```
- [ ] `run_fleet.py` ends with PASS (`done.ok=true`, chain OK). Closer is **suspended** and the stale CRM row is **blocked**. The Claude Code beat needs `claude` installed. Without it, drop `--claude-code` and cut that line from beat 4.
- [ ] Run the demo brief (below) once in the Sourced tab, so the Crustdata cache is warm and you can confirm the passport step and at least one **Send Guard cleared** badge appear. Then reload the page.
- [ ] Console: the roster shows 6 AI employees, and the Ledger panel says chain OK.
- [ ] If `COUNTERSIGN_ADMIN_TOKEN` is set in `.env`, paste it into the console's Admin token field. The payroll check and the demo stream need it.
- [ ] Turn on Focus mode, close other tabs, and set browser zoom to 110-125%. Make the terminal font large (18pt+). Record with `Cmd+Shift+5` with the mic on, or record silent and voice over later.

**Demo brief** (messy on purpose, never run by the agents before today):
```
need a senior backend eng asap, payments exp (UPI/cards), blr or remote india. ex startup pref, NOT big tech lifers. python or go. 5+ yrs
```
If a judge types their own brief at the finals, use that one. "A request it has never seen" is the point.

## Run of show

| # | Time | On screen | Say (roughly) |
|---|---|---|---|
| 1 | 0:00-0:15 | Sourced tab: paste the brief, Run. The first step to land is the **passport check**: sponsor exists, is still employed, domain matches, title can grant `outreach.hiring`, each one cited | "This is Sourced, an AI recruiter, and it's an AI employee. Before it touches any data, Countersign checks its passport live on Crustdata: its sponsor is a real co-founder, still at the company, and senior enough to authorise hiring outreach." |
| 2 | 0:15-0:40 | Step feed: title variants, search, broadening, enrich. Then the shortlist. Open the top candidate and hover a claim's source | "From a messy brief it expands the titles, searches Crustdata's people graph, enriches every candidate and their company, and checks each claim. Every line is Verified, Contradicted or Unverifiable, with the endpoint and field it came from." (If a "changed jobs N weeks ago" flag shows, point at it: "Crustdata knows before the profile does.") |
| 3 | 0:40-0:58 | Same candidate: the green **Send Guard cleared** badge on its draft. Switch to Console > Send Guard: agent Sourced, recipient Vinod Sonagara at Fam, draft "Congrats on 5 years at Fam…", Send. It's **blocked**, citing the start date | "Its outreach draft went through Send Guard and cleared, and it's never sent automatically. Now a draft with one wrong fact: five years at Fam. Crustdata's record says about a year and a half, so it's blocked before it goes out, with the field that proves it." |
| 4 | 0:58-1:25 | Console roster: 6 AI employees. Click **Run payroll check**: Closer goes **Suspended**, citing "left PulseTrader on 2026-04-01". Then the terminal: `python scripts/run_fleet.py --only sponsor_left,scope,outside --claude-code --pause 1` (speed up 2x in the edit) | "Sourced isn't alone. Countersign runs a fleet: sales, vendor diligence, reference checks, and Claude Code over MCP. A payroll check re-verifies every sponsor. Closer's sponsor left his company in April, so Closer is suspended, and its next clock-in and send are both refused. The diligence agent tries to email a vendor without the scope, and it's refused too. Claude Code, with only our MCP server, gets its clean note allowed and its false one blocked." |
| 5 | 1:25-1:45 | Console Ledger panel: chain OK, entries with sources. Terminal: `python scripts/run_fleet.py --only tamper` shows the forged passport blocked on `signature_valid`, and **chain broken at entry #N** in an edited copy | "Every passport check, verdict and piece of work is written to a hash-chained ledger with its Crustdata sources. An agent that edits its own passport to give itself payment rights fails the signature. Change one line of the ledger and the chain points at the exact entry." |
| 6 | 1:45-1:58 | Back to the Sourced shortlist | "Messy brief in, verified shortlist out, no human in the loop. And every AI employee doing it is backed by a real person, checked against Crustdata, stopped before it says something false, and on the record." |

**Single-take alternative for beats 4-5:** run `python scripts/run_fleet.py --only sponsor_left,scope,stale,tamper,outside --claude-code --pause 1.5` once and narrate over it (sped up), then cut to the console roster showing Closer suspended. It's fewer tab switches, but less visual.

## Cut order if over 2:00
1. Drop the scope refusal and Claude Code lines in beat 4 (keep Closer).
2. Speed up beat 2's step feed 1.5-2x in the edit (say "sped up").
3. Never cut: the passport check (1), a Send Guard block (3), Closer suspended (4), or the ledger chain (5).

## If something breaks during recording
- **Sourced is slow or finds nobody:** check `curl localhost:8000/api/health` shows live modes. Person Enrich is limited to 15/min: wait a minute and re-run. The warm cache makes the second run fast.
- **A draft is blocked when it should clear:** the guard fails closed on a rate limit. Re-run after a minute, or lower `GUARD_MAX` in `.env`.
- **A `run_fleet.py` beat isn't OK:** run it with `-v` to see every check and its source. A second run reuses the fleet and does a fresh payroll run.
- **Console says backend offline:** run `backend/scripts/demo_up.sh --no-fleet` again (it keeps the seeded store).
- **Live API down entirely:** `CRUSTDATA_MODE=replay LLM_MODE=mock python scripts/run_fleet.py --store /tmp/fleet` still plays all 7 beats from fixtures in about 5 s. Sourced needs live data, or a pushed cache for the brief (gap P0-3).
- The tamper beat edits a **copy** of the ledger, so the live ledger stays clean for the finals.

## After recording
- Trim with `Cmd+T` in QuickTime, export at 1080p, watch it once end to end, and upload by 15:15.
