# Frontend (WS4: web UI)

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
