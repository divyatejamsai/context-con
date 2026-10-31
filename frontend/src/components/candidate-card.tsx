"use client";
import { Building2, ChevronRight, Flag, MapPin } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClaimBadge, normalizeStatus } from "@/components/claim-status";
import type { Candidate, ClaimStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export function countClaims(c: Candidate): Record<ClaimStatus, number> {
  const out = { verified: 0, contradicted: 0, unverifiable: 0 };
  for (const k of c.claims ?? []) out[normalizeStatus(k.status)]++;
  return out;
}

export function ScoreRing({ score, size = 48 }: { score?: number; size?: number }) {
  const s = Math.max(0, Math.min(100, Math.round(score ?? 0)));
  const r = size / 2 - 4;
  const circ = 2 * Math.PI * r;
  const color = s >= 80 ? "var(--verified)" : s >= 60 ? "var(--primary)" : s >= 40 ? "var(--flag)" : "var(--contradicted)";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} aria-label={`Score ${s} of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--muted)" strokeWidth={4} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={4}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - s / 100)}
          style={{ transition: "stroke-dashoffset 600ms ease" }}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-sm font-semibold tabular-nums">{score === undefined ? "–" : s}</span>
    </div>
  );
}

export function CandidateCard({ candidate: c, rank, onOpen }: { candidate: Candidate; rank: number; onOpen: () => void }) {
  const counts = countClaims(c);
  const top = c.reasons?.[0]?.text;
  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen())}
      className={cn(
        "group cursor-pointer p-4 transition hover:border-primary/50 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring animate-rise",
        counts.contradicted > 0 && "border-l-4 border-l-contradicted",
      )}
    >
      <div className="flex items-start gap-3">
        <ScoreRing score={c.score} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="text-xs tabular-nums text-muted-foreground">#{rank}</span>
            <h3 className="truncate font-semibold">{c.name}</h3>
          </div>
          <p className="truncate text-sm text-muted-foreground">
            {[c.title, c.company].filter(Boolean).join(" · ") || "Title unknown"}
          </p>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {c.location && (
              <span className="inline-flex items-center gap-1">
                <MapPin className="size-3" />
                {c.location}
              </span>
            )}
            {c.company && (
              <span className="inline-flex items-center gap-1">
                <Building2 className="size-3" />
                {c.company}
              </span>
            )}
          </div>
        </div>
        <ChevronRight className="size-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5" />
      </div>
      {top && <p className="mt-3 line-clamp-2 text-sm">{top}</p>}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {counts.verified > 0 && <ClaimBadge status="verified" count={counts.verified} />}
        {counts.contradicted > 0 && <ClaimBadge status="contradicted" count={counts.contradicted} />}
        {counts.unverifiable > 0 && <ClaimBadge status="unverifiable" count={counts.unverifiable} />}
        {(c.flags ?? []).map((f) => (
          <Badge key={f} variant="flag">
            <Flag />
            {f}
          </Badge>
        ))}
      </div>
    </Card>
  );
}
