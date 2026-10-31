# Countersign: trust infrastructure for AI employees

> Track 2 of the hackathon, built **alongside** the Sourced hiring agent (which keeps going unchanged).
> Theme: "Infrastructure for agents", which asks for: *proof of who sent a message, and on whose authority an agent acts*;
> *a check that stops a wrong email before it is sent*; *a tamper-proof record of where every fact came from*.
> Judges want "building blocks that still hold after a crash, a model swap or a lie."

## One-line pitch
Companies are hiring AI employees. Countersign gives each one a verifiable identity tied to a real human sponsor,
checks live against Crustdata that the sponsor still has the authority, blocks wrong outbound messages before they are sent,
and writes every action to a tamper-evident ledger.

## The four parts (and who builds them)

| # | Part | Folder (owned by) | What it does |
|---|---|---|---|
| 1 | **Agent Passport** | `backend/app/agents/passport.py` (WS6) | Ed25519-signed credential: agent id, sponsor (real person), company, scopes, expiry. `verify_passport()` checks signature + expiry + **live sponsor checks via Crustdata**. |
| 2 | **Send Guard** | `backend/app/agents/guard.py`, `backend/mcp_server.py` (WS7) | Pre-send check any agent calls (HTTP or MCP) with a draft message. Blocks if passport fails, scope missing, recipient no longer at the company, or the draft makes a false/unverifiable claim (reuses `verify/`). |
| 3 | **AI Employee registry + console** | `backend/app/agents/registry.py`, `frontend/src/app/console/` (WS8) | Onboard an AI employee (name, role, sponsor LinkedIn URL, scopes), issue its passport, list status (active / suspended + reason), re-check sponsors ("payroll run"). Sourced is employee #1. |
| 4 | **Ledger** | `backend/app/agents/ledger.py` (WS6) | Append-only, hash-chained JSONL. Every passport issue, check, guard verdict, suspension is an entry carrying its Crustdata `_source` citations. `verify_chain()` detects tampering. |

Shared HTTP routes live in `backend/app/agents/api.py` (WS6 creates the file with stubs; each WS fills its own routes).
`backend/app/main.py` (WS2) gets exactly one line: `app.include_router(agents_router)`.

## Rules every part follows
- **No real messages are sent.** The guard returns a verdict; "send" means "write to the outbox file", never email.
- **Every verdict cites a source** (`Source` from `schemas.py`: endpoint + field). No source = `unverifiable`, never `pass`.
- **Fail closed.** If Crustdata errors or times out, the check is `unverifiable` and the guard blocks (with that reason).
- Crustdata is blocked from cloud sandboxes: code against `fixtures/crustdata/` with `CRUSTDATA_MODE=replay`; live runs on Sai's Mac.
- No new heavy deps. `cryptography` (Ed25519) is the only addition to `requirements.txt`.
- Reuse `app/verify/profile.py` (`load_person`, `load_company`, `same_company`, `seniority_rank`, `title_similarity`) for all person/company reading.

## Shared types (`backend/app/agents/models.py`, WS6 creates first, others import)
```python
Scope = Literal["outreach.hiring", "outreach.sales", "data.read", "contract.sign", "payment.send"]

class Sponsor(BaseModel):
    name: str; profile_url: str; company: str; company_domain: str | None = None; title: str | None = None

class Passport(BaseModel):            # what an agent carries
    agent_id: str; agent_name: str; role: str
    sponsor: Sponsor; scopes: list[Scope]
    issued_at: str; expires_at: str   # ISO
    public_key: str                   # agent's Ed25519 public key, base64
    issuer_signature: str             # Countersign signs the canonical JSON of every other field

class Check(BaseModel):               # one line of a verdict
    id: str; name: str                # e.g. "sponsor_still_employed"
    status: Literal["pass", "fail", "unverifiable"]
    detail: str; source: Source | None = None

class Verdict(BaseModel):
    subject: str                      # agent_id or message id
    decision: Literal["allow", "block"]
    checks: list[Check]
    ledger_entry: str | None = None   # hash of the ledger entry that recorded this verdict
```

## Function contracts
```python
# passport.py (WS6)
def issue_passport(agent_name: str, role: str, sponsor: Sponsor, scopes: list[Scope], days: int = 30) -> tuple[Passport, bytes]  # (passport, agent private key)
def sign_message(passport: Passport, agent_private_key: bytes, body: str) -> str   # agent's signature over body
async def verify_passport(p: Passport, client: CrustdataClient, scope: Scope | None = None, *, today=None) -> Verdict
#   checks: signature_valid, not_expired, sponsor_exists (person/enrich), sponsor_still_employed (current employer == sponsor.company,
#           catches "left 3 weeks ago" via end_date / missing current job), domain_matches_company (company/identify),
#           sponsor_can_grant_scope (title/seniority rule table, e.g. outreach.hiring needs talent/HR/eng-manager/founder; contract.sign needs VP+/founder)

# ledger.py (WS6)
def append(kind: str, payload: dict, sources: list[Source] = []) -> str        # returns entry hash; entry = {seq, ts, kind, payload, sources, prev_hash, hash}
def entries(agent_id: str | None = None) -> list[dict]
def verify_chain() -> tuple[bool, int | None]                                   # (ok, first bad seq)
#   file: backend/data/ledger.jsonl (gitignored); LEDGER_PATH env overrides (tests use tmp_path)

# guard.py (WS7)
async def check_send(passport: Passport, signature: str, to: dict, body: str, scope: Scope, client: CrustdataClient) -> Verdict
#   to = {"name", "profile_url", "company"}; runs verify_passport(scope) + message_signature_valid + recipient_still_at_company
#   + claims_in_body_true (extract factual claims about the recipient with llm.generate_json, check with verify/ helpers).
#   allow only if every check passes. Appends verdict to ledger.

# registry.py (WS8)
def onboard(agent_name, role, sponsor: Sponsor, scopes) -> dict            # issues passport, stores in backend/data/agents.json, ledger entry
def list_agents() -> list[dict]                                            # {passport, status: active|suspended, reason, last_checked}
async def recheck_all(client) -> list[Verdict]                             # "payroll run": verify_passport for each, suspend on fail
```

## HTTP routes (`/api/agents/...`)
| Method | Path | Body / returns | WS |
|---|---|---|---|
| POST | `/api/agents` | onboard body -> `{agent, passport}` | WS8 |
| GET | `/api/agents` | list | WS8 |
| POST | `/api/agents/recheck` | -> `list[Verdict]` | WS8 |
| POST | `/api/passport/verify` | `{passport, scope?}` -> `Verdict` | WS6 |
| POST | `/api/guard/check` | `{passport, signature, to, body, scope}` -> `Verdict` | WS7 |
| GET | `/api/ledger?agent_id=` | entries + `{chain_ok, first_bad_seq}` | WS6 |

MCP server (WS7, `backend/mcp_server.py`, stdio): tools `verify_agent(passport)`, `check_before_send(...)`, `ledger_lookup(agent_id)`.

## Demo story (2 min, shared with the Sourced video or its own)
1. Console: onboard **Sourced** as an AI recruiter, sponsored by a real Head of Talent (from fixtures). Passport issued, ledger entry 1.
2. Sourced drafts outreach (existing pipeline). Guard: **allow**, every check green with Crustdata citations.
3. Same agent, sponsor swapped to someone whose Crustdata record shows they **left the company weeks ago** -> **block** "sponsor_still_employed: fail, end_date 2026-10-02 (person/enrich, past_employers[0])". "Payroll run" suspends it.
4. A draft that says "congrats on 5 years at Razorpay" to someone with 2 years -> **block** on the false claim.
5. Edit one line of `ledger.jsonl` by hand -> ledger view shows **chain broken at entry N**.

## Fixtures for demos/tests
WS6 adds `fixtures/countersign/sponsors.json`: 3 sponsors built from `fixtures/crustdata/person_enrich_*.json`
(one current + authorised, one current but junior = can't grant `contract.sign`, one with a recent end_date = left).
