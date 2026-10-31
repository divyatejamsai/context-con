# Send Guard live check (2026-10-31, Sai's Mac)

`python -m app.agents.guard_demo` with `CRUSTDATA_MODE=cache LLM_MODE=live` against the real Crustdata API
(empty cache, no fixtures) and Gemini claim extraction. 15 s, no errors, no extraction fallback.

| Case | Verdict | Failing check |
|---|---|---|
| Clean outreach | ALLOW | - |
| False claim ("5 years at Fam") | BLOCK | claims_in_body_true (start 2025-05-01, 1.5 yrs) |
| Recipient already left (Trinkerr) | BLOCK | recipient_still_at_company, claims_in_body_true |
| Sponsor left the company | BLOCK | sponsor_still_employed (left PulseTrader 2026-04-01) |
| Body altered after signing | BLOCK | message_signature_valid |

Recorded: the 2 batched `person/enrich` responses in `fixtures/crustdata/person_enrich/` (520a67b3d0a1e887, b913b522545d73b4).
With an empty cache, two reruns served everything from fixtures (0 live calls, same verdicts).
Caveat: Person Enrich calls are batched by timing, so a different batch composition misses these files.
