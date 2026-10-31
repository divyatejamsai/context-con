"use client";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { PIPELINE_STEPS } from "@/lib/types";

export interface FeedItem {
  kind: "step" | "error" | "done";
  step?: string;
  message: string;
  at: number;
}

const LABEL: Record<string, string> = {
  parse: "Parse",
  search: "Search",
  enrich: "Enrich",
  verify: "Verify",
  rank: "Rank",
  outreach: "Outreach",
};

export function PipelineBar({ current, done }: { current?: string; done: boolean }) {
  const idx = current ? PIPELINE_STEPS.indexOf(current as (typeof PIPELINE_STEPS)[number]) : -1;
  return (
    <ol className="grid grid-cols-6 gap-1">
      {PIPELINE_STEPS.map((s, i) => {
        const state = done || i < idx ? "done" : i === idx ? "active" : "todo";
        return (
          <li key={s} className="flex flex-col gap-1">
            <div
              className={cn(
                "h-1.5 rounded-full",
                state === "done" && "bg-primary",
                state === "active" && "bg-primary/50 animate-pulse",
                state === "todo" && "bg-muted",
              )}
            />
            <span className={cn("truncate text-[11px]", state === "todo" ? "text-muted-foreground" : "text-foreground")}>
              {LABEL[s]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function StepFeed({ items, running }: { items: FeedItem[]; running: boolean }) {
  if (!items.length) {
    return <p className="text-sm text-muted-foreground">The agent&apos;s steps will stream here as it works.</p>;
  }
  return (
    <ol className="flex flex-col gap-2.5">
      {items.map((it, i) => {
        const last = i === items.length - 1;
        return (
          <li key={i} className="flex gap-2.5 text-sm animate-rise">
            <span className="mt-0.5">
              {it.kind === "error" ? (
                <AlertTriangle className="size-4 text-flag" />
              ) : last && running ? (
                <Loader2 className="size-4 animate-spin text-primary" />
              ) : (
                <CheckCircle2 className="size-4 text-verified" />
              )}
            </span>
            <div className="min-w-0">
              {it.step && (
                <span className="mr-1.5 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
                  {LABEL[it.step] ?? it.step}
                </span>
              )}
              <span className={cn(it.kind === "error" && "text-flag")}>{it.message}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
