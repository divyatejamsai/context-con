"use client";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, ChevronDown, Database, FileSearch, Mail, ScanSearch, ShieldCheck, Sparkles, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import { PIPELINE_STEPS } from "@/lib/types";
import type { RunState, StepState } from "@/lib/run-state";

const META: Record<string, { label: string; todo: string; tool: string; Icon: typeof Database; bg: string }> = {
  parse: { label: "Read the brief", todo: "Read the brief", tool: "llm · parse_brief", Icon: Sparkles, bg: "bg-lavender" },
  search: { label: "Searched people", todo: "Search people", tool: "crustdata · person/search", Icon: ScanSearch, bg: "bg-sky" },
  enrich: { label: "Enriched profiles", todo: "Enrich profiles", tool: "crustdata · person + company enrich", Icon: Database, bg: "bg-pink" },
  verify: { label: "Verified claims", todo: "Verify claims", tool: "crustdata · enrich + web fetch", Icon: ShieldCheck, bg: "bg-lime" },
  rank: { label: "Ranked candidates", todo: "Rank candidates", tool: "llm · rank, cites claim ids", Icon: Trophy, bg: "bg-yellow" },
  outreach: { label: "Drafted outreach", todo: "Draft outreach", tool: "llm · draft, never sent", Icon: Mail, bg: "bg-coral" },
};

const fmt = (ms?: number) => (ms === undefined ? "" : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`);

export function Trace({ run, now }: { run: RunState; now: number }) {
  const endRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [run.log.length]);

  const extra = Object.keys(run.steps).filter((s) => !(PIPELINE_STEPS as readonly string[]).includes(s));
  const seen = [...PIPELINE_STEPS, ...extra].filter((s) => run.steps[s] || run.log.some((l) => l.step === s));
  const pending = run.running ? PIPELINE_STEPS.filter((s) => !seen.includes(s)) : [];
  const ungrouped = run.log.filter((l) => !l.step);

  return (
    <ol className="relative flex flex-col gap-2.5">
      <span className="absolute bottom-3 left-[19px] top-3 w-0.5 bg-ink/80" aria-hidden />
      {seen.map((s, idx) => {
        const st = run.steps[s] as StepState | undefined;
        const lines = run.log.filter((l) => l.step === s);
        const status = st?.status ?? "done";
        const active = status === "active" && run.running;
        const dur = st?.startedAt ? Math.max(0, (st.endedAt ?? (run.running ? now : st.startedAt)) - st.startedAt) : undefined;
        const m = META[s] ?? { label: s, todo: s, tool: s, Icon: FileSearch, bg: "bg-elevated" };
        const isOpen = open[s] ?? (active || lines.some((l) => l.kind === "error"));
        return (
          <li key={s} className="relative animate-rise" style={{ animationDelay: `${idx * 20}ms` }}>
            <div className="flex gap-2.5">
              <span className={cn("relative z-10 grid size-10 shrink-0 place-items-center rounded-full border-2 border-ink text-on-color shadow-brut-sm", m.bg, active && "animate-pulse")}>
                <m.Icon className="size-4" strokeWidth={2.5} />
              </span>
              <div className={cn("min-w-0 flex-1 rounded-lg border-2 border-ink bg-panel", active ? "shadow-brut" : "shadow-brut-sm")}>
                <button onClick={() => setOpen((o) => ({ ...o, [s]: !isOpen }))} className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left">
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate text-[13px] font-bold", active && "caret")}>{m.label}</span>
                    <span className="block truncate font-mono text-[10.5px] text-muted-foreground">{m.tool}</span>
                  </span>
                  {st?.count !== undefined && (
                    <span className="rounded border-[1.5px] border-ink bg-yellow px-1 font-mono text-[11px] font-bold text-on-color tabular-nums">{st.count}</span>
                  )}
                  {!!st?.errors && (
                    <span className="inline-flex items-center gap-0.5 rounded border-[1.5px] border-ink bg-coral px-1 text-[11px] font-bold text-on-color">
                      <AlertTriangle className="size-3" /> {st.errors}
                    </span>
                  )}
                  <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">{fmt(dur)}</span>
                  {active ? (
                    <span className="size-3.5 shrink-0 animate-spin rounded-full border-2 border-ink border-t-transparent" />
                  ) : (
                    <Check className="size-3.5 shrink-0" strokeWidth={3} />
                  )}
                  {lines.length > 0 && <ChevronDown className={cn("size-3.5 shrink-0 transition-transform", isOpen && "rotate-180")} />}
                </button>
                {isOpen && lines.length > 0 && (
                  <ol className="border-t-2 border-dashed border-ink/40 px-2.5 py-1.5 font-mono text-[11px] leading-relaxed">
                    {lines.map((l, i) => (
                      <li key={i} className={cn("flex gap-2 py-0.5", l.kind === "error" ? "font-semibold text-contradicted" : "text-secondary")}>
                        <span className="shrink-0 text-faint tabular-nums">{(l.t / 1000).toFixed(1)}s</span>
                        <span className="min-w-0">{l.message}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </div>
          </li>
        );
      })}
      {ungrouped.map((l, i) => (
        <li key={`u${i}`} className="relative ml-[50px] rounded-lg border-2 border-ink bg-coral px-2.5 py-1.5 text-[12px] font-semibold text-on-color">
          {l.message}
        </li>
      ))}
      {pending.map((s) => {
        const m = META[s];
        return (
          <li key={s} className="relative flex items-center gap-2.5 opacity-60">
            <span className="relative z-10 grid size-10 shrink-0 place-items-center rounded-full border-2 border-dashed border-ink bg-background">
              <m.Icon className="size-4" />
            </span>
            <span className="flex-1 rounded-lg border-2 border-dashed border-ink/60 px-2.5 py-2 text-[13px] font-semibold">{m.todo}</span>
          </li>
        );
      })}
      {!seen.length && !run.running && <li className="text-[13px] text-faint">The agent&apos;s tool calls appear here.</li>}
      <div ref={endRef} />
    </ol>
  );
}
