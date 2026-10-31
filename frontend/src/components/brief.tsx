"use client";
import { forwardRef } from "react";
import { ArrowUp, CornerDownLeft, Square } from "lucide-react";
import { cn } from "@/lib/utils";

export const EXAMPLES = [
  { label: "Payments backend, Bangalore", brief: "need a senior backend eng, payments exp, Bangalore, ex-startup, can start soon" },
  { label: "Founding ML, Mumbai", brief: "founding ML engineer for a seed-stage fintech in Mumbai, LLM + ranking experience" },
  { label: "Head of growth, remote", brief: "head of growth, B2B SaaS, has scaled 0→1, remote india ok" },
  { label: "A messy one", brief: "pm?? fintech-ish. delhi or gurgaon. NOT big tech. someone scrappy" },
];

interface Props {
  value: string;
  onChange: (v: string) => void;
  onRun: () => void;
  onStop: () => void;
  running: boolean;
  compact?: boolean;
  footer?: React.ReactNode;
}

export const BriefInput = forwardRef<HTMLTextAreaElement, Props>(function BriefInput({ value, onChange, onRun, onStop, running, compact, footer }, ref) {
  return (
    <div
      className={cn(
        "relative rounded-lg border border-border-strong bg-panel transition focus-within:border-primary/60",
        !compact && "shadow-[var(--shadow)] focus-within:shadow-[0_0_0_3px_var(--glow)]",
      )}
    >
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
        placeholder="Tell me who you're hiring, however it comes out…"
        rows={compact ? 1 : 3}
        wrap={compact ? "off" : "soft"}
        disabled={running}
        className={cn(
          "w-full resize-none bg-transparent placeholder:text-faint focus:outline-none disabled:opacity-60",
          compact ? "block h-10 overflow-hidden px-3.5 py-2.5 pr-28 text-[13.5px]" : "px-4 pb-2 pt-4 text-[17px] leading-relaxed",
        )}
        aria-label="Hiring brief"
      />
      {compact ? (
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2">
          <RunButton running={running} disabled={!value.trim()} onRun={onRun} onStop={onStop} label="Re-run" />
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2 px-3 pb-3">
          <div className="min-w-0">{footer}</div>
          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-1 text-[11px] text-faint sm:inline-flex">
              <kbd>⌘</kbd>
              <kbd>↵</kbd>
            </span>
            <RunButton running={running} disabled={!value.trim()} onRun={onRun} onStop={onStop} label="Find candidates" />
          </div>
        </div>
      )}
    </div>
  );
});

function RunButton({ running, disabled, onRun, onStop, label }: { running: boolean; disabled: boolean; onRun: () => void; onStop: () => void; label: string }) {
  return running ? (
    <button onClick={onStop} className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border-strong bg-elevated px-2.5 text-[12.5px] font-[510] hover:bg-hover">
      <Square className="size-3 fill-current" /> Stop
    </button>
  ) : (
    <button
      onClick={onRun}
      disabled={disabled}
      className="inline-flex h-7 items-center gap-1.5 rounded-md bg-foreground px-2.5 text-[12.5px] font-[510] text-background transition hover:opacity-85 disabled:opacity-40"
    >
      {label === "Re-run" ? <CornerDownLeft className="size-3.5" /> : <ArrowUp className="size-3.5" />}
      {label}
    </button>
  );
}
