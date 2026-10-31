"use client";
// Guided demo: plays /api/demo/run (backend/app/fleet/demo.py) beat by beat, with every verdict and its sources.
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, ChevronDown, FileText, IdCard, KeyRound, Link2, Loader2, Play, RotateCcw, Send, ShieldCheck, ShieldX, Square, UserRound, X } from "lucide-react";
import { API_URL } from "@/lib/stream";
import { cn } from "@/lib/utils";
import { getAdminToken, setAdminToken } from "../api";

type Src = { endpoint?: string; field?: string | null; url?: string | null } | null;
type Check = { id?: string; name: string; status: "pass" | "fail" | "unverifiable"; detail?: string; source?: Src };
type Who = { name?: string; profile_url?: string | null; company?: string } | null;
type Beat = { n: number; id: string; title: string; narration: string };
type Ev =
  | ({ type: "start"; beats: Beat[]; modes?: Record<string, string> })
  | ({ type: "beat" } & Beat)
  | { type: "line"; n: number; text: string }
  | { type: "agent"; n: number; agent: string; role?: string; job?: string; runtime?: string; sponsor?: Who & { title?: string }; scopes?: string[]; status?: string; reason?: string | null }
  | { type: "draft"; n: number; agent: string; to?: Who; scope?: string; body: string }
  | { type: "verdict"; n: number; agent: string; action: string; decision: "allow" | "block"; headline: string; to?: Who; sent?: boolean | null; checks?: Check[]; ledger_entry?: string | null }
  | { type: "finding"; n: number; agent: string; candidate: string; profile_url?: string; verified: number; total: number; contradicted: { claim: string; evidence?: string; source?: Src }[] }
  | { type: "filed"; n: number; agent: string; kind: string; summary: string; ledger_entry?: string | null; sources?: Src[] }
  | { type: "artifact"; n: number; agent: string; kind?: string; title: string; content: string }
  | { type: "beat_done"; n: number; id: string; ok: boolean; summary: string }
  | { type: "done"; ok: boolean; chain_ok: boolean; entries: number; scorecard: Score[] }
  | { type: "error"; n?: number; message: string };
type Score = { agent: string; status: string; messages_checked?: number; allowed?: number; blocked?: number; sponsor_checks?: number; sponsor_checks_failed?: number; work_filed?: number };
type Phase = "idle" | "running" | "done" | "failed";

const ACTION: Record<string, string> = {
  clock_in: "Clock-in check",
  send: "Send Guard",
  payroll: "Payroll re-check",
  ledger_audit: "Ledger audit",
};

// Same SSE / NDJSON tolerance as lib/stream.ts.
async function* events(url: string, token: string, signal: AbortSignal): AsyncGenerator<Ev> {
  const res = await fetch(url, { headers: token ? { "x-admin-token": token } : {}, signal });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    throw Object.assign(new Error(body?.detail ?? `Backend returned ${res.status}`), { status: res.status });
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let i: number;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      const raw = line.startsWith("data:") ? line.slice(5).trim() : line.startsWith("{") ? line : "";
      if (!raw) continue;
      try {
        yield JSON.parse(raw) as Ev;
      } catch {}
    }
  }
}

export default function DemoPage() {
  const [beats, setBeats] = useState<Beat[]>([]);
  const [evs, setEvs] = useState<Ev[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<{ message: string; status?: number } | null>(null);
  const [view, setView] = useState(1); // beat number on screen; 8 = results
  const [pause, setPause] = useState(true);
  const [claude, setClaude] = useState(false);
  const [needToken, setNeedToken] = useState(false);
  const [token, setToken] = useState("");
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    setToken(getAdminToken());
    fetch(`${API_URL}/api/demo/beats`)
      .then((r) => {
        if (r.status === 404) throw new Error(`The backend at ${API_URL} has no guided demo yet. Update it to the latest main and restart it.`);
        return r.ok ? r.json() : Promise.reject(new Error(`Backend returned ${r.status}`));
      })
      .then((b: Beat[]) => setBeats(b))
      .catch((e) =>
        setError({ message: e instanceof Error && e.message !== "Failed to fetch" ? e.message : `Can't reach the backend at ${API_URL}. Start it with backend/scripts/demo_up.sh, then reload.` }),
      );
  }, []);

  const start = useCallback(async () => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setEvs([]);
    setError(null);
    setNeedToken(false);
    setView(1);
    setPhase("running");
    try {
      const url = `${API_URL}/api/demo/run?claude_code=${claude}`;
      for await (const ev of events(url, getAdminToken(), ctrl.signal)) {
        if (ev.type === "start" && ev.beats?.length) setBeats(ev.beats);
        setEvs((xs) => [...xs, ev]);
      }
      setPhase("done");
    } catch (e) {
      if (ctrl.signal.aborted) return setPhase("idle");
      const status = (e as { status?: number }).status;
      if (status === 401) setNeedToken(true);
      setError({
        status,
        message:
          status === 401
            ? "This backend asks for an admin token before it runs the demo, because the demo writes to the registry and ledger."
            : status === 409
              ? "A demo is already running on this backend. Wait for it to finish, then start again."
              : e instanceof Error && e.message !== "Failed to fetch"
                ? e.message
                : `Can't reach the backend at ${API_URL}.`,
      });
      setPhase("failed");
    }
  }, [claude]);

  const byBeat = useMemo(() => {
    const m = new Map<number, Ev[]>();
    for (const e of evs) {
      const n = "n" in e && typeof e.n === "number" ? e.n : 0;
      if (!m.has(n)) m.set(n, []);
      m.get(n)!.push(e);
    }
    return m;
  }, [evs]);
  const doneEv = evs.find((e): e is Extract<Ev, { type: "done" }> => e.type === "done");
  const beatDone = (n: number) => byBeat.get(n)?.find((e): e is Extract<Ev, { type: "beat_done" }> => e.type === "beat_done");
  const reached = Math.max(0, ...evs.filter((e) => e.type === "beat").map((e) => (e as Beat).n));

  // Without pause, follow the stream. With pause, the viewer presses Next.
  useEffect(() => {
    if (!pause && reached) setView(doneEv ? 8 : reached);
  }, [pause, reached, doneEv]);

  const total = beats.length || 7;
  const canNext = view < total ? reached > view || !!doneEv : !!doneEv;
  const cur = beats.find((b) => b.n === view);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur-xl">
        <div className="mx-auto flex h-12 max-w-[1280px] items-center gap-1.5 px-4">
          <Link href="/console" className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12.5px] text-muted-foreground hover:bg-elevated hover:text-foreground">
            <ArrowLeft className="size-3.5" /> Countersign console
          </Link>
          <span className="text-faint">/</span>
          <span className="flex items-center gap-2 px-1">
            <IdCard className="size-4 text-primary" />
            <span className="text-[14px] font-[590]">Guided demo</span>
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-[1280px] px-4 pb-24 pt-8">
        <div className="max-w-[720px]">
          <h1 className="text-[26px] font-[590] tracking-[-0.02em]">See Countersign handle seven real situations</h1>
          <p className="mt-2 text-[14px] leading-relaxed text-muted-foreground">
            Six AI employees each work for a named person. Press <span className="font-[510] text-foreground">Start demo</span> and the backend runs them through seven situations, from normal work to a sponsor who has left, a forged passport and an edited ledger. For every action you see what the agent tried, Countersign&apos;s decision, and the Crustdata record that decided it.
          </p>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3 rounded-lg border border-border bg-panel px-4 py-3">
          {phase === "running" ? (
            <button
              onClick={() => abort.current?.abort()}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-elevated px-3 text-[13px] font-[510] hover:bg-hover"
              title="Stop reading the stream. Steps already shown stay on screen."
            >
              <Square className="size-3 fill-current" /> Stop
            </button>
          ) : (
            <button
              onClick={start}
              disabled={!beats.length && !!error && !needToken}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-foreground px-3 text-[13px] font-[510] text-background hover:opacity-85 disabled:opacity-40"
              title="Runs the seven situations on the backend. It onboards agents and writes to the ledger."
            >
              {evs.length ? <RotateCcw className="size-3.5" /> : <Play className="size-3.5" />} {evs.length ? "Run it again" : "Start demo"}
            </button>
          )}
          <Toggle checked={pause} onChange={setPause} label="Pause after each step" hint="Press Next to move on. Turn off to follow along live." />
          <Toggle
            checked={claude}
            onChange={setClaude}
            disabled={phase === "running"}
            label="Include Claude Code"
            hint="An outside agent that only has the Countersign MCP server. Adds about 20 seconds."
          />
          <span className="ml-auto text-[12px] text-faint">
            {phase === "running" ? (
              <span className="inline-flex items-center gap-1.5"><Loader2 className="size-3.5 animate-spin" /> Running step {reached || 1} of {total}</span>
            ) : doneEv ? (
              "Finished. Every decision is on the ledger."
            ) : (
              "Takes about 5 seconds on recorded data."
            )}
          </span>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-contradicted/30 bg-contradicted/[0.06] px-4 py-3 text-[13px]">
            <p className="text-secondary">{error.message}</p>
            {needToken && (
              <form
                className="mt-2 flex flex-wrap items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  setAdminToken(token.trim());
                  start();
                }}
              >
                <KeyRound className="size-4 text-muted-foreground" />
                <input
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="COUNTERSIGN_ADMIN_TOKEN"
                  type="password"
                  className="h-8 w-64 rounded-md border border-border-strong bg-panel px-2.5 font-mono text-[12px] focus:border-primary/60 focus:outline-none"
                />
                <button className="h-8 rounded-md bg-foreground px-3 text-[12.5px] font-[510] text-background hover:opacity-85">Save and start</button>
                <span className="text-[12px] text-muted-foreground">Kept in this browser only.</span>
              </form>
            )}
          </div>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <nav aria-label="Demo steps" className="lg:sticky lg:top-20 lg:self-start">
            <ol className="flex gap-1 max-lg:overflow-x-auto lg:flex-col">
              {(beats.length ? beats : Array.from({ length: 7 }, (_, i) => ({ n: i + 1, id: String(i), title: "…", narration: "" }))).map((b) => {
                const d = beatDone(b.n);
                const live = phase === "running" && reached === b.n && !d;
                const got = b.n <= reached;
                return (
                  <li key={b.n} className="shrink-0">
                    <button
                      onClick={() => got && setView(b.n)}
                      title={b.title}
                      disabled={!got}
                      className={cn(
                        "flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left transition",
                        view === b.n ? "bg-elevated shadow-[inset_0_0_0_1px_var(--border-strong)]" : got ? "hover:bg-hover" : "cursor-default",
                      )}
                    >
                      <span
                        className={cn(
                          "mt-px grid size-5 shrink-0 place-items-center rounded-full border font-mono text-[10.5px]",
                          d ? (d.ok ? "border-verified/40 bg-verified/10 text-verified" : "border-contradicted/40 bg-contradicted/10 text-contradicted") : live ? "border-primary/50 text-primary" : "border-border-strong text-faint",
                        )}
                      >
                        {d ? (d.ok ? <Check className="size-3" /> : <X className="size-3" />) : live ? <Loader2 className="size-3 animate-spin" /> : b.n}
                      </span>
                      <span className="min-w-0 max-lg:hidden">
                        <span className={cn("block text-[13px] font-[510]", !got && "text-muted-foreground")}>{b.title}</span>
                        {d && <span className="block text-[11.5px] text-faint">{d.summary}</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
              <li className="shrink-0">
                <button
                  onClick={() => doneEv && setView(8)}
                  title="Results and ledger"
                  disabled={!doneEv}
                  className={cn("flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left", view === 8 ? "bg-elevated shadow-[inset_0_0_0_1px_var(--border-strong)]" : doneEv ? "hover:bg-hover" : "cursor-default")}
                >
                  <span className={cn("grid size-5 place-items-center rounded-full border", doneEv ? "border-verified/40 text-verified" : "border-border-strong text-faint")}>
                    <Link2 className="size-3" />
                  </span>
                  <span className={cn("text-[13px] font-[510] max-lg:hidden", !doneEv && "text-muted-foreground")}>Results and ledger</span>
                </button>
              </li>
            </ol>
          </nav>

          <section className="min-w-0">
            {!evs.length ? (
              <Intro beats={beats} />
            ) : view === 8 && doneEv ? (
              <Results done={doneEv} />
            ) : cur ? (
              <BeatView beat={cur} evs={byBeat.get(cur.n) ?? []} done={beatDone(cur.n)} waiting={phase === "running" && reached < cur.n} />
            ) : null}

            {evs.length > 0 && (
              <div className="mt-6 flex items-center justify-between gap-3 border-t border-border pt-4">
                <button
                  onClick={() => setView((v) => Math.max(1, v - 1))}
                  disabled={view <= 1}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-panel px-3 text-[13px] font-[510] hover:bg-hover disabled:opacity-40"
                >
                  <ArrowLeft className="size-3.5" /> Back
                </button>
                {view < 8 && (
                  <button
                    onClick={() => setView((v) => Math.min(8, v + 1))}
                    disabled={!canNext}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md bg-foreground px-3 text-[13px] font-[510] text-background hover:opacity-85 disabled:opacity-40"
                    title={canNext ? undefined : "The next step is still running"}
                  >
                    {view < total ? `Next: ${beats.find((b) => b.n === view + 1)?.title ?? "next step"}` : "See the results"} <ArrowRight className="size-3.5" />
                  </button>
                )}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

function Toggle({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint: string; disabled?: boolean }) {
  return (
    <label className={cn("flex cursor-pointer items-start gap-2", disabled && "cursor-not-allowed opacity-50")} title={hint}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 size-3.5 accent-[var(--primary)]" />
      <span className="text-[12.5px] leading-tight">
        <span className="font-[510]">{label}</span>
        <span className="block text-[11.5px] text-muted-foreground">{hint}</span>
      </span>
    </label>
  );
}

function Intro({ beats }: { beats: Beat[] }) {
  return (
    <div className="rounded-lg border border-dashed border-border-strong p-6">
      <p className="text-[14px] font-[590]">What you&apos;ll see</p>
      <ol className="mt-3 space-y-3">
        {beats.map((b) => (
          <li key={b.n} className="flex gap-3">
            <span className="mt-0.5 font-mono text-[11px] text-faint">{b.n}</span>
            <span className="text-[13px] leading-relaxed">
              <span className="font-[510]">{b.title}.</span> <span className="text-muted-foreground">{b.narration}</span>
            </span>
          </li>
        ))}
        {!beats.length && <li className="text-[13px] text-faint">Loading the steps from the backend…</li>}
      </ol>
    </div>
  );
}

function BeatView({ beat, evs, done, waiting }: { beat: Beat; evs: Ev[]; done?: Extract<Ev, { type: "beat_done" }>; waiting: boolean }) {
  const agents = evs.filter((e): e is Extract<Ev, { type: "agent" }> => e.type === "agent");
  const lines = evs.filter((e): e is Extract<Ev, { type: "line" }> => e.type === "line");
  const errs = evs.filter((e): e is Extract<Ev, { type: "error" }> => e.type === "error");
  // Pair each draft with the verdict that follows it.
  const items: React.ReactNode[] = [];
  let draft: Extract<Ev, { type: "draft" }> | null = null;
  evs.forEach((e, i) => {
    if (e.type === "draft") draft = e;
    else if (e.type === "verdict") {
      items.push(<VerdictCard key={i} v={e} draft={e.action === "send" ? draft : null} />);
      draft = null;
    } else if (e.type === "finding") items.push(<FindingCard key={i} f={e} />);
    else if (e.type === "filed") items.push(<FiledCard key={i} f={e} />);
    else if (e.type === "artifact") items.push(<ArtifactCard key={i} a={e} />);
  });

  return (
    <div className="animate-fade">
      <p className="font-mono text-[11px] text-faint">Step {beat.n}</p>
      <h2 className="mt-1 text-[20px] font-[590] tracking-[-0.015em]">{beat.title}</h2>
      <p className="mt-1.5 max-w-[720px] text-[13.5px] leading-relaxed text-muted-foreground">{beat.narration}</p>
      {done && (
        <p className={cn("mt-3 inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12.5px] font-[510]", done.ok ? "border-verified/30 bg-verified/10 text-verified" : "border-contradicted/30 bg-contradicted/10 text-contradicted")}>
          {done.ok ? <Check className="size-3.5" /> : <X className="size-3.5" />} {done.ok ? "Worked as intended" : "Did not go as intended"}: {done.summary}
        </p>
      )}

      {waiting && <p className="mt-6 inline-flex items-center gap-2 text-[13px] text-faint"><Loader2 className="size-4 animate-spin" /> Waiting for this step to start…</p>}

      {agents.length > 0 && (
        <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((a, i) => (
            <div key={i} className="rounded-lg border border-border bg-panel p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[13.5px] font-[590]">{a.agent}</span>
                <span className={cn("rounded-full border px-1.5 text-[10.5px] font-[510]", a.status === "active" ? "border-verified/30 text-verified" : "border-contradicted/30 text-contradicted")}>{a.status}</span>
              </div>
              <p className="text-[12px] text-muted-foreground">{a.role}{a.runtime === "external" ? " · outside agent" : ""}</p>
              {a.sponsor?.name && (
                <p className="mt-1.5 flex items-center gap-1 text-[12px]">
                  <UserRound className="size-3 text-faint" /> Acts for <span className="font-[510]">{a.sponsor.name}</span>
                  <span className="truncate text-faint">· {a.sponsor.title ? `${a.sponsor.title}, ` : ""}{a.sponsor.company}</span>
                </p>
              )}
              {!!a.scopes?.length && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {a.scopes.map((s) => <span key={s} className="rounded border border-border-strong px-1 font-mono text-[10.5px] text-muted-foreground">{s}</span>)}
                </div>
              )}
              {a.reason && <p className="mt-1.5 text-[11.5px] text-contradicted">{a.reason}</p>}
            </div>
          ))}
        </div>
      )}

      {items.length > 0 && <div className="mt-5 flex flex-col gap-3">{items}</div>}

      {errs.map((e, i) => <p key={i} className="mt-3 rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[13px] text-contradicted">{e.message}</p>)}

      {lines.length > 0 && (
        <details className="group mt-5 rounded-lg border border-border">
          <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-[12.5px] font-[510] text-muted-foreground">
            Raw log · {lines.length} lines <ChevronDown className="size-4 transition group-open:rotate-180" />
          </summary>
          <pre className="max-h-72 overflow-auto border-t border-border px-3 py-2 font-mono text-[11px] leading-relaxed text-muted-foreground">{lines.map((l) => l.text).join("\n")}</pre>
        </details>
      )}
    </div>
  );
}

function SourceChip({ s }: { s?: Src }) {
  if (!s?.endpoint) return <span className="text-[11px] text-faint">no source</span>;
  const body = (
    <span className="inline-flex max-w-full items-center gap-1 truncate rounded border border-border-strong bg-elevated px-1.5 font-mono text-[10.5px] text-muted-foreground">
      {s.endpoint}
      {s.field && <span className="truncate text-faint">.{s.field}</span>}
    </span>
  );
  return s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="max-w-full hover:underline">{body}</a> : body;
}

function CheckRow({ k }: { k: Check }) {
  return (
    <li className="flex flex-wrap items-start gap-x-2 gap-y-1 py-1">
      {k.status === "pass" ? <Check className="mt-0.5 size-3.5 shrink-0 text-verified" /> : <X className={cn("mt-0.5 size-3.5 shrink-0", k.status === "fail" ? "text-contradicted" : "text-unverifiable")} />}
      <span className="min-w-0 flex-1 text-[12.5px]">
        <span className="font-[510]">{k.name.replaceAll("_", " ")}</span>
        {k.detail && <span className="text-muted-foreground"> · {k.detail}</span>}
      </span>
      <SourceChip s={k.source} />
    </li>
  );
}

function VerdictCard({ v, draft }: { v: Extract<Ev, { type: "verdict" }>; draft: Extract<Ev, { type: "draft" }> | null }) {
  const ok = v.decision === "allow";
  const checks = v.checks ?? [];
  const bad = checks.filter((c) => c.status !== "pass");
  const good = checks.filter((c) => c.status === "pass");
  return (
    <article className="overflow-hidden rounded-lg border border-border bg-panel">
      <header className={cn("flex items-start gap-2.5 border-b px-4 py-3", ok ? "border-verified/20 bg-verified/[0.05]" : "border-contradicted/20 bg-contradicted/[0.05]")}>
        {ok ? <ShieldCheck className="mt-0.5 size-4 shrink-0 text-verified" /> : <ShieldX className="mt-0.5 size-4 shrink-0 text-contradicted" />}
        <div className="min-w-0 flex-1">
          <p className="text-[11.5px] text-muted-foreground">
            <span className="font-[510] text-foreground">{v.agent}</span> · {ACTION[v.action] ?? v.action}
            {v.to?.name && <> · to {v.to.name}{v.to.company ? ` (${v.to.company})` : ""}</>}
          </p>
          <p className={cn("mt-0.5 text-[13.5px] font-[590]", ok ? "text-verified" : "text-contradicted")}>
            {ok ? "Allowed" : "Blocked"}: <span className="font-[510] text-foreground">{v.headline}</span>
          </p>
        </div>
      </header>
      <div className="px-4 py-3">
        {draft && (
          <details className="group mb-3">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[12px] font-[510] text-muted-foreground">
              <Send className="size-3.5" /> The message it tried to send <ChevronDown className="size-3.5 transition group-open:rotate-180" />
            </summary>
            <p className="mt-2 whitespace-pre-wrap rounded-md border border-border bg-elevated px-3 py-2 text-[12.5px] leading-relaxed text-secondary">{draft.body}</p>
          </details>
        )}
        {bad.length > 0 && (
          <>
            <p className="text-[12px] font-[510] text-muted-foreground">Why it was blocked</p>
            <ul className="mt-0.5">{bad.map((k, i) => <CheckRow key={i} k={k} />)}</ul>
          </>
        )}
        {good.length > 0 && (
          <details className={cn("group", bad.length > 0 && "mt-2")}>
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[12px] font-[510] text-muted-foreground">
              {good.length} check{good.length > 1 ? "s" : ""} passed <ChevronDown className="size-3.5 transition group-open:rotate-180" />
            </summary>
            <ul className="mt-1">{good.map((k, i) => <CheckRow key={i} k={k} />)}</ul>
          </details>
        )}
        {v.ledger_entry && <p className="mt-2 font-mono text-[10.5px] text-faint">Recorded on the ledger · {v.ledger_entry.slice(0, 16)}</p>}
        {v.action === "send" && ok && <p className="mt-1 text-[11.5px] text-faint">Cleared messages go to the outbox file. Nothing reaches a real person during the event.</p>}
      </div>
    </article>
  );
}

function FindingCard({ f }: { f: Extract<Ev, { type: "finding" }> }) {
  return (
    <article className="rounded-lg border border-border bg-panel px-4 py-3">
      <p className="text-[11.5px] text-muted-foreground"><span className="font-[510] text-foreground">{f.agent}</span> · resume check</p>
      <p className="mt-0.5 text-[13.5px] font-[590]">
        {f.candidate}: {f.verified} of {f.total} claims verified
        {f.contradicted.length > 0 && <span className="text-contradicted"> · {f.contradicted.length} contradicted</span>}
      </p>
      {f.contradicted.length > 0 && (
        <ul className="mt-2 divide-y divide-border">
          {f.contradicted.map((c, i) => (
            <li key={i} className="py-1.5">
              <div className="flex flex-wrap items-start gap-x-2 gap-y-1">
                <X className="mt-0.5 size-3.5 shrink-0 text-contradicted" />
                <span className="min-w-0 flex-1 text-[12.5px]">
                  <span className="font-[510]">{c.claim}</span>
                  {c.evidence && <span className="block text-muted-foreground">{c.evidence}</span>}
                </span>
                <SourceChip s={c.source} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function FiledCard({ f }: { f: Extract<Ev, { type: "filed" }> }) {
  return (
    <article className="flex flex-wrap items-start gap-x-3 gap-y-1 rounded-lg border border-border bg-elevated px-4 py-2.5">
      <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <p className="text-[12.5px]">
          <span className="font-[510]">{f.agent}</span> filed its work: <span className="text-secondary">{f.summary}</span>
        </p>
        <p className="font-mono text-[10.5px] text-faint">
          {f.kind} · {f.sources?.length ?? 0} source{f.sources?.length === 1 ? "" : "s"}
          {f.ledger_entry && ` · ledger ${f.ledger_entry.slice(0, 12)}`}
        </p>
      </div>
    </article>
  );
}

function ArtifactCard({ a }: { a: Extract<Ev, { type: "artifact" }> }) {
  return (
    <details className="group rounded-lg border border-border bg-panel">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3">
        <span className="text-[13px]">
          <span className="font-[590]">{a.title}</span> <span className="text-muted-foreground">· written by {a.agent}</span>
        </span>
        <ChevronDown className="size-4 text-muted-foreground transition group-open:rotate-180" />
      </summary>
      <div className="border-t border-border px-4 py-3">
        <Markdown text={a.content} />
      </div>
    </details>
  );
}

// Small markdown subset: headings, bullets, bold, paragraphs. Enough for the agents' briefs.
function Markdown({ text }: { text: string }) {
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith("**") && p.endsWith("**") ? <strong key={i} className="font-[590] text-foreground">{p.slice(2, -2)}</strong> : p));
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) out.push(<ul key={out.length} className="my-1.5 list-disc space-y-0.5 pl-5">{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>);
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (/^\s*[-*] /.test(line)) { list.push(line.replace(/^\s*[-*] /, "")); continue; }
    flush();
    if (!line.trim()) continue;
    const h = line.match(/^(#{1,3}) (.*)/);
    if (h) out.push(<p key={out.length} className={cn("mt-3 font-[590] text-foreground first:mt-0", h[1].length === 1 ? "text-[15px]" : "text-[13.5px]")}>{inline(h[2])}</p>);
    else out.push(<p key={out.length} className="my-1">{inline(line)}</p>);
  }
  flush();
  return <div className="text-[12.5px] leading-relaxed text-secondary">{out}</div>;
}

function Results({ done }: { done: Extract<Ev, { type: "done" }> }) {
  return (
    <div className="animate-fade">
      <p className="font-mono text-[11px] text-faint">Results</p>
      <h2 className="mt-1 text-[20px] font-[590] tracking-[-0.015em]">What every agent was allowed to do</h2>
      <p className={cn("mt-3 inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12.5px] font-[510]", done.chain_ok ? "border-verified/30 bg-verified/10 text-verified" : "border-contradicted/30 bg-contradicted/10 text-contradicted")}>
        <Link2 className="size-3.5" /> {done.chain_ok ? `Ledger intact: all ${done.entries} entries link up` : "Ledger chain is broken"}
      </p>
      <div className="mt-4 overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[560px] text-[12.5px]">
          <thead className="bg-elevated text-left text-[11.5px] text-muted-foreground">
            <tr>
              {["Agent", "Status", "Messages checked", "Allowed", "Blocked", "Sponsor checks", "Work filed"].map((h) => <th key={h} className="px-3 py-2 font-[510]">{h}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {done.scorecard.map((s) => (
              <tr key={s.agent}>
                <td className="px-3 py-2 font-[510]">{s.agent}</td>
                <td className={cn("px-3 py-2", s.status === "active" ? "text-verified" : "text-contradicted")}>{s.status}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{s.messages_checked ?? 0}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{s.allowed ?? 0}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{s.blocked ?? 0}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{s.sponsor_checks ?? 0}{s.sponsor_checks_failed ? <span className="text-contradicted"> ({s.sponsor_checks_failed} failed)</span> : null}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{s.work_filed ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-4 text-[13px] text-muted-foreground">
        Open the{" "}
        <Link href="/console" className="text-primary hover:underline">Countersign console</Link>{" "}
        to see each agent&apos;s passport and full history, or{" "}
        <Link href="/" className="text-primary hover:underline">run Sourced</Link> yourself as one of these AI employees.
      </p>
    </div>
  );
}
