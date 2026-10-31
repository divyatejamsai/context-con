"use client";
import { useEffect, useMemo, useState } from "react";
import { Check, Copy, ExternalLink, EyeOff, Flag, MapPin, Pin, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate, ClaimStatus } from "@/lib/types";
import { claimCounts, evidenceStrength, normalizeStatus } from "@/lib/run-state";
import { Stamp, STATUS_LABEL } from "@/components/evidence";

type Filter = "all" | ClaimStatus;

export interface DossierProps {
  candidate: Candidate;
  rank: number;
  pinned: boolean;
  dismissed: boolean;
  draft: string | undefined;
  onDraft: (text: string) => void;
  onPin: () => void;
  onDismiss: () => void;
}

const Section = ({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) => (
  <section className="border-t border-rule px-6 py-5">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h4 className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">{title}</h4>
      {aside}
    </div>
    {children}
  </section>
);

export function Dossier({ candidate: c, rank, pinned, dismissed, draft, onDraft, onPin, onDismiss }: DossierProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [hl, setHl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => setFilter("all"), [c.id]);

  const counts = claimCounts(c);
  const strength = evidenceStrength(c);
  const order = { contradicted: 0, verified: 1, unverifiable: 2 } as const;
  const claims = useMemo(
    () =>
      (c.claims ?? [])
        .map((k) => ({ ...k, status: normalizeStatus(k.status, !!k.source?.endpoint) }))
        .sort((a, b) => order[a.status] - order[b.status]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [c.claims],
  );
  // Footnote numbers follow the ledger order, so [1] in a reason is the first row below.
  const footnote = useMemo(() => new Map(claims.map((k, i) => [k.id, i + 1])), [claims]);
  const shown = filter === "all" ? claims : claims.filter((k) => k.status === filter);
  const text = draft ?? c.outreach_draft ?? "";

  const jump = (id: string) => {
    setFilter("all");
    setHl(id);
    requestAnimationFrame(() => document.getElementById(`claim-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
    setTimeout(() => setHl(null), 1600);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  };

  return (
    <article className={cn("flex flex-col", dismissed && "opacity-70")}>
      <header className="px-6 pb-5 pt-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
              Candidate №{String(rank).padStart(2, "0")} · {c.id}
            </p>
            <h2 className="font-display mt-1 text-[34px] font-medium leading-[1.05] tracking-tight">{c.name}</h2>
            <p className="mt-1.5 text-[15px]">{[c.title, c.company].filter(Boolean).join(" at ") || "Title unknown"}</p>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              {c.location && (
                <span className="inline-flex items-center gap-1">
                  <MapPin className="size-3.5" /> {c.location}
                </span>
              )}
              {c.profile_url && (
                <a href={c.profile_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                  Profile <ExternalLink className="size-3" />
                </a>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="font-display text-5xl font-light leading-none tabular-nums">{c.score ?? "–"}</div>
            <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">fit / 100</div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            onClick={onPin}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition",
              pinned ? "border-foreground bg-foreground text-background" : "border-rule hover:border-foreground",
            )}
          >
            <Pin className="size-3.5" /> {pinned ? "Pinned" : "Pin"} <kbd className="ml-0.5">p</kbd>
          </button>
          <button
            onClick={onDismiss}
            className="inline-flex items-center gap-1.5 rounded-full border border-rule px-3 py-1 text-xs font-medium transition hover:border-foreground"
          >
            {dismissed ? <RotateCcw className="size-3.5" /> : <EyeOff className="size-3.5" />} {dismissed ? "Restore" : "Pass"} <kbd className="ml-0.5">x</kbd>
          </button>
          {(c.flags ?? []).map((f) => (
            <span key={f} className="inline-flex items-center gap-1 rounded-full bg-flag/12 px-2.5 py-1 text-xs font-medium text-flag">
              <Flag className="size-3" /> {f}
            </span>
          ))}
        </div>
      </header>

      <Section title="Why this candidate">
        {c.reasons?.length ? (
          <ol className="flex flex-col gap-2">
            {c.reasons.map((r, i) => (
              <li key={i} className="font-display text-[17px] leading-snug">
                {r.text}
                {r.claim_ids?.map((id) => (
                  <button
                    key={id}
                    onClick={() => jump(id)}
                    title={`Jump to claim ${id}`}
                    className="ml-0.5 align-super font-mono text-[10px] font-medium text-primary hover:underline"
                  >
                    [{footnote.get(id) ?? id}]
                  </button>
                ))}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted-foreground">No ranking reasons yet.</p>
        )}
      </Section>

      <Section
        title={`Evidence ledger · ${strength}% verified`}
        aside={
          <div className="flex gap-0.5 rounded-full border border-rule p-0.5 font-mono text-[10px]">
            {(["all", "contradicted", "verified", "unverifiable"] as Filter[]).map((f) => {
              const n = f === "all" ? counts.total : counts[f];
              if (f !== "all" && !n) return null;
              return (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={cn(
                    "rounded-full px-2 py-0.5 uppercase tracking-wider",
                    filter === f ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {f === "all" ? "All" : STATUS_LABEL[f].slice(0, f === "unverifiable" ? 7 : 20)} {n}
                </button>
              );
            })}
          </div>
        }
      >
        <div className="mb-4 flex h-1.5 overflow-hidden rounded-full bg-muted">
          <span className="bg-verified" style={{ width: `${(counts.verified / (counts.total || 1)) * 100}%` }} />
          <span className="bg-contradicted" style={{ width: `${(counts.contradicted / (counts.total || 1)) * 100}%` }} />
        </div>
        <ol className="flex flex-col">
          {shown.map((k) => (
            <li
              key={k.id}
              id={`claim-${k.id}`}
              className={cn(
                "grid grid-cols-[24px_1fr] gap-x-2 border-b border-dashed border-rule py-3 transition-colors last:border-0",
                hl === k.id && "bg-highlight",
                k.status === "contradicted" && "bg-contradicted/[0.04]",
              )}
            >
              <span className="pt-0.5 text-right font-mono text-[11px] text-muted-foreground">{footnote.get(k.id)}</span>
              <div className="min-w-0">
                <div className="flex items-start justify-between gap-3">
                  <p className={cn("text-[15px] font-medium leading-snug", k.status === "contradicted" && "line-through decoration-contradicted/60")}>
                    {k.claim}
                  </p>
                  <Stamp status={k.status} />
                </div>
                {k.evidence && <p className="mt-1 text-sm text-muted-foreground">{k.evidence}</p>}
                <p className="mt-1.5 flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
                  {k.source?.endpoint ? (
                    <>
                      <span className="text-muted-foreground">src</span>
                      <span className="rounded-sm bg-muted px-1.5 py-px">
                        crustdata/{k.source.endpoint}
                        {k.source.field && <span className="text-muted-foreground"> · {k.source.field}</span>}
                      </span>
                      {k.source.url && (
                        <a href={k.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
                          {new URL(k.source.url, "https://x").hostname.replace(/^www\./, "")} <ExternalLink className="size-3" />
                        </a>
                      )}
                    </>
                  ) : (
                    <span className="text-contradicted">no source returned, so not counted as evidence</span>
                  )}
                </p>
              </div>
            </li>
          ))}
          {!shown.length && <p className="text-sm text-muted-foreground">No claims checked for this candidate.</p>}
        </ol>
      </Section>

      <Section
        title="Outreach draft"
        aside={
          (c.outreach_draft || draft) && (
            <div className="flex items-center gap-2">
              {draft !== undefined && draft !== c.outreach_draft && (
                <button onClick={() => onDraft(c.outreach_draft ?? "")} className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground">
                  Reset
                </button>
              )}
              <button
                onClick={copy}
                className="inline-flex items-center gap-1.5 rounded-full border border-rule px-3 py-1 text-xs font-medium hover:border-foreground"
              >
                {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy"} <kbd>c</kbd>
              </button>
            </div>
          )
        }
      >
        {c.outreach_draft || draft ? (
          <div className="relative">
            <textarea
              value={text}
              onChange={(e) => onDraft(e.target.value)}
              rows={Math.min(14, Math.max(6, text.split("\n").length + 1))}
              className="w-full resize-y rounded-md border border-rule bg-background/60 p-4 font-display text-[15px] leading-relaxed focus:border-foreground focus:outline-none"
              data-outreach
            />
            <span className="pointer-events-none absolute right-3 top-3 rotate-[4deg] rounded-[3px] border-[1.5px] border-primary/60 px-1.5 font-mono text-[9px] uppercase tracking-[0.16em] text-primary/80">
              Draft · not sent
            </span>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No draft. The agent only writes outreach for strong, verified matches.</p>
        )}
      </Section>
    </article>
  );
}
