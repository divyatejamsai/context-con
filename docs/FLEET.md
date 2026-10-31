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

## The guided demo (one story, seven beats)
`backend/app/fleet/demo.py` plays the fleet as an ordered story. The console's Run demo page streams it from
`GET /api/demo/run`, and `scripts/run_fleet.py` prints the same events in a terminal.

| # | Beat | What the audience sees |
|---|---|---|
| 1 | Onboard the fleet | Six passports, each tied to a real Crustdata person, with job, scopes and runtime |
| 2 | Real work | Pipeline clears 3 sales emails, Reference catches 10 of 10 planted resume lies, Diligence files a 12-fact Razorpay brief |
| 3 | The sponsor left | The payroll run suspends Closer (Crustdata: "Left PulseTrader on 2026-04-01"), then Closer's clock-in and its send are both refused |
| 4 | Past its permissions | Diligence emails the vendor: blocked on `scope_in_passport` and `sponsor_can_grant_scope` |
| 5 | Wrong facts | Stale CRM row (Shivank "at PulseTrader") and "congrats on 5 years at Fam" (record: 1.5 years) are both blocked, with the field that disproves each |
| 6 | Tampering | A self-edited passport fails `signature_valid`, and one edited line in a copy of the ledger shows "chain broken at entry #N" (the live ledger is never touched) |
| 7 | Claude Code | The real CLI with only the MCP server signs two notes: the clean one is allowed, the false tenure is blocked |

Every verdict in the stream carries its checks and each check's Crustdata source. The event shapes are at the
top of `demo.py`.

```bash
cd backend
python scripts/run_fleet.py --claude-code --pause 2       # live (.env modes), real store: the console fills in
python scripts/run_fleet.py -v                            # every check with its source
CRUSTDATA_MODE=replay LLM_MODE=mock python scripts/run_fleet.py --store /tmp/fleet    # offline, about 5s
curl -N localhost:8000/api/demo/run?claude_code=true      # the stream the console reads
```
Re-running reuses the agents in the store, so a second run is a fresh payroll run on the same fleet. Exit code 1
(or `done.ok=false`) if any beat's outcome is wrong. `--sourced` also runs Sourced's hiring pipeline. Live, it
only counts as passing if at least one shortlisted draft went through Send Guard.
When `COUNTERSIGN_ADMIN_TOKEN` is set, `/api/demo/run` needs it (`x-admin-token` or `?token=`).

Live cost (Crustdata): about 6 Person Enrich (batched), 1 Company Identify, 6 Company Enrich and 1 Web Fetch.
Gemini makes 4 drafts, 1 brief (pro tier) and 5 resume extractions.

## Add Claude Code by hand (for the video)
```bash
cd backend
claude mcp add countersign -e AGENTS_PATH=$PWD/data/agents.json -- python $PWD/mcp_server.py
python scripts/run_fleet.py --only outside        # onboards the fleet, prints Claude Code's agent id
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

## Self-audit of the fleet and demo (round 2)
Fixed in this round:
- The ledger had only an in-process lock, but the API, the MCP server subprocess and scripts all append to
  one file, so two processes could claim the same seq and break the chain. Appends now take a file lock
  (`fcntl`, `ledger.jsonl.lock`).
- `verify_chain(path)` audits any copy of a ledger. The tamper beat uses it on a copy, never on the live file.
- The Sourced run counted as "OK" with no shortlist. Live, it now needs at least one guarded draft.
- `/api/demo/run` writes to the store and can start the Claude Code CLI, so it now honours `COUNTERSIGN_ADMIN_TOKEN`.

Still open (honest limits):
- In replay mode, Gemini is off: drafts and the vendor brief come from labelled templates, and resumes are read
  by a line parser. Live mode uses Gemini for all three, and those outputs vary run to run. The guard still
  checks whatever Gemini writes, so a live draft can be blocked for a claim it made.
- The Claude Code beat needs the `claude` CLI signed in on the machine (about 20s). Without it, the
  beat is reported as skipped, not passed silently.
- One demo run at a time per server process. The lock is in-process, so a second uvicorn worker could start a
  parallel run.
- Agent keys sit in `agents.json` (P2-12). An outside agent signs through `agent_sign.py`, which reads that
  file, so outside agents and the registry still share a machine.
