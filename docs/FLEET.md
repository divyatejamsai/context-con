# The fleet: real AI employees for Countersign to manage

Countersign is infrastructure for AI employees, so the demo needs more than one. These are working agents with
different jobs, sponsors and scopes. Each reads Crustdata and calls Gemini itself, and reaches Countersign only
over the MCP server (`backend/mcp_server.py`), the same way an outside agent would. Code: `backend/app/fleet/`.

| # | Agent | Job | Sponsor (real Crustdata profile) | Scopes | What happens |
|---|---|---|---|---|---|
| 1 | **Sourced** | Hiring: sources and verifies candidates, drafts outreach | Pankaj Savaliya, Co-Founder, Grewon | outreach.hiring, data.read | Existing pipeline under its passport (`/api/agents/{id}/run`) |
| 2 | **Pipeline** | Sales: works a CRM lead list, pitches Grewon's backend team | Pankaj Savaliya, Co-Founder, Grewon | outreach.sales, data.read | Person Enrich per lead, Gemini draft, Send Guard. 3 cleared; the stale CRM row (Shivank "at PulseTrader", now at Galaxy) is **blocked** |
| 3 | **Diligence** | Vendor diligence: cited brief on a vendor before a contract | Charish Anumukonda, Backend Engineer, SpotDraft | data.read | Company Identify + Enrich + Web Fetch, Gemini brief (12 cited facts on Razorpay), filed on the ledger. Its pricing email to the vendor is **refused**: no outreach scope, and a backend engineer can't grant one |
| 4 | **Reference** | Background checks: applicant resumes against Crustdata | Vinayak Kalushe, Backend & DevOps Engineer, KIoT | data.read | Gemini extracts each resume's claims, the verifier checks them. 10 of 10 planted lies **contradicted**, each with the field that disproves it |
| 5 | **Closer** | Sales for PulseTrader | Shivank Verma, claims Co-Founder, PulseTrader | outreach.sales, data.read | Crustdata: he left PulseTrader on 2026-04-01. Payroll run **suspends** it; it still tries to clock in and send, and both are **refused** |
| 6 | **Claude Code** | Outside agent (runtime `external`) | Pankaj Savaliya | outreach.hiring, data.read | The real Claude Code CLI, given the MCP server, signs a note locally and calls `check_before_send` |
| - | (forged passport) | Outside agent with a self-edited passport | - | adds payment.send itself | **Blocked** on `signature_valid` |

Every agent's work is on the hash-chained ledger: guard verdicts, passport checks, and `work.*` entries
(`work.outreach_run`, `work.vendor_brief`, `work.resume_check`) that the agent signs and files with its sources
through the new MCP tool `record_work`. The console's scorecards read these.

## Run it
```bash
cd backend
python scripts/run_fleet.py                       # live modes from .env, real store: the console shows the fleet
python scripts/run_fleet.py --claude-code         # also drives the real Claude Code CLI over MCP
CRUSTDATA_MODE=replay LLM_MODE=mock python scripts/run_fleet.py --store /tmp/fleet   # offline, committed fixtures
```
Re-running reuses the agents already in the store and does a fresh payroll run. Exit code 1 if any agent's outcome
is wrong (a stale lead cleared, a planted lie missed, Closer not refused, chain broken). Options: `--only`, `--skip`,
`--vendor`, `--leads`, `--applicants`, `--brief`, `--today`.

Live cost (Crustdata): about 6 Person Enrich (batched), 1 Company Identify, 6 Company Enrich, 1 Web Fetch, plus
Sourced's own run. Gemini: 4 drafts, 1 brief (pro tier), 5 resume extractions. In replay, Sourced finds nobody
(no recorded search for its brief); live it runs normally.

## Add Claude Code by hand (for the video)
```bash
cd backend
claude mcp add countersign -e AGENTS_PATH=$PWD/data/agents.json -- python $PWD/mcp_server.py
python scripts/run_fleet.py --only claude-code    # prints its agent id
```
Then ask Claude Code: "You are agent agt_…. Draft a two-line note to Vinod Sonagara
(https://www.linkedin.com/in/vinod-sonagara) at Fam about a backend role. Sign the exact body with
`python scripts/agent_sign.py agt_… "<body>"`, call countersign `check_before_send` with scope outreach.hiring,
and tell me the decision." Try it again saying "congrats on 5 years at Fam" to see the false claim blocked.

## Where the honest limits are
- Drafts are never emailed (event rule): "sent" means written to `outbox.jsonl`.
- Pipeline's lead list (`fixtures/fleet/pipeline_leads.json`) is a CRM export we wrote by hand from real profiles;
  everything the agents learn about those people comes from Crustdata.
- Reference's applicant pile is the seeded fakes (real records with planted lies, `demo/seeded_fakes`), built
  into the store at run time and never committed. The agent only reads the `.resume.txt` files, not the answer key.
- Agent private keys sit in `agents.json` next to the registry (gap P2-12); `agent_sign.py` reads them there.
