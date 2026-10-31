"use client";
import { forwardRef } from "react";
import { ArrowRight, CornerDownLeft, Square } from "lucide-react";
import { cn } from "@/lib/utils";

export const EXAMPLES = [
  { label: "Payments backend, BLR", brief: "need a senior backend eng, payments exp, Bangalore, ex-startup, can start soon" },
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
    <div className={cn("relative rounded-xl border-[1.5px] border-ink bg-panel transition-shadow focus-within:shadow-brut-lg", compact ? "shadow-brut-sm" : "shadow-brut-xl")}>
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
        placeholder="Describe the role, however it comes out…"
        rows={compact ? 1 : 3}
        wrap={compact ? "off" : "soft"}
        disabled={running}
        className={cn(
          "w-full resize-none bg-transparent placeholder:text-faint focus:outline-none disabled:opacity-60",
          compact ? "block h-11 overflow-hidden px-3.5 py-3 pr-32 text-[14px] font-medium" : "px-5 pb-2 pt-5 text-[18px] font-medium leading-relaxed sm:text-[20px]",
        )}
        aria-label="Hiring brief"
      />
      {compact ? (
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2">
          <RunButton running={running} disabled={!value.trim()} onRun={onRun} onStop={onStop} label="Re-run" />
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2 px-4 pb-4">
          <div className="min-w-0">{footer}</div>
          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-1 sm:inline-flex">
              <kbd>⌘</kbd>
              <kbd>↵</kbd>
            </span>
            <RunButton running={running} disabled={!value.trim()} onRun={onRun} onStop={onStop} label="Find candidates" big />
          </div>
        </div>
      )}
    </div>
  );
});

function RunButton({ running, disabled, onRun, onStop, label, big }: { running: boolean; disabled: boolean; onRun: () => void; onStop: () => void; label: string; big?: boolean }) {
  const base = cn("press inline-flex items-center gap-1.5 rounded-lg border-[1.5px] border-ink font-bold shadow-brut-sm disabled:opacity-40", big ? "h-11 px-4 text-[15px]" : "h-8 px-3 text-[13px]");
  return running ? (
    <button onClick={onStop} className={cn(base, "bg-coral text-on-color")}>
      <Square className="size-3 fill-current" /> Stop
    </button>
  ) : (
    <button onClick={onRun} disabled={disabled} className={cn(base, "bg-ink text-background")}>
      {big ? null : <CornerDownLeft className="size-3.5" />}
      {label}
      {big && <ArrowRight className="size-4" strokeWidth={3} />}
    </button>
  );
}
