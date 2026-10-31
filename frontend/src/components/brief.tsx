"use client";
import { forwardRef } from "react";
import { ArrowRight, CornerDownLeft, Square } from "lucide-react";
import { cn } from "@/lib/utils";

export const EXAMPLES = [
  { label: "Payments backend", brief: "need a senior backend eng, payments exp, Bangalore, ex-startup, can start soon" },
  { label: "Founding ML", brief: "founding ML engineer for a seed-stage fintech in Mumbai, LLM + ranking experience" },
  { label: "Growth lead", brief: "head of growth, B2B SaaS, has scaled 0→1, remote india ok" },
  { label: "Messy one", brief: "pm?? fintech-ish. delhi or gurgaon. NOT big tech. someone scrappy" },
];

interface Props {
  value: string;
  onChange: (v: string) => void;
  onRun: () => void;
  onStop: () => void;
  running: boolean;
  compact?: boolean;
}

export const BriefInput = forwardRef<HTMLTextAreaElement, Props>(function BriefInput({ value, onChange, onRun, onStop, running, compact }, ref) {
  return (
    <div className={cn("group relative rounded-lg border border-rule bg-paper transition focus-within:border-foreground", compact ? "shadow-none" : "shadow-[0_1px_0_var(--rule),0_12px_32px_-16px_rgba(0,0,0,0.25)]")}>
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey || (!e.shiftKey && compact))) {
            e.preventDefault();
            onRun();
          }
          if (e.key === "Escape") (e.target as HTMLTextAreaElement).blur();
        }}
        placeholder="Describe the role the way you'd say it to a recruiter…"
        rows={compact ? 1 : 3}
        disabled={running}
        className={cn(
          "w-full resize-none bg-transparent focus:outline-none disabled:opacity-70",
          compact ? "px-4 py-3 pr-36 text-[15px]" : "font-display px-6 pb-16 pt-5 text-2xl leading-snug placeholder:text-muted-foreground/70 sm:text-[28px]",
        )}
        aria-label="Hiring brief"
      />
      <div className={cn("absolute flex items-center gap-2", compact ? "right-2 top-1/2 -translate-y-1/2" : "bottom-3 right-3")}>
        {!compact && (
          <span className="hidden items-center gap-1 text-xs text-muted-foreground sm:inline-flex">
            <kbd>⌘</kbd>
            <kbd>↵</kbd>
          </span>
        )}
        {running ? (
          <button onClick={onStop} className="inline-flex h-9 items-center gap-2 rounded-md border border-foreground px-4 text-sm font-medium hover:bg-muted">
            <Square className="size-3.5 fill-current" /> Stop
          </button>
        ) : (
          <button
            onClick={onRun}
            disabled={!value.trim()}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-90 disabled:opacity-40"
          >
            {compact ? <CornerDownLeft className="size-4" /> : null}
            {compact ? "Re-run" : "Build shortlist"}
            {!compact && <ArrowRight className="size-4" />}
          </button>
        )}
      </div>
    </div>
  );
});
