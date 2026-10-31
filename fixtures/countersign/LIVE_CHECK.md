# Countersign live check (2026-10-31, Sai's Mac)

`verify_passport` ran for all 5 scenarios in `sponsors.json` against the real Crustdata API
(fresh empty cache, no fixtures): 5 live `person/enrich` calls, 0 errors, 0 retries.

| Scenario | Expect | Live verdict | Failing check |
|---|---|---|---|
| authorised_founder | allow | allow | - |
| sponsor_left | block | block | sponsor_still_employed: left PulseTrader 2026-04-01, now at Galaxy |
| title_changed | block | block | sponsor_title_current ('Co-Founder' vs 'Advisor'); sponsor_can_grant_scope |
| junior_sponsor | block | block | sponsor_can_grant_scope (Backend Engineer cannot delegate contract.sign) |
| spoofed_domain | block | block | domain_matches_company (kiot-hr.com vs kiot.io) |

The 5 responses are recorded in the cache format under `fixtures/crustdata/person_enrich/<request_hash>.json`,
so `CrustdataClient(mode="replay")` serves them through the normal client path (not only the Graph fallback).
Replay of the same 5 scenarios: 5/5 match, served as `fixture`, 0 live calls. `pytest`: 68 passed.
