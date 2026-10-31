# verify/ (WS3)

`verify_candidate(person, company, criteria, client, today=None) -> (claims, flags)`
`rank_candidate(person, claims, criteria) -> (score, reasons)`

- Claims checked: employer, title, tenure, total experience, location, company stage/size, each brief skill.
- What is checked against what: `person["claimed"]` (resume / seeded fake: employer, title, start_date,
  tenure_years, years_experience, location, company_stage, skills) or else the profile headline,
  against the employment record from Person Enrich and Company Enrich. Employer with no graph backing
  is corroborated via `client.web_search`.
- `company=None` is fine: the verifier calls `company_enrich` / `company_identify` itself.
- Any failed or slow call (8s, `VERIFY_CALL_TIMEOUT`) makes that claim `unverifiable`, never a guess.
- Flags: job change in the last 120 days, recent exit, stale headline, concurrent roles, every contradiction.
- Ranker is deterministic (role 30, skills 25, location 15, company pref 15, experience 15, rescaled
  to the factors the brief mentions; 12 pts off per contradiction, 6 for a stale headline).
  Every reason cites claim ids. `RANK_USE_LLM=1` rewrites reason text via `app.llm` (ids preserved).
- Env: `VERIFY_WEB=0` disables web corroboration.

Tests: `cd backend && python -m pytest tests/test_verify.py -q` (needs pytest-asyncio).
