"use client";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Play, Radio, RotateCcw, ShieldCheck, Square, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { PipelineBar, StepFeed, type FeedItem } from "@/components/step-feed";
import { CandidateCard, countClaims } from "@/components/candidate-card";
import { CandidateDrawer } from "@/components/candidate-drawer";
import { API_URL, streamRun, type RunMode } from "@/lib/stream";
import { canonicalStep, type Candidate, type Criteria, type RunEvent, type Summary } from "@/lib/types";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "need a senior backend eng, payments exp, Bangalore, ex-startup, can start soon",
  "founding ML engineer for a seed-stage fintech in Mumbai, LLM + ranking experience",
  "head of growth, B2B SaaS, has scaled 0→1, remote india ok",
];

interface State {
  running: boolean;
  feed: FeedItem[];
  currentStep?: string;
  criteria?: Criteria;
  candidates: Record<string, Candidate>;
  summary?: Summary;
  order?: string[];
  done: boolean;
  fatal?: string;
}

type Action = { type: "start" } | { type: "event"; ev: RunEvent } | { type: "fatal"; message: string } | { type: "stop" };

const initial: State = { running: false, feed: [], candidates: {}, done: false };

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "start":
      return { ...initial, running: true };
    case "stop":
      return { ...s, running: false };
    case "fatal":
      return { ...s, running: false, fatal: a.message };
    case "event": {
      const ev = a.ev;
      const at = Date.now();
      switch (ev.type) {
        case "step": {
          const step = canonicalStep(ev.step);
          return {
            ...s,
            currentStep: step,
            criteria: ev.data?.criteria ?? s.criteria,
            order: Array.isArray(ev.data?.order) ? ev.data.order : s.order,
            feed: [...s.feed, { kind: "step", step, message: ev.message, at }],
          };
        }
        case "error":
          return { ...s, feed: [...s.feed, { kind: "error", step: canonicalStep(ev.step), message: ev.message, at }] };
        case "criteria":
          return { ...s, criteria: ev.criteria };
        case "candidate": {
          const c = ev.candidate;
          if (!c?.id) return s;
          // Later events for the same id (e.g. after verify/rank) merge over earlier ones.
          return { ...s, candidates: { ...s.candidates, [c.id]: { ...s.candidates[c.id], ...c } } };
        }
        case "done":
          return {
            ...s,
            done: true,
            running: false,
            summary: ev.summary,
            feed: [...s.feed, { kind: "done", message: "Done", at }],
          };
        default:
          return s;
      }
    }
  }
}

export default function Home() {
  const [brief, setBrief] = useState(EXAMPLES[0]);
  const [mode, setMode] = useState<RunMode>(process.env.NEXT_PUBLIC_DEFAULT_MODE === "live" ? "live" : "replay");
  const [state, dispatch] = useReducer(reducer, initial);
  const [openId, setOpenId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const m = new URLSearchParams(window.location.search).get("mode");
    if (m === "live" || m === "replay") setMode(m);
  }, []);

  const run = useCallback(async () => {
    if (!brief.trim()) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setOpenId(null);
    dispatch({ type: "start" });
    try {
      for await (const ev of streamRun(brief, mode, ctrl.signal)) dispatch({ type: "event", ev });
      dispatch({ type: "stop" });
    } catch (e) {
      if (ctrl.signal.aborted) return dispatch({ type: "stop" });
      const msg = e instanceof Error ? e.message : String(e);
      dispatch({
        type: "fatal",
        message: mode === "live" ? `Could not reach the agent at ${API_URL} (${msg}).` : msg,
      });
    }
  }, [brief, mode]);

  const stop = () => {
    abortRef.current?.abort();
    dispatch({ type: "stop" });
  };

  // Backend's final rank order wins when present; otherwise sort by score.
  const ranked = useMemo(() => {
    const pos = new Map((state.order ?? []).map((id, i) => [id, i]));
    return Object.values(state.candidates).sort(
      (a, b) => (pos.get(a.id) ?? 1e9) - (pos.get(b.id) ?? 1e9) || (b.score ?? -1) - (a.score ?? -1),
    );
  }, [state.candidates, state.order]);
  const totals = useMemo(
    () =>
      ranked.reduce(
        (t, c) => {
          const k = countClaims(c);
          return { verified: t.verified + k.verified, contradicted: t.contradicted + k.contradicted, unverifiable: t.unverifiable + k.unverifiable };
        },
        { verified: 0, contradicted: 0, unverifiable: 0 },
      ),
    [ranked],
  );
  const open = openId ? state.candidates[openId] ?? null : null;
  const started = state.running || state.feed.length > 0 || state.fatal;

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:py-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <ShieldCheck className="size-6 text-primary" /> Brief to Shortlist
          </h1>
          <p className="text-sm text-muted-foreground">
            Paste any hiring brief. The agent searches Crustdata, checks every claim, and cites a source for each one.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-1 text-xs" role="radiogroup" aria-label="Data source">
          {(["replay", "live"] as const).map((m) => (
            <button
              key={m}
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              disabled={state.running}
              className={cn("rounded-md px-2.5 py-1 font-medium", mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}
            >
              {m === "replay" ? "Replay" : (
                <span className="inline-flex items-center gap-1">
                  <Radio className="size-3" /> Live
                </span>
              )}
            </button>
          ))}
        </div>
      </header>

      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <Textarea
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && run()}
            placeholder="e.g. need a senior backend eng, payments exp, Bangalore, ex-startup, can start soon"
            disabled={state.running}
            rows={3}
            className="text-base"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => setBrief(ex)}
                  disabled={state.running}
                  className="max-w-64 truncate rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
                  title={ex}
                >
                  {ex}
                </button>
              ))}
            </div>
            {state.running ? (
              <Button variant="outline" onClick={stop}>
                <Square /> Stop
              </Button>
            ) : (
              <Button onClick={run} disabled={!brief.trim()}>
                {state.done ? <RotateCcw /> : <Play />} {state.done ? "Run again" : "Find candidates"}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {state.fatal && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-contradicted/40 bg-contradicted/5 px-4 py-3 text-sm">
          <span>{state.fatal}</span>
          {mode === "live" && (
            <Button size="sm" variant="outline" onClick={() => setMode("replay")}>
              Switch to replay
            </Button>
          )}
        </div>
      )}

      {started && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
          <aside className="flex flex-col gap-4 lg:sticky lg:top-6 lg:self-start">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Agent activity</CardTitle>
                <PipelineBar current={state.currentStep} done={state.done} />
              </CardHeader>
              <CardContent className="max-h-[50vh] overflow-y-auto">
                <StepFeed items={state.feed} running={state.running} />
              </CardContent>
            </Card>
            {state.criteria && <CriteriaCard criteria={state.criteria} />}
          </aside>

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 font-semibold">
                <Users className="size-4" /> Shortlist
                <span className="text-sm font-normal text-muted-foreground">{ranked.length}</span>
              </h2>
              <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                {state.summary &&
                  Object.entries(state.summary).map(([k, v]) => (
                    <span key={k}>
                      <span className="font-semibold tabular-nums text-foreground">{v}</span> {k}
                    </span>
                  ))}
                {ranked.length > 0 && (
                  <span>
                    <span className="font-semibold text-verified">{totals.verified}</span> verified ·{" "}
                    <span className="font-semibold text-contradicted">{totals.contradicted}</span> contradicted ·{" "}
                    <span className="font-semibold">{totals.unverifiable}</span> unverifiable
                  </span>
                )}
              </div>
            </div>
            {ranked.length ? (
              <div className="grid gap-3 md:grid-cols-2">
                {ranked.map((c, i) => (
                  <CandidateCard key={c.id} candidate={c} rank={i + 1} onOpen={() => setOpenId(c.id)} />
                ))}
              </div>
            ) : (
              <Card className="grid place-items-center p-10 text-center text-sm text-muted-foreground">
                {state.running
                  ? "Candidates appear here as soon as they're verified."
                  : state.done
                    ? "No candidates matched. Try a broader brief (fewer must-haves, wider location)."
                    : "No candidates yet."}
              </Card>
            )}
          </section>
        </div>
      )}

      <CandidateDrawer candidate={open} onClose={() => setOpenId(null)} />
    </main>
  );
}

function CriteriaCard({ criteria: c }: { criteria: Criteria }) {
  const rows: [string, string[] | undefined][] = [
    ["Titles", c.title_variants],
    ["Skills", c.skills],
    ["Locations", c.locations],
    ["Companies", c.company_preferences],
    ["Must have", c.must_haves],
    ["Nice to have", c.nice_to_haves],
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">What the agent understood</CardTitle>
        {c.role && (
          <p className="text-sm">
            {c.role}
            {c.seniority && <span className="text-muted-foreground"> · {c.seniority}</span>}
          </p>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {rows
          .filter(([, v]) => v?.length)
          .map(([label, v]) => (
            <div key={label} className="flex flex-wrap items-center gap-1">
              <span className="w-24 shrink-0 text-xs text-muted-foreground">{label}</span>
              {v!.map((x) => (
                <Badge key={x} variant="outline">
                  {x}
                </Badge>
              ))}
            </div>
          ))}
      </CardContent>
    </Card>
  );
}
