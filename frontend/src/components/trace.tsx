"use client";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, ChevronRight, Database, FileSearch, Mail, ScanSearch, ShieldCheck, FileText, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import { PIPELINE_STEPS } from "@/lib/types";
import type { RunState, StepState } from "@/lib/run-state";

const META: Record<string, { label: string; todo: string; tool: string; Icon: typeof Database }> = {
  parse: { todo: "Read the brief", label: "Read the brief", tool: "llm · parse_brief", Icon: FileText },
  search: { todo: "Search people", label: "Searched people", tool: "crustdata · person/search", Icon: ScanSearch },
  enrich: { todo: "Enrich profiles", label: "Enriched profiles", tool: "crustdata · person/enrich, company/enrich", Icon: Database },
  verify: { todo: "Verify claims", label: "Verified claims", tool: "crustdata · enrich + web/fetch", Icon: ShieldCheck },
  rank: { todo: "Rank candidates", label: "Ranked candidates", tool: "llm · rank (cites claim ids)", Icon: Trophy },
  outreach: { todo: "Draft outreach", label: "Drafted outreach", tool: "llm · draft (never sent)", Icon: Mail },
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
    <div className="flex flex-col gap-1.5">
      {seen.map((s) => {
        const st = run.steps[s] as StepState | undefined;
        const lines = run.log.filter((l) => l.step === s);
        const status = st?.status ?? "done";
        const active = status === "active" && run.running;
        const dur = st?.startedAt ? Math.max(0, (st.endedAt ?? (run.running ? now : st.startedAt)) - st.startedAt) : undefined;
        const m = META[s] ?? { label: s, todo: s, tool: s, Icon: FileSearch };
        const isOpen = open[s] ?? (active || lines.some((l) => l.kind === "error"));
        return (
          <div key={s} className={cn("animate-rise rounded-lg border bg-panel transition-colors", active ? "border-primary/40" : "border-border")}>
            <button
              onClick={() => setOpen((o) => ({ ...o, [s]: !isOpen }))}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left"
            >
              <span
                className={cn(
                  "grid size-6 shrink-0 place-items-center rounded-md border",
                  active ? "border-primary/40 bg-primary/10 text-primary" : "border-border bg-elevated text-muted-foreground",
                )}
              >
                <m.Icon className="size-3.5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className={cn("truncate text-[13px] font-[510]", active && "shimmer-text")}>{m.label}</span>
                  {st?.count !== undefined && <span className="font-mono text-[11px] text-secondary tabular-nums">{st.count}</span>}
                  {!!st?.errors && (
                    <span className="inline-flex items-center gap-0.5 text-[11px] text-flag">
                      <AlertTriangle className="size-3" /> {st.errors}
                    </span>
                  )}
                  <span className="ml-auto font-mono text-[10.5px] text-faint tabular-nums">{fmt(dur)}</span>
                  {status === "done" || status === "warn" || !run.running ? (
                    <Check className={cn("size-3.5 shrink-0", status === "warn" ? "text-flag" : "text-verified")} />
                  ) : (
                    <span className="size-3.5 shrink-0 animate-spin rounded-full border-[1.5px] border-primary border-t-transparent" />
                  )}
                </span>
                <span className="mt-0.5 flex items-center gap-1 font-mono text-[10.5px] text-faint">
                  <span className="truncate">{m.tool}</span>
                  {lines.length > 0 && <ChevronRight className={cn("ml-auto size-3 shrink-0 transition-transform", isOpen && "rotate-90")} />}
                </span>
              </span>
            </button>
            {isOpen && lines.length > 0 && (
              <ol className="border-t border-border px-3 py-2 font-mono text-[11px] leading-relaxed">
                {lines.map((l, i) => (
                  <li key={i} className={cn("flex gap-2 py-0.5", l.kind === "error" ? "text-flag" : "text-muted-foreground")}>
                    <span className="shrink-0 text-faint tabular-nums">{(l.t / 1000).toFixed(1)}s</span>
                    <span className="min-w-0">{l.message}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        );
      })}
      {ungrouped.map((l, i) => (
        <p key={i} className="rounded-lg border border-flag/30 bg-flag/5 px-3 py-2 text-[12px] text-flag">
          {l.message}
        </p>
      ))}
      {pending.map((s) => {
        const m = META[s];
        return (
          <div key={s} className="flex items-center gap-2.5 rounded-lg border border-dashed border-border px-3 py-2 text-faint">
            <span className="grid size-6 place-items-center rounded-md border border-border">
              <m.Icon className="size-3.5" />
            </span>
            <span className="text-[13px]">{m.todo}</span>
          </div>
        );
      })}
      {!seen.length && !run.running && <p className="text-[13px] text-faint">The agent&apos;s tool calls appear here.</p>}
      <div ref={endRef} />
    </div>
  );
}
