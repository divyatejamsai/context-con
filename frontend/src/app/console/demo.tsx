"use client";
// Guided demo: plays the backend's seven-beat story (backend/app/fleet/demo.py, GET /api/demo/run) as it happens.
// Every card on this page is an event from that stream: real agents, real Send Guard verdicts, real ledger entries.
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Check, ChevronDown, FileText, Loader2, Play, RotateCcw, Square, TerminalSquare } from "lucide-react";
import { API_URL } from "@/lib/stream";
import type { Source } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { AgentStatus, Check as CheckT, Scope, Scorecard, Sponsor } from "./api";
import { Button, CheckRow, DecisionBadge, RuntimeBadge, ScopeChip, SourceChip, StatusPill, cardCls, checkLabel } from "./parts";

// ---- stream types (mirror the docstring of backend/app/fleet/demo.py) ----------------------------

interface Beat { n: number; id: string; title: string; narration: string }
interface To { name: string; profile_url?: string; company?: string }
interface AgentEv { agent: string; agent_id: string; role: string; job?: string; runtime?: string; sponsor: Sponsor; scopes: Scope[]; status: AgentStatus; reason?: string | null; new?: boolean }
interface DraftEv { agent: string; agent_id?: string; to: To; scope: Scope; body: string }
interface VerdictEv {
  agent: string; agent_id?: string | null; action: "clock_in" | "send" | "payroll" | "ledger_audit"; decision: "allow" | "block";
  headline: string; to?: To | null; sent?: boolean | null; checks: Omit<CheckT, "id">[]; ledger_entry?: string | null;
}
interface FindingEv { agent: string; candidate: string; profile_url?: string; extracted_by?: string; verified: number; total: number; contradicted: { claim: string; evidence: string; source?: Source }[] }
interface FiledEv { agent: string; kind: string; summary: string; ledger_entry: string; sources: Source[] }
interface ArtifactEv { agent: string; kind: string; title: string; path: string; content: string }
interface DoneEv { ok: boolean; chain_ok: boolean; entries: number; scorecard: (Scorecard & { agent: string; agent_id: string; status: AgentStatus })[] }

type Item =
  | { k: "agents"; list: AgentEv[] }
  | { k: "exchange"; draft?: DraftEv; verdict?: VerdictEv }
  | { k: "finding"; e: FindingEv }
  | { k: "filed"; e: FiledEv }
  | { k: "artifact"; e: ArtifactEv };

interface BeatRun { items: Item[]; lines: string[]; started: boolean; done?: { ok: boolean; summary: string } }
type Phase = "idle" | "running" | "finished" | "error";

const ACTION: Record<VerdictEv["action"], string> = { clock_in: "Clock-in", send: "Message", payroll: "Payroll check", ledger_audit: "Ledger audit" };

/** Fold one stream event into the per-beat runs. Pure, so React state updates stay simple. */
function fold(runs: Record<number, BeatRun>, ev: Record<string, unknown> & { type: string; n?: number }): Record<number, BeatRun> {
  const n = ev.n;
  if (!n) return runs;
  const cur: BeatRun = runs[n] ?? { items: [], lines: [], started: false };
  const items = [...cur.items];
  const last = items[items.length - 1];
  switch (ev.type) {
    case "beat":
      return { ...runs, [n]: { ...cur, started: true } };
    case "line":
      return { ...runs, [n]: { ...cur, lines: [...cur.lines, String(ev.text)] } };
    case "agent":
      if (last?.k === "agents") items[items.length - 1] = { k: "agents", list: [...last.list, ev as unknown as AgentEv] };
      else items.push({ k: "agents", list: [ev as unknown as AgentEv] });
      break;
    case "draft":
      items.push({ k: "exchange", draft: ev as unknown as DraftEv });
      break;
    case "verdict": {
      const v = ev as unknown as VerdictEv;
      // A draft is sent just before its verdict: pair them into one card.
      if (last?.k === "exchange" && last.draft && !last.verdict && last.draft.agent === v.agent) items[items.length - 1] = { ...last, verdict: v };
      else items.push({ k: "exchange", verdict: v });
      break;
    }
    case "finding":
      items.push({ k: "finding", e: ev as unknown as FindingEv });
      break;
    case "filed":
      items.push({ k: "filed", e: ev as unknown as FiledEv });
      break;
    case "artifact":
      items.push({ k: "artifact", e: ev as unknown as ArtifactEv });
      break;
    case "beat_done":
      return { ...runs, [n]: { ...cur, started: true, done: { ok: !!ev.ok, summary: String(ev.summary ?? "") } } };
    case "error":
      return { ...runs, [n]: { ...cur, lines: [...cur.lines, `error: ${ev.message}`] } };
    default:
      return runs;
  }
  return { ...runs, [n]: { ...cur, items } };
}

// ---- page ------------------------------------------------------------------------------------

export function DemoView({ onChanged, onOpen }: { onChanged: () => void; onOpen: (v: "employees" | "ledger") => void }) {
  const [beats, setBeats] = useState<Beat[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string>();
  const [runs, setRuns] = useState<Record<number, BeatRun>>({});
  const [modes, setModes] = useState<Record<string, string>>();
  const [final, setFinal] = useState<DoneEv>();
  const [claudeCode, setClaudeCode] = useState(false);
  const [auto, setAuto] = useState(false);
  const [revealed, setRevealed] = useState(0); // highest beat the audience has been shown
  const [current, setCurrent] = useState(1);
  const [finale, setFinale] = useState(false);
  const es = useRef<EventSource | null>(null);
  const autoRef = useRef(auto);
  autoRef.current = auto;

  useEffect(() => {
    fetch(`${API_URL}/api/demo/beats`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then(setBeats).catch(() => setError("The demo routes aren't on this backend yet (GET /api/demo/beats failed)."));
    return () => es.current?.close();
  }, []);

  const received = Math.max(0, ...Object.entries(runs).filter(([, r]) => r.started).map(([n]) => Number(n)));
  const last = beats.length;

  const run = useCallback(() => {
    es.current?.close();
    setRuns({});
    setFinal(undefined);
    setError(undefined);
    setRevealed(0);
    setCurrent(1);
    setFinale(false);
    setPhase("running");
    let got = false;
    const src = new EventSource(`${API_URL}/api/demo/run?claude_code=${claudeCode}`);
    es.current = src;
    src.onmessage = (m) => {
      got = true;
      const ev = JSON.parse(m.data) as Record<string, unknown> & { type: string; n?: number };
      if (ev.type === "start") {
        setModes(ev.modes as Record<string, string>);
        if (Array.isArray(ev.beats)) setBeats(ev.beats as Beat[]);
        setRevealed(1);
      } else if (ev.type === "beat" && ev.n) {
        const n = ev.n;
        if (autoRef.current) {
          setRevealed((r) => Math.max(r, n));
          setCurrent(n);
        }
      } else if (ev.type === "beat_done") {
        onChanged();
      } else if (ev.type === "done") {
        setFinal(ev as unknown as DoneEv);
        if (autoRef.current) setFinale(true);
        setPhase("finished");
        src.close();
        onChanged();
      } else if (ev.type === "error" && !ev.n) {
        setError(String(ev.message));
        setPhase("error");
        src.close();
      }
      setRuns((r) => fold(r, ev));
    };
    src.onerror = () => {
      src.close();
      setPhase((p) => (p === "running" ? "error" : p));
      setError((e) => e ?? (got ? "The stream was cut off before the story finished." : "Couldn't start a run. Another run may be going (the backend allows one at a time), or the backend is down."));
    };
  }, [claudeCode, onChanged]);

  const stop = () => {
    es.current?.close();
    setPhase("error");
    setError("Stopped. Whatever ran before you stopped is already on the ledger.");
  };

  const next = () => {
    const n = Math.min(current + 1, Math.max(received, 1));
    setRevealed((r) => Math.max(r, n));
    setCurrent(n);
  };

  const showFinal = !!final && finale;
  const pick = (n: number) => {
    setFinale(false);
    setCurrent(n);
  };
  const beat = beats.find((b) => b.n === current);
  const r = runs[current];
  const canNext = current < last && received > current;

  return (
    <main className="mx-auto max-w-[1280px] px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-[720px]">
          <h1 className="text-[22px] font-[620] tracking-[-0.02em]">Run the demo</h1>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
            Six AI employees do real work through the Countersign MCP server. Every passport, message and finished job is checked against
            Crustdata and written to the ledger. Nothing on this page is scripted output: each card is an event from the run as it happens.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Toggle checked={claudeCode} onChange={setClaudeCode} disabled={phase === "running"} label="Include Claude Code" hint="drives the real CLI, about 20s" />
          <Toggle checked={auto} onChange={setAuto} label="Auto-advance" hint="otherwise step with Next" />
          {phase === "running" ? (
            <Button onClick={stop}><Square className="size-3.5" /> Stop</Button>
          ) : (
            <Button variant="primary" onClick={run} disabled={!beats.length}>
              {phase === "idle" ? <Play className="size-3.5" /> : <RotateCcw className="size-3.5" />} {phase === "idle" ? "Run demo" : "Run again"}
            </Button>
          )}
        </div>
      </div>

      {modes && (
        <p className="mt-3 flex flex-wrap gap-2 font-mono text-[10.5px] text-faint">
          {Object.entries(modes).map(([k, v]) => (
            <span key={k} className="rounded border border-border px-1.5 py-px">{k}: {v}</span>
          ))}
          {modes.crustdata === "replay" && <span className="py-px">Crustdata responses replayed from recorded calls</span>}
        </p>
      )}
      {error && <p className="mt-4 rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}

      <div className="mt-6 grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <ol className="flex gap-1 overflow-x-auto lg:sticky lg:top-16 lg:flex-col lg:self-start lg:overflow-visible">
          {beats.map((b) => {
            const br = runs[b.n];
            const shown = b.n <= revealed;
            const state = !shown ? "pending" : br?.done ? (br.done.ok ? "ok" : "bad") : br?.started ? "running" : "pending";
            return (
              <li key={b.n} className="shrink-0">
                <button
                  disabled={!shown}
                  onClick={() => pick(b.n)}
                  className={cn(
                    "flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition disabled:cursor-default",
                    current === b.n && shown && !showFinal ? "bg-hover" : shown && "hover:bg-hover/60",
                  )}
                >
                  <span
                    className={cn(
                      "mt-px grid size-5 shrink-0 place-items-center rounded-full border font-mono text-[10.5px]",
                      state === "ok" ? "border-verified/40 bg-verified/10 text-verified" : state === "bad" ? "border-contradicted/40 bg-contradicted/10 text-contradicted" : state === "running" ? "border-primary/50 text-primary" : "border-border-strong text-faint",
                    )}
                  >
                    {state === "ok" ? <Check className="size-3" strokeWidth={3} /> : state === "running" ? <Loader2 className="size-3 animate-spin" /> : b.n}
                  </span>
                  <span className={cn("text-[13px] leading-snug", shown ? "font-[510]" : "text-faint")}>{b.title}</span>
                </button>
              </li>
            );
          })}
          {final && revealed >= last && (
            <li className="shrink-0">
              <button onClick={() => setFinale(true)} className={cn("flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition", showFinal ? "bg-hover" : "hover:bg-hover/60")}>
                <span className={cn("mt-px grid size-5 shrink-0 place-items-center rounded-full border", final.chain_ok ? "border-verified/40 bg-verified/10 text-verified" : "border-contradicted/40 text-contradicted")}>
                  <Check className="size-3" strokeWidth={3} />
                </span>
                <span className="text-[13px] font-[510] leading-snug">Scorecard</span>
              </button>
            </li>
          )}
        </ol>

        <section className="min-w-0">
          {phase === "idle" && !revealed ? (
            <div className={cn(cardCls, "grid min-h-72 place-items-center p-8 text-center")}>
              <div className="max-w-[420px]">
                <p className="text-[13.5px] font-[510]">Press Run demo to play the story from the start.</p>
                <p className="mt-1.5 text-[12.5px] text-muted-foreground">
                  It uses the same registry and ledger as the rest of the console, so the AI employees and the ledger fill in as it plays.
                </p>
              </div>
            </div>
          ) : showFinal ? (
            <Finale done={final!} onOpen={onOpen} onBack={() => pick(last)} />
          ) : beat ? (
            <div key={beat.n} className="animate-fade">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[11px] text-faint">{beat.n} / {last}</span>
                <h2 className="text-[18px] font-[620] tracking-[-0.015em]">{beat.title}</h2>
              </div>
              <p className="mt-1.5 max-w-[760px] text-[13.5px] leading-relaxed text-secondary">{beat.narration}</p>

              <div className="mt-5 space-y-3">
                {(r?.items ?? []).map((it, i) => <ItemCard key={i} it={it} />)}
                {r && !r.done && phase === "running" && (
                  <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> working…</p>
                )}
                {r?.lines.length ? <Log lines={r.lines} open={!r.items.length || beat.id === "outside"} /> : null}
              </div>

              {r?.done && (
                <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-border pt-4">
                  <span className={cn("text-[13px] font-[510]", r.done.ok ? "text-verified" : "text-contradicted")}>{r.done.summary}</span>
                  <span className="ml-auto" />
                  {current < last ? (
                    <Button variant="primary" onClick={next} disabled={!canNext}>
                      {canNext ? <>Next: {beats.find((b) => b.n === current + 1)?.title} <ArrowRight className="size-3.5" /></> : <><Loader2 className="size-3.5 animate-spin" /> Waiting for the next step</>}
                    </Button>
                  ) : final ? (
                    <Button variant="primary" onClick={() => setFinale(true)}>
                      See the scorecard <ArrowRight className="size-3.5" />
                    </Button>
                  ) : (
                    <Button variant="primary" disabled><Loader2 className="size-3.5 animate-spin" /> Counting the scorecard</Button>
                  )}
                </div>
              )}
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}

function Toggle({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint: string; disabled?: boolean }) {
  return (
    <label className={cn("flex items-center gap-2 text-[12.5px]", disabled && "opacity-60")} title={hint}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="accent-[var(--primary)]" />
      <span className="font-[510]">{label}</span>
    </label>
  );
}

// ---- cards -----------------------------------------------------------------------------------

function ItemCard({ it }: { it: Item }) {
  switch (it.k) {
    case "agents":
      return (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {it.list.map((a) => <AgentCard key={a.agent_id} a={a} />)}
        </div>
      );
    case "exchange":
      return <Exchange draft={it.draft} verdict={it.verdict} />;
    case "finding":
      return <Finding e={it.e} />;
    case "filed":
      return <Filed e={it.e} />;
    case "artifact":
      return <Artifact e={it.e} />;
  }
}

function AgentCard({ a }: { a: AgentEv }) {
  return (
    <div className={cn(cardCls, "px-4 py-3")}>
      <div className="flex items-center gap-2">
        <span className="text-[14px] font-[590]">{a.agent}</span>
        <RuntimeBadge runtime={a.runtime} />
        <StatusPill status={a.status} className="ml-auto" />
      </div>
      <p className="mt-0.5 text-[12px] text-muted-foreground">{a.role}</p>
      {a.job && <p className="mt-1.5 text-[12.5px] leading-snug text-secondary">{a.job}</p>}
      <p className="mt-2 text-[12px] text-muted-foreground">
        for <span className="font-[510] text-foreground">{a.sponsor.name}</span>
        {a.sponsor.title && `, ${a.sponsor.title}`} at {a.sponsor.company}
      </p>
      <div className="mt-2 flex flex-wrap gap-1">{a.scopes.map((s) => <ScopeChip key={s} scope={s} />)}</div>
      {a.reason && <p className="mt-2 text-[12px] leading-snug text-contradicted">{a.reason}</p>}
    </div>
  );
}

function Exchange({ draft, verdict }: { draft?: DraftEv; verdict?: VerdictEv }) {
  const [showPassed, setShowPassed] = useState(false);
  const agent = verdict?.agent ?? draft?.agent;
  const to = verdict?.to ?? draft?.to;
  const failing = (verdict?.checks ?? []).filter((c) => c.status !== "pass");
  const passed = (verdict?.checks ?? []).filter((c) => c.status === "pass");
  const ok = verdict?.decision === "allow";
  return (
    <div className={cn(cardCls, "overflow-hidden")}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5 text-[12.5px]">
        <span className="font-[590]">{agent}</span>
        <span className="text-muted-foreground">{verdict ? ACTION[verdict.action] : "Message"}</span>
        {to && <span className="text-muted-foreground">to <span className="text-foreground">{to.name}</span>{to.company && ` at ${to.company}`}</span>}
        {draft?.scope && <ScopeChip scope={draft.scope} />}
        <span className="ml-auto">{verdict ? <DecisionBadge decision={verdict.decision} /> : <span className="flex items-center gap-1.5 text-faint"><Loader2 className="size-3 animate-spin" /> checking</span>}</span>
      </div>
      {draft && (
        <blockquote className="mx-4 mt-3 whitespace-pre-line border-l-2 border-border-strong pl-3 text-[12.5px] leading-relaxed text-secondary">{draft.body}</blockquote>
      )}
      {verdict && (
        <div className="px-4 pb-3 pt-3">
          <p className={cn("text-[13.5px] font-[590]", ok ? "text-verified" : "text-contradicted")}>{verdict.headline}</p>
          {failing.length > 0 && (
            <ul className="mt-1 divide-y divide-border">
              {failing.map((c, i) => <CheckRow key={i} check={{ id: String(i), ...c }} />)}
            </ul>
          )}
          {passed.length > 0 && (
            <>
              <button onClick={() => setShowPassed((v) => !v)} className="mt-1.5 flex min-w-0 items-center gap-1 whitespace-nowrap text-[12px] text-muted-foreground hover:text-foreground">
                <ChevronDown className={cn("size-3.5 transition", showPassed && "rotate-180")} />
                {passed.length} {passed.length === 1 ? "check" : "checks"} passed
                {!showPassed && <span className="hidden truncate text-faint sm:inline">: {passed.slice(0, 4).map((c) => checkLabel(c.name)).join(", ")}{passed.length > 4 ? "…" : ""}</span>}
              </button>
              {showPassed && (
                <ul className="divide-y divide-border">
                  {passed.map((c, i) => <CheckRow key={i} check={{ id: String(i), ...c }} />)}
                </ul>
              )}
            </>
          )}
          <p className="mt-2 flex flex-wrap gap-x-3 font-mono text-[10.5px] text-faint">
            {verdict.action === "send" && <span>{verdict.sent ? "written to the outbox, never emailed" : "not sent"}</span>}
            {verdict.ledger_entry && <span title={verdict.ledger_entry}>ledger {verdict.ledger_entry.slice(0, 12)}</span>}
          </p>
        </div>
      )}
    </div>
  );
}

function Finding({ e }: { e: FindingEv }) {
  return (
    <div className={cn(cardCls, "px-4 py-3")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-muted-foreground">{e.agent} checked the resume of</span>
        <span className="text-[14px] font-[590]">{e.candidate}</span>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">
          <span className="text-verified">{e.verified}</span> verified · <span className={e.contradicted.length ? "text-contradicted" : ""}>{e.contradicted.length}</span> false · {e.total} claims
        </span>
      </div>
      {e.contradicted.length > 0 && (
        <ul className="mt-2 divide-y divide-border">
          {e.contradicted.map((c, i) => (
            <li key={i} className="py-2">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="text-[13px] font-[510]">
                  <span className="mr-1.5 font-mono text-[10.5px] text-contradicted">FALSE</span>
                  {c.claim}
                </span>
                <SourceChip source={c.source ? { ...c.source, url: c.source.url ?? e.profile_url } : null} />
              </div>
              <p className="mt-0.5 text-[12.5px] leading-snug text-secondary">{c.evidence}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Filed({ e }: { e: FiledEv }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-dashed border-border-strong px-3.5 py-2 text-[12.5px]">
      <FileText className="size-3.5 text-faint" />
      <span className="font-[510]">{e.agent} filed {e.kind.replace(/^work\./, "").replace(/_/g, " ")}</span>
      <span className="min-w-0 flex-1 truncate text-muted-foreground">{e.summary}</span>
      <span className="font-mono text-[10.5px] text-faint">{e.sources.length} sources · signed · ledger {e.ledger_entry.slice(0, 12)}</span>
    </div>
  );
}

function Artifact({ e }: { e: ArtifactEv }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cn(cardCls, "overflow-hidden")}>
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <FileText className="size-4 text-primary" />
        <span className="text-[13px] font-[590]">{e.title}</span>
        <span className="ml-auto truncate font-mono text-[10.5px] text-faint" title={e.path}>{e.path.split("/").pop()}</span>
      </div>
      <div className={cn("relative px-5 py-4", !open && "max-h-[340px] overflow-hidden")}>
        <Markdown text={e.content} />
        {!open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-panel" />}
      </div>
      <button onClick={() => setOpen((v) => !v)} className="w-full border-t border-border py-2 text-[12px] text-muted-foreground hover:bg-hover hover:text-foreground">
        {open ? "Collapse" : "Read the whole brief"}
      </button>
    </div>
  );
}

function Log({ lines, open: initial }: { lines: string[]; open: boolean }) {
  const [open, setOpen] = useState(initial);
  return (
    <div className="rounded-lg border border-border">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 px-3.5 py-2 text-[12px] text-muted-foreground hover:text-foreground">
        <TerminalSquare className="size-3.5" /> Agent log <span className="text-faint">({lines.length} lines)</span>
        <ChevronDown className={cn("ml-auto size-3.5 transition", open && "rotate-180")} />
      </button>
      {open && (
        <pre className="max-h-[320px] overflow-auto border-t border-border px-3.5 py-2.5 font-mono text-[11px] leading-relaxed text-secondary">{lines.join("\n")}</pre>
      )}
    </div>
  );
}

function Finale({ done, onOpen, onBack }: { done: DoneEv; onOpen: (v: "employees" | "ledger") => void; onBack: () => void }) {
  return (
    <div className="animate-fade">
      <h2 className="text-[18px] font-[620] tracking-[-0.015em]">The scorecard</h2>
      <p className="mt-1.5 max-w-[760px] text-[13.5px] leading-relaxed text-secondary">
        Counted from the ledger, not from this page: what each AI employee sent, what Send Guard stopped, and the work it filed.
      </p>
      <div className={cn("mt-4 flex items-center gap-3 rounded-xl border px-4 py-3", done.chain_ok ? "border-verified/30 bg-verified/[0.05]" : "border-contradicted/35 bg-contradicted/[0.06]")}>
        <span className={cn("text-[14px] font-[590]", done.chain_ok ? "text-verified" : "text-contradicted")}>{done.chain_ok ? "Chain intact" : "Chain broken"}</span>
        <span className="text-[12.5px] text-muted-foreground">{done.entries} ledger entries, every one hash-linked to the one before</span>
        <Button className="ml-auto" onClick={() => onOpen("ledger")}>Open the ledger <ArrowRight className="size-3.5" /></Button>
      </div>
      <div className={cn(cardCls, "mt-4 overflow-x-auto")}>
        <table className="w-full min-w-[640px] text-[12.5px]">
          <thead>
            <tr className="border-b border-border text-left text-[11.5px] text-muted-foreground">
              {["AI employee", "Status", "Messages", "Allowed", "Blocked", "Top block reason", "Work filed", "Sponsor checks"].map((h) => (
                <th key={h} className="px-4 py-2 font-[510]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border tabular-nums">
            {done.scorecard.map((s) => (
              <tr key={s.agent_id}>
                <td className="px-4 py-2.5 font-[510]">{s.agent}</td>
                <td className="px-4 py-2.5"><StatusPill status={s.status} /></td>
                <td className="px-4 py-2.5">{s.messages_checked}</td>
                <td className="px-4 py-2.5 text-verified">{s.allowed}</td>
                <td className={cn("px-4 py-2.5", s.blocked && "text-contradicted")}>{s.blocked}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{s.block_reasons[0] ? checkLabel(s.block_reasons[0][0]) : "none"}</td>
                <td className="px-4 py-2.5">{s.work_filed ?? 0}</td>
                <td className="px-4 py-2.5">{s.sponsor_checks}{s.sponsor_checks_failed ? <span className="text-contradicted"> ({s.sponsor_checks_failed} failed)</span> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-5 flex flex-wrap gap-2">
        <Button onClick={onBack}>Back to the last step</Button>
        <Button onClick={() => onOpen("employees")}>See the AI employees <ArrowRight className="size-3.5" /></Button>
      </div>
    </div>
  );
}

// ---- tiny markdown (headings, lists, bold, links, citations) for the vendor brief ------------

function inline(s: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:[^)]+)\)|\[(\d+)\]/g;
  let i = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > i) out.push(s.slice(i, m.index));
    if (m[1]) out.push(<strong key={m.index} className="font-[590]">{m[1]}</strong>);
    else if (m[2]) out.push(<a key={m.index} href={m[3]} target="_blank" rel="noreferrer" className="text-primary underline-offset-2 hover:underline">{m[2]}</a>);
    else out.push(<sup key={m.index} className="ml-0.5 font-mono text-[9.5px] text-primary">[{m[4]}]</sup>);
    i = m.index + m[0].length;
  }
  if (i < s.length) out.push(s.slice(i));
  return out;
}

function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const L = list.ordered ? "ol" : "ul";
    blocks.push(
      <L key={blocks.length} className={cn("my-1.5 space-y-0.5 pl-5 text-[12.5px] leading-relaxed text-secondary", list.ordered ? "list-decimal" : "list-disc")}>
        {list.items.map((t, j) => <li key={j}>{inline(t)}</li>)}
      </L>,
    );
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const ul = /^\s*[-*]\s+(.*)/.exec(line);
    const ol = /^\s*\d+\.\s+(.*)/.exec(line);
    if (ul || ol) {
      const ordered = !!ol;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push((ul ?? ol)![1]);
      continue;
    }
    flush();
    if (!line) continue;
    const h = /^(#{1,3})\s+(.*)/.exec(line);
    if (h) {
      const lvl = h[1].length;
      blocks.push(
        <p key={blocks.length} className={cn("font-[620] tracking-[-0.01em]", lvl === 1 ? "text-[16px]" : "mt-3 text-[13.5px]")}>{inline(h[2])}</p>,
      );
    } else blocks.push(<p key={blocks.length} className="my-1 text-[12.5px] leading-relaxed text-secondary">{inline(line)}</p>);
  }
  flush();
  return <div>{blocks.map((b, i) => <Fragment key={i}>{b}</Fragment>)}</div>;
}
