import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate, ClaimStatus } from "@/lib/types";
import { normalizeStatus } from "@/lib/run-state";

export const STATUS_LABEL: Record<ClaimStatus, string> = {
  verified: "Verified",
  contradicted: "Contradicted",
  unverifiable: "Unverifiable",
};

const ICON = { verified: CheckCircle2, contradicted: XCircle, unverifiable: CircleDashed } as const;
const TONE: Record<ClaimStatus, string> = {
  verified: "text-verified",
  contradicted: "text-contradicted",
  unverifiable: "text-unverifiable",
};

export function StatusIcon({ status, className }: { status: ClaimStatus; className?: string }) {
  const I = ICON[status];
  return <I className={cn("size-3.5 shrink-0", TONE[status], className)} aria-label={STATUS_LABEL[status]} />;
}

export function StatusPill({ status, count, className }: { status: ClaimStatus; count?: number; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 rounded-full border px-1.5 text-[11px] font-[510]",
        status === "verified" && "border-verified/25 bg-verified/10 text-verified",
        status === "contradicted" && "border-contradicted/30 bg-contradicted/10 text-contradicted",
        status === "unverifiable" && "border-border-strong text-muted-foreground",
        className,
      )}
    >
      <StatusIcon status={status} className="size-3" />
      {count !== undefined ? count : STATUS_LABEL[status]}
    </span>
  );
}

const SEG: Record<ClaimStatus, string> = {
  verified: "bg-verified",
  contradicted: "bg-contradicted",
  unverifiable: "bg-border-strong",
};

/** One segment per claim, contradicted first: the record's trustworthiness at a glance. */
export function EvidenceStrip({ candidate, className }: { candidate: Candidate; className?: string }) {
  const order = { contradicted: 0, verified: 1, unverifiable: 2 } as const;
  const statuses = (candidate.claims ?? [])
    .map((k) => normalizeStatus(k.status, !!k.source?.endpoint))
    .sort((a, b) => order[a] - order[b]);
  if (!statuses.length) return <span className="text-[11px] text-faint">no claims</span>;
  return (
    <span className={cn("inline-flex items-center gap-[2px]", className)} aria-label={`${statuses.length} claims`}>
      {statuses.map((s, i) => (
        <span key={i} className={cn("h-2.5 w-[5px] rounded-[1.5px]", SEG[s])} title={STATUS_LABEL[s]} />
      ))}
    </span>
  );
}

export function matchLabel(score?: number): { label: string; cls: string } {
  if (score === undefined) return { label: "Scoring", cls: "text-faint" };
  if (score >= 85) return { label: "Strong match", cls: "text-verified" };
  if (score >= 70) return { label: "Good match", cls: "text-primary" };
  if (score >= 50) return { label: "Partial match", cls: "text-flag" };
  return { label: "Weak match", cls: "text-muted-foreground" };
}

export function FitBadge({ score, align = "right" }: { score?: number; align?: "left" | "right" }) {
  const m = matchLabel(score);
  return (
    <span className={cn("flex flex-col leading-tight", align === "right" ? "items-end" : "items-start")}>
      <span className="font-mono text-[15px] font-medium tabular-nums">{score === undefined ? "–" : `${Math.round(score)}%`}</span>
      <span className={cn("text-[11px] font-[510]", m.cls)}>{m.label}</span>
    </span>
  );
}

const HUES = [255, 200, 160, 30, 330, 285, 120, 10];
export function Avatar({ name, size = 28, className }: { name: string; size?: number; className?: string }) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const hue = HUES[h % HUES.length];
  return (
    <span
      className={cn("grid shrink-0 place-items-center rounded-full font-[590] text-white", className)}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.38,
        background: `linear-gradient(135deg, hsl(${hue} 60% 55%), hsl(${(hue + 40) % 360} 55% 38%))`,
      }}
    >
      {initials}
    </span>
  );
}
