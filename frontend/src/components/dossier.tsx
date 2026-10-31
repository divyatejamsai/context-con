"use client";
import { useEffect, useMemo, useState } from "react";
import { Building2, Check, Copy, ExternalLink, EyeOff, Flag, Link2, MapPin, Pin, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate, ClaimStatus } from "@/lib/types";
import { claimCounts, evidenceStrength, normalizeStatus } from "@/lib/run-state";
import { Avatar, EvidenceStrip, FitBadge, StatusIcon, StatusPill, STATUS_BG, STATUS_LABEL } from "@/components/evidence";

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

const Section = ({ title, tag, aside, children }: { title: string; tag?: string; aside?: React.ReactNode; children: React.ReactNode }) => (
  <section className="border-t-2 border-ink px-5 py-4">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h4 className="font-display flex items-center gap-2 text-[17px] font-extrabold tracking-tight">
        {title}
        {tag && <span className="rounded-full border-2 border-ink bg-panel px-1.5 font-mono text-[11px] font-bold">{tag}</span>}
      </h4>
      {aside}
    </div>
    {children}
  </section>
);

const chip = "press inline-flex h-8 items-center gap-1.5 rounded-lg border-2 border-ink px-2.5 text-[12.5px] font-bold shadow-brut-sm";

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
  // Citation numbers follow the claims list order, so [1] in a reason is the first claim below.
  const cite = useMemo(() => new Map(claims.map((k, i) => [k.id, i + 1])), [claims]);
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
    <article className={cn("flex flex-col", dismissed && "opacity-60")}>
      <header className="relative overflow-hidden bg-yellow px-5 pb-5 pt-5 text-on-color">
        <span className="font-display pointer-events-none absolute -right-3 -top-6 select-none text-[120px] font-extrabold leading-none text-black/10">
          #{rank}
        </span>
        <div className="relative flex items-start gap-3">
          <Avatar name={c.name} size={52} className="shadow-[3px_3px_0_0_#111]" />
          <div className="min-w-0 flex-1">
            <h2 className="font-display truncate text-[28px] font-extrabold leading-[1.05] tracking-[-0.02em]">{c.name}</h2>
            <p className="mt-0.5 truncate text-[14px] font-semibold">{[c.title, c.company].filter(Boolean).join(" @ ") || "Title unknown"}</p>
            <div className="mt-1 flex flex-wrap gap-x-3 text-[12.5px] font-medium">
              {c.location && (
                <span className="inline-flex items-center gap-1">
                  <MapPin className="size-3.5" /> {c.location}
                </span>
              )}
              {c.company && (
                <span className="inline-flex items-center gap-1">
                  <Building2 className="size-3.5" /> {c.company}
                </span>
              )}
            </div>
          </div>
          <FitBadge score={c.score} size="lg" />
        </div>

        <div className="relative mt-4 flex flex-wrap items-center gap-2">
          <button onClick={onPin} className={cn(chip, "border-[#111] shadow-[2px_2px_0_0_#111]", pinned ? "bg-[#111] text-white" : "bg-white text-[#111]")}>
            <Pin className="size-3.5" /> {pinned ? "Pinned" : "Pin"}
          </button>
          <button onClick={onDismiss} className={cn(chip, "border-[#111] bg-white text-[#111] shadow-[2px_2px_0_0_#111]")}>
            {dismissed ? <RotateCcw className="size-3.5" /> : <EyeOff className="size-3.5" />} {dismissed ? "Restore" : "Pass"}
          </button>
          {c.profile_url && (
            <a href={c.profile_url} target="_blank" rel="noreferrer" className={cn(chip, "border-[#111] bg-white text-[#111] shadow-[2px_2px_0_0_#111]")}>
              Profile <ExternalLink className="size-3" />
            </a>
          )}
          {(c.flags ?? []).map((f) => (
            <span key={f} className="inline-flex h-8 -rotate-1 items-center gap-1 rounded-lg border-2 border-[#111] bg-coral px-2 text-[12px] font-bold text-[#111]">
              <Flag className="size-3.5" /> {f}
            </span>
          ))}
        </div>
      </header>

      <div className="grid grid-cols-3 border-t-2 border-ink">
        {[
          ["Evidence", `${strength}%`, "verified"],
          ["Claims", String(counts.total), "checked"],
          ["Contradicted", String(counts.contradicted), counts.contradicted ? "found" : "none"],
        ].map(([k, v, sub], i) => (
          <div key={k} className={cn("px-4 py-3", i > 0 && "border-l-2 border-ink", i === 2 && counts.contradicted > 0 && "bg-coral text-on-color")}>
            <div className="text-[11px] font-bold uppercase tracking-wider opacity-70">{k}</div>
            <div className="font-display text-[26px] font-extrabold leading-tight tabular-nums">{v}</div>
            <div className="text-[11px] font-medium opacity-70">{sub}</div>
          </div>
        ))}
      </div>

      <Section title="Why them">
        {c.reasons?.length ? (
          <ul className="flex flex-col gap-2">
            {c.reasons.map((r, i) => (
              <li key={i} className="flex gap-2.5 text-[14px] leading-relaxed">
                <span className="mt-[7px] size-2 shrink-0 rotate-45 border-[1.5px] border-ink bg-yellow" />
                <span>
                  {r.text}
                  {r.claim_ids?.map((id) => (
                    <button
                      key={id}
                      onClick={() => jump(id)}
                      title={`Show claim ${id}`}
                      className="ml-1 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-full border-[1.5px] border-ink bg-lavender px-1 font-mono text-[10px] font-bold text-on-color transition hover:-translate-y-0.5"
                    >
                      {cite.get(id) ?? id}
                    </button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-faint">No ranking reasons yet.</p>
        )}
      </Section>

      <Section
        title="Receipts"
        tag={String(counts.total)}
        aside={
          <div className="flex flex-wrap gap-1">
            {(["all", "contradicted", "verified", "unverifiable"] as Filter[]).map((f) => {
              const n = f === "all" ? counts.total : counts[f];
              if (f !== "all" && !n) return null;
              const on = filter === f;
              return (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={cn(
                    "inline-flex h-7 items-center gap-1 rounded-full border-2 border-ink px-2 text-[11px] font-bold transition",
                    on ? (f === "all" ? "bg-ink text-background" : cn(STATUS_BG[f], f === "unverifiable" ? "text-foreground" : "text-on-color")) : "bg-panel hover:bg-hover",
                  )}
                >
                  {f === "all" ? "All" : STATUS_LABEL[f]} <span className="font-mono">{n}</span>
                </button>
              );
            })}
          </div>
        }
      >
        <EvidenceStrip candidate={c} className="mb-3 h-4" />
        <ol className="flex flex-col gap-2.5">
          {shown.map((k) => (
            <li
              key={k.id}
              id={`claim-${k.id}`}
              className={cn(
                "relative rounded-lg border-2 border-ink bg-panel p-3 shadow-brut-sm transition-all",
                k.status === "contradicted" && "bg-coral/15",
                hl === k.id && "-translate-x-0.5 -translate-y-0.5 bg-lavender/40 shadow-brut",
              )}
            >
              <div className="flex items-start gap-2.5">
                <span className="font-display grid size-6 shrink-0 place-items-center rounded-md border-2 border-ink bg-background text-[12px] font-extrabold tabular-nums">
                  {cite.get(k.id)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <p className={cn("text-[14px] font-bold leading-snug", k.status === "contradicted" && "decoration-contradicted decoration-2 line-through")}>{k.claim}</p>
                    <StatusPill status={k.status} />
                  </div>
                  {k.evidence && <p className="mt-1 text-[13px] leading-relaxed text-secondary">{k.evidence}</p>}
                  <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                    {k.source?.endpoint ? (
                      <>
                        <span className="inline-flex items-center gap-1 rounded-md border-[1.5px] border-ink bg-sky px-1.5 py-0.5 font-mono font-semibold text-on-color">
                          <Link2 className="size-3" />
                          crustdata/{k.source.endpoint}
                          {k.source.field && <span className="opacity-70">.{k.source.field}</span>}
                        </span>
                        {k.source.url && (
                          <a href={k.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 font-semibold underline decoration-2 underline-offset-2">
                            {safeHost(k.source.url)} <ExternalLink className="size-3" />
                          </a>
                        )}
                      </>
                    ) : (
                      <span className="inline-flex items-center gap-1 font-semibold text-contradicted">
                        <StatusIcon status="unverifiable" /> No source returned, so it doesn&apos;t count as evidence
                      </span>
                    )}
                  </p>
                </div>
              </div>
            </li>
          ))}
          {!shown.length && <p className="text-[13px] text-faint">No claims checked for this candidate.</p>}
        </ol>
      </Section>

      <Section
        title="Outreach"
        aside={
          (c.outreach_draft || draft) && (
            <div className="flex items-center gap-2">
              {draft !== undefined && draft !== c.outreach_draft && (
                <button onClick={() => onDraft(c.outreach_draft ?? "")} className="text-[12px] font-bold underline decoration-2 underline-offset-2">
                  Reset
                </button>
              )}
              <button onClick={copy} className={cn(chip, "h-7 bg-lime text-on-color")}>
                {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} {copied ? "Copied!" : "Copy"} <kbd>C</kbd>
              </button>
            </div>
          )
        }
      >
        {c.outreach_draft || draft ? (
          <div className="relative rounded-lg border-2 border-ink bg-panel shadow-brut">
            <div className="flex items-center justify-between border-b-2 border-ink px-3 py-2 text-[12.5px]">
              <span>
                <span className="font-bold">To:</span> {c.name}
              </span>
              <span className="rotate-2 rounded-md border-2 border-ink bg-yellow px-1.5 text-[10.5px] font-extrabold uppercase tracking-wider text-on-color">
                Draft · not sent
              </span>
            </div>
            <textarea
              value={text}
              onChange={(e) => onDraft(e.target.value)}
              rows={Math.min(14, Math.max(6, text.split("\n").length + 1))}
              className="w-full resize-y bg-transparent px-3 py-2.5 text-[14px] leading-relaxed focus:outline-none"
            />
          </div>
        ) : (
          <p className="rounded-lg border-2 border-dashed border-ink/50 p-3 text-[13px] text-muted-foreground">
            No draft. The agent only writes outreach for strong, verified matches.
          </p>
        )}
      </Section>
    </article>
  );
}

function safeHost(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "link";
  }
}
