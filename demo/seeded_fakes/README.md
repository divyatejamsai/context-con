# Seeded-fake resumes (stretch goal, theme: "applications seeded with fakes")

Idea for the demo: we hand the agent a few resumes. Each one is built from a **real** Crustdata profile,
with 1-2 **planted false claims**. The verifier must mark exactly those claims **Contradicted**, cite the
Crustdata field that disproves them, and leave the true claims **Verified**.

Because they're generated from real fixtures, the lies are checkable against the graph (not against our own made-up data).

## Make them
```bash
# from repo root, after WS1 has saved real Person Enrich responses into fixtures/crustdata/
python demo/seeded_fakes/make_fakes.py fixtures/crustdata/person_enrich_*.json \
    --companies fixtures/crustdata/companies.json --out demo/seeded_fakes/out
python demo/seeded_fakes/check_fakes.py demo/seeded_fakes/out --companies fixtures/crustdata/companies.json
```
For each input profile it writes:
- `out/<slug>.person.json`  the real enrich record plus `person["claimed"]` (employer, title, start_date,
  years_experience, location, company_stage, skills). Pass it straight to `verify_candidate()`.
- `out/<slug>.resume.txt`   the same claims as a plain-text resume, for showing on screen
- `out/answer_key.json`     which keys are planted and what the graph really says (QA only, never shown to the agent)

`--companies` (map of company_id to Company Enrich response) is optional; without it the company_stage lie isn't planted.
`check_fakes.py` runs WS3's verifier offline and prints CAUGHT / MISSED / FALSE POSITIVE per lie (exit 1 on any failure).
`show_fake.py <slug>.person.json --companies ...` prints one resume and the verifier's verdict per claim, in colour (the video shot).

Results: on the 5 real Person Enrich fixtures from WS1, 10 planted lies across all 7 lie types were all caught, with 0 false positives.
On WS3's dev fixtures it also passes.

**The repo is public: never commit `out/` (it holds real people's records). It's gitignored.** Generate the fakes on the demo machine from the local cache.

## The lie types (each maps to a check the verifier already does)
| Type | Example planted claim | Graph field that disproves it |
|---|---|---|
| `inflated_title` | "Staff Engineer" when profile says "Software Engineer" | current title |
| `fake_employer` | Claims to work at a famous company that isn't in the employment history | current employer |
| `inflated_experience` | Total years of experience +5 | earliest role start date |
| `company_stage` | "Seed-stage startup" for a Series C+ company, or "Series D" for a small one | Company Enrich stage / headcount |
| `stretched_tenure` | Start date moved 2 years earlier | employer start date |
| `stale_current_job` | Still claims old employer as current after a job change | current employer (freshness!) |
| `wrong_location` | Claims a different city | location |

`stale_current_job` is the sponsor-pleasing one: Crustdata knows about the job change even if the resume doesn't.

## Pass bar
- Every planted claim -> `contradicted`, with `source.endpoint = person/enrich` and the field.
- No true claim marked contradicted (false positives lose more trust than misses).
