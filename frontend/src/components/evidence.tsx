import { cn } from "@/lib/utils";
import type { Candidate, ClaimStatus } from "@/lib/types";
import { normalizeStatus } from "@/lib/run-state";

export const STATUS_LABEL: Record<ClaimStatus, string> = {
  verified: "Verified",
  contradicted: "Contradicted",
  unverifiable: "Unverifiable",
};

const STATUS_CLS: Record<ClaimStatus, string> = {
  verified: "text-verified border-verified/60",
  contradicted: "text-contradicted border-contradicted/70",
  unverifiable: "text-unverifiable border-unverifiable/50 border-dashed",
};

/** Rubber-stamp style status mark. */
export function Stamp({ status, className, animate }: { status: ClaimStatus; className?: string; animate?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 select-none items-center rounded-[3px] border-[1.5px] px-1.5 py-px font-mono text-[10px] font-medium uppercase tracking-[0.14em]",
        STATUS_CLS[status],
        animate && "animate-stamp",
        className,
      )}
      style={{ ["--stamp-rot" as string]: status === "contradicted" ? "-3deg" : "0deg", transform: status === "contradicted" ? "rotate(-3deg)" : undefined }}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

const DOT: Record<ClaimStatus, string> = {
  verified: "bg-verified",
  contradicted: "bg-contradicted",
  unverifiable: "bg-transparent border border-unverifiable/70",
};

/** One tick per claim, coloured by status: contradicted first so problems are visible at a glance. */
export function EvidenceStrip({ candidate, className }: { candidate: Candidate; className?: string }) {
  const order = { contradicted: 0, verified: 1, unverifiable: 2 } as const;
  const statuses = (candidate.claims ?? [])
    .map((k) => normalizeStatus(k.status, !!k.source?.endpoint))
    .sort((a, b) => order[a] - order[b]);
  if (!statuses.length) return <span className="font-mono text-[10px] text-muted-foreground">no claims</span>;
  return (
    <span className={cn("inline-flex items-center gap-[3px]", className)} aria-label={`${statuses.length} claims`}>
      {statuses.map((s, i) => (
        <span key={i} className={cn("h-3 w-1.5 rounded-[1px]", DOT[s])} title={STATUS_LABEL[s]} />
      ))}
    </span>
  );
}

export function FitMeter({ score, className }: { score?: number; className?: string }) {
  const s = Math.max(0, Math.min(100, Math.round(score ?? 0)));
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className="relative h-1 w-16 overflow-hidden rounded-full bg-muted">
        <span className="absolute inset-y-0 left-0 rounded-full bg-foreground transition-[width] duration-700" style={{ width: `${s}%` }} />
      </span>
      <span className="font-mono text-xs tabular-nums">{score === undefined ? "–" : s}</span>
    </span>
  );
}
