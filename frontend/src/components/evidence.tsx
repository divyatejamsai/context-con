import { Check, HelpCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate, ClaimStatus } from "@/lib/types";
import { normalizeStatus } from "@/lib/run-state";

export const STATUS_LABEL: Record<ClaimStatus, string> = {
  verified: "Verified",
  contradicted: "Contradicted",
  unverifiable: "Unverifiable",
};

const ICON = { verified: Check, contradicted: X, unverifiable: HelpCircle } as const;
export const STATUS_BG: Record<ClaimStatus, string> = {
  verified: "bg-lime",
  contradicted: "bg-coral",
  unverifiable: "bg-elevated",
};

export function StatusIcon({ status, className }: { status: ClaimStatus; className?: string }) {
  const I = ICON[status];
  return (
    <span className={cn("grid size-4 shrink-0 place-items-center rounded-full border-[1.5px] border-ink text-on-color", STATUS_BG[status], status === "unverifiable" && "text-foreground", className)}>
      <I className="size-2.5" strokeWidth={3.5} aria-label={STATUS_LABEL[status]} />
    </span>
  );
}

export function StatusPill({ status, count, className }: { status: ClaimStatus; count?: number; className?: string }) {
  const I = ICON[status];
  return (
    <span
      className={cn(
        "inline-flex h-[22px] shrink-0 items-center gap-1 rounded-full border-[1.5px] border-ink px-2 text-[11px] font-semibold",
        STATUS_BG[status],
        status === "unverifiable" ? "text-foreground" : "text-on-color",
        className,
      )}
    >
      <I className="size-3" strokeWidth={3.5} />
      {count !== undefined ? count : STATUS_LABEL[status]}
    </span>
  );
}

/** One block per claim, contradicted first: the record's trustworthiness at a glance. */
export function EvidenceStrip({ candidate, className }: { candidate: Candidate; className?: string }) {
  const order = { contradicted: 0, verified: 1, unverifiable: 2 } as const;
  const statuses = (candidate.claims ?? [])
    .map((k) => normalizeStatus(k.status, !!k.source?.endpoint))
    .sort((a, b) => order[a] - order[b]);
  if (!statuses.length) return <span className="text-[11px] text-faint">no claims</span>;
  return (
    <span className={cn("inline-flex h-3.5 overflow-hidden rounded-[3px] border-[1.5px] border-ink", className)} aria-label={`${statuses.length} claims`}>
      {statuses.map((s, i) => (
        <span key={i} className={cn("w-2.5", STATUS_BG[s], i > 0 && "border-l-[1.5px] border-ink")} title={STATUS_LABEL[s]} />
      ))}
    </span>
  );
}

export function matchLabel(score?: number): { label: string; bg: string; cls: string } {
  if (score === undefined) return { label: "Scoring", bg: "bg-elevated", cls: "text-faint" };
  if (score >= 85) return { label: "Strong", bg: "bg-lime", cls: "text-verified" };
  if (score >= 70) return { label: "Good", bg: "bg-sky", cls: "text-foreground" };
  if (score >= 50) return { label: "Partial", bg: "bg-yellow", cls: "text-flag" };
  return { label: "Weak", bg: "bg-elevated", cls: "text-muted-foreground" };
}

export function FitBadge({ score, size = "md" }: { score?: number; size?: "md" | "lg" }) {
  const m = matchLabel(score);
  return (
    <span
      className={cn(
        "flex shrink-0 flex-col items-center justify-center rounded-lg border-[1.5px] border-ink text-on-color shadow-brut-sm",
        m.bg,
        score === undefined && "text-foreground",
        size === "lg" ? "h-[68px] w-[76px]" : "h-[52px] w-[60px]",
      )}
    >
      <span className={cn("font-display font-bold leading-none tabular-nums", size === "lg" ? "text-[30px]" : "text-[22px]")}>
        {score === undefined ? "–" : Math.round(score)}
      </span>
      <span className="mt-0.5 text-[9.5px] font-semibold uppercase tracking-[0.08em]">{m.label}</span>
    </span>
  );
}

const SWATCH = ["bg-yellow", "bg-lime", "bg-lavender", "bg-sky", "bg-pink", "bg-coral"];
export function Avatar({ name, size = 28, className }: { name: string; size?: number; className?: string }) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return (
    <span
      className={cn("font-display grid shrink-0 place-items-center rounded-full border-[1.5px] border-ink font-bold text-on-color", SWATCH[h % SWATCH.length], className)}
      style={{ width: size, height: size, fontSize: size * 0.4 }}
    >
      {initials}
    </span>
  );
}
