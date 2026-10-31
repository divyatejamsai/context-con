# Frontend (WS4: web UI) · "Dossier"

Next.js 15 + Tailwind 4 + shadcn-style components (`src/components/ui`, hand-written; `components.json` is set up so `npx shadcn add ...` works later).

```bash
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                     # http://localhost:3000
```

- **Replay** (default): `/api/replay` streams `frontend/fixtures/run.jsonl` (or `FIXTURE_PATH`, or `../fixtures/run.jsonl`) as SSE with realistic pacing. `?speed=2` doubles it. No backend needed: demo safety net.
- **Live**: toggle top-right, or open `/?mode=live`. POSTs `{brief}` to `$NEXT_PUBLIC_API_URL/api/run` and reads the SSE stream.

Event handling (contract in CONTEXT.md section 6):
- `step` with `data.criteria` fills "What the agent understood"; `data.order` sets the final shortlist order (otherwise sorted by score).
- `candidate` events with the same `id` merge, so the backend can send a partial card and update it.
- Claims with no `source.endpoint` are shown as Unverifiable. Contradicted claims sort first in the drawer.
- Accepts both SSE `data:` frames and plain NDJSON lines; unknown event types are ignored.

## What's in the UI
- **Hero** with a big brief box and example briefs (including a deliberately messy one). ⌘↵ runs it.
- **Three panes on wide screens:** the agent trace on the left (pipeline stepper with per-step timings, counts, warnings, and a timestamped log), the ranked shortlist in the middle, and the selected candidate's dossier on the right. Below 1280px the dossier opens as a drawer.
- **Dossier:** fit score, flags, reasons with footnote citations that jump to the claim, an evidence ledger where each claim has a stamp (verified, contradicted or unverifiable) and its Crustdata source, and an editable outreach draft marked "not sent".
- **Evidence strip:** one tick per claim on every row, so contradictions are visible without opening anything.
- **Compare view:** a sortable table by rank, fit, % verified or contradictions.
- **Triage:** pin (p), pass (x), hide contradicted (h). Pinned candidates float to the top and passed ones sink.
- **Export:** a Markdown report with every claim and its source, plus CSV and JSON. Passed candidates are left out, and edited drafts are kept.
- **Keyboard:** j/k move, c copy outreach, v toggle compare, / edit brief, ? shows all shortcuts.

Fonts (Fraunces, IBM Plex Sans and Mono) are bundled through @fontsource, so the app works offline.
