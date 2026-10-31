# 2-minute demo video script (v2: Countersign managing a real AI-employee fleet)

**Story:** companies are hiring AI employees. **Countersign** gives each one a passport tied to a real human sponsor,
checks live against Crustdata that the sponsor still has the authority, stops wrong messages before they're sent,
and writes every action to a tamper-evident ledger. **Sourced, the hiring agent, is AI employee #1** and the first thing
judges see. Everything runs **live** (`CRUSTDATA_MODE=cache`, `LLM_MODE=live`). Replay is only a backup.

> The final submission story is still the user's call (Hiring only vs Countersign with Sourced as employee #1).
> This script covers the combined story. For a hiring-only cut, keep beats 1-2 and stretch them, then use the hiring close at the bottom.

Target **1:55**. Two browser tabs: `localhost:3000` (Sourced) and `localhost:3000/console` (Countersign). One terminal.

## Before recording (about 10 min, on the Mac)
```bash
git pull
backend/scripts/demo_up.sh        # seeds the fleet live (payroll, every agent's job), starts API :8000 + UI :3000
```
- [ ] The fleet scorecard prints all OK. The Closer agent should be **suspended**, and the stale Pipeline lead **blocked**.
- [ ] Run the demo brief (below) once in the Sourced tab, so the Crustdata cache is warm and the passport and guard steps show up. Then reload the page.
- [ ] Console: the roster shows 6 AI employees, and the Ledger panel says chain OK.
- [ ] Open the ledger file in an editor: `backend/data/ledger.jsonl`. Pick a `work.resume_check` line to edit live in beat 5.
- [ ] Turn on Focus mode, close other tabs, and set browser zoom to 110-125%. Record with `Cmd+Shift+5` with the mic on, or record silent and voice over later.

**Demo brief** (messy on purpose):
```
need a senior backend eng asap, payments exp (UPI/cards), blr or remote india. ex startup pref, NOT big tech lifers. python or go. 5+ yrs
```
If a judge wants to see an unseen request, take any brief they type. That's the point.

## Run of show

| Time | On screen | Say (roughly) |
|---|---|---|
| 0:00-0:10 | Console roster: 6 AI employees, their sponsors and statuses | "Companies are hiring AI employees. But who is each one acting for, and does that person still have the authority? Countersign answers that, live, from Crustdata's people graph." |
| 0:10-0:30 | Sourced tab: paste the brief and run. The first step to land is the **passport check**: sponsor exists, still employed, domain matches, title can grant the scope, each one cited | "This is Sourced, our hiring agent and AI employee number one. Before it touches any data, Countersign checks its passport: the co-founder who sponsors it is a real person, still at the company, and senior enough to authorise hiring outreach. Every check is cited." |
| 0:30-0:55 | Step feed: title variants, search, broadening, enrich. Then the shortlist. Open the top candidate's dossier and hover a claim's source | "From a messy brief it expands titles, searches Crustdata, enriches each candidate and their company, and verifies every claim. Each line is Verified, Contradicted or Unverifiable, with the endpoint and field it came from." (If a "changed jobs N weeks ago" flag appears, point at it: "that's Crustdata's freshness.") |
| 0:55-1:15 | Same candidate: green **Send Guard cleared** badge on the draft. Switch to Console > Send Guard, pick Sourced, recipient Vinod Sonagara at Fam, draft "congrats on 5 years at Fam…", Send | "Its outreach draft went through Send Guard and cleared. It's never sent automatically. Now watch an agent get a fact wrong. This draft says five years at Fam. Crustdata says he joined in 2025, so it's blocked before it's sent, with the field that proves it." |
| 1:15-1:35 | Console > **Run payroll check**. Closer goes Suspended, with the reason cited (sponsor left PulseTrader 2026-04-01). Scroll the roster to Diligence, Reference and Claude Code | "Countersign runs payroll for agents: it re-checks every sponsor. Closer's sponsor left his company in April, so Closer is suspended, with the citation, and its next send is refused. The same rules cover the vendor-diligence agent, the reference checker that caught every planted lie in its applicant resumes, and even Claude Code, which connects over MCP." |
| 1:35-1:50 | Ledger panel: chain OK. In the editor, change one character in a ledger line and save. Within 3 s (or click "Re-check now") the Ledger panel shows **tampering detected at entry #N** | "Every passport check, verdict and piece of work goes on a hash-chained ledger with its sources. Change one character in the file and Countersign points at the exact entry." |
| 1:50-1:58 | Back to the console roster | "Every AI employee is backed by a real person, checked against Crustdata, stopped before it says something false, and on the record. That's Countersign." |

**Hiring-only close** (if the story is just Sourced): "Messy brief in, verified and cited shortlist out, drafts checked before sending, no human in the loop. Built on Crustdata."

## Cut order if over 2:00
1. Drop the Claude Code / Diligence / Reference mentions in 1:15-1:35 (keep Closer).
2. Shorten 0:30-0:55 by speeding up the step feed 1.5-2x in the edit (say "sped up").
3. Never cut: the passport check, a Send Guard block, or the ledger tamper. Those are the claims.

## If something breaks during recording
- **Sourced finds nobody / is slow:** check `curl localhost:8000/api/health` shows live modes. Rate limited (Person Enrich is 15/min)? Wait a minute and re-run. The cache from the warm-up run makes the second run fast.
- **A draft is "blocked" when it should clear:** the guard fails closed on a rate limit. Re-run after a minute, or set a lower `GUARD_MAX` in `.env`.
- **Console says backend offline:** the API died. Run `backend/scripts/demo_up.sh --no-fleet` (keeps the seeded store).
- **Live API down entirely:** `CRUSTDATA_MODE=replay`. The fleet beats still work from fixtures, but Sourced will find nobody in replay unless its brief's cache was pushed (gap P0-3). Say nothing different, the data is real.
- **Tamper beat:** after recording, undo the edit (or delete `backend/data/ledger.jsonl` and re-run `demo_up.sh`) so the store is clean for the live finals.

## After recording
- Trim with `Cmd+T` in QuickTime, export at 1080p, watch it once end to end, and upload by 15:15.
