# Frontend (WS4: web UI) · "Dossier"

Next.js 15 + Tailwind 4 + shadcn-style components (`src/components/ui`, hand-written; `components.json` is set up so `npx shadcn add ...` works later).

```bash
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                     # http://localhost:3000
```

- **Live** (default): POSTs `{brief}` to `$NEXT_PUBLIC_API_URL/api/run` and reads the SSE stream. If `NEXT_PUBLIC_AGENT_ID` is set, it calls `/api/agents/{id}/run` instead, so the run happens under that agent's Agaxes passport: a `passport` step gates the run, a `guard` step checks each shortlisted draft, and candidates carry a `guard` verdict shown as a Cleared / Blocked badge.
- **Replay** (fallback): toggle top-right, or open `/?mode=replay`. `/api/replay` streams `frontend/fixtures/run.jsonl` (or `FIXTURE_PATH`, or `../fixtures/run.jsonl`) as SSE with realistic pacing. `?speed=2` doubles it. No backend needed, and it is labelled as a sample run. Set `NEXT_PUBLIC_DEFAULT_MODE=replay` to start in it.

Event handling (contract in CONTEXT.md section 6):
- `step` with `data.criteria` fills "What the agent understood"; `data.order` sets the final shortlist order (otherwise sorted by score).
- `candidate` events with the same `id` merge, so the backend can send a partial card and update it.
- Claims with no `source.endpoint` are shown as Unverifiable. Contradicted claims sort first in the drawer.
- Accepts both SSE `data:` frames and plain NDJSON lines; unknown event types are ignored.

## What's in the UI
- **Shortlist tiers:** if the final `rank` step carries `data.shortlist` / `data.near_miss`, the shortlist is the main list, near misses sit in a collapsed section, and everyone else goes in a greyed "Below the bar" section. Without those fields, everyone is shortlisted.
- **Start screen:** one question, a brief box and example briefs (including a deliberately messy one). ⌘↵ runs it.
- **Three panes on wide screens:** the agent trace on the left (pipeline stepper with per-step timings, counts, warnings, and a timestamped log), the ranked shortlist in the middle, and the selected candidate's dossier on the right. Below 1280px the dossier opens as a drawer.
- **Dossier:** fit score, flags, reasons with footnote citations that jump to the claim, an evidence ledger where each claim has a stamp (verified, contradicted or unverifiable) and its Crustdata source, and an editable outreach draft marked "not sent".
- **Evidence strip:** one tick per claim on every row, so contradictions are visible without opening anything.
- **Compare view:** a sortable table by rank, fit, % verified or contradictions.
- **Triage:** pin (p), pass (x), hide contradicted (h). Pinned candidates float to the top and passed ones sink.
- **Export:** a Markdown report with every claim and its source, plus CSV and JSON. Passed candidates are left out, and edited drafts are kept.
- **Keyboard:** j/k move, c copy outreach, v toggle compare, / edit brief, ? shows all shortcuts.

Visual system: a Vercel / Attio-style look. It's light by default with a dark toggle in the top bar, white surfaces, hairline grey borders and one blue accent for selection, focus and links. Green, red and amber only ever mean verified, contradicted and unverifiable or flagged. There are no gradients, glows or decorative icons. Type is Geist Sans with Geist Mono for endpoints, ids and timings, bundled through the `geist` package so the app works offline.
