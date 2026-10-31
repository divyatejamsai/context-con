"use client";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { PIPELINE_STEPS } from "@/lib/types";
import type { RunState, StepState } from "@/lib/run-state";

const LABEL: Record<string, string> = {
  parse: "Read the brief",
  search: "Search Crustdata",
  enrich: "Enrich profiles",
  verify: "Verify every claim",
  rank: "Rank with citations",
  outreach: "Draft outreach",
};

const fmt = (ms?: number) => (ms === undefined ? "" : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`);

export function Trace({ run, now }: { run: RunState; now: number }) {
  const logRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [run.log.length]);

  const extra = Object.keys(run.steps).filter((s) => !(PIPELINE_STEPS as readonly string[]).includes(s));
  const steps = [...PIPELINE_STEPS, ...extra];

  return (
    <div className="flex flex-col gap-5">
      <ol className="relative flex flex-col">
        {steps.map((s, i) => {
          const st = run.steps[s];
          const status = (st?.status ?? (run.done ? "skipped" : "pending")) as StepState["status"] | "skipped";
          const dur = st?.startedAt ? Math.max(0, (st.endedAt ?? (run.running ? now : st.startedAt)) - st.startedAt) : undefined;
          return (
            <li key={s} className="relative flex gap-3 pb-3 last:pb-0">
              {i < steps.length - 1 && (
                <span className={cn("absolute left-[7px] top-4 h-full w-px", status === "done" || status === "warn" ? "bg-foreground/50" : "bg-rule")} />
              )}
              <span
                className={cn(
                  "relative z-10 mt-0.5 grid size-[15px] shrink-0 place-items-center rounded-full border-[1.5px] bg-paper",
                  status === "pending" && "border-rule",
                  status === "skipped" && "border-dashed border-rule",
                  status === "active" && "border-primary",
                  status === "done" && "border-foreground bg-foreground",
                  status === "warn" && "border-flag bg-flag",
                )}
              >
                {status === "active" && <span className="size-1.5 animate-ping rounded-full bg-primary" />}
              </span>
              <div className="flex min-w-0 flex-1 items-baseline justify-between gap-2">
                <span className={cn("text-sm", status === "pending" || status === "skipped" ? "text-muted-foreground" : "font-medium")}>
                  {LABEL[s] ?? s}
                  {st?.count !== undefined && <span className="ml-1.5 font-mono text-xs text-muted-foreground">{st.count}</span>}
                  {!!st?.errors && <span className="ml-1.5 font-mono text-xs text-flag">{st.errors} warn</span>}
                </span>
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{fmt(dur)}</span>
              </div>
            </li>
          );
        })}
      </ol>

      <div>
        <div className="mb-2 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          <span>Agent log</span>
          <span>{run.log.length} events</span>
        </div>
        <ol ref={logRef} className="max-h-72 overflow-y-auto border-l border-rule pl-3 font-mono text-[11.5px] leading-relaxed">
          {run.log.map((l, i) => (
            <li key={i} className={cn("animate-rise py-0.5", l.kind === "error" && "text-flag")}>
              <span className="mr-2 text-muted-foreground tabular-nums">{(l.t / 1000).toFixed(1).padStart(4, " ")}s</span>
              {l.kind === "error" && "⚠ "}
              {l.message}
            </li>
          ))}
          {run.running && <li className="py-0.5 text-muted-foreground">▍</li>}
          {!run.log.length && !run.running && <li className="text-muted-foreground">Waiting for a brief.</li>}
        </ol>
      </div>
    </div>
  );
}
