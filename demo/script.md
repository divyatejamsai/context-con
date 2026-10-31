# 2-minute demo video script (draft v1, finalize at 14:00 once the UI is live)

Target: 1:55. Screen recording of the UI + voiceover. Record at 1080p, browser zoom 110-125% so text is readable.
Uses brief **B1** from `briefs.md` (pre-cached, so replay mode is the backup).

| Time | On screen | Say (roughly) |
|---|---|---|
| 0:00-0:12 | Title card or empty UI | "Recruiting firms get paid per hire, but half of what's on a profile is stale or inflated. We built an agent that does the recruiter's job end to end, and proves every claim it makes using Crustdata." |
| 0:12-0:25 | Paste the messy B1 brief, hit Run | "Here's a brief exactly as a hiring manager would type it: abbreviations, 'blr', 'not big tech lifers'. No form, no human in the loop from here." |
| 0:25-0:50 | Live step feed: parsed criteria, title variants, search counts, enrich progress | "It turns the brief into criteria, expands the title, because a payments backend engineer might be called SDE-3 or Platform Engineer, and searches Crustdata's people graph with each variant. Then it enriches every candidate and their company." (If an auto-broaden or retry event appears, point at it: "zero results, so it relaxes a constraint by itself.") |
| 0:50-1:20 | Shortlist appears. Open the top candidate. Hover a claim's source | "Every line here is a claim with a status and a source: this employer and start date come from Person Enrich, company stage from Company Enrich. Nothing is shown without a citation. And look: Crustdata shows this person changed jobs three weeks ago, which their profile summary doesn't say yet." |
| 1:20-1:40 | Seeded-fake resume run (or a candidate with a red Contradicted badge) | "We also fed it resumes with planted lies. It caught the inflated title and the employer they left, marked them Contradicted, and shows the field that disproves them. Things it can't check, like notice period, say Unverifiable instead of guessing." |
| 1:40-1:50 | Outreach draft panel | "For the top picks it drafts a personal note citing why they fit. Drafted, never sent." |
| 1:50-1:58 | Back to shortlist | "Messy brief in, verified, cited shortlist out, no human involved. Built on Crustdata." |

## Recording checklist
- [ ] `CRUSTDATA_MODE=cache` with B1 already run once (fast + same results). Have `replay` ready if wifi drops.
- [ ] Clear old runs from the UI; close other tabs and notifications (macOS Focus mode on).
- [ ] Record with QuickTime (File > New Screen Recording) or `Cmd+Shift+5`, mic on. Or record silent and voice over after.
- [ ] Do one full dry run with a timer before the real take. If over 2:00, cut the outreach beat first.
- [ ] Trim in QuickTime (`Cmd+T`), export 1080p, check the file plays, upload by 15:15.

## If something breaks during recording
- Pipeline slow: speed up the step-feed section 1.5-2x in the edit and say "sped up".
- Seeded fakes not built: skip 1:20-1:40 and show any real Contradicted / Unverifiable claim instead.
- Live API down: switch to replay mode, say nothing different. The data is real, just cached.
